---
name: patent-binding-repair
description: Drive a patent document's structure-activity binding to completion by adjudicating the readings the deterministic rules left unowned. Use when the user asks to fix, complete, or verify that all activities in a patent are linked to structures, when `unattributed_by_reason` is non-zero, or when the review queue is full of `designation_unbound` items.
---

# Patent binding repair

The deterministic pass cannot finish this job alone. It reads what it can
(labels, headings, product statements, masses) and refuses to guess the rest;
the residue is exactly what a reader settles by looking at the page. Your job
is to be that reader, one adjudicated batch at a time, and to leave a record of
why each link is right.

Rules you never break:

- Values come from `query_activities`, never from a printed table, Markdown, or
  a screenshot. You are deciding *ownership*, not values.
- A link you write says "this reading and this stored structure are the same
  compound". If the evidence does not say that, it goes to the review queue.
- `method=agent` is outranked by a human link, so a later human decision costs
  nothing; a wrong agent link is a silent data corruption.

## The loop

Run this loop until the remaining readings are proven to have no structure:

1. **Measure.** `query_activities(doc_id, limit=1)` → `stats`. Record `total`,
   `attributed`, `unattributed_by_reason`. This is the scoreboard; do not
   estimate from the printed table.
2. **Fetch the packet.** `get_binding_candidates(doc_id, limit=50)` and follow
   `next_offset` until `null`. Designations with `has_reading` come first.
3. **Triage by reason**, using the playbook below. Skip nothing silently: every
   unattributed reading must end as an agent link, or as a named gap with the
   page evidence that proves it cannot be linked.
4. **Decide** using the evidence ladder. Prefer document statements
   (product sentence, caption, printed mass) over geometry, and geometry over
   visual impression.
5. **Write one batch per document pass**: `assign_attributions(doc_id,
   decisions=[...])`. The batch is validated as a whole — one bad decision
   rejects the write, which is what keeps a partial pass from looking finished.
6. **Re-measure** with step 1 and compare. If the number did not move, the
   decision was wrong or the gap is not what you thought: re-read the page
   before writing again.
7. **Record**: the scoreboard before/after, the designations still open and why,
   and the evidence ids you relied on, in `work_state` (a `decision` thread).

## When the structure itself is missing

`label_not_read` and `structure_detected_unmatched` can both mean the same
thing: the drawing was recognized, the designation was printed, and no
`molecules` row exists because the Markush role gate withheld the drawing (its
neighbouring prose mentions R-groups or a generic formula, which is normal in a
CN example section). `get_binding_candidates` shows it as `entry:
structure_status: missing` with `owns: true`, and `search_molecules` finds only
the intermediates.

That is not a decision to make — it is a promotion:

1. Read the drawing's evidence (`verify_structures`, `inspect_visual`) and
   confirm it is a closed structure with a printed designation, not a generic
   scaffold. A scaffold, a fragment with a dummy atom, or a rejected structure
   must never be promoted.
2. `promote_structure(doc_id, smiles=… | evidence_id=…, reason=…)` stores that
   one drawing as a concrete molecule and records the reason on it. It is
   idempotent.
3. `assign_attributions` the readings (or re-run Patent: the entry now binds by
   rule, which is cheaper for many readings on one compound).

