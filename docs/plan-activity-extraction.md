# 活性数据提取与落库改造计划

状态：**Phase A 已实施（A1–A7 全部完成）**。Phase B/C 只记录边界，尚未开工。
日期：2026-10-20。
目标产品：面向不熟悉计算的使用者的分子科学验证软件。LLM 是其中主导模块，核心能力是
从专利文献提出 **结构 ↔ 活性配对**，并在此之上发起计算（Boltz-2 结构预测、深度学习实验、
分子对接），把**可复现、有来源**的结果汇报给药物化学家，最终支持 SAR 分析与下一步合成建议。

本文件只把 **Phase A：专利活性数据的提取与落库** 作为当前工作。Phase B/C 是目标形态的
记录，不是承诺的排期。与 [Patent 分析与领域 Agent Harness 计划](plan-patent-agent-harness.md)
并列，不替代它。

## 1. 为什么先做这一步

产品的每一层都建立在"结构 ↔ 活性"这一对数据之上：SAR 需要同一母核的系列读数，
对接/预测需要一个有结构的起点，报告需要有来源的事实。而当前这条链路是**通的但没接通**：

- 提取器产出读数，但读数只存在于 `patent_facts.json` 产物里；
- SQL 的 `activities` 表有 34 个字段、有读接口、有 agent 工具，**没有任何生产代码写入**；
- 唯一真正落库的活性是一个标量：`molecules.activity / activity_type / units`，
  而且每个分子只保留**第一条**读数。

在这一点上做任何 SAR 或计算编排，都是在空表上做统计。

## 2. 已核对的现状（2026-10-20 实测）

### 2.1 `activities` 表没有写入方

- `grep "INSERT INTO activities"` 在 `src/` 下**零命中**；只有 `tests/unit/routers/test_activity.py`
  和 `tests/unit/test_cascade_delete_activities.py` 手工插入。
- 真实库核对（`.tmp/live-llm-assoc-20261016/doc-library/library.db`）：

  | 表 | 行数 |
  | --- | --- |
  | `documents` | 13 |
  | `source_evidence` | 22,809 |
  | `molecules` | 7 |
  | `activities` | **0** |
  | `molecules.activity IS NOT NULL` | 7 |

- 读方存在且已接线：`GET /api/v1/activities/documents/{doc_id}`（`service/use_cases/documents/activity_queries.py`）
  与 agent 的 `query_activities` 都读这张表，因此**对一切真实文档恒返回空**（review_items 分支除外，
  而该 kind 也没有生产者，见 2.4）。

### 2.2 读数只存在于产物里，且全部无结构归属

汇总 18 份 `.tmp/**/patent_facts.json`：

| 指标 | 数值 |
| --- | --- |
| `entries` | 526 |
| `measurements` | 130 |
| 其中带 `mol_id` | **0** |
| `measurement.linking_status` | failed 112 / linked 16 / unlinked 2 |

单份实测（CN120329282A）：66 个条目、24 条读数、0 条带 `mol_id`；读数形如

```json
{"measurement_id": "a3fa98…", "compound_entry_id": "3061e7…", "mol_id": null,
 "metric": "IC50", "linking_status": "failed",
 "value": {"original_value": 60.7, "original_unit": "nM", "operator": "="},
 "evidence_ids": ["21b9f1…"], "provenance": {"reference_key": "1", "reference_type": "compound"}}
```

即：**读数本身是完整、可追溯的**（值、比较符、单位、证据 ID、页码都在），缺的只是结构归属。

注意 `linking_status` 的语义：它由 `association.py` 按"本次关系类 issue 是否已解决"置位
（`failed` / `linked`），**不代表结构归属** —— 上表 16 条 `linked` 中间读数的 `mol_id` 仍为
`null`。字段名容易被误读成"已绑定结构"，改造时不要按它筛选。

### 2.3 唯一落库路径会塌缩并丢弃数据

`service/use_cases/documents/patent_facts.py::_derived_rows`：

1. 只保留能解析到 `entry.entity_id` 或 `measurement.mol_id` 的读数 —— 上面 18 份产物中
   条目结构归属率 144/526 ≈ **27%**，且 **0 条读数带 `mol_id`**，所以绝大多数读数在这一步被丢弃；
2. 通过的分子只取 `measurements_by_smiles[...][0]` —— **每个分子只保留第一条读数**，
   同分子多 assay、多靶点、多剂量全部丢失；
3. 结果经 `activity_updates` 写成 `UPDATE molecules SET activity = ?, activity_type = ?, units = ?`
   （`db/molecule_store.py::persist_candidates_in_transaction`），**一个分子一个标量**。

### 2.4 相关死代码

| 位置 | 规模 | 状态 |
| --- | --- | --- |
| `service/pipeline/activity/matching.py::match_activities` | 385 行 | 仅被 `tests/unit/pipeline/test_family_core.py` 引用，生产零调用 |
| `service/pipeline/activity/family_gate.py` | 139 行 | 同上，`make_family_core_guard` 无生产调用方 |
| 复核类型 `activity_match` | — | `activity_store.py` 只读不产；`domain/review.py`、`service/dto/review.py` 里的声明无生产者 |

即"活性匹配"这一层曾被设计并实现，但当前主路径上没有接上；真正生效的只有
`service/pipeline/patent/association.py` 里基于编号的关联。

### 2.5 缺失的证据分级维度

`activities` 与 `molecules` 都没有任何字段区分"文献实测"与"模型预测"。
`molecules.source_type` 表达的是来源渠道（manual/detected），不是证据等级。
这一点在 Phase B 引入对接/Boltz-2 后会变成硬约束（见 §7）。

