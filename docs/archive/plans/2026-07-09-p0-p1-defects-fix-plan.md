# P0 + P1 缺陷修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成缺陷报告中的 P0 止血项 + P1 本月项，使测试覆盖、性能体验、代码质量、安全基线达到可持续迭代水平。

**Architecture:** 前端修复配置 + 错误处理；后端实现模型预热、路由冒烟测试、Ruff lint 清零、SSE 可恢复、API key 脱敏、异步 GPU 探测、Agent 流错误分类。

**Tech Stack:** Python 3.12, FastAPI, pytest, ruff, TypeScript/Vite, vitest.

## Global Constraints

- 使用 `uv run` 执行 Python 命令，使用 `npm --prefix frontend` 执行前端命令。
- 不修改现有 API 契约；所有改动必须向后兼容。
- 模型预热异常必须被捕获，不能阻塞服务启动。
- 测试不能写入真实用户 `settings.json`（已有 `conftest.py` 保障）。
- 冒烟测试不依赖真实模型/外部网络。
- 每个子任务独立 commit，便于单独 revert。
- `ruff check src/mbforge` 最终必须 0 errors。

---

## Task 1: 修复 `frontend/tsconfig.json` 的 `"noCheck"` ✅

**Files:**
- Modify: `frontend/tsconfig.json:13`

**Interfaces:**
- Produces: 合法的 `tsconfig.json`（`skipLibCheck` 保留）。

- [x] Step 1: 删除 `"noCheck": true` 行。
- [x] Step 2: 验证 `cd frontend && npx tsc --noEmit`（暴露 baseline 类型错误，允许）。
- [x] Step 3: Commit。

**Status:** 已在 commit `0523ed2` 完成，task review 通过。

---

## Task 2: 模型后台预热

**Files:**
- Modify: `src/mbforge/server.py:46-47`
- Modify: `src/mbforge/app.py:39-42`
- Create: `tests/unit/test_server_prewarm.py`

**Interfaces:**
- Consumes: `mbforge.backends.moldet_v2_ft.get_moldet_ft()`, `mbforge.backends.molscribe.load`.
- Produces: `_prewarm()` 在 `server.py` 实现并在 `app.py:lifespan` 后台调用；失败被捕获并记录 warning。

- [ ] **Step 1: 实现 `_prewarm()`**

Replace:
```python
def _prewarm() -> None:
    pass  # MolDet/MolScribe are lazy-loaded on first use
```

With:
```python
def _prewarm() -> None:
    """Prewarm local model backends in the background.

    Runs inside lifespan via loop.run_in_executor so startup is not blocked.
    Failures are logged as warnings and do not prevent the app from starting.
    """
    try:
        logger.info("Prewarming MolDet...")
        from .backends.moldet_v2_ft import get_moldet_ft
        get_moldet_ft()
    except Exception as e:
        logger.warning("MolDet prewarm failed (non-fatal): %s", e)

    try:
        logger.info("Prewarming MolScribe...")
        from .backends.molscribe import load as load_molscribe
        load_molscribe()
    except Exception as e:
        logger.warning("MolScribe prewarm failed (non-fatal): %s", e)

    logger.info("Model prewarm complete")
```

- [ ] **Step 2: 在 `app.py` lifespan 中调用 `_prewarm()`**

Change:
```python
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, check_environment)
    try:
        yield
```

To:
```python
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, check_environment)
    from .server import _prewarm
    loop.run_in_executor(None, _prewarm)
    try:
        yield
```

- [ ] **Step 3: 编写测试**

Create `tests/unit/test_server_prewarm.py`:
```python
"""Tests for server.py model prewarm."""
from unittest.mock import patch
from mbforge.server import _prewarm


class TestPrewarm:
    def test_prewarm_calls_moldet_and_molscribe(self):
        with (
            patch("mbforge.server.get_moldet_ft") as mock_moldet,
            patch("mbforge.server.load_molscribe") as mock_molscribe,
        ):
            _prewarm()
        mock_moldet.assert_called_once()
        mock_molscribe.assert_called_once()

    def test_prewarm_continues_after_moldet_failure(self):
        with (
            patch("mbforge.server.get_moldet_ft") as mock_moldet,
            patch("mbforge.server.load_molscribe") as mock_molscribe,
        ):
            mock_moldet.side_effect = RuntimeError("model not found")
            _prewarm()
        mock_moldet.assert_called_once()
        mock_molscribe.assert_called_once()

    def test_prewarm_continues_after_molscribe_failure(self):
        with (
            patch("mbforge.server.get_moldet_ft") as mock_moldet,
            patch("mbforge.server.load_molscribe") as mock_molscribe,
        ):
            mock_molscribe.side_effect = RuntimeError("model not found")
            _prewarm()
        mock_moldet.assert_called_once()
        mock_molscribe.assert_called_once()
```

