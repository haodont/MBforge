# Evidence-scoped Patent harness — 2026-10-30

The initial v4/v4.1 results below are retained as history. The v4.2 continuation
supersedes the cell-ownership limitation and adds multi-document development
trials; v4.3 fixes logarithmic unit semantics and v4.4 narrows table tools. None
establishes held-out performance.

## Outcome and scope

The harness now delivers citable table/context packets, uses the exported answer
schema as the actual tool contract, checks literal row/value/metric support, and
keeps context citations from changing a measurement's merge anchor. It reuses
the existing Node Pi runtime and Python validation/publication path. No new
provider client, orchestration framework, dependency, OCR backend or default
enablement was added.

A real-provider trial on the **stored, unedited OCR** of US20250206734A1 p42
returned **22/22 expected non-ND cells and 3 assay methods**. Revalidation and
replay through the actual PatentStage committed **22 review measurement
candidates, 0 confirmed measurements and 0 structure links** in an isolated SQL
backup. This is one development table, not a held-out corpus benchmark or proof
that general scientific extraction is solved.

## Reproduced blockers and changes

| Blocker | Change and observable boundary |
| --- | --- |
| A numeric table headed by assay names could disappear before the LLM worklist | Designation + assay + numeric readings now create a complex-table gap; assay names never imply IC50 by themselves |
| Qualitative bins had document-wide, uncitable definitions appended to their excerpt | Select up to 6 same-document text passages within one page, ranked by proximity; each carries evidence ID, page, work/context role and truncation state |
| Context and table text competed for one truncated excerpt | Work and context each have a bounded packet budget, at most 4000 characters; the main excerpt remains the work chunk |
| Submit accepted an arbitrary object while a separate prompt renderer described its shape | Expand the exported Pydantic JSON Schema into the actual Pi tool parameters; remove the second prompt schema renderer; host binds run/document/gap identity |
| Valid evidence membership did not show that a reading occurred in a data row | Packet-backed table readings require a source_quote from cited work text containing the printed designation and expression; reject ND/NA/NT readings, inconsistent numeric values/operators and metrics absent from cited text |
| Adding a legend citation could move the merge slot | Prefer cited work evidence as the anchor; retain context citations as support |
| Example 1 could collapse into Compound 1 without a recognized structure | Normalize example keys to @example:N even when molecule_ref is empty, and preserve them in slots |
| SDK tool validation could fail without an explanatory progress message | Stream a bounded error with API key and task credential removed; the offline runtime test requires the rejected tool event itself to name the invalid field |

The quote check deliberately establishes **literal support**. It does not prove
that a value belongs to the claimed column, that an adjacent definition applies,
or that an assay/structure association is scientifically correct. Those remain
review/adoption boundaries. request_excerpt retains its one-follow-up limit and
adds returned text to the packet so it can be cited during repair. Its follow-up
text is context; a truncated work row cannot be recovered as new work by this
mechanism and needs a suitably sized work chunk.

## Frozen input and gold cells

- Document: US20250206734A1.pdf, page 42.
- Document ID: c24739ab9ce06de14404205495546289e621d24b8b996a32bbd3085afd0c5e34.
- Work evidence: 2c6b6b23f7f99f36bf5b28473a065785.
- Definition evidence: 0dd54e72aeb30e0ef4918e8073ecffdd, paragraph 0355,
  explicitly applying the bins to Table A and assays A/B/C.
- Input is the existing SQL OCR table, **not** a manually repaired header or OXR
  replacement. Nearby method/definition evidence was selected by build_gaps.

| Example | MRGPRX2 FLIPR | MRGPRX2 IP1 HTRF | MRGPRX2 β-Arrestin |
| --- | --- | --- | --- |
| 1 | +++ | ++ | ++ |
| 2 | +++ | ++ | ND |
| 3 | +++ | +++ | +++ |
| 4 | +++ | +++ | +++ |
| 5 | +++ | ++ | +++ |
| 6 | +++ | +++ | +++ |
| 7 | +++ | +++ | +++ |
| 8 | +++ | ND | +++ |

The audit compares the set of (printed row, assay column, bin) tuples, rejects
duplicates, requires exactly 22 items and skips the two ND cells. It checks all
example namespaces, source quotes, empty structure references, null point values
and resolvable assay references. The final output stores the **verbatim scale
on each assay method**, referenced by its readings. The audit requires this
scale to occur in the supplied definition and verifies strict lower / inclusive
upper endpoints: +++ is >0.1 and ≤100 nM; ++ is >100 and ≤1000 nM. An evaluator
self-check changes ≤ to < and must detect the changed boundary.