## 3. 目标数据模型（Phase A）

把"读数"与"归属"拆开，让读数**永远可存**，归属**增量补齐**：

```
measurements                     一条印刷读数，不依赖结构
  measurement_id      PK
  doc_id
  evidence_ids        JSON   该读数的证据行（页码/bbox 可从 SourceEvidence 解出）
  page_num / table_idx / row_idx / col_idx
  raw_text                     原始文本片段
  metric / activity_type       IC50 / Ki / 抑制率 / 定性
  original_value / original_unit / operator / measurement_kind
  canonical_value / canonical_unit / scale
  qualitative_raw / qualitative_rank / qualitative_scheme / qualitative_label
  target / species / assay_type / assay_description
  provenance          JSON   reference_raw / reference_key / reference_type
  entry_id            指向产物里的编号条目（`PatentFactsArtifact.entries[].entry_id`），可为空
  evidence_grade      Phase A 恒为 'measured'
  review_status       accepted / pending_review / rejected
  run_id / created_at

measurement_attribution          读数 → 结构的归属，零行合法
  measurement_id      FK
  mol_id              FK molecules
  method              rule / model / human
  confidence
  evidence_id         支撑这次归属的证据
  review_status       pending / accepted / rejected
  created_at
```

要点：

- `molecules.activity/activity_type/units` 三个标量列在新表接管后**只作为兼容投影**，
  不再是权威；
- 一条 `measurement` 可有多条 `measurement_attribution` 候选（冲突时保留两者），
  由复核中心裁决，而不是在写入时二选一；
- `entry_id` 允许读数挂在"编号"上而不挂结构 —— 这正是当前 80% 的实际情况。

按 AGENTS.md：本地 SQLite 是开发数据，**直接改 canonical schema，不写历史迁移**。

## 4. Phase A 工作项

| # | 工作项 | 状态 | 出口条件 |
| --- | --- | --- | --- |
| A1 | `db/sqlite/schema.py` 新增 `measurements` / `measurement_attribution` 两张表 | **完成** | 空库可建，`PRAGMA table_info` 与契约一致 |
| A2 | `contracts/measurement.py` + `db/measurement_store.py` + `MeasurementRepository` 端口 | **完成** | 契约测试通过；`db` 不导入 `service` |
| A3 | `PatentStage` 发布时把 `artifact.measurements` **全量**写入 `measurements` | **完成** | 真实产物实测 36/36 入库，丢弃 0 |
| A4 | 归属写入 `measurement_attribution`，不再依赖 `molecules.activity` 标量 | **完成** | 有归属可反查；无归属仍在 `measurements` |
| A5 | 读侧迁移：`/api/v1/activities/*` 与 agent `query_activities` 读新表 | **完成** | 新增 `/stats` 返回覆盖计数 |
| A6 | 删除 `activities` 读路径、`match_activities`、`make_family_core_guard` | **完成** | `ruff`/`pytest` 干净 |
| A7 | 数据集查询：按 target/assay/grade/status 过滤 + 覆盖统计 | **完成** | `dataset_stats` + HTTP `/stats` |

真实语料复核（同日第二轮）：三个只在真实文本上暴露的缺陷已修复——读数缺位置、
重叠表格被读两遍、定性分档被标成定量。详见下方「真实语料验证」。

### 实施记录（2026-10-20）

新增模块：

- `src/mbforge/contracts/measurement.py` — `MeasurementRecord`、`MeasurementAttribution`、
  `MeasurementQuery`、`MeasurementDatasetStats`、`EvidenceGrade` / `ReviewStatus` /
  `AttributionMethod` / `LinkingStatus`。全部 `extra="forbid"`。
- `src/mbforge/db/measurement_store.py` — 两张表的读写；`measurement_id` 幂等
  （`INSERT OR REPLACE`），归属与读数按 `doc_id` 同事务删除重写。
- `src/mbforge/service/pipeline/patent/measurement_records.py` — artifact → 行投影。
  `measurement_records()` **不按结构过滤**；`measurement_attributions()` 只产出真正解析到的链接，
  归属可从 `measurement.mol_id` 或所引条目的 `entity_id` 两侧解析。
- `tests/unit/pipeline/test_patent_measurement_publication.py` — 5 例，核心回归是
  **同一结构的多条读数全部保留**（旧路径只留 `[0]`）。
- `tests/unit/pipeline/test_activity_location.py` — 4 例真实语料回归：读数带页码/行号/列号、
  重叠表格只读一次、定性分档不落成定量、定位字段可往返序列化。

改动点：

- `patent_facts.publish_document_facts` 增 `_reading_rows()`，把读数与归属随快照同事务提交；
  `PatentAnalysisRepository.commit` 增 `measurements` / `attributions` 参数。
- `DatabaseManager.delete_document_molecule_data` 与 `document_backup._DOC_TABLES` 覆盖新表。
- `activity_queries` 重写为读 `measurements` + 标注 `attributed` / `mol_ids`；
  `ActivityRecordResponse` 增 `evidence_grade` / `review_status` / `attributed` / `mol_ids`。
- 删除 `matching.py`（385 行）、`make_family_core_guard`；`family_gate.py` 收窄为只保留
  `derive_family_core`（`tests/unit/pipeline/test_recover_labels.py` 实际使用）。

验证：

- 真实产物端到端（`.tmp/meas-check/e2e.py`）：**artifact 36 条 → SQL 36 行，丢弃 0，
  其中 12 条有归属**。改造前同一批数据只落 8 个 `molecules.activity` 标量。
