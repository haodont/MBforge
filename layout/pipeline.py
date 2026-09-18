from __future__ import annotations

import time
from pathlib import Path

if __package__:
    from .v3 import DEFAULT_MODEL_DIR, LayoutDetectorV3, build_regions, px_box_to_pdf, to_evidence
    from .merge import flatten, merge
else:
    from v3 import DEFAULT_MODEL_DIR, LayoutDetectorV3, build_regions, px_box_to_pdf, to_evidence
    from merge import flatten, merge


MODEL_V3 = DEFAULT_MODEL_DIR
_MOLDET_DIR = Path(__file__).resolve().parent / "weights" / "moldet"
MOLDET_WEIGHTS = {
    "960_doc": _MOLDET_DIR / "moldet_v2_yolo26n_960_doc.pt",
    "640_general": _MOLDET_DIR / "moldet_v2_yolo26n_640_general.pt",
}

# 版面检测器：Hiro-Layout（ONNX / onnxruntime）。类别顺序以 ONNX 元数据为准，
# 见 `hiro.py` 顶部说明。
HIRO_MODEL_DIR = Path(__file__).resolve().parent / "weights" / "hiro"


def load_v3(model_dir=MODEL_V3, *, device=None, dtype="bfloat16"):
    return LayoutDetectorV3(model_dir, device=device, dtype=dtype)


def load_hiro(model_dir=HIRO_MODEL_DIR, *, input_size=640, providers=None):
    if __package__:
        from .hiro import HiroLayoutDetector
    else:
        from hiro import HiroLayoutDetector

    return HiroLayoutDetector(model_dir, input_size=input_size, providers=providers)


def load_moldet(weights):
    from ultralytics import YOLO

    weights = Path(weights)
    if not weights.is_file():
        raise FileNotFoundError(f"MolDet 权重不存在: {weights}")
    return YOLO(str(weights))


def page_image(path, *, src_dpi=144, dpi=144):
    from PIL import Image

    if src_dpi <= 0 or dpi <= 0:
        raise ValueError(f"DPI must be positive, got src_dpi={src_dpi}, dpi={dpi}")
    with Image.open(path) as source:
        image = source.convert("RGB")
    if src_dpi != dpi:
        scale = dpi / src_dpi
        image = image.resize(
            (round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    return image


def detect_page(image, v3, mol_model=None, *, doc_id: str, page_num: int = 1,
                dpi: int = 144, conf: float = 0.4, imgsz: int = 800,
                mol_conf: float = 0.4, mol_imgsz: int = 960,
                min_area_pct: float = 0.1, device: str | None = None,
                nms_iou: float | None = None):
    import numpy as np

    if dpi <= 0:
        raise ValueError(f"dpi must be positive, got {dpi}")
    arr = np.array(image)
    predict_kwargs = {} if nms_iou is None else {"nms_iou": nms_iou}
    t = time.perf_counter()
    items, page_px = v3.predict(
        arr, threshold=conf, size={"height": imgsz, "width": imgsz}, **predict_kwargs)
    v3_ms = (time.perf_counter() - t) * 1000

    n_area_dropped = 0
    if min_area_pct > 0:
        thr = page_px[0] * page_px[1] * min_area_pct / 100
        before = len(items)
        items = [r for r in items
                 if (r["bbox_px"][2] - r["bbox_px"][0])
                 * (r["bbox_px"][3] - r["bbox_px"][1]) >= thr]
        n_area_dropped = before - len(items)

    regions, page = build_regions(
        {"items": items, "page_px": page_px}, doc_id, page_num, dpi,
        source=getattr(v3, "source_name", "layout_v3"))

    # 检测器不自带阅读顺序时（Hiro），用官方的 column_sort 启发式补上。
    # V3 自带模型级逻辑阅读序（provides_reading_order=True），**保持原样不动**——
    # 这是 V3 相对外部方案的真实优势，重排只会破坏它（也会改动 baseline_256）。
    if not getattr(v3, "provides_reading_order", True):
        from reading_order import assign as assign_reading_order
        regions = assign_reading_order(regions, page)
    mols, mol_ms = [], 0.0
    if mol_model is not None:
        t = time.perf_counter()
        res = mol_model.predict(
            source=arr, imgsz=mol_imgsz, conf=mol_conf,
            device=device, verbose=False,
        )[0]
        mol_ms = (time.perf_counter() - t) * 1000
        if res.boxes is not None and len(res.boxes):
            for b in res.boxes:
                box = [float(v) for v in b.xyxy[0].tolist()]
                mols.append({
                    "region_id": f"{doc_id}-{page_num}-molecule-{len(mols)}",
                    "label": "molecule",
                    "bbox_px": [round(v, 2) for v in box],
                    "bbox_pdf": [round(v, 2) for v in px_box_to_pdf(
                        box, page["height_pt"], page["px_per_pt"])],
                    "score": round(float(b.conf[0]), 4),
                    "source": "molecule_det",
                })

    return regions, mols, page, {
        "v3_ms": v3_ms, "mol_ms": mol_ms, "area_dropped": n_area_dropped,
    }


def merge_page(regions, mols, page, *, doc_id: str, page_num: int = 1, params=None):
    return merge(regions, mols, doc_id, page_num,
                 page["height_pt"], page["px_per_pt"], params=params)


def to_evidence_page(regions, mols, page, *, doc_id: str, page_num: int = 1, params=None):
    ev_regions, _ = merge_page(
        regions, mols, page, doc_id=doc_id, page_num=page_num,
        params={"cross_module": False, **(params or {})})
    evidence = []
    for region in flatten(ev_regions):
        ev = to_evidence(region, doc_id, page_num)
        if ev:
            evidence.append(ev)
    return evidence
