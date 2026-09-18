# layout —— 版面识别（Hiro-Layout + MolDetv2-YOLO26）

ChemLayout 的**版面识别层**。对应 `../DESIGN.md` §0.1 / §3 / §4.2 / §5。

**当前实现范围**：Hiro-Layout（区域检测）+ MolDetv2-YOLO26（分子检测）跑在**同一张 144 DPI 页面图**上，
合并为一份类型化 `Region` 列表，并渲染叠加图。

**不在范围内**（未实现）：任何**识别**——无 OCR、无表格结构还原、无公式识别、无分子结构→SMILES。
`image` / `chart` 区域**只出 bbox 四元组，不做任何识别**（不主动识别图片内容）。

> **版本说明**：早期版本以 PP-DocLayoutV3（下称 V3）为主方案、Hiro 为"候选二"。
> 实测后**已改为 Hiro 为主**（依据见 §12.5 / §12.8），V3 降为对照基线（`v3.py`，不在生产路径上）。
> 本 README 保留了 V3 时期的实测数据——它们仍是判定输入尺寸/精度/合并规则的依据。

---

## 1. 检测内容与实现

| 模型 | 职责 | 权重 | 运行时 |
| --- | --- | --- | --- |
| **Hiro-Layout**（PatSnap，RT-DETR-X） | 出 text / table / header / footer / image / chart / chem / rxn / mnote / figno 等区域框 | `weights/hiro/`（250.31 MiB） | **onnxruntime-gpu**（ONNX-only） |
| **MolDetv2-YOLO26**（960_doc，UniParser） | 出 molecule 框 | `weights/moldet/`（5.21 MB） | ultralytics / PyTorch |
| PP-DocLayoutV3（**对照基线，非生产路径**） | 同上（V3 词表，无 chem/rxn） | `weights/v3/`（127.10 MiB） | transformers / PyTorch |

三者跑在**同一张 144 DPI 页面图**上，坐标天然同构（见 §5），无需二次映射。

> ⚠️ **`Hiro ∪ MolDet` 的并集是承重设计，不是可选叠加**：实测**两个版面检测器都几乎抓不到
> 化学结构式**（中位召回 0.000），真实结构式全靠 MolDet 兜底。依据见 §12.5。

---

## 2. 环境：统一用 MBForge 的 venv

| 项 | 值 |
| --- | --- |
| venv | `C:\Users\10954\Desktop\MBForge\.venv` |
| 关键包 | **onnxruntime-gpu 1.30.0**（Hiro 的 CUDA EP）、torch 2.11.0+cu128、transformers 5.17.0、ultralytics 8.4.150、rapidocr 3.9.2 |

```powershell
$PY = "C:\Users\10954\Desktop\MBForge\.venv\Scripts\python.exe"
```

**2026-09-18 变更**：该 venv 原先是 `onnxruntime 1.29.0` **CPU 版**（`get_available_providers()`
里连 `CUDAExecutionProvider` 都没有），Hiro 只能跑 CPU（742 ms/页）。
现已换成 GPU 版，实测 `session.get_providers()` 返回 `['CUDAExecutionProvider', 'CPUExecutionProvider']`
—— **CUDA 在前，真在 GPU**。详见 `../RUNTIME-PYTORCH.md` §2.1。

> 项目自有的 `..\.venv`（2.07 GB）因此**不再需要**，尚未删除。
>
> ⚠️ **装完 `onnxruntime-gpu` 后必须注意加载顺序**：`preload_dlls()` 会抢走 torch 自带的
> 同名 `cudnn_cnn64_9.dll`，导致 `import torch` 崩 `WinError 127`。
> `hiro.py::_preload_gpu_dlls` 已先 `import torch` 兜住。详见 `../RUNTIME-PYTORCH.md` §3 陷阱 7。

### 2.1 环境陷阱（已踩，勿重蹈）

1. **`huggingface.co` 本机不可达**（连接超时/拒绝）。`hf-mirror.com` 可达，但其 Xet 后端
   （`cas-server.xethub.hf.co`）返回 **401**，`model.safetensors` 下载必失败，需 `HF_HUB_DISABLE_XET=1`。
   → 本模块**默认走 ModelScope**。
2. **清华 PyPI 镜像在 Windows 上只给 CPU-only torch**（会装成 `2.14.0+cpu`，`torch.cuda.is_available()=False`）。
   CUDA 版必须走 `--index-url https://download.pytorch.org/whl/cu126`。复用 MBForge venv 可完全绕开。
3. **ModelScope 上有两个同名仓库**：`PaddlePaddle/PP-DocLayoutV3` 是 `.pdiparams`（**Paddle 格式，transformers 加载不了**）；
   必须用 **`PaddlePaddle/PP-DocLayoutV3_safetensors`**。

---

## 3. 权重与样本

```powershell
& $PY fetch_weights.py          # 从 ModelScope 拉 PP-DocLayoutV3_safetensors
```

`weights/PP-DocLayoutV3/`：`model.safetensors` 133,270,468 B + `config.json` + `preprocessor_config.json` + `inference.yml`。

`samples/` 是从 `../Sample/` 复制的 4 页真实化学专利（另有 `../Sample/` 全集 32 页供批量脚本使用）：

| 文件 | 尺寸 | 内容 |
| --- | --- | --- |
| `cn_mrgprx2_p405.png` | 3173×4491 | 3 个结构式、页眉三段、页码、`[0719]-[0721]` 段号、含上下标的 MS 数据 |
| `cn_mrgprx2_p419.png` | 3173×4491 | 同上 |
| `us_202619539414a_p45.png` | 3264×4224 | 两栏版式、1 个反应式、化学表格、5 个结构式 |
| `us_202619539414a_p50.png` | 3264×4224 | 同上 |

⚠️ **样本是 ~384 DPI，不是设计契约的 144 DPI**（3173 px / 595.28 pt = 5.33 px/pt = 384 DPI）。
所有脚本默认 `--src-dpi 384 --dpi 144`，先降采样到契约分辨率再推理，输出的 `bbox_pdf` 才符合 2 px/pt 约定。

---

## 4. 用哪个脚本

| 脚本 | 用途 |
| --- | --- |
| **`detect_overlay.py`** | **CLI 入口。** 调用 pipeline → 渲染叠加图 + JSON；`--layout hiro|v3` 选检测器 |
| **`pipeline.py`** | 可复用接口：模型加载（`load_hiro`/`load_v3`/`load_moldet`）、页面准备、检测、合并、扁平 evidence；不写文件或绘图 |
| `test_pipeline.py` | 真实单页 API 冒烟检查；可选对比重构前后 JSON 和叠加图 |
| `merge.py` | 合并规则 R1–R5。独立模块，可 import 复用 |
| `hiro.py` | **Hiro-Layout 适配**（ONNX）；`--list-labels` 并列打印 ONNX 元数据与官方 `labels.json` |
| `v3.py` | 仅 V3（**对照基线**）；含冒烟检查（`--verify`）与标签表（`--list-labels`） |
| `moldet.py` | **MolDetv2-YOLO26 分子检测**；图片/通配符/PDF 输入，输出 JSON + 标注图 |
| `moldet_architecture.py` | MolDet 架构解析（层数/参数量/GFLOPs/Detect 头细节） |
| `moldet_attention.py` | MolDet L10 注意力特征分类器实验（纯分子 / 反应式 / 无分子） |
| `bench_hiro_gpu.py` | Hiro GPU 批量基准（同进程背靠背，见 §12.4.1） |
| `eval_layout_quality.py` | 双向质量评测：PDF 文本层 + 矢量图形做真值（见 §12.5） |
| `sweep_imgsz.py` | V3 输入尺寸扫描 15 档并出曲线图（`--plot-only` 可只重绘） |
| `compare_dtype.py` | V3 精度（fp32/bf16/fp16）× 尺寸对比，含框级一致性 |
| `compare_inputsize.py` | V3 非方形尺寸的叠加图对比（人工逐张看） |
| `compare_det.py` | V3 vs RapidOCR 的检出对比（用于论证必须按区域路由） |
| `bench.py` | V3 速度基准 |
| `sample_from_pdf.py` | 从 PDF 随机抽样补足样本集（固定种子可复现） |
| `fetch_weights.py` | 权重拉取（`--model hiro|v3`） |

