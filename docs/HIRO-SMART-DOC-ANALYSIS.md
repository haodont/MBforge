# Hiro-Smart-Doc 源码分析：与 MBForge 的兼容性 · 版面识别设计可借鉴之处

> 分析日期：2026-09-17
> 代码来源：`https://github.com/patsnap/Hiro-Smart-Doc`（`main`，commit `9c1a40f`），
> 已落到本地 `refs/Hiro-Smart-Doc/`。
> 对照对象：`C:\Users\10954\Desktop\MBForge`（`src/mbforge`）与 `DESIGN.md` / `layout/README.md`。
>
> ⚠️ 本机 **`github.com` 直连不可达**（Connection reset），需走镜像：
> `https://ghfast.top/https://github.com/<owner>/<repo>/archive/refs/heads/main.zip`。
> 仓库不含权重（`layout_model/.gitkeep` 只有说明），ONNX 仍从 HF 镜像拉。

---

## 0. 结论摘要

1. **Hiro-Smart-Doc 与 MBForge 不冲突，也不重叠**——前者是"无状态的文档解析**服务**"，后者是"有耐久证据库的**工作台**"。两者最自然的结合点是：**用 Hiro 的版面能力替换 MBForge 目前依赖 OCR 厂商的版面能力**。

2. **MBForge 目前没有任何独立版面模型**。它全部的"版面"（text / figure / table 三种 `block_type`）都来自 **OCR 提供方服务端的 layout parsing**，由后端代码映射成 `{0,1,2}`。这既意味着版面识别有明确的插入点，也意味着一个真实缺陷：**版面分析无法脱离 OCR 独立运行**。

3. **MBForge 的阅读顺序是纯光栅排序，没有任何分栏处理**（Join 期一次 `sort`，`page, -bbox[3], bbox[0], …`）。这对两栏美国专利是硬伤。Hiro 有 `column_sort`（1/2/3 栏判定），V3 自带逻辑阅读序——**这是版面识别最容易被忽视、但价值很高的一条可借鉴项**。

4. **可直接移植度最高的是 Hiro 的 `DuplicatesBoxFilter`**：把类别分成 "basic / complex" 两组，basic 做**类别无关** NMS 且判据是 `IoU > 0.5` **或** `交集/较小框面积 > 0.7`（包含比），complex 做**类别内** NMS。这正好是我们 `merge.py` R1/R2 想解决但写得很脆的问题。

5. **Hiro 独立证实了我们上一轮的类别顺序结论**：`model_runners/layout.py` 的 `classes_25` 与 ONNX 内嵌元数据 `names` **逐位一致**（`2=text, 5=head, 6=foot, 17=tab, 19=chem, 24=graph`）。→ HF `labels.json` 的下标错乱是**官方文档 bug**，不是我们读错。

6. **授权需要降级措辞**（见 §4.4）：ONNX 里的 `AGPL-3.0` 字符串是 **ultralytics 导出器写进去的样板字段**；PatSnap 自己的代码是 Apache-2.0，模型卡也宣称 Apache-2.0。所以应表述为"**需 PatSnap 书面澄清**"，而不是"确定是 AGPL"。但另有两条更硬的约束：**MBForge 本体是 CC BY-NC-SA 4.0（非商用）**。

---

## 1. Hiro-Smart-Doc 是什么（代码事实）

FastAPI 服务（`hiro-smart-doc` 1.0.0，Apache-2.0），把 PDF / 图像 / Office 文档转成**按阅读顺序排列的区域流**，可附带 Markdown。

```
PDF / 图像 / Office
      │  (Office → LibreOffice unoserver → PDF，默认关闭)
      ▼
  逐页渲染 (pypdfium2, PDF_RENDER_DPI=150)
      ▼
  版面检测 (RT-DETR ONNX)  ──►  PatSnap/Hiro-Layout
      ▼
  去重框过滤 (DuplicatesBoxFilter) → 阅读顺序 (column_sort) → 按类别过滤
      ▼
  裁剪 → 批量 OCR  ──►  MOSS-OCR（独立 vLLM 服务，OpenAI 兼容 HTTP）
      ▼
  流式返回区域 JSON（可选 markdown=true 拼接全文）
```

两个模型都与仓库解耦：版面权重在 HF，OCR 是**外部 HTTP 服务**（`MOSS_VLLM_OCR_API`，默认 `http://127.0.0.1:8088/v1`），本仓库只有客户端。

