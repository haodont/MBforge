# MolDetv2-YOLO26 (UniParser) 分子检测

从 ModelScope 拉取的 **MolDetv2（YOLO26 版）** 权重与可运行脚本，用于在文献图片 / PDF 中检测分子结构区域。

> **位置说明**：本模块已并入 `layout/`（版面识别），因为**版面模型抓不到化学结构式**，
> 真正承重的是 MolDet（见 `README.md` §1 / §12.5）。文件对应关系：
>
> | 原 UniParser 仓库 | 现在 |
> | --- | --- |
> | `inference.py` | `layout/moldet.py` |
> | `architecture.py` | `layout/moldet_architecture.py` |
> | `attention_classifier.py` | `layout/moldet_attention.py` |
> | `weights/` | `layout/weights/moldet/` |
> | `test_aspirin.png` | `layout/test_aspirin.png` |
> | `docs/` | `layout/moldet_docs/` |

* 模型仓库: ModelScope `UniParser/MolDetv2-YOLO26`
* 上游: [UniParser/MolDetv2](https://huggingface.co/UniParser/MolDetv2)（深势科技 DP Technology）
* 许可证: **CC-BY-NC-SA-4.0，仅限非商用**；商用请联系 fangxi@dp.tech
* 引用: Fang et al., *MolParser-Mobile: Ultrafast OCSR System for Large-Scale Chemical Literature Mining*, arXiv:2609.05807

## 目录结构

```
layout/weights/moldet/                # 模型权重（ModelScope 拉取）
├── moldet_v2_yolo26n_640_general.pt / .onnx   # 640px 通用分子检测
├── moldet_v2_yolo26n_960_doc.pt / .onnx       # 960px 文档(文献)检测
└── README.md / configuration.json             # ModelScope 模型卡与元数据

layout/
├── moldet.py                         # 推理脚本（图片 / 批量 / PDF）
├── moldet_architecture.py            # 模型架构解析脚本
├── moldet_attention.py               # 注意力特征分类器实验
├── test_aspirin.png                  # 测试图（PubChem 阿司匹林）
└── moldet_docs/                      # 架构解析报告（脚本自动生成）
    ├── architecture_report.md
    └── architecture.html
```

## 环境要求

* Python 3.10+
* 依赖见 `layout/requirements.txt`（`ultralytics>=8.3` 等）；正式依赖以项目根的 `pyproject.toml` + `uv` 为准
* `.pt` 权重直接走 **ultralytics（PyTorch）** 后端；`.onnx` 仅作纯 CPU 推理备选（需自行安装 `onnxruntime`，非必需）

## 推理

官方用法：

```python
from ultralytics import YOLO
model = YOLO("weights/moldet/moldet_v2_yolo26n_640_general.pt")   # 通用图像
model.predict("img.png", save=True, imgsz=640, conf=0.5)
model = YOLO("weights/moldet/moldet_v2_yolo26n_960_doc.pt")       # PDF 文档
model.predict("page.png", save=True, imgsz=960, conf=0.5)
```

本模块脚本（自动选择模型、输出 JSON + 标注图）：

```powershell
cd "C:\Users\10954\Desktop\ChemLayout\layout"
python moldet.py --input test_aspirin.png              # 单张图片（640 模型）
python moldet.py --input "imgs/*.png" --conf 0.3       # 批量
python moldet.py --input paper.pdf                     # PDF（自动用 960_doc 模型）
python moldet.py --input paper.pdf --no-save-img       # 只要 JSON
```

结果输出到 `output/<时间戳>/`：`results.json`（每张图 / 每页的 bbox、置信度、类别）+ `annotated/` 标注图。类别仅一种：`molecule`。

> 生产路径不用这个 CLI，而是 `layout/pipeline.py::load_moldet` + `detect_page`（见 `layout/README.md` §4.1）。

## 架构解析

```powershell
python moldet_architecture.py
```

输出模型总览（任务、类别、参数量、GFLOPs）、逐层模块与实测输出张量形状、Detect 头细节（strides / 特征层 / 锚点数），并生成 `moldet_docs/architecture_report.md`。核心结论：

* **结构**: YOLO26n（ultralytics 官方 summary: 260 层 / 2,504,190 参数 / 5.8 GFLOPs @ 640）
* **Backbone**: 2×Conv (k3,s2) 下采样 + C3k2 + SPPF + C2PSA（PSA 注意力），通道 16→32→64→128→256
* **Neck/Head**: FPN 上采样 - Concat 融合 P3/P4，PAN 自顶向下，最终三特征层 P3 (80×80) / P4 (40×40) / P5 (20×20)
* **Detect 头**: `end2end=True`（免 NMS）、`reg_max=1`（无 DFL 分布回归）、nc=1，输出 `[1, 300, 6]`

## 注意力特征分类器（纯分子 / 反应式 / 无分子）

用 L10 C2PSA 注意力层输出（GAP→256 维）训练一个简单 MLP，判断图片类型；"有无分子"由类别推导（纯分子/反应式=有，无分子=无）。

数据按文件夹组织（文件夹名即类别，建议关键词 molecule / reaction / no_molecule）：

```
data/train/molecule/*.png       纯分子结构图
data/train/reaction/*.png       反应式（反应箭头、多分子）
data/train/no_molecule/*.png    无分子（文字、表格、空白页）
data/val/…                      同结构，可省略（自动划 20% 验证）
```

```powershell
python moldet_attention.py train --data data/train --out model.pt --epochs 40
python moldet_attention.py predict --model model.pt --input img.png
```

提示：判"有没有分子"最直接可信的信号是检测头本身（`moldet.py` 的检测框数量/置信度）；L10 特征分类器更适合"纯分子 vs 反应式"这类检测头无法区分的版面级判断。