- `uv run pytest tests/unit -q` → **395 passed, 1 failed**；唯一失败是既有的 Windows
  平台问题 `test_docking_engine.py::test_udp_command_and_pose_parsing`
  （`#!/bin/sh` 文本桩在 Windows 必然 WinError 193，与本轮改动无关）。
- `uv run ruff check` / `ruff format --check` 干净。

### 真实语料验证（2026-10-20，第二轮）

用 `.tmp/e2e/rerun_patent.py` 在 **13 篇真实专利**上重跑 Patent 阶段（复用已落库的
SQL 证据，不需要 GPU，单篇 2–4 秒），再用 `.tmp/e2e/final_report.py` 核对 SQL。

这一轮**发现了三个只在真实文本上才暴露的缺陷**，都已修复并补了回归测试：

1. **读数不带位置**。`ActivityMeasurement` 没有 `page_num`/`table_idx`/`row_idx`/
   `col_idx` 字段，而 `ActivityRecord` 明明有——提取时算出来了，构造测量对象时全丢了。
   结果 52 条读数 `page_num` 全为 NULL，无法回到 PDF。修复：域对象带上四个定位字段，
   `to_dict`/`from_dict` 往返保留；表格解析补上 `row_idx`（此前从未赋值）。
   现状 **43/43 有页码、43/43 有行号**。
2. **同一张表被读两遍**。CN120329282A 的一张 19 行表在布局阶段被存成两条证据行，后者
   以前者内容开头（`21b9f1e9` 288 字符 ⊃ `d2c7d2c7` 181 字符）。两条都读，重叠的 9 行
   就变成重复读数（28 条 vs 真正的 19 行）。修复：跳过文本被更长表格证据前缀包含的行。
   去重后该文档 28 → 19，**同单元格重复 = 0**。
3. **定性分档被当成定量**。`++`/`+++` 这类分档在 normalization 层已正确判为
   `qualitative`，但 `ActivityMeasurement` 没有 `measurement_kind` 字段，投影又从
   `value` 里读它（实际在测量项顶层），于是全部落成 `quantitative`。把 `++` 当成浓度
   误差是数量级的。修复后 12 条分档正确标为 `qualitative`。

语料结果（真实库 `.tmp/e2e/library`，43 条读数）：

| 指标 | 数值 |
| --- | --- |
| artifact 读数 → SQL 行 | **43 → 43，丢弃 0** |
| `page_num` / `row_idx` | **43/43（100%）** |
| `assay_method_id` | 19/43（44%） |
| `target` | 12/43（28%） |
| 结构归属 | 11/43（26%） |
| `evidence_grade` | 全部 `measured` |
| 同单元格重复 | 0 |

注：`target`/`assay_method_id` 的低覆盖是**上游提取缺口**，不是投影 bug——44b8daed 与
a96eb3c0 两篇的读数没有对应 assay 小节可继承，5a288b 中 7 条读数的 assay 小节本身
未识别出 target。这属于页级提取召回，已在 §7 记录。

### 归因率拆解（2026-10-21）

26% 的归因率曾看起来像缺陷。逐条追查 44b8daed（19 条读数、8 个检出结构）后确认
**投影逻辑无误**：11 条有 `entity_id` 的读数正好产出 11 条归因，一条不多不少。

真正的问题是这 26% 把**两类完全不同的信息混成了一个数字**：

- 文献**根本没有画**这个化合物的结构；
- 我们**检出了**结构但规则没能绑定。

前者是文献事实（对药化家有价值），后者才是可修的缺陷。因此新增
`unattributed_by_reason` 分类（`contracts/measurement.py::UnattributedReason`）：

| 原因 | 含义 |
| --- | --- |
| `no_printed_designation` | 读数没有印任何编号 |
| `designation_without_structure` | 印了编号，但文献没画它的结构 |
| `structure_detected_unmatched` | 结构画了，规则没绑上（**可修**） |
| `document_has_no_detections` | 整篇没检出任何结构 |

关键判据是 `document_label_numbers()`：返回文档检出结构携带的**完整**编号。
必须用完整编号而非数字前缀——`77-A` 与 `77` 是不同化合物，按数字比较会把
"没画"的 `77-A` 误判成"画了没绑上"（这正是第一版分类器的错误，已修正）。

真实语料结果：

| 文档 | 读数 | 已归因 | 未归因分类 |
| --- | --- | --- | --- |
| 44b8daed | 19 | 11 | `designation_without_structure` 8 |
| 5a288b | 19 | 0 | `document_has_no_detections` 14 + `no_printed_designation` 5 |
| a96eb3c0 | 5 | 0 | `document_has_no_detections` 5 |

**结论：当前 26% 不是缺陷，而是检出率的直接反映。** 44b8daed 那 8 条里没有一条是
可修的匹配缺口——例如 `77-A`/`77-B` 是手性 SFC 分离产物，原文只印了产率、保留时间和
LC-MS，**没有任何结构图**。全库 13 篇只有 8 个分子检出，因此提升归因率的下一步不是
做索引，而是先确认 MolDet 是否漏检（见 §7）。

### MolDet 实测调参与分子落库缺陷（2026-10-21）

**调参结论：MolDet 无需调整，且没有调整空间。**

在真实语料上扫描置信度阈值 0.50 → 0.05（IOU 0.45、imgsz 960、200 DPI）：

| conf | 读数页检出数 |
| --- | --- |
| 0.50 | 1 |
| 0.25 | 1 |
| 0.10 | 1 |
| 0.05 | 1 |

