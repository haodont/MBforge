"""MBForge logging configuration and structured diagnostics.

Sets up console, rotating file, and in-memory ring-buffer handlers.
Exposes ``get_logger`` for module-level loggers, decorators for call
tracing, and helpers for pushing diagnostic records consumed by the
``/api/v1/diagnostics`` endpoints.
"""

from __future__ import annotations

import collections
import contextlib
import contextvars
import functools
import inspect
import json
import logging
import os
import sys
import threading
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from .paths import APP_NAME, GLOBAL_APP_DIR

# 日志格式 —— 增加进程ID、线程名，方便多线程/多进程诊断
_CONSOLE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(process)d:%(threadName)s | %(name)s | %(message)s"
)
_FILE_FORMAT = (
    "%(asctime)s | %(levelname)s | %(process)d:%(threadName)s | %(name)s | "
    "%(funcName)s:%(lineno)d | %(message)s"
)

_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class GuardedStreamHandler(logging.StreamHandler):
    """StreamHandler that survives the stream being closed mid-session.

    Background: ``sys.stdout`` (or any attached stream) can be closed
    after ``setup_logging`` has already attached the handler — e.g.
    when a third-party model package resets or
    closes stdout during import, or under ``uv run`` on Windows where
    child-process stdio teardown is non-deterministic. Without this
    guard, the next ``log.info()`` raises
    ``ValueError: I/O operation on closed file`` inside
    ``StreamHandler.emit`` and bubbles through ``handleError`` →
    ``sys.stderr.write`` (which itself fails when stderr is also
    dead) → caller crash with a confusing "during handling of the
    above exception" traceback.

    Behavior on emit failure: silently discard. We deliberately do NOT
    call ``self.handleError(record)`` because that path tries to write
    a traceback to ``sys.stderr``, and in the failure mode we're
    designed for stderr is often the *same* closed stream. The
    observability trail (diagnostic ring buffer, file handler) is
    unaffected. This is a log-output degradation, not a log-content
    loss: ring-buffer + file handlers still capture every record.
    """

    def emit(self, record: logging.LogRecord) -> None:
        with contextlib.suppress(ValueError, OSError, AttributeError):
            super().emit(record)
            # Stream is closed / unwritable / torn down. Drop the
            # record on the floor for THIS handler. Other handlers
            # (file, diagnostic ring) are independent and unaffected.