```powershell
Set-Location "C:\Users\10954\Desktop\ChemLayout\layout"

# —— 生产路径：Hiro ∪ MolDet ——
& $PY detect_overlay.py --layout hiro --merge --samples ..\Sample `
      --src-dpi 144 --dpi 144 --out out\hiro

# —— 对照路径：V3 ∪ MolDet ——
& $PY detect_overlay.py --layout v3 --merge --limit 4

# 只看版面（不跑 MolDet）
& $PY detect_overlay.py --layout hiro --no-moldet --limit 4

# 标签表 / 单页可视化
& $PY hiro.py --list-labels
& $PY hiro.py --image ..\Sample\CN117180334A_FullTextImage_p0006.png --save-vis
```

产物：`out\overlay_merged\*.overlay.jpg`（每页一张，左上有图例）+ `out\overlay_merged\detections.json` + `out\overlay_merged\evidence.json`。

### 4.1 Python 模块调用

从项目根目录调用；模型在循环外加载一次，调用方负责保存结果：

```python
from pathlib import Path
from layout.pipeline import (
    MOLDET_WEIGHTS, load_hiro, load_v3, load_moldet, page_image,
    detect_page, merge_page, to_evidence_page,
)

det = load_hiro(input_size=640)          # 或 load_v3()
moldet = load_moldet(MOLDET_WEIGHTS["960_doc"])
for path in sorted(Path("Sample").glob("*.png")):
    image = page_image(path, src_dpi=144, dpi=144)
    regions, molecules, page, timing = detect_page(
        image, det, moldet, doc_id=path.stem, page_num=1, dpi=144, imgsz=640)
    merged, stats = merge_page(regions, molecules, page, doc_id=path.stem)
    evidence = to_evidence_page(regions, molecules, page, doc_id=path.stem)
```

`detect_page` 的第二个参数在代码里仍叫 `v3`，**两个检测器同签名可直接互换**（这是刻意的，便于对照）。
它接收已按目标 DPI 准备的 RGB 页面图，不自动缩放；返回原始区域、原始分子框、页面坐标元数据及 `v3_ms/mol_ms/area_dropped`。
传 `mol_model=None` 可关闭分子检测。`doc_id/page_num` 在检测、合并和 evidence 调用中必须一致；CLI 保留原来的文件名作为 doc_id、page_num=1 约定。
`merge_page` 接受合并 `params`；`to_evidence_page` 接收原始检测结果，执行 R1/R2/R5、跳过 R3/R4，分子扁平输出，几何仲裁仍交下游。
`load_moldet` 接收权重文件路径，缺失时抛出 `FileNotFoundError`。旧的 `detect_overlay.MODEL_V3/MOLDET_WEIGHTS` 与绘图函数导入保持兼容。

在 layout 目录验证（需要本地权重及 Sample 页面）：

```powershell
& $PY test_pipeline.py
& $PY test_pipeline.py --compare <重构前输出目录> <重构后输出目录>
```

对比只排除输出目录及耗时字段；其余 JSON 严格相等，叠加图逐字节比较。
⚠️ `test_pipeline.py` 默认走 V3 路径，需 MBForge venv 或给项目 `.venv` 补 torch。

---

## 5. 坐标契约

```
V3 输出（page_image 像素，左上原点，y 向下）== bbox_px
   （page_image 即 144 DPI = 2 px/pt，无需再缩放；post_process 已按 target_sizes 反映射）
   └─ bbox_pdf：x 缩放 1/2，y 翻转 + 偏移 → PDF pt，左下原点，y 向上
```

```python
PX_PER_PT = 2.0   # 144 DPI，与 MBForge _OCR_RENDER_PX_PER_PT 一致

def px_to_pdf_box(box_px, page_height_pt):
    x0, y0, x1, y1 = box_px                      # y 向下
    return (x0 / PX_PER_PT,
            page_height_pt - y1 / PX_PER_PT,     # 下边
            x1 / PX_PER_PT,
            page_height_pt - y0 / PX_PER_PT)     # 上边
```

**⚠️ y0/y1 必须交换**。`DESIGN.md` §3.1 那条 `y_pdf = page_height_pt - y_px/2.0` 若逐坐标套用，会得到
`y0 > y1` 的倒置框，**且不会报错**。多项式（V3 的 `polygon_points`）逐顶点施加同一变换。

**输入尺寸是硬约束，且必须用原生 800×800**（实测，详见 §7.4）：

- V3 的 `feature_strides = [8, 16, 32]`，而 FPN 里有一处直接 concat。因此**输入的宽高都必须是 32 的整数倍**，
  否则直接崩：传 1190×1684 会报 `RuntimeError: Sizes of tensors must match ... Expected size 76 but got size 75`。
- **非方形虽然能跑，但更差**；加大到 960 或原尺寸同样更差。**该 checkpoint 就是针对方形 800 调优的，偏离即退化。**

---

## 6. 标签体系

### 6.1 V3 的 id2label 原始表（25 槽 / 21 个不同标签）

```
 0 abstract          9 footer           18 reference
 1 algorithm        10 footnote         19 reference_content
 2 aside_text       11 formula_number   20 seal
 3 chart            12 header           21 table
 4 content          13 header           22 text
 5 formula          14 image            23 text
 6 doc_title        15 formula          24 vision_footnote
 7 figure_title     16 number
 8 footer           17 paragraph_title