- [ ] **Step 4: 验证**

Run: `uv run pytest tests/unit/test_server_prewarm.py -v`
Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/server.py src/mbforge/app.py tests/unit/test_server_prewarm.py
git commit -m "feat(server): background prewarm for MolDet and MolScribe

- _prewarm triggers lazy model loading in lifespan executor
- app.py lifespan calls _prewarm because mounted server.py lifespan is not run
- Failures are non-fatal and logged as warnings"
```

---

## Task 3: 扩展路由冒烟测试

**Files:**
- Modify: `tests/unit/test_routers_smoke.py`

**Interfaces:**
- Consumes: `mbforge.app.create_app()`。
- Produces: 19 个 include_router + model_server 的冒烟测试。

- [ ] **Step 1: 追加缺失 router 的测试类**

Append to `tests/unit/test_routers_smoke.py`:
```python
class TestDocumentsEndpoints:
    def test_doc_list_empty(self, tmp_path):
        c = _client()
        r = c.post("/api/v1/documents/list", json={"library_root": str(tmp_path)})
        assert r.status_code == 200
        assert r.json().get("success") is True
        assert r.json()["documents"] == []

    def test_doc_delete_missing_doc_id(self, tmp_path):
        c = _client()
        r = c.post("/api/v1/documents/delete", json={"library_root": str(tmp_path)})
        assert r.status_code == 200
        assert r.json().get("success") is False


class TestCorefEndpoints:
    def test_figure_labels_missing_params(self):
        c = _client()
        r = c.post("/api/v1/coref/figure-labels", json={})
        assert r.status_code == 422

    def test_predictions_missing_params(self):
        c = _client()
        r = c.post("/api/v1/coref/predictions", json={})
        assert r.status_code == 422


class TestSarEndpoints:
    def test_find_scaffold(self):
        c = _client()
        r = c.post("/api/v1/sar/find-scaffold", json={"smiles": "CCO"})
        assert r.status_code == 200

    def test_decompose_missing_smiles(self):
        c = _client()
        r = c.post("/api/v1/sar/decompose", json={})
        assert r.status_code == 200


class TestOcrEndpoints:
    def test_chain_status(self):
        c = _client()
        r = c.get("/api/v1/ocr/chain-status")
        assert r.status_code == 200
        assert "backends" in r.json()

    def test_uniparser_stub(self):
        c = _client()
        r = c.post("/api/v1/ocr/test-uniparser", json={})
        assert r.status_code == 200
        assert r.json()["ok"] is False


class TestPdfEndpoints:
    def test_classify_pdf(self):
        c = _client()
        r = c.post("/api/v1/pdf/classify", json={"path": ""})
        assert r.status_code == 200
        assert "pdf_type" in r.json()

    def test_inspect_pdf_missing_body(self):
        c = _client()
        r = c.post("/api/v1/pdf/inspect", json={})
        assert r.status_code == 200


class TestEventsEndpoints:
    def test_stream_route_registered(self):
        app = create_app()
        paths = {route.path for route in app.routes}
        assert "/api/v1/events/stream" in paths


class TestMoldetApiEndpoints:
    def test_coref_ft_missing_image(self):
        c = _client()
        r = c.post("/api/v1/moldet/coref_ft", json={})
        assert r.status_code == 422

    def test_extract_pdf_page_missing_path(self):
        c = _client()
        r = c.post("/api/v1/moldet/extract-pdf-page", json={})
        assert r.status_code == 422

    def test_removed_endpoint_returns_gone(self):
        c = _client()
        r = c.post("/api/v1/moldet/detect-page", json={})
        assert r.status_code == 410


