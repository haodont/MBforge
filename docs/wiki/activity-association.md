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
  (`association.py`). It **never sets `mol_id`**.
- The molecule link is therefore **indirect**:
  `measurement → compound_entry_id → entry.entity_id (canonical SMILES) → molecules.activity`.
  The last hop is `publish_document_facts` → `_derived_rows`
  (`service/use_cases/documents/patent_facts.py`), which maps the resolved
  reference to a candidate through **both** identity spaces (`mol_id` and
  canonical SMILES) and then updates `molecules.activity`.
- A reading whose designation no section declares is not left ownerless: the rule
  pass declares the printed designation itself (`association._declare_entry`, reusing
  the existing `CompoundEntry` with `review_status="pending"`), keyed in the space the
  print names — `化合物23` → `23`, `实施例23` → `@example:23`, the same derivation
  `apply_gap_links` uses. The entry pass then resolves its structure exactly as for a
  section-declared entry, and `molecule_label_unresolved` reports the designations no
  candidate carries.
- When a gap was handed to the model, the association it returns
  (`PatentGapLink`: `label_raw` + a recognized `mol_id`) is consumed by
  `apply_gap_links(entries, links, doc_id=…, sections=…, candidates=…, measurements=…)`
  before the artifact is built, and `associate_facts` runs a second time on the
  result. What that second pass derives is what gets published:
  - a designation an entry already prints is resolved in place (its evidence keeps
    both the printed row and the citation);
  - a designation **no** entry declares — the `dangling_fact_reference` case — is
    declared by the link itself: the entry is the existing `CompoundEntry`, with
    `review_status="pending"`, so a model-declared designation is visible as one;
  - the reference is stored in the persistence space, so a link that named a
    `mol_id` still matches the canonical SMILES the store writes;
  - a designation the rules already resolved is **not** overwritten by a
    suggestion;
  - the reading whose provenance cites the resolved designation carries it in
    `measurement.mol_id`, which is what makes it eligible for persistence even when
    no entry path exists;
  - a printed passage whose owner the rules could not read — a spectrum, a printed
    name, a preparation route — takes the designation from the link that cites its
    own evidence row, when exactly one such passage sits on that row and exactly one
    link claims it (`apply_gap_links(..., attributions=…)`). Anything else stays
    unattributed rather than being paired by guesswork.
- Where the model gets the candidates: a gap already carries the structures whose
  printed label its excerpt shows (`rule_context.structures`), and
  `list_molecules(label=…)` returns every recognized candidate that carries a
  designation — one call, compared in the same key space as the association, so
  ``化合物77``, ``77`` and ``实施例77`` all reach the structure labelled ``77`` while
  ``77A`` stays a different designation. The lookup is bounded to three calls per
  gap; the unlabelled catalogue stays paged. (Live evidence for this: the v3 run
  spent four lookups inside one gap on a catalogue it could not page, then died on
  its gap budget.)
- What one gap is worth: family reports (spectra, names, routes) and designation
  reports are grouped to the contract's own passage budget
  (`MAX_GAP_PASSAGES`), not one per row, because an answer may cite up to fifty
  links and a document prints hundreds of passages. A refused table is handed over
  `TABLE_ROWS_PER_GAP` rows at a time for the same reason.
- What a gap may be built on: a **printed** row (`text`/`table`), never a detection
  payload — a live run was handed a payload as its excerpt and correctly answered
  ``no_attribution``. An association issue about a designation cites the *candidates*
  it could not choose between, and those are payloads, so the rows are resolved
  through the **entry** the issue names: the passage the designation printed in is
  what travels, and `rule_context.designations` names the labels the gap settles.
  (Missing this silenced all 34 ambiguous designations of one document as
  ``no_text_location``.) Measured over the corpus: 646 family and 26+34 designation
  reports become **142 gaps carrying 251 designations**, where one row per gap
  produced 735 gaps.
- The relation reports (`RELATION_ISSUE_CODES`) are recomputed by that second pass
  rather than appended to: an association the model supplied removes the failure it
  answered instead of leaving a report the run has already disproved.
