# Patent SQL 统一解析阶段实施计划

> 状态：核心实现已落地；真实 OCR 表格样本抽查仍待运行环境具备有效 OCR 输入后完成。
>
> 日期：2026-09-09
>
> #### 当前进度（2026 续）
>
> - **批 1 已验收**：全量 OCR 契约、OCR 有界并发、Join→SQL 失败阻断和 `table_cell→table_span` 已收口。
> - **批 2 已落地**：SQL 证据版 section parser、Patent facts 字段、统一 entry/example/assay/activity 解析和单一工件发布均已完成。
> - Link/Persist、数据库/API 及前端阶段展示不属于当前任务，另立后续 TODO。
> - 后续 Link 方案已由 `patent-link-replacement-plan.md` 取代：确定性关联现在在 Patent 内完成，旧 Link 实现不再保留。
>
> 适用流水线：`Extract ∥ Detection → Markdown → Patent`；Patent 完成后本任务结束。

## 一、目标

把当前 `PatentStage`、`ExamplesStage`、`ActivityStage` 的文献事实解析职责合并到一个外部名称为 `PatentStage` 的阶段。该阶段只从前置 Join 已成功写入 SQLite 的 `source_evidence` 读取事实，以 `SourceEvidence.raw_text` 作为解析文本，以已有 `evidence_id` 作为唯一来源引用，统一写入 `patent_facts.json`。

补全Extract 改为全页 PaddleOCR，并加入有界并发与整页失败重试的缺口

完成后：

- `ExamplesStage`、`ActivityStage` 不再注册和运行；
- 不再通过 Markdown 字符区间反查 Patent、Examples、Activity 的来源；
- 不再生成运行工件 `examples_facts.json`、`activities.json`；
- Link/Persist 不在本阶段调用、设计或适配；
- 旧独立解析工件和旧规范文件直接删除，不增加读取、迁移或回填路径；
- Activity 解析不调用 LLM，复杂或不完整表格整表进入人工复核，不生成猜测记录。



## 二、非目标

本计划不做以下事情：

- 不删除全局 LLM provider/model，也不影响 Markdown 分子工具或聊天能力；
- 保留 `document.md` 作为 Markdown 展示产物；本任务不生成或读取 `document.map.json`；
- 不恢复同页、最近文本、bbox 邻近、行号或字符串相似度链接；后续关系链接另立计划；
- 不复制整段 `SourceEvidence.raw_text` 到派生事实；
- 不保留旧 `activities.json`、`examples_facts.json` 或旧 Patent 规范的读取路径；
- 不引入新的解析框架、消息总线、通用规则 DSL 或额外数据库；
- 不在本次改造中解决 Markush、名称转结构、SAR comparison key 或合成步骤深度抽取。

## 三、实施前状态快照

已知的额外的实现：
- 简化runid生成机制为时间戳YYYYMMDDHHMMSS，在queue中被具体的worker承接的时候生成
- 为runid添加限制，同一个docid下，不同stage之间允许有独立的runid，而一个stage中有且只能有一个有效runid，只保留最新的，旧的runid产物需要被移除
- 只在stage完全结束的时候才生成最新runid对应的工件，生成完成后才对旧的工件进行回收

实施前实现曾有三条并行解析路径：

| 当前组件 | 当前输入 | 当前输出/作用 | 本计划处置 |
| --- | --- | --- | --- |
| `PatentStage` | SQL evidence + `ctx.extracted.pages` + Markdown/map + PDF RapidOCR 补标题 | `patent_facts.json` | 保留阶段名；改成只读 SQL，一次完成统一解析 |
| `ExamplesStage` | Markdown/map，配置开关控制 | `examples_facts.json` | 删除阶段注册和独立工件，逻辑并入 Patent |
| `ActivityStage` | Markdown，确定性规则与 LLM 路径 | `activities.json`、staging activity records | 删除阶段和 LLM 路径，规则并入 Patent |
| `LinkStage` | patent facts + activities | 后续关系计算 | 本阶段不修改 |
| `PersistStage` | candidates、activity records、examples、links | 后续数据库投影 | 本阶段不修改 |