阈值降十倍，检出数完全不变——因为模型输出的置信度高度集中在 **0.93–0.96**，
0.50 的默认阈值几乎不丢任何框。全语料 13 篇、每篇前 40 页共检出 **3,162 个框**。

页面跳过规则（`text_page_char_threshold=500`，纯文本且无图片的页跳过）在 1,036 页中
只跳过 91 页（9%），且全部集中在 JP2023544789A 一篇；其余 12 篇为 0。

**真正的缺陷：Extract 从不把 `complete` 结构写入 `molecules`。**

完整生产路径实测（CN120943813A，95 页，Extract 174 秒）：

```
ingest_logs: "Extracted 95 pages (81929 chars, 1245 molecules, 2649 evidence rows)"
磁盘:        storage/{doc_id}/crops/  1245 个裁剪图
SQL:         molecules=0  molecule_detections=0  markush_review_candidates=0
```

识别了 1,245 个分子，裁剪图全部落盘，**`molecules` 表一行没有**。

根因：`persist_review_candidates` 只写入 `review_required` / `scaffold` / `fragment`
三类（Markush 侧），而 `complete`（具体分子）被跳过；`persist_molecule_candidates`
虽然实现了 `role == "complete"` 的筛选与写入，但**生产代码从未调用它**——只有测试调用。
此后唯一可能创建分子行的是 Patent 阶段的重发布，而它要求读数能解析到结构归属，
所以没有绑定读数的文档恒为 0 个分子。

修复：Extract 阶段在持久化证据后调用 `persist_molecule_candidates`，只写
`structure_role == "complete"` 的候选。干净库上重跑 CN120329282A：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| `molecules` | 0 | **290** |
| `molecule_detections` | 0 | **290** |
| `markush_review_candidates` | 0 | 47 |

新导入的分子带编号（`name='8'`、`'9'`、`'3'`…），正是活性读数引用所需的实体。

回归测试：`tests/unit/pipeline/test_persist_molecules.py::test_complete_structures_reach_the_library_without_an_activity`
——验证不带任何活性读数的具体结构也会入库。

**仍未解决**：识别出的结构与活性读数的编号绑定。290 个分子里大部分 `name` 为
空或与读数编号不一致，`association.py` 的编号匹配率仍是待提升项。

### 端到端验证与第二处数据破坏（2026-10-21）

修复后跑完整生产流程（Extract + Patent，干净库，3 篇真实专利），首轮结果暴露出第二个缺陷：
**分子入库了，但检出记录被删光**。

```
CN120329282A   分子 290  检出   8   ← 290 个分子里只有 8 个有检出记录
US20210128561  分子 144  检出   0
CN120943813    分子 405  检出   0
```

根因：Patent 阶段的 `persist_candidates_in_transaction` 会**先
`DELETE FROM molecule_detections WHERE doc_id = ?`** 再重写，但它只传入能证明归属的
8 个候选。于是 Extract 写入的其余 282 条检出被整批删除；两篇没有活性读数的文档
（候选为空）更是被清空到 0。

这与「空事实不得残留旧派生」的既有约定冲突。判断：**结构归属权属于 Extract**，
它才是识别并存储全部具体结构的一方；Patent 只重写它证明得了的那几个。
`delete_document_molecule_data` 已在重新提取时负责清理，因此 Patent 不应再删。

修复后：

| 文档 | 分子 | 检出 | 命名 | 读数 | 归因 | 归因率 |
| --- | --- | --- | --- | --- | --- | --- |
| CN120329282A | 290 | **290** | 148 | 19 | 11 | **58%** |
| US20210128561A1 | 144 | **144** | 10 | 0 | 0 | — |
| CN120943813A | 405 | **410** | 58 | 0 | 0 | — |
| 合计 | 839 | 844 | 216 | 19 | 11 | 58% |

**归因率 26% → 58%**（11/19）。这个提升来自两处修复的叠加：
Extract 现在把具体结构写入 `molecules`，Patent 不再把它们删掉。

改动：
- `molecule_store._persist_loop` 的 `molecule_detections` 插入改为
  `ON CONFLICT(mol_id, doc_id, page) DO UPDATE`——同一页画出同一结构（示图 + 表格行）
  会撞 UNIQUE 约束，普通 INSERT 抛错曾中断整篇持久化。
- `molecule_store.persist_candidates_in_transaction` 不再整篇删除，只替换本次候选的检出。
- 既有测试 `test_publishing_empty_facts_clears_the_previous_derived_rows` 的前提被
  架构变更取代，改写为 `test_publishing_empty_facts_keeps_the_structures_evidence_owns`。
- 新增 `test_republishing_subset_keeps_other_structures_detections` 锁住该破坏行为。

### 命名转结构：CMNP 接入（2026-10-22）

扫描件专利里，化合物常在正文以系统命名出现，而结构图根本没画（例如手性 SFC 分离的
77-A/77-B 只有 LC-MS 数据）。这时**命名是回到结构的唯一路径**。

CN120329282A 实测：1014 条文本证据中 190 条含化学命名特征，**16 段同时印了编号和系统命名**，
但只有 5 条进入 artifact——提取器几乎没用上。

**接入方式**：CMNP（纯标准库中文化合物名解析器）已 vendor 到
`src/mbforge/foundation/chemname/`（`parser.py` + `element.json` + `ring_topo.json` +
`func_group_topo.json`），MBForge 侧新增薄适配层 `mbforge.foundation.chemname.parse_name()`：

