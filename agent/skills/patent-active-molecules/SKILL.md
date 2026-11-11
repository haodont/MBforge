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
2. Call `get_document` and check `has_patent_facts`.
   - If false and the session is read-only, stop and report that Patent facts
     must be produced first. Do not read around the missing facts.
   - If false and writes are allowed, call `submit_patent_analysis`, then poll
   `get_run` until the Patent stage settles. Report the run id.
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

## Read the page before you judge it

Every structural question about a patent is answered by looking, not by
reasoning from the numbers:

- `ocr_page_region` returns the page's text blocks **with their positions and
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

- If `query_activities` is not in the active tool list, say the capability is
  unavailable. Do not fall back to OCR, Markdown tables, or evidence search for
  *values*. Reading the printed table for the reference frame is not a fallback
  for values and stays allowed.
- If a field or identifier is absent from tool output, say it is unavailable.
  Never infer a number or SMILES from page text or pixels.
- Never present a pending or rejected reading as an accepted fact; show its
  status.
- Never claim completeness while `next_offset` is non-null.
