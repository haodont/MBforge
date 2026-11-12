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
| `propose_review` | file a gap a human must settle (never a value the pipeline could have written) |
| `list_review_queue` | items already waiting; hand them over with `[[ui:review:<kind>:<item_id>]]` |

`assign_attributions` requires the capability token (a mutating call). It
validates every reading and every molecule before writing anything.

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