- **永不抛异常**：损坏的名称是扫描件的常态输入。
- **RDKit 双重校验**：SMILES 必须能被 RDKit 解析，**且**环数不能与 AST 矛盾。
- 校验不通过时保留 AST（供骨架匹配用），但 `smiles` 置空、`smiles_valid=False`。

第二道校验是必须的。实测 CMNP 当前的装配步骤会吐出**合法但错误**的分子：

| 名称 | CMNP SMILES | 实际应为 |
| --- | --- | --- |
| 甲苯 | `C`（甲烷） | 甲苯 C7H8 |
| 氯苯 | `C`（甲烷） | 氯苯 C6H5Cl |
| 乙酸 | `C(=O)O`（甲酸） | 乙酸 C2H4O2 |

RDKit 能解析 `C`，所以只验证"能否解析"会把甲烷当成甲苯写进库——`_smiles_agrees_with_ast`
用 AST 里 `type == "ring"` 的节点判断名称是否含环，含环名称必须产出含环 SMILES。

> **更正（同日）**：上表描述的"装配损坏"其实是**我 vendor 了错误的文件**。CMNP 工作副本
> 的 `parser.py`（sha256 `5216080C…`）装配正确，而我最初拷贝的是另一个版本
> （`9806CD58…`）。重新 vendor 后实测：
>
> | 名称 | SMILES | 分子式 | 环数 |
> | --- | --- | --- | --- |
> | 苯 | `c1:c:c:c:c:c1` | C6H6 | 1 |
> | 甲苯 | `c1:c:c:c:c:c1(C)` | C7H8 | 1 |
> | 氯苯 | `c1:c:c:c:c:c1(Cl)` | C6H5Cl | 1 |
> | 乙酸 | `CC(O)(=O)` | C2H4O2 | 0 |
>
> 全部与预期一致。**教训：vendor 外部代码必须比对内容哈希，不能只看 `git status`**
> ——后者只反映修改状态，我据此误判了版本。`_smiles_agrees_with_ast` 这道校验仍然保留：
> 它防的是"未来装配再次退化"，不是补偿当前的 bug。
>
> 同理，此前"CMNP 单测 8 条全失败"也是我的测量错误——GBK 控制台下中文夹具被损坏导致
> 比较失败。加 `-X utf8` 后 `Ran 8 tests ... OK`，与 README 的 218/233 一致。

**当前 CMNP 能力边界**（实测，`-X utf8`，全部用 RDKit 校验分子式与环数）：

| 输入 | 结果 |
| --- | --- |
| `苯` / `甲苯` / `氯苯` / `乙酸` | ✅ C6H6 / C7H8 / C6H5Cl / C2H4O2，全部正确 |
| `1H-吡唑-4-甲酰胺` | ✅ C4H5N3O，1 环 |
| `喹啉-4-胺` | ✅ C9H8N2，2 环 |
| `3-氯-1H-吡唑-4-甲酰胺` | ✅ C4H4ClN3O，1 环 |
| `1-(2-(甲磺酰基)乙基)-1H-吡唑-4-羧酸乙酯` | ✅ 可生成结构 |
| 含**硫代酰胺**的长命名（`…-2-甲基丙硫酰胺`） | ❌ `pending_review` |

**7/7 个基础骨架化学正确**，包括此前失败的喹啉、吡唑、噻唑。

剩余失败已精确定位到**单一缺失官能团：硫代酰胺**（thioamide）：

```
丙硫酰胺     -> pending_review   ← 缺失
丙酰胺       -> ok
2-甲基丙硫酰胺 -> pending_review   ← 缺失
2-甲基丙酰胺  -> ok
噻唑-2-胺    -> ok
5-(3,5-二氟苄基)噻唑 -> ok
```

含硫代酰胺的长命名因此整条失败（因为解析是右锚定父体驱动的，父体解析不了则整条失败）。
这是范围很小、目标明确的下一步，不是骨架级缺陷。

真实专利样本 5 条中 1 条已可用（`1-(2-(甲磺酰基)乙基)-1H-吡唑-4-羧酸乙酯`），
其余 4 条含硫代酰胺。

### DPI 提升是有毒的（2026-10-22 实测，已回退）

一度把 `detection_dpi` 从 200 提到 300，因为实测编号识别率从 20% 升到 32%、渲染成本只增
0.3s/10 页。**结果是回归**：

| 指标 | 200 DPI | 300 DPI |
| --- | --- | --- |
| 编号识别率 | 20% | 32% ↑ |
| 归因率 | **58%** | **0%** ↓ |
| 重复编号对 | 0 | 31 对，**0 对分子式相同** |

31 对重复编号的样本（同一编号挂到两个完全不同的分子）：

```
'20': C26H26ClF3N4O3S  vs  C25H23ClF3N4O3S
'23': C10H14N2O3S      vs  C25H26ClF3N4O3S
'77': C7H10ClN3O3S     vs  C23H24ClF4N5O3S
```

原因是 OCR 窗口（结构框外扩 15%）在 300 DPI 下读到了**隔壁结构**的编号，属系统性错配而非
歧义。`association` 因此触发 `molecule_candidate_ambiguous` 并全部拒绝。

**已回退到 200**，并把这段证据写进 `MoldetConfig.detection_dpi` 与
`DEFAULT_RENDER_DPI` 的注释，防止后续再"优化"一次。

结论：**提高召回必须先有空间消歧**，否则召回的是错误标签。这项工作记为 `task-2`。

### 空间消歧已落地并接入（2026-10-22）

`task-2` 完成：新增 `service/pipeline/detection/label_assignment.py`（纯几何，无 OCR/GPU/
网络依赖），并已接入 `crop_processor`。

