# Gold standard for patent relation pairs

- **Status:** Protocol accepted (2026-10-23); pilot annotation is the next
  action.
- **Related:** [ADR 0001](adr/0001-relation-pair-contract.md),
  [patent taxonomy](wiki/patent-taxonomy.md),
  [adoption rules](wiki/patent-adoption-rules.md).
- **Artifacts:** `tests/gold/schema.json`, `tests/gold/manifest.json`,
  `tests/gold/validate.py`.

## 1. What the gold set answers

The gold set answers one question:

> Of the relation pairs the pipeline publishes as facts, how many are right;
> of the pairs it covers, how many are wrong; and what did it refuse to answer?

It is not a molecule-count benchmark, not an OCR benchmark and not a document
classification benchmark. The unit is the relation pair from
[ADR 0001](adr/0001-relation-pair-contract.md):

```
(anchor, relation_type, subject, object?, evidence, status)
```

The gold set is **scanned-first**. The default page is an image with no text
layer. A native-text page is a control arm, not the main stratum. The page
image, not the OCR text, is the annotation source of truth.

## 2. Gold labels and scoring states

A gold record labels the document, not the system:

| Gold label | Meaning |
|---|---|
| `present` | The relation is printed and true. |
| `absent` | The page was exhaustively checked and no such relation exists. These are the negatives that make precision computable. |
| `insufficient_evidence` | The page is unreadable, clipped or genuinely ambiguous; no annotator can decide. |

The system produces one of three outcomes per gold `present` pair:

| System outcome | Meaning |
|---|---|
| `committed` | A pair with `commit_status='committed'`. |
| `abstained` | No committed pair; the system either emitted `abstained` or nothing. |
| `wrong` | A committed pair that does not match a gold `present` pair on an exhaustively annotated page. |

Scoring:

- **TP** — committed and matches a gold `present`.
- **FP** — committed and unmatched on an **exhaustively annotated** page.
- **FN** — gold `present` with no matching commit.
- **TN** — gold `absent` with no commit.
- **Correct abstention** — gold `insufficient_evidence` with no commit.
- **Unjudged** — committed and unmatched on a **targeted** page. Excluded from
  precision, counted in a separate "unjudged commits" line. This prevents the
  classic "unmatched = wrong" fallacy.

Each page carries `page_annotation: "exhaustive" | "targeted"`. Precision is
computed only on exhaustive pages. Targeted pages (for example, one Markush
genus) contribute to recall only.

## 3. Splits and leakage

The current 13-document corpus is a **development set**: its forms were read to
write the parsers, so it cannot also be the held-out proof. The gold set is split
by document, never by pair.

| Split | Rule |
|---|---|
| `development` | The 13 corpus documents. Rules and heuristics may be written against them. |
| `pilot` | 2 development documents, 30 pages, used to calibrate schema, time and adjudication. |
| `held-out` | At least 6 documents never inspected during rule development. Must include one granted `B`, one utility model, one EP, one Markush-heavy document and one machine-translated document. |

Held-out documents must be in different patent families from the development
documents. The manifest records `family`; where it is unknown, it must be
assigned before the split. A family that appears in both splits invalidates the
evaluation.

## 4. Stratification and sample size

The strata follow the dimensions that change the extraction path, not
jurisdiction alone. Targets are for gold v1; the pilot is a subset.

| Stratum | Docs | Pages | Pairs | Why it exists |
|---|---:|---:|---:|---|
| CN scanned, example + table | 4 | 24 | 300 | The dominant corpus form; example/table binding |
| US/WO scanned, examples + tables | 4 | 24 | 300 | Lettered assays, split headers, structure columns |
| WO/EP Markush | 3 | 18 | 200 | Genus + variable table; no enumeration |
| JP CJK + KR translated | 3 | 18 | 200 | Native text vs OCR, glyph damage, lost headings |
| Granted / utility / EP | 2 | 12 | 100 | Claims as granted; family comparison |
| Reaction scheme / salt / polymorph | 2 | 12 | 100 | Two-structure edges |
| Native-text control | 2 | 12 | 100 | Measures the OCR penalty |
| **Total** | **20** | **120** | **1,300** | Within the 800–1,500 pair budget |

