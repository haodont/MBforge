---
name: patent-active-molecules
description: Extract every stored activity reading and the molecules that own them from one patent. Start from the patent's printed activity table, compare it with what the library stored, and diagnose the gap. Use for "all active molecules", IC50/EC50/SAR tables, activity datasets, or compound potency questions scoped to a document.
---

# Patent active molecules

Two different sources, two different jobs:

- The **printed table** says what the patent reports: which rows exist, what the
  row label is, which value columns the patent prints, and whether it prints the
  structure itself. It is the reference frame.
- **`query_activities`** says what the library stored: the canonical dataset.

Never take a value from the printed table, and never rebuild the dataset from
it. Read the table to know what the answer must cover; take the values from
`query_activities`.

## Workflow

1. Resolve the document with `resolve_document`. Use the exact returned
   `doc_id`; never invent one.
2. Call `document_read` (`part="info"`) and check `has_patent_facts`.
   - If false and the session is read-only, stop and report that Patent facts
     must be produced first. Do not read around the missing facts.
   - If false and writes are allowed, call `submit_patent_analysis`, then poll
   `runs` (`action="get"`) until the Patent stage settles. Report the run id.
3. **Find the printed activity table first.** Call `list_evidence` with
   `kind="tab"` and no page: one call returns every printed table in the
   document (follow `next_offset` until it is `null` if there are more than one
   page of tables). Read the table text and establish:
   - how many activity rows the patent prints, and what the row-label column
     holds — `化合物N` and `实施例N` are not the same key (one patent here
     prints `实施例34 → 化合物1A`), so never assume they agree;
   - which value columns exist (`IC50`, `Cmax`/`AUC`, `LC-MS`, …): a column the
     library has no metric for is a gap, not a row to drop;
   - whether the table prints a **structure column** or an `LC-MS` column. That
     is the patent's own structure↔value relation, printed. Note it even when
     the library binds no structure to it.
   - One table is usually **one evidence row per page fragment**, and each
     fragment repeats the header and drops the separator row. Join fragments by
     their header, not by counting rows: a structure table split over three
     pages looks like three tables.
4. Call `query_activities` with:
   - the exact `doc_id`;
   - no `min_value`/`max_value` unless the user asked for a threshold;
   - optional `metric`, `target`, or `assay_description` only when the user
     asked to narrow the dataset.
5. Follow `next_offset` until it is `null`. Collect every page before saying
   "all". Do not stop because `truncated` was false on one page while another
   page was requested.
6. **Compare the two, row by row.** For every printed row, say whether the
   library stores it; for every stored reading, say which printed row it came
   from. A printed row with no stored reading is a gap to name; its value is
   not to be recovered from the table. The issue codes
   (`get_patent_result(collection="issues")`) say why:
   - `activity_cells_unattributed` names the cells that became no reading (no
     compound beside them, or two readings merged into one cell);
   - `complex_activity_table` means the table was refused whole;
   - `table_header_inherited` means the row was read under the previous page's
     header.
7. Group the readings by `mol_id` for a molecule-level answer, but retain each
   reading under its molecule. A reading with `attributed=false` is not a
   molecule; report it separately as an unattributed reading.
8. If a reading has several `mol_ids`, keep all candidates and say the
   attribution is contested. Never choose one silently.
9. Report coverage from `stats`: total, attributed, unattributed, pending, and
   `unattributed_by_reason`. A document with zero rows has zero stored
   readings, which does not by itself prove the patent reports no activity.

## 用候选材料包做绑定判断（承接工作流第 6 步）

`get_binding_candidates` 把「指代符 → 候选结构」的配对整理好，比逐条读原始
evidence 高效。它**只读、不决定**：判断仍由你做。

调用 `get_binding_candidates(doc_id)`，返回：

| 字段 | 内容 |
|---|---|
| `readings` | 全部读数：指代符、值、单位、页码、`attributed`、`reasons` |
| `designations` | 每个指代符：`label_raw`/`label_key`、`pages`、`context_types`、`has_reading`、`reading_ids`、`candidates`、`attribution` |
| `candidates[]` | `label_keys`、`label_sources`（`page_text` > `crop`）、`designation_counts`、`owns`、`page`/`bbox`、`detection_score`、`formula`/`exact_mass`、`mass_check`、`entry` |
| `review_items` | 待人工复核项（含 `designation_unbound`） |
| `table_cells` | 表内 `[MOL:n]` token 与页码（token→分子映射未持久化） |