模块地图：

| 路径 | 职责 |
| --- | --- |
| `hiro_smart_doc/service.py` | FastAPI 端点 + 单页 `smart_doc()` 生成器 + PDF 逐页并发编排（26 KB，最大文件） |
| `hiro_smart_doc/base_app.py` | 挂载 `RD_API_PATH`、`/static` 静态图服务、请求日志中间件 |
| `hiro_smart_doc/layout/` | 版面引擎：`LayoutRunner`（按 `model_id` 注册多模型）、`backends/onnx_backend.py`、`model_runner.py`（预处理/后处理基类）、`model_runner_{25,9,5,chem}/`、`infer_utils.py` |
| `hiro_smart_doc/model_runners/layout.py` | 业务层：类别表、8 类 category 映射、阅读顺序、过滤 |
| `hiro_smart_doc/model_runners/moss_*.py` | MOSS-OCR 客户端（OpenAI 兼容 + 重试 + 并发闸） |
| `hiro_smart_doc/common/` | `file_utils.py`（渲染/裁剪/哈希）、`local_storage.py`、`stage_timing.py`、`utils.py`（retry / CoroutinePool） |

### 1.1 一次加载四个版面模型

`layout/__init__.py` 的 `LayoutRunner.create_model` 按 id 分派：

| model_id | 类别数 | 输入尺寸 | 类别 |
| --- | ---: | ---: | --- |
| `25` | 25 | **640** | title, sec, text, photo, seq, head, foot, draw, mnote, cap, struc, figno, lineno, colno, ref, toc, noise, tab, eqn, chem, figcx, rxn, bib, srep, graph |
| `9` | 9 | 960 | text, supplement, noise, tab, graph, fig, eqn, chem, rxn |
| `5` | 5 | 1280 | text, tab, fig, eqn, chem |
| `chem` | 2 | 960 | chem, rxn |

由 `MODEL_LIST`（逗号分隔）选择加载哪些、`MODEL_ID` 选默认。**同一套 `filter()` 接口服务所有模型**——靠的是下面这个中间层。

### 1.2 两级类别体系（细类 → category）

`model_runners/layout.py` 里 `classes_category_25` 把 25 个细类归成 8 个 category：

| category | 细类 |
| --- | --- |
| `figure` | draw, graph, photo, struc |
| `chemical` | chem, rxn |
| `equation` | eqn |
| `table` | tab |
| `main_text` | text, cap, figno, sec, seq, title, ref, toc |
| `supplemental_text` | colno, foot, head, lineno, mnote |
| `complex` | bib, figcx, srep |
| `others` | noise |

这 8 个 category 直接暴露成 API 参数 `filter_options`（返回哪些类别）与 `ocr_filter_options`（对哪些类别跑 OCR）。

### 1.3 去重框过滤：basic vs complex

`infer_utils.DuplicatesBoxFilter`：

```python
complex_class = [11, 19, 20, 21, 22, 23]   # figno, chem, figcx, rxn, bib, srep
# 注释原文："11: figno perhaps locate in the box of figure
#           19: chem perhaps locate in the box of table"
```

- `filter_basic`：**类别无关** NMS，抑制判据是**双条件**
  `ovr = IoU <= iou_thresh(0.5)` **且** `ovr_ratio = 交集/较小框面积 <= merge_ratio(0.7)`
- `filter_complex`：**按类别分组**后各自 NMS（允许跨类重叠）
- 两侧都还留着一个 `merge_overlap_boxes`（`>0.7` 并集合并、`>0.995` 直接删），但**在 `filter_basic`/`filter_complex` 里被注释掉了**——当前实际未启用。

### 1.4 阅读顺序：`determine_columns` + `column_sort`

启发式，无模型：

- 过滤"细长框"（`box[2]-box[0] > 0.1`），把 `lineno`/`mnote` 这类竖排小框排除；
- 按 x 区间累计高度，判定 1 / 2 / 3 栏（阈值 `line1_splitting=0.33`、`line2_splitting=0.60`）；
- 逐栏排序，并处理**跨栏的标题行**（横跨多栏的框先入列，然后把上方各栏内容合并）。

作者自己在注释里写了"these magic numbers are based on case study and may need to be tuned"。

### 1.5 预处理/后处理（与我们的实测完全一致）

`model_runner.py`：

