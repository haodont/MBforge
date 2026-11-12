# agent 主导的"结构 ↔ 活性"绑定计划

状态：**方案 C 已实现**（只读 capability `get_binding_candidates`，见 §12）；三层架构未开工。
日期：2026-11-12。
关联：[活性数据提取与落库改造计划](plan-activity-extraction.md)、
[Activity ↔ molecule association](wiki/activity-association.md)、
[TODO 索引](../TODO/INDEX.md)。

> 命名说明：本文件的"方案 C"指**最小候选读面原型**，与
> [plan-activity-extraction.md](plan-activity-extraction.md) 的"Phase C（SAR 与建议）"
> 不是同一件事。后者是更远的计算/建议阶段，本文件不涉及。

## 0. 定位

既有文档已经把"读数落库 + 确定性关联"做完了，本文件**不重复**其实测数据，只记录
下一步方向：

- [plan-activity-extraction.md](plan-activity-extraction.md)：`measurements` /
  `measurement_attribution`（`method = rule / model / human`、`confidence`、
  `evidence_id`、`review_status`）、归因原因码、CMNP 命名转结构（已删，可从 git
  历史恢复）。
- [wiki/activity-association.md](wiki/activity-association.md)：关联链、每条未归属
  路径与真实语料实测（实测数字以该文为准，本文件不复制）。
- [TODO/INDEX.md](../TODO/INDEX.md)：提取、关联、复核的当前状态与已知缺口。

本文件要回答的问题是：**语义绑定（指代符 → 结构）是否应该从确定性流水线里拆出来，
交给 agent 主导，流水线改为候选材料供应方。**

## 1. 问题陈述

确定性流水线在"读表 + 落库"上已被证明高效且可复用：它把原始 PDF 变成带页码的
证据行、把表格解析成读数、把结构图识别成 SMILES。这些是 agent 自己读原始 PDF
做不到的（见 [TODO/INDEX.md](../TODO/INDEX.md) 的"Agent molecule-recognition tool"：
模型看页面图像能读出数值，但**无法**从结构图产出 SMILES）。

但流水线的**语义绑定**在复杂文本上已证明不适应：

- 同一化合物印两次、两次识别不一致 → 编号歧义（`molecule_candidate_ambiguous`）；
- 编号印在栏间空隙，与邻栏图等距 → 错绑或漏绑；
- 表格转置、跨页 fragment、一格两读数、定性分档 → 整表拒绝或静默丢失；
- 指代符与实施例的对应关系因文档而异，没有全局映射。

结论：**流水线负责"把材料准备好"，agent 负责"判断谁是谁"。**

## 2. 已确认的决定

1. **流水线定位**：改造为候选材料供应方——确定性提取（文本/表格/结构）保留并增强，
   语义绑定交给 agent。
2. **裁决主体**：agent 为主，流水线规则为辅。
3. **名称转化**：保留为 TODO，必须解决（难识别结构复核 + 加速指代符—结构关联）。
4. **指代符键空间**：无全局绝对映射，**按文档自适应**；流水线给候选，agent 按文档
   定映射。
5. **置信度**：原始 PDF 页面 > 化合物命名转化 > OCR 结构。
6. **裁决策略**：大部分自动裁决，规则穷尽仍不定 → 人工。

## 3. 目标架构（三层）

| 层 | 职责 | 产物 | 写库 |
| --- | --- | --- | --- |
| **L1 流水线**（确定性） | 文本提取、表格定位解析、结构识别、名称候选、指代符索引、候选配对 + 置信度打分 | **候选材料包**（读面） | 写**基线归属**（`method=rule`）与候选/证据 |
| **L2 agent**（语义） | 读候选材料包；规则穷尽后读原始页面/文本；做指代符—结构绑定与冲突裁决 | 归属决定（带证据引用） | 写 `method=agent`（新增枚举值） |
| **L3 人工** | 处理 agent 挂起的歧义 | `measurement_attribution, method=human` | 人工确认 |

### 3.1 关键修正：L1 必须保留基线归属

