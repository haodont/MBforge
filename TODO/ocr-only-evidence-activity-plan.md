# 全量 OCR + 无 LLM 兜底 + 证据驱动 提取方案（OCRActivityPlan）

> 2026-09-10 记录。直接用户拍板三项决策（2026-09-10）：
> 1. **全量 OCR**：所有页面统一走 PaddleOCR，删除"原生文本双轨 + `<50 字符` 阈值兜底"，不对非 OCR 结果保留独立处理逻辑。
> 2. **去 LLM**：移除 Activity 阶段的 LLM 兜底，改为遍历 `source_evidence` 提取 + 纯确定性解析；复杂表**跳过整表并出 review issue**。
> 3. **OCR 失败页策略**：某页 OCR 最终失败 → **整文档 Extract 失败**（stage 报错可重试），不允许证据不完整继续。
>
> 本文档为评审用方案（TODO/），实施分批次进行（见 §四），现状行号基于 2026-09-10 代码，实施前以代码为准。
>
> 目标决策记录（用户确认）：
> - 默认所有文本都经 OCR，OCR 成本足够低，无需为早期非 OCR 结果专门维护独立路径。
> - kind `table_cell`（实际语义为"整张表"）重命名为 `table_span`，表/行/列文本挂在该 kind 的 `raw_text`。

---

> #### 状态（2026-09 已按当前代码核对后正式接受）
>
> - **批 1（Extract 全量 OCR + Join 单路径）已在代码落地**：`pipeline/extract_text.py` 为纯 OCR-only（无 `_OCR_MIN_CHARS`/`ocr_fallback`/`_extract_native_pages`，`build_from_document` 已删并抛错护栏）；`_ocr_pages` 有界并发（`_OCR_MAX_CONCURRENCY=4`）+ 每页重试 + 空页即 `OCRUnavailableError` 整文档失败（决策 3）；`extract_stage.py` 无 `ocr_fallback` 调用点；`stage_artifacts.py::join_evidence_artifacts` 单路径（PDF 左下坐标、无旋转/双坐标分支）；`chain.DEFAULT_PRIORITY == ("paddleocr",)`。
> - **批 2 的 kind 改名 `table_cell → table_span` 已实施**（全仓库小更新，`patent-sql-unified-stage-plan.md` 亦认可可优先执行）：`stage_artifacts.py`、`markdown/esmiles_insert.py`、`stages/activity_stage.py` 与相关测试均已迁移；`test_v2_join_registers_table_span` 通过，ruff 全绿。
> - **批 2 其余（Activity 改读证据 + 去 LLM + prose 通道 + 复杂表 review + 配置清理）由已获批的 `patent-sql-unified-stage-plan.md` 取代**，不在本文件重复实施；kind 改名作为其前置契约已交付。
> - 批 1 残余（ingest 硬前置校验/前端文案、`ocr_result.json` 的 table `block_content` 抽查）留待统一计划收尾。OCR 图片保存行为保持现状（按 2026 决策仍正常保存 `_save_images` 产出的从文本提取图片）。

## 一、现状与动机

### 现状链路

```
Extract(原生PyMuPDF + <50字符→OCR) → Join(source_evidence写入SQL)
                                          ↓ 原生块无table类型、左上角坐标
                          document.md(MarkdownStage, 页边界注释 + ESMILES插入)
                                          ↓ activity回归读 document.md 再切表
ActivityStage: _extract_tables_from_markdown → 确定性解析 + LLM兜底
                                          ↓ 拿 LLM 复述文本回 evidence 做子串匹配
                          evidence_ids_for(page + bbox + raw_text子串 + kind)
```

### 主要缺陷（逐条验证）