**算法**：先用"settled"样本（一个清晰的印字 + 一个明确最近的图形）推断本页的
**编号约定**（ABOVE / BELOW / LEFT / RIGHT / INSIDE），再用该约定为每个印字竞争图形；
胜过第二名不足 1.5× 的一律报歧义，不强行绑定。

**接入方式**（`CropProcessor.enrich_ocr_labels`）：
- 改成**整页一次性分配**，不再逐裁剪框"就近取标"。
- OCR 读数现在携带自身位置（`ocr_label_image` 返回 `detailed`），并把裁剪窗口内坐标
  加上窗口原点换算到页面坐标系（`slot_read_boxes`）。
- 几何未定归属的结构：`name` 保持空，读数存入 `ocr_labels_unassigned` 作为未验证上下文。
- 页面完全没有位置信息时（后端不返回坐标）回退到旧的 primary 行为，避免静默丢失全部标签。

**真实语料验证**（CN120329282A，113 页扫描件）：

| 指标 | 消歧前 | 消歧后 |
| --- | --- | --- |
| 分子 / 检出 | 290 / 290 | 290 / 290 |
| 命名数 | 148（51%）| 138（48%）|
| 归因率 | **58%** | **58%** |

命名数略降是**预期的质量换量**：歧义标签不再被强行绑定到某个结构上。归因率不退化，
因为读数真正匹配的那批编号本来就在"settled"集合里。

6 个单元测试覆盖：编号在上/在左、共享水平带（**复现 300 DPI 失败模式**，断言旧规则会把
`21` 同时判给 A 和 B 而新规则给出 `{"20":"A","21":"B"}`）、等距歧义、无邻近编号、四种约定推断。

### 正文命名提取（2026-10-22）

`extract_compound_names` 原本**只读 section 标题**，因此正文里"得到化合物 X（系统命名）"
这类句子完全被忽略。新增 `extract_prose_compound_names` 扫描正文：

| 文档 | 证据行 | 正文命名（新增） |
| --- | --- | --- |
| 44b8daed | 2477 | **60+ 条**，最长 78 字符 |
| 5a288b | 439 | 0 |

提取出的都是完整系统命名（`N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)-…-1H-吡唑-4-甲酰胺`）。
设计要点：
- 括号属于名称内部（`N-((1R,3S)-…`），终止条件是句读或紧随的说明性括注（`(化合物38)`）。
- `得到混合物在氮气保护下…` 这类后处理句不是命名，用步骤词表排除。
- **编号留空**：正文很少说明命名属于哪个编号，猜一个会把读数绑错结构。

2 个回归测试：完整长名称提取（不含产率等括注）、后处理句不被当作命名。

### OCR 文本错误与规范化层（2026-10-22）

扫描件专利的文本由 RapidOCR 从页面渲染读取，错误是**小而规律**的一类，不是随机噪声。
全语料（13 篇、10,592 条文本证据）实测：

| 错误 | 次数 | 正确形式 |
| --- | --- | --- |
| `mmo1` | **1253** | `mmol` |
| `[M+H]†` | 573 | `[M+H]+` |
| `mo1` | 84 | `mol` |

**关键证据：这是上下文相关的系统性偏移，不是随机错。** 同一个字形在 `mL` 里 2060 次
读对、仅 2 次读错；在 `mmol` 里则 61% 读错（1253 vs 797）。因此**替换表能精确修复，
不需要模型**。

新增 `foundation/inference/ocr/normalise.py`，并接入 `read_text_in_boxes`（所有页面文本
的唯一出口）：

- 单位尾字母 `l/1/I` 混淆，含**无数量词**形态（`mo1/L`、`mo1%`）
- 日文字体字距导致单位被空格拆开（`m mo1` → `mmol`）
- adduct 上标 `+` 被读成 `†`/`‡`/`⁺`
- `ICs0` → `IC50`；破折号家族统一为 `-`

**不修复、且明确不假装修复的**（需要原始像素，留给后续层）：
数字本身读错（`248.0` 实为 `246.0`）、化学名内部字符错（`三氯甲基`/`三氟甲基`）、
替换表未收录的字形。这三项列在 `RESIDUAL_UNCERTAINTY` 常量里。

**真实语料验证**（CN120329282A，113 页，重新跑完整 Extract）：

| 指标 | 规范化前 | 规范化后 |
| --- | --- | --- |
| `mmo1` 残留 | 270 | **0** |
| adduct 匕首残留 | 有 | **0** |
| `mmol` 正确数 | — | **270** |
| 提取耗时 | 172s | 187s（+8.7%）|

7 个单测覆盖：单位修复、分母形态、adduct、空格拆分、**正确文本不被误改**
（`12.5mL`、`C26H26ClF3N4O3S`、`化合物77-A` 必须原样通过）、更长词不误伤、幂等性。

> 规范化后归因率仍是 58%（11/19）——因为这篇文档的归因瓶颈是结构编号，不是文本单位。
> 文本规范化的收益体现在下游解析（质量校验、名称解析）能正常工作，而不是直接提升归因率。

### 印刷质谱的归属与质量校验（2026-10-22）

`find_mass_mismatches` 是免费的确定性校对器：拿原文印刷的 MS 质荷比，比对结构计算质量。
但它此前**完全失效**——47 条印刷 MS 行，`label_key` 全为空，一条都匹配不上结构。

根因：MS 行在证据里是**独立的 33 字符行**（`[0168] LC-MS,M/Z(ESI):444.1[M+H]+`），
而它所属的化合物印在前面的步骤标题里。原实现只看本行和本证据行。

