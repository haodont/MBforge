# Extract 性能：基线、第一项优化与下一步（2026-10-16）

## 基线

- Harness：`scripts/bench_extract.py`（运行时 monkeypatch 计时/计数，零 `src/` 改动）。
- 快照：`docs/qa/bench-extract-baseline.json`。
- 环境：RTX 3070 Ti Laptop，torch 2.11.0+cu128，onnxruntime 1.26.0，ultralytics 8.4.150。
- 语料：`CN120329282A`(113p) / `US20210128561A1`(67p) / `WO2022152853A1`(66p)，各 3 次取中位数。
- 复现：`uv run python scripts/bench_extract.py`；**退出码 0 = 三次指纹逐字节一致**。

## 第一项优化：`page_text` 识别前过滤（已实施）

`src/mbforge/foundation/inference/ocr/page_text.py::read_text_in_boxes` 原先对整页检测出的
**每一行**都跑识别模型，之后才按 layout 文本区域丢弃区域外的行（源码注释称这类行约占 38%）。
现改为：检测仍整页跑一次，但**先按区域过滤，只识别区域内的行**。新增 `_region_for_box`，
让预过滤与最终组装共用同一条中心点判定，二者不可能分歧。**输出不变**。

| 文档 | wall（前→后） | `ocr.page_text`（前→后） | 指纹 |
|---|---|---|---|
| CN120329282A | 169.6 → 150.2 s（−11.4%） | 136.1 → 93.9 s（−31.1%） | 逐字节一致 |
| US20210128561A1 | 96.2 → 88.4 s（−8.1%） | 76.2 → 67.4 s（−11.6%） | 逐字节一致 |
| WO2022152853A1 | 72.2 → 70.9 s（−1.7%） | 54.6 → 51.6 s（−5.5%） | 逐字节一致 |

**测量噪声**：笔记本 GPU 长时间满载会热降频，跨轮次绝对值有 ±10% 漂移（优化后那一轮里
非目标模型反而慢 4–13%）。因此 wall 收益是保守下界；干净信号是 `ocr.page_text` 本身。

## 分支探针（否决了"流水线化 layout 分支"）

单独运行两条生产者分支（CN，113 页，均为优化后代码）：

- layout 分支（渲染+Hiro+MolDet+文本/表格 OCR）：**82.1 s**
- molecule 分支（渲染+MolDet+MolParser+标签 OCR）：**109.6 s**

单独相加 191.7 s，两条并发时 wall 150.2 s —— 二者确有重叠但相互争用。
**molecule 分支是天花板**，layout 分支不是。因此"给 layout 分支做跨页流水线以隐藏其渲染/检测"
在当前语料上**不会带来收益**（且会加剧单卡 GPU 争用），故未实施。

## 下一步：真正的瓶颈在 molecule 分支的标签 OCR

优化后 CN 的单项累计耗时（中位数）：

| 项 | ms | 调用数 |
|---|---|---|
| ocr.labels（crop 标签 OCR） | 146 652 | 746 |
| ocr.page_text | 93 851 | 139 |
| molparser | 65 382 | 803 crops |
| moldet | 29 360 | 226 图 |
| slanet | 17 180 | 26 表 |

`ocr.labels` 是**单项最大**，且是 molecule 分支的关键路径。它的结构性问题：

1. 每张 crop offcut 一次独立引擎调用，torch 引擎**进程内串行**（`_ENGINE_LOCK`），
   `ocr_workers` 对 torch 引擎无效（强制 1 worker）；只能靠与 MolParser/MolDet 的线程重叠，
   无法并行加速。
2. 约 200 ms/次，且日志显示**大量 offcut 的检测结果为空**——这些调用白花。
3. 该引擎启用了方向分类（Cls），page-text 引擎则刻意关闭。

可能的后续方向（均需接受"可能改变结果"的取舍，须用指纹验证）：

- 收紧"该 offcut 是否有可读标签"的预判，减少空检测调用（行为风险：可能漏掉真实标签）。
- 调整标签引擎的 det 参数，避免小 offcut 被上采样（行为风险：检测框变化）。
- 标签 OCR 换用 onnxruntime CPU 引擎 + 多 worker，把 OCR 挪出 GPU（行为风险：换引擎换结果）。
- 去掉每页重复的渲染与 MolDet（CN 共约 22 s GPU 工作）——但两分支 DPI 不同（144 vs 200），
  共享渲染会改变结果，无法保证指纹不变。

以上任一项都可以用现有 harness 直接验证"更快 + 指纹不变"。
