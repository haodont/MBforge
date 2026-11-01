# Structure–activity export audit, 2026-10-30

The current deliverable is a usable document-selection export with original
readings and traceable structure associations. Automatic matching remains pending
scientific review. It does not establish source-wide recall or atom/stereochemistry
accuracy.

## Usage and contract

In the workspace, choose **导出结构与活性** from a document menu or select documents
and use the export toolbar action. Run Patent analysis first. The API is
`POST /api/v1/activities/export`, body
`{"doc_ids": ["<doc_id>"], "library_root": "<root>"}`. The root is optional.

The downloadable ZIP contains:

- `structure_activity.csv`: each recognized concrete structure with each linked
  measurement, including repeats and different assays, pending scientific review.
- `unresolved.csv`: every other committed reading, with explicit reasons for
  missing structures, conflicting references, incomplete/invalid citations,
  rejected entries/structures or changed catalog identity.
- `dataset.json`: exact values, document filename/SHA-256 identity, committed
  revision/evidence signature, complete facts snapshot, separate review candidates
  and conflicts, plus canonical SQL SourceEvidence rows (raw content, page, bbox).
- `README.txt`: field, coordinate, unit and spreadsheet conventions.

The service reads through the shared committed-snapshot use case, checks the
current evidence signature and revision, and checks them again before assembling
the ZIP. Unanalysed, stale or concurrently republished sources fail explicitly
with 409. Missing documents fail with 404. A failed document prevents the batch
download; the selection is never partially exported without notice. Exports use
all snapshot measurements, without the activity query's 1,000-row ceiling.

PDF pages are one-based. Bboxes use PDF points with bottom-left origin. Table,
data-row and source-column indexes are zero-based. The PDF itself is not included:
use the content-addressed doc_id to match the original PDF. Source evidence remains
SQL-owned; the ZIP is an export, not a new evidence store.

`metric`, `original_value`, `original_unit`, and `operator_original` retain the
source scale. `canonical_metric`, `canonical_value`, `canonical_unit`, and
`operator` describe the converted scale. For example, `1.5 μM` becomes `1500 nM`;
`pIC50 > 7` becomes `IC50 < 100 nM`. Unknown units stay unchanged; missing units
never acquire an invented concentration value. Qualitative grades retain their
raw symbol, rank and local scale. `missing_fields` explicitly lists absent assay,
species/system, target, conditions or unit information. Empty context is unknown,
not evidence that assays can be pooled.

CSV uses UTF-8 BOM. Formula-like text (including `=` and `+++`) receives an
apostrophe prefix for spreadsheets; JSON preserves exact strings. All exported
pair review states are conservatively pending. The catalog's structure review
state is separate. If an edit changes the catalog structure while the extraction
still describes the old one, the pair becomes unresolved: `canonical_smiles` is
blank, and `recognized_smiles` / `current_canonical_smiles` preserve both versions.

## Bugs corrected

The shared concentration normalizer multiplied μM values by 1,000 but retained
the μM unit, and mislabeled unknown units as nM. These are corrected at the shared
normalizer and publication boundary. Original comparators now survive domain
serialization, and older converted pIC50 comparators are interpreted on their
correct scale rather than inverted twice during merge/publication.

Independent review also reproduced two integrity failures and verified their
fixes: unitless `1` and `1000` no longer compare equal when both canonical values
are absent; and a human-corrected SQL structure cannot lend its confirmed status
to the old recognized SMILES. Exported mol_id now comes from the persisted row,
since hydrated extraction candidates can have an empty transient mol_id.

Two comments were corrected: normalization is shared by deterministic extraction
and LLM analysis (not LLM-only), and contradictory direct/entry references do not
form a valid attribution.

## Development corpus replay

Isolated SQLite backup: `.tmp/export-20261030/library/library.db`. The original
production/development facts and model settings were not republished. The public
Patent stage was run with LLM analysis disabled. The first stored-evidence replay
produced 41 readings / 14 matches / 27 unresolved. The follow-up refreshed only
two CN121270515A table regions from the original PDF using the current local
SLANet + RapidOCR producer at 144 DPI, then republished the isolated snapshots.
It is not a full fresh extraction of all 13 PDFs. Reproduction script:
`.tmp/export-20261030/run.py`; final ZIP: `.tmp/export-20261030/structure-activity.zip`;
row/citation audit: `.tmp/export-20261030/audit.json`.

| Document | Extracted readings | Matched pending review | Unresolved |
| --- | ---: | ---: | ---: |
| CN120329282A | 19 | 13 | 6 |
| CN120943813A | 5 | 3 | 2 |
| CN121270515A | 19 | 0 | 19 |
| WO2025223036A1 | 5 | 0 | 5 |
| Other nine development PDFs | 0 | 0 | 0 |
| Total | 48 | 16 | 32 |