The pilot is 2 documents × 15 pages, targeting 60–100 pairs. It exists to
measure annotation time and inter-annotator agreement before the full spend.

## 5. Page and pair sampling

Within a document, sample pages by role rather than uniformly:

1. Claims pages (first two).
2. Abstract / title page.
3. First example section.
4. An example that prints a structure.
5. An activity table.
6. A Markush / genus page.
7. A reaction-scheme page.
8. A visually degraded page, when the document has one.

Annotate every pair on a sampled page; do not sample pairs at random within a
page. Pair density varies by page, and random pair sampling hides table and
scheme failures.

Cap a document at 80 pairs for the pilot and 120 pairs for v1. If a page exceeds
the cap, mark it `targeted` and annotate the first N pairs in reading order.

## 6. Annotation protocol

### Materials

- Page render at 150–200 DPI.
- The `source_evidence` rows for the page, with `evidence_id` and bbox.
- Structure crops with their MolDet/MolParser output.
- A one-line natural-language rendering of the candidate pair.

A reviewer screen must show the page crop, the OCR anchor text, the structure
re-render and the sentence; missing one of the four turns a 30-second decision
into a minutes-long investigation.

### Procedure

1. Annotator A and Annotator B label independently.
2. Disagreements go to Annotator C for adjudication.
3. The page image is truth. OCR text is evidence, not truth.
4. OCR errors, broken line wraps and glyph substitutions are recorded on the
   anchor (`ocr_issue`), not silently corrected.
5. A label that prints no relation is recorded as `absent` on an exhaustive page.
6. A page that cannot be read is `insufficient_evidence`, never a guess.
7. Structure identity records its level:
   `exact_stereo | exact_isotopes | connectivity | parent_after_desalting | tautomer_collapsed`.
   Use `exact_isotopes` for deuterated or 13C-labelled compounds. Full standard
   InChIKeys distinguish isotopologues, but their connectivity block alone does
   not; this level explicitly compares RDKit canonical isomeric SMILES.
8. Record annotation time per pair. The budget is ~30 s/pair with pre-annotation
   and ~3 min/pair from scratch.

### Record shape

The normative shape is `tests/gold/schema.json`. A record carries:

- `doc` — `doc_id`, file name, jurisdiction, kind, language, rendering,
  chemistry patterns, table forms.
- `anchor` — kind, key space, verbatim label, normalized key, page, bbox,
  `evidence_id`, optional `ocr_issue`.
- `subject` — molecule (`smiles`, optional `inchikey`, identity level) or
  scaffold (`esmiles`, variable table).
- `object` — optional second molecule or scaffold.
- `relation_type`, `example_status`, `gold_status`, `verification`, evidence ids
  and `annotation` metadata.

## 7. Metrics

### Pair F1 (the primary metric)

A committed pair matches a gold `present` pair only when all three hold:

1. **Anchor** — same `evidence_id` and label key, or bbox IoU ≥ 0.5 with the
   same normalized label.
2. **Structure** — equivalent at the gold record's `identity_level`.
   RDKit is available in core: InChIKey is the default for non-isotopic
   structures; `exact_isotopes` compares canonical isomeric SMILES to keep isotope
   identity explicit, without relying on a truncated InChIKey connectivity block.
3. **Relation type** — exact enum match.

`pair_P`, `pair_R` and `pair_F1` are computed from this conjunctive match. A
system that gets the structure right but the anchor wrong is a false positive,
not a partial success.

### Component metrics

- `anchor_F1` — anchor match, ignoring structure and relation type.
- `structure_F1` — structure match, ignoring anchor and relation type.
- `relation_type_F1` — relation type given a correct anchor and structure.

These separate "entity wrong" from "anchor wrong" and stop a single blended
number from hiding the bottleneck.

### Coverage and risk

- `commit_coverage` — share of gold `present` pairs for which the system commits
  anything (right or wrong).
- `commit_precision` — correct commits / all commits on exhaustive pages.
- `risk = 1 - commit_precision`.
- `recall` — correct commits / gold `present`.

Report the **coverage–risk curve** as the verification gate is tightened. A
system that commits only the easy 20% is not comparable to one that commits 80%
at the same precision.