对抗性审核指出：若 L1 只产候选、不写归属，**没有 agent 在场的文档**将没有任何归属
数据——这些文档里已由规则归属的读数会直接归零。

因此 L1 继续写确定性归属作为**基线**，L2 做**增强/纠错**，而不是取代。一条
`measurement` 可有多条 `measurement_attribution`（表已支持"零行合法"）：

- 基线：`method=rule`；
- 修正：`method=agent`；
- 终裁：`method=human`。

**优先级**：`human > agent > rule`。展示/导出取最高优先级且 `review_status=accepted`
的那条。

### 3.2 与"Patent 确定性"规范的关系

AGENTS.md 明确 Patent 阶段是确定性的（LLM 分析已移除）。本设计**不把 LLM 判断放回
流水线内**：L1 仍是纯确定性代码，L2 发生在流水线之外（agent 会话），L2 的决定通过
写入路径落库。规范冲突的表述需要精确：**事实层的归属可以由 agent 产生，但流水线
本身不做语义判断。**

## 4. 裁决规则 R1–R7 与置信度模型

对每个指代符的候选集：

| 轮 | 条件 | 动作 | 层 |
| --- | --- | --- | --- |
| R0 | 候选集为空 | 直接落归因原因码，不进裁决 | L1 |
| R1 | 唯一候选 | 自动绑定（**需过最低置信度门槛**） | L1 |
| R2 | 多候选但 canonical SMILES 相同 | 去重绑定 | L1 |
| R3 | 置信度不同 | 取最高（PDF > 命名 > OCR） | L1/L2 |
| R4 | 同置信度 | 证据来源优先（页面印刷编号 > 表内结构列 > 裁切 OCR） | L1 |
| R5 | 仍并列 | 多数印刷 | L1 |
| R6 | 平票 | agent 读原始页面/文本再判 | L2 |
| R7 | 仍不定 | `propose_review` | L3 |

R1–R5 覆盖大多数（自动）；R6 是 agent 语义；R7 才是人工。

### 4.1 对抗性审核对规则的修正

- **R1 需要最低置信度门槛**：唯一候选只说明候选少，不说明正确；唯一但错误的候选
  （误识别/误读编号）会被自动固化。
- **R3 的"PDF"证据在 L1 不可用**：L1 是确定性代码，没有"看页面"的能力；"原始 PDF"
  是 L2 的证据。L1 自动规则只能用 OCR/表格证据，PDF 证据只在 agent 实际读页后参与。
- **R4 的表内结构列可能是通式/Markush**：此时它不该优先于一个明确的具体结构；
  需先判断该列是具体结构还是通式。
- **R5 多数印刷的适用面窄**：多个不同结构争同一编号，更可能是编号复用/歧义，
  不是"多数正确"。多数印刷只能作为弱信号。
- **R6 → R7 的转移判据未定义**："仍不定"需要可操作判据（例如 agent 读页后仍存在
  两个同等证据的候选）。
- **R0 缺失**：候选集为空时 R1–R7 全不适用，必须单独处理。
- **可执行性依赖 L1 字段**：R2 需要 canonical SMILES；R3 需要置信度；R4 需要来源；
  R5 需要计数。L1 字段不全 → 实际只剩 R1 + R7。

### 4.2 置信度模型

"原始 PDF > 命名转化 > OCR 结构"是**证据质量**排序，但不应硬编码来源类别：一个
高质量 E-SMILES 识别可能比一个含糊的命名转化更可靠。**置信度应分数化**（0–1），
由以下信号加权：

- 编号来源（页面印刷 > 表内结构列 > 裁切 OCR > 重复印刷）；
- 识别置信度（MolDet score，仅作弱信号——它表示"找到结构"而非"SMILES 正确"）；
- 独立校验（印刷 MS 质量守恒、分子式/环数一致性）；
- 印刷一致性（同一化合物多处印刷是否得到同一 SMILES）。

## 5. 指代符键空间