```

**三个必须处理的事实**：

1. **`label2id` 是空对象 `{}`** —— 任何 `config.label2id[label]` 取 cls_id 的代码直接失效。
2. **标签名重复**：`footer` 占 8/9、`header` 占 12/13、`formula` 占 5/15、`text` 占 22/23。
   `{v: k for k, v in id2label.items()}` 这类反查会**静默吞掉** 8/12/5/22。
3. 因此映射表**硬编码在 `inference.py`**（`V3_CLS_TO_LABEL` / `V3_LABEL_TO_CLS_IDS`），
   按类过滤/设阈值时重复 cls_id 必须**全部下发**。

### 6.2 映射到 RegionType

| V3 标签 | → RegionType |
| --- | --- |
| doc_title | `title` |
| text, paragraph_title, content, abstract, algorithm, aside_text, footnote, vision_footnote, reference, reference_content, figure_title, formula_number | `text` |
| **number** | **`page_number`** |
| table | `table` |
| formula | `formula` |
| image | `image` |
| chart | `chart` |
| header / footer | `header` / `footer` |
| seal | `seal` |

**`number` = 页码，已实测证实**：CN 页的 `405` 在页底正中、US 页的 `34` 在页顶正中，
bbox 36×20 / 40×22 px，score 0.75 / 0.67。
→ **代价：V3 不产出 `footer`**，页脚位置的页码由 `number` 承担（实测 `footer` 命中数为 0）。
V3 也**不产出 `toc`**（其标签谱系源自 17 类系列，非 20/23 类系列）。

---

## 7. 实测结果

环境：RTX 3070 Ti Laptop / torch 2.11.0+cu128 / transformers 5.17.0 / F32。
样本：`../Sample/` 全 **100 页**（3 份专利：CN 121398814 A、US 2026/0242367 A1、WO 2025IB63301，
另含从 `打印.pdf` 按 seed=42 随机抽样的 56 页），统一降采样到 144 DPI。
页面尺寸混合 A4(3173–3176×4491) 与 Letter(3264×4224)。

### 7.1 检测量与耗时

**当前配置：V3 @800×800（原生方形，bfloat16）+ MolDet @960（960_doc），conf 均 0.4，V3 面积下限 0.1%。**

| | 数量 | 每页 |
| --- | ---: | ---: |
| V3 区域 | 1415 | 14.2 |
| └ text | 600 | 6.0 |
| └ table | 35 | 0.35 |
| └ image/chart | 93 | 0.93（**仅出 bbox，不识别**） |
| └ 其它（header/footer/page_number/formula/figure_title） | 687 | 6.9 |
| MolDet 分子 | 500 | 5.0 |
| **合并后区域** | **1428** | **14.3** |

V3 的面积过滤另外丢弃 **975** 个碎块——conf 降到 0.4 后，**过滤的主要工作从置信度转移到了面积下限**：
V3 原始输出 2390 个（23.9/页），面积过滤砍掉 41%。

| 阶段 | 稳态中位（3 次同配置运行的区间） |
| --- | ---: |
| V3 | **139 – 175 ms/页** |
| MolDet | 29 – 37 ms/页 |
| **合计** | **169 – 212 ms/页** |

→ 吞吐约 **4.7 – 5.9 页/秒**，一本 500 页专利纯推理约 **85 – 106 秒**。

> ⚠️ **这台笔记本的 GPU 计时噪声极大，跨运行的绝对耗时不可比。**
> 同一配置（fp32@800 / conf 0.4 / 100 页）连续三次测得 V3 中位 **139 / 158 / 175 ms**（±26%），
> 且随连续运行单调变慢（疑为热降频）。**只有同进程内背靠背的比较才有效**（见 §7.5）。
> 上表区间是三次运行的包络，**不要收窄**。
> 相对地，**检出量完全确定**：同一配置多次运行的计数一字不差（1415 / 600 / 35 / 93）。

- **模型加载**（一次性）：V3 ~10–11 s（858 张量 / 127.10 MiB），MolDet 0.10 s。
- **⚠️ 脚本目前没有预热**，所以它自报的均值含第 1 页冷启动（~1300 ms）。
  上表已剔除该页。服务化**必须补预热**，否则首个请求慢 6 倍。

### 7.2 §11.1 冒烟检查（`inference.py --verify`）全部 PASS

| # | 检查 | 结果 |
| --- | --- | --- |
| 1 | 加载 + 前向 | PASS |
| 2 | `polygon_points` 与 `boxes` 同坐标系 | PASS（外接框 IoU 均值 0.92–0.94、最低 0.85；**无需手工缩放**） |
| 3 | 输出顺序即阅读顺序 | PASS（见下） |
| 4 | 坐标往返 px→pdf→px | PASS（20/20） |
| 5 | `bbox_pdf` 满足 y0 < y1 | PASS（0 违例） |
| 6 | 重复 cls_id 映射 | PASS |
| 7 | 区域内嵌检测 | PASS（见 §9.3） |

**第 3 项（重要）**：V3 的输出顺序**就是逻辑阅读顺序，且能正确处理分栏**。判据是与纯光栅序比较时存在
**y 方向回跳**——US 两栏页最大回跳 **323 px**（≈栏高），CN 单栏页 74 px。回跳是"读完左栏换右栏"的签名特征，
**纯光栅排序不可能产生**。US 页实际顺序：左栏（`[0269]` 段落 → 左表）→ 右栏（右表 → Example 5 → Step 1）→ 底部反应式。
→ 下游组装**不必再恢复阅读顺序**，可直接消费输出下标。

### 7.3 `image` 就是分子结构式，`table` 命中化学表格

- CN p405 的 3 个结构 → `image`×3；US p50 的上部分子 + 底部反应式 → `image`×2。
  V3 **没有 molecule 类**，属预期行为，由 MolDet 补类型。
- US 页两张"Compound# / Characterization Data"化学表格**全部命中** `table`。
- US p50 的整个反应式（reactant + 箭头 + 条件 + product）被判成**单个** `image`，交 MolDet 拆分。

### 7.4 输入尺寸（实测）

**硬约束：宽高都必须是 32 的整数倍。** `feature_strides = [8, 16, 32]`，且 FPN 里有一处直接 concat
（`torch.concat([top_fpn_feature_map, backbone_feature_map], dim=1)`）。传页面原尺寸 1190×1684 会直接崩：

```
RuntimeError: Sizes of tensors must match except in dimension 1.
Expected size 76 but got size 75 for tensor number 1 in the list.
```

1684/32 = 52.625、1190/32 = 37.19，都不是整数。

**非方形与偏离原生尺寸都会退化**（4 页样本，conf 0.7）：

| 配置 | 32倍 | 像素 | 区域 | text | table | ms |
| --- | :---: | ---: | ---: | ---: | ---: | ---: |
| 方形 960×960 | ✅ | 921,600 | **54** | **18** | **2** | 135 |
| 保比例 800×1152（同像素预算） | ✅ | 921,600 | 49 | 14 | 2 | 130 |
| 保比例 1184×1664（2.14× 像素） | ✅ | 1,970,176 | 38 | 9 | 1 | 225 |
| 保比例 1664×1184（2.14× 像素） | ✅ | 1,970,176 | 37 | 15 | 1 | 219 |

方形在每一页都最多或并列最多；而用 2.14 倍像素的非方形反而检出更少、还慢 65%。
→ **该 checkpoint 是针对方形 800×800 调优的，偏离即属分布外。**

**全量扫描（100 页 × 15 档，conf 0.4，面积下限 0.1%）** —— 这是选定 800 的依据：

| V3 输入 | 过滤后区域 | text | table | V3 ms | 备注 |
| --- | ---: | ---: | ---: | ---: | --- |
| 512 | 1268 | 568 | 33 | 79 | 检出不足，丢 2 个表 |
| 640 | 1384 | 601 | 34 | 97 | |
| 704 | 1412 | 600 | 35 | 102 | table 达标 |
| 768 | 1439 | 605 | 35 | 139 | |
| **800** | **1415** | 600 | 35 | **107** | **采用** |
| 832 | 1439 | 602 | 35 | 132 | |
| 896 | 1448 | 602 | 35 | 199 | |
| 960 | 1449 | 606 | 35 | 165 | |
| **1024** | **1456（峰值）** | 603 | 35 | 164 | 检出峰值 |
| 1088 | 1438 | 596 | 36 | 169 | |
| 1152 | 1386 | 587 | 37 | 181 | 开始下降 |
| 1280 | 1263 | 527 | 36 | 209 | 最差 |

三条读数：

1. **平台在 768–1088**（1438–1456，波动约 1%），峰值在 1024。曲线是"先升后平再降"。
2. **table 自 576 起就稳定在 35**，与输入尺寸基本无关——只有 512 掉到 33。
3. **耗时在 832 之后跳升**：≤832 约 80–140 ms，≥896 约 160–210 ms。

→ **800 拿到峰值的 97.2%（1415/1456），耗时只有峰值档的 65%（107/164 ms）**，
落在"便宜区间的右端 + 平台区间的左端"，因此采用 **800×800**。

曲线图 `out/sweep_imgsz/sweep_imgsz.png`（X=输入边长，Y=检出量 / table 数 / 耗时），
原始数据 `out/sweep_imgsz/sweep_imgsz.json`；改图用 `sweep_imgsz.py --plot-only` 重绘，不必重跑。

> ⚠️ **不要用小样本判断输入尺寸。** 早期那 4 页小样本**两次**给出与全量相反的结论
> （都显示 960 / 1184 明显优于 800），全量都推翻了。判断尺寸必须用全样本集。

**非方形另测**（4 页，conf 0.7）：保宽高比的 800×1152 / 1184×1664 / 1664×1184 分别只检出
49 / 38 / 37，均不如方形 960 的 54；且 1184×1664 用了 2.14 倍像素反而更少。
→ **非方形属分布外**，方形 800 是唯一采用值。

**为什么不取检出峰值 1024**：峰值 1456 只比 800 的 1415 高 **+2.7%**，而

- 耗时显著更高：扫描内 V3 单页 800→107 ms、1024→164 ms（**+53%**）。该差异由扫描内的
  单调趋势支撑（尺寸越大越慢），比跨运行比较可信。
- 边际收益落在噪声量级：768–1088 整段是平台（1438–1456，波动约 1%），1024 多出的 41 个区域
  不具备区分度。
- bf16 抵消不了它（见 §7.5）：bf16@1024 实测 172 ms，远高于 bf16@800。

→ **结论：保持 800×800**。

### 7.5 bf16：已采用（目的是显存，不是速度）

**采用理由：显存显著降低。** 本模块的耗时余量充足（单页远低于 0.5 s 的感官阈值），
所以提速与否不是判据；显存才是。

**必须先打补丁才能跑**：transformers 的 `post_process_object_detection` 内部会
`.detach().cpu().numpy()`，而 **numpy 不支持 bfloat16**，直接用 bf16 推理会在后处理阶段抛
`TypeError: Got unsupported ScalarType BFloat16`。已在 `inference.py::_cast_outputs_fp32()`
把输出降回 fp32（只影响后处理，不影响 bf16 前向）。

**精度代价（实测，供参考）**：`compare_dtype.py` 在同进程内背靠背对比，
bf16 与 fp32 的**框级一致度 98.6%**（即 1.4% 的框会变），检出量 1421 vs 1415。
**fp16 的一致度是 99.9%**，若你更在意一致性可改用 fp16（同为半精度，显存收益相同）。

**耗时**：本机 GPU 计时噪声大（同一配置多次运行 V3 中位在 127–177 ms 间波动），
**测不出 bf16 的稳定提速**，但也没有稳定的变慢。由于时间不是判据，这不影响采用。

> 通用注意：本机耗时只适合同进程背靠背比较，跨运行的绝对 ms 应视为区间。

---

## 8. 合并规则（`merge.py`）

实现 `DESIGN.md` §4.2 的"区域合并去重"，五条规则按序执行：

| 规则 | 内容 | 阈值 | 100 页命中 |
| --- | --- | --- | ---: |
| **R1** | 同一检测器内部同类重复框去重，保留高分者 | IoU > 0.7 | 移除 **1** |
| **R2** | 文本流内嵌抑制：行内子块降级为父块 span | 子块面积 < 父块 1% 且被父块包含 > 0.8 | 抑制 **27** |
| **R3** | 跨模块 1:1 让位：区域改为 molecule | 分子框与区域 IoU > 0.7 | 让位 **218** |
| **R4** | 跨模块 1:N 容器：保留为容器，分子挂 `children` | 分子框被区域包含 > 0.8 | **55** 个容器 / 收纳 **241** 分子 |
| — | 独立分子（不在任何 image 区域内） | — | 41 |

**校验**：218 + 241 + 41 = **500** = MolDet 检出总数；1428 = 1415 − 1 − 27 + 41。两项都对得上。

> R2 长期稳定在很小量级（早期配置 99 → 现在 27），因为 conf 0.4 + 面积过滤后，
> `formula` 碎块**在检测阶段就被滤掉**，合并阶段不再需要补救。

### 8.1 R4 是必须的（原设计只写了 1:1）

原设计"被包含即让位"在实测中会出错：**p415 的一个 `image` 区域里装着 16 个分子**，
整块让位会把"16 个分子的合成路线"误标成"1 个分子"。故按 **1:1 / 1:N 分治**：
1:1 才整块改判 `molecule`（并保留 V3 多边形作裁剪依据）；1:N 保留为**容器**，分子挂成 `children`，
容器带 `meta.container=True` 与 `meta.molecule_count`，供下游按"图 + N 个分子"渲染而非"图片占位"。

### 8.2 R2 的范围要收紧

可被吞掉的行内类型限定为 `formula / formula_number / figure_title / footnote / vision_footnote /
reference / reference_content`，**刻意不含 `text` 本身**——小 `text` 块可能是合法独立块（表格标题、独立标注），
被父级大文本块吞掉会造成内容丢失。同类重叠交给 R1。

### 8.3 踩过的坑

一个分子若落在**两个重叠容器**内会被重复收纳，导致 53 + 126 + 13 = 194 ≠ 190。
已在 R4 加 `used_mol` 去重。

---

## 9. 已知问题

### 9.1 V3 会漏掉密集多面板合成路线（**最重要**）

**p415**：页面中部的"合成路线："——三行多步反应式（含 H₂SO₄/HNO₃、K₂CO₃、LiOH·H₂O、Pd/C H₂、
HCl(EA)、TEA、110 °C 等条件标注）——**V3 一个框都没检出**，占页高约 26%。
该页所有 V3 区域合计只覆盖 **28.1%** 页面（其余 31 页平均 52.2%）。

**但 MolDet 补上了**：同一页 MolDet 检出 **16 个分子框**，完整覆盖整条路线。
→ **版面模型单独不够用，`Hiro ∪ MolDet` 是承重设计**，不是可选优化。

### 9.2 `formula` 严重过触发

CN 页 8 个 `formula` **没一个是真公式**，全是 MS 数据里的上下标碎块。可分性很干净：

| 分组 | 面积% 页面 | score | 内容 |
| --- | --- | --- | --- |
| 真化学式 ×3 | **0.13 – 0.17** | **0.68 – 0.77** | MS 行里的 `C₁₈H₂₅N₃O₃` |
| 伪碎片 ×5 | **0.03 – 0.09** | **0.51 – 0.66** | 单字符 / `NH₄Cl` / 短片段 |

→ **建议默认 `threshold ≥ 0.68` 或 `面积 ≥ 0.1% 页面`**（当前默认 `--conf 0.5`）。
CN 页 20 个区域中有 **13 个面积 < 0.5% 页面**，噪声占比高。

### 9.3 区域内嵌（R2 已处理）

V3 同时输出父级 `text` 大块与其内部的 `formula` 小块，同一内容会分别路由到文本与公式两条路径。
实测 CN p405 有 8 对、US p50 有 2 对。R2 已把它们降级为父块 `span`（`meta.spans`）。

### 9.4 两个标签在化学专利上语义漂移

- **`figure_title`** 命中的是结构式下方的**化合物系统命名**（一长串中文 IUPAC 名），score 0.56。本质是正文。
- **`formula_number`** 命中的是正文片段（`(5.1 mg, Compound 4)` 附近），**并非公式编号**。

→ 需在映射表之上再加领域规则：`figure_title` 若为长文本改判 `text`；`formula_number` 建议直接丢弃。

### 9.5 重叠框

5/32 页存在 IoU>0.5 的重叠框（共 6 对），例如 p415 的两个 `image` 框几乎完全重合。R1 处理了一部分，
更宽松的阈值会清得更干净。

---

## 10. 为什么必须"先区域检测、再路由"

对同一批 32 页用 RapidOCR(PP-OCRv6) 裸跑全页 OCR，共 2052 个文本行，按位置归属统计：

| 落在 | 行数 | 占比 |
| --- | ---: | ---: |
| V3 `text` 区域 | 1033 | **50.3%** |
| V3 `image`/`chart` 区域 | 784 | **38.2%** |
| V3 `table` 区域 | 49 | 2.4% |
| 任何 V3 区域之外 | 69 | 3.4% |

**38.2% 的文本行落在结构式/图区域内**——那是结构式里的取代基符号、试剂名、键标注
（实测见过 `O`、`N-N` 这类输出）。图重页该比例高达 49.1%。
→ **不能对整页裸跑 OCR**，必须先用版面识别的区域把 `image`/`molecule` 遮掉。

另：**V3 与全文 OCR 是互补的两层**，不是替代关系——V3 出 16.8 个带类型的粗粒度区块（"在哪、什么类型"），
OCR 出 64.1 个细粒度文本行（"具体文字"）。真正的文本层应取**区域类型 + 行框**求交。

---

## 11. 未实施 / 后续

| 项 | 状态 |
| --- | --- |
| **任何识别**（OCR / 表格结构 / 公式 / 分子→SMILES） | ❌ 未实现。`image`/`chart` 只出 bbox |
| **裁剪级矫正**（用 V3 多边形对抗畸变） | ❌ 未实现。`polygon_*` 字段已产出但**无消费方** |
| **`text` 区域的 OCR 与按类型路由**（DESIGN.md §5.1） | ❌ 未实现 |
| **`threshold` 调优到 0.68 + 面积下限** | ❌ 未实施，当前默认 0.5 |
| **`figure_title` / `formula_number` 的领域规则** | ❌ 未实现 |
| **畸变样本回归** | ❌ 未做。本批 32 页全为方正页面，**V3 相对 plus-L 的畸变优势无实测支撑** |
| **PaddleX `layout_detection` 模块能否注册 V3** | ⚠️ 未验证。官方 13 个模型列表里没有它。当前走 transformers 直载，不依赖 PaddleX |

---

## 12. Hiro-Layout（PatSnap/Hiro-Layout，ONNX）· **已采用**

> 2026-09-17。引入动机：V3 的漏检与标签漂移（§9.1 / §9.4 / §12.6），需要一个可替换的第二方案。
> **结论（§12.8）：已选定 Hiro 作为生产路径的版面检测器，V3 降为对照基线。**
> **但权重授权仍需澄清，且 Hiro 不输出阅读顺序 —— 这两条是采用它的实际代价。**

### 12.1 权重与元数据

| 项 | 值 |
| --- | --- |
| 权重 | `layout_model/RT-DETR_25.onnx`，250.31 MiB |
| 架构 | ultralytics **rt-detr-x**（ONNX 元数据 `description`） |
| 训练配置 | `/home/liuqi/layout/code/datasets_config/patent0122.yaml` |
| 输入 | `images [B,3,H,W]` float32；**`imgsz=[640,640]`**，`stride=32`，`dynamic=True` |
| 输出 | `output0 [B,300,29]` = 4 个**归一化 cxcywh** + 25 类概率（已过 sigmoid） |
| 后处理 | `end2end=False`（非端到端导出，故保留可选 NMS） |
| **授权** | **AGPL-3.0**（ONNX 元数据 `license`）；模型卡写的是 Apache-2.0，**二者冲突** |
| 来源 | `PatSnap/Hiro-Layout`；**ModelScope 上没有**（实测 404），只能走 HF 镜像 |

拉取（本机 `huggingface.co` 不可达，走 `hf-mirror.com` + `HF_HUB_DISABLE_XET=1`）：

```powershell
& $PY fetch_weights.py --model hiro
```

### 12.2 三个必须先知道的坑

#### (1) `labels.json` 的 id 与 ONNX 输出下标对不上——必须用 ONNX 内嵌元数据

官方 `labels.json` / `config.json` / README 按 "figure → text → complex" 三组顺序编号
（`text=8`、`head=11`、`tab=4`…），但权重里的真实顺序是另一套——**25 个位置里 24 个不一致**：

| idx | ONNX 元数据（权威） | 中文 | → RegionType | `labels.json` 同位置（错） |
|---:|---|---|---|---|
| 0 | title | 标题 | title | graph |
| 1 | sec | 章节标题 | text | draw |
| 2 | **text** | 文本 | text | struc |
| 3 | photo | 照片 | image | photo |
| 4 | seq | 序列表 | table | tab |
| 5 | **head** | 页眉 | header | eqn |
| 6 | foot | 页脚 | footer | chem |
| 7 | draw | 绘制图 | image | noise |
| 8 | mnote | 边注 | text | text |
| 9 | cap | 说明 | text | title |
| 10 | struc | 结构图 | image | sec |
| 11 | figno | 编号 | text | head |
| 12 | lineno | 行号 | text | foot |
| 13 | colno | 栏号 | text | mnote |
| 14 | ref | 参考文献 | text | cap |
| 15 | toc | 目录 | text | figno |
| 16 | noise | 噪声 | noise | lineno |
| 17 | **tab** | 表格 | table | colno |
| 18 | eqn | 数学公式 | formula | seq |
| 19 | **chem** | 化学式 | image | figcx |
| 20 | figcx | 图片组 | image | rxn |
| 21 | rxn | 反应式 | reaction | bib |
| 22 | bib | 著录页 | text | srep |
| 23 | srep | 搜索报告 | text | toc |
| 24 | graph | 图表 | chart | ref |

**照 `labels.json` 解读的后果**：正文段落被读成 `structure diagram`。
证据：256 页样本上 `idx=2` 的框有 **411/518（79%）** 与 V3 的 `text` 区域重合；
而 `labels.json` 认定的 `text`（idx 8）在 60 页里只触发 **1** 次——
一个 `text` F1 0.81、`text` 占其评测集 53%（17,668/33,054）的模型不可能如此。

`hiro.py` **从 ONNX 元数据 `names` 读类别表**（读不到才回退硬编码），
`--list-labels` 并列打印两列以便核对。

#### (2) 只有 640×640 letterbox 是有效工作点

`imgsz` 元数据是 `[640,640]`，实测偏离即退化（4 页，conf 0.3）：

| 输入边长 | 640 | 800 | 1024 | 1280 | 1600 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 检出总数 | **35** | 15 | 10 | 6 | **0** |

即"动态轴能跑，但只有 640 是导出时的工作点"。
预处理：**letterbox（保持长宽比 + 灰边 114）→ /255 → RGB → CHW**。

> 排除性测试（都不是可调空间）：pad 色 0/114/255、归一化 /255｜ImageNet｜±1、RGB/BGR
> 对结果几乎无影响；squash 拉伸、原生尺寸直喂同样不解决问题。

#### (3) 授权字段自相矛盾，需书面澄清（**不是**"确定 AGPL"）

ONNX 元数据 `license = "AGPL-3.0 License (https://ultralytics.com/license)"`，
而模型卡与仓库 `LICENSE` 文件都写 Apache-2.0。

**但看完 `refs/Hiro-Smart-Doc/` 源码后措辞应回退一步**（详见 `../docs/HIRO-SMART-DOC-ANALYSIS.md` §3.4）：
该字符串与 `description`（`Ultralytics rt-detr-x model trained on …`）一样，都是
**ultralytics 导出器固定写入的样板字段**；PatSnap 自己的服务代码是 Apache-2.0。
→ 合理推断是"权重按 Apache-2.0 发布、AGPL 只是导出器样板"，但**必须拿到 PatSnap 的书面澄清**才能进商用路径。

> 另外两条更硬的约束：**MBForge 本体是 CC BY-NC-SA 4.0（非商用）**；
> `DESIGN.md` §7 对 MinerU 已写明"AGPL-3.0，⚠️ 避免引入"，澄清前按同一标准处理。

### 12.3 用法

```powershell
Set-Location "C:\Users\10954\Desktop\ChemLayout\layout"