Do not re-run Extract to fix a withheld drawing: the role gate would withhold it
again unless the document prints the same number on two or more drawings of it
(which `classify_structure_role` already treats as the document's own naming).

## 同号多次印刷不是歧义

一份专利把同一个化合物印在很多地方（权利要求清单、实施例方案、活性表引用），
这是常态，不是冲突。看到同一编号有多张图时：

- 先确认它们是不是**同一个实例**：同一结构的多次印刷在库里是一个 molecule，
  两张图都指向它即可，不要按"候选太多"处理；
- 如果两张图的结构式不同，那么"哪一张是这个编号"由**制备它的那个实施例所印的
  LC-MS** 决定（实测 CN121717757A：`I-266-A` 权利要求图 572.2、实施例图 558.16，
  实施例26 印 `(M+H)+ = 558.0` → 取 558.16 那张）。这条已经写进 association
  （`designation_settled_by_printed_mass`），所以先看它有没有替你判；
- 只有"没有 MS、或两者都在容差内"才轮到人。

## 先确认管线已经能做什么

下面这些以前需要人工补，现在由确定性规则处理，遇到时先重跑而不是先动手：

| 症状 | 现在的处理 |
| --- | --- |
| 图注被读成 `1-2` / `1-273-A`（首字符 1/I 混淆、无字母） | `figno` 图注按指代接受，`1`/`I` 用系列字母还原 |
| 图注印在图的**上方**（p32 那种网格） | 居中的图注上下皆可，第一遍仍按惯例优先 |
| 编号只在同一结构的多张图上出现、周围散文是 R 基定义 | 角色门放行（印两次 = 文档自己的命名） |
| 一编号两结构 | 印刷 MS 定夺（见上） |

重跑 Extract 只在**标签规则**是原因时才值得（它要几分钟到十几分钟，且会重新
OCR 整篇）。归属/结构判断一律用能力写入，不靠重跑。

## 复核队列是工作清单，不是历史

- 某个读数被后续 pass 判断上之后，它的 `designation_unbound` 项会被自动关闭；
  **不要**再去解释或"重新打开"已关闭的项。
- `review_required` 项是**角色门扣下的图**：这正是 `promote_structure` 的对象，
  不是"没有结构"。先看图与证据，再提升，再 `assign_attributions`。
- human/agent 的归属在重跑后保留（只要读数还在），所以不必重复写；重复写只会
  产生同样的 `method=agent` 行。

## Reading the reason correctly

`unattributed_by_reason` tells you which playbook applies. Misreading it is the
most common way to waste a pass.

| reason | means | playbook |
|---|---|---|
| `label_not_read` | no stored structure carries that designation; unlabeled drawings exist | find the drawing, prove it is the compound, link it |
| `structure_detected_unmatched` | a drawing *does* carry the designation, but the reading's entry did not bind | the candidate list already has it — check `owns`, then link |
| `designation_without_structure` | the document names a compound it never drew | prove absence on the page, then stop |
| `no_printed_designation` | the reading names no compound (`阳参化合物`, a WO patent number) | not a compound of this document; stop |

### `structure_detected_unmatched` — usually already decided

`get_binding_candidates` lists the claiming structures per designation. Link
`measurement_id → candidates[0].mol_id` when:

- `owns: true` and there is exactly one candidate, or
- several candidates share one canonical SMILES (duplicates from two printings),
  or
- `label_sources` contains `page_text` (the page printed the number there) and
  the others are crop guesses.

If two *different* structures both own the designation, the page is ambiguous —
`inspect_visual(page_molecules, page=...)` on that page decides, and if it does
not, leave the review item.

### `label_not_read` — the drawing exists, its number did not

This is where agent work replaces a rule that cannot exist. The packet's
`designations[].nearby_structures` lists the unlabelled drawings printed on the
reading's own pages; `unlabeled_structures` is the same material unfiltered.

Find the right drawing with, in order:

1. **A printed mass.** `verify_structures` reports `printed_ms` and
   `mass_check: match` per structure at the document's own 0.6 Da tolerance.
   A printed `MS … [M+H]+` that matches one unlabeled drawing is strong
   evidence — the patent printed the compound's mass next to it.
2. **The synthesis section.** `search_evidence("实施例19")` / the compound
   number finds the section that prepares it; the drawing inside that section
   is the product. `inspect_visual(page_text, page=...)` shows the caption.
3. **The page itself.** `inspect_visual(page_image, page=..., region=[x0,y0,x1,y1])`
   (PDF points) on the drawing's box: read the label the pipeline could not.

If the drawing carries a caption your reader can see but the library has no
label for, that is still a printable link: the reading and the drawing are the
same compound by the document's own layout. Link it and cite the structure
evidence id.

**Two drawings for one designation** (a cis/trans pair printed as
`19-P1 or 19-P2` under a shared `19`) is not one compound. Do not pick one
silently; the review item carries the pair, or the pair is genuinely the
substance the reading measured. Say which you concluded and why.

### `designation_without_structure` / `no_printed_designation`

**First: is the token even a compound?** A CN table often cites `实施例 44` in a
column whose header still says `化合物编号` — the example space, not the compound
space. `query_activities` reports `reference_type`; if it says `example`, the
reading belongs to the compound that example *prepares* (`得到 33.75mg 化合物44`),
not to compound 44 of the same number. Read the example's own page before
concluding anything about binding.

**A caption naming several designations is not a gap.** `1-P2 or 1-P1 or 1-P3 or
1-P4` under four stereoisomer drawings, or `I-233-A、I-233-B、… 中的一个或两个`,
is a set the document declares interchangeable. MBForge reports it as
`designation_group_caption` and deliberately does not bind it
(`docs/known-limitations.md`). Do not hand-pick a member to "close" it.

Prove it, do not infer it. Locate every page the designation is printed on
(`search_evidence`), open those pages, and confirm no structure is drawn for
it. Then it is a document gap, not a pipeline gap: report it and move on. A
positive control, a comparator patent number, or a value with no compound
beside it is never linkable, and inventing a structure for it is the worst
outcome of this whole workflow.

## Evidence ladder

Strongest first. Stop at the first rung that settles it.

1. The document states the relation: `实施例29 … 得到55mg化合物29`, or a
   compound table row pairing a designation with a structure column.
2. A printed mass matching the structure (`mass_check: match`).
3. A printed caption/heading beside the drawing, read by the page text
   (`label_sources: page_text`) or visible in `page_image`.
4. Section locality: the drawing sits inside the section that prepares the
   compound.
5. Geometry alone (`crop` label, nearest drawing). Weakest; use it only when
   nothing above contradicts it.

## Tools and what they are for

| tool | use |
|---|---|
| `query_activities` | the scoreboard and the readings (`measurement_id`, reason) |
| `get_binding_candidates` | the packet: designations, candidates, nearby unlabeled drawings, review items |
| `verify_structures` | formula, exact mass, printed MS verdict, owning entry per drawing |
| `inspect_visual` | `page_text` (captions), `page_image` (look), `page_molecules` (re-read one page) |
| `search_evidence` | find where a designation is printed |
| `assign_attributions` | write a batch of accepted decisions |
| `promote_structure` | store one withheld drawing as a concrete molecule (with its reason) |
| `list_review_queue` | `review_required` items are the promotion worklist; `designation_unbound` items are decisions |
| `propose_review` | file a gap a human must settle (never a value the pipeline could have written) |
| `list_review_queue` | items already waiting; hand them over with `[[ui:review:<kind>:<item_id>]]` |

`assign_attributions` requires the capability token (a mutating call). It
validates every reading and every molecule before writing anything.

## When the counts move under you (measure before you fix)

Three extraction runs of one PDF have produced three different detection
geometries on CN121717757A. So:

- Never compare a scoreboard across a reingest without naming the run ids.
- `reingest_document` re-mints measurement ids: human/agent attributions do NOT
  survive it. Re-apply them, or fix the label path first and reingest once.
- A change that only touches labelling needs a re-extract (`reingest_document`),
  a change in the association/characterization rules needs only
  `submit_patent_analysis`. `submit_extraction` on an existing document fails
  closed with "source evidence batch is immutable".

## Verify a rule at the function level before touching the pipeline

Every "the pipeline loses my designation" report so far has been answered by
calling the rule directly on the text the page prints, in seconds, without a
re-run:

```python
from mbforge.service.pipeline.activity.parsing.tables import _parse_simple_activity_table
for r in _parse_simple_activity_table(md, 0, 94, default_target=""):
    print(r.reference_raw, r.reference_key, r.reference_type, r.value_canonical)
# or, for the example chain
from mbforge.service.pipeline.patent.rules.entries import extract_entries_from_body
from mbforge.service.pipeline.patent.rules.characterization import declared_product_labels
```

If the function returns the right thing, the defect is in the *plumbing* around it
(section kind, evidence scope, which stage owns the value) — and only then is a
re-run worth its ten minutes.

## Label geometry: where captions actually sit

The four bands that decide whether a printed number attaches to a drawing, in the
order the matcher tries them, all in top-down page coordinates:

1. **Head band** — `top ± 15% of the drawing's height`. A compound list prints the
   number above its drawing.
2. **Foot band** — `bottom − 12% … bottom + 16 pt`. A synthesis scheme prints the
   number under the drawing.
3. **Inside the box's lower half** — when the detector box grew over the caption
   (`1-256-A` sat 0.9 pt above the foot band). A print in the *upper* half is a
   substituent label and must not attach.
4. **Inside the columns but above the drawing** — a table row of captions. Without
   this only the outer two columns of a four-drawing row keep their numbers.

A print inside the drawing's columns is not automatically a foot caption. If a
row loses only its *inner* columns, this is the bug, not the OCR.

## Series spelling: `1-256-A` and `I-256-A` are one compound

The layout reads the series head `I` as the digit `1` often enough that a drawing
is captioned `1-256-A` while the activity table cites `I-256-A`. Both spellings
are legal keys and a candidate answers to all of them; a bare number or a
chemistry name gains nothing. When a designation "has no recognized structure",
check which spelling the drawing carries before believing it.

## Traps

- **The packet is paginated.** `designations` is paged; `readings` is the whole
  document. Follow `next_offset` before claiming a designation does not exist.
- **A stored structure is keyed by canonical SMILES.** `assign_attributions`
  `mol_id` is that SMILES, not a display name.
- **One molecule may be printed twice.** Two drawings of the same compound are
  not a conflict — compare formula/mass before calling the page ambiguous.
- **A Markush scaffold is not a compound.** `structure_kind: markush` (a SMILES
  with `*`) never owns a finished compound's reading.
- **The same number in two key spaces is not the same thing.** `实施例5` and
  `化合物5` are different identities unless the document says so; a link
  between them needs a printed product sentence or a shared drawing.
- **Do not re-run Extract to fix a binding.** Extract re-OCRs the document;
  binding decisions are written by `assign_attributions` and survive a re-run
  of Patent. Only re-ingest when a *label itself* was never read.