现状（见 [wiki/activity-association.md](wiki/activity-association.md) §3.2 与
[plan-activity-extraction.md](plan-activity-extraction.md)）：

- `normalize_reference_label` 产出 `key + reference_type`
  （`compound` / `example` / `e_series` / `letter_ambiguous` / `unresolved`）；
- `compound_label_key` 处理字母系列（`A-1`、`B-40`）；
- `designation_key` 处理系列编号后缀（`I-256-A`）与立体前缀（`cis-`/`trans-`）；
- 示例分支接受" 组分 N"（`@example:15组分1`）。

**决定**：键空间**按文档自适应**。理由：`化合物N` 与 `实施例N` 可能指同一物，也可能
指不同物（例如某专利印 `实施例34 → 化合物1A`）；没有全局映射。

**职责切分**（避免与 L1 确定性冲突）：

- **L1 只做候选生成**：收集所有指代符 token 及其上下文（页码、类型、出现次数），
  不解析全局映射；
- **L2 做映射解析**：按文档判断 `化合物N` / `实施例N` / 系列编号 / `组分N` 的关系，
  并产出该文档的键映射表（可作为候选材料包的一部分）。

## 6. 结构来源与优先级

| 优先级 | 来源 | 说明 |
| --- | --- | --- |
| 1 | 表内结构列 | 专利自己印的"指代符—结构"关系；需先判断是具体结构还是通式 |
| 2 | 结构图识别 | MolDet + MolParser；编号来源：页面印刷 > 裁切 OCR > 重复印刷 |
| 3 | 文本关联 | 指代符出现在实施例/正文 → 附近结构；含"实施例 → 化合物"映射 |
| 4 | 名称转化 | 化合物名 → 结构；**TODO，当前不可用** |

## 7. 名称转化（TODO，必须解决）

**为什么必须**：扫描件专利里化合物常在正文以系统命名出现，而结构图根本没画（例如
手性 SFC 分离产物只有 LC-MS 数据）。此时命名是回到结构的唯一路径；即便画了结构，
命名也能加速指代符—结构关联并用于复核。

**历史**：CMNP（纯标准库中文化合物名解析器）曾 vendor 到
`src/mbforge/foundation/chemname/`，适配层 `parse_name()` 永不抛异常、用 RDKit 双重
校验（SMILES 可解析 + 环数与 AST 一致）。2026-11-04 删除，原因是无生产路径导入。
**可从 git 历史恢复。**

**已知边界**（实测）：

- 基础骨架（苯/甲苯/氯苯/乙酸/吡唑/喹啉/噻唑）正确；
- 多层嵌套取代基装配曾失败（碎片用 `.` 断开，喹啉/Cl/CF3/磺酰基丢失）；
- 硫代酰胺缺失，导致含该官能团的长命名整条失败。

**待定**：

- 工具选型：恢复 CMNP / 接入 OPSIN / 调 PubChem / 内部词典；
- 触发条件：仅在结构未画出或识别失败时，还是始终作为候选来源；
- 落库位置：命名候选进 `molecules` 还是独立候选表。

## 8. 对抗性审核（反例与修正）

由主 agent 扮演反驳者完成（`review_task` 子智能体两次超时，未产出）。完整反例如
§4.1 与下：

1. **L1 不写归属 = 无 agent 文档退化** → 修正为保留基线归属（§3.1）。
2. **R1 唯一候选可能错误** → 加最低置信度门槛。
3. **R3 把 PDF 证据放进 L1 是层次错配** → PDF 证据只在 L2 可用。
4. **R4 表内结构列可能是通式** → 先判具体/通式。
5. **R5 多数印刷可能固化错误** → 降为弱信号。
6. **R6 → R7 判据未定义** → 需要可操作判据。
7. **R0 缺失** → 候选集为空单独处理。
8. **规则依赖 L1 字段，未验证** → 列为方案 C 的验证项。
9. **置信度硬排来源类别** → 改为分数化。
10. **与 Patent 确定性规范冲突** → 精确表述为"流水线不做语义判断，事实层可由 agent 产生"（§3.2）。
11. **名称转化投入产出存疑**（OPSIN 对中文支持有限）→ 保留 TODO，但需先验证触发面。
12. **最小改动/测试准入**：三层全量是大改，R1–R7 分支密集，测试成本高。

