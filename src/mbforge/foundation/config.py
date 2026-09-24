"""MBForge global configuration — single JSON file with Pydantic schema.

Loads, validates, and persists application settings from
``~/MBForge/settings.json``.  All runtime and business configuration
(LLM, OCR, molecule detection, ingestion) flows through the ``AppConfig``
model exposed here; direct ``os.environ`` reads are limited to pure
runtime toggles such as ``MBFORGE_FORCE_CPU``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from mbforge.foundation.files import load_json, save_json
from mbforge.foundation.logger import get_logger
from mbforge.foundation.paths import GLOBAL_APP_DIR, GLOBAL_SETTINGS_PATH

logger = get_logger(__name__)


class LLMConfig(BaseModel):
    """LLM configuration shared by pipeline and Agent tasks."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "openai_compatible"
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 1.0
    request_timeout: int = 60
    molecule_tool_enabled: bool = Field(
        default=False,
        description=(
            "Use one cloud LLM tool-call pass as a text-only molecule fallback "
            "when image detection returns no candidates."
        ),
    )
    molecule_tool_max_chars: int = Field(
        default=16000,
        ge=1000,
        le=100000,
        description="Maximum source characters sent to the molecule registration tool.",
    )
    language: str = "en"


class MoldetConfig(BaseModel):
    """Molecule detection (MolDetv2 + MolParser-Mobile) settings."""

    model_config = ConfigDict(extra="ignore")

    device: str = "auto"
    molparser_dir: str = ""
    auto_moldet_on_import: bool = True
    detection_dpi: float = 200.0
    detection_batch_size: int = 0
    # MolParser crops per inference batch; clamped to [1, 64] by the extractor.
    molparser_batch_size: int = 16
    # Crop-label OCR worker threads (0 disables the dedicated pool fallback to
    # in-thread OCR). Used to run RapidOCR off the critical MolParser-feed path
    # so the GPU is not starved by serial CPU label reads; clamped to [0, 8].
    # Applies to the onnxruntime engine's parallel pool; the torch engine is
    # single-threaded by design (forced to 1 worker regardless).
    ocr_workers: int = 4
    # Crop-label OCR inference engine: "torch" (default; rapidocr v3 TORCH on
    # CUDA — measured ~128ms/img vs ~495ms CPU onnx on real 9.5k-px offcuts) or
    # "onnx" (rapidocr_onnxruntime, CPU fallback for no-GPU / CI).
    ocr_engine: str = "torch"
    # Auto-fall back to the onnxruntime CPU backend when the torch engine is
    # unavailable (no CUDA / missing torch). When False, an unavailable torch
    # engine yields a silent empty OCR (labels are enrichment only); "onnx"
    # never falls forward to torch.
    ocr_engine_fallback: bool = True
    # Crop-label OCR deployment: "inprocess" (default; engine lives in the
    # MBForge process / its OCR pool) or "daemon" (spawns and keeps a long-lived
    # background OCR process so model warm-up is paid once and torch can sit on
    # a dedicated GPU out of MolDet/MolParser's way).
    ocr_mode: str = "inprocess"
    # Daemon-mode address: host/port the background OCR service listens on and
    # CUDA device (torch engine) it binds. Defaults mirror the CLI.
    ocr_daemon_host: str = "127.0.0.1"
    ocr_daemon_port: int = 18799
    ocr_daemon_device: int = 0
    text_page_char_threshold: int = 500
    max_pages_per_doc: int | None = None


class LayoutConfig(BaseModel):
    """Page layout region detection settings for the Extract branch.

    Page text and layout come exclusively from the local Hiro-Layout producer:
    the detector's own labels (``chem`` / ``figcx`` / ``eqn`` …) plus a
    column-aware reading order, with region text read locally by RapidOCR.
    There is no cloud OCR provider to switch to, so the branch needs
    ``onnxruntime-gpu`` and the locally downloaded model weights.
    """

    model_config = ConfigDict(extra="ignore")

    conf_threshold: float = 0.4
    #: Run MolDet on the same page render so the cross-model rules can type a
    #: figure region that is really one molecule, and keep a figure holding
    #: several molecules as a container. Without it the layout path emits
    #: geometry only and molecule recognition stays the molecule pass' job.
    cross_model: bool = True
    #: Table recognizer backend id (reserved for backend switching).
    table_recognizer: str = "slanet"
    max_pages_per_doc: int | None = None


class IngestConfig(BaseModel):
    """Document ingestion queue / pipeline behavior settings."""

    model_config = ConfigDict(extra="ignore")

    auto_enqueue_on_import: bool = True
    default_priority: int = 0
    stage_timeout_seconds: dict[str, int] = Field(default_factory=dict)
    max_retries: int = 1
    max_concurrency: int = Field(
        default=4,
        ge=1,
        le=8,
        description=(
            "同时运行的 pipeline 任务数(每库)。GPU 阶段仍由 gpu_gate 串行保护。"
        ),
    )


class PdfParseConfig(BaseModel):
    """PDF text parsing / chunking settings."""

    model_config = ConfigDict(extra="ignore")

    chunk_size: int = 1000
    chunk_overlap: int = 200


