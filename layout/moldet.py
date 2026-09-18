# -*- coding: utf-8 -*-
"""
MolDetv2-YOLO26 推理脚本（UniParser 官方 .pt 权重，ultralytics PyTorch 后端）

用法示例：
    python inference.py --input img.png
    python inference.py --input "imgs/*.png" --conf 0.3 --imgsz 640
    python inference.py --input doc.pdf --model weights/moldet_v2_yolo26n_960_doc.pt --imgsz 960
    python inference.py --input doc.pdf --no-save-img

输出目录（默认 output/）：
    output/<时间戳>/annotated/*.jpg     标注图（--save-img）
    output/<时间戳>/results.json        检测结果 JSON（文件/页 + bbox + conf + cls）
"""

import argparse
import glob
import json
import sys
import time
from pathlib import Path

try:
    from ultralytics import YOLO
except ImportError:
    sys.exit("未安装 ultralytics，请先执行: pip install ultralytics")


def parse_args():
    p = argparse.ArgumentParser(description="MolDetv2-YOLO26 分子检测推理")
    p.add_argument("--input", required=True,
                   help="输入：图片路径 / 通配符（如 imgs/*.png）/ PDF 路径")
    p.add_argument("--model", default=None,
                   help="权重路径，默认自动选择：PDF 输入用 960_doc，其余用 640_general")
    p.add_argument("--imgsz", type=int, default=None,
                   help="推理分辨率（640 或 960），默认按模型自动选择")
    p.add_argument("--conf", type=float, default=0.5, help="置信度阈值（官方示例 0.5）")
    p.add_argument("--iou", type=float, default=0.7, help="NMS IoU 阈值")
    p.add_argument("--device", default=None, help="设备，如 cpu / 0 / mps")
    p.add_argument("--outdir", default="output", help="输出目录")
    p.add_argument("--save-img", action="store_true", default=True,
                   help="保存标注图（默认开）")
    p.add_argument("--no-save-img", action="store_false", dest="save_img",
                   help="不保存标注图，仅输出 JSON")
    return p.parse_args()


def serialize_result(result, src_name):
    """把 ultralytics 的单张预测结果转成可 JSON 序列化的 dict。"""
    boxes = []
    if result.boxes is not None:
        for b in result.boxes:
            boxes.append({
                "cls": int(b.cls[0].item()),
                "label": result.names[int(b.cls[0].item())],
                "conf": round(float(b.conf[0].item()), 5),
                "xyxy": [round(float(v), 2) for v in b.xyxy[0].tolist()],
            })
    return {"source": src_name, "boxes": boxes, "n": len(boxes)}


def main():
    args = parse_args()
    here = Path(__file__).resolve().parent
    weights_dir = here / "weights" / "moldet"

    src = args.input
    is_pdf = Path(src).suffix.lower() == ".pdf"

    # 模型自动选择
    if args.model:
        model_path = Path(args.model)
    elif is_pdf:
        model_path = weights_dir / "moldet_v2_yolo26n_960_doc.pt"
    else:
        model_path = weights_dir / "moldet_v2_yolo26n_640_general.pt"
    if not model_path.exists():
        sys.exit(f"权重不存在: {model_path}")
    imgsz = args.imgsz or (960 if "960" in model_path.name else 640)

    print(f"[1/3] 加载模型: {model_path}")
    print(f"     推理尺寸: {imgsz} | conf={args.conf} | iou={args.iou} | device={args.device or 'auto'}")
    model = YOLO(str(model_path))

    save_dir = here / args.outdir / time.strftime("%Y%m%d_%H%M%S")
    save_dir.mkdir(parents=True, exist_ok=True)

    # 输入收集
    sources = []
    if is_pdf:
        print("[2/3] 渲染 PDF 页面...")
        import fitz  # PyMuPDF
        pages_dir = save_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(src)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            png = pages_dir / f"page_{i:03d}.png"
            pix.save(str(png))
            sources.append(str(png))
        print(f"     共 {len(sources)} 页，已渲染到 {pages_dir}")
    elif "*" in src or "?" in src:
        sources = sorted(glob.glob(src))
        print(f"[2/3] 匹配到 {len(sources)} 张图片")
    else:
        if not Path(src).exists():
            sys.exit(f"输入不存在: {src}")
        sources = [src]

    # 推理
    print(f"[3/3] 推理中（每张图预计 <1s）...")
    results_all = []
    annot_dir = save_dir / "annotated"
    for i, s in enumerate(sources, 1):
        results = model.predict(
            source=s, imgsz=imgsz, conf=args.conf, iou=args.iou,
            device=args.device, save=args.save_img,
            project=str(annot_dir), name=".", exist_ok=True,
            verbose=False, line_width=3,
        )
        res = serialize_result(results[0], Path(s).name)
        results_all.append(res)
        print(f"     [{i}/{len(sources)}] {Path(s).name}: 检出 {res['n']} 个分子")

    # 输出 JSON
    json_path = save_dir / "results.json"
    json_path.write_text(
        json.dumps({"model": str(model_path), "imgsz": imgsz,
                    "conf": args.conf, "iou": args.iou, "results": results_all},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")

    print(f"\n完成。结果目录: {save_dir}")
    print(f"  JSON: {json_path}")
    if args.save_img:
        print(f"  标注图: {annot_dir}")


if __name__ == "__main__":
    main()