```python
# 预处理：letterbox（保持宽高比 + 灰边 114），no_scale_up=True（不放大），cv2.INTER_LINEAR
#        BGR -> RGB (..., ::-1)，/255.0
# 后处理：xywh2xyxy().clip(0,1) -> 反 letterbox -> 乘 (W,H,W,H) 到像素
#        -> duplicate_box_filter -> 再除回去 -> 落回归一化 0-1
# 阈值：CONFIDENCE_THTRESHOLD_25 默认 0.3
```

`backends/onnx_backend.py`：

```python
providers=["CUDAExecutionProvider", "CPUExecutionProvider"]
# 并调用 onnxruntime.preload_dlls() 加载 pip 轮子里的 CUDA/cuDNN
```

`pyproject.toml`：

```toml
dependencies = ["onnxruntime>=1.20.0", ...]      # 默认 CPU
gpu = ["onnxruntime-gpu[cuda,cudnn]>=1.21"]       # 额外装 CUDA12+cuDNN9 轮子
```

> → **这直接回答了我们上一轮"Hiro 慢 3.4 倍"的原因与解法**：我们用的是 CPU 版
> onnxruntime，他们预期走 GPU。装 `onnxruntime-gpu[cuda,cudnn]` 即可，**未验证**。

---

## 2. MBForge 的现状（对照面）

### 2.1 证据契约：`SourceEvidence`

`src/mbforge/core/evidence.py`，不可变 dataclass：

```python
doc_id: str            # 非空
page: int              # 1-based，>= 1
bbox: tuple[float,float,float,float]   # 有限；0 <= x0 <= x1，0 <= y0 <= y1
evidence_id: str = ""  # 空则自动 stable_id("evidence-v1", doc_id, page, kind, bbox)
raw_text: str = ""
coref: str = ""        # 必须是库内相对路径（无 "://"、非绝对、无 ".."）
kind: str = "text_span"
```

**`__post_init__` 有一条硬约束：`raw_text` 与 `coref` 至少一个非空**，否则直接 `ValueError`。

`kind` 词表只有 5 个（`evidence_join._KIND_RANK`）：
`text_span(0) / table_span(1) / ocr_label(2) / image_region(3) / molecule(4)`。

### 2.2 版面在 MBForge 里是什么

**只有 `block_type ∈ {0=text, 1=image/figure, 2=table}`**，定义在 `backends/ocr/base.py::LayoutSpan` 与 `pipeline/extract/text.py::TextSpan`。

它**只由 OCR 后端产生**，来源是 OCR 提供方服务端的 layout 结果：

| 后端 | 映射代码 |
| --- | --- |
| PaddleOCR（云/本地） | `backends/ocr/paddleocr.py` `_spans_from_result`：`{"text","paragraph_title","formula"}→0`、`{"table"}→2`、`image→1` |
| GLM-OCR | `backends/ocr/glmocr.py`：`_LABEL_BLOCK_TYPE = {"image": 1, "table": 2}`，其余 0 |
| 本地 PaddleOCR | `backends/ocr/ocr_local.py` 转发到云解码函数，`useLayoutDetection=True`（布局由**服务端**做） |

**`src/mbforge` 里没有任何独立的版面/区域检测模型**（搜 `layout`、`doclayout`、`reading_order`、`column` 等均无）。`block_type==2`（表格）也没有任何几何启发式，完全依赖 OCR 厂商。

### 2.3 阅读顺序

`pipeline/artifacts/evidence_join.py::_evidence_sort_key`，**在 Join 期一次性排序**：

```python
return (item.page, -bbox[3], bbox[0], -bbox[1], bbox[2],
        _KIND_RANK.get(item.kind, 99), item.evidence_id)
```

因为 bbox 是 PDF pt / 左下原点，`-y1` 让 y 从上到下，再按 x 从左到右。
→ **纯光栅序，没有分栏概念，也没有使用任何模型的顺序输出。**

### 2.4 其余相关契约