class TestModelServerEndpoints:
    def test_models_health(self):
        c = _client()
        r = c.get("/api/v1/models/health")
        assert r.status_code == 200

    def test_models_environment_check(self):
        c = _client()
        r = c.get("/api/v1/models/environment/check")
        assert r.status_code == 200

    def test_models_test_missing_model_id(self):
        c = _client()
        r = c.post("/api/v1/models/test", json={})
        assert r.status_code == 200
        assert r.json().get("success") is False

    def test_models_render_missing_smiles(self):
        c = _client()
        r = c.post("/api/v1/models/mol/render", json={})
        assert r.status_code == 200
        assert r.json().get("success") is False
```

- [ ] **Step 2: 验证**

Run: `uv run pytest tests/unit/test_routers_smoke.py -v`
Expected: 全部通过（允许既有 pre-existing 失败保持原状）。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_routers_smoke.py
git commit -m "test(routers): smoke tests for all 19 routers + model_server

- Add coverage for documents, coref, sar, ocr, pdf, events, moldet_api
- Add model_server health/env/test/render smoke tests"
```

---

## Task 4: httpFetch 区分 Pydantic 422 与 MBForgeError

**Files:**
- Modify: `frontend/src/api/http/_utils.ts:81-108`
- Create: `frontend/src/api/http/_utils.test.ts`

**Interfaces:**
- Consumes: backend JSON error body (`{error, error_code, ...}` or `{detail: [...]}`).
- Produces: `AppError(ErrorCode.ApiError, ...)` for Pydantic 422; existing behavior for MBForgeError.

- [ ] **Step 1: 修改错误解析逻辑**

Replace the `if (!resp.ok)` block in `httpFetch` with:
```typescript
    if (!resp.ok) {
      const body = await resp.text().catch(() => '')
      let payload: Record<string, unknown> | null = null
      try {
        payload = body ? JSON.parse(body) : null
      } catch {
        // Non-JSON body — fall through to legacy fallback.
      }

      // Pydantic ValidationError shape: { detail: [{loc, msg, type}, ...] }
      if (
        resp.status === 422 &&
        payload &&
        Array.isArray(payload.detail)
      ) {
        const detail = payload.detail as Array<{ loc?: string[]; msg?: string }>
        const msg = detail
          .map((e) => `${(e.loc ?? []).join('.')}: ${e.msg ?? 'invalid'}`)
          .join('; ')
        throw new AppError(ErrorCode.ApiError, msg || 'Validation failed', {
          severity: severityFromHttpStatus(resp.status),
          context: { http_status: resp.status, backend_code: 'validation_error' },
        })
      }

      const code = payload
        ? backendCodeToErrorCode(payload.error_code as string | undefined)
        : ErrorCode.Network
      const message = payload?.error
        ? String(payload.error)
        : `HTTP ${resp.status}: ${body.slice(0, 200)}`
      const opts: AppErrorOpts = {
        severity: normalizeSeverity(payload?.severity) ?? severityFromHttpStatus(resp.status),
        category: payload?.category as string | undefined,
        context: {
          ...(payload?.context as Record<string, unknown> | undefined),
          http_status: resp.status,
          ...(payload?.error_code
            ? { backend_code: String(payload.error_code) }
            : {}),
        },
        timestamp: payload?.timestamp as number | undefined,
      }
      throw new AppError(code, message, opts)
    }
```

- [ ] **Step 2: 添加单元测试**

Create `frontend/src/api/http/_utils.test.ts`:
```typescript
import { describe, it, expect, vi } from 'vitest'
import { httpFetch, ErrorCode, AppError } from './_utils'

describe('httpFetch Pydantic 422 handling', () => {
  it('throws ApiError with joined detail messages for Pydantic validation errors', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () =>
        JSON.stringify({
          detail: [
            { loc: ['body', 'title'], msg: 'field required', type: 'missing' },
            { loc: ['body', 'page'], msg: 'value is not a valid integer', type: 'type_error' },
          ],
        }),
    } as Response)

    await expect(httpFetch('/api/v1/test', { method: 'POST', body: '{}' })).rejects.toThrow(
      AppError,
    )
    await expect(httpFetch('/api/v1/test', { method: 'POST', body: '{}' })).rejects.toSatisfy(
      (err: AppError) =>
        err.errorCode === ErrorCode.ApiError &&
        err.message.includes('body.title: field required') &&
        err.message.includes('body.page: value is not a valid integer'),
    )
  })

  it('preserves MBForgeError handling for custom 422', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 422,
      text: async () =>
        JSON.stringify({
          error: 'invalid root',
          error_code: 'validation_error',
          severity: 'warning',
        }),
    } as Response)

    await expect(httpFetch('/api/v1/test')).rejects.toSatisfy(
      (err: AppError) =>
        err.errorCode === ErrorCode.ApiError && err.message === 'invalid root',
    )
  })
})
```