## Real-provider trials

All trials used LongCat-2.5-Preview through the production
SidecarPatentAnalysisRuntime → Node server/Pi → Python tool routes. Budget:
8 model turns, 60,000 reported tokens, 240 seconds total, 200 seconds per gap,
8192 maximum output tokens. No Python LLM client was used.

| Trial / local directory | Prompt | Result | Calls / usage |
| --- | --- | --- | --- |
| .tmp/harness-live-20261030 | patent-gap-v4, duplicated compact schema | Success; 22 cells, 3 methods | 2 turns, 2 tool calls, 34,183 tokens, 139.481 s |
| .tmp/harness-live-final-20261030 | patent-gap-v4.1, tool schema only | Provider reported Request timed out.; no answer | 1 turn, 0 tool calls, 10.918 s |
| .tmp/harness-live-retry-20261030 | patent-gap-v4.1, unchanged manual retry | Success; 22 cells, 3 methods | 2 turns, 2 tool calls, 34,288 tokens, 117.409 s |

Both successes rejected the first submission and accepted the second. The live
events did not retain the first rejection's detail; **its reason is unknown**.
The final telemetry path is covered by a local-provider test that submits an
invalid enum and repairs it. That test cannot establish what caused either
historical rejection. The timeout's underlying provider/network cause is also
unconfirmed; it was not counted as a successful extraction. These few runs do
not establish a failure rate or show that prompt simplification improved speed.

The final successful answer was revalidated with current submit_gap_answer and
replayed, without another provider call, through PatentStage.execute and the
committed SQL snapshot publisher. Audit result:

| Check | Result |
| --- | --- |
| Expected / matched non-ND cells | 22 / 22 |
| Assay methods | 3 |
| Duplicate cells / invented point values | 0 / 0 |
| Strict/inclusive bounds | Both observed bins verified |
| Persisted review measurement candidates | 22 |
| Confirmed measurements / structure links | 0 / 0 |
| Stage / document analysis status | success / partial |

The selected table gap succeeded; the replayed document remains partial because
other document gaps were not answered. Original library facts and settings were
not replaced. Ordinary application logging still used library/logs.

## Artifacts, failures and verification

Local, ignored artifacts (not committed; settings contain credentials):

- Each trial directory: inputs.json, events.json, result.json, sidecar.log and
  an isolated library backup. Do not publish settings.json.
- .tmp/harness-live-retry-20261030/audit.json and
  .tmp/harness-live-retry-audit-20261030.log: final cell/bounds/publication audit.
- .tmp/audit-harness-live-retry-20261030.py: bounded, sample-specific gold audit;
  no provider call. Earlier audit retained separately.
- .tmp/harness-backend-full-20261030.log and
  .tmp/harness-agent-final-20261030.log: verification logs.

Experiment wiring failures were corrected separately from product behavior:
the first successful run saved its answer before postprocessing failed because
DraftCoverage lacked required page lists; the first publisher audit omitted
PipelineContext.pdf_path. Neither was an LLM extraction failure. A read-only
noninteractive omp review timed out after 3 minutes without findings; independent
review is **not** claimed. Temporary callback/sidecar services were stopped.

Verification scope:

- Focused Python contracts, parsing, merge, tool routes, stage and publication:
  **49 passed** across test_patent_llm_merge.py, test_activity_parsing.py,
  test_patent_analysis_tools.py, test_patent_stage_llm.py,
  test_patent_analysis_contracts.py and test_patent_measurement_publication.py.
- Full backend after Python behavior changes: **441 passed, 1 failed** in
  136.05 s. Failure: test_udp_command_and_pose_parsing, Windows WinError193
  executing the unchanged non-Windows fixture; not repaired in this scope.
- Final tool-route rerun after typing/docstring cleanup: **7 passed**.
- Agent: TypeScript compilation and **7 tests passed**, including a stalled gap,
  an isolated next session, SDK enum rejection, repair, host identity and
  an error-bearing tool event.
- Ruff check/format on touched Python files and git diff --check passed.
- Frontend was not changed or tested in this task.

## Remaining acceptance work

