# MolParser 上游对齐评估与最小迁移计划（修订版）

> 2026-09-10 初稿；同日按评审意见修订，并执行了置信度字段收敛。
> 当前代码已移除 MBForge 自行计算的 `scribe_conf` / `composite_conf`；本文件剩余内容只规划后续 MolDet 底层替换。关联：`TODO/INDEX.md`、`AGENTS.md`（Model & OCR Backends）。

## 0. 修订记录（评审结论采纳情况）

| 评审意见 | 核实结果 | 本版处理 |
|---|---|---|
| P0 建立在错误现状上：`postprocess_caption` 已接入，`_strip_trailing_sep` 是 MBForge 契约 | ✅ 属实。`backends/molparser.py:117` 已用上游后处理；`:45` 的剥离函数有回归测试 `test_predict_strips_isolated_trailing_sep`（上游把 `CCO` 输出为 `CCO<sep>`，我们要退化为纯 SMILES） | **P0 撤销**，标记"无需执行" |
| `parse()` 无法同时满足显式要求（无 token 分数、无 crop、bbox 为渲染图左上像素、无法接入主簇预处理与 offcut OCR） | ✅ 与上游实现一致（`MolParserResult` 只有 MolDet `confidence`） | P1 原方案**不执行**，逐条记为约束 |
| DPI 前提写错：本地是 `detection_dpi = 200`，144 属 Extract OCR，交互端点 300 | ✅ `utils/config.py:77` = `200.0`；`routers/molecule/moldet.py:93` = `300.0` | 事实更正，并明确 `pdf_dpi` 是**构造参数** |
| bbox 逐值一致无法保证；`evidence_id` 参与哈希；证据集合不可变 | ✅ `core/evidence.py:37`（bbox 两位小数参与 hash）、`pipeline/persist/source_evidence.py:38`（同文档证据集合不可变） | 由"待拍板"升级为**硬约束** |
| 会引入资源与取消回归 | ✅ 上游 `_parse_pdf_batch` 先落全部页图、再落全部 crop、再统一识别 | 记入 C4，P1 原方案否决理由之一 |
| 回滚设计自相矛盾 | ✅ 采纳 | 改为"未发布项目直接 git 回退"，不搞双实现开关 |
| 建议 P1 只替换底层 YOLO 加载 | ✅ 上游 `MolDetDetector` 正是这一层 | 采纳为**唯一建议执行项** |
| **执行期发现（2026-09-10 20:3x）：P1 缩小版同样不成立** | 上游 `MolDetDetector(model_path, device, imgsz, conf)` 的 `detect()` **不传 `iou`**（落到 ultralytics 默认 0.7），且**无 warmup、无 `max_per_call` 分块**；我们现用 `iou=0.45` + 零张量预热 + 分块 | §6 结论改为**暂缓/撤回**（详见 §6），两个可选前提见 §6 |

## 1. 现状核实（本版实测，含上游包内实现）

| 事实 | 证据 |
|---|---|
| 上游后处理已接入 | `backends/molparser.py:117` → `molparser.utils.postprocess_caption`；`markush`/`sru`/`groups` 已透出到 `properties` |
| MBForge 唯一本地增补 | `_strip_trailing_sep`（`:45`），语义为"无扩展时退化为纯 SMILES" |
| 检测 DPI | `detection_dpi = 200.0`（`utils/config.py:77`）；Extract OCR 用 144；交互 `/api/v1/moldet/extract-pdf` 默认 300 |
| `pdf_dpi` 生效位置 | `MolParserConfig` 字段，构造期 `render_pdf(..., dpi=self.config.pdf_dpi)`；**不是** `parse()` 参数 |
| 上游**内置模型下载** | `molparser/models/runtime.py::resolve_model(local_path, hf_model_id, modelscope_model_id, filename, cache_dir, token)`：本地路径优先 → HF（`hf_hub_download`/`snapshot_download`）→ ModelScope（`snapshot_download`）→ 全失败抛 `ModelResolveError`；`MolParser(**_)_resolve_detector/_recognize` 都走它 |
| 上游检测器本质 | `MolDetDetector(model_path, device, imgsz, conf)` = `YOLO(model_path).predict(batch, imgsz, conf, device)`，只返回 bbox+confidence |
| 上游 PDF 批处理 | `_parse_pdf_batch`：渲染并保存**全部**页图 → 保存**全部** crop → 统一识别 |

## 2. 阶段结论