### Statistics

- Bootstrap by **document**, 10,000 resamples. Never resample pairs
  independently: pairs in one document share OCR, layout and language.
- If families are known, use a family-clustered bootstrap as the sensitivity
  check.
- Report per-stratum and macro/micro aggregates.
- Report Cohen's κ for relation type and structure equivalence between
  annotators.
- Calibrate `verification_status`: does `corroborated` actually predict a correct
  commit? Report AUROC and the pass/fail counts per corroboration source.

## 8. Acceptance gates

Hard gates (a failure blocks release regardless of F1):

1. **Evidence completeness** — 100% of committed pairs have complete geometry
   and at least one evidence id.
2. **No fabricated text** — every emitted anchor string is a substring of its
   cited evidence row or the exact OCR output of its crop.
3. **No contradicted commit** — no `verification_status='contradicted'` or
   `insufficient_evidence` pair is committed.
4. **No silent drop** — every uncommitted gold `present` has a system
   `abstain_reason` or a missing-pair report; no designation vanishes.
5. **Reproducibility** — a rerun produces identical `anchor_id` and `pair_id`
   values for unchanged inputs.
6. **Family separation** — no held-out family appears in development.

Quality targets (reported with confidence intervals, not asserted as facts):

- `commit_precision ≥ 0.95` on the Tier-1 scanned strata.
- `commit_precision ≥ 0.90` overall.
- `pair_F1` reported per stratum; no single aggregate without the table.
- `commit_coverage` reported; an abstention rate above 30% on a Tier-1 stratum
  is a product decision, not a hidden failure.

## 9. Versioning

- `manifest.json` carries `version`, `frozen_at`, `schema_version` and every
  document's metadata. The evaluator pins the manifest hash.
- Annotations are JSONL. A correction appends a new record with
  `annotation.version` and `supersedes`; the old record is never edited.
- A schema change increments `schema_version` and requires a re-validation of
  every record.
- Gold v1 is frozen before the first held-out run. Changes after that create v2.

## 10. Pilot and schedule

| Step | Work | Output |
|---|---|---|
| P0 | Freeze this protocol and the manifest | `tests/gold/manifest.json` |
| P1 | Annotate 2 documents × 15 pages | 60–100 pilot pairs |
| P2 | Adjudicate and measure κ / time per pair | Pilot report |
| P3 | Run the current deterministic pipeline and the current LLM path | Baseline coverage–risk |
| P4 | Fix the schema from pilot friction | Schema v1 |
| P5 | Annotate the remaining strata | 800–1,500 pairs |
| P6 | Freeze gold v1; run held-out | Release evidence |

The pilot is deliberately small. Its job is to find out whether the schema
survives real pages, not to produce a headline number.

## 11. Risks

- **Overfitting the development corpus.** The 13 documents already shaped the
  parsers. Held-out documents are mandatory; a number measured only on the
  development set is a sanity check, not a result.
- **Annotation cost.** 1,300 pairs at 30 s each is ~11 hours of focused work,
  plus adjudication. The pilot measures the real rate before the full spend.
- **OCR ambiguity.** A blurred label is not a negative; it is
  `insufficient_evidence`. Conflating the two inflates precision.
- **Structure identity.** Stereochemistry may be unreadable. Record the identity
  level; do not silently compare a connectivity-only gold to an exact-stereo
  prediction as if they were the same claim.
- **Family leakage.** A WO publication and its US/EP national phase are one
  invention. Without family assignment, the held-out split is not held out.
- **Metric gaming.** A system can raise precision by abstaining on everything.
  Coverage and risk are reported together, always.

## 12. Artifacts

| Path | Purpose |
|---|---|
| `tests/gold/schema.json` | Normative JSON Schema for one gold record |
| `tests/gold/manifest.json` | Development corpus metadata and strata |
| `tests/gold/validate.py` | Structural and semantic validator; `--self-test` |
| `tests/gold/annotations/*.jsonl` | Annotations, one record per line (created during P1) |
| `tests/gold/README.md` | How to validate and what is frozen |

The PDFs stay outside the repository. A record identifies its document by
`doc_id` (the SHA-256 of the file bytes), never by a committed PDF.
