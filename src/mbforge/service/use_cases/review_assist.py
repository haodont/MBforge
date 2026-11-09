"""Review-center AI assistance: build the packet, run it, keep the answer.

The review center is the one surface where the deterministic pipeline has
already refused to decide. This module hands those cases to the model with what
a reviewer would look at - the printed text of the page and the original images -
and records the answer as a suggestion beside the item. It never decides: no
status flips, no structure is written, and a missing model degrades to text.
"""

from __future__ import annotations

import base64
import threading
import time
from collections.abc import Sequence
from typing import Any

from mbforge.contracts.review_assist import (
    AssistCandidate,
    AssistImage,
    AssistPacket,
    AssistSuggestion,
)
from mbforge.foundation import config as app_config
from mbforge.foundation.errors import PathTraversalError, ValidationError
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger
from mbforge.service.ports import get_repositories
from mbforge.service.ports.review_assist import get_review_assist_runtime

logger = get_logger(__name__)

ASSIST_KINDS: tuple[str, ...] = (
    "markush_link",
    "review_required",
    "low_conf_molecule",
    "unparsable_smiles",
    "missing_evidence",
    "ambiguous_coref",
    "designation_unbound",
)

_TASK_BY_KIND = {
    "markush_link": "判断这处结构图上的印刷编号属于哪个候选结构（若图上印了编号）。",
    "review_required": "判断这处结构是具体化合物、Markush 骨架还是片段，并指出依据。",
    "low_conf_molecule": "判断这张结构图识别出的结构是否与图中一致，指出可疑的位置。",
    "unparsable_smiles": "判断图中结构能否读成完整分子，指出哪一部分读不出来。",
    "missing_evidence": "判断这条记录能否从给出的原文与图片中得到证实。",
    "ambiguous_coref": "判断图中编号指的是哪个候选结构。",
    "designation_unbound": "判断这条印刷读数属于哪个候选结构（或说明无从判断）。",
}

_ANSWER_CONTRACT = (
    "回答要求（严格）：",
    "1. 第一行 answer=<候选编号 N> 或 answer=cannot_decide；",
    "2. 之后最多三行 证据=... 引用给出的原文片段或图中可见的印字；",
    "   当选定了候选时，再写一行 mol_id=<该候选的 mol_id>；",
    "3. 不得给出新的 SMILES、数值或编号，不得假设未提供的内容。",
)

_auto_lock = threading.Lock()
_auto_running = False
#: One background pull per minute: a queue poll must not become a model loop.
_auto_last_at = 0.0
_AUTO_INTERVAL_SECONDS = 60.0


def assist_config():
    """The live review-assist settings."""
    return app_config.load_global_config().review


def vision_available() -> bool:
    """True when the original images should be captured and sent.

    The configured chat model may itself be multimodal (LongCat accepts
    text+image), so images need no separate ``vlm`` entry. The sidecar prefers a
    dedicated vision model when one is configured and falls back to text-only
    (reporting ``vision = false``) when the provider refuses the image.
    """
    return bool(assist_config().images)


def _question(kind: str, item: dict[str, Any]) -> str:
    task = _TASK_BY_KIND.get(kind, "判断这条复核记录在原文与图片中是否成立。")
    reasons = ", ".join(str(reason) for reason in (item.get("reasons") or []))
    lines = [
        "你在复核一篇扫描专利中的一处识别结果。只依据给出的原文与原始图片作答。",
        "任务：" + task,
    ]
    if item.get("name"):
        lines.append("流水线读到的编号：" + str(item.get("name")))
    if item.get("smiles"):
        lines.append("流水线读到的结构：" + str(item.get("smiles")))
    lines.append("复核原因：" + (reasons or "未标注"))
    lines.extend(_ANSWER_CONTRACT)
    return "\n".join(lines)


def _page_text(library_root: str, doc_id: str, page: int | None, budget: int) -> str:
    """The printed text around the item, each block tagged for citation."""
    from mbforge.service.use_cases.documents.source_evidence import list_evidence

    if not doc_id:
        return ""
    pages = [
        value
        for value in ((page or 0) - 1, page, (page or 0) + 1)
        if value and value >= 1
    ]
    chunks: list[str] = []
    for current in dict.fromkeys(pages):
        for block in list_evidence(library_root, doc_id, page=current):
            if block.kind == "molecule":
                continue
            text = (block.raw_text or "").strip()
            if not text:
                continue
            chunks.append(
                "[p" + str(current) + " " + block.evidence_id[:8] + "] " + text
            )
    joined = "\n".join(chunks)
    return joined if len(joined) <= budget else joined[:budget] + "\n…(截断)"