| 项 | 事实 |
| --- | --- |
| Stage 契约 | `core/stage.py`：`@register(after=..., depends_on=...)`，类需 `name` + `execute(ctx) -> StageResult`；`ORDER` 由注册推导 |
| 阶段 | `extract ∥ detection → join → markdown → patent`（`pipeline/stages/*`） |
| MolDet 后端 | `backends/moldet_v2_ft.py::MolDetv2Detector`，`detect()/detect_batch()` → `PixelBox=(x1,y1,x2,y2,conf,category_id)`，再 `_normalize_boxes()` 成 0-1；面积比 ∈ [0.0001, 0.5]、长宽比 ≤ 10 过滤；`gpu_gate()` 包裹；进程内单例 + `ResourceManager.ensure("moldet")` 拉权重 |
| OCR 契约 | `OCRBackend.extract_text(image: bytes, *, cancel_check) -> OCRResult`（**同步**，按页）；`OCRResult{text, error, spans: list[LayoutSpan], raw_output, backend, ...}` |
| 去重 | `pipeline/detection/bbox_filter.py::dedupe_keep_larger`，IoU 0.5，**保留面积大的** |
| 标签规范化 | `pipeline/detection/label_normalization.py`，纯正则，输出 `formula / r_group / ring / compound / example`，**认不出就返回 `None`**（不让垃圾进数据） |
| 存储 | `storage/layout.py::LibraryLayout`，`{root}/storage/{doc_id}/{source.pdf, document.md, pages/, crops/, images/, artifacts/, runs/}`；`doc_id` 正则 `^[A-Za-z0-9_\-]+$` |
| 渲染 DPI | `ExtractionConfig.render_dpi` 默认 **200**（我们是 144，Hiro 是 150） |
| ROI 引导检测 | `PageDetector` 支持用 OCR 的 figure bbox 裁 ROI 后只在小图上跑 MolDet，**但生产路径上 `ocr_spans_by_page` 从未被构造**，`detection_stage.py` 调用时没传 → **该分支是死代码，实际永远是全页 MolDet** |

---

## 3. 兼容性分析

### 3.1 层级对照

| 维度 | MBForge | Hiro-Smart-Doc |
| --- | --- | --- |
| 定位 | 耐久工作台（SQLite 证据库 + 前端 + 审阅） | 无状态解析服务（流式 JSON，无持久化） |
| 版面来源 | OCR 厂商服务端 layout → `block_type{0,1,2}` | 独立 RT-DETR ONNX → 25 类 → 8 category |
| 版面可脱离 OCR | **不能** | 能 |
| 阅读顺序 | Join 期光栅排序，**无分栏** | `column_sort`，1/2/3 栏 |
| 区域类别 | 3 | 25 细类 / 8 大类 |
| OCR | PaddleOCR-VL（云/本地）、GLM-OCR；按页返回 | MOSS-OCR（外部 vLLM）；**按区域**返回，prompt 路由 |
| 坐标 | PDF pt，**左下原点** | 归一化 0-1，**左上原点** |
| 标签/编号 | `coref` 相对路径 + 5 种 `kind` | 无（只有 category） |
| 证据 ID | 确定性 `stable_id` | 无 |
| 持久化 | SQLite + 文件布局 | 只有本地静态图目录 |
| 渲染 | PyMuPDF，默认 200 DPI | pypdfium2，150 DPI |
| 并发 | 同步后端 | async + 信号量 + 保序流 |

### 3.2 三个可行的接入形态

**(a) 用 Hiro-Layout 替换 MBForge 的版面来源 —— 价值最高、改动最小**

MBForge 的 `LayoutSpan{text, bbox(bottom-left pt), block_type}` 只有三个字段。一个适配器把 Hiro 的 25 类映射到 `{0,1,2}` 即可**原地替换** OCR 厂商的 layout——而且能**让版面与 OCR 解耦**（现在拿不到 OCR 就没有版面）。

这正是我们版面识别在做的事。差别只在：版面识别现在输出 `Region`（更富的类型），MBForge 只吃 3 类。

**(b) 把 Hiro-Smart-Doc 当作 MBForge 的一个 OCR 后端**

把它包成 `OCRBackend`：调 `/image/smart-doc`，把返回的区域流拼回 `OCRResult{text, spans}`。

- 好处：Hiro **按区域**返回（bbox + category + content），比 PaddleOCR 的按页返回**更贴合** `LayoutSpan` 的形状；
- 代价：接口是 async/streaming，`OCRBackend.extract_text` 是 sync——需要包一层阻塞调用；且要么改为"一页一次调用取全部区域"，要么承认 shape 不匹配去做适配。

**(c) 不要把它的服务代码整体搬进来**

理由见 §3.3。

### 3.3 硬性不兼容点（逐条）

1. **坐标系相反**。Hiro 出**归一化 / 左上原点**；MBForge 要 **PDF pt / 左下原点**。换算需要页面尺寸，且 `SourceEvidence` 会校验 `0<=x0<=x1, 0<=y0<=y1` 与有限性。`DESIGN.md` §3.1 已经处理过这件事（`y0/y1 必须交换`），但**任何直接搬运都会踩**。