& $PY hiro.py --list-labels
& $PY hiro.py --image ..\Sample\CN117180334A_FullTextImage_p0006.png --save-vis

# 走完整管线（Hiro ∪ MolDet ∪ 合并）
& $PY detect_overlay.py --layout hiro --merge --samples ..\Sample `
      --src-dpi 144 --dpi 144 --out out\hiro
```

Python 侧与 V3 同签名，可直接替换：

```python
from layout.pipeline import load_hiro, load_moldet, MOLDET_WEIGHTS, detect_page, merge_page
det = load_hiro(input_size=640)
moldet = load_moldet(MOLDET_WEIGHTS["960_doc"])
regions, mols, page, timing = detect_page(image, det, moldet, doc_id="x", imgsz=640)
```

`detect_overlay.py` 新增 `--layout {v3,hiro}`；`--imgsz` 默认按 layout 取（v3=800 / hiro=640）。

### 12.4 256 页实测（与 V3 同管线、同 MolDet 权重与阈值）

样本 `Sample/` 256 页（跨 67 个专利 PDF 全局随机抽，seed=42，144 DPI；其中 28 个 PDF 为数字版）。
共同配置：conf 0.4、面积下限 0.1%、MolDet `960_doc` @960 conf 0.4。

| | **V3**（bf16 / GPU） | **Hiro-Layout**（ONNX / CPU） |
| --- | ---: | ---: |
| 版面区域 | 3402（13.3/页） | 3441（13.4/页） |
| └ text | 1522 | **1901** |
| └ table | 70 | 73 |
| └ image / chart | 526 | **806** |
| MolDet 分子 | 685（2.7/页） | 685（2.7/页） |
| 合并后区域 | 2730（10.7/页） | 3328（13.0/页） |
| 面积过滤丢弃 | 2077 | **388** |
| R1 同类去重 | 6 | 0 |
| R2 内嵌抑制 | 94 | 0 |
| R5 文本框去重叠 | 595 | 113 |
| R3 1:1 让位 | 353 | **577** |
| R4 1:N 容器 | 65 容器 / 309 分子 | 46 容器 / 108 分子 |
| 独立分子 | 23 | **0** |
| evidence | 2803 | 3465 |
| **耗时** | **193.7 + 38.2 = 231.9 ms/页** | **122.0 + 51.9 ≈ 174 ms/页**（GPU，见 §12.4.1） |