LLM Patent analysis remains opt-in. Context uses adjacent-page heuristics and
bounded excerpts, not a general section/assay scope resolver. Literal quote
checks can still accept the wrong column or row substring. Bins remain raw
qualitative readings with their definition, not normalized point IC50 values.
Assay-method field semantics and definition applicability still need review.

Before broader enablement, freeze a separate multi-document gold set covering
numeric tables, grouped intervals, distant legends, repeated labels and multiple
assays; evaluate omissions, wrong cells and false structure links separately.
OCR repair remains useful where the source text is missing; this harness cannot
reconstruct missing pixels or establish a structure from a compound number alone.

## Continuation: v4.2 cell ownership and multiple documents (2026-10-30)

### Reproductions and fixes

The previous quote guard accepted a real whole-row quote
`| 化合物1 | 10 | 化合物2 | 20 |` while assigning `20` to `化合物1`.
An endpoint regression reproduced the acceptance before the fix.
Packet-backed pipe-table readings now require `source_column`, a strict,
nonnegative, zero-based value-column index counting label columns too.
The host requires one complete, uniquely matching source row, an exact value
cell, and its exact printed label in the nearest preceding designation column.
Whitespace is ignored. Wrong/missing columns, substring labels, sibling-pair
borrowing and blank-label ownership are rejected. Identical duplicate rows
are conservatively ambiguous. The column travels with the persisted candidate.
The schema remains readable for older snapshots; new submissions need grounding.

A real CN120943813A p95 trial also reproduced control loss: the model submitted
five readings, the host rejected `阳参化合物` as outside the row scope, and repair
silently removed it. Recognizing that exact observed printed label now lets the
deterministic parser keep all five readings without an LLM table call. The
endpoint is explicitly IC50, target MRGPRX2, unit nM; `<0.001` stays an inequality.
The control retains its raw designation, unresolved reference type, pending
status and no molecule link. This was verified at the public extraction boundary,
not by a separate five-reading SQL publication trial.

Under example headers, an unrecognized external publication and an unrelated
unknown label could both normalize to an empty key. Normalization now falls back
to the printed key: `WO2022067094` is retained without an invented example or
structure link; unrelated labels are rejected. Prompt `patent-gap-v4.2` and both
exported schemas include the column contract and printed-control instructions.

### Development trials on stored OCR

These use the production Python runtime, Node Pi sidecar and Python tool routes,
with copied SQL libraries and actual stored structure candidates. One existing
table work chunk per case was selected; original facts/settings were not
replaced. Page images were rendered and visually inspected. Expectations were
written after requests had started and one had completed, before inspecting
detailed answers; this is neither preregistered nor blind evaluation.

Budget per trial: 8 turns, 60,000 tokens, 240 seconds overall, 200 seconds per
gap and 8,192 output tokens. Provider model: LongCat-2.5-Preview.

| v4.2 case / source | Text-supported output | Turns / calls | Tokens | Seconds |
| --- | --- | --- | --- | --- |
| cn-missing / CN121270515A p20 | 6/6; examples 1–5 plus external WO designation | 1 / 1 | 8,719 | 42.222 |
| us-multi / US20250206734A1 p42 | 22/22 non-ND cells, 3 assay methods | 1 / 1 | 13,399 | 88.552 |
| us-noise / US20260027089A1 p60 | Unanswerable, 0 readings | 1 / 1 | 6,500 | 22.890 |
| us-partial / US20260027089A1 p63 | E020 pIC50 6.9 only | 3 / 3 | 23,302 | 49.076 |

The CN page image prints seven readings, but OCR dropped example 6's label;
the model correctly returns six without guessing 6 or duplicating 5. The US p60
image prints E001 6.4, E002 5.1 and E003 7.4, but the work OCR cannot pair those
labels and values. Refusal avoids assigning 6.4 to E003; it does not recover
the page. The p63 image has eight readings, while the selected chunk supports
only E020. Safe text extraction and page-level recall must be scored separately.
The three-assay output keeps all 22 cells distinct via inline endpoint names
even with empty assay-local keys; per-reading conditions preserve the bin bounds
`(0.1,100] nM` and `(100,1000] nM`, with no invented point values.

Earlier v4.1 trials in this continuation are retained in
`.tmp/harness-multidoc-20261030/`: cn-missing 6 readings (1 turn, 9,641 tokens,
48.578 s), cn-numeric 4 after control rejection (2 turns, 22,108 tokens,
72.061 s), us-noise 0 (1 turn, 6,816 tokens, 27.994 s), us-partial 1
(3 turns / 4 calls, 25,225 tokens, 59.835 s). These few runs do not support a
statistical performance or latency improvement claim.

