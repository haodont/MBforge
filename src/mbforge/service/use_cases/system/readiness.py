"""Readiness diagnostics service — aggregated environment probes.

Read-only summary plus one active probe (the demo pipeline run). Every probe
degrades independently: a single failing subsystem never affects the other
sections of the summary. The HTTP router only maps these functions to
endpoints (including the legacy /diagnostics compatibility surface).

The Node agent sidecar owns LLM readiness and provider calls; this summary
reports only Python backend subsystems.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mbforge.foundation.config import AppConfig, load_global_config
from mbforge.foundation.layout import probe_library_root
from mbforge.foundation.logger import get_logger
from mbforge.foundation.paths import get_model_cache_dir
from mbforge.service.dto.readiness import (
    BlockingModelReadiness,
    DatabaseReadiness,
    DemoRunResponse,
    LibraryReadiness,
    ModelGateReadiness,
    ModelReadiness,
    OCRReadiness,
    ReadinessSummaryResponse,
)
from mbforge.service.ports import get_database, get_runtime

logger = get_logger(__name__)

_READINESS_RESOURCE_IDS = frozenset(
    {"moldet", "molparser", "rdkit", "torch", "unidock_tools"}
)


def _sanitize_error(exc: BaseException) -> str:
    """Render a bounded error message for readiness diagnostics."""
    message = str(exc) or type(exc).__name__
    return message[:300]


def _load_config_safe() -> AppConfig | None:
    try:
        return load_global_config()
    except Exception as exc:  # noqa: BLE001 — config load must not break summary
        logger.warning("readiness: failed to load global config: %s", exc)
        return None


def _probe_library_sync() -> LibraryReadiness:
    cfg = _load_config_safe()
    root = cfg.library_root if cfg is not None else None
    probe = probe_library_root(root)
    return LibraryReadiness(
        configured=probe.configured,
        path=str(probe.path) if probe.path is not None else None,
        exists=probe.exists,
        writable=probe.writable,
        error=probe.error,
    )


def _probe_database_sync(library: LibraryReadiness) -> DatabaseReadiness:
    if not library.configured or not library.path:
        return DatabaseReadiness(ok=False, error="library_not_configured")
    try:
        db = get_database(library.path)
        with db.kb_conn():
            return DatabaseReadiness(ok=True)
    except Exception as exc:  # noqa: BLE001 — degraded probe, never raise
        logger.warning("readiness: database probe failed: %s", exc)
        return DatabaseReadiness(ok=False, error=_sanitize_error(exc))


def _probe_models_sync() -> list[ModelReadiness]:
    try:
        runtime = get_runtime()
        report = runtime.resource_manager.check_all()
    except Exception as exc:  # noqa: BLE001 — degraded probe, never raise
        logger.warning("readiness: model probe failed: %s", exc)
        return []
    try:
        cache_dir: str | None = get_model_cache_dir()
    except Exception:  # noqa: BLE001 — best-effort cosmetic field
        cache_dir = None
    items: list[ModelReadiness] = []
    for resource in report.resources:
        if resource.id not in _READINESS_RESOURCE_IDS:
            continue
        info = runtime.resource_manager.catalog.get(resource.id)
        items.append(
            ModelReadiness(
                id=resource.id,
                name=resource.name,
                status=resource.status.value,
                local_path=resource.local_path or None,
                size_mb=resource.size_mb or None,
                expected_size_mb=float(info.size_mb) if info is not None else None,
                cache_dir=cache_dir,
                last_error=runtime.model_status.get_error(resource.id)
                or resource.error
                or None,
            )
        )
    return items


def _probe_layout_sync() -> OCRReadiness:
    """Report the local text/layout pipeline this build runs.

    There is no OCR provider chain any more: page text comes from the local
    layout producer, so this reports whether its weights are on disk. The DTO
    keeps the ``chain`` shape so the readiness UI needs no new contract.
    """
    try:
        result = get_runtime().resource_manager.check("hiro_layout")
        status = getattr(result, "status", None)
        value = getattr(status, "value", status)
        if value == "ready":
            return OCRReadiness(chain=["hiro-layout"])
        return OCRReadiness(chain=[], error=f"hiro_layout: {value}")
    except Exception as exc:  # noqa: BLE001 — degraded probe, never raise
        logger.warning("readiness: layout probe failed: %s", exc)
        return OCRReadiness(chain=[], error=_sanitize_error(exc))


def _probe_model_gate_sync() -> ModelGateReadiness:
    """Report whether the ingest queue may claim documents, and why not."""
    from mbforge.service.use_cases.pipeline.model_gate import evaluate_model_gate

    try:
        gate = evaluate_model_gate()
    except Exception as exc:  # noqa: BLE001 — degraded probe, never raise
        logger.warning("readiness: model gate probe failed: %s", exc)
        return ModelGateReadiness(ready=False, reason=_sanitize_error(exc))
    return ModelGateReadiness(
        ready=gate.ready,
        required=list(gate.required),
        missing=[
            BlockingModelReadiness(
                id=model.id, name=model.name, status=model.status, error=model.error
            )
            for model in gate.missing
        ],
        reason=gate.reason(),
    )


async def summary() -> ReadinessSummaryResponse:
    """Aggregate read-only probes for library, database, models and layout."""
    library = await asyncio.to_thread(_probe_library_sync)
    database, models, ocr, model_gate = await asyncio.gather(
        asyncio.to_thread(_probe_database_sync, library),
        asyncio.to_thread(_probe_models_sync),
        asyncio.to_thread(_probe_layout_sync),
        asyncio.to_thread(_probe_model_gate_sync),
    )
    return ReadinessSummaryResponse(
        library=library,
        database=database,
        models=models,
        ocr=ocr,
        model_gate=model_gate,
    )


def _write_demo_pdf(library_root: str) -> tuple[Path, str]:
    """Generate a demo PDF and register it as a library document.

    Returns ``(pdf_path, doc_id)`` so the caller can enqueue the
    registered document through the standard ingest path.
    """
    import tempfile

    import pymupdf

    pdf_path = Path(tempfile.gettempdir()) / "mbforge-readiness-demo.pdf"
    doc = pymupdf.open()
    try:
        for i in range(2):
            page = doc.new_page(width=612, height=792)
            page.insert_text(
                (72, 72),
                f"MBForge readiness demo, page {i + 1}. "
                "Synthetic sample document for pipeline smoke testing.",
                fontsize=12,
            )
            page.insert_text(
                (72, 112),
                "Detectable example: caffeine C8H10N4O2",
                fontsize=14,
            )
            page.draw_polyline(
                [
                    (130, 170),
                    (160, 150),
                    (190, 170),
                    (190, 205),
                    (160, 225),
                    (130, 205),
                    (130, 170),
                ],
                color=(0, 0, 0),
                width=1.2,
            )
            page.draw_line((190, 170), (225, 150), color=(0, 0, 0), width=1.2)
            page.draw_line((225, 150), (250, 170), color=(0, 0, 0), width=1.2)
        doc.save(str(pdf_path))
    finally:
        doc.close()
    from mbforge.service.use_cases.documents.library import LibraryStore

    store = LibraryStore.get(library_root)
    demo_doc = store.add_document(str(pdf_path), title="Readiness Demo")
    return pdf_path, demo_doc.doc_id


async def demo_run() -> DemoRunResponse:
    """Generate a demo PDF and enqueue it via the standard ingest path."""
    cfg = _load_config_safe()
    root = cfg.library_root if cfg is not None else None
    if not root:
        return DemoRunResponse(ok=False, error="library_not_configured")
    file_path = ""
    try:
        pdf_path, doc_id = await asyncio.to_thread(_write_demo_pdf, root)
        file_path = str(pdf_path)
        from mbforge.service.use_cases.pipeline.ingest import (
            enqueue as ingest_enqueue,
        )

        run_id = await ingest_enqueue(root, doc_id)
        return DemoRunResponse(
            ok=True, run_id=run_id, file_path=file_path, doc_id=doc_id
        )
    except Exception as exc:  # noqa: BLE001 — report failure, never raise
        logger.warning("readiness: demo run failed: %s", exc)
        return DemoRunResponse(
            ok=False, file_path=file_path, error=_sanitize_error(exc)
        )


# ── Diagnostics export ───────────────────────────────────────────


def export_diagnostics_sync(directory: str | None, limit: int) -> dict:
    """Snapshot the diagnostics ring buffer + stats to a JSON file.

    Raises ``OSError`` when the directory cannot be created or the file
    cannot be written; the router maps that to HTTP semantics.
    """
    import json
    from datetime import UTC, datetime

    from mbforge.foundation.logger import get_diagnostic_stats, get_diagnostics
    from mbforge.foundation.paths import GLOBAL_APP_DIR

    records = get_diagnostics(limit=limit)
    stats = get_diagnostic_stats()
    exported_at = datetime.now(tz=UTC).isoformat()

    out_dir = Path(directory) if directory else GLOBAL_APP_DIR / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    if not out_dir.is_dir():
        raise OSError("export directory does not exist")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"diagnostics_{stamp}.json"
    payload = {"exported_at": exported_at, "stats": stats, "errors": records}
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info("Exported %d diagnostics records to %s", len(records), out_file)
    return {"path": str(out_file), "count": len(records), "exported_at": exported_at}