第一版修复按"同页最近编号"回退，拿到 32/47，但**是错的**：一页多条 MS 会全部绑到同一个
编号。实测证据：p47 的 `265.9` 和 `444.1` 两个不同质量都被绑到编号 `4`。这正是既有测试
`test_an_association_reaches_the_persisted_activity` 守住的行为——它断言"读数上方的谱图不得
继承读数的编号"。

最终判据收窄为**只有步骤标题才授权归属**：

```
第三步：…氨基甲酸酯(化合物8)的合成     ← 步骤标题，带编号
[0168] LC-MS,M/Z(ESI):596.2[M+H]⁺      ← 紧随其后的谱图，归给化合物8
```

实测结果：47 条 MS 行中 **2 条**获得可靠归属（编号 8 和 38），其余保持未归属并作为 gap
交给读者。**这 2 条的质量校验全部通过（0 处不一致）**——说明这些 OCR 结果化学上正确。

宁可只绑定 2 条可靠的，也不绑定 32 条可能错的：错的归属会污染它本要服务的质量校验。

2 个回归测试：步骤标题授权归属、读数上方的谱图**不得**继承读数编号。

**扩大触发率的实测（同日）**：把回退从"紧邻一行"扩到"向上 24 行内的最近步骤标题"
（实测 38/38 条 MS 行都在 24 行内找到标题，其中 33 条恰好距离 5 行），归属从 2 条提到
**5 条**，且没有编号同时拥有多条不同 MS 行。

剩下的 42 条**无法通过改进规则解决**。按标题类型分类统计：

| MS 行归属的标题类型 | 条数 |
| --- | --- |
| 实施例（最终化合物，进 `entries`） | **0** |
| 步骤 / 中间体（`A1-3`、`A1-6` 等） | **41** |
| 其他 | 6 |

**结论：这篇专利的质谱数据几乎全部属于合成中间体，而中间体不是最终化合物、不进入
`entries`。** 所以即使正确解析出 `A1-6` 这类编号，也没有对应结构可校验——这是文献
本身的结构，不是提取缺陷。

这也解释了为何质量校验只有 2-5 条可跑：不是规则不够好，是**可用于校验的样本本来就少**。

### 文本资源盘点与结构-活性链路的实测瓶颈（2026-10-23）

用户要求"完整提取结构活性对应关系"，并对文本可利用资源做整理分析。以下是实测。

**CN120329282A（113 页）文本资源盘点**（2477 条证据行）：

| 资源 | 出现次数 |
| --- | --- |
| 化学名称（`N-(`、`酰胺`、`吡唑`、`喹啉`…） | **664** |
| 化合物编号引用 | 189 |
| 质谱 | 103 |
| 步骤标题 | 82 |
| 靶点 | 43 |
| 中间体编号 | 27 |
| 核磁 | 26 |
| 实施例标题 | 23 |
| 活性数据（IC50 / 抑制率） | 各 6 |

**核心链路实测：实施例标题 → 结构 = 0/23。**

23 个实施例标题**全部印有完整系统命名和化合物编号**，例如：

```
实施例1: N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)
         -1-(2-(甲基磺酰基)乙基)-1H-吡唑-4-甲酰胺三氟乙酸盐(化合物1)的制备
```

**这是结构-活性关系的正解路径**——编号直接给了，不需要猜。但 23 条全部无法转成结构。

**失败原因被精确定位为两个，都是文本错误或装配缺陷，不是解析能力不足：**

1. **化学同形字 OCR 错误**（已修复）。`环已基` 应为 `环己基`。全语料 **78 次错误 vs 105 次正确**，
   `已烷` 33 次错误 vs `己烷` 20 次正确。`已` 对名称解析器是未知字符，导致整条名称失败。
   已在 `normalise_ocr_text` 修复：`已/巳` → `己`（环已基/已烷/环已烷/环已烯）、`酰胶` → `酰胺`。
   修复后 `实施例1` 的 status 从 `pending_review`（`unknown chars ['已']`）变为 **`ok`**。

2. **CMNP 嵌套取代基装配缺陷**（未修复，属 CMNP 侧）。修复同形字后，长名称 status 变 `ok`，
   但生成的 SMILES 只含部分骨架，且**碎片之间用 `.` 断开**：

   ```
   完整名称 → CCN(C2CCCCC2)1N=CC(=C1)C(N)=O.C.C      ← 喹啉、Cl、CF3、磺酰基全丢
   ```
   实测各子片段单独都能正确构建（`喹啉` ✓、`1H-吡唑-4-甲酰胺` ✓、`N-环己基苯甲酰胺` ✓、
   `N-(喹啉-4-基)苯甲酰胺` ✓），**只有多层嵌套组合时装配失败**。

**适配层的行为是正确的**：这些残缺 SMILES 通不过 RDKit，`parse_name` 返回
`smiles_valid=False`，不会污染库。

**结论：结构-活性链路的瓶颈已经从"找不到资源"变成"CMNP 装配不了多层嵌套命名"。**
23/23 全部卡在这一个点上，且这是 CMNP 的独立缺陷，与 MBForge 的数据通路无关。

### 对三层校对方案的验证结论（2026-10-23）

用户提出的方案：小模型判断是否需要校对 → 需要则外部 LLM 校正 → 打标签结构化输出。
实测数据对该方案的**修正**：

| 方案假设 | 实测结果 | 结论 |
| --- | --- | --- |
| 需要模型判断"是否要校对" | 已有免费判据：印刷 MS 质量、环数/分子式一致性 | **不需要模型** |
| 校对主要对象是结构 | 实际最大缺口是**文本同形字**（78 次环已基） | 校对层应是**文本规则** |
| LLM 校正有足够样本 | 可校验 MS 仅 3 条（属最终化合物） | **样本不足，无法验证价值** |