- [ ] **Step 3: 验证**

Run: `cd frontend && npx vitest run src/api/http/_utils.test.ts`
Expected: tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/http/_utils.ts frontend/src/api/http/_utils.test.ts
git commit -m "fix(frontend): distinguish Pydantic 422 from MBForgeError in httpFetch

- Join detail.loc/detail.msg into an ApiError message
- Preserve existing error_code handling for custom errors"
```

---

## Task 5: Agent streaming 错误分类

**Files:**
- Modify: `src/mbforge/agent/graph.py:88-90`
- Create: `tests/unit/test_agent_graph.py`

**Interfaces:**
- Consumes: exceptions from `agent.astream_events`.
- Produces: `{"type": "error", "error", "recoverable"}` for known errors; re-raise unknown errors after yielding fatal message.

- [ ] **Step 1: 定义已知异常类**

At the top of `src/mbforge/agent/graph.py`, add:
```python
class ToolExecutionError(Exception):
    """Raised when an agent tool fails."""


class LLMProviderError(Exception):
    """Raised when the LLM provider call fails."""
```

- [ ] **Step 2: 修改异常处理分支**

Replace:
```python
    except Exception as e:
        logger.error("Agent streaming error: %s", e)
        yield {"type": "error", "error": str(e)}
```

With:
```python
    except (ToolExecutionError, LLMProviderError) as e:
        logger.warning("Agent streaming recoverable error: %s", e)
        yield {"type": "error", "error": str(e), "recoverable": True}
    except Exception as e:
        logger.error("Agent streaming fatal error", exc_info=True)
        yield {"type": "error", "error": "Internal error", "recoverable": False}
        raise
```

- [ ] **Step 3: 添加测试**

Create `tests/unit/test_agent_graph.py`:
```python
"""Tests for agent streaming error handling."""
import pytest
from mbforge.agent.graph import (
    LLMProviderError,
    ToolExecutionError,
    stream_agent_response,
)


async def _failing_agent(exc):
    async def _aiter():
        raise exc

    class _FakeAgent:
        async def astream_events(self, *args, **kwargs):
            async for item in _aiter():
                yield item

    return _FakeAgent()


@pytest.mark.asyncio
async def test_recoverable_tool_error():
    agent = await _failing_agent(ToolExecutionError("tool failed"))
    events = [e async for e in stream_agent_response(agent, [])]
    errors = [e for e in events if e.get("type") == "error"]
    assert len(errors) == 1
    assert errors[0]["error"] == "tool failed"
    assert errors[0].get("recoverable") is True


@pytest.mark.asyncio
async def test_recoverable_llm_error():
    agent = await _failing_agent(LLMProviderError("llm failed"))
    events = [e async for e in stream_agent_response(agent, [])]
    errors = [e for e in events if e.get("type") == "error"]
    assert errors[0]["error"] == "llm failed"
    assert errors[0].get("recoverable") is True