实施前已存在但尚未收口的前置改动：

- 工作区已开始把 Extract 改为全页 PaddleOCR，并加入有界并发与整页失败重试；本计划不重复实现，只做验收和缺口收口。
- Join 的表格 evidence 需统一为 `kind="table_span"`；当前首先检查全仓库引用，确保排序、重建、Markdown 和测试一致。
- `SourceEvidence.coref` 当前是相对文件路径，不是跨 evidence 关系；不得把它解释为候选分子链接。
- `SourceEvidence.evidence_id` 是 `doc_id + page + canonical bbox + kind` 的位置型稳定 ID。事实可天然链接回来源记录，但两个不同 evidence 记录不会因为同页或相邻而自动等价。

## 四、目标数据流

```text
Extract raw ─┐
             ├─ Join ─ persist source_evidence SQL ─┬─ Markdown（展示）
Detection ───┘                                      └─ Patent（事实解析）
                                                        │
                                                        ├─ sections / entries
                                                        ├─ assay_methods / examples
                                                        └─ measurements / issues
                                                             │
                                                     patent_facts.json
                                                             │
                                                   本阶段在此结束
```

Patent 的调用入口只接受前置 Extract、Detection、Join 和 SQL 写入均已成功的上下文。SQL 未写入、SourceEvidence 缺失或 ID 校验失败时，前置阶段直接失败，Patent 不会被调用；Patent 不重复实现这些判断，也不回退到 raw artifact、Markdown、PDF 或 JSON 快照。

## 五、不可破坏的契约

1. **SQL 是唯一运行时事实源**：Patent 一次性加载前置阶段提供的当前文档 `source_evidence`，之后只在内存中解析；Patent 不把 run ID 当作 SQL 筛选条件。
2. **来源只保存 `evidence_ids`**：派生事实不保存页码、bbox、整段来源文本；需要展示时按 ID 查询 SQL。
3. **不猜关系**：本阶段不建立 molecule、entry 或其他下游关系。
4. **原始值与标准化值分离**：如 `IC50 < 0.1 μM`，保留原始测量词元，同时独立保存 comparator、数值和标准单位。
5. **复杂表整表跳过**：不能确定列语义、单位、行边界或化合物引用时，不产生部分 activity 行。
6. **解析不确定性进入 issue**：标签损坏、表格结构不完整、单位不明确或数值无法标准化时不生成猜测事实。
7. **一次解析、一个载荷**：禁止同时维护 `measurements` 与 `activity_records` 两套同义数据。
8. **下游关系留待后续**：本阶段只产出文献事实和来源引用，不产出 Link/Persist 结论。
9. **不新增实体**：measurement 继续使用现有 `ActivityMeasurement`；表、行、列和来源引用不新增持久对象。

## 六、统一工件契约

### 6.1 `patent_facts.json`

路径固定为 `storage/{doc_id}/patent_facts.json`，每次 Patent 成功时原子覆盖当前文档工件；不通过 `runs/{run_id}` 或 `runs/current.json` 读取。

在现有 `PatentFactsArtifact` 上直接扩展，不新建第二个顶层工件类型：

```json
{
  "doc_id": "...",
  "run_id": "...",
  "sections": [],
  "entries": [],
  "synthesis_steps": [],
  "assay_methods": [],
  "examples": [],
  "measurements": [],
  "issues": [],
  "stats": {}
}
```

约束：

- `doc_id`、`run_id` 沿用当前发布上下文；Patent 不把 run ID 当作 SQL 筛选条件；
- `sections` 不再持久化字符区间和整段 `raw_text`；
- 每个事实只保存实际使用的已有 `evidence_ids`；
- `stats` 只记录解析结果数量和 issue 数量；
- 不复制整段 `SourceEvidence.raw_text`，不增加额外标记字段。

### 6.2 Measurement 最小字段