`designations` 按 `has_reading` 排序：有读数要安置的指代符在前，其余是文献
印了但没有活性的上下文。`label_raw` 以读数先出现者为准。

### 裁决规则（R1–R7）

对每条未归属读数，按顺序：

| 轮 | 条件 | 动作 |
|---|---|---|
| R0 | 候选集为空 | 归入 `designation_without_structure` / `label_not_read`，不进裁决 |
| R1 | 唯一候选 | 记录；仍需最低置信度（`mass_check=match` 或 `label_sources` 含 `page_text`） |
| R2 | 多候选 canonical SMILES 相同 | 去重 |
| R3 | 置信度不同 | 取最高（原始 PDF > 命名转化 > OCR） |
| R4 | 同置信度 | `label_sources`：`page_text` > `crop` |
| R5 | 仍并列 | `designation_counts` 多数印刷（`owns`） |
| R6 | 平票 | 用 `inspect_visual`（`page_image` / `page_molecules`）读原始页面再判 |
| R7 | 仍不定 | 交人工 |

R1–R5 覆盖大多数；R6 才是看图；R7 才落到人。

### 结果写到哪里

**R1–R5 能自动裁决的**：调 `assign_attribution`（mutating，需 edit token）落
`method=agent`、`review_status=accepted`；载荷 `doc_id` / `measurement_id` /
`mol_id`（候选的 `mol_id`，即 canonical SMILES）/ `evidence_id` / `confidence`。
该 capability 会校验读数存在且分子已入库，否则 404。

- **R6 看图后确定的**：同样落 `method=agent`（把 `evidence_id` 指向被看的结构证据）。
- **R7 仍不定的**：指到 `designation_unbound` 复核项
  （`[[ui:review:designation_unbound:<item_id>]]`），由人确认后落 `method=human`；
  agent 链接会被 human 覆盖（优先级 human > agent > rule）。
- 不要用 `propose_review` 对 measurement 目标落值（record-only）。

> 名称转化（化合物名 → 结构）是已记录的 TODO，当前**不可用**；不要假设它能用。
> 表内 `[MOL:n]` → 分子的映射未持久化，包只报 token，不指认结构。

## Read the page before you judge it

Every structural question about a patent is answered by looking, not by
reasoning from the numbers:

- `inspect_visual` (`action="page_text"`) returns the page's text blocks **with their positions and
  the layout producer's reading order**. Use it to see how the document prints
  its compound numbers and names, and where.
- `inspect_visual` with `action="page_image"` renders the page. Look at it: a
  compound list prints its number in the gutter beside the drawing, and no
  amount of coordinate arithmetic says so as clearly as one look.
- `inspect_visual` with `action="page_molecules"` re-runs MolDet and MolParser
  on one stored page on demand and returns every structure with its box. It
  persists nothing and costs no re-ingest — the cheap instrument for "is this
  the same molecule as the one on the other page?".
- `inspect_visual` with `action="molecule_image"` renders a SMILES. Use it when
  two recognised structures differ and the difference decides an attribution.
- `verify_structures` reports every recognised structure with its formula,
  mass, printed designation and the compound entry that owns it — the place to
  see whether a designation was bound to the right drawing.
- `search_molecules` checks a structure against the library by text,
  substructure or similarity.
- `propose_review` files a gap for a human decision. Use it when the gap is
  real and a person must settle it; it never applies a value.

## Handing a gap to a human

The Patent stage already queues one `designation_unbound` review item per
reading that has no structure (`patent_facts.py`, ``_queue_unbound``), each
with a candidate list of the structures drawn near it. **Do not file an AI
proposal for these**: `ai_review` is record-only for a measurement target
(`RECORD_ONLY_TARGETS`), so confirming it writes nothing. The item that binds
the attribution is the `designation_unbound` one, and confirming it writes
`measurement_attribution` with `method="human"`.

Read the queue with the backend use case, then hand the person a deep link:

