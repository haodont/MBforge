"""Molecule extraction from PDF images and native text.

Detects chemical structures in rendered PDF pages via MolDetv2 and
recognizes them with MolParser. Also extracts SMILES strings directly from
native PDF text. Results feed the normalization and persistence stages.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import shutil  # noqa: F401 — imported here so tests can patch `mbforge.pipeline.detection.extraction.shutil.move`
from collections.abc import Iterable
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PIL import Image

from ...utils.logger import get_logger
from ..cancellation import CancelCheck
from .types import ExtractionResult

logger = get_logger("mbforge.pipeline.detection.extraction")

# 分子检测渲染分辨率（200 DPI 在检测精度损失 <5% 的前提下提升渲染速度 ~50%）
DEFAULT_RENDER_DPI = 200.0
_BASE_PDF_DPI = 72.0

# 纯文本页跳过阈值：文本量超过此值且无嵌入图 → 跳过分子检测
_TEXT_PAGE_CHAR_THRESHOLD = 500

# MolParser crop 批处理（PIPE-10）：限制同时驻留内存的 PIL crop 数量。
# 默认值 16 来自本地基准（2026-07-27，CUDA，32 张 384x384 crop）：batch=16 时
# 吞吐最高（9.4 img/s，与无界批相同），更大批次无收益且徒增内存；硬上限防止
# 异常配置破坏内存边界。
DEFAULT_SCRIBE_BATCH_SIZE = 16
MAX_SCRIBE_BATCH_SIZE = 64

# split_molecule_crop（墨迹阈值 + DBSCAN 墨迹聚类拆分）的输入上限：超过该
# 像素数时跳过预处理，避免 CPU 上的聚类/逐像素操作把单页处理拖到数十秒。
_PREPROCESS_MAX_PIXELS = 1_000_000

# 窗口 B 相对紧贴检测框 A 的扩展比例，**只向右、向下**扩展，使 A 与 B 共用
# 左上角（重叠区像素逐点相同，故抹除主簇无需坐标换算）。B 一图两用：落盘存档
# 用它（结构右侧/下方的相邻标签与边框因此保留），抹去主簇后交给 RapidOCR；
# MolParser 仍只吃 A 的主簇 A1，不受此值影响。
_OCR_WINDOW_EXPAND_FRACTION = 0.15


def _clamp_scribe_batch_size(configured: int) -> int:
    """Clamp a configured MolParser batch size into ``[1, MAX_SCRIBE_BATCH_SIZE]``."""
    return max(1, min(configured, MAX_SCRIBE_BATCH_SIZE))


def _ocr_label_image(image: Image.Image) -> tuple[list[str], str]:
    """OCR a label image (window B minus the molecule drawing); owns and closes it.

    Runs inside the shared OCR pool (one RapidOCR engine per pool thread), so
    label reading no longer serializes in front of the MolParser feed. The
    caller transfers ownership of ``image`` here — it is always closed, on
    both the success and failure paths. Returns ``(labels, primary)``.
    """
    from ...backends.ocr.label_reader import get_label_reader
    from .recognition import select_primary_coref

    try:
        reads = get_label_reader().read(image)
        labels = [text for text, _, _, _ in reads]
        primary = select_primary_coref(
            [(text, bbox, iso) for text, _, bbox, iso in reads]
        )
        return labels, primary
    except Exception as exc:
        logger.debug("crop-label OCR failed on a label image: %s", exc)
        return [], ""
    finally:
        image.close()


def _fill_ocr_slot(slot: list, ocr_future: Future) -> None:
    """Fill ``[labels, primary]`` as OCR completes (no blocking on worker).

    Runs on the OCR pool thread via ``Future.add_done_callback``. The flush
    path reads the slot at most once and never blocks on the future, keeping
    the GPU/MolParser feed the sole critical path; labels land after the fact
    and the extractor drains the futures before returning.
    """
    try:
        labels, primary = ocr_future.result()
    except Exception as exc:
        logger.debug("crop-label OCR future failed: %s", exc)
        return
    if labels:
        slot.append(list(labels))
    if primary:
        slot.append(primary)


_SMILES_LIKE_PATTERN = re.compile(r"[A-Za-z0-9\(\)\[\]\=\#\+\-\\\\/@\.]{3,}")


def make_candidate_id(
    doc_id: str,
    canonical_smiles: str,
    page_number: int | None,
    bbox: Iterable[float] | None,
) -> str:
    """Return a deterministic stable identity for a molecule candidate.

    The ID is a truncated SHA-256 over
    ``doc_id | canonical_smiles | page_number | bbox`` so an ESMILES block can
    be matched back to its candidate by stable identity instead of a fuzzy
    SMILES prefix. Identical inputs always produce the same ID; any change in
    structure, page, position, or owning document yields a different one.
    """
    page_part = "" if page_number is None else str(page_number)
    bbox_part = ",".join(f"{value:.2f}" for value in bbox) if bbox else ""
    payload = "|".join((doc_id, canonical_smiles, page_part, bbox_part))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _nearby_page_text(
    page_blocks: object,
    bbox_top_left: tuple[float, float, float, float],
) -> str:
    """Return native PDF text near a detected molecule bbox.

    Markush context is often printed as ``Formula I``/``R1`` next to the
    drawing.  Passing the whole page to the classifier would incorrectly mark
    every molecule on a page as Markush, so only overlapping or nearby text
    blocks are retained.  Scanned pages simply return an empty string and can
    still be reviewed through the SMILES/dummy-atom rules.

    ``page_blocks`` is the page's ``page.get_text("blocks")`` result, fetched
    once per page by the caller (PIPE-09) instead of once per molecule.
    """
    if not isinstance(page_blocks, (list, tuple)):
        return ""
    blocks = page_blocks

    x0, y0, x1, y1 = bbox_top_left
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    pad_x = max(18.0, width * 0.75)
    pad_y = max(24.0, height * 1.5)
    query = (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)

    nearby: list[tuple[float, str]] = []
    for block in blocks:
        if not isinstance(block, (list, tuple)) or len(block) < 5:
            continue
        try:
            bx0, by0, bx1, by1 = (float(value) for value in block[:4])
        except (TypeError, ValueError):
            continue
        text = block[4].strip() if isinstance(block[4], str) else ""
        if not text:
            continue
        if bx1 < query[0] or bx0 > query[2] or by1 < query[1] or by0 > query[3]:
            continue
        distance = abs((bx0 + bx1) / 2 - (x0 + x1) / 2) + abs(
            (by0 + by1) / 2 - (y0 + y1) / 2
        )
        nearby.append((distance, text))

    nearby.sort(key=lambda item: item[0])
    return " ".join(text for _, text in nearby[:4])[:1000]


def extract_molecules_from_pdf(
    pdf_path: str,
    library_root: str,
    doc_id: str,
    max_pages: int | None = None,
    cancel_check: CancelCheck | None = None,
    staging_dir: str | Path | None = None,
    ocr_spans_by_page: dict[int, list[dict]] | None = None,
) -> list[ExtractionResult]:
    """Render PDF pages and extract molecule structures via MolDetv2 + MolParser.

    The legacy Doc+General detector pipeline (MolImagePipeline.extract_page)
    was replaced by the joint MolDetv2 detector on 2026-07-08. This
    function now mirrors /api/v1/moldet/extract-pdf-page but is driven by
    the in-process pipeline runner (no HTTP round-trip) and writes crop
    images to {library_root}/storage/{doc_id}/crops/ for downstream
    pipeline stages.

    All molecule crops are passed to ``molparser.predict_batch`` in bounded
    batches (PIPE-10): at most ``moldet.molparser_batch_size`` PIL crops are
    held in memory at once, and each batch's images are saved and closed
    before the next batch starts, so peak memory no longer scales with the
    number of molecules in the document.

    ``cancel_check`` is a cooperative cancellation checkpoint polled per page
    and around each MolParser batch; the blocking batch call itself is never
    force-killed, but the first checkpoint after it returns stops any further
    crop writes.

    ``staging_dir`` (``storage/{doc_id}/.staging/``) redirects the
    physical crop writes into this invocation's staging area while the logical
    path
    recorded on ``ExtractionResult.mol_img_path`` stays the canonical crops
    dir, so persisted references remain valid once the runner promotes the
    staged files on success. ``None`` writes directly to the crops dir.

    ``ocr_spans_by_page`` optionally provides pre-extracted layout spans from
    the OCR backend (e.g. PaddleOCR). When present, figure-region bboxes are used
    as Regions of Interest (ROI), skipping full-page MolDet detection and
    saving GPU time. Keys are 0-based page indices; values are lists of span
    dicts with keys ``bbox``, ``block_type`` (1 = image/figure).

    Scheduling: the stage runs as a three-thread CPU/GPU pipeline — a renderer
    thread (own fitz handle) renders pages ahead of time, the calling thread
    batches all of a page's MolDet ROIs into one GPU call, and a worker thread
    preprocesses crops and flushes bounded MolParser batches. The GPU thus
    alternates MolDet/MolParser without idle gaps while rendering and
    preprocessing stay hidden behind inference.
    """
    check = cancel_check or (lambda: None)
    import contextlib

    from ...backends import molparser
    from ...backends.moldet_v2_ft import (
        detect_molecules,
        detect_molecules_batch,
        get_moldet,
    )

    # 权重就位由 backends.get_moldet() 首次创建时经 ResourceManager
    # ensure（首次运行从 ModelScope 自动拉取），pipeline 不直接触 infra。
    get_moldet()
    # 从 config 读取检测参数（回退到硬编码默认值）
    try:
        from ...utils.config import load_global_config

        _cfg = load_global_config()
        _moldet_cfg = _cfg.moldet
        _render_dpi = float(_moldet_cfg.detection_dpi)
        _detection_batch_size = int(_moldet_cfg.detection_batch_size)
        _text_page_char_threshold = int(_moldet_cfg.text_page_char_threshold)
        _cfg_max_pages = _moldet_cfg.max_pages_per_doc
        _scribe_batch_size = _clamp_scribe_batch_size(
            int(_moldet_cfg.molparser_batch_size)
        )
    except Exception:
        _render_dpi = DEFAULT_RENDER_DPI
        _detection_batch_size = 0
        _text_page_char_threshold = _TEXT_PAGE_CHAR_THRESHOLD
        _cfg_max_pages = None
        _scribe_batch_size = DEFAULT_SCRIBE_BATCH_SIZE

    detector = get_moldet()
    if not detector.is_available():
        logger.warning("MolDetv2 unavailable, skipping image molecule extraction")
        return []

    logger.info("Loading MolParser model for document %s", doc_id)
    molparser.load()
    logger.info("MolParser availability: %s", molparser.health())

    import queue as _queue
    import threading

    import fitz

    _open_errors: tuple[type[Exception], ...] = (RuntimeError,)
    if hasattr(fitz, "FileDataError"):
        _open_errors = _open_errors + (fitz.FileDataError,)

    from ...storage.layout import LibraryLayout

    crop_dir = LibraryLayout(library_root).crops_dir(doc_id)
    # Physical writes go to this run's staging dir when provided; crop_dir
    # stays the logical location recorded on the extraction results.
    write_dir = Path(staging_dir) / "crops" if staging_dir else crop_dir
    write_dir.mkdir(parents=True, exist_ok=True)

    # Validate the PDF up front (same error semantics as before) and get the
    # page count; the renderer below opens its own handle because PyMuPDF
    # documents must not be shared across threads.
    try:
        probe = fitz.open(pdf_path)
        page_count = len(probe)
        probe.close()
    except _open_errors as exc:
        logger.error("Failed to open PDF %s: %s", pdf_path, exc)
        return []

    results: list[ExtractionResult] = []
    # Lightweight per-crop metadata, safe to keep for the whole document:
    # (page_idx, mol_idx, bbox_pdf, mol_score, crop_path, nearby_text,
    #  ocr_slot). ``ocr_slot`` is a ``[labels, primary]`` list filled
    # asynchronously by the OCR-pool callback (empty when the label image had
    # too little foreground to OCR); the worker never blocks on it. The PIL
    # crops themselves live only in ``pending_crops`` for the current bounded
    # closed as soon as that batch is flushed (PIPE-10), so peak image memory is
    # bounded by the batch size, not by the number of molecules in the document.
    crop_entries: list[tuple[int, int, list[float], float, Path, str, list]] = []
    pending_crops: list[Image.Image] = []
    # 已提交到 OCR 池的 future，文件级协调：worker 不阻塞，收尾统一 drain。
    ocr_futures: list[Future] = []
    # 与 ``pending_crops`` 一一对应的存档图片 = 窗口 B（结构 + 右侧/下方相邻
    # 标签）。``pending_crops`` 交 MolParser 推理、``pending_archive`` 落盘，
    # 用途不同但同批追加、同批释放。
    pending_archive: list[Image.Image] = []

    # ---------------------------------------------------------------------------
    # CPU/GPU 流水线（三个线程，队列均有界）：
    #   renderer  — 独立 fitz 句柄逐页渲染（CPU）→ page_q(maxsize=2)
    #   main      — 批量 MolDet（GPU）→ crop_q(maxsize=2)
    #   worker    — crop 预处理/标签 OCR（CPU）+ 攒批刷 MolParser（GPU）
    # GPU 时间线上 MolDet 与 MolParser 无缝交替；渲染与预处理完全被藏到
    # GPU 之后。线程通过超时 put + 存活检查规避死锁；取消在所有队列跳点
    # 都有检查点，取消路径不刷 MolParser 残批（与旧串行行为一致）。
    # ---------------------------------------------------------------------------
    from ..cancellation import TaskCancelledError

    page_q: _queue.Queue = _queue.Queue(maxsize=2)
    crop_q: _queue.Queue = _queue.Queue(maxsize=2)
    render_error: list[BaseException] = []
    worker_error: list[BaseException] = []
    skipped_pure_text = [0]

    def _put_bounded(q: _queue.Queue, item: object, consumer_alive=None) -> bool:
        """Put with a timeout so a dead consumer cannot deadlock the producer.

        ``consumer_alive`` is a callable returning the consumer's liveness;
        when it reports dead before a slot frees, the put is abandoned and
        False is returned. Cancel is polled between retries.
        """
        while True:
            check()
            try:
                q.put(item, timeout=0.1)
                return True
            except _queue.Full:
                if consumer_alive is not None and not consumer_alive():
                    return False

    def flush_scribe_batch() -> None:
        """Infer, save, and release the pending crops as one bounded batch.

        Checkpoint before the blocking batch call and per entry after it:
        a cancel that arrives during inference stops any further crop
        writes. Every pending PIL image is closed before returning, so no
        crop survives into the next batch.
        """
        if not pending_crops:
            return

        logger.info(
            "Flushing MolParser batch: %d crops for doc %s",
            len(pending_crops),
            doc_id,
        )

        check()
        batch_entries = crop_entries[len(results) :]
        try:
            logger.info(
                "Calling molparser.predict_batch with %d images", len(pending_crops)
            )
            scribe_results = molparser.predict_batch(list(pending_crops))
            logger.info(
                "MolParser batch completed, got %d results", len(scribe_results)
            )
        except Exception as scribe_exc:
            raise RuntimeError(
                f"MolParser batch predict failed for doc {doc_id}: {scribe_exc}"
            ) from scribe_exc

        # 严格化：返回值必须与输入 crop 数一一对应。MolParser 正常返回等长
        # 结果；此处不匹配即真 bug，拒绝静默补空/丢弃（zip_longest 兜底曾
        # 吞掉数量偏差）。
        if len(scribe_results) != len(batch_entries):
            raise RuntimeError(
                f"MolParser batch result count mismatch for doc {doc_id}: "
                f"expected {len(batch_entries)} crops, got {len(scribe_results)}"
            )

        try:
            for batch_idx, (entry, scribe) in enumerate(
                zip(batch_entries, scribe_results, strict=True)
            ):
                check()
                (
                    page_idx,
                    mol_idx,
                    bbox_pdf,
                    score,
                    crop_path,
                    nearby_text,
                    ocr_slot,
                ) = entry
                ocr_labels: list[str] = []
                ocr_primary = ""
                if ocr_slot:
                    # 非阻塞：callback 已在 OCR 池线程填好 ``[labels, primary]``。
                    # ``ocr_slot[0]`` 是标签列表，``ocr_slot[-1]`` 是 primary（可能
                    # 只有标签而无 primary，故按序取）。文件收尾会 drain 全部 future，
                    # 因此返回给调用方时 labels 已就绪。
                    if len(ocr_slot) >= 1:
                        ocr_labels = list(ocr_slot[0])
                    if len(ocr_slot) >= 2:
                        ocr_primary = ocr_slot[1]
                if ocr_primary:
                    ocr_labels = [
                        ocr_primary,
                        *(label for label in ocr_labels if label != ocr_primary),
                    ]
                raw_smiles = getattr(scribe, "smiles", "")
                smi = raw_smiles.strip() if isinstance(raw_smiles, str) else ""
                context_parts = [part for part in (nearby_text,) if part]
                properties = {}
                scribe_properties = getattr(scribe, "properties", {})
                markush = (
                    isinstance(scribe_properties, dict)
                    and scribe_properties.get("markush") is True
                )
                if markush:
                    properties["markush"] = True
                    groups = scribe_properties.get("groups")
                    if isinstance(groups, str):
                        properties["groups"] = groups
                if nearby_text:
                    properties["role_context"] = nearby_text
                if ocr_labels:
                    properties["ocr_labels"] = ocr_labels
                if ocr_primary:
                    properties["ocr_labels_primary"] = ocr_primary
                # Save crop file; the logical path under the canonical crops
                # dir is recorded on the result even when the physical write
                # went to this run's staging dir.
                try:
                    archive_path = write_dir / crop_path.name
                    # 落盘的是窗口 B 本身；MolParser 推理用的是 ``pending_crops``
                    # 中的主簇 A1，两者不可互换。
                    pending_archive[batch_idx].save(archive_path)
                    if not archive_path.is_file():
                        raise OSError(f"crop archive was not created: {archive_path}")
                except Exception as save_exc:
                    raise RuntimeError(
                        f"Molecule crop archive failed for {crop_path}: {save_exc}"
                    ) from save_exc
                results.append(
                    ExtractionResult(
                        # Ordinary candidates use Layer 1 directly.  Keep the
                        # raw Layer 2 value only for Markush candidates.
                        esmiles=(
                            scribe.esmiles.strip()
                            if markush and isinstance(scribe.esmiles, str)
                            else smi
                        ),
                        smiles=smi,
                        name=ocr_labels[0] if ocr_labels else "",
                        source="image",
                        moldet_conf=score,
                        bbox_pdf=bbox_pdf,
                        page_idx=page_idx,
                        context_text="\n".join(context_parts),
                        mol_img_path=crop_path,
                        status="pending",
                        properties=properties,
                    )
                )
        finally:
            # 无论成功、mismatch 还是 save 失败，本批 PIL 一律关闭并清空，
            # 避免 open 句柄在异常提前退出时泄漏。
            for pending_crop in pending_crops:
                pending_crop.close()
            pending_crops.clear()
            for archived in pending_archive:
                archived.close()
            pending_archive.clear()

    def preprocess_worker() -> None:
        """Crop + preprocess + label-OCR worker; feeds bounded MolParser batches.

        Sole owner of ``crop_entries`` / ``pending_crops`` / ``results`` so no
        locks are needed. On cancellation the pending batch is discarded
        (never flushed), matching the previous serial behaviour.
        """
        try:
            while True:
                payload = crop_q.get()
                if payload is None:
                    break
                (
                    page_idx,
                    image,
                    detect_result_bboxes,
                    scale_x,
                    scale_y,
                    page_h_pts,
                    page_blocks,
                ) = payload
                check()
                for mol_idx, cb in enumerate(detect_result_bboxes):
                    if getattr(cb, "category_id", 1) != 1:
                        continue
                    check()
                    # normalized -> pixel
                    px1 = int(round(cb.bbox[0] * image.width))
                    py1 = int(round(cb.bbox[1] * image.height))
                    px2 = int(round(cb.bbox[2] * image.width))
                    py2 = int(round(cb.bbox[3] * image.height))
                    if px2 <= px1 or py2 <= py1:
                        continue
                    box_w = px2 - px1
                    box_h = py2 - py1
                    pad_x = int(round(box_w * _OCR_WINDOW_EXPAND_FRACTION))
                    pad_y = int(round(box_h * _OCR_WINDOW_EXPAND_FRACTION))
                    # B：只向右、下扩展的窗口（落盘存档 + OCR 底图）。
                    wide_crop = image.crop(
                        (
                            px1,
                            py1,
                            min(image.width, px2 + pad_x),
                            min(image.height, py2 + pad_y),
                        )
                    ).convert("L")
                    # A：紧贴检测框。与 B 共用左上角，故从 B 的左上角切出即可，
                    # 不必再裁一次页面。
                    raw_crop = wide_crop.crop((0, 0, box_w, box_h))
                    # 预处理只跑 A：灰度 → 墨迹阈值 (<200) → 对前景墨迹像素做
                    # DBSCAN，最大簇 A1 交 MolParser（保留原灰度，不二值化）。
                    # 聚类输入为像素坐标而非连通分量质心——200 DPI 下分子自身的
                    # 原子字母间距 20-50px，质心聚类会把结构拆碎并丢掉 70-95%
                    # 前景（实测）。1MP+ 的 A 是 CPU 重活，超过阈值时跳过预处理，
                    # 交由 MolParser processor 内部缩放（守卫按 A 判定，语义不变）。
                    try:
                        if box_w * box_h > _PREPROCESS_MAX_PIXELS:
                            crop, main_mask = raw_crop, None
                        else:
                            from .image_preprocessing import split_molecule_crop

                            split = split_molecule_crop(raw_crop)
                            crop, main_mask = split.main, split.main_mask
                    except Exception as pp_exc:
                        logger.debug(
                            "split_molecule_crop failed: %s, using raw crop", pp_exc
                        )
                        crop, main_mask = raw_crop, None
                    # OCR 输入 = B 抹去 A1：留下 A2 与右/下扩入的字符，同时避免
                    # 文本检测被分子自身的原子字母吸引。A1 与 B 左上角对齐，
                    # mask 直接原地生效，无坐标换算。
                    ocr_image = None
                    if main_mask is not None:
                        from .image_preprocessing import erase_ink_region

                        ocr_image = erase_ink_region(wide_crop, main_mask)
                    # 只保留足够的有效前景才 OCR（≥16px），纯噪点跳过。OCR 交给
                    # 共享 OCR 池完成；``_ocr_label_image`` 接管并关闭
                    # ``ocr_image``，无足够前景时直接由本线程关闭。
                    #
                    # 关键：这里不把 OCR 拽回 worker 同步路径。我们用 callback 把
                    # 结果异步写进 ``ocr_slot``（worker/GPU 零阻塞），并把 future
                    # 登记到 ``ocr_futures``，文件跑完统一 drain 后才返回——标签是
                    # 富化信息，不能让 GPU 空等它。
                    ocr_slot: list = []
                    ocr_future: Future | None = None
                    if ocr_image is not None:
                        if int((np.asarray(ocr_image) < 200).sum()) >= 16:
                            from ...infra.process import ocr_executor

                            ocr_future = ocr_executor().submit(
                                _ocr_label_image, ocr_image
                            )
                            ocr_future.add_done_callback(
                                lambda fut, s=ocr_slot: _fill_ocr_slot(s, fut)
                            )
                            ocr_futures.append(ocr_future)
                        else:
                            ocr_image.close()
                    # PDF-space bbox (lower-left origin)
                    bbox_pdf = [
                        round(px1 * scale_x, 2),
                        round(page_h_pts - py2 * scale_y, 2),
                        round(px2 * scale_x, 2),
                        round(page_h_pts - py1 * scale_y, 2),
                    ]
                    nearby_text = _nearby_page_text(
                        page_blocks,
                        (
                            px1 * scale_x,
                            py1 * scale_y,
                            px2 * scale_x,
                            py2 * scale_y,
                        ),
                    )
                    crop_filename = (
                        f"{doc_id}_page_{page_idx:04d}_mol_{mol_idx:04d}.png"
                    )
                    crop_path = crop_dir / crop_filename
                    crop_entries.append(
                        (
                            page_idx,
                            mol_idx,
                            bbox_pdf,
                            cb.score,
                            crop_path,
                            nearby_text,
                            ocr_slot,
                        )
                    )
                    # 落盘存档就是 B 本身（含结构 + 右侧/下方相邻标签），与 OCR
                    # 底图同一张图、同一次裁剪；MolParser 吃的仍是 A 的主簇。
                    pending_crops.append(crop)
                    pending_archive.append(wide_crop)
                    if len(pending_crops) >= _scribe_batch_size:
                        logger.info(
                            "Batch size reached (%d), flushing for doc %s",
                            _scribe_batch_size,
                            doc_id,
                        )
                        flush_scribe_batch()
        except TaskCancelledError as exc:
            worker_error.append(exc)
        except Exception as exc:
            logger.error("Molecule preprocess worker failed: %s", exc)
            worker_error.append(exc)
        finally:
            # Final partial batch — only on a clean run (a cancelled or
            # failed run discards pending crops, as before).
            if not worker_error and pending_crops:
                try:
                    logger.info(
                        "Flushing final batch with %d remaining crops for doc %s",
                        len(pending_crops),
                        doc_id,
                    )
                    flush_scribe_batch()
                except TaskCancelledError as exc:
                    worker_error.append(exc)
                except Exception as exc:
                    logger.error("Final MolParser flush failed: %s", exc)
                    worker_error.append(exc)

    def render_pages() -> None:
        """Render pages (CPU) with an independent fitz handle.

        PyMuPDF documents must not be shared across threads; this thread
        therefore owns the only handle. Pure-text pages are skipped here
        (they cannot contain molecule structures) and counted.
        """
        doc = None
        try:
            doc = fitz.open(pdf_path)
            zoom = _render_dpi / _BASE_PDF_DPI
            mat = fitz.Matrix(zoom, zoom)
            _effective_max_pages = (
                max_pages if max_pages is not None else _cfg_max_pages
            )
            stop = min(
                _effective_max_pages
                if _effective_max_pages is not None
                else page_count,
                page_count,
            )
            for page_idx in range(stop):
                check()
                page = doc.load_page(page_idx)

                # 跳过纯文本页：有大量原生文本且无嵌入图 → 不可能有分子结构
                native_text = page.get_text("text").strip()
                has_images = len(page.get_images()) > 0
                if len(native_text) > _text_page_char_threshold and not has_images:
                    skipped_pure_text[0] += 1
                    continue

                # PIPE-09: read the page's text blocks once here; the
                # per-molecule `_nearby_page_text` calls filter this snapshot
                # per bbox instead of re-reading the page for every molecule.
                try:
                    page_blocks = page.get_text("blocks")
                except Exception as exc:  # noqa: BLE001 - PDF backends vary by page type
                    logger.debug("Could not read nearby PDF text: %s", exc)
                    page_blocks = ()

                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                    pix.height, pix.width, pix.n
                )
                image = Image.fromarray(img_array)
                if not _put_bounded(
                    page_q,
                    (page_idx, image, page_blocks, page.rect.width, page.rect.height),
                ):
                    return
        except TaskCancelledError as exc:
            render_error.append(exc)
        except _open_errors as exc:
            logger.error("Failed to open PDF %s: %s", pdf_path, exc)
            render_error.append(exc)
        except Exception as exc:
            logger.error("Page rendering failed for %s: %s", pdf_path, exc)
            render_error.append(exc)
        finally:
            if doc is not None:
                doc.close()
            page_q.put(None)

    worker = threading.Thread(
        target=preprocess_worker, name="mbforge-detect-preprocess", daemon=True
    )
    renderer = threading.Thread(
        target=render_pages, name="mbforge-detect-render", daemon=True
    )
    worker.start()
    renderer.start()

    try:
        while True:
            item = page_q.get()
            if item is None:
                break
            page_idx, image, page_blocks, page_w_pts, page_h_pts = item
            check()

            # ROI optimization: use OCR figure spans as candidate regions.
            ocr_figure_bboxes: list[tuple[float, float, float, float]] | None = None
            if ocr_spans_by_page is not None:
                spans = ocr_spans_by_page.get(page_idx)
                if spans:
                    # Collect bboxes of image/figure blocks (block_type == 1).
                    ocr_figure_bboxes = [
                        tuple(s["bbox"]) for s in spans if s.get("block_type") == 1
                    ]
                    logger.info(
                        "Page %d: OCR provided %d spans, %d are figures",
                        page_idx,
                        len(spans),
                        len(ocr_figure_bboxes),
                    )

            # 1. FT detection (full-page or ROI-guided, batched per page)
            if ocr_figure_bboxes:
                # Use OCR figure regions as ROIs: batch-crop each figure, then
                # run MolDet *inside the ROIs* in ONE GPU call so only real
                # molecule boxes survive (a figure often contains several
                # structures plus text).
                # Coordinates: OCR bbox is PDF-space bottom-left origin; the
                # page pixmap is pixel-space top-left origin.
                scale_x_px = image.width / page_w_pts if page_w_pts > 0 else 0
                scale_y_px = image.height / page_h_pts if page_h_pts > 0 else 0
                roi_inputs: list[Image.Image] = []
                roi_meta: list[tuple[int, int, int, int]] = []
                for _fig_idx, (x0, y0_ll, x1, y1_ll) in enumerate(ocr_figure_bboxes):
                    px1 = int(round(x0 * scale_x_px))
                    py1_top = int(round((page_h_pts - y1_ll) * scale_y_px))
                    px2 = int(round(x1 * scale_x_px))
                    py2_bot = int(round((page_h_pts - y0_ll) * scale_y_px))
                    if px2 <= px1 or py2_bot <= py1_top:
                        continue
                    roi_inputs.append(image.crop((px1, py1_top, px2, py2_bot)))
                    roi_meta.append((px1, py1_top, px2, py2_bot))

                detect_result_bboxes = []
                if roi_inputs:
                    logger.info(
                        "Using %d OCR figure ROIs on page %d for doc %s (batched)",
                        len(roi_inputs),
                        page_idx,
                        doc_id,
                    )
                    # MolDet in ROI-local normalized coords (0.7 conf filter
                    # already applied by detect_molecules_batch).
                    roi_results = detect_molecules_batch(
                        roi_inputs,
                        detector=detector,
                        max_per_call=_detection_batch_size,
                    )
                    for (px1, py1_top, px2, py2_bot), roi_res in zip(
                        roi_meta, roi_results, strict=True
                    ):
                        roi_w = max(1, px2 - px1)
                        roi_h = max(1, py2_bot - py1_top)
                        for cb in roi_res.bboxes:
                            if getattr(cb, "category_id", 1) != 1:
                                continue
                            # ROI-local normalized → full-page pixel → normalized.
                            ax1 = px1 + cb.bbox[0] * roi_w
                            ay1 = py1_top + cb.bbox[1] * roi_h
                            ax2 = px1 + cb.bbox[2] * roi_w
                            ay2 = py1_top + cb.bbox[3] * roi_h
                            detect_result_bboxes.append(
                                SimpleNamespace(
                                    category_id=1,
                                    bbox=[
                                        ax1 / image.width,
                                        ay1 / image.height,
                                        ax2 / image.width,
                                        ay2 / image.height,
                                    ],
                                    score=cb.score,
                                )
                            )

                # Fallback: OCR figures that contain no molecule (e.g. a
                # misclassified table) must not silently drop the page — run
                # full-page MolDet as the safety net.
                if not detect_result_bboxes:
                    logger.info(
                        "No molecules inside OCR ROIs on page %d, "
                        "falling back to full-page MolDet",
                        page_idx,
                    )
                    detect_result = detect_molecules(image, detector=detector)
                    detect_result_bboxes = detect_result.bboxes
                logger.info(
                    "MolDet found %d molecule candidates on page %d (ROI-guided)",
                    len(detect_result_bboxes),
                    page_idx,
                )
            else:
                # No OCR guidance — run full-page MolDet.
                logger.info("Running MolDet on page %d for doc %s", page_idx, doc_id)
                detect_result = detect_molecules(image, detector=detector)
                detect_result_bboxes = detect_result.bboxes
                logger.info(
                    "MolDet found %d molecule candidates on page %d",
                    len(detect_result_bboxes),
                    page_idx,
                )

            # Sort by reading order: top-to-bottom (y1), then left-to-right (x0).
            detect_result_bboxes.sort(key=lambda cb: (cb.bbox[1], cb.bbox[0]))

            if not detect_result_bboxes:
                continue

            # 2. Hand the page off for crop preprocessing + batched MolParser.
            scale_x = page_w_pts / image.width if image.width > 0 else 0
            scale_y = page_h_pts / image.height if image.height > 0 else 0
            if not _put_bounded(
                crop_q,
                (
                    page_idx,
                    image,
                    detect_result_bboxes,
                    scale_x,
                    scale_y,
                    page_h_pts,
                    page_blocks,
                ),
                consumer_alive=worker.is_alive,
            ):
                # Worker died mid-run; its error is re-raised after the join.
                break
    finally:
        # Worker sentinel: skip waiting if the worker already exited.
        while True:
            try:
                crop_q.put(None, timeout=0.1)
                break
            except _queue.Full:
                if not worker.is_alive():
                    break
        worker.join()
        # Drain page_q so a still-producing renderer cannot block forever
        # (happens when the main loop exits early on an error).
        while renderer.is_alive():
            with contextlib.suppress(_queue.Empty):
                page_q.get(timeout=0.2)
            renderer.join(timeout=0.1)
        renderer.join()

    if render_error:
        raise render_error[0]
    if worker_error:
        raise worker_error[0]

    logger.info(
        "Extracted %d molecule image candidates from %s (%d pure-text pages skipped, dpi=%s, batch=%d, scribe_batch=%d)",
        len(results),
        doc_id,
        skipped_pure_text[0],
        _render_dpi,
        _detection_batch_size,
        _scribe_batch_size,
    )
    # 收尾 drain OCR future：worker 一路上都没阻塞，此处确保返回前所有标签
    # 富化已落地（callback 都执行完毕）。任一失败已由 callback 吞掉，不影响结果。
    for _fut in ocr_futures:
        with contextlib.suppress(Exception):
            _fut.result()
    for result, entry in zip(results, crop_entries, strict=True):
        ocr_slot = entry[-1]
        if not ocr_slot:
            continue
        labels = list(ocr_slot[0]) if ocr_slot else []
        primary = ocr_slot[1] if len(ocr_slot) >= 2 else ""
        if primary:
            labels = [primary, *(label for label in labels if label != primary)]
        if labels:
            result.name = labels[0]
            result.properties["ocr_labels"] = labels
        if primary:
            result.properties["ocr_labels_primary"] = primary
    return results


async def extract_molecules_from_pdf_async(
    pdf_path: str,
    library_root: str,
    doc_id: str,
    max_pages: int | None = None,
) -> list[ExtractionResult]:
    """Async wrapper that runs the PDF molecule extractor off the event loop."""
    return await asyncio.to_thread(
        extract_molecules_from_pdf,
        pdf_path,
        library_root,
        doc_id,
        max_pages,
    )


def extract_molecules_from_text(text: str, doc_id: str) -> list[ExtractionResult]:
    """Extract SMILES strings from raw text and validate with RDKit."""
    from rdkit import Chem

    results: list[ExtractionResult] = []
    seen: set[str] = set()

    for match in _SMILES_LIKE_PATTERN.finditer(text):
        candidate = match.group(0)
        try:
            mol = Chem.MolFromSmiles(candidate)
            if mol is None:
                continue
            canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        except Exception as exc:
            logger.debug("RDKit failed to parse candidate %r: %s", candidate, exc)
            continue
        if canonical in seen:
            continue
        seen.add(canonical)

        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 200)
        context = text[start:end]

        results.append(
            ExtractionResult(
                esmiles=canonical,
                name="",
                source="text",
                context_text=context,
                status="pending",
            )
        )

    logger.info("Extracted %d text SMILES candidates from %s", len(results), doc_id)
    return results


async def extract_molecules_from_text_async(
    text: str, doc_id: str
) -> list[ExtractionResult]:
    """Async wrapper that runs text SMILES extraction off the event loop."""
    return await asyncio.to_thread(extract_molecules_from_text, text, doc_id)