复用现有 `ActivityMeasurement` 与 `MeasurementValue`，不为后续 Link/Persist 提前增加实体或字段。本阶段只输出可以直接从 SQL 文本确认的测量事实：

```text
measurement_id
doc_id
metric
value.raw_text
value.comparator
value.value
value.value_high | null
value.unit
evidence_ids[]
```

`value.raw_text` 只保留原文中的测量词元，例如 `< 0.1 μM`；它是待复核的业务值，不是对整条 SourceEvidence 的复制。

measurement 的来源只有两类：`text_span.raw_text` 的正文 activity，或 `table_span.raw_text` 的表格 activity。表格内多个值可以共享同一个表级 evidence ID；不加入 `page`、`row_index`、bbox、`source_text`。

### 6.3 Review issue

统一 issue 至少包含：

```text
code
message
severity
evidence_ids[]
related_fact_id | null
```

第一批固定错误码：

- `complex_activity_table`：表格结构复杂或字段不完整，整表跳过；
- `activity_value_unparsed`：存在 activity 语义但值无法无歧义标准化；
- `compound_reference_unresolved`：化合物指代无法严格归一；
- `section_gap`：章节编号存在可见缺口，但不执行 PDF OCR 补回；
- `unsupported_table_format`：Paddle 表格块格式不在已验收格式内。

## 七、SQL 读取与分段算法

### 7.1 一次加载与校验

PatentStage 调用现有 SQL service，按当前文档读取 SourceEvidence；service 继续负责数据库句柄和行转换，Stage 不直接操作 `DatabaseManager`。

前置阶段已经负责 SQL 写入、SourceEvidence 完整性和 evidence ID 校验。Patent 不重复实现这些失败分支，不自行判断 SQL 是否属于某个 run，也不从其他来源补齐 evidence。

### 7.2 确定性阅读顺序

沿用 source-evidence service 的稳定顺序：

```text
page ASC,
bbox_y1 DESC,
bbox_x0 ASC,
bbox_y0 ASC,
bbox_x1 ASC,
evidence_id ASC
```

不再建立 Markdown 字符映射。解析器直接顺序处理现有 `SourceEvidence` 列表，不新增 evidence、row、cell 或其他持久对象。

### 7.3 章节切分

新增/替换一个入口 `parse_source_evidence_sections(evidence)`，复用现有 `match_section_heading` 和标签归一逻辑：

1. 只在带文本的 `text_span`/`table_span` 上识别章节标题；
2. 标题命中后，从当前 block 开始收集到下一个标题之前的 blocks；
3. `title_evidence_ids` 只包含命中标题的 block ID；
4. `evidence_ids` 只包含该章节实际使用过的 blocks，而不是无条件把整页/整章都挂到每条事实；
5. 章节全文可在内存按 blocks 拼接供规则读取，但不写入 artifact；
6. 章节编号缺口仅产生 `section_gap`，删除 Patent 的 RapidOCR/PDF 补标题路径。

## 八、各类事实解析

### 8.1 Patent entry 与 Example

- 复用现有章节分类、公共 labels 和 entry 构建规则；
- 严格归一 `21`、`21-a`、`I-1`、`化合物 21`、`Compound 21`、`Example 21`；
- 只有剩余文本满足现有语法时才接受右侧标签，不修复 OCR 损坏字符；
- `Example` 改为统一 facts 中的一类事实，不再是一个 Stage；
- example/entry 只挂实际触发标题、标签、产物或步骤规则的 evidence IDs；
- 名称转结构不在此批次执行，原有 `name_to_structure` 阶段专属配置删除。

### 8.2 Assay method

- 只从明确的 assay/activity 章节和表头提取；
- target、assay type、metric、实验条件必须有直接文本 evidence；
- 不使用硬编码文件级 target 推断；
- 多个 assay context 无法唯一归属 measurement 时，measurement 保留但 `assay_method_id=null` 并进入复核。

### 8.3 简单活动表