@pytest.mark.asyncio
async def test_fatal_unknown_error():
    agent = await _failing_agent(RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        [e async for e in stream_agent_response(agent, [])]
```

- [ ] **Step 4: 验证**

Run: `uv run pytest tests/unit/test_agent_graph.py -v`
Expected: 3 tests passed.

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/agent/graph.py tests/unit/test_agent_graph.py
git commit -m "fix(agent): classify streaming errors as recoverable or fatal

- Add ToolExecutionError and LLMProviderError
- Recoverable errors yield recoverable:true
- Unknown errors log full stack and re-raise"
```

---

## Task 6: `nvidia-smi` 异步化/缓存

**Files:**
- Modify: `src/mbforge/core/resource_manager.py:798-822`

**Interfaces:**
- Consumes: `subprocess.run(['nvidia-smi'], ...)` inside `ResourceManager.check_all()`.
- Produces: synchronous `_get_gpu_info_sync()` + optional async wrapper or 1-minute TTL cache.

- [ ] **Step 1: 提取同步 GPU 探测并加缓存**

Above `class ResourceManager`, add:
```python
import time
from functools import lru_cache


@lru_cache(maxsize=1)
def _cached_gpu_info(_cache_key: int) -> dict[str, str]:
    """Probe GPU info via nvidia-smi, cached for 60 seconds.

    The cache key is ``int(time.time() / 60)`` so the result is refreshed
    once per minute. GPU availability does not change on a sub-second
    timescale, and the probe can block for several seconds on hosts
    without NVIDIA drivers.
    """
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            return {
                "gpu_available": "true",
                "gpu_name": parts[0].strip() if parts else "",
                "cuda_version": parts[1].strip() if len(parts) > 1 else "",
            }
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return {"gpu_available": "false", "gpu_name": "", "cuda_version": ""}


def _get_gpu_info() -> dict[str, str]:
    cache_key = int(time.time() / 60)
    return _cached_gpu_info(cache_key)
```

- [ ] **Step 2: 替换 check_all 中的直接调用**

Replace the direct `subprocess.run` block in `check_all` with:
```python
        if not report.gpu_available:
            gpu_info = _get_gpu_info()
            if gpu_info["gpu_available"] == "true":
                report.gpu_available = True
                report.gpu_name = gpu_info["gpu_name"]
                report.cuda_version = gpu_info["cuda_version"]
```

- [ ] **Step 3: 验证**

Run: `uv run pytest tests/unit/test_diagnostics.py -v` (uses health/resource endpoints)
Expected: pass, and `/api/v1/environment/check` returns quickly on second call.

- [ ] **Step 4: Commit**

```bash
git add src/mbforge/core/resource_manager.py
git commit -m "perf(resources): cache nvidia-smi probe for 60 seconds

- Avoid blocking the event loop on every /environment/check call
- Cache invalidates per-minute; missing nvidia-smi stays non-fatal"
```

---

## Task 7: Settings GET 脱敏 API key

**Files:**
- Modify: `src/mbforge/routers/settings.py:19-22`
- Create: `tests/unit/test_settings_redaction.py`

**Interfaces:**
- Consumes: `AppConfig` from `load_global_config()`.
- Produces: `GET /api/v1/settings` returns `***` for any field whose name contains `api_key` or `secret`.

- [ ] **Step 1: 实现脱敏函数**

Add to `src/mbforge/routers/settings.py`:
```python
def _redact_secrets(obj: Any) -> Any:
    """Recursively replace secret-ish values with '***' for GET responses."""
    if isinstance(obj, dict):
        return {
            k: "***" if isinstance(v, str) and ("api_key" in k.lower() or "secret" in k.lower()) else _redact_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj
```

Change `settings_get` to:
```python
@router.get("")
async def settings_get() -> dict:
    cfg = load_global_config()
    return {"success": True, "settings": _redact_secrets(cfg.model_dump())}
```

- [ ] **Step 2: 添加测试**

Create `tests/unit/test_settings_redaction.py`:
```python
"""Tests for settings secret redaction."""
from unittest.mock import patch
from mbforge.routers.settings import _redact_secrets, settings_get


def test_redact_api_keys():
    raw = {
        "ocr": {
            "mineru_api_key": "secret123",
            "paddleocr_api_key": "secret456",
            "glmocr_api_key": "secret789",
            "host": "https://example.com",
        },
        "llm": {"openai_api_key": "sk-xxx", "model": "gpt-4"},
        "theme": "dark",
    }
    redacted = _redact_secrets(raw)
    assert redacted["ocr"]["mineru_api_key"] == "***"
    assert redacted["ocr"]["paddleocr_api_key"] == "***"
    assert redacted["ocr"]["glmocr_api_key"] == "***"
    assert redacted["ocr"]["host"] == "https://example.com"
    assert redacted["llm"]["openai_api_key"] == "***"
    assert redacted["llm"]["model"] == "gpt-4"
    assert redacted["theme"] == "dark"


def test_redact_handles_non_string_secrets():
    assert _redact_secrets({"api_key": None}) == {"api_key": None}
    assert _redact_secrets({"api_key": 123}) == {"api_key": 123}
```

- [ ] **Step 3: 验证**

Run: `uv run pytest tests/unit/test_settings_redaction.py -v`
Expected: 2 tests passed.

- [ ] **Step 4: Commit**

```bash
git add src/mbforge/routers/settings.py tests/unit/test_settings_redaction.py
git commit -m "fix(settings): redact api_key and secret fields in GET /settings

- Recursive _redact_secrets masks any string value whose key contains
  api_key or secret
- Prevents credentials from leaking to the frontend"
```

---

## Task 8: Ruff lint 清零

**Files:**
- Modify: `pyproject.toml`
- Modify: many Python files under `src/mbforge/`

**Interfaces:**
- Produces: `uv run ruff check src/mbforge` exits 0.

- [ ] **Step 1: 自动修复**

Run: `uv run ruff check --fix src/mbforge`
This fixes ~142 of 254 issues.

- [ ] **Step 2: 为第三方/批量导出代码添加 per-file ignores**

Add to `pyproject.toml` under `[tool.ruff.lint]`:
```toml
[tool.ruff.lint.per-file-ignores]
"src/mbforge/parsers/molecule/molscribe_inference/**" = ["N806", "N803", "E741"]
"src/mbforge/gui/utils/__init__.py" = ["F401"]
```

- [ ] **Step 3: 人工修复剩余问题**

Run: `uv run ruff check src/mbforge`
For each remaining issue, fix it manually. Common remaining categories:
- F401 unused imports in non-exempt files
- N806/N803 naming in non-exempt files
- I001 import sorting
- B905 `zip(..., strict=True)` where lengths are guaranteed equal

- [ ] **Step 4: 验证**

Run: `uv run ruff check src/mbforge`
Expected: 0 errors.

Run: `uv run pytest tests/unit/ -q`
Expected: no new test failures.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/mbforge/
git commit -m "style: clear Ruff lint baseline

- Apply ruff --fix
- Add per-file ignores for vendored molscribe_inference and gui/utils
- Fix remaining manual lint issues"
```

---

## Task 9: 最终验证与描述文件更新

**Files:**
- Modify: `docs/superpowers/plans/2026-07-09-p0-p1-defects-fix-plan.md`
- Modify: `docs/superpowers/specs/2026-07-09-p0-defects-fix-design.md`（如需）
- Create/Modify: 进度描述文件（如 `.superpowers/sdd/progress.md`）

- [ ] **Step 1: 运行全量 Python 测试**

Run: `uv run pytest tests/ -q`
Expected: 记录通过/跳过/失败数，确认无新增失败。

- [ ] **Step 2: 运行前端相关测试**

Run: `cd frontend && npx vitest run src/api/http/_utils.test.ts`
Expected: pass.

- [ ] **Step 3: Ruff 最终检查**

Run: `uv run ruff check src/mbforge`
Expected: 0 errors.

- [ ] **Step 4: 更新进度/描述文件**

Append to `.superpowers/sdd/progress.md`:
```markdown
## P0 + P1 缺陷修复 - 完成摘要
- 分支: fix/p0-defects
- 工作树: .worktrees/fix/p0-defects
- 完成任务: Task 1-8
- 关键结果:
  - tsconfig.json 移除非法 noCheck
  - server.py/app.py 实现模型后台预热
  - 19 routers + model_server 冒烟测试覆盖
  - httpFetch 区分 Pydantic 422
  - Agent streaming 错误分类
  - nvidia-smi 60s 缓存
  - Settings GET 脱敏 api_key/secret
  - Ruff lint 清零
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-07-09-p0-p1-defects-fix-plan.md docs/superpowers/specs/2026-07-09-p0-defects-fix-design.md .superpowers/sdd/progress.md
git commit -m "docs: record P0+P1 completion and update progress ledger"
```

---

## Rollback

| 改动 | 回滚命令 |
|---|---|
| tsconfig | `git revert <tsconfig-fix-sha>` |
| prewarm | `git revert <prewarm-sha>` |
| router tests | `git revert <router-tests-sha>` |
| httpFetch 422 | `git revert <httpFetch-sha>` |
| agent errors | `git revert <agent-graph-sha>` |
| nvidia-smi cache | `git revert <resource-manager-sha>` |
| settings redaction | `git revert <settings-sha>` |
| Ruff cleanup | `git revert <ruff-sha>` |

---

## P2/P3 Roadmap（仅记录）

- 文档-代码同步（README/AGENTS/CLAUDE pipeline stage/router counts/storage paths）
- 全局状态 `AppState` 重构
- 依赖版本收紧
- OpenKB PageIndex 性能基准
- 前端打包体积优化