class UvicornAccessLogFilter(logging.Filter):
    """Keep non-success access records while suppressing routine 2xx noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        status_code = getattr(record, "status_code", None)
        if status_code is None and isinstance(record.args, tuple):
            # Uvicorn 0.47 formats access logs as
            # (client, method, path, http_version, status_code).
            candidate = record.args[-1] if record.args else None
            if isinstance(candidate, int):
                status_code = candidate
        return not (isinstance(status_code, int) and 200 <= status_code < 300)


def configure_uvicorn_access_logging() -> None:
    """Suppress successful Uvicorn access logs without hiding failures.

    Uvicorn owns a dedicated ``uvicorn.access`` handler. Install the filter on
    both the logger and its handlers so later logging configuration cannot
    bypass it by routing records directly through the handler.
    """
    access_logger = logging.getLogger("uvicorn.access")
    access_filter = next(
        (
            item
            for item in access_logger.filters
            if isinstance(item, UvicornAccessLogFilter)
        ),
        None,
    )
    if access_filter is None:
        access_filter = UvicornAccessLogFilter()
        access_logger.addFilter(access_filter)

    for handler in access_logger.handlers:
        if not any(
            isinstance(item, UvicornAccessLogFilter) for item in handler.filters
        ):
            handler.addFilter(access_filter)


_logger_initialized = False
_log_level: int = logging.INFO

_ERROR_ONLY_LOGGER_PREFIXES = (
    "mbforge.pipeline.stages.extract",
    "mbforge.pipeline.stages.molecule_detection",
    "mbforge.pipeline.extract.text",
    "mbforge.pipeline.detection",
    "mbforge.pipeline.artifacts",
    "mbforge.backends.ocr",
    "mbforge.backends.moldet_v2_ft",
)

# ---- 诊断环形缓冲 + 请求路径上下文 ----
# 容量 500 条，覆盖典型会话的错误风暴;GET 端支持 ?since= 增量分页。
_RING_CAPACITY = 500
_diagnostic_buffer: collections.deque[dict[str, Any]] = collections.deque(
    maxlen=_RING_CAPACITY
)
_diagnostic_lock = threading.Lock()
_diagnostic_seq = 0
# FastAPI 中间件在每个请求的 context 里 set; 日志格式化器读它。
_request_path_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "mbforge_request_path", default="-"
)
# 全链路追踪上下文: doc_id。由 pipeline 运行器等长任务
# 设置, 使同一次运行的日志在环形缓冲和 JSON 文件中可被关联查询。
_trace_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mbforge_trace", default=None
)


def setup_logging(
    level: int = logging.INFO,
    log_dir: Path | None = None,
    console: bool = True,
    file: bool = True,
    *,
    json_mode: bool = False,
) -> None:
    """配置全局日志.

    Args:
        level: 日志级别 (logging.DEBUG/INFO/WARNING/ERROR)
        log_dir: 日志文件目录，默认 ~/MBForge/logs
        console: 是否输出到控制台
        file: 是否输出到文件
        json_mode: 文件输出用 JSON 行格式 (结构化聚合; 默认关闭, 沿用人类可读)
    """
    global _logger_initialized, _log_level
    if _logger_initialized:
        # 允许动态调整级别
        root = logging.getLogger()
        root.setLevel(level)
        for h in root.handlers:
            h.setLevel(level)
        for logger_name in _ERROR_ONLY_LOGGER_PREFIXES:
            logging.getLogger(logger_name).setLevel(logging.ERROR)
        _log_level = level
        return

    _log_level = level
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # 清除已有 handler，避免重复
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 控制台输出
    if console:
        # sys.stdout 可能已关闭 (例如 uv run + Windows + Python 3.12 在
        # 导入阶段就会触发此情况)。先把 stdout 不可用的情况关掉, 避免
        # 后续 StreamHandler.emit 在首次 info() 调用时崩。
        console_stream = sys.stdout
        stdout_closed = (
            getattr(console_stream, "closed", False)
            or not getattr(console_stream, "writable", lambda: True)()
        )
        if stdout_closed:
            console = False  # 跳过 console handler;后续日志走 file/ring buffer
        else:
            # Windows zh-CN locale 下 sys.stdout.encoding 可能是 gbk，无法编码 ✓/✗
            # 这类 Unicode 字符。早期实现是包一层 ``io.TextIOWrapper(
            # sys.stdout.buffer, encoding='utf-8')``, 但 TextIOWrapper.__del__
            # 会关掉借来的 buffer, 一旦 wrapper 被孤立 GC, sys.stdout 也跟着死
            # (uv run / 子进程启动场景的非确定性崩溃)。改用 ``reconfigure``:
            # 原地改 TextIOWrapper 的编码字段, 不创建新对象, 不接管 buffer,
            # 因此不会引入 wrapper-GC 路径。副作用是用户进程的 sys.stdout
            # 编码从此变 utf-8 — 但调用 setup_logging 本就是显式接管控制台
            # 输出的入口, 改编码是预期行为。

            with contextlib.suppress(AttributeError, ValueError, OSError):
                console_stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
            console_handler = GuardedStreamHandler(console_stream)
            console_handler.setLevel(level)
            console_handler.setFormatter(
                logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT)
            )
            root_logger.addHandler(console_handler)

    # 文件输出
    if file:
        log_dir = log_dir or (GLOBAL_APP_DIR / "logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{APP_NAME.lower()}.log"

        try:
            from logging.handlers import RotatingFileHandler

            class _SafeRotatingFileHandler(RotatingFileHandler):
                """RotatingFileHandler that tolerates rename failures on Windows.

                On Windows, os.rename() can fail with PermissionError when the
                log file is locked by another process (e.g., a zombie worker).
                Instead of crashing the logger, we skip the rollover and keep
                appending to the current file.
                """

                def rotate(self, source, dest):
                    # File is locked — skip rollover this time. The current
                    # log will continue growing until the next rotation check.
                    with contextlib.suppress(PermissionError):
                        super().rotate(source, dest)

            file_handler = _SafeRotatingFileHandler(
                log_file,
                maxBytes=20 * 1024 * 1024,  # 20 MB
                backupCount=10,
                encoding="utf-8",
                delay=True,  # Delay opening the file until first write to avoid Windows lock issues
            )
            file_handler.setLevel(level)
            if json_mode:
                file_handler.setFormatter(JsonFormatter())
            else:
                file_handler.setFormatter(
                    logging.Formatter(_FILE_FORMAT, datefmt=_DATE_FORMAT)
                )
            root_logger.addHandler(file_handler)
        except Exception as e:
            # 文件日志初始化失败不影响运行，但要打一条控制台日志
            fallback = GuardedStreamHandler(sys.stderr)
            fallback.setFormatter(
                logging.Formatter(_CONSOLE_FORMAT, datefmt=_DATE_FORMAT)
            )
            root_logger.addHandler(fallback)
            root_logger.error(f"Failed to initialize file logging: {e}")

    # 诊断环形缓冲始终挂到 root logger;记录所有 DEBUG+ 信息,
    # 但只有被 mbforge_exception_handler 显式提升的 LogRecord 会带
    # error_code/severity/category 字段。
    root_logger.addHandler(DiagnosticRingHandler(level=logging.DEBUG))

    _logger_initialized = True
    for logger_name in _ERROR_ONLY_LOGGER_PREFIXES:
        logging.getLogger(logger_name).setLevel(logging.ERROR)
    root_logger.info(
        f"Logging initialized | level={logging.getLevelName(level)} | "
        f"directory={log_dir} | json={json_mode}"
    )


def get_logger(name: str) -> logging.Logger:
    """获取命名日志器.

    如果全局日志尚未初始化，会自动执行默认初始化。
    """
    if not _logger_initialized:
        # 支持通过环境变量 MBFORGE_LOG_LEVEL 控制初始级别
        env_level = os.environ.get("MBFORGE_LOG_LEVEL", "INFO").upper()
        level = getattr(logging, env_level, logging.INFO)
        setup_logging(level=level)
    return logging.getLogger(name)


# ---------- 诊断工具 ----------

T = TypeVar("T")


def log_call(
    level: int = logging.DEBUG,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """装饰器：自动记录函数进入/退出及耗时.

    用法:
        @log_call()
        def my_func(x, y):
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = f"{func.__module__}.{func.__qualname__}"
        func_logger = get_logger(func.__module__)

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # 构建参数摘要（避免记录过大对象）
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            args_summary = []
            for k, v in bound.arguments.items():
                if k in ("self", "cls"):
                    continue
                rep = repr(v)
                if len(rep) > 80:
                    rep = rep[:77] + "..."
                args_summary.append(f"{k}={rep}")
            args_str = ", ".join(args_summary)

            func_logger.log(level, f"[CALL] → {func_name}({args_str})")
            import time

            t0 = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.perf_counter() - t0) * 1000
                func_logger.log(level, f"[OK]   ← {func_name} | {elapsed:.1f}ms")
                return result
            except Exception as e:
                elapsed = (time.perf_counter() - t0) * 1000
                func_logger.log(
                    logging.ERROR,
                    f"[ERR]  ← {func_name} | {elapsed:.1f}ms | {type(e).__name__}: {e}",
                )
                raise

        return wrapper

    return decorator