先抽查真实 `ocr_result.json`，固定 Paddle `table.block_content` 的实际格式，再写唯一 adapter。支持范围仅包括已观察并验收的格式，例如 HTML table 或现有 pipe table；不为假设格式预留插件层。

一个表只有同时满足以下条件才解析：

- 可唯一识别 metric 列；
- 单位来自明确表头、单元格或紧邻说明；
- 每行列数完整，合并单元格不造成歧义；
- comparator、区间和值可由现有 normalization 处理；
- 表 raw_text 能够完整表示要解析的表。

只要任一条件失败，整条 `table_span` 不产出 measurement，生成一个 `complex_activity_table` 或 `unsupported_table_format` issue，其来源为该 `table_span.evidence_id`。

### 8.4 正文活动值

复用现有 activity normalization，新增窄范围、确定性的 prose 入口。measurement 只从 SQL 的 `text_span.raw_text` 或 `table_span.raw_text` 产生。只接受同时出现以下元素的正文陈述：

- 明确 metric：如 `IC50`、`EC50`、`Ki`、`Kd`；
- 明确 comparator 或数值/区间；
- 明确且可标准化的单位；
- 若出现 compound reference，只记录能从原文确认的 reference 文本，不在本阶段建立关系。

例如 `Compound 21 showed an IC50 of < 0.1 μM` 可生成 measurement；“活性较好”“显著抑制”不生成定量 measurement。

每条 prose measurement 只引用实际包含该陈述的 `text_span.evidence_id`。跨多个 block 才能组成陈述时，按阅读顺序保存所有被实际使用的 IDs；不使用字符区间。

### 8.5 证据 ID 使用

- evidence ID 由前置 Join 生成并在入库前去重；
- Patent 不重新生成、覆盖或按 page/bbox 合并 evidence ID；
- table measurement 直接引用所属 `table_span.evidence_id`；
- prose measurement 直接引用实际承载陈述的 `text_span.evidence_id`；
- 同一张表中的多个 measurement 按 SQL 阅读顺序保留，不因共享表级 evidence ID 被错误合并。

## 九、来源链接与下游边界

### 9.1 Fact → SourceEvidence

这是本阶段唯一实现的链接：fact 保存 `evidence_ids`，展示/审核时按 ID 回查 SQL 的 `raw_text`、page、bbox 和 kind。删除 `evidence_ids_for(markdown_char_range)` 及同类字符区间投影。

### 9.2 后续关系暂不定义

本文件编写时不定义 measurement→compound entry、measurement→molecule candidate 或其他业务关系。该边界已由 `patent-link-replacement-plan.md` 取代；当前实现将确定性关联收束到 Patent，不生成 LinkArtifact，不写 activities 表，不修改 Activity API，不增加数据库字段。

## 十、阶段、工件和配置清理表

| 删除/修改项 | 目标状态 |
| --- | --- |
| `ExamplesStage` 注册与 composition gate | 删除 |
| `ActivityStage` 注册 | 删除 |
| 当前任务执行边界 | 执行到 Patent 后结束；Link/Persist 保留现状 |
| `examples_facts.json` | 删除生成与读取 |
| run `activities.json` | 删除生成与读取 |
| `.staging/activity_records.json` | 删除 |
| `ActivityArtifact`、`ExampleFactsArtifact` | 删除；字段并入 `PatentFactsArtifact` |
| Patent Markdown char map | 删除 |
| Patent RapidOCR gap recovery | 从统一解析路径删除；若无其他调用者则连模块/测试删除 |
| Activity LLM prompt/client/JSON repair/retry/pacing | 删除 |
| `llm.activity_max_concurrency` | 后端、前端设置与类型删除 |
| `llm.activity_max_retries` | 后端、前端设置与类型删除 |
| `llm.activity_min_request_interval_seconds` | 后端、前端设置与类型删除 |
| `llm.examples_enabled` | 删除 |
| `llm.examples_max_concurrency` | 删除 |
| `llm.name_to_structure` | 删除 |
| 全局 LLM provider/model | 保留 |
| `molecule_tool_enabled` / `molecule_tool_max_chars` | 保留 |