class VLMConfig(BaseModel):
    """Visual LLM settings (reserved for future visual pipeline use)."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "openai_compatible"
    model: str = ""
    api_key: str = ""
    base_url: str = ""


class ModelServerConfig(BaseModel):
    """Local model server settings (reserved for future model-server process)."""

    model_config = ConfigDict(extra="ignore")

    host: str = "127.0.0.1"
    port: int = 18792
    auto_start: bool = False
    startup_timeout: int = 30
    health_check_interval: int = 5


class ProcessConfig(BaseModel):
    """Process governance and executor settings."""

    model_config = ConfigDict(extra="ignore")

    auto_reap_orphans: bool = True
    reap_grace_seconds: float = 5.0
    heartbeat_interval: float = 30.0
    gpu_concurrency: int = Field(default=1, ge=1, le=4)


class AppConfig(BaseModel):
    """全局应用配置 — 唯一 schema."""

    model_config = ConfigDict(extra="ignore")

    llm: LLMConfig = Field(default_factory=LLMConfig)
    model_cache_dir: str = ""
    theme: str = "dark"
    language: str = "zh"
    vlm: VLMConfig = Field(default_factory=VLMConfig)
    model_server: ModelServerConfig = Field(default_factory=ModelServerConfig)
    library_root: str | None = Field(
        default=None, description="Unified library data directory"
    )
    pdf_parse: PdfParseConfig = Field(default_factory=PdfParseConfig)
    moldet: MoldetConfig = Field(default_factory=MoldetConfig)
    layout: LayoutConfig = Field(default_factory=LayoutConfig)
    ingest: IngestConfig = Field(default_factory=IngestConfig)
    process: ProcessConfig = Field(default_factory=ProcessConfig)


# 历史文件名（用于一次性迁移）
_SETTINGS_PATH = GLOBAL_SETTINGS_PATH


def _canonicalize_configured_root(cfg: AppConfig) -> AppConfig:
    """Persist ``library_root`` as one absolute, normalized path."""
    if not cfg.library_root:
        return cfg
    normalized = str(Path(cfg.library_root).expanduser().resolve())
    if normalized == cfg.library_root:
        return cfg
    return cfg.model_copy(update={"library_root": normalized})


@lru_cache(maxsize=1)
def load_global_config() -> AppConfig:
    """读取 settings.json;缺失/损坏时使用并持久化 schema 默认值."""
    if _SETTINGS_PATH.exists():
        data = load_json(_SETTINGS_PATH)
        if data is not None:
            try:
                cfg = AppConfig.model_validate(data)
                # 未设置 library_root 时默认指向统一应用目录
                if cfg.library_root is None or cfg.library_root == "":
                    cfg.library_root = str(GLOBAL_APP_DIR)
                    save_global_config(cfg)
                else:
                    normalized = _canonicalize_configured_root(cfg)
                    if normalized.library_root != cfg.library_root:
                        save_global_config(normalized)
                        cfg = normalized
                return cfg
            except Exception as exc:  # noqa: BLE001 — corrupt file, fall through to defaults
                logger.warning(
                    "settings.json corrupt or invalid, using defaults: %s", exc
                )
    cfg = AppConfig()
    cfg.library_root = str(GLOBAL_APP_DIR)
    save_global_config(cfg)
    return cfg


def save_global_config(config: AppConfig) -> None:
    """持久化并清空 lru_cache."""
    load_global_config.cache_clear()
    save_json(_SETTINGS_PATH, config.model_dump())


_REDACTED_SENTINEL = "***"


def _strip_redacted_markers(
    partial: dict[str, Any], base: dict[str, Any]
) -> dict[str, Any]:
    """Recursively replace "***" leaves in `partial` with the corresponding
    value from `base`. Lets clients roundtrip a redacted GET payload
    back through PUT without overwriting the real secret on disk.
    """
    out: dict[str, Any] = {}
    for k, v in partial.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            out[k] = _strip_redacted_markers(v, base[k])
        elif v == _REDACTED_SENTINEL and k in base:
            out[k] = base[k]
        else:
            out[k] = v
    return out


def update_settings(partial: dict[str, Any]) -> AppConfig:
    """Deep-merge `partial` 到当前配置 → 校验 → 持久化.

    Returns 新 AppConfig.输入不合法时抛 pydantic.ValidationError.

    字符串值等于 ``"***"`` 的叶子会被替换为磁盘上现有的值,这样经过
    ``_redact_secrets`` 的 GET 响应再原样 PUT 回来不会清掉真实密钥.
    """
    current = load_global_config().model_dump()
    safe_partial = _strip_redacted_markers(partial, current)

    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                _deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    _deep_merge(current, safe_partial)
    new_cfg = _canonicalize_configured_root(AppConfig.model_validate(current))
    save_global_config(new_cfg)
    return new_cfg


def reset_settings() -> AppConfig:
    """回到默认配置并持久化."""
    cfg = AppConfig()
    save_global_config(cfg)
    return cfg


def reset_config_cache() -> None:
    """测试辅助:清空 lru_cache."""
    load_global_config.cache_clear()