### Publication and verification

Each final answer passed current `submit_gap_answer`, then replayed through
`PatentStage.execute` and the committed SQL snapshot publisher without another
provider call. All four isolated audits passed. Review-candidate counts were
6, 22, 0 and 1; source columns persisted correctly, with no new LLM structure
links. Answered selected chunks left document analysis partial; the refused
chunk left it fallback. CN also contained 12 other deterministic measurements,
so the new LLM candidate status must not be confused with total document facts.

- Focused parsing/routes/merge/stage/contracts/publication: **51 passed**;
  final route rerun after external-label assertions: **8 passed**.
- Full backend: **443 passed, 1 failed**, 97.14 s. The existing
  `test_udp_command_and_pose_parsing` failure is Windows WinError193 when
  executing the non-Windows fixture; it remains outside this change.
- Agent TypeScript compilation and full agent suite: **7 passed**.
- Ruff check/format passed on the six touched Python/test files. Frontend was
  neither changed nor tested by this task.
- Final `git diff --check` passed; no trial runner or sidecar remained running.
- Noninteractive read-only omp review again timed out without findings;
  independent review is not claimed.

Artifacts (local, ignored): `.tmp/run-harness-cell-20261030.py`,
`.tmp/audit-harness-cell-20261030.py`, each case's inputs/events/result/audit JSON
under `.tmp/harness-cell-20261030/`, and
`.tmp/harness-cell-{case}-audit.log`. Suite logs are
`.tmp/harness-cell-backend-full-20261030.log` and
`.tmp/harness-cell-agent-20261030.log`. Do not publish copied `settings.json`:
it contains credentials. Temporary trial processes have exited.

Wiring failures were distinguished from extraction failures: evidence-kind
bootstrap, test bbox, diagnostic dict access, audit invocation and required
budget fields were corrected before final verification. The first omp command
had an unquoted PowerShell file argument; the corrected command reached its
deadline without a review result.

### Remaining boundaries

The cell guard proves literal ownership, not semantic assay/target alignment,
unit/header consistency, completeness or molecular identity. Nearby context is
still candidate scope. A dimensionless pIC50 currently needs
`missing_fields=["unit"]` under the generic numeric draft validator; this caused
a repair turn and remains a contract issue. Damaged OCR still loses page data.
Separate held-out evaluation and review remain necessary before broader
enablement; LLM Patent analysis stays opt-in.

## Continuation: v4.3 dimensionless potency contract (2026-10-30)

The preceding pIC50 unit limitation is now fixed. Replaying the real p63 reading
`6.9` without `missing_fields=["unit"]` reproduced a contract rejection before
the change. `DraftValue` could not distinguish a missing concentration unit
from an inapplicable logarithmic unit because it did not know the metric.

Unit validation now belongs to `DraftMeasurement`. Logarithmic potency metrics
such as pIC50/pEC50/pKi/pKd keep the printed value and empty unit without a
missing-unit declaration. A physical unit on those metrics is rejected;
ordinary numeric measurements without units still must declare the absence.
Older drafts with a declared missing log unit remain readable. The existing
log-metric predicate moved into the domain layer so contracts and deterministic
normalization share it without an upward dependency. Both schemas were
regenerated, and the prompt revision is v4.3. There is no new representation
field, provider client, OCR backend or default enablement.

The existing contract test protects all three outcomes: accepted dimensionless
pIC50, rejected pIC50 with nM, and rejected undeclared missing concentration
unit. The existing method-only-answer reconstruction test now also verifies
that a recorded pIC50 survives reconstruction into a draft. Existing numeric
conversion and publication behavior are retained.

All four saved v4.2 responses remain readable under the new contract (6, 22, 0
and 1 readings). Their historical missing-unit annotations are preserved;
revalidation does not rewrite stored source provenance.

Verification: 40 focused Python tests passed before the method-only regression
assertions were extended. The subsequent full backend run, including those
assertions, had **443 passed, 1 failed** in 96.03 s: the same Windows
`test_udp_command_and_pose_parsing` fixture failure. Agent TypeScript compilation
and **7 tests passed**. Ruff and diff checks passed. A separate replay removed
the erroneous missing-unit flag from the saved p63 answer, then passed current
`submit_gap_answer` and actual isolated SQL publication: one review candidate,
source column 1, no new structure link. This replay made no provider call and
its retained v4.2 token/time metadata describes the old trial, not replay cost.