## 9. 修正后的路线

| 方案 | 内容 | 风险 | 建议 |
| --- | --- | --- | --- |
| A 三层全量 | L1 重构 + L2 落库 + L3 闭环 | 大改、规范冲突、测试重 | 暂缓 |
| B 增量 | 保留现有 facts；增强读面；agent 增量裁决走 `propose_review` | 中 | C 成功后 |
| **C 最小原型** | 只做候选读面，验证 agent 能否仅凭它正确裁决 | 小 | **先做** |

方案 C 成功后：B（把包接进技能，agent 增量补全）；最后才考虑 A。

## 10. 方案 C 设计：最小候选读面原型

### 10.1 目标

用最小改动回答一个问题：**agent 仅凭"候选材料包"能否做出正确的指代符—结构裁决？**
不改写入路径，不改 schema，不动流水线归属。

### 10.2 范围

- 新增一个只读 capability（建议名 `get_binding_candidates`，或扩展
  `verify_structures` / `get_patent_result`）。
- 输入：`doc_id`。
- 输出：候选材料包（§10.3）。
- 不写库、不改 schema、不改流水线、不实现名称转化。

### 10.3 候选材料包内容

1. **读数清单**：`measurement_id`、指代符（raw / key / type）、metric、value、unit、
   operator、定性标签、page / table / row、当前归属（method / confidence / status）。
2. **指代符索引**：token、规范化键、页码、上下文类型（表行标签 / 实施例标题 /
   正文 / 结构图标签）、出现次数。
3. **结构候选**：`mol_id`、SMILES、name、labels（含来源：`page_text` / `crop` /
   `repeated_print`）、page、bbox、detection score、formula / mass、印刷 MS 的
   delta 与 verdict。
4. **候选—指代符配对**：候选携带的指代符、来源、置信度。
5. **表内结构列映射**：`[MOL:n]` token → 分子。
6. **名称候选**：先留空（TODO）。
7. **现有归属与复核项**：`measurement_attribution`、`designation_unbound` /
   `ai_review` 待办。

### 10.4 产物

- 一个只读 capability + service use case。
- 一个契约测试：包字段完整、与现有读面（`query_activities` / `verify_structures` /
  `list_review_queue`）一致。
- 一份真实文档验证记录。

### 10.5 验证方式

- **盲测**：选 `CN120118069A`（41 条未归属读数，见 §12.1；`CN119504738A` 读数在 re-ingest 后被清空）与
  `US20210128561A1`（4 条未归属读数：A-26、B-49×2、B-50）。agent 仅凭包做裁决，
  与已知答案对比。
- **度量**：裁决准确率；包完整性（是否缺少决策所需字段）；需要额外读页的比例。
- **对照**：与当前"无包、直接读 evidence"的方式对比耗时与准确率。

### 10.6 验收

- capability 返回完整包，契约测试通过。
- 盲测准确率达到可用阈值（先测再定数值，不预设）。
- 明确回答："agent 仅凭包能否正确裁决"——能则走 B，不能则先补字段。

### 10.7 非目标

- 不写库、不改 schema。
- 不实现名称转化。
- 不做 L1 重构。
- 不改流水线归属逻辑。

## 11. 风险与开放问题

| 风险 | 说明 |
| --- | --- |
| L1 字段不全 | R2–R5 依赖 canonical SMILES / 置信度 / 来源 / 计数；任一缺失规则退化为 R1+R7 |
| 基线 vs agent 归属并存 | 需要明确的优先级与展示规则；`measurement_attribution` 已支持多行，但展示/导出需确认 |
| 键空间自适应的边界 | "按文档自适应"可能被误读为"任意映射"；需要可审计的映射表与证据引用 |
| 规范表述 | 需精确说明"流水线确定性"与"事实层由 agent 产生"的边界 |
| 名称转化 ROI | 触发面可能很小（CN 专利极少给系统命名），需先量化 |

