# Patent analysis adoption rules

Fixed in P0 of [Patent analysis plan](../plan-patent-agent-harness.md); the
types live in `mbforge/contracts/patent.py`, the slot/signature rules in
`mbforge/domain/patent_analysis.py`. Implementation phases (P2/P3) must not
relax these rules.

## Sources and status

- Sources are `deterministic | llm | agreed | human`; statuses are
  `accepted | pending_review | rejected` — two separate axes.
- `accepted` means the adoption rules below were satisfied. It never means the
  measurement is experimentally proven.
- `analysis_status` (`disabled | succeeded | fallback`) and `extraction_mode`
  (`deterministic | hybrid`) describe the run; a merged result that includes
  deterministic facts is `hybrid`, never "pure LLM".

## Slots and signatures

- A **slot** is a stable position derived from source anchors only: document,
  anchor evidence, compound reference, assay, metric, conditions. Values are
  never part of a slot, so the same slot may hold incompatible readings.
- A **candidate signature** covers exactly the compared fields of one
  candidate; the **candidate-set signature** covers the whole (order-free) set.
- A conflict/review item ID is slot + candidate-set signature: an unchanged
  re-run reuses the item, a changed candidate set creates a new one.
- A human decision stores the candidate-set and evidence signatures it was made
  under. Both must still match for the decision to apply; a changed evidence
  set (re-extract) or candidate set retires it and it re-enters review. Stale
  decisions are retained, never silently applied or dropped.

## Alignment, duplicates and ambiguity

- Align by document → anchor → compound → assay → metric → conditions, then
  compare field values. `value` and LLM-rewritten titles are never match keys.
- The same compound under different assays, repeat measurements and multiple
  records on one page stay separate rows: they differ in assay key, anchor
  evidence or conditions.
- Identical parse results on both sides without supporting evidence still go to
  review — agreement is not proof.
- When a fact cannot be uniquely aligned, report the ambiguity; never collapse
  it into one row.

## Numbers, units, operators

- Preserve the printed expression (`raw_text`) and comparison operator. Never
  rewrite `< 100 nM` as an exact `100 nM`.
- A fixed-concentration inhibition reading stays an inhibition metric; never
  record it as an IC50.
- Units stay as printed in the draft; canonicalization reuses the existing
  normalization (`service/pipeline/activity/normalization.py`). No second
  chemistry normalization is implemented.
- Absent fields are declared in `missing_fields` (a numeric reading without a
  printed unit must declare `unit`) — absence is recorded, never guessed.

## Targets and species

- Target and system (species) are explicit fields. Human MRGPRX2 and mouse
  Mrgprb2 are different assays; they never merge into one comparison key.
- Assay conditions participate in the slot key, so different conditions yield
  different slots even for the same compound/metric.

## Source constraints

- Every fact cites `evidence_id`s and must cite only IDs of the document bound
  to the run; membership is validated server-side against the bound scope.
- Association suggestions reference existing detection candidates or confirmed
  molecules. The model never generates or edits SMILES in v1.
- The chain of header, row label and footnote evidence is preserved with the
  value; a value is never admitted on the strength of a citation alone.

## Conflicts and decisions

- Both candidates of a conflicting slot are preserved and **neither** enters
  downstream usable results until a human decides.
- Decisions are `choice=deterministic | llm | neither` — v1 has no free-text
  value edits and no bulk confirm without an explicit choice for patent items.
- `reopen` withdraws the decision and re-blocks the conflict slot.
- LLM-only facts may be adopted when they pass these rules; deterministic-only
  facts are kept, but are held back while a conflict questions them. Nothing
  auto-prefers an LLM value merely because it cites valid evidence.
- `model_confidence` is diagnostic only and is never an adoption gate.