**修正后的分层**：

```
OCR 输出
  ↓
第 1 层【已实现，零成本】文本规范化
   单位(mmo1→mmol) / adduct(†→+) / 化学同形字(已→己)
   实测修复 1253 单位错误 + 78 同形字
  ↓
第 2 层【可用，样本少】确定性校验
   印刷 MS 质量守恒（仅 3 条适用）
  ↓
第 3 层【暂不需要】LLM 校正
   触发依据不足：第 2 层 3 条样本全通过
```

**第 1 层才是当前真正产生收益的部分**，且它是纯规则、零 token。

### 分步顺序（已按此执行）

A1 → A2 → A3 是硬顺序（表 → 契约 → 写入）；A4 依赖 A3；
A5 可与 A4 并行；A6 在 A5 之后；A7 依赖 A5。

### 不在 Phase A 范围

- SAR 矩阵与热图（`api/http/sar.py` 仍是 fail-closed 空壳，保持空壳）；
- 页级"编号 → 结构"的 LLM 索引（这是把解析率提上去的手段，但它属于提取召回，
  建议在 A4 落地、读数能全量入库之后再动，否则无法度量收益）；
- 任何计算编排（对接 / Boltz-2 / 训练）；
- 数据集导出（SDF/CSV）。

## 5. 验证

按 AGENTS.md 的测试准入规则，只在这条链路上补**外部可观察契约**：

- 一篇真实文档跑完 Patent，`measurements` 行数 == artifact `measurements` 长度；
- 一条无归属读数在 SQL 中存在，且 `measurement_attribution` 为空；
- 一条有归属读数可按 `mol_id` 反查，且同时保留 `review_status`；
- 同分子多条读数全部保留（当前被 `[0]` 塌缩），这是本次的核心回归点；
- `query_activities` 对真实文档不再返回空列表。

不新增覆盖顺序/表名/内部函数的测试；扩展现有 `tests/unit/pipeline/test_patent_facts_publication.py`
与 `tests/unit/services/test_review_service.py`。

## 6. 风险

- **重复写入**：`persist_candidates_in_transaction` 每次删旧派生行再写。新表必须在同一事务里
  按 `doc_id` 删除重写，否则重跑会翻倍。
- **标量兼容**：`molecules.activity` 被前端筛选（`activity_presence`）使用，切换前要确认
  它是从新表投影还是继续写标量；两者并存会不一致。
- **`review_items` 关联**：现有 `patent_fact_review` 用 `slot_id` 寻址，新表引入后要确认
  复核项仍能定位到具体 `measurement_id`，避免决定应用到错误读数上。

## 7. 后续阶段（记录，不排期）

### Phase B — 计算层与可复现

目标：让"预测"成为一等公民，且与"实测"物理隔离。

1. `evidence_grade`：`measured` / `predicted` / `derived` / `suggested`，贯穿读数与计算产物；
2. 统一 `compute_runs` 记账（对接 / Boltz-2 / 训练共用）：`model_id`、`model_version`、
   `weights_hash`、`params_hash`（含 seed）、`input_hash`、`started/finished_at`、`run_id`；
3. Boltz-2 接入，含格式桥：当前受体导入**只接受 `.pdb`**
   （`service/use_cases/docking/receptors.py`），而 Boltz-2 输出 mmCIF；
   还需从预测复合物切出蛋白链、切出配体参考构象、推导对接盒；
4. 对接已有基础（UniDock-Pro、`docking_jobs`/`docking_poses`），但 `docking_jobs` 只存
   `params`（含 seed/exhaustiveness），不记录引擎版本，输入侧仅 `receptors.file_hash`
   有哈希、配体侧没有，需要并入 `compute_runs`；
5. 预算闸：非专业用户一次"全跑"可能是几十 GPU 小时，需要 compute budget（可复用
   `patent_analysis` 的 `createBudgetGuard` 形态）。

### Phase C — SAR 与建议

前置条件（任一不满足就不做）：

- 同一母核 + 同一 assay + 同一物种的系列读数达到最小样本量；
- `measurement_attribution` 的结构归属率达到可统计的下限；
- 系列完整性检查可判定（母核判定可复用 `domain/enumeration.py` 里基于 RDKit 骨架编辑的
  MCS / `ReplaceAtom` 能力）。

满足后：SAR 矩阵（当前 `api/http/sar.py` 空壳）→ 只在通过检查时开放；
**合成建议默认不做自动生成**，最多给"该位点已知类似物 + 文献出处"。
理由：逆合成可行性、试剂可得性、实验室约束都不在文献里，模型生成的建议在药化语境下
无法自证。

### 对非专业使用者的约束（跨阶段）

- 报告必须三段式：**文献实测事实 / 计算假设 / 模型猜测**，绝不混表；
- 每条结论可点回 PDF 页码或 `run_id`；
- 数据不足时明确拒绝给出结论（尤其是 SAR），而不是硬跑。

## 8. 相关文档

- [TODO 索引](../TODO/INDEX.md)
- [Patent 分析与领域 Agent Harness 计划](plan-patent-agent-harness.md)
- [活性 ↔ 结构关联](wiki/activity-association.md)
- [专利提取形态目录](wiki/patent-extraction-forms.md)
- [专利采用规则](wiki/patent-adoption-rules.md)
- [真实 LLM 全链路验收 2026-10-16](qa/patent-live-association-20261016.md)