| 阶段 | 可行性 | 处置 |
|---|---:|---|
| P0（postprocess_caption 替换） | — | **无需执行**：已实现，且现有剥离逻辑是契约 |
| P1 原方案（整链换 `parse()`） | 低 | **不执行**（详见 §3） |
| P1 缩小版（仅换底层检测器加载） | 低（执行期下调） | **暂缓/撤回**：上游 `MolDetDetector` 缺 `iou`/warmup/分块，与"bbox 逐值一致"互斥（§6） |
| P2（Markush / 渲染对比） | 可行 | 独立研究，不绑定 P1（§7） |

## 3. 为什么 P1 原方案不执行（约束清单）

| # | 约束 | 具体后果 |
|---|---|---|
| C1 | `parse()` 只返回最终结果：无 token 分数、无实际识别 crop、无中间 hook | 不再自行补造 `scribe_conf`；主簇预处理与 offcut 标签 OCR 无处挂载 |
| C2 | bbox 无法逐值对齐：fitz vs pypdfium2；本地 NMS IoU 0.45；本地面积/长宽比/0.7 二次阈值；本地 OCR figure ROI 且 ROI 无结果回退整页；上游仅整页检测；渲染 DPI 不同（200 vs 200 但渲染库不同） | 哪怕 DPI 相同，bbox 仍会漂移 |
| C3 | `evidence_id = hash(doc, page, bbox(两位小数), kind)`，且 `persist_source_evidence` 要求同文档证据集合不可变 | 在"不改存储契约"前提下，**只能不接受 bbox 变化**；若接受，须另立《证据重建》计划 |
| C4 | 上游批处理一次性持有全部页图与 crop | 丢掉有界队列、有界批次、逐页取消检查、纯文本页跳过、ROI、主簇预处理、异步标签 OCR；内存随页数/分子数增长 |
| C5 | 回滚：一边删旧 backend 一边保留配置开关 = 双实现 + 双测试矩阵 | **仓库当前无任何 commit**（`git log` → `main` has no commits），git 回退不可用 → 只能靠文件/目录快照；这也是"大改不可逆"的主要风险来源 |
| C6 | 模型下载：上游内置（HF/ModelScope + `cache_dir`/`hf_token`），本地已有 `ResourceManager`（进度/校验/设置页 UI） | 不迁移下载通道；`resolve_model` 支持 `local_path` 优先，正好传本地绝对路径 |
| C7 | `/api/v1/moldet/*` 为对外契约，前端 `/extract-pdf` 在用 | 端点保留，仅可换内部实现 |

## 4. 已定稿决策（评审结论，本版锁定）

1. **bbox 必须保持现有契约**；做不到就另立"证据重建"计划，不在本计划内。
2. **不保留 `scribe_conf` 与 `composite_conf`**；结构识别只记录 `smiles` / `esmiles`，检测质量只记录 MolDet 的 `moldet_conf`。
3. 模型权重**继续由 `ResourceManager` 管理**，以本地绝对路径经 `resolve_model(local_path=…)` 注入上游。
4. **保留 `/api/v1/moldet/*`** 端点。

## 5. 当前执行结果与后续基线

已完成置信度字段收敛：上游 `MolParserRecognizer.recognize()` 直接返回 caption 列表，MBForge 不再开启 `output_scores` 或调用 `extract_confidence()`；`ExtractionResult`、检测缓存、PDF overlay 和前端 Detection 类型均不再承载 `scribe_conf` / `composite_conf`。Join 写入图片型 molecule evidence 时，`raw_text` 统一为包含 `name`、`smiles`、`esmiles`、`moldet_conf` 的 JSON；文本型 evidence 仍保留原始文本。当前定向回归为 **52 passed**。

后续若执行 P1 缩小版，需另建 MolDet 替换前后的 bbox、crop 和 evidence 集合基线；不能把 OCSR token 概率作为验收指标。

## 6. P1 缩小版（执行期核实后：暂缓 / 撤回）

**执行期核实（2026-09-10 20:3x）**：上游检测器与我们现有实现并非同构，替换会同时丢掉三样东西：