| 缺陷 | 证据 |
| --- | --- |
| 文本来源双轨、证据粒度不统一 | `extract_text.py:29` `_OCR_MIN_CHARS=50` 逐页阈值；`_extract_native_pages`（`:281`）只用 PyMuPDF dict block，产出 `block_type∈{0,1}`，**无 table 类型**；OCR 页才有 `block_type=2`（`paddleocr.py:347`）。 |
| "原生页→OCR页"坐标与 block_type 分支并存 | `stage_artifacts.py:545-577` `ocr_layout` 双坐标/旋转分支。 |
| Activity 输入与证据脱耦，靠文本子串回查 | `activity_stage.py:117` `_publish_measurements` 用 LLM 复述的 `raw_text` 调 `evidence_ids_for` 子串匹配（`stage_artifacts.py:627-666`），命中不稳；`evidence_bbox` 恒为 None（`extraction.py:114,560`），几何匹配维度从未激活。 |
| 原生 PDF 的数字表大概率零提取 | `_extract_tables_from_markdown`（`parsing/tables.py:100`）只认 `|` pipe 与 `<table>`，原生 block 是文本块、无管道符 → `tables_found=0`。 |
| LLM 兜底引入不确定性、成本、失败面 | `_parse_table_with_llm`/`_get_chat_client`/`_paced_invoke`/JSON 修复（`extraction.py:581-758`）与 `llm.activity_max_concurrency` 等配置。 |

### 关键支撑事实

- `source_evidence.kind` **无 CHECK 约束**（`schema.py:384` 注明 kind 可自由扩展，无需迁移）；存量行按仓库约定重跑 ingest（SQLite 为可丢弃开发库）。
- **Detection 分子图像分支独立读 PDF，不消费 Extract**（`detection_stage.py:129`）。全量 OCR 只影响文本/证据侧，MolDet/MolParser 图像链路不受影响。检测质量不受文本改造影响。
- PaddleOCR layout `table` 块已给 `block_content`（整表文本/HTML）+ 整表 bbox（`paddleocr.py:340-349`）；`_html_table_to_markdown`（`parsing/tables.py:73`）已能把 HTML 表转 pipe 表供确定性解析器消费。**table 块 `block_content` 的确切格式（HTML vs 结构化文本）需抽查一份 `ocr_result.json` 确认（实施前第一步）。**

---

## 二、目标架构

```
Extract(全部页 PaddleOCR, 144DPI)  ← 有界并发
   ↓ 每页 LayoutSpan(text/table/formula/title/image), PDF左下坐标, block_content
Join(source_evidence写入SQL; 单坐标单 branch_type 路径)
   ↓ kind: text_span / table_span(整表) / image_region / molecule / ocr_label
ActivityStage: 遍历 source_evidence
   ├ table_span.raw_text → HTML→pipe → 确定性解析(_parse_simple_activity_table)
   │                    ● 完整→记录(挂 table_span.evidence_id)
   │                    ● 不完整→跳过整表 + review issue(带 table_span.evidence_id)
   └ text_span.raw_text → find_activity_metrics 预筛 → 正则 prose 通道(非LLM)
                           ● 命中→记录(挂 text_span.evidence_id)
measurement.evidence_ids = 遍历到的证据 id（删除子串模糊匹配）
Link / Persist 消费 measurement/entry 的逻辑不变
```

---

## 三、分项改动清单（file:line 为改动点基准）

### 批次 1：Extract 全量 OCR + Join 单路径化

1. **`pipeline/extract_text.py`**
   - 删 `_OCR_MIN_CHARS`、`ocr_fallback` 参数、`_extract_native_pages`。
   - `extract_pdf_text` / `extract_document_text` 改为：全部页渲染（zoom=2.0）→ PaddleOCR chain。
   - `_ocr_pages` 改为**有界并发**（复用 `extraction.py:313` ThreadPoolExecutor 模式），串行 submit→poll 会使百页专利过慢。
   - OCR 最终失败（空文本无错误容忍）→ 抛错误使 ExtractStage 整体失败（对应决策 3,后端已有 `OCRUnavailableError` 语义）。
   - `build_from_document` 对 document_store 原生缓存的消费删除；该缓存若保留仅供预览需在调用处注明。
   - `parser` 统一标记（不再出现 `pymupdf` 字样于证据路径）。
