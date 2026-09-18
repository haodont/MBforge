# -*- coding: utf-8 -*-
"""
基于 MolDetv2-YOLO26 C2PSA 注意力特征（L10）的简单图像分类器

用途：
    三类分类：纯分子图 / 反应式图 / 无分子图
    由此可推导两个问题的答案：
      - 有没有分子？  类别为 纯分子 或 反应式  → 有
      - 纯分子还是反应式？ 分类结果即答案

特征：L10 C2PSA 输出 [1,256,20,20] → 全局平均池化 → 256 维向量
分类器：两隐层 MLP（256→128→C，ReLU + Dropout），CrossEntropy，Adam

用法：
    # 训练（数据按文件夹组织）
    python attention_classifier.py train --data data/train --val data/val --out model.pt

    # 预测
    python attention_classifier.py predict --model model.pt --input img.png
    python attention_classifier.py predict --model model.pt --input "imgs/*.png"

数据布局（文件夹名即类别，建议关键词：molecule / reaction / no_molecule）：
    data/train/
        molecule/      纯分子结构图
        reaction/      反应式（反应箭头、多分子）
        no_molecule/   无分子（文字、表格、空白页等）
    data/val/          同结构，可省略（省略则从 train 中划 20% 验证）
"""

import argparse
import glob
import json
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from ultralytics import YOLO

HERE = Path(__file__).resolve().parent
DEFAULT_WEIGHTS = HERE / "weights" / "moldet" / "moldet_v2_yolo26n_640_general.pt"

# 类别名 → 语义的推断规则（predict 输出时使用，可按需修改）
def infer_semantics(class_names):
    rules = {"no": [], "reaction": []}
    for name in class_names:
        low = name.lower()
        if any(k in low for k in ("no_mol", "nomol", "none", "blank", "empty", "no_")):
            rules["no"].append(name)
        elif any(k in low for k in ("react", "rxn", "scheme")):
            rules["reaction"].append(name)
    return rules


class MLP(nn.Module):
    def __init__(self, in_dim, n_class):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(in_dim, 128), nn.ReLU(), nn.Dropout(0.3),
            nn.Linear(128, 64), nn.ReLU(), nn.Dropout(0.2),
            nn.Linear(64, n_class),
        )

    def forward(self, x):
        return self.net(x)


def extract_features(model, img_paths, layer=10, imgsz=640, device=None, batch=16):
    """对每张图提取第 layer 层的特征（GAP 池化为定长向量）。"""
    det = model.model
    captured = {}
    handle = det.model[layer].register_forward_hook(
        lambda m, i, o: captured.__setitem__("f", o.detach()))

    vecs = []
    for i in range(0, len(img_paths), batch):
        chunk = img_paths[i:i + batch]
        for p in chunk:
            model.predict(source=str(p), imgsz=imgsz, device=device, verbose=False)
            f = captured["f"]  # [1, C, H, W]
            vecs.append(nn.functional.adaptive_avg_pool2d(f, 1).flatten().cpu().numpy())
    handle.remove()
    return np.stack(vecs)


def collect(data_dir):
    """把 data_dir/{cls}/*.图片 收集成 (paths, labels, class_names)。"""
    exts = ("*.png", "*.jpg", "*.jpeg", "*.bmp", "*.webp", "*.tif", "*.tiff")
    data_dir = Path(data_dir)
    paths, labels = [], []
    classes = sorted(d.name for d in data_dir.iterdir() if d.is_dir())
    if not classes:
        sys.exit(f"数据目录下没有类别子文件夹: {data_dir}")
    for cls in classes:
        files = []
        for e in exts:
            files += sorted(glob.glob(str(data_dir / cls / e)))
        paths += files
        labels += [cls] * len(files)
    if not paths:
        sys.exit(f"数据目录为空（未找到图片）: {data_dir}")
    return paths, labels, classes


def load_model(weights):
    m = YOLO(str(weights))
    return m


def main():
    p = argparse.ArgumentParser(description="C2PSA 注意力特征简单分类器")
    sub = p.add_subparsers(dest="cmd", required=True)

    tr = sub.add_parser("train", help="训练分类器")
    tr.add_argument("--data", required=True, help="训练数据目录（含类别子文件夹）")
    tr.add_argument("--val", default=None, help="验证数据目录（可选）")
    tr.add_argument("--out", default="attention_cls.pt", help="输出模型路径")
    tr.add_argument("--layer", type=int, default=10, help="特征层序号（默认 10 = C2PSA）")
    tr.add_argument("--imgsz", type=int, default=640)
    tr.add_argument("--epochs", type=int, default=40)
    tr.add_argument("--device", default=None)

    pr = sub.add_parser("predict", help="预测图片类别")
    pr.add_argument("--model", required=True, help="训练好的模型 .pt")
    pr.add_argument("--input", required=True, help="图片或通配符")
    pr.add_argument("--layer", type=int, default=10)
    pr.add_argument("--imgsz", type=int, default=640)
    pr.add_argument("--device", default=None)
    pr.add_argument("--weights", default=str(DEFAULT_WEIGHTS), help="检测权重（特征提取用）")
    args = p.parse_args()

    if args.cmd == "train":
        train(args)
    else:
        predict(args)