| 项 | 我们（`moldet_v2_ft.py`） | 上游 `MolDetDetector(model_path, device, imgsz, conf)` |
|---|---|---|
| NMS IoU | `predict(..., iou=0.45)` 显式传参 | **不传 `iou`** → 落到 ultralytics 默认 0.7（重叠框的抑制强度不同，**框集合会变**） |
| 预热 | 加载后 `predict(np.zeros((960,960,3)))` 预热 | 无 |
| 分块 | `max_per_call` 控制单次 `predict` 图片数 | 无（整批一次） |
| 面积/长宽比过滤 | `detect_batch` 内（比例 1e-4–0.5、长宽比 ≤10） | 无（这部分在我们侧，可保留） |

**结论**：§6 的验收标准（"逐值与 bbox 集合一致"）与本替换**互斥**——只要用上游 `MolDetDetector.detect()`，`iou` 必然从 0.45 变为 0.7。而其收益仅是删掉约 25 行 YOLO 加载代码。因此**暂缓/撤回**。

若仍要推进，只有两个前提可选（二选一，均需另立基线）：

| 选项 | 内容 | 代价 |
|---|---|---|
| A（推荐） | 撤回：保持 `moldet_v2_ft.py` 现状 | 无 |
| B | 采用上游 `MolDetDetector`，接受 bbox 变化 + 放弃 warmup/分块 | 需按 §5 另建 bbox/crop/evidence 基线，并确认 `imgsz=960`、`conf=0.5` 逐项对齐；重叠框结果可能变化 |

（原始设想，供追溯）**范围**：只把 `moldet_v2_ft.py::MolDetv2Detector` 的"模型加载 + 推理"换成上游 `MolDetDetector`，仍用 `resolve_model(local_path=<ResourceManager 绝对路径>)` 走本地权重。**保留不动**：`extraction.py` 编排、我们的阈值过滤、坐标与 crop 归档、`evidence_id`、`/api/v1/moldet/*` 契约、前端。

| 文件 | 动作 |
|---|---|
| `src/mbforge/backends/moldet_v2_ft.py` | 改：内部委托上游 `MolDetDetector`；保留对外 `detect_molecules*` / `to_api_dict` / `get_moldet` 签名 |
| `src/mbforge/backends/prewarm.py`、`src/mbforge/infra/models/lifecycle.py` | 改（仅当加载路径/类名变化时） |
| `tests/unit/backends/test_moldet_v2_ft.py` | 改：断言对齐新加载层 |
| `tests/unit/routers/test_moldet_api.py` | 不改（端点契约不变，作为回归护栏） |
| `src/mbforge/utils/config.py` | 可能改：暴露 detector conf/imgsz（当前上游 `MolDetDetector` 参数需与我们一致才能保持框集合） |

**验收**：基线全绿后，同一 PDF 前后两版对比 —— 分子数、逐值与 bbox 集合、crop 文件名、`evidence_id` 集合一致。

**风险**：上游 `MolDetDetector.detect()` 不做我们的面积/长宽比/0.7 二次阈值与 IoU 0.45 逻辑（这部分在我们自身后处理中，需确认未被一并替换）；上游 `imgsz/conf` 默认 640/0.5，必须与我们现配置逐项对齐，否则框会变。

**回滚**：单文件改动；注意仓库**无 commit**，只能先做文件快照（见 §3 C5）。

## 7. P2 独立对比研究（不排期）

- `utils.substitute_markush`（`R1`/`R[1]`、`?1-3`/`?n` 多重性）vs `services/markush/*`；
- `utils.draw(svg/png)` vs 现有结构渲染路径。
- 产物仅评估报告；不改 `markush_*` 落库与审核流（本库已 38 scaffolds / 22 fragments / 100 evidence / 11 decisions）。

## 8. 边界（不做的事）

- 不替换化合物编号 OCR：`backends/ocr/crop_labels.py`、`pipeline/detection/label_recovery.py`、`label_normalization.py`。
- 不动业务策略：`structure_role.py`、`correction.py`、`document_registration.py`、`formula_normalization.py`。
- 不改 SQL 证据模型；分子结构元数据复用 `source_evidence.raw_text` 的 JSON 文本，不新增实体或字段；当前 Detection overlay 仅将其还原为 `name`、`smiles`、`esmiles` 和 `moldet_conf`，不再输出 OCSR 或综合置信度。

## 9. 待确认（新增）

1. 是否评估"删掉自管下载通道、改由上游 `cache_dir` 下载"？前置条件：进度上报、完整性校验、离线安装、设置页 UI 能力对齐（否则维持现状）。
2. 后续若需要 OCSR 质量评估，另立独立评估方案；不得把 token 概率直接命名为模型识别置信度。