2. **`raw_text` / `coref` 二选一非空**。Hiro 的区域流里 `content` 可能为 `null`（未跑 OCR 的类别），此时既无 `raw_text` 也无 `coref` → **不是合法 `SourceEvidence`**。
   ⚠️ **这条同时也是我们版面识别的现状问题**：`layout/v3.py::to_evidence` 把 `raw_text` 与 `coref` 都留空，`layout/README.md` 也承认了，但**这意味着现在导出的 `evidence.json` 不是合法的 `SourceEvidence`**。版面识别单独永远无法满足它——只能靠文本识别（出 `raw_text`）或裁剪图（出 `coref`）。
   → Hiro 的 `upload_filter_options`（默认 `figure=True`，把图裁剪存盘并给 URL）**正好是 `coref` 那一半**，是个值得抄的做法（见 §4.4-D）。

3. **category ≠ kind**。MBForge 只有 5 个 `kind`。Hiro 的 8 类里 `chemical`（chem+rxn）、`equation`、`figure` 都得落到 `image_region`；`others`(noise) 无处可放。我们上一轮已经把 `reaction → image_region`、`noise → None` 写进 `layout/v3.py::KIND_MAP`，是同一处理。

4. **无持久化、无 ID**。MBForge 的一切以 `evidence_id` 为外键；Hiro 的流只有一次性 JSON。接入必须由 MBForge 侧重建 ID。

5. **无鉴权 + 图像公开**（他们 README 自述）。要暴露到不可信网络必须前置网关；这与 MBForge 的本地工作台假设不同。

6. **同步 vs 异步**。见 §3.2(b)。

7. **架构方向相反**：MBForge 是"分支 → Join → 序列化产物"的**批式**；Hiro 是"逐区域流式吐出"的**流式**。把流式塞进批式要么缓冲全页、要么改成增量消费。

### 3.4 授权

| 组件 | 声明 | 备注 |
| --- | --- | --- |
| Hiro-Smart-Doc 源码 | **Apache-2.0** | 可商用 |
| Hiro-Layout 模型卡 / `LICENSE` | **Apache-2.0** | — |
| `RT-DETR_25.onnx` 内嵌元数据 | **`AGPL-3.0 License (https://ultralytics.com/license)`** | ultralytics 导出器写入的样板字段 |
| MBForge 本体 | **CC BY-NC-SA 4.0（非商用）** | `LICENSE` 与 README 均如此 |
| MolDetv2 / MolDet 权重 | CC-BY-NC-SA-4.0 | 已在 `DESIGN.md` §7 记录 |

**修正上一轮的措辞**：`AGPL-3.0` 出现在 ONNX 元数据里，但那是 **ultralytics 导出器固定写入的字符串**（`description` 也写了 `Ultralytics rt-detr-x model trained on …`）。PatSnap 自己的代码与模型卡都是 Apache-2.0，因此合理推断：他们把"训练好的权重"按 Apache-2.0 发布，AGPL 字符串只是导出器样板。
→ 应表述为"**需 PatSnap 书面澄清**"，而非"确定是 AGPL"。

**但另有两条更硬的约束**：

- 若目标是 **MBForge**，其本体就是 **CC BY-NC-SA 4.0**——非商用约束已经先于 AGPL 生效，AGPL 之争在这个场景里是次要问题。
- 若目标是 **ChemLayout 自身的商用路径**，则 `DESIGN.md` §7 的"避免 AGPL"原则下仍需澄清；而 MBForge 的 NC 条款同样是外部依赖约束。

---

## 4. 我们的 layout 可以借鉴什么（按价值排序）

### 4.1 ⭐ 两级类别体系（细类 → category → RegionType）

**问题**：`DESIGN.md` §3.2 的 `RegionType` 是**平铺的一层枚举**，而我们实际上已经在写第三层映射了（`V3_LABEL_TO_REGION_TYPE`、`HIRO_LABEL_TO_REGION_TYPE`）。每换一个检测器就要重写一遍到 `RegionType` 的映射，下游还只能看 `RegionType`。

**借鉴**：加一层 `category`，让**模型词表 / 产品词表 / 路由词表**三段解耦：