## 12. 实施记录（方案 C，2026-11-12）

方案 C 已实现：新增只读 capability `get_binding_candidates`，只读、不写库、不改 schema。

| 文件 | 改动 |
| --- | --- |
| `service/use_cases/documents/binding_candidates.py` | 新增：指代符索引 + 候选配对 + 读数/复核项/表内 token 组合 |
| `service/capabilities/read_binding.py` | 新增：capability 与 DTO，注册到 registry |
| `service/use_cases/documents/structure_verification.py` | `_structure_row` 增加 `name`/`labels`/`label_sources`/`designation_counts`（加法） |
| `service/capabilities/read_structures.py` | `VerifiedStructure` 同步新字段（两个读面共用） |
| `service/use_cases/documents/activity_queries.py` | `list_activity_records` 读数增加 `attributions`（加法） |
| `tests/unit/services/test_binding_candidates.py` | 新增 2 例（join + 分页/token） |
| `tests/unit/capabilities/test_capability_http.py` | 新增 1 例（capability 端到端） |

真实库验证（`CN120118069A`，69 条读数）：**158 指代符、170 候选结构、40 复核项、3 张表 token**；
`label_sources` 有 `crop`/`page_text`，`designation_counts` 有值（例如 `{'27A-4': 6, '0': 1}`）。

### 12.1 既有问题（非本次引入，但影响盲测）

1. **re-ingest 清空了部分文档的 `measurements`，Patent 未重跑**：`CN119504738A` 与
   `CN121717757A` 现在 0 条读数（结构仍在）。盲测改用 `CN120118069A`。
2. **提交的 Patent 快照与当前 `PatentFactsArtifact` 不一致**：快照含 `coverage` /
   `conflicts` / `review_candidates` / `llm`，当前模型 `extra=forbid`，`load_patent_facts`
   判为 malformed 并返回 `None`，因此包的 `entry` 上下文（`context_types` 里的 `entry`、
   候选的 `entry` 字段）暂时缺失。重跑 Patent 会重写快照。
3. **表内 `[MOL:n]` → 分子的映射未持久化**：`molecule_cells` 只在布局产物里，SQL 没有，
   所以包只报 token 与页码，不指认结构。

### 12.2 方案 A：agent 归属写入路径（2026-11-12）

| 文件 | 改动 |
| --- | --- |
| `contracts/measurement.py` | `AttributionMethod` 增加 `agent` |
| `db/measurement_store.py` | `bind_attribution` 增加 `confidence` 参数 |
| `db/sqlite/schema.py` | `method` 注释补 `agent` |
| `service/capabilities/write_binding.py` | 新增 mutating capability `assign_attribution` |
| `service/use_cases/documents/activity_queries.py` | `effective_attribution`（human > agent > rule）+ 读面暴露 |
| `service/use_cases/documents/binding_candidates.py` | 候选 `mol_id` 回退到 canonical SMILES |
| `agent/skills/patent-active-molecules/SKILL.md` | R1–R5 自动裁决改为调 `assign_attribution` |

裁决语义：agent 写入 `method=agent`、`review_status=accepted`（立即生效）；人工链接覆盖它。
`assign_attribution` 校验读数存在且分子已入库，否则 404；mutating 需 edit token（无 token 403）。

验证：`uv run pytest tests/unit/services tests/unit/capabilities tests/unit/routers/test_activity.py -q` → **91 passed**；
真实库 `CN120118069A` 28 条已归属读数的 `effective_attribution` 全部非空。

## 13. 相关文档

- [活性数据提取与落库改造计划](plan-activity-extraction.md)
- [Activity ↔ molecule association](wiki/activity-association.md)
- [专利提取形态目录](wiki/patent-extraction-forms.md)
- [专利采用规则](wiki/patent-adoption-rules.md)
- [TODO 索引](../TODO/INDEX.md)
- [Gold standard for relation pairs](plan-gold-standard.md)