删除前用 CodeGraph/引用搜索确认没有 Markdown、聊天或其他非三阶段调用者；有共享调用者时只删除阶段专属分支。不要为了下游 Link/Persist 暂时可运行而扩展 Patent 输出。

## 十一、实施批次

每批独立完成、验收后再进入下一批。本阶段只推进到 Patent，不修改 Link/Persist、数据库或 API。

### 批次 0：锁定真实输入

1. 抽查真实成功 run 的 `ocr_result.json`，确认 Paddle `table.block_content` 的实际格式；
2. 选定一个简单表、一个复杂表和一个 prose activity 作为最小验收样本；
3. 用 CodeGraph/引用搜索确认三个解析阶段、旧工件和阶段专属配置的调用者；
4. 确认当前执行入口在 Patent 成功后结束，不把 Link/Persist 加入本阶段验收。

不创建通用 fixture 体系，只记录已确认的输入格式和调用者。

### 批次 1：收口 OCR/Join 前置

1. 确认每页走全量 PaddleOCR，OCR 失败页已在 Extract 阶段失败；
2. 确认 Join 的表格 evidence 使用 `table_span`，并检查排序、重建、Markdown 和测试中的残留引用；
3. 确认 Join→SQL 失败发生在 Patent 之前，Patent 不重复添加该判断；
4. 不为 Patent 增加 SQL/SourceEvidence 缺失分支。

### 批次 2：实现 SQL-only Patent

1. 调整 Patent facts/section 模型，去掉字符区间和整段 raw text 持久化；
2. 实现统一 SQL evidence section parser；
3. 将 Examples 与 Activity 规则并入 Patent；
4. 从 `text_span.raw_text` 和 `table_span.raw_text` 生成现有 measurement；
5. 删除 Markdown/map/PDF/RapidOCR 和 Activity LLM 解析路径；
6. 一次组装并发布 `patent_facts.json`；
7. Patent 成功后结束当前阶段执行。

### 批次 3：删除本阶段旧入口

1. 删除 Examples/Activity 阶段注册、旧独立工件发布/读取和 staging 路径；
2. 删除 Activity/Examples 专属 LLM 配置，保留全局 LLM provider/model、Markdown molecule tool 和聊天能力；
3. 删除 `TODO/patent-link-spec.md`，并从 TODO 索引移除；
4. 清理源码、测试和文档中对已删除规范文件的硬编码引用，只更新说明文字，不改 Link/Persist 实现；
5. 将前端 pipeline flow、阶段类型、README/wiki 阶段展示不同步问题登记到 TODO；
6. 保留 Link/Persist、activities DB/API 和后续关系代码现状，不为它们提前改造 Patent 输出。

## 十二、失败处理与可观测性

前置失败不进入 Patent：

| 情况 | 处理位置 | Patent 行为 |
| --- | --- | --- |
| OCR 页失败 | Extract | 不调用 Patent |
| Join/SQL 写入失败 | Join/前置持久化 | 不调用 Patent |
| SourceEvidence 缺失或 ID 校验失败 | Join/前置校验 | 不调用 Patent |
| 表格式未确认 | Patent | 整表 issue，不产出 measurement |
| 表结构复杂/残缺 | Patent | 整表 issue，不产出部分事实 |
| prose 值无法标准化 | Patent | `activity_value_unparsed` |
| compound label 不可归一 | Patent | 保留可确认事实并记录 issue |
| section 编号缺口 | Patent | `section_gap`，不使用 PDF 补回 |

日志只记录 `doc_id`、run、section/entry/example/assay/measurement/issue 数量及 evidence ID；不把全文写入日志。

## 十三、必要验证

只保护 SQL 输入、事实来源和“复杂表不产生错误事实”等高风险边界。优先扩展现有测试，不为包装函数和后续阶段新增测试。

### 最小测试场景