def log_exception(logger: logging.Logger, msg: str = "") -> None:
    """记录当前异常及完整堆栈.

    用法:
        try:
            ...
        except Exception:
            log_exception(logger, "PDF渲染失败")
    """
    exc_text = traceback.format_exc()
    prefix = f"{msg} | " if msg else ""
    logger.error(f"{prefix}Exception details:\n{exc_text}")


# ---------- 诊断：JSON 格式化器 + 内存环形缓冲 ----------


def set_request_path(path: str) -> contextvars.Token:
    """由 FastAPI 中间件调用, 把当前请求路径写入 ContextVar.

    返回 token 供 `reset()` 清理; 中间件 try/finally 用。
    """
    return _request_path_var.set(path)


def reset_request_path(token: contextvars.Token) -> None:
    _request_path_var.reset(token)


class JsonFormatter(logging.Formatter):
    """单行 JSON 格式 — 适合 Loki/ELK/grep 聚合.

    输出字段:
        ts: ISO8601 UTC 时间戳 (毫秒精度)
        level: 大写级别字符串 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
        logger: logger 名 (通常即 __name__)
        message: 格式化后的消息
        exception: 完整堆栈文本, 没有异常时为 None
        pid / tid: 进程与线程标识
        mbforge_error_code / mbforge_status_code / mbforge_severity /
        mbforge_category / mbforge_context: 由异常处理器显式设置,
            普通日志记录时为 None
        request_path: 当前请求路径, 由 request_path middleware 注入
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: A003 — stdlib API
        ts = (
            datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S")
            + f".{int(record.msecs):03d}Z"
        )
        payload: dict[str, Any] = {
            "ts": ts,
            "level": logging.getLevelName(record.levelno),
            "logger": record.name,
            "pid": record.process,
            "tid": record.threadName,
            "message": record.getMessage(),
            "exception": self.formatException(record.exc_info)
            if record.exc_info
            else None,
            "error_code": getattr(record, "mbforge_error_code", None),
            "status_code": getattr(record, "mbforge_status_code", None),
            "severity": getattr(record, "mbforge_severity", None),
            "category": getattr(record, "mbforge_category", None),
            "context": getattr(record, "mbforge_context", None),
            "request_path": _request_path_var.get(),
            **_current_trace(),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


def _record_to_diagnostic(record: logging.LogRecord) -> dict[str, Any]:
    """把 LogRecord 转换为环形缓冲里存储的 dict."""
    ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
    return {
        "ts": ts,
        "level": logging.getLevelName(record.levelno),
        "logger": record.name,
        "message": record.getMessage(),
        "exception": record.__dict__.get("mbforge_exception_text")
        or (
            "".join(traceback.format_exception(*record.exc_info))
            if record.exc_info
            else None
        ),
        "error_code": getattr(record, "mbforge_error_code", None),
        "status_code": getattr(record, "mbforge_status_code", None),
        "severity": getattr(record, "mbforge_severity", None),
        "category": getattr(record, "mbforge_category", None),
        "context": getattr(record, "mbforge_context", None),
        "request_path": _request_path_var.get(),
        **_current_trace(),
    }


class DiagnosticRingHandler(logging.Handler):
    """把每条 LogRecord 推入线程安全的内存环形缓冲.

    由 setup_logging() 在初始化时挂到 root logger。被 MBForge 异常处理器
    升级的 LogRecord 会带 mbforge_* 属性, 落进环形缓冲时即附加分类信息;
    普通 logger.info/error 调用产生的记录不携带业务字段, 仅按 level/logger
    落缓冲供调试。

    emit() 中捕获所有异常避免打断日志链路 (logging.Handler.handleError 默认
    调用 sys.stderr, 这里静默更稳妥)。
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401, A003
        try:
            global _diagnostic_seq
            payload = _record_to_diagnostic(record)
            with _diagnostic_lock:
                _diagnostic_seq += 1
                payload["seq"] = _diagnostic_seq
                _diagnostic_buffer.append(payload)
        except Exception:
            # 永远不要让日志缓冲把日志链路打断
            pass


