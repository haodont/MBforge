# Activity ↔ molecule association

Why this document: activity data (活性数据) frequently ends up attached to no
molecule. This records *how* an activity gets associated with a molecule and
*every* code path that leaves it unassociated, with the real inputs the parsers
see and the outcomes the current code actually produces.

All observed results below were produced by running the real functions; the
harness is in [Reproduce](#reproduce).

## 1. The association chain

- `PatentStage` mints `ActivityMeasurement` dicts from SQL evidence
  (`service/pipeline/stages/patent_stage.py::_extract`), then calls
  `associate_facts(...)`.
- `associate_facts` (`service/pipeline/patent/association.py`) sets only
  `compound_entry_id`, `assay_method_id` and `linking_status`
  (`association.py:110-194`). It **never sets `mol_id`**.
- The molecule link is therefore **indirect**:
  `measurement → compound_entry_id → entry.entity_id (canonical SMILES) → molecules.activity`.
  The last hop is `_persist_activity_backed_molecules`
  (`patent_stage.py:227-288`) → `molecules.replace_document_candidates`.
- A measurement that never gets a molecule survives **only** in
  `storage/{doc_id}/patent_facts.json` (`measurements[]`), whose contract is
  "unlinked measurements are preserved here, never faked into the DB"
  (`service/pipeline/patent/artifact.py:46-49`). `domain/activity.py` states the
  same rule: *"``compound_entry_id`` and ``mol_id`` are both optional and
  unlinked measurements are never dropped."*

Two labels are in play:

- `compound_entry_id` — a document-local compound declaration (a "化合物N" entry).
  Entries are minted **only from section titles** (`extract_entries_from_title`,
  `patent_stage.py:117-156`, called at `422-432`), and only for a digit-led label
  (`_COMPOUND_TOKEN_RE`, `patent_stage.py:43-48`).
- `mol_id` — the molecule's canonical SMILES.

`linking_status` lives on the measurement and is `linked` / `failed` / `pending`
(`domain/activity.py`). Critically, it reflects only the **four measurement-scoped**
codes (see 3.7); entry→molecule failures never downgrade it.

## 2. Where an unassociated activity can end up

| Surface | Can hold an unassociated activity? | Evidence |
|---|---|---|
| `patent_facts.json` `measurements[]` | **Yes** — this is the only place today | `patent/artifact.py:46-49` |
| `molecules.activity` (SQLite) | No — needs a canonical-SMILES `mol_id` | `patent_stage.py:266-287` |
| `activities` table | **No** — `mol_id TEXT NOT NULL`, and nothing in `src/` inserts | `db/sqlite/schema.py:422-424` |
| `review_items` kind `activity_match` | Read by `db/activity_store.py`, but **no producer** | `activity_store.py:110-127` |
| `match_activities()` label/SMILES/page matcher | **No production caller** | `activity/matching.py:170`; only `tests/unit/pipeline/test_family_core.py` imports it |
| `ctx.activity_records` | Declared, never assigned | `run/context.py:71` |

Read side: `db/activity_store.py` + `service/use_cases/documents/activity_queries.py`
project both `activities` rows and `activity_match` review items, so the API can
*display* an unassociated row — nothing writes one. The `activities` table is
populated only by hand in tests (`tests/unit/routers/test_activity.py`).

## 3. The causes

### 3.1 The measurement is never minted (dropped at parse time)

`service/pipeline/activity/extraction.py` + `activity/parsing/tables.py`:

- A table row whose **first (label) cell is empty is skipped**
  (`tables.py:157-160`).
- A row **shorter than a metric column** silently drops that column
  (`tables.py:163`). No issue is emitted.
- A table whose header carries no activity signal is not an activity table
  (`_is_activity_table`, `tables.py:39-53`) → no records.
- A table with an **unparsable activity cell** is discarded whole with
  `complex_activity_table` (`extraction.py:487`, `:496`).
- An activity signal in an unsupported table layout → `unsupported_table_format`
  (`extraction.py:472`).
- A prose metric with no deterministically parsable value →
  `activity_value_unparsed` (`extraction.py:331`, `:349`, `:369`).

### 3.2 The measurement exists but has no resolvable compound reference

`association.py:119-131` emits `compound_reference_unresolved` when
`normalize_reference_label(...)` yields `key is None`, a non-`compound`
`reference_type`, or `ambiguous`. Sources, per `activity/normalization.py`:

- free text / no reference at all (`key=None`, `type="unresolved"`);
- `Example N` (`type="example"`);
- a bare E-series label (`type="e_series"`);
- an ambiguous letter label such as `A` (`type="letter_ambiguous"`).

### 3.3 The reference resolves to a compound key but no entry declares it

`association.py:132-140` emits `dangling_fact_reference`. Because entries come
only from titles, any compound number that appears in a table or prose but is
never declared in a section title lands here. **This is the headline "attached
to a number, no molecule" case.**

### 3.4 Several entries share the key and evidence cannot scope one

`association.py:141-160` emits `compound_entry_ambiguous` when the same 化合物N is
declared in more than one section and the measurement's evidence matches neither
section uniquely.

### 3.5 The entry exists but no molecule matches it — and this is silent

`association.py:215-264` resolves an entry to a candidate only when exactly one
unambiguous, non-rejected, non-Markush candidate with valid SQL evidence carries
the label. Failure modes and their codes:

| Condition | Code | Location |
|---|---|---|
| Multiple candidates (or a multi-label candidate) share the key | `molecule_candidate_ambiguous` | `:223-230` |
| Candidate is rejected or Markush | `molecule_candidate_rejected` | `:234-244` |
| Candidate has no valid SQL evidence id | `molecule_evidence_unresolved` | `:245-253` |
| Candidate has no verifiable label at all | `molecule_label_unresolved` | `:200-208` |
| **No candidate carries the label** | **no code — `continue`** | **`:220-222`** |

Two traps here:

- **No matching candidate emits nothing.** The entry simply keeps
  `entity_id = None` (and `structure_status = "missing"`, its
  `CompoundEntry` default — `domain/patent.py:88-89`, `:104-105`), so nothing in
  the output tells you an activity lost its molecule. Verified by case C3.
- `_candidate_label_keys` reads **only `candidate.properties`**
  (`ocr_labels_primary`/`ocr_labels`/`raw_coref_label`/`normalized_label`/`label`/
  `formula_label`, `association.py:41-69`) — **not `candidate.name`**. A candidate
  whose label exists only as `name` is invisible, even though the (dead)
  `matching.py:_candidate_label_values` *does* read `name`. Verified by C5 vs C6.

### 3.6 The molecule is found but the persist gate drops it

`_persist_activity_backed_molecules` (`patent_stage.py:227-288`):

- `_measurement_has_activity` requires a non-empty `compound_entry_id` and a
  reading (`:208-224`) — otherwise the measurement is skipped (`:243-247`).
- The entry's `entity_id` must be a **known candidate SMILES** (`:248-255`).
- `candidates_by_smiles` only holds candidates with a non-empty `canonical_smiles`
  (`:236-241`).
- `filter_persistable_candidates` (`persist/molecules.py:41-106`) then drops:
  `status == "rejected"`, `structure_role != "complete"`, no detections, a
  detection with `page is None`, or no `canonical_smiles`.
  Note `classify_structure_role` makes an invalid/empty SMILES
  `REVIEW_REQUIRED` (`detection/structure_role.py:284-288`), so **a molecule whose
  SMILES failed to parse can never be `complete` and its activity is orphaned.**
- Only the **first** measurement per molecule is persisted
  (`patent_stage.py:267-281`); further measurements for the same molecule stay in
  the artifact only.

### 3.7 A measurement can read `linked` with no molecule

`linking_status` is set from only four codes —
`compound_reference_unresolved`, `compound_entry_ambiguous`,
`dangling_fact_reference`, `assay_method_unresolved` (`association.py:183-194`).
The entry→molecule codes of 3.5 are attached with `related_fact_id = entry_id`,
not the measurement id, so they **never** downgrade the measurement. A measurement
with a good `compound_entry_id` but `entry.entity_id = None` still reports
`linked`/`failed` based on the assay method alone — never "no molecule".

## 4. The structural gap

There is currently **no SQL surface for an unassociated activity**:

- `activities.mol_id` is `TEXT NOT NULL` (`db/sqlite/schema.py:422-424`) and no
  `src/` code inserts into `activities`.
- `activity_match` review items have no producer.
- `match_activities()` (row label → full SMILES → low-confidence same-page
  fallback, with the family-core veto) is fully implemented and tested but has
  **no production caller**; `ctx.activity_records` is never populated.

So "activity with no molecule" is representable only in
`patent_facts.json`. The dead matcher and the `activities` table are the pieces
of an association path that was never wired to the Patent stage.

## 5. Observed cases (real input → real result)

Run through the real functions; see [Reproduce](#reproduce). Extraction cases
use one `SourceEvidence` block each.

| # | Input (verbatim) | Observed |
|---|---|---|
| A1 | `\| Compound \| IC50 (nM) \| EC50 (nM) \|\n\|---\|---\|---\|\n\| 1 \| 10 \| 20 \|\n\| 2 \| 5 \| 15 \|` | 4 measurements, 0 issues |
| A2 | `\| Compound \| IC50 (nM) \|\n\|---\|---\|\n\| 1 \| 10 \|\n\| 2 \| unreadable \|` | **0 measurements**, issue `complex_activity_table` — the whole table (including row 1) is discarded |
| A3 | `\| Compound \| Yield (%) \|\n\|---\|---\|\n\| 1a \| 82 \|` | 0 measurements, 0 issues (not an activity table) |
| A4 | `\| Compound \| IC50 (nM) \|\n\|---\|---\|\n\|  \| 10 \|\n\| 2 \| 5 \|` | 1 measurement (row 2 only); the empty-label row is silently skipped |
| A5 | `\| Compound \| IC50 (nM) \| EC50 (nM) \|\n\|---\|---\|---\|\n\| 1 \| 10 \|` | 1 measurement (IC50); the missing EC50 cell is silently dropped, no issue |
| A6 | `Compound 21 showed an IC50 of < 0.1 μM.` | 1 measurement, provenance `{reference_raw: "Compound 21", reference_key: "21", reference_type: "compound"}` |
| A7 | `The IC50 was determined to be 12 nM.` | 1 measurement with **`provenance = {}`** → 3.2 |
| A8 | `Example 5 showed an IC50 of 3 nM.` | `reference_type: "example"` → 3.2 |
| A9 | `Compound E001 showed an IC50 of 3 nM.` | `reference_type: "compound"`, `reference_key: "E001"` (explicit prefix wins) → 3.3 dangling, since no entry is ever minted for `E001` |
| A10 | `Compound A showed an IC50 of 3 nM.` | **`provenance = {}`** — the prose regex does not capture a single letter, so no reference at all |

Reference normalization (`normalize_reference_label`), real strings:

| Input | key | reference_type | ambiguous |
|---|---|---|---|
| `化合物20` | `20` | `compound` | False |
| `compound 20` | `20` | `compound` | False |
| `20A` | `20A` | `compound` | False |
| `Example 20` | `20` | `example` | False |
| `E001` | `E001` | `e_series` | False |
| `## Compound E001` | `E001` | `compound` | False |
| `A` | `A` | `letter_ambiguous` | True |
| `\| IC50` | `None` | `unresolved` | True |

Association cases (one measurement + entries + candidates; the harness supplies
no sections, so `assay_method_unresolved` appears in every row and alone drives
`linking_status`):

| # | Setup | `compound_entry_id` | entry `entity_id` | issues |
|---|---|---|---|---|
| C1 | reference `化合物20`, no entries | None | — | `dangling_fact_reference`, `assay_method_unresolved` |
| C2 | no reference in provenance | None | — | `compound_reference_unresolved`, `assay_method_unresolved` |
| C3 | entry `20` exists, **no candidates** | `en1` | **None** | only `assay_method_unresolved` — *the missing molecule is silent* |
| C4 | two entries share `20` | None | None | `compound_entry_ambiguous`, `assay_method_unresolved` |
| C5 | candidate with `name="20"` but empty `properties` | `en1` | **None** | only `assay_method_unresolved` — label in `name` is invisible |
| C6 | same candidate with `properties.ocr_labels=["20"]` + evidence | `en1` | **`CCO`** | only `assay_method_unresolved` — resolves |
| C7 | candidate Markush | `en1` | None | `molecule_candidate_rejected` |
| C8 | two candidates carry `20` | `en1` | None | `molecule_candidate_ambiguous` |

## Reproduce

```python
from mbforge.domain.evidence import SourceEvidence
from mbforge.domain.evidence_kind import register_kinds
from mbforge.service.pipeline.layout.labels import kind_vocab
from mbforge.service.pipeline.activity.extraction import (
    extract_activity_measurements_from_evidence,
)
from mbforge.service.pipeline.activity.normalization import normalize_reference_label
from mbforge.service.pipeline.patent.association import associate_facts

DOC = "case"
register_kinds(kind_vocab())  # the app registers producer labels at import time

def ev(raw: str, kind: str = "text") -> SourceEvidence:
    return SourceEvidence.create(
        doc_id=DOC, page=1, bbox=(10.0, 20.0, 100.0, 40.0), raw_text=raw, kind=kind
    )

# A2: the whole table is dropped when one cell is unreadable
ms, issues = extract_activity_measurements_from_evidence(
    [ev("| Compound | IC50 (nM) |\n|---|---|\n| 1 | 10 |\n| 2 | unreadable |", "tab")], DOC
)
assert ms == [] and [i["code"] for i in issues] == ["complex_activity_table"]

# C3: an entry with no candidate keeps entity_id=None and emits no issue
measurements = [{"measurement_id": "m1", "evidence_ids": ["e1"],
                 "provenance": {"reference_raw": "化合物20"}}]
# CompoundEntry.to_dict() always carries these two keys (domain/patent.py:104-105).
entries = [{"entry_id": "en1", "label_key": "20", "section_id": "s1",
            "entity_id": None, "structure_status": "missing"}]
issues = []
associate_facts(sections=[], entries=entries, assay_methods=[], measurements=measurements,
                candidates=[], valid_evidence_ids={"e1"}, issues=issues)
assert measurements[0]["compound_entry_id"] == "en1"
assert entries[0]["entity_id"] is None and entries[0]["structure_status"] == "missing"
assert [i["code"] for i in issues] == ["assay_method_unresolved"]

# A7 vs A6: prose without a compound reference has empty provenance
ms, _ = extract_activity_measurements_from_evidence(
    [ev("The IC50 was determined to be 12 nM.")], DOC
)
assert ms[0]["provenance"] == {}
```

## Existing tests

- `tests/unit/pipeline/test_activity_parsing.py` — A1/A2/A3, prose with a
  reference, table evidence sharing.
- `tests/unit/pipeline/test_activity_normalization.py` — reference types, label
  key sharing, log-scale conversions.
- `tests/unit/pipeline/test_patent_stage.py::test_patent_stage_entries_survive_without_structures`
  — the entry-without-molecule case (C3) from the persisted side.
- `tests/unit/pipeline/test_family_core.py` — exercises `match_activities` and the
  family-core veto, which have no production caller.
- `tests/unit/routers/test_activity.py`, `tests/unit/test_cascade_delete_activities.py`
  — seed `activities` rows and `activity_match` review items by hand.

## Related

- [Pipeline contract](pipeline.md)
- [Known gaps](../../TODO/INDEX.md)