1. **SQL-only Patent**：不给 Patent Markdown/map/Extract pages，只提供 SQL evidence，仍能得到 section、entry、example 和 measurement；
2. **measurement 来源**：`text_span` 的 `IC50 < 0.1 μM` 引用 text evidence ID；`table_span` 的多个值均引用同一 table evidence ID；
3. **表级证据**：一个表只存在一个 `table_span` 来源，不创建 row/cell entity；
4. **复杂表边界**：复杂表得到零 measurement 和一个整表 issue；
5. **字符映射隔离**：删除 document.map 后 Patent 仍能运行，代码路径不读取字符区间；
6. **LLM 隔离**：Patent activity 解析不调用 LLM；全局 LLM 和 Markdown molecule tool 不受影响；
7. **阶段边界**：Patent 成功后不调用 Link/Persist；
8. **旧入口删除**：静态确认旧独立工件、旧阶段注册和 `patent-link-spec.md` 不再是当前入口，不测试读取已删除文件。

### 推荐命令

```powershell
$env:CONDA_PREFIX = ""
$env:UV_CACHE_DIR = "$PWD/.uv-cache"
$env:TEMP = "$PWD/.tmp"
$env:TMP = "$PWD/.tmp"
uv run pytest tests/unit/pipeline/test_sections_sql.py tests/unit/pipeline/test_patent_stage.py tests/unit/pipeline/test_activity_parsing.py tests/unit/pipeline/test_activity_normalization.py tests/unit/pipeline/test_stage_artifacts.py -q --basetemp .pytest-tmp
uv run ruff check src/mbforge/pipeline tests/unit/pipeline/test_sections_sql.py tests/unit/pipeline/test_patent_stage.py tests/unit/pipeline/test_activity_parsing.py tests/unit/pipeline/test_activity_normalization.py tests/unit/pipeline/test_stage_artifacts.py
uv run ruff format src/mbforge/pipeline tests/unit/pipeline/test_sections_sql.py tests/unit/pipeline/test_patent_stage.py tests/unit/pipeline/test_activity_parsing.py tests/unit/pipeline/test_activity_normalization.py tests/unit/pipeline/test_stage_artifacts.py --check
```

本阶段不运行 Link/Persist、数据库投影或前端全链路验收；前端展示问题只登记 TODO。

## 十四、验收条件

- [x] 当前任务边界为 `Extract ∥ Detection → Markdown → Patent`，Patent 后结束；
- [x] Patent 的唯一运行时解析输入是 SQL `source_evidence`；
- [x] measurement 明确来自 `text_span`/`table_span` 的 `raw_text`；
- [x] 一个表使用一个 `table_span.evidence_id`，不新增行列实体；
- [x] 不存在 Markdown 字符区间、`document.map.json`、PDF 或 RapidOCR 解析依赖；
- [x] Activity 无 LLM；简单表和 prose 使用确定性规则；复杂表整表 issue；
- [x] facts 只引用已有 `evidence_ids`，不复制整段来源文本，不重新生成 evidence ID；
- [x] `patent_facts.json` 是当前阶段唯一解析输出，含 examples 和 measurements；
- [x] 不新增 Link/Persist 所需关系字段、数据库字段或 API 契约；
- [x] Examples/Activity 旧解析入口、独立工件和阶段专属 LLM 配置已删除；
- [x] `TODO/patent-link-spec.md` 已删除，前端/公开文档阶段展示不同步已加入 TODO；
- [x] Link/Persist、activities DB/API、源 PDF 和用户数据未被本阶段修改或删除。

## 十五、回退与重处理

每批保持单一逻辑提交；失败时只回退本批文件，不覆盖无关脏改动。重处理从前置 Extract/Detection/Join 开始，重新写入 SQL evidence 后再运行 Patent；不从旧 Markdown 或旧独立 activity/example 工件恢复。只删除明确废弃的仓库规范文件和生成工件，不删除源 PDF。

本阶段结束后，下一份独立计划再根据 `patent_facts.json` 的实际字段设计 Link/Persist。本计划不为未来关系字段、数据库投影或 API 变化预留实现。