（text/table/image 用的是 `evidence.json` 的**合并前**扁平计数，故与「版面区域」合计不完全相等。）

四条读数：

1. **检出总量持平**（13.3 vs 13.4 区域/页），但成分不同：Hiro 的 text 多 25%、image 多 53%。
2. **Hiro 的框更"整"**：面积过滤只丢 388 个（V3 丢 2077），很少产出碎块；
   R1/R2 因此归零——不是规则失效，是没有可收拾的碎块。
3. **Hiro 更快**（换 GPU 运行时之后）：见 §12.4.1，122 ms/页 vs V3 的 193.7 ms/页。
4. MolDet 那一列（38.2 vs 51.9 ms）是 GPU 计时噪声，**不可比**（见 §7.1）。

### 12.4.1 【2026-09-17】GPU 运行时：Hiro 反超 V3（**重要**）

上面那张表的 Hiro 耗时（742.2 ms/页）是**在 CPU 版 onnxruntime 上**测的，**不代表 Hiro 的真实能力**。
Hiro-Layout 是 ONNX-only，而官方 `pyproject.toml` 明确走 GPU：

```toml
gpu = ["onnxruntime-gpu[cuda,cudnn]>=1.21"]   # CUDA12/cuDNN9 作为 pip 轮子
```

装上之后（`onnxruntime-gpu 1.30.0`，本机实测拿到 `CUDAExecutionProvider`），
256 页 × 3 轮**同进程背靠背**（`bench_hiro_gpu.py`，conf 0.4，imgsz 640）：