The fresh v4.3 provider trial did **not** succeed: after a structure lookup it
exhausted the 200-second gap budget (2 turns, 1 tool call, 12,424 reported tokens,
200.027 s, no submitted answer). No numeric speedup or end-to-end success is
inferred from the contract fix alone. Local artifacts:
`.tmp/harness-unit-20261030/us-partial/`,
`.tmp/harness-unit-replay-20261030/us-partial/`,
`.tmp/harness-unit-contract-replay-20261030.json`,
`.tmp/harness-unit-replay-audit-20261030.log` and
`.tmp/harness-unit-backend-full-20261030.log`. Copied settings remain private.

## Continuation: v4.4 table tool scope (2026-10-30)

Inspecting the timed-out trial showed that a bound table-reading session still
received `list_molecules`, although unresolved molecular identity does not
prevent recording a reading. The existing real-runtime test was extended and
first failed because the provider actually received that catalogue tool.

Bound table sessions now expose only `request_excerpt` and `submit_gap_answer`.
They use the supplied structure mapping when explicit and otherwise preserve
the printed designation with empty molecule_ref. Non-table association sessions
retain the existing bounded structure lookups. Python's deterministic attachment
of an unambiguous supplied candidate is unchanged. This can defer a catalogue-only
structure link to an association task or review; it does not prove such links
will be resolved automatically. The prompt states the table task boundary.

The agent compilation and all **7 tests passed** after the change, including
wire-level verification that table sessions receive neither `get_gap` nor
`list_molecules`, and that SDK rejection can be repaired before submission ends
the session. The generic tool surface remains covered by the existing test.

The v4.4 real-provider retest on the same stored p63 work chunk succeeded in
**1 turn / 1 submit call, 9,178 tokens, 59.675 seconds**. It returned exactly
E020 pIC50 6.9 with empty unit and no missing-unit annotation. Current tool
revalidation and isolated `PatentStage` SQL publication passed: one review
candidate, persisted source column 1, no structure link, document status partial.
The test covers one work chunk, not all eight readings in the page image.
This single run supports functional validity, not a latency or reliability
improvement claim; v4.2 had fewer seconds despite more repair turns.

Artifacts: `.tmp/harness-scope-20261030/us-partial/` (inputs/events/result/audit),
`.tmp/run-harness-scope-20261030.py`,
`.tmp/audit-harness-scope-20261030.py`,
`.tmp/harness-scope-us-partial-20261030.log`,
`.tmp/harness-scope-us-partial-audit-20261030.log` and
`.tmp/harness-scope-agent-20261030.log`. Copied settings contain credentials and
must not be published. Temporary trial services exited; final diff checks pass.

### Next work in order of expected value

1. **Account for omitted cells.** Derive a work-cell inventory from printed
   table geometry/text, then classify each cell as a proposed reading, a no-data
   marker, ambiguous ownership or unreadable. Count omissions explicitly;
   successful tool submission is not table completeness. Preserve unexplained
   omissions as partial work rather than forcing the model to invent owners.
   Track page image → OCR → work packet → model candidate → publication
   separately so packet selection/truncation is not misreported as OCR loss.
2. **Recover evidence selectively.** For missing labels/structure-heavy cells,
   compare the current local extraction with a frozen-crop OXR run on the
   existing server, preserving original evidence and separately recording the
   replacement candidate. Score printed label/value recovery and false pairs
   against the page image before changing defaults. Better text cannot itself
   validate molecular identity or assay association.
3. **Resolve assay scope with explicit evidence.** Exercise nearby versus
   distant legends, multiple assays on one page and negative neighbouring
   definitions. Require the header/definition/reading chain and score wrong
   assay associations separately from correct numeric values.
4. **Freeze a held-out evaluation by patent family.** Reuse the existing
   `tests/gold` protocol; keep the development cases above out of the held-out
   split. Record page-level recall, text-supported precision/recall, wrong
   assay/structure links, refusals, repair turns, tokens and elapsed time.

These are remaining tasks, not delivered features. Further prompt tuning is
useful only when the failure classification shows complete evidence that the
model still fails to extract. Existing human-review gates remain in place.