def _candidates(
    library_root: str, doc_id: str, page: int | None, limit: int
) -> list[AssistCandidate]:
    """Recognized structures drawn near the item page (the only choices offered)."""
    if not doc_id or not page:
        return []
    from mbforge.service.pipeline.artifacts.hydration import load_detections

    loaded = load_detections(library_root, doc_id)
    if not loaded:
        return []
    rows: list[AssistCandidate] = []
    for candidate in loaded[0]:
        detections = list(getattr(candidate, "detections", []) or [])
        near = [
            detection
            for detection in detections
            if detection.page is not None and abs(int(detection.page) + 1 - page) <= 1
        ]
        if not near:
            continue
        first = near[0]
        smiles = str(
            getattr(candidate, "canonical_smiles", "")
            or getattr(candidate, "smiles", "")
            or ""
        )
        # The pipeline leaves ``mol_id`` empty on some candidates; the canonical
        # SMILES is the identity every consumer uses, so an answer that names it
        # stays comparable across runs and documents.
        identity = str(getattr(candidate, "mol_id", "") or "") or smiles
        rows.append(
            AssistCandidate(
                mol_id=identity,
                smiles=smiles,
                name=str(getattr(candidate, "name", "") or ""),
                page=page,
                bbox=list(first.bbox) if getattr(first, "bbox", None) else None,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _crop_image(
    layout: LibraryLayout, doc_id: str, item: dict[str, Any], cfg: Any
) -> AssistImage | None:
    relpath = str(item.get("crop_relpath") or "").strip()
    if not relpath:
        return None
    try:
        path = layout.crop(doc_id, relpath)
    except (PathTraversalError, OSError, ValueError):
        return None
    if not path.is_file():
        return None
    data = path.read_bytes()
    if not data or len(data) > cfg.image_max_bytes:
        return None
    page = item.get("page") if isinstance(item.get("page"), int) else None
    return AssistImage(
        kind="crop",
        media_type="image/png",
        label="结构裁剪图",
        page=page,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def _page_image(
    layout: LibraryLayout, doc_id: str, item: dict[str, Any], cfg: Any
) -> AssistImage | None:
    """Render the item page whole: the printed number sits around the drawing."""
    page = item.get("page")
    if not isinstance(page, int) or page < 1:
        return None
    document = get_repositories(str(layout.library_root)).documents.get(doc_id)
    if not document:
        return None
    pdf = layout.storage_dir(doc_id) / str(document.get("file_name") or "")
    if not pdf.is_file():
        pdf = layout.source_pdf(doc_id)
    if not pdf.is_file():
        return None
    try:
        import pymupdf
    except ImportError:  # pragma: no cover - pymupdf ships with the backend
        return None
    try:
        opened = pymupdf.open(str(pdf))
    except Exception:  # noqa: BLE001 - an unreadable PDF is not an assist failure
        return None
    try:
        if page > opened.page_count:
            return None
        page_obj = opened.load_page(page - 1)
        rect = page_obj.rect
        scale = max(cfg.image_dpi, 72) / 72
        longest = max(rect.width, rect.height) * scale
        if longest > cfg.image_max_px:
            scale *= cfg.image_max_px / longest
        pix = None
        data = b""
        for _attempt in range(3):
            pix = page_obj.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            data = pix.tobytes("jpeg")
            if len(data) <= cfg.image_max_bytes:
                break
            scale *= 0.7
        else:
            return None
    finally:
        opened.close()
    if pix is None or not data:
        return None
    return AssistImage(
        kind="page",
        media_type="image/jpeg",
        label="原页",
        page=page,
        width=pix.width,
        height=pix.height,
        data_base64=base64.b64encode(data).decode("ascii"),
    )


def build_packet(
    library_root: str, kind: str, item_id: str, cfg: Any = None
) -> AssistPacket:
    """Assemble one bounded packet for a review item."""
    cfg = cfg or assist_config()
    item = get_repositories(library_root).review.get_item(kind, item_id)
    doc_id = str(item.get("doc_id") or "")
    layout = LibraryLayout(library_root)
    page = item.get("page") if isinstance(item.get("page"), int) else None

    images: list[AssistImage] = []
    if cfg.max_images > 0 and vision_available():
        for builder in (_crop_image, _page_image):
            if len(images) >= cfg.max_images:
                break
            image = builder(layout, doc_id, item, cfg)
            if image is not None:
                images.append(image)

    return AssistPacket(
        kind=kind,
        item_id=item_id,
        doc_id=doc_id,
        page=page,
        question=_question(kind, item),
        text=_page_text(library_root, doc_id, page, cfg.text_char_budget),
        candidates=_candidates(library_root, doc_id, page, cfg.max_candidates),
        images=images,
        vision_requested=bool(images),
    )


def assist_for(library_root: str, kind: str, item_id: str) -> dict[str, Any] | None:
    """The stored suggestion for one item, if any."""
    return get_repositories(library_root).review.get_assist(kind, item_id)


def assist_items(
    library_root: str,
    items: Sequence[dict[str, str]] | None = None,
    *,
    limit: int | None = None,
    force: bool = False,
) -> list[dict[str, Any]]:
    """Run the assistant for the given items, or the oldest unassisted ones.

    Every item costs one model call, so the batch is bounded twice: by the
    caller and by review.max_items. One failing item never stops the batch.
    """
    cfg = assist_config()
    if not cfg.enabled:
        raise ValidationError("review AI assistance is disabled in settings")
    runtime = get_review_assist_runtime()
    budget = max(1, min(limit or cfg.max_items, cfg.max_items))
    targets = [dict(item) for item in (items or [])][:budget]
    if not targets:
        targets = get_repositories(library_root).review.pending_without_assist(
            ASSIST_KINDS, budget
        )
    if not targets:
        return []

    results: list[dict[str, Any]] = []
    for target in targets:
        kind = str(target.get("kind") or "")
        item_id = str(target.get("item_id") or "")
        if not kind or not item_id:
            continue
        existing = get_repositories(library_root).review.get_assist(kind, item_id)
        if existing is not None and not force:
            results.append(existing)
            continue
        try:
            packet = build_packet(library_root, kind, item_id, cfg)
            answer: AssistSuggestion = runtime.run(
                packet, timeout_seconds=cfg.timeout_seconds
            )
            record = {
                "kind": kind,
                "item_id": item_id,
                "status": answer.status,
                "model": answer.model,
                "vision": answer.vision,
                "answer": answer.answer,
                "error": answer.error,
            }
        except Exception as exc:  # noqa: BLE001 - one item must not stop a batch
            logger.warning("review assist failed for %s/%s: %s", kind, item_id, exc)
            record = {
                "kind": kind,
                "item_id": item_id,
                "status": "error",
                "model": "",
                "vision": False,
                "answer": "",
                "error": str(exc)[:300],
            }
        get_repositories(library_root).review.upsert_assist(record)
        results.append(record)
    return results


def attach_suggestions(library_root: str, items: Sequence[dict[str, Any]]) -> None:
    """Embed stored suggestions into queue items, in place."""
    keys = [(str(item.get("kind") or ""), str(item.get("id") or "")) for item in items]
    stored = get_repositories(library_root).review.assists_for(keys)
    for item in items:
        key = (str(item.get("kind") or ""), str(item.get("id") or ""))
        suggestion = stored.get(key)
        if suggestion is None:
            continue
        payload = item.get("payload")
        item["payload"] = {
            **(payload if isinstance(payload, dict) else {}),
            "ai_assist": suggestion,
        }


def schedule_auto_assist(library_root: str) -> bool:
    """Pull assistance for unassisted pending items in the background.

    Single-flight: a queue poll while a run is in flight never starts a second
    one, so opening the review center cannot fan out into a model stampede.
    """
    global _auto_running, _auto_last_at
    cfg = assist_config()
    if not cfg.enabled or not cfg.auto:
        return False
    now = time.monotonic()
    with _auto_lock:
        if _auto_running or now - _auto_last_at < _AUTO_INTERVAL_SECONDS:
            return False
        _auto_running = True
        _auto_last_at = now

    def _run() -> None:
        global _auto_running
        try:
            assist_items(library_root)
        except Exception as exc:  # noqa: BLE001 - a background pull must not raise
            logger.warning("auto review assist failed: %s", exc)
        finally:
            with _auto_lock:
                _auto_running = False

    threading.Thread(target=_run, name="review-assist", daemon=True).start()
    return True


__all__ = [
    "ASSIST_KINDS",
    "assist_config",
    "assist_for",
    "assist_items",
    "attach_suggestions",
    "build_packet",
    "schedule_auto_assist",
    "vision_available",
]