- A measurement that never gets a molecule survives **only** in
  `storage/{doc_id}/patent_facts.json` (`measurements[]`), whose contract is
  "unlinked measurements are preserved here, never faked into the DB"
  (`service/pipeline/patent/artifact.py:46-49`). `domain/activity.py` states the
  same rule: *"``compound_entry_id`` and ``mol_id`` are both optional and
  unlinked measurements are never dropped."*

Two labels are in play:

- `compound_entry_id` — a document-local compound declaration (a "化合物N" entry).
  An entry comes from the section title (`extract_entries_from_title`), from a
  designation the section **body** mentions (`extract_entries_from_body`, so a
  table or prose reference usually has an owner), from an example section's own
  identity, and — on the gap path — from the model's association when no section
  declares the designation at all (`association.apply_gap_links`, recorded with
  `review_status="pending"` so a declared designation is visible as one).
- `mol_id` — the structure the reading resolved to, in the identity the persistence
  reads (a candidate's canonical SMILES). The rules leave it empty; an accepted
  association is its only producer.

`linking_status` lives on the measurement and is `linked` / `failed` / `pending`
(`domain/activity.py`). It reflects only the **four measurement-scoped** codes (see
3.7), so it is not a molecule indicator: a reading whose compound is bound but whose
assay is unknown — or whose entry carries no structure at all — still reports
`linked`. Read `measurement.mol_id` and `entry.entity_id` for that question.

## 2. Where an unassociated activity can end up

| Surface | Can hold an unassociated activity? | Evidence |
|---|---|---|
| `patent_facts.json` `measurements[]` | **Yes** — this is the only place today | `patent/artifact.py:46-49` |
| `molecules.activity` (SQLite) | No — needs a canonical-SMILES `mol_id` | `patent_stage.py:266-287` |
| `measurements` (SQLite) | **Yes** — no structural requirement; a reading is stored whether or not a structure owns it | `db/sqlite/schema.py` measurements |
| `measurement_attribution` | Optional `reading -> structure` links, zero or more per reading | `db/measurement_store.py` |
| `ctx.activity_records` | Declared, never assigned | `run/context.py:71` |

Read side: `service/use_cases/documents/activity_queries.py` projects
`measurements` and their attributions, so the API displays an unassociated
reading directly. The retired `activities` table, `activity_match` review kind
and the unused `match_activities()` matcher no longer exist.

## 3. The causes

### 3.1 The measurement is never minted (dropped at parse time)

`service/pipeline/activity/table_scan.py` (one table evidence row) and
`activity/parsing/tables.py` (the table itself):

- A table row whose **first (label) cell is empty is skipped**
  (`tables.py` `_read_table_layout`).
- A row **shorter than a metric column** silently drops that column. No issue is
  emitted.
- A table whose header carries no activity signal is not an activity table
  (`_is_activity_table`).
- A table with an **unparsable activity cell** is discarded whole with
  `complex_activity_table`.
- An activity signal in an unsupported table layout → `unsupported_table_format`.
- A prose metric with no deterministically parsable value →
  `activity_value_unparsed`.
- A **page-split table** used to be dropped silently: the continuation prints no
  header, so it was neither read nor reported. It is now read under the previous
  page's header — adjacent page only, same column count, first cell a designation,
  no header band — and published with a `table_header_inherited` issue citing both
  evidence rows. A continuation-shaped row that cannot be read raises
  `complex_activity_table`; a table that prints its own header is never borrowed
  over.

### 3.2 The measurement exists but has no resolvable compound reference

`association.py:119-131` emits `compound_reference_unresolved` when
`normalize_reference_label(...)` yields `key is None`, a non-`compound`
`reference_type`, or `ambiguous`. Sources, per `activity/normalization.py`:

- free text / no reference at all (`key=None`, `type="unresolved"`);
- `Example N` (`type="example"`);
- a bare E-series label (`type="e_series"`);
- an ambiguous letter label such as `A` (`type="letter_ambiguous"`).

### 3.3 The reference resolves to a compound key but no entry declares it — closed

This used to be the headline "attached to a number, no molecule" case. It no longer
exists as a report: the rule pass declares the printed designation itself
(`_declare_entry`) in the space the print names, so the reading always has an owner —
review pending, because only the label vouches for it — and the entry pass resolves
its structure like any other. The `dangling_fact_reference` code was removed with its
last producer; what remains for the model is the *structure*, reported per
designation as `molecule_label_unresolved`.

### 3.4 Several entries share the key and evidence cannot scope one

`association.py` emits `compound_entry_ambiguous` when the same 化合物N is
declared in more than one section and the measurement's evidence matches neither
section uniquely.

### 3.5 The entry exists but no molecule matches it

`association.py` resolves an entry to a candidate only when exactly one
unambiguous, non-rejected, non-Markush candidate with valid SQL evidence carries
the label. Failure modes and their codes:

| Condition | Code | Reported as |
|---|---|---|
| Multiple candidates (or a multi-label candidate) share the key | `molecule_candidate_ambiguous` | gap (ambiguity, the model may settle it) |
| Candidate is rejected or Markush | `molecule_candidate_rejected` | issue |
| Candidate has no valid SQL evidence id | `molecule_evidence_unresolved` | issue |
| Candidate carries no verifiable label | `molecule_label_unresolved` | gap |
| **No candidate carries the designation** | `molecule_label_unresolved` (info) | gap |

The last row used to `continue` in silence: the entry kept `entity_id = None`
(and `structure_status = "missing"`, its `CompoundEntry` default), so nothing in
the output said an activity had lost its molecule. It is now reported — keyed by
the *entry*, `severity="info"` — which is what hands the designation to the model
instead of leaving it unowned. Measured over the corpus: 310 entries, 63 resolved,
so 247 designations are unresolved today (34 of one document's 66 entries are
`molecule_candidate_ambiguous`, 5 were the silent case).

`_candidate_label_keys` reads `candidate.properties`
(`ocr_labels_primary`/`ocr_labels`/`raw_coref_label`/`normalized_label`/`label`/
`formula_label`) **and `candidate.name`**. A designation stored only in `name` used
to be invisible to every rule; the normalizer still decides what counts as a
designation, so a printed chemistry name yields no key. (On the 13-document corpus
this rescue is currently 0 — the fix is a contract, not a measured recall gain.)

### 3.5b The designation is disputed, so no pair is published

`association.py` emits `molecule_candidate_ambiguous` when two candidates print the
same designation (or one candidate prints two), and the entry keeps no structure.
The declared-example join (`entries._declared_structure_activity`) used to publish
the pair anyway from `molecules.name`, which is whichever label read arrived first;
`structure_activity` then contradicted the reading's own attribution and reached the
export. The issue now carries its `label_key` and the join withholds the
designation, so a disputed label produces no pair anywhere.


### 3.6 The molecule is found but the persist gate drops it

`publish_document_facts` → `_derived_rows`
(`service/use_cases/documents/patent_facts.py`):

- `_measurement_has_activity` requires a reading and a named owner — the entry the
  reading cites **or** the structure it resolved to directly (`mol_id`).
- The resolved reference is mapped to a candidate through **both** identity spaces:
  the canonical SMILES the store writes and the `mol_id` a gap payload or a model
  link carries.
- `filter_persistable_candidates` (`persist/molecules.py:41-106`) then drops:
  `status == "rejected"`, `structure_role != "complete"`, no detections, a
  detection with `page is None`, or no `canonical_smiles`.
  Note `classify_structure_role` makes an invalid/empty SMILES
  `REVIEW_REQUIRED` (`detection/structure_role.py:284-288`), so **a molecule whose
  SMILES failed to parse can never be `complete` and its activity is orphaned.** A
  structure named by a link must therefore be a real parse, not a string that merely
  looks like one.
- Only the **first** measurement per molecule is persisted; further measurements for
  the same molecule stay in the artifact only.

### 3.7 A measurement can read `linked` with no molecule

`linking_status` is set from only four codes —
`compound_reference_unresolved`, `compound_entry_ambiguous`,
`dangling_fact_reference`, `assay_method_unresolved` (`association.py`).
The entry→molecule codes of 3.5 are attached with `related_fact_id = entry_id`,
not the measurement id, so they **never** downgrade the measurement. A measurement
with a good `compound_entry_id` but `entry.entity_id = None` still reports
`linked`/`failed` based on the assay method alone — never "no molecule".

These reports are recomputed on each association pass rather than accumulated
(`RELATION_ISSUE_CODES`), so the pass that runs after an accepted association
reports the relation it now finds: the failure the model answered disappears, while
every other producer's issues are untouched.

## 4. The structural gap

There is currently **no SQL surface for an unassociated activity**:

- `measurements` stores a printed reading with no structural requirement;
  `measurement_attribution` holds the optional `reading -> structure` links.
- The retired `activities` table and `activity_match` review kind are gone.
- The unused `match_activities()` matcher was removed; `ctx.activity_records` is
  never populated.

So "activity with no molecule" is representable only in
`patent_facts.json`. The dead matcher and the `activities` table are the pieces
of an association path that was never wired to the Patent stage.

What changed with the gap path is the other half: an activity whose structure **was**
identified — by the rules or by an accepted association — now reaches
`molecules.activity` even when no entry path exists, because the reading carries the
resolved structure on itself and both identity spaces resolve in `_derived_rows`.
Unresolved readings are still artifact-only.

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
| C3 | entry `20` exists, **no candidates** | `en1` | **None** | `assay_method_unresolved`, `molecule_label_unresolved` (info) — the missing molecule is reported, not silent |
| C4 | two entries share `20` | None | None | `compound_entry_ambiguous`, `assay_method_unresolved` |
| C5 | candidate with `name="20"` but empty `properties` | `en1` | **`CCO`** | `assay_method_unresolved` — the label in `name` resolves now |
| C6 | same candidate with `properties.ocr_labels=["20"]` + evidence | `en1` | **`CCO`** | `assay_method_unresolved` — resolves |
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

# C3: an entry with no candidate keeps entity_id=None and is reported, not silent
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
# ``molecule_label_unresolved`` is the report that hands the designation to the model.
assert [i["code"] for i in issues] == ["assay_method_unresolved", "molecule_label_unresolved"]

# A7 vs A6: prose without a compound reference has empty provenance
ms, _ = extract_activity_measurements_from_evidence(
    [ev("The IC50 was determined to be 12 nM.")], DOC
)
assert ms[0]["provenance"] == {}
```

## Measured over the corpus

`uv run python .tmp/e2e/activity_recall.py` (table/value recall, zero tokens) and
`.tmp/e2e/assoc_probe.py` (designations) cover all 13 documents of the isolated
corpus library. Current totals: **310 entries, 63 with a structure, 247 unresolved,
52 measurements, 47 with a declared owner, 16 with a resolved molecule**; 31 activity
tables, 6 of which parse (3 before this round). Every reading has an owner now — the
*structure* behind a designation is what the model is asked for. A full stage run on
one real document (scratch copy of the DB, analysis disabled) publishes **7
activity-backed molecules** with their real IC50 values, which is the persistence path
this page describes working end to end.

## Existing tests

- `tests/unit/pipeline/test_activity_parsing.py` — A1/A2/A3, prose with a
  reference, table evidence sharing.
- `tests/unit/pipeline/test_activity_normalization.py` — reference types, label
  key sharing, log-scale conversions.
- `tests/unit/pipeline/test_patent_stage.py::test_patent_stage_entries_survive_without_structures`
  — the entry-without-molecule case (C3) from the persisted side.
- `tests/unit/pipeline/test_patent_stage.py::test_an_association_resolves_the_designation_and_binds_its_reading`
  — the whole link contract: resolve in place, declare an undeclared designation,
  translate the identity, never overwrite a rule match, stamp the reading.
- `tests/unit/pipeline/test_patent_stage_llm.py::test_an_association_reaches_the_persisted_activity`
  — the same chain through the stage: gap → association → declared entry → bound
  reading → `molecules.activity`, with the answered failure gone.
- `tests/unit/routers/test_activity.py` — seeds `measurements` rows and their
  attributions by hand.

## Related

- [Pipeline contract](pipeline.md)
- [Known gaps](../../TODO/INDEX.md)