```
http://localhost:5173/review?kind=designation_unbound&status=pending&id=<item_id>
```

`ReviewCenter` seeds its filters and selection from `kind` / `status` / `id`,
and resolves an `id` that is not on the first page through
`useReviewItem` → `GET /api/v1/review/items/{kind}/{id}`. Check the candidate
list before pointing at an item: a candidate set that does not contain the
structure the crop evidence names is not confirmable, and the fix belongs in
the pipeline, not in the review center.

## Why a reading has no structure

`unattributed_by_reason` separates the causes, and they need different work:

| reason | what it means | what usually fixes it |
|---|---|---|
| `label_not_read` | no structure carries that designation | the number was never read, or never attached to a drawing |
| `structure_detected_unmatched` | a structure carries the designation, but the reading's own entry did not bind | two candidates claim the designation, or the name was taken by another drawing |
| `designation_without_structure` | the document names a compound it never drew | nothing — the patent does not print that structure |
| `no_printed_designation` | the reading names no compound | the value sat in prose without a compound beside it |

Before concluding anything about a designation, check the two questions that
explain most failures: **was the same compound printed twice** (a patent lists
its compounds in two places, and the second print is not a second compound),
and **did another drawing steal the name** (a molecule row keeps the first name
written for its SMILES).

## Traps

- **The reading order is not the compound numbering.** The layout producer
  reads a two-column page row by row across the columns, while a patent
  numbers its compounds column by column. Do not use "the numbers ascend in
  reading order" as a binding rule.
- **A number beside a drawing is not necessarily beside *that* drawing.** In a
  two-column list the number sits in the gutter, almost as close to the
  neighbouring column's drawing as to its own.
- **The same compound is often printed twice** (a first list and a second one
  later in the document). Two drawings of one compound are not a conflict;
  compare their formula and mass before calling a discrepancy.
- **A cell may hold two readings** (`>100 (40%) >100 (45%)`): the layout merged
  two rows, and neither value belongs to the row without guessing.
- **`± SEM` is one value** (the mean), and `>100 (4%)` is one censored reading
  with its inhibition percentage.

## Output

For each molecule, report:

| Field | Source |
|---|---|
| compound label / designation | `reference_raw` or `reference_key` |
| molecule id | `mol_ids` / `molecules[].mol_id` |
| SMILES | `molecules[].smiles` |
| printed name | `molecules[].name` |
| assay/target | `assay_description`, `assay_type`, `target` |
| metric and value | `metric`, `value`, `unit_original`, `operator` |
| qualitative result | `qualitative_label`, `qualitative_raw` |
| location | `page_num`, `table_idx`, `row_idx` |
| provenance | `evidence_ids` |
| status | `attributed`, `review_status`, `reasons` |

Group by assay when a molecule has readings from multiple assays. Never compare
values with different units or different metrics. Keep the original value and
unit next to the canonical value.

State the coverage gap in the same answer: which printed rows have no stored
reading, which stored readings own no structure, and — when the patent prints a
structure column — that the printed structure↔value relation exists in the
document but is not bound in the library.

## Failure rules

- `get_binding_candidates` is an accelerator, not a prerequisite: if it is not
  in the active tool list (an older session), read `list_evidence` +
  `verify_structures` and do the same comparison by hand. Do not use its
  absence as a reason to skip the binding question.
- If `query_activities` is not in the active tool list, say the capability is
  unavailable. Do not fall back to OCR, Markdown tables, or evidence search for
  *values*. Reading the printed table for the reference frame is not a fallback
  for values and stays allowed.
- If a field or identifier is absent from tool output, say it is unavailable.
  Never infer a number or SMILES from page text or pixels.
- Never present a pending or rejected reading as an accepted fact; show its
  status.
- Never claim completeness while `next_offset` is non-null.

## 缺口需要 agent 补齐时

上面这套只读诊断说明"哪条读数没有结构、为什么"。要真正把读数关联完，走
`patent-binding-repair` skill：它在同一个候选材料包上做裁决、用
`assign_attributions` 批量落库，并把无法证实的项交复核。代码规则跑不通的
那部分（编号未读到、同号不同图、示例与化合物编号不一致）归它处理。