```
模型 label (25 类)  →  category (8 类)  →  RegionType (DESIGN §3.2)
   chem, rxn            chemical            image / reaction
   tab                  table               table
   eqn                  equation            formula
   text, cap, sec...    main_text           text
```

收益：
- 换模型只改 label→category，下游路由看 category 不动；
- 可以像 Hiro 一样把 category 暴露成**请求级过滤开关**（`filter_options` / `ocr_filter_options`），这正是我们编排器需要的"按类型路由"的控制面；
- 解决我们上一轮暴露的问题：`HIRO_MERGE_LABELS` 这类**词表耦合**可以用 category 表达，而不是硬编码 label 集合。

**具体**：`Region` 增加 `category: str`；`layout/v3.py` 与 `layout/hiro.py` 各加一张 `LABEL_TO_CATEGORY`；`merge.py` 的 `_TEXTY` / `_INLINE_CHILD` / `_CONTAINER_TYPES` 改成按 category 判断（我们上一轮已把 `_CONTAINER_TYPES` 改成按 type，按 category 更稳）。

### 4.2 ⭐ 移植 `DuplicatesBoxFilter`（含"包含比"判据）

**问题**：我们的 `merge.py` R1/R2 是**按 label 白名单**手调的，且我们上一轮刚踩过"白名单是 V3 词表"的坑。R2 用 `coverage(child, parent) > 0.8` + `child_area < 1% parent` 判内嵌——方向对，但只作用于固定 label 列表。

**借鉴**：把他们这套直接拿来当 R1 的替代：

```
basic 类：类别无关 NMS，抑制条件 = IoU > 0.5  或  交集/较小框面积 > 0.7
complex 类：类别内 NMS（允许跨类重叠）
```

三点价值：
1. **"或"的第二个条件就是包含比**，能抓住"小框几乎完全落在大框里但 IoU 很低"的情形（R2 想做的），且不需要枚举父子 label；
2. **"basic / complex" 二分是个干净的抽象**：与其枚举"哪对 label 该互斥"，不如声明"哪些类**允许**重叠"。他们的注释给了语义依据：`figno`（图号）本来就该在图框里、`chem` 本来就可能在表格里；
3. 现成阈值可作起点（IoU 0.5 / merge 0.7 / delete 0.995）。

⚠️ **但不要照抄它把 `complex_class` 写成裸下标** `[11,19,20,21,22,23]`。那正是我们踩过的 `labels.json` 同类 bug（下标绑定到某个 ONNX 导出顺序）。**必须按名字派生**。

### 4.3 ⭐ 分栏阅读顺序，作为校验与兜底

**问题**：MBForge 的阅读顺序是**纯光栅序**（§2.3），两栏专利会读串。V3 自带逻辑阅读序（我们实测 323 px y 回跳），Hiro 靠 `column_sort`。

**借鉴**：
- 把 `determine_columns`（累计高度 + x 区间）**作为一个独立可测函数**实现，用途有二：
  1. **交叉校验** V3 的输出顺序——两者对"几栏"的判断应当一致，不一致就该人工看；
  2. 当某检测器**不输出顺序**时（Hiro 就是）作为兜底。
- 它的两个工程细节值得抄：**先过滤细长框**（`width > 0.1`）再判栏，避免 `lineno`/`mnote` 这类竖排小框污染高度统计；**跨栏标题行**要单独处理（横跨多栏的框先把上方同栏内容并回去）。

⚠️ **不要把它的魔数当契约**：0.3/0.4/0.52/0.66/0.33/0.60 全是 case-study 调出来的，作者自己标注了 "may need to be tuned"。它是一个**兜底**，不该取代模型自带的顺序。

### 4.4 其它可抄的具体做法

**A. `no_scale_up=True` + `cv2.INTER_LINEAR` 的 letterbox。**
我们现在 `layout/hiro.py` 用 PIL `BILINEAR`。为与官方参考实现逐位对齐，改用 `cv2.INTER_LINEAR` 更稳妥；`no_scale_up`（`r = min(r, 1.0)`）在我们现在的整页输入下无影响，但若将来喂**裁剪块**就必须加，否则小图会被放大到 640 产生分布外输入。

**B. `conf_thres` 默认值差异。** 他们 25 类模型默认 **0.3**（`CONFIDENCE_THTRESHOLD_25`），我们上一轮用了 0.4。值得在 256 页样本上扫一遍 0.3/0.35/0.4 看正文召回的收益。