| 配置 | ms/页 | 三轮 | 离散度 | 94,759 页单次全量 |
| --- | ---: | --- | ---: | ---: |
| cuda / batch=1 | 167.0 | 170.3 / 167.0 / 165.9 | 2.7% | 4.4 h |
| cuda / batch=2 | 142.5 | 143.6 / 142.5 / 140.2 | 2.4% | 3.8 h |
| cuda / batch=4 | 129.1 | 128.9 / 129.3 / 129.1 | 0.3% | 3.4 h |
| **cuda / batch=8** | **122.0** | 123.8 / 122.0 / 120.9 | 2.4% | **3.2 h** |
| — 参考：V3 @800 bf16（GPU） | 193.7 | — | — | 5.1 h |
| — 参考：Hiro（CPU onnxruntime） | 742.2 | — | — | 19.5 h |

**三条结论**：

1. **Hiro 在 GPU 上是 122 ms/页，比 V3 的 193.7 ms/页快 1.6 倍**，比它自己的 CPU 版快 **6.1 倍**。
   → 上一轮"慢 3.4 倍"的判断**只对 CPU 成立**，是个环境产物，不是模型属性。
2. **批推理有效且几乎免费**：batch 1→8 从 167 降到 122 ms/页（**-27%**），
   且 b1/b2/b4/b8 的**逐页检出数完全一致**（11487 框 / 3 轮 / 256 页 = 14.96 框/页）——
   说明 `predict_batch` 的逐样本 letterbox 反变换是正确的（各图比例/边距不同，写错就会整体偏框）。
3. **GPU 计时反而比 V3 稳**：三轮离散度全程 ≤2.7%（V3 那边跨运行能到 ±26%），
   可能因为单次前向很短（~2 ms/页的 GPU 计算 + 大量固定开销），不容易累积热降频。

**实践含义**：95k 页规模下，Hiro ∪ MolDet 单次全量约 **4.8 h**（3.2 h 版面 + 1.0 h MolDet），
已在"过夜跑完"的可接受区间。**问题 #1 的门槛（≤400 ms/页）通过。**

> ⚠️ **别被单页 CLI 的耗时骗了**：`hiro.py --image <一张>` 会显示 **~740 ms**，
> 那是**进程内第一次推理**（CUDA kernel 编译 / cuDNN autotune），与 V3 的
> "冷启动 750 ms vs 稳态 110 ms"是同一现象（见 §6.3 / `DESIGN.md` §6.3）。
> 上表的 122 ms 是**预热后**的稳态值（256 页 × 3 轮的中位）。
> **服务化必须补预热**，否则首个请求会比稳态慢 6 倍。

> ⚠️ **踩坑记录（不解决会白等 6 倍时间）**：`onnxruntime-gpu` 装好但**静默回落 CPU**。
> CUDA EP 依赖 `cublasLt64_*.dll` / `cudnn*.dll`，这些 DLL 随 `nvidia-*` 轮子装进来
> 但**不在 PATH 上**；而 `ort.get_available_providers()` **照样列出 `CUDAExecutionProvider`**
> （"编译进来了"≠"能加载"）。必须：
> ① 建 session **之前**调 `onnxruntime.preload_dlls()`；
> ② 判定是否真在 GPU **只能看 `session.get_providers()`**。
> `hiro.py::_preload_gpu_dlls` 已实现，并在请求 CUDA 却只拿到 CPU 时发 `RuntimeWarning`。
> 详见 `../RUNTIME-PYTORCH.md` §3 陷阱 6。