def push_diagnostic(payload: dict[str, Any]) -> int:
    """外部 (例如前端 POST /api/v1/diagnostics/errors 处理器) 直接入环形缓冲.

    返回分配的 seq; payload 中可被忽略的字段在写入前不会被改写 (允许调用方
    自填 category='client' 等标签)。
    """
    global _diagnostic_seq
    with _diagnostic_lock:
        _diagnostic_seq += 1
        record = dict(payload)
        record.setdefault("ts", datetime.now(tz=UTC).isoformat())
        record["seq"] = _diagnostic_seq
        seq = _diagnostic_seq
        _diagnostic_buffer.append(record)
    return seq


def get_diagnostics(
    *,
    since: int | None = None,
    level: str | None = None,
    category: str | None = None,
    error_code: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """读取环形缓冲快照 + 过滤.

    Args:
        since: 只返回 seq > since 的记录 (增量分页)
        level: 严格匹配 (大写)
        category: 严格匹配
        error_code: 严格匹配
        limit: 上限 (默认 200, 服务端硬上限 1000)
    """
    limit = min(max(limit, 1), 1000)
    level_up = level.upper() if level else None

    with _diagnostic_lock:
        snapshot = list(_diagnostic_buffer)

    out: list[dict[str, Any]] = []
    # Newest-first: the ring buffer evicts the oldest entries, and callers
    # (error list, export snapshot) want the most recent records. Reversed
    # iteration also keeps incremental `since` polls focused on fresh data.
    for rec in reversed(snapshot):
        if since is not None and rec.get("seq", 0) <= since:
            continue
        if level_up and rec.get("level") != level_up:
            continue
        if category and rec.get("category") != category:
            continue
        if error_code and rec.get("error_code") != error_code:
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def get_diagnostic_by_id(seq_id: int) -> dict[str, Any] | None:
    with _diagnostic_lock:
        snapshot = list(_diagnostic_buffer)
    for rec in snapshot:
        if rec.get("seq") == seq_id:
            return rec
    return None


def get_diagnostic_stats() -> dict[str, Any]:
    """聚合统计 — 供 /api/v1/diagnostics/stats 端点."""
    with _diagnostic_lock:
        snapshot = list(_diagnostic_buffer)

    by_level: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_error_code: dict[str, int] = {}
    last_seen: str | None = None
    for rec in snapshot:
        lvl = rec.get("level")
        if lvl:
            by_level[lvl] = by_level.get(lvl, 0) + 1
        cat = rec.get("category")
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1
        ec = rec.get("error_code")
        if ec:
            by_error_code[ec] = by_error_code.get(ec, 0) + 1
        ts = rec.get("ts")
        if ts and (last_seen is None or ts > last_seen):
            last_seen = ts

    return {
        "total": len(snapshot),
        "capacity": _RING_CAPACITY,
        "by_level": by_level,
        "by_category": by_category,
        "by_error_code": by_error_code,
        "last_seen": last_seen,
        "now": datetime.now(tz=UTC).isoformat(),
    }


def set_trace(*, doc_id: str | None = None) -> contextvars.Token:
    """设置当前上下文的文档标识 (doc_id)。

    返回 token 供 `reset_trace()` 在 finally 中还原。
    """
    return _trace_var.set(doc_id)


def reset_trace(token: contextvars.Token) -> None:
    _trace_var.reset(token)


def _current_trace() -> dict[str, str | None]:
    """返回当前追踪标识字段 (缺失时为 None)。"""
    return {"doc_id": _trace_var.get()}