Every committed reading is in exactly one output CSV. For all 16 matched rows,
the structure, reading, entry and any assay references resolve to evidence from
the same document. The 32 unresolved readings currently lack a resolved concrete
structure. Zero extracted rows does not mean that the PDF contains no activity.
All 13 source PDF SHA-256 hashes match their doc_ids, and all 16 matched rows
carry a non-empty persisted mol_id in the regenerated final ZIP.

Read-only PDF rendering compared the three original activity pages (CN120943813A
p95, CN120329282A p110/p113) and 13 unique matched structure panels, including the
two recovered structures. The follow-up also inspected CN121270515A p20/p21 and
its final-product crops. These checks do not establish atom/stereo accuracy for
the whole corpus. Some matched rows lack structured assay context; those fields
remain explicitly missing.

### Follow-up corrections and remaining blockers

- A concrete compound sharing a label with a generic fragment or a rejected
  crop was incorrectly classified as ambiguous. Association now considers only
  persistable concrete candidates. CN120329282A compound 1 (60.7 nM) and compound
  7 (39.26 nM) are recovered; genuinely conflicting concrete structures remain
  unresolved.
- A lost rowspan in the old CN121270515A p21 Markdown shifted targets by one
  column. The parser now refuses this malformed header. Fresh image inference
  restores all 12 readings with the correct MRGPRX1/2/3/4 columns; examples 1/2
  each read `+ / ++++ / + / +`. Fresh p20 inference restores seven readings,
  including the previously dropped example 6. Original SQL regions/IDs are
  preserved; before/after text, raw HTML, producer, crop/PDF hashes and readings
  are recorded in `.tmp/export-20261030/table-refresh.json`.
- Body mentions of starting materials suppressed example identities and could
  capture example-indexed measurements. Product identity now depends on title
  declarations, with an independent `@example:` identity otherwise. A body
  compound cannot replace it merely by appearing in the section.
- Independent image review found that both recognized CN121270515A example 1/2
  products have S,S stereochemistry while source drawings/titles specify R,S.
  Source-caption links and correction candidates are documented in
  `.tmp/cn121270515a-review/findings.json`; they remain review findings, without
  automatic structure replacement or eight newly claimed correct pairs. Matching
  molecular masses cannot detect these stereo errors.

Refresh script: `.tmp/export-20261030/refresh_tables.py`; the pre-refresh isolated
database is retained as `before-table-refresh.db`. To reproduce: refresh tables,
run `run.py`, then `check_recovery.py`. The last script audits the real ZIP for
48 readings retained once, all 13 PDF hashes, all cited IDs, persisted mol_ids,
correct selectivity targets/values and separate example identities. The original
libraries and settings are not changed.

## Validation and remaining work

The API regression exercises actual SQL evidence, publication, ZIP parsing,
multiple readings, stereochemistry, unit/log conversions, qualitative data,
conflicting references, invalid citations, catalog correction/rejection and
stale sources in one workflow. Existing normalization/merge tests protect the
shared scientific-value fixes. Frontend API tests check download bytes and that
a 409 response cannot produce a download.

Frontend: 112 tests passed; lint, TypeScript and production build passed. Backend
initial full run: 444 passed, one known Windows `WinError 193` in
`test_udp_command_and_pose_parsing` (a Unix-style test executable). Final targeted
checks passed; the final suite excluding that known platform fixture finished
with **444 passed, 1 deselected**. Logs are in the ignored experiment folder.
Ruff checks/format and `git diff --check` pass.
After the follow-up parser/association fixes, the focused three-file workflow
suite passed 35 tests, followed by another full backend run with **444 passed,
1 deselected** (the same Windows-only fixture; `backend-recovery.log`). Existing
workflow tests now cover a concrete label competing with generic/rejected crops,
an example product competing with a body reagent and lost-rowspan quarantine.
Frontend code was unchanged during this follow-up, so its earlier checks were
not repeated.
Independent follow-up review passed the parser and stage tests (29 tests),
confirmed malformed tables retain a citable `complex_activity_table` issue and
found no new blocking defect. Its stale activity-table detector docstring was
updated to describe gap eligibility rather than claiming ambiguity blocks LLM
requests.
No live browser click-through was performed. An authorized bounded omp read-only
review exceeded its 120-second deadline; the independent agent review supplied
the two reproducible findings above and verified their corrections.

Next useful work is a reviewed gold set of complete structure–reading–assay–source
tuples, then evidence-scoped recovery of the unresolved structure associations,
missing assay context and damaged table cells. Citation existence and matching
counts alone must not substitute for precision/recall or scientific validation.