> 复现：`& $PY bench_hiro_gpu.py --limit 0 --rounds 3 --providers cuda`
> 原始数据 `out/hiro_gpu_bench.json`。**注意 2026-09-18 之前必须用 ChemLayout 自有 venv**
> （`..\.venv\Scripts\python.exe`），因为 MBForge venv 里是 CPU 版 onnxruntime；
> **现已统一** —— MBForge venv 升到 `onnxruntime-gpu 1.30.0`，直接用它即可（见 §2）。

汇总数据：`out/layout_compare_256.json`。

### 12.5 质量评测（数字版页双向真值）

> 脚本 `eval_layout_quality.py`，原始数据 `out/layout_quality.json`。
> 本节数字**取代**早先只算正文覆盖率的版本。

**真值从哪来**：数字版 PDF 自带机器可读的版面信息——
`page.get_text()` 的逐行 bbox（作者排版位置）、`page.get_drawings()` 的**矢量路径**
（化学结构式在数字版专利里几乎全是矢量绘制）+ `get_image_info()` 的位图。

**真值清洗**（不做会得到毫无意义的数字，三处已踩）：
1. **长直线**（表格框线/下划线）单独剔除，不算图形；
2. **矢量化的文字**：文字常被转成轮廓，`get_drawings()` 会把它整片算成"图形"——
   未剔除时图形真值高达 35.9M 像素（占页 44%），两个检测器的图形召回中位数都被压到 0；
   → 聚类被文本真值覆盖 > 30% 即判为文字；
3. **整页背景图**：本批"数字版"多数其实是**扫描图 + OCR 文本层**的可检索 PDF，
   `get_image_info()` 返回一张覆盖整页的位图（那是页面本身）→ 面积 > 50% 页面的聚类剔除。

清洗后：真值图形 **8.05M 像素 / 占页 5.3%（中位 0.4%）**，130 个聚类，47/76 页有图形。

**真值可信度分层（重要）**：76 页里 **62 页是真矢量 PDF**（文本层 = 作者排版真值，
可当绝对准确率），**14 页是扫描+OCR 文本层**（文本层本身就是 OCR 输出，只能做相对比较）。

#### 正文召回

| 检测器 | 子集 | 页数 | 平均 | 中位 |
| --- | --- | ---: | ---: | ---: |
| V3 | 真矢量 PDF | 62 | 0.892 | 0.969 |
| **Hiro** | 真矢量 PDF | 62 | **0.946** | **0.986** |
| V3 | 扫描+OCR 文本层 | 14 | 0.782 | 0.918 |
| Hiro | 扫描+OCR 文本层 | 14 | 0.789 | 0.924 |

**在可信子集上 Hiro 正文召回 94.6% vs V3 89.2%（+5.4 点）**，一致方向。

#### 图形 / 结构式召回（47 页有图形）——**本节最重要的发现**

| 口径 | 平均 | 中位 |
| --- | ---: | ---: |
| 仅 V3 版面模型 | 0.208 | **0.000** |
| 仅 Hiro 版面模型 | 0.084 | **0.000** |
| 仅 MolDet | 0.451 | 0.479 |
| **V3 ∪ MolDet** | **0.536** | **0.805** |
| Hiro ∪ MolDet | 0.482 | 0.574 |

三条读数：

1. **两个版面模型都几乎抓不到化学结构式**（中位召回都是 **0.000**）。
   实测 `CN114072393A_p0054`：该页有 3 个矢量绘制的结构式，**V3 与 Hiro 都输出 0 个 image 区域**，
   结构式被当作正文段落的一部分。
2. **MolDet 才是真正的承重墙**：平均 0.451、中位 0.479，**高于任一版面模型**。
   同一页 MolDet 精确抓到 3 个结构式，框位与真值近乎逐像素吻合。
   → 量化印证了 `DESIGN.md` §9 风险 1"**Hiro ∪ MolDet 是承重设计**"。
3. ⚠️ **换 Hiro 会让结构式召回的均值下降**：`V3 ∪ MolDet` 中位 **0.805** vs `Hiro ∪ MolDet` 中位 **0.574**。
   原因：在这些页上 V3 多少会吐一些 image 区域，而 Hiro 一个都不出。
   **这条对"直接采用 Hiro"是负面证据，选型时必须纳入。**

#### 误报（越低越好）

| 口径 | V3 | Hiro |
| --- | ---: | ---: |
| 正文区域压在图形真值上 | 0.015（中位 0） | 0.018（中位 0） |
| 图形区域压在文本真值上 | 0.069（中位 0.025） | 0.069（中位 0.016） |

两侧中位数都是 0 —— **典型页面上互不侵占**；均值被少数页拉高。

> ⚠️ **仍未测量的部分**：`Sample/` 256 页里 **177 页是纯扫描件，完全没有真值**。
> 上面的所有结论只覆盖 76 页（且其中 14 页真值本身是 OCR 输出）。
> 扫描件是语料的多数，它的质量目前**只有视觉抽检**，没有数字。
> 补它的办法：人工标 30–50 页扫描件（或找已标注的公开专利版面集）。

### 12.6 顺带实测到的 V3 失败模式：整页正文被判成 `table`

§12.5 里 V3 那几个 0% 不是度量误差。`JP2020141708A_p0021` 上 V3 **只出 2 个区域**：
`header 0.80`（页眉）+ **`table 0.85`——把整页日文正文框成一张表**。

危害是直接的：该页正文会**整块路由到表格识别**，文本识别拿到的文本为 0。
Hiro 在同一页出 12 个 text 区域（外加页眉、行号），结构正确。

→ 这类页面证明 `DESIGN.md` §9 风险 9（标签语义漂移）不是孤例，**第二版面方案有实际价值**。

### 12.7 `merge.py` 的词表耦合（已修；V3 行为不变）

引入第二个检测器暴露出 `merge.py` 的一个隐含假设：**R2/R5 的 label 集合是 V3 的词表**。

- **R3/R4 容器判定**原为 `r["label"] in {"image","chart"}`。Hiro 把结构式判成
  `chem`/`draw`/`figcx`/`struc`，其 `type` 才是 `image`。后果：256 页上 Hiro 产出 806 个 image 区域，
  **R3/R4 命中数为 0，685 个分子全部沦为 standalone**，分子↔图容器关系整体丢失。
  → 已改为按 **RegionType** 匹配。V3 的 label 与 type 在 image/chart 上一一对应，**行为不变**。
- **R2/R5 词表**（`_INLINE_CHILD` / `_TEXTY`）同样是 V3 词表，直接跑 Hiro 会全部落空。
  → 已加 `params` 覆盖项（`inline_child_labels` / `texty_labels` / `r2_parent_labels`）；
  Hiro 的集合放在 `hiro.HIRO_MERGE_LABELS`。

**回归验证**：改动后重跑 V3 全 256 页，`out/baseline_256` 与 `out/v3_verify` 的
逐页区域、`merge_stats`、全部 2803 条 evidence **完全一致**。

### 12.8 结论（**已决策：采用 Hiro**）

**决策**：生产路径的版面检测器用 **Hiro**；`v3.py` 保留为对照基线，不在生产路径上。

采用的依据：

- **正文质量更好**：可信子集（62 页真矢量 PDF）上正文召回 **94.6% vs V3 的 89.2%**（+5.4 点），
  长尾失败页更少（§12.5）；类别体系也更贴合专利
  （`chem` / `rxn` / `figcx` / `mnote` / `figno` / `head` / `foot` 都是 V3 没有的）。
- **速度更快**：GPU 上 **122 ms/页**，比 V3 的 193.7 ms/页快 1.6 倍（§12.4.1）。