**C. `StageRecorder`：统一的阶段级耗时口径。**
`common/stage_timing.py` 的 `mark(stage)` → `finish()` 输出 `{stage_ms, stages_sum_ms, wall_total_ms}`，并在 PDF 层聚合。他们 `smart_doc()` 打点 `layout → filter_crop_prep → ocr → ocr_upload`。
→ 我们 `layout/README.md` §7.1 明确抱怨"跨运行的绝对耗时不可比，只有同进程背靠背有效"。**同样的打点结构 + 同一进程内多配置背靠背**，才能产出可比数字。成本极低。

**D. 用"存裁剪图"满足 `coref`，让证据合法。**
Hiro 的 `upload_filter_options` 默认只对 `figure` 存图，落到 `LOCAL_IMAGE_DIR` 并给出静态 URL。
→ 对应 MBForge 的 `coref`（**必须是库内相对路径**）。这给了版面识别一条**不依赖 OCR** 就能产出合法 `SourceEvidence` 的路：`image`/`molecule` 区域裁图落盘 → `coref` 指向它、`raw_text` 留空。**建议加进版面识别的 evidence 导出**，否则它的 `evidence.json` 目前对 MBForge 不可用。

**E. 一个 OCR 模型 + 三种 prompt，而不是三个模型。**
`moss_ocr_runner.CATEGORY_TO_TASK`：`table→"read table … output in HTML"`、`equation→"… Latex formula"`、`text/supplemental→"… Markdown"`。
→ 我们 `DESIGN.md` §4 把表格识别（SLANeXt）与公式识别（PP-FormulaNet）规划成两个独立模型。**如果 OCR 是 VLM，"一个模型三种 prompt"能省两个模型的加载与显存**。这条值得在表格/公式选型前先做个对照实验。

**F. 批推理。** `LayoutModelRunner.batch_inference` 把 N 页 stack 成一个 tensor 一次前向；OCR 侧同样批处理裁剪块。我们目前是**逐页**跑。对 500 页专利是直接的吞吐收益，且实现不复杂。

**G. ROI 引导 + 强制兜底（但要谨慎用在我们场景）。**
`PageDetector.detect()`：有 OCR figure bbox 就只在 ROI 里跑 MolDet，**ROI 里一个都没检出时回退全页**（注释原文："an incorrect ROI never silently drops the page"）。
→ 对我们 `Hiro ∪ MolDet` 的启示：可以用 Hiro 的 `image`/`chem` 区域当 ROI 加速 MolDet。但**我们的数据反对把它当默认**：`layout/README.md` §9.1 实测 V3 会**整块漏掉**密集多面板合成路线（p415 三行反应式未检出，占页高 26%），而那正是 MolDet 存在的理由。他们的兜底只在"零检出"时触发，**抓不住部分漏检**。
→ 结论：**保留我们现在的"全页并行 + 并集"**；ROI 只作为可选加速，且要按"ROI 并集 全页"处理。
> 顺带一提：MBForge 里这条 ROI 路径目前是**死代码**（`ocr_spans_by_page` 从未构造）——想法成立但**未经其生产验证**。

**H. 内容哈希做文档键 + 静态图服务。** `hash_file()`（blake2b 取 4 字节）拼成 `{filename}-{hash}` 作为 doc 键；`/static` 挂载本地图目录。小技巧，但对我们"裁剪块落盘供审阅"的路径有用。

**I. 保序流式 + 信号量。** PDF 逐页用 `asyncio.Semaphore(pdf_page_parallelism)` 并发、但**按页号顺序吐出**（每页一个 future，主循环 `await page_done[pn]`）。编排器可以照此设计：并发执行、确定性输出顺序。

### 4.5 不建议照搬的

| 项 | 原因 |
| --- | --- |
| `complex_class = [11,19,20,21,22,23]` 裸下标 | 与 `labels.json` 同类 bug：下标绑死到某次导出顺序 |
| `column_sort` 的魔数阈值 | 作者自述靠 case study，未经系统评测 |
| `merge_overlap_boxes` 的 `(x2-x1+1)` 面积约定 | 源自 Fast-RCNN 的像素闭区间，与我们 `merge.py::area()` 的连续面积口径不一致，混用会引入 1px 偏差 |
| `DuplicatesBoxFilter.filter_complex` 只做类别内 NMS | 跨类重叠的 complex 框之间**不做**任何裁决，可能留下重叠 |
| 无鉴权 + 图像公开静态目录 | 他们的安全声明已明示，不适合直接用于内网以外 |
| 把 25 类当"产品分类"直接用 | 我们下游（表格/公式/分子识别/文本识别）只需要 8 类以内；细类应留在适配器内 |