2. **`pipeline/stages/extract_stage.py`**：`ocr_fallback=True` 调用点删除（`extract_stage.py:55`））。
3. **`pipeline/stage_artifacts.py`** Join（`:520-615`）
   - 塌缩 `ocr_layout` 双坐标/旋转分支为单路径（OCR span 已是 PDF 左下点坐标）。
   - 删除 `_top_left_to_bottom_left`/`_bbox_in_frame` 原生分支（若仅服务原生，一并清理）。
   - `block_type=2` → `kind="table_span"`（语义修正）。
4. **`backends/ocr/chain.py`**：默认优先级保持 `("paddleocr",)`；如加并发，chain 的分页循环拆到 Extract 侧并发、chain 保持单页接口。
5. **配置/前端**：
   - OCR 从"扫描页兜底"变为 **ingest 硬前置**：settings 校验无 `paddleocr_api_key` 时禁止启动 ingest（或显式报错）。
   - 前端设置页 OCR 面板从"可选/回退"文案改为"必选文本源"。
   - 删 `llm.activity_max_*` 等仅服务活性的配置项（批次 2 一并）。
6. **测试**：
   - 更新 `_OCR_MIN_CHARS`/`ocr_fallback`/原生 block 相关单测。
   - 新增/改证据契约：全量页均产生 OCR span、原生页不再出现 text-only 空 table 情况（具体准入见 §五）。

### 批次 2：kind 重命名 + Activity 证据驱动 + 去 LLM

1. **kind 重命名 `table_cell`(整表) → `table_span`**，改动点：
   - `stage_artifacts.py:75,559,681,701`、`markdown/esmiles_insert.py:25,28`、`stages/activity_stage.py:204`。
   - 新引入真正语义的 cell 级证据**不做**（第二阶段可选），本次 `table_span` 即"整张表"。
   - 相关测试：`tests/unit/pipeline/test_stage_artifacts.py:176,188`、`tests/unit/pipeline/test_link_stage.py:30`。
   - 存量 SQL `kind='table_cell'` 重跑 ingest。
2. **`pipeline/stages/activity_stage.py`**
   - 输入改读 `load_document_evidence`（SQL）而不是 `document_md_path`。
   - 遍历 `kind in {table_span, text_span}`；`page` 直接取证据.page。
   - 每条 measurement 生成即挂 `evidence_id`；删除 `evidence_ids_for` 子串回查调用。
   - 与 PatentStage 的 compound_entry 关联、assay method 分页关联逻辑保持不变。
3. **`pipeline/activity/extraction.py`**
   - 删 `_parse_table_with_llm`、`_build_extraction_prompt`、`_get_chat_client`、`_paced_invoke`、pacing/重试与 JSON 修复（`:581-758`）。
   - 主流程：table_span → `_HtmlTableParser`→pipe→`_parse_simple_activity_table`；不完整（`_simple_activity_table_is_complete` 为 False）→ **跳过整表并产出 review issue**（挂 table_span evidence）。
   - 新增 prose 通道：`text_span` → `find_activity_metrics` 预筛 → 正则提取（非 LLM）。
   - `_infer_document_target` 现状保留（可后续改证据驱动）；`merge/simple parser` 复用不删。
   - 置信度语义：确定性来源固定值（如 `0.9`），`<0.5` 丢弃策略同步调整。
   - `ActivityRecord.evidence_bbox` 现全 None：批次 2 内保持（table_span 级挂证），cell 级 bbox 属第三阶段。