必须一并接受的代价：

1. ⚠️ **结构式召回的数字会变差（0.805 → 0.574）——但这条不构成反对理由。**
   实测**两个版面模型都几乎抓不到化学结构式**（中位召回 0.000），
   真正承重的是 **MolDet**；而 MolDet 是对整页推理的，**不依赖版面模型先圈出结构式区域**。
   即结构式覆盖由 MolDet 决定，与选哪个版面模型无关。
   （那个差值来自少数页上 V3 碰巧吐出的 image 区域恰好压到结构式，属偶发，不是能力差异。）
   → **成立的前提是 MolDet 必须始终开启**。任何"只跑版面模型"的简化方案都不成立。
2. ⚠️ **丢掉模型级阅读顺序**：V3 的输出顺序即逻辑阅读序（实测两栏页 323 px y 回跳），Hiro 不输出顺序。
   → **阅读顺序的恢复责任转移到组装层**（`../DESIGN.md` §4.9），官方参考是 `column_sort`
   那套硬编码启发式。**尚未实施。**
3. **权重更大**（250 MB vs 127 MB），且**必须有 GPU 版 onnxruntime**（CPU 上慢 6 倍）。
4. **授权需澄清**（AGPL 字符串 vs Apache-2.0 声明，见 §12.2(3)）。按 `../DESIGN.md` §7 的授权原则，
   **拿到 PatSnap 书面澄清前不应进入商用路径。**

尚未做完的三件事：

- ① **阅读顺序**：对比 Hiro + `column_sort` 与 V3 的原生顺序，决定组装层怎么写；
- ② **结构式覆盖的根因**：Hiro 的 `chem` 类在这些页为何没触发？被面积下限/置信度滤掉了，
  还是根本没检出？若能调参找回，代价 1 可进一步消解；
- ③ **扫描件真值**：177/256 页是纯扫描件、完全没有真值，而扫描件是语料多数。

### 12.9 参考实现（源码级）

官方服务 **`PatSnap/Hiro-Smart-Doc`** 已拉到 `refs/Hiro-Smart-Doc/` 并做过源码级分析：
`../docs/HIRO-SMART-DOC-ANALYSIS.md`。其中三条与本模块直接相关：

1. **它独立证实了 §12.2(1) 的类别顺序**——`model_runners/layout.py::classes_25` 与 ONNX 元数据 `names` 逐位一致，
   HF 的 `labels.json` 确属文档 bug。
2. **官方预处理与我们实测一致**（letterbox + 灰边 114 + `/255` + BGR→RGB），
   但其 resize 用 `cv2.INTER_LINEAR` 且 `no_scale_up=True`；本模块用的是 PIL `BILINEAR`，
   建议对齐（分析文档 §4.4-A）。
3. **官方的 `DuplicatesBoxFilter`（basic/complex 二分 + 包含比判据）值得移植进 `merge.py`**，
   并且它暴露了本模块当前的**实际阻塞项**：`evidence.json` 的 `raw_text`/`coref` 均为空，
   **不是合法的 MBForge `SourceEvidence`**——需按分析文档 §4.4-D 补裁剪图 `coref`。

---

## 13. 目录

> 环境：**统一用 MBForge 的 venv**（`onnxruntime-gpu 1.30.0`，见 `../RUNTIME-PYTORCH.md` §2.1）：
> `C:\Users\10954\Desktop\MBForge\.venv\Scripts\python.exe`。
> （项目自有的 `..\.venv` 已不再需要，尚未删除。）

```
layout/
├── weights/
│   ├── hiro/                      # Hiro-Layout（HF 镜像拉取，250.31 MiB，授权待澄清）
│   ├── v3/                        # PP-DocLayoutV3（对照基线，ModelScope，127.10 MiB）
│   └── moldet/                    # MolDetv2-YOLO26（.pt + .onnx，5.21 MB）
├── out/
│   ├── baseline_256/              # 256 页 V3 ∪ MolDet 基线（§12.4）
│   ├── v3_verify/                 # merge.py 改动后的 V3 回归（与 baseline 完全一致）
│   ├── hiro_256/                  # 256 页 Hiro ∪ MolDet（§12.4）
│   ├── hiro_gpu_bench.json        # Hiro GPU 基准原始数据（§12.4.1）
│   ├── layout_compare_256.json    # 两方案对比汇总
│   ├── layout_quality.json        # 双向质量评测原始数据（§12.5）
│   ├── text_coverage.json         # 早期只算正文覆盖率的版本（已被 layout_quality.json 取代）
│   ├── overlay_merged/            # 检测+合并的渲染图 + detections.json
│   ├── compare_det.json           # V3 vs RapidOCR 的 32 页对比原始数据
│   └── bench_*.json               # 速度基准原始数据
├── moldet_docs/                   # MolDet 架构解析报告（moldet_architecture.py 生成）
├── moldet_output/                 # MolDet 历史推理产物
├── detect_overlay.py              # 主入口：版面识别 + 合并 + 渲染（--layout hiro|v3）
├── pipeline.py                    # 可复用接口（load_hiro / load_v3 / load_moldet / detect_page / merge_page）
├── merge.py                       # 合并规则 R1–R5
├── hiro.py                        # Hiro-Layout ONNX 适配（§12）
├── v3.py                          # PP-DocLayoutV3 适配（对照基线）+ 冒烟检查 + 标签表
├── moldet.py                      # MolDetv2-YOLO26 分子检测（图片/PDF → JSON + 标注图）
├── moldet_architecture.py         # MolDet 架构解析
├── moldet_attention.py            # MolDet 注意力特征分类器实验
├── moldet_README.md               # MolDet 上游说明（ModelScope 模型卡）
├── test_pipeline.py               # 单页 API 冒烟检查
├── test_aspirin.png               # MolDet 测试图
├── bench_hiro_gpu.py              # Hiro GPU/批量基准，同进程背靠背（§12.4.1）
├── eval_layout_quality.py         # 双向质量评测：PDF 文本层/矢量图形做真值（§12.5）
├── bench.py                       # V3 速度基准
├── compare_det.py                 # V3 vs RapidOCR 检出对比
├── compare_dtype.py               # V3 精度 × 尺寸对比
├── compare_inputsize.py           # V3 非方形尺寸叠加图对比
├── sweep_imgsz.py                 # V3 输入尺寸扫描 15 档 + 曲线图
├── fetch_weights.py               # 权重拉取（--model hiro|v3）
├── sample_from_pdf.py             # 抽样（--pdf 单文件补足 / --pdf-dir 跨文件全局随机）
├── requirements.txt               # pip 备忘（正式依赖见 ../pyproject.toml + uv）
└── README.md
```

---

## 14. 参考

- `../DESIGN.md` §0.1 已定决策 / §3 数据契约 / §4.2 版面识别 / §5 数据流
- `../RUNTIME-PYTORCH.md` 运行时与环境决策
- Hiro-Layout 权重：https://huggingface.co/PatSnap/Hiro-Layout （本机需 `HF_ENDPOINT=hf-mirror.com`）
- V3 权重（对照基线）：https://modelscope.cn/models/PaddlePaddle/PP-DocLayoutV3_safetensors
- MolDet 上游：ModelScope `UniParser/MolDetv2-YOLO26`（详见 `moldet_README.md`）
- 模型文档：https://github.com/huggingface/transformers/blob/main/docs/source/en/model_doc/pp_doclayout_v3.md
- RT-DocLayout 论文：arXiv 2606.23344（ECCV 2026）
- Hiro-Smart-Doc 源码级分析：`../docs/HIRO-SMART-DOC-ANALYSIS.md`