def train(args):
    paths, labels, classes = collect(args.data)
    print(f"训练集: {len(paths)} 张 | 类别: {classes}")
    y = np.array([classes.index(c) for c in labels])

    if args.val:
        vpaths, vlabels, vclasses = collect(args.val)
        if vclasses != classes:
            sys.exit(f"训练/验证类别不一致: {classes} vs {vclasses}")
        vy = np.array([classes.index(c) for c in vlabels])
    else:
        idx = np.random.RandomState(0).permutation(len(paths))
        n_val = max(1, int(len(paths) * 0.2))
        vpaths, vy = [paths[i] for i in idx[:n_val]], y[idx[:n_val]]
        paths, y = [paths[i] for i in idx[n_val:]], y[idx[n_val:]]
    print(f"验证集: {len(vpaths)} 张")

    print(f"提取 L{args.layer} 注意力特征（GAP→定长向量）...")
    m = load_model(DEFAULT_WEIGHTS)
    X = extract_features(m, paths, layer=args.layer, imgsz=args.imgsz, device=args.device)
    Xv = extract_features(m, vpaths, layer=args.layer, imgsz=args.imgsz, device=args.device)
    in_dim = X.shape[1]
    print(f"特征维度: {in_dim}")

    Xt = torch.tensor(X, dtype=torch.float32)
    yt = torch.tensor(y, dtype=torch.long)
    Xvt = torch.tensor(Xv, dtype=torch.float32)
    yvt = torch.tensor(yv := np.array(vy), dtype=torch.long)

    model = MLP(in_dim, len(classes))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = nn.CrossEntropyLoss()
    bs = min(16, len(Xt))
    best = (0.0, None)
    for epoch in range(1, args.epochs + 1):
        model.train()
        perm = torch.randperm(len(Xt))
        tot = 0.0
        for i in range(0, len(Xt), bs):
            idx = perm[i:i + bs]
            opt.zero_grad()
            out = model(Xt[idx])
            loss = loss_fn(out, yt[idx])
            loss.backward()
            opt.step()
            tot += loss.item() * len(idx)
        model.eval()
        with torch.no_grad():
            acc = (model(Xvt).argmax(1) == yvt).float().mean().item()
        if acc > best[0]:
            best = (acc, {k: v.clone() for k, v in model.state_dict().items()})
        if epoch % 10 == 0 or epoch == args.epochs:
            print(f"  epoch {epoch:>3}/{args.epochs} | loss {tot / len(Xt):.4f} | val acc {acc:.3f}")

    model.load_state_dict(best[1])
    torch.save({
        "state_dict": model.state_dict(),
        "class_names": classes,
        "in_dim": in_dim,
        "layer": args.layer,
        "val_acc": best[0],
    }, args.out)
    print(f"完成。验证准确率 {best[0]:.3f}，模型已保存: {args.out}")


def predict(args):
    ckpt = torch.load(args.model, map_location="cpu")
    classes = ckpt["class_names"]
    model = MLP(ckpt["in_dim"], len(classes))
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    rules = infer_semantics(classes)

    inputs = sorted(glob.glob(args.input)) if any(c in args.input for c in "*?") else [args.input]
    if not inputs:
        sys.exit(f"没有匹配的输入: {args.input}")

    m = load_model(args.weights)
    X = extract_features(m, inputs, layer=ckpt.get("layer", args.layer),
                         imgsz=args.imgsz, device=args.device)
    with torch.no_grad():
        probs = torch.softmax(model(torch.tensor(X, dtype=torch.float32)), dim=1).numpy()

    for path, prob in zip(inputs, probs):
        cls = classes[int(prob.argmax())]
        has_mol = cls not in rules["no"] if rules["no"] else cls not in ()
        if cls in rules["reaction"]:
            itype = "反应式图片"
        elif cls in rules["no"]:
            itype = "无分子图片"
        else:
            itype = "纯分子图片"
        print(f"{Path(path).name}: {itype} | 含分子: {'是' if has_mol else '否'} | "
              f"置信度 {prob.max():.3f} | 各类 {dict(zip(classes, [round(float(x), 3) for x in prob]))}")


if __name__ == "__main__":
    main()
