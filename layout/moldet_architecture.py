# -*- coding: utf-8 -*-
"""
MolDetv2-YOLO26 模型架构解析脚本（UniParser）

功能：
    1. 输出模型元信息（任务、类别、层数、参数量、GFLOPs、设计要点）
    2. 展开 YOLO26n 的 backbone / head 结构配置
    3. 通过 forward hook 实测每一层模块、参数量、输出张量形状
    4. 输出 Detect 检测头细节（strides / 输出通道 / end2end）
    5. 生成 docs/architecture_report.md 架构报告

用法：
    python architecture.py [--model weights/moldet_v2_yolo26n_640_general.pt] [--imgsz 640]
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import torch
    from ultralytics import YOLO
except ImportError:
    sys.exit("未安装 torch / ultralytics，请先执行: pip install ultralytics")


def hook_shape(o):
    """把 hook 输出规整成可读的形状描述。"""
    if isinstance(o, torch.Tensor):
        return list(o.shape)
    if isinstance(o, (list, tuple)):
        return [hook_shape(x) for x in o]
    return type(o).__name__


def analyze(model_path: Path, imgsz: int) -> dict:
    m = YOLO(str(model_path))
    det = m.model
    y = det.yaml
    det.eval()

    # ---- 1. 元信息（官方 info() 摘要经异步 LOGGER 打印，不可靠；直接统计/计算）----
    layers_n = sum(1 for _ in det.modules())  # 递归子模块总数（与官方 260 一致）
    params_n = sum(p.numel() for p in det.parameters())
    grads_n = sum(p.numel() for p in det.parameters() if p.requires_grad)
    try:
        from ultralytics.utils.torch_utils import get_flops
        flops_n = round(float(get_flops(det, imgsz)), 2)
    except Exception:
        flops_n = None
    meta = {
        "weights": str(model_path),
        "arch_file": y.get("yaml_file"),
        "scale": y.get("scale"),
        "task": m.task,
        "nc": y.get("nc"),
        "names": m.names,
        "imgsz": imgsz,
        "layers": layers_n,
        "params": params_n,
        "gradients": grads_n,
        "gflops": flops_n,
        "end2end": y.get("end2end"),
        "reg_max": y.get("reg_max"),
        "scales": y.get("scales"),
    }

    # ---- 2. 逐层实测（模块名 / 参数 / 输出形状）----
    layers = []
    shapes = {}
    handles = []
    for i, layer in enumerate(det.model):
        layers.append({
            "idx": i,
            "module": type(layer).__name__,
            "params": sum(p.numel() for p in layer.parameters()),
        })
        handles.append(layer.register_forward_hook(
            lambda mod, inp, out, _i=i: shapes.__setitem__(_i, hook_shape(out))))
    with torch.no_grad():
        det(torch.zeros(1, 3, imgsz, imgsz))
    for h in handles:
        h.remove()
    for i, l in enumerate(layers):
        l["out_shape"] = shapes.get(i)

    # ---- 3. Detect 头细节 ----
    detect = det.model[-1]
    detect_info = {}
    if hasattr(detect, "stride"):  # 三特征层真实步长 [8, 16, 32]
        strides = [int(s) for s in detect.stride.tolist()]
        detect_info["strides"] = strides
        detect_info["feature_maps"] = [f"{imgsz // s}×{imgsz // s}" for s in strides]
        detect_info["anchor_points_total"] = sum((imgsz // s) ** 2 for s in strides)
    detect_info["nc"] = detect.nc if hasattr(detect, "nc") else None
    detect_info["reg_max"] = detect.reg_max if hasattr(detect, "reg_max") else None
    detect_info["end2end"] = detect.end2end if hasattr(detect, "end2end") else None
    if hasattr(detect, "no"):
        detect_info["num_outputs_per_anchor"] = detect.no

    return {"meta": meta, "yaml": y, "layers": layers, "detect": detect_info}


def to_md(data: dict) -> str:
    meta, y, layers, det = data["meta"], data["yaml"], data["layers"], data["detect"]
    L = []

    L.append(f"# MolDetv2-YOLO26 模型架构报告\n")
    L.append(f"- 权重: `{meta['weights']}`")
    L.append(f"- 结构文件: `{meta['arch_file']}` (scale={meta['scale']})")
    L.append(f"- 任务: {meta['task']} | 类别: {meta['nc']} (`{meta['names']}`)")
    gflops = f"{meta['gflops']}" if meta["gflops"] is not None else "N/A"
    L.append(f"- 顶层结构模块: {len(layers)}（ultralytics 官方 summary 口径为 260 层）| 参数量: {meta['params']:,} | GFLOPs: {gflops} @ {meta['imgsz']}px")
    L.append(f"- 检测头: end2end={meta['end2end']} (免 NMS), reg_max={meta['reg_max']} (无 DFL 分布回归)")
    L.append(f"- 缩放系数 scales.n = {meta['scales']['n']} (depth, width, max_channels)\n")

    L.append("## 逐层结构（forward hook 实测，输入 1×3×640×640）\n")
    L.append("| # | 模块 | 参数量 | 输出形状 | 阶段 |")
    L.append("|---|------|-------:|----------|------|")
    backbone_ids = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10}
    for l in layers:
        stage = "Backbone" if l["idx"] in backbone_ids else "Neck/Head"
        out = json.dumps(l["out_shape"], ensure_ascii=False)
        L.append(f"| {l['idx']} | {l['module']} | {l['params']:,} | `{out}` | {stage} |")

    L.append("\n## 检测头（Detect）\n")
    for k, v in det.items():
        L.append(f"- {k}: `{v}`")
    L.append("\n- 输出 `[1, 300, 6]`：300 = end2end 模式 TopK 候选框；6 = [x1, y1, x2, y2, conf, cls]")
    L.append("- 三个特征层 P3(80×80) / P4(40×40) / P5(20×20)，分别对应 stride 8 / 16 / 32\n")

    L.append("## YOLO26n 结构配置（yaml 原样）\n")
    L.append("```json")
    L.append(json.dumps({"backbone": y["backbone"], "head": y["head"]}, ensure_ascii=False, indent=2))
    L.append("```\n")
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="MolDetv2-YOLO26 架构解析")
    p.add_argument("--model", default=None, help=".pt 权重路径（默认 640_general）")
    p.add_argument("--imgsz", type=int, default=640, help="用于实测输出形状的输入尺寸")
    p.add_argument("--out", default=None, help="报告输出路径（默认 docs/architecture_report.md）")
    args = p.parse_args()

    here = Path(__file__).resolve().parent
    model_path = Path(args.model) if args.model else \
        here / "weights" / "moldet" / "moldet_v2_yolo26n_640_general.pt"
    if not model_path.exists():
        sys.exit(f"权重不存在: {model_path}")

    print(f"解析模型: {model_path}\n")
    data = analyze(model_path, args.imgsz)

    print("=" * 70)
    m = data["meta"]
    print(f"模型: {m['arch_file']} (scale={m['scale']}) | 任务: {m['task']} | 类别: {m['nc']} {m['names']}")
    print(f"顶层结构模块: {len(data['layers'])} | 参数: {m['params']:,} | GFLOPs: {m['gflops']} @ {args.imgsz}px")
    print(f"end2end(免NMS)={m['end2end']} | reg_max={m['reg_max']}")
    print("=" * 70)
    print(f"{'#':>3} {'模块':<12} {'参数量':>10}  输出形状")
    for l in data["layers"]:
        print(f"{l['idx']:>3} {l['module']:<12} {l['params']:>10,}  {json.dumps(l['out_shape'])}")
    print("=" * 70)
    print("Detect 头:", json.dumps(data["detect"], ensure_ascii=False))

    md = to_md(data)
    out = Path(args.out) if args.out else here / "docs" / "architecture_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"\n架构报告已保存: {out}")


if __name__ == "__main__":
    main()