---

## 5. 行动建议

**立刻可做（低成本、确定收益）**

1. `layout/hiro.py` 的 letterbox 改 `cv2.INTER_LINEAR` + `no_scale_up` 语义，与官方参考实现对齐。
2. 给版面识别的 evidence 导出补 `coref`（裁剪图落盘）→ 让 `evidence.json` 成为**合法 `SourceEvidence`**（§4.4-D）。这是接入 MBForge 的**实际阻塞项**。
3. 照 `StageRecorder` 的结构给版面识别加阶段打点（layout / merge / render），并在同一进程内做多配置背靠背（§4.4-C）。
4. Hiro 的 `conf` 扫 0.3 / 0.35 / 0.4（§4.4-B）。

**设计层（需改 `DESIGN.md`）**

5. `Region` 加 `category` 中间层，`merge.py` 的词表集合改按 category 判断（§4.1）。
6. 把 `DuplicatesBoxFilter` 的"basic/complex + 双判据"吸收进 `merge.py` 取代 R1/R2，**complex 集合按名字派生**（§4.2）。
7. 增加独立的 `determine_columns` 工具函数，用于**校验**模型自带顺序 + 无顺序时兜底（§4.3）。

**选型层（先实验再定）**

8. 表格/公式识别用"一个 VLM OCR + 三种 prompt"替代两个专模型做 A/B（§4.4-E）。
9. 装 `onnxruntime-gpu[cuda,cudnn]` 复测 Hiro 速度（上一轮遗留）。
10. 批推理（§4.4-F）在 500 页规模上的收益实测。

**授权层**

11. 向 PatSnap 要一句书面澄清：`RT-DETR_*.onnx` 的实际授权（Apache-2.0 还是 AGPL）。措辞比上一轮应更缓和——证据指向"导出器样板字符串"，但**必须落地成文字**。

---

## 6. 附：独立验证——类别顺序

`refs/Hiro-Smart-Doc/hiro_smart_doc/model_runners/layout.py::classes_25`：

```python
classes_25 = ['title','sec','text','photo','seq','head','foot','draw','mnote','cap',
              'struc','figno','lineno','colno','ref','toc','noise','tab','eqn','chem',
              'figcx','rxn','bib','srep','graph']
```

与我们上一轮从 `RT-DETR_25.onnx` 元数据 `names` 恢复的顺序**逐位一致**：

| idx | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 名称 | title | sec | text | photo | seq | head | foot | draw | mnote | cap | struc | figno | lineno |

| idx | 13 | 14 | 15 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 名称 | colno | ref | toc | noise | tab | eqn | chem | figcx | rxn | bib | srep | graph |

**两个独立来源互证**，而 HF 仓库的 `labels.json` / `config.json` / README 表格给出的是另一套（按 figure→text→complex 分组重排）。→ 结论确定：**`labels.json` 的下标与 ONNX 输出不对应，是官方模型仓库的文档 bug**；`layout/hiro.py` 从 ONNX 元数据读类别表的做法是正确的，且与其官方服务的实现一致。

---

## 7. 参考

- `refs/Hiro-Smart-Doc/`（本地代码，commit `9c1a40f`）
  - `hiro_smart_doc/model_runners/layout.py` — 类别表、category 映射、`column_sort`
  - `hiro_smart_doc/layout/infer_utils.py` — `DuplicatesBoxFilter`、`letterbox`、NMS
  - `hiro_smart_doc/layout/model_runner.py` — 预处理/后处理、批推理、`resize_with_padding`
  - `hiro_smart_doc/service.py` — 端点、单页流水线、PDF 并发编排
  - `hiro_smart_doc/model_runners/moss_ocr_runner.py` — category→prompt 路由
- `../DESIGN.md` §0.1 已定决策 / §3 数据契约 / §4.2 版面识别 / §5 数据流 / §7 授权清单
- `../layout/README.md` §12（Hiro-Layout 实测）/ §9.1（V3 漏检密集合成路线）
- MBForge：`src/mbforge/core/evidence.py`、`pipeline/artifacts/evidence_join.py`、
  `pipeline/detection/bbox_filter.py`、`backends/ocr/base.py`、`backends/moldet_v2_ft.py`、
  `storage/layout.py`、`core/stage.py`