4. **review 落库**：跳过整表写入 `markush_review_candidates` 之外的 review 通道——复用 `persist_stage` 已有的 review_items 机制（`kind=new 'complex_activity_table'`，`payload` 带 table_span evidence）。接入点：`persist_stage._persist_molecules_and_links` 事务内。
5. **统计字段**：`tables_found/tables_eligible/tables_attempted/tables_skipped/records` 保留；新增 `complex_tables_skipped`（走 review 的数量）、`prose_records`。
6. **配置清理**：删 `llm.activity_max_concurrency`、`activity_max_retries`、`activity_min_request_interval_seconds`（仅服务旧 LLM 活性）从 `utils/config.py` 默认与前端设置。

### 批次 3（可选，本次不做）
- Paddle structure cell bbox 下钻 → 真正的 cell 级证据（page+row_idx+col_idx+bbox），measurement 精确到 cell，`evidence_bbox` 激活。

---

## 四、实施顺序与验收

1. **批次 1（前置，先落）**：Extract 全量 OCR + Join 单路径。验收：任意数字版 PDF 的 `source_evidence` 每页均有 OCR span；活性表以整表 `table_span` 存在；OCR 未配置 or 单页失败 → ingest 整体失败。
2. **批次 2**：kind 重命名 + ActivityStage 改读证据 + 删 LLM + prose 通道 + review issue。验收：无 LLM 调用的活性表提取成功；复杂表不出低置信行、仅 review；measurement.evidence_ids 直接来自遍历证据、无子串回查。
3. **批次 3（可选）**：cell 级证据精度。

> 依赖顺序说明：全量 OCR 必须先于证据驱动落地，保证 Activity 遍历到的证据覆盖所有页面；否则原生页无 table_span 会使证据驱动在数字版 PDF 上成为空集（现状正是 `tables_found=0`）。

---

## 五、测试准入（仅保护新增契约，遵循 AGENTS.md 准入门槛）

1. **全量 OCR 契约**：数字版 PDF（原生文本 rich）经 Extract 后 `source_evidence` 含 OCR span、无 `text_span`-only 空表缺口。→ 一个集成级测试。
2. **table_span 契约**：`block_type=2` → `kind="table_span"`（更新 `test_stage_artifacts.py:176/188`）。
3. **去 LLM 契约**：table 解析链路不触发任何 LLM 调用；复杂表产出 review issue、不出低置信行。→ 一个确定性子集表 unit 测试 + review 落库测试。
4. **prose 通道**：`text_span` 命中"化合物N IC50 <值>"提取一条、挂该 text_span evidence。→ 一个 unit 测试。
5. 不新增：pass-through、等价输入排列、纯统计字段的过度覆盖。

---

## 六、风险与回退

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| OCR 依赖成硬前置 | 无 api_key/云端故障 → 所有 ingest 失败 | 明确前置校验与错误信息；保留 chain 结构便于未来加厂商 |
| 延迟上升 | 全页串行 OCR 慢 | 批次 1 加有界并发 |
| 表格质量口径变化 | 原生精确文本被 OCR 取代 | 记录在 CHANGELOG/README；抽样对比 benchmark |
| 复杂表召回下降 | 去 LLM 后复杂表整体跳过 | review issue 可见、不静默；后续 parser 增强或 cell 级证据 |
| 隐私合规 | 整份 PDF 每页上传云端 | settings/文档明示；若本地化需求需后端扩展（不在本次） |

**回退**：批次 1/2 每批独立提交；批次 1 如 OCR 质量不可接受，可保留 `ocr_fallback` 开关回退到现状（但按用户决策，该开关设计为临时逃生阀，默认全量 OCR）。

---

## 七、待办（实施前第一动作）

1. 抽查一份 `ocr_result.json`：确认 PaddleOCR-VL `table` 块 `block_content` 是 HTML 还是纯文本，据此固化 `_html_table_to_markdown` 输入契约。
2. `utils/config.py` 与前端设置面板的 OCR/LLM-activity 配置项清单核对，避免残留死配置。