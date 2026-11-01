# ADR 0001: Relation-pair contract for patent chemistry

- **Status:** Accepted (2026-10-23). Schema specified; implementation pending.
- **Scope:** Extract → Patent storage, the Patent facts projection, and every
  consumer of patent chemistry facts (SAR, research tools, review).
- **Related:** [patent taxonomy](../wiki/patent-taxonomy.md),
  [gold standard](../plan-gold-standard.md),
  [adoption rules](../wiki/patent-adoption-rules.md),
  [extraction forms](../wiki/patent-extraction-forms.md).
- **Supersedes:** none.

## Context

The active pipeline is `Extract → Markdown → Patent`. Extract mints the canonical
`source_evidence` rows; Patent publishes `patent_facts.json` from them. The
evidence row is the only location authority:

```
source_evidence(evidence_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                raw_text, kind)
```

`bbox_*` are PDF points with a bottom-left origin, independent of the render DPI
(`service/pipeline/layout/regions.py::px_box_to_pdf`). The crop pipeline converts
MolDet's normalized boxes into the same space.

Since 2026-10-23 the row also carries `reading_order` (zero-based inside the
page). The producer writes the column-aware order, and `list_source_evidence`
orders by it; legacy rows keep the default `0` and fall back to the geometric
order until the document is re-extracted.

**The default input is a scanned PDF.** In the 13-document corpus, 11 documents
have no text layer at all, one is native (`JP2023544789A`, 400 pages) and one is
hybrid (`US20210128561A1`, 64 native / 3 scanned pages). Every text block and
structure on a scanned page comes from the render → layout → OCR / MolDet →
MolParser path. A native text layer is a cost optimization, never the contract.

The measured bottleneck is association, not recognition. On the 13-document
corpus, 63 of 314 entries (20%) carry a structure and 343 of 2,605 structures
(13%) carry any designation. `associate_facts` rebuilds its index in memory from
candidate `properties` on every run: it is not persisted, not queryable and not
auditable. `_candidate_label_keys` emits only `LabelKind.COMPOUND`, so an
`@example:N` entry can never match a candidate on the deterministic path; the
example → structure jump is structural, not statistical.

Three forks are unresolved in the current write path:

1. `CompoundEntry.entity_id` stores a canonical SMILES string, while
   `PatentGapLink.mol_id` and `measurement_attribution.mol_id` store `mol_id`.
   The same relation carries two identity types.
2. `structure_status="resolved"` is written after a candidate match. It means
   "a string was obtained", not "the structure is right"; the entry loop does
   not even guard an empty SMILES.
3. A Markush candidate raises `molecule_candidate_rejected` and is dropped. The
   genus and its variable table have no relation to land in, so the densest part
   of the patent becomes noise.

A fourth constraint is scheduling: the live model takes ~86 s per turn and a gap
takes ~3 turns, while a document has hundreds of designations. The model cannot
be the index. It can only answer a bounded question about an index that already
exists.

## Decision

1. **The canonical unit is a relation pair**, not a molecule and not a fact row.
   A pair is `(anchor, relation_type, subject, object?, evidence, status)`.
2. **Anchors are printed facts.** `label_anchor` records the label exactly as
   printed, its key space, its geometry and the evidence row it came from. It
   does not store a structure. Resolution lives in `relation_pair`.
3. **Structures are referenced by `mol_id` only.** A pair never stores SMILES.
   The gold set stores chemical truth separately; the runtime stores local ids.
4. **The evidence store is unchanged.** `source_evidence` remains the only
   location authority. Pairs cite evidence ids; they never duplicate raw text as
   truth.
5. **The default producer is the scanned path.** Native text, XML, TIFF and DOCX
   are producers that must emit `source_evidence` rows; they do not change the
   pair contract.
6. **Status is three independent axes.** `recognition_status` (was a structure
   read?), `verification_status` (was it checked?) and `commit_status` (may it be
   published?). `example_status` (`exemplified` / `prophetic`) is a qualifier,
   not an edge.
7. **Relation types are a closed enum** (below). An unknown relation is
   `abstained`, not a new type.
8. **Markush is a relation, never an enumeration.** `member_of_genus` and
   `claim_scope` are first-class pairs; enumerated structures are derived rows
   with `derived=true`, never facts.
9. **Corrections append.** A corrected pair is a new row whose `superseded_by`
   points at the old one; the old row is never updated or deleted.

## Schema

The canonical schema lives in `src/mbforge/db/sqlite/schema.py`. This ADR adds
three tables. The local SQLite library is disposable development data, so the
canonical schema is updated directly; no migration is written.

### `page_geometry` — scanned-page metadata

Geometry checks and review crops need the page size and the render DPI, which
`source_evidence` does not carry today.

```sql
CREATE TABLE IF NOT EXISTS page_geometry (
    doc_id        TEXT NOT NULL,
    page          INTEGER NOT NULL CHECK (page >= 1),
    width_pt      REAL NOT NULL CHECK (width_pt > 0),
    height_pt     REAL NOT NULL CHECK (height_pt > 0),
    render_dpi    REAL NOT NULL CHECK (render_dpi > 0),
    quality_class TEXT NOT NULL DEFAULT 'clean',
    skew_deg      REAL,
    ink_density   REAL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (doc_id, page),
    CHECK (quality_class IN ('clean', 'degraded', 'unreadable'))
);
```

`quality_class` is the producer's verdict on the rendered page, not on a fact.
`unreadable` pages still carry evidence rows; they simply cannot produce a
committed pair.

### `label_anchor` — one printed designation slot

```sql
CREATE TABLE IF NOT EXISTS label_anchor (
    anchor_id   TEXT PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    page        INTEGER NOT NULL CHECK (page >= 1),
    bbox_x0     REAL NOT NULL,
    bbox_y0     REAL NOT NULL,
    bbox_x1     REAL NOT NULL,
    bbox_y1     REAL NOT NULL,
    label_raw   TEXT NOT NULL,
    label_key   TEXT NOT NULL,
    key_space   TEXT NOT NULL,
    anchor_kind TEXT NOT NULL,
    source      TEXT NOT NULL,
    occurrence  INTEGER NOT NULL DEFAULT 0,
    confidence  REAL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (bbox_x0 >= 0 AND bbox_y0 >= 0 AND bbox_x0 <= bbox_x1 AND bbox_y0 <= bbox_y1),
    CHECK (key_space IN (
        'example', 'compound', 'claim', 'internal_code',
        'table_row', 'scheme_node', 'none'
    )),
    CHECK (anchor_kind IN (
        'section_heading', 'table_row_label', 'table_cell', 'caption',
        'prose', 'scheme_node', 'claim_text', 'title', 'abstract'
    )),
    CHECK (source IN (
        'text_layer', 'ocr_text', 'ocr_label', 'table_cell',
        'caption', 'heading', 'human', 'imported'
    ))
);
CREATE INDEX IF NOT EXISTS idx_la_doc_key
    ON label_anchor(doc_id, label_key);
CREATE INDEX IF NOT EXISTS idx_la_evidence
    ON label_anchor(evidence_id);
CREATE INDEX IF NOT EXISTS idx_la_doc_page
    ON label_anchor(doc_id, page);
```

`anchor_id = stable_id("anchor", doc_id, evidence_id, label_key, occurrence)`.
`occurrence` disambiguates a repeated label inside the same evidence row (for
example two `实施例1` prints in one table). `label_raw` is verbatim: for a text
source it must be a substring of the cited row's `raw_text`; for an OCR label it
is the OCR output, never a normalized rewrite.

`label_anchor` deliberately has **no `mol_id`**. The anchor is the fact; the
resolution is an assertion about it. A view of `relation_pair` answers
"which structures carry this designation".

### `relation_pair` — one document-local assertion

```sql
CREATE TABLE IF NOT EXISTS relation_pair (
    pair_id       TEXT PRIMARY KEY,
    doc_id        TEXT NOT NULL,
    anchor_id     TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    subject_slot  TEXT NOT NULL DEFAULT 'primary',
    subject_mol_id TEXT,
    object_slot   TEXT,
    object_mol_id TEXT,
    object_scaffold_id TEXT,
    recognition_status  TEXT NOT NULL,
    verification_status TEXT NOT NULL,
    commit_status       TEXT NOT NULL,
    example_status      TEXT,
    corroboration TEXT NOT NULL DEFAULT '[]',
    evidence_ids  TEXT NOT NULL DEFAULT '[]',
    geometry_complete INTEGER NOT NULL DEFAULT 0,
    abstain_reason TEXT,
    source        TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    superseded_by TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (relation_type IN (
        'exemplified_by', 'designated_as', 'reported_as',
        'member_of_genus', 'claim_scope', 'prepared_from',
        'salt_of', 'solvate_of', 'stereoisomer_of', 'tautomer_of',
        'formulated_as'
    )),
    CHECK (recognition_status IN (
        'missing', 'detected', 'parsed', 'ambiguous', 'rejected'
    )),
    CHECK (verification_status IN (
        'insufficient_evidence', 'uncorroborated', 'corroborated', 'contradicted'
    )),
    CHECK (commit_status IN ('committed', 'abstained', 'review_pending')),
    CHECK (example_status IS NULL OR example_status IN (
        'exemplified', 'prophetic', 'unknown'
    )),
    CHECK (geometry_complete IN (0, 1)),
    CHECK (source IN ('rule', 'llm', 'human', 'imported')),
    CHECK (abstain_reason IS NULL OR abstain_reason IN (
        'anchor_ambiguous', 'structure_ambiguous', 'structure_missing',
        'geometry_incomplete', 'markush_excluded', 'verification_contradicted',
        'table_incomplete', 'out_of_scope', 'no_relation'
    )),
    CHECK (superseded_by IS NULL OR superseded_by <> pair_id),
    CHECK (commit_status <> 'committed'
           OR subject_mol_id IS NOT NULL
           OR object_mol_id IS NOT NULL
           OR object_scaffold_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_rp_doc_anchor
    ON relation_pair(doc_id, anchor_id);
CREATE INDEX IF NOT EXISTS idx_rp_doc_commit
    ON relation_pair(doc_id, commit_status);
CREATE INDEX IF NOT EXISTS idx_rp_subject
    ON relation_pair(subject_mol_id);
CREATE INDEX IF NOT EXISTS idx_rp_object
    ON relation_pair(object_mol_id);
CREATE INDEX IF NOT EXISTS idx_rp_scaffold
    ON relation_pair(object_scaffold_id);
```

`pair_id = stable_id("pair", doc_id, anchor_id, relation_type, subject_slot,
object_slot)`. The structure id is deliberately **not** part of the key, so a
structure correction appends a new row instead of silently changing identity.

### Relation types and direction

| `relation_type` | subject | object | Meaning |
|---|---|---|---|
| `exemplified_by` | molecule | — | The anchor's example prepares or claims this compound. `example_status=prophetic` means "may be prepared", not a fact. |
| `designated_as` | molecule | — | The printed label names this compound. Weak relation; a label is not a synonym for a structure. |
| `reported_as` | molecule | — | The anchor's printed reading (measurement) belongs to this compound. The reading itself stays in `measurements`. |
| `member_of_genus` | molecule | scaffold | The compound falls under the Markush genus. |
| `claim_scope` | — | scaffold | The claim asserts the genus. |
| `prepared_from` | product | reactant/intermediate | The product is prepared from the reactant. |
| `salt_of` | salt | parent | Salt/free-base relation. |
| `solvate_of` | solvate | parent | Solvate relation. |
| `stereoisomer_of` | stereoisomer | parent | Explicit stereoisomer edge, not a fold. |
| `tautomer_of` | tautomer | parent | Explicit tautomer edge, not a fold. |
| `formulated_as` | molecule | — | The compound appears in a printed formulation. |

The anchor asserts the relation; the direction is always anchor → subject /
object as tabled. No relation may be inferred from a label alone.

## Invariants

These are enforced in code and in `tests/gold/validate.py`; SQLite `CHECK`s
cover the closed vocabularies, not the cross-row rules.

1. **P1 — Scope.** `relation_pair.doc_id` equals the anchor's `doc_id`, and
   every `evidence_id` belongs to that document.
2. **P2 — Geometry.** Anchor and structure boxes lie inside
   `page_geometry.width_pt/height_pt` (1 pt tolerance). A box that crosses the
   page edge is clipped evidence, not a fact.
3. **P3 — Completeness.** `geometry_complete=1` only when the anchor row, the
   structure evidence row and the page geometry all exist, the label is inside or
   adjacent to the structure crop under the layout rule, and no side of the crop
   is cut by the page boundary.
4. **P4 — Recognition.** `recognition_status='parsed'` requires a non-null
   `subject_mol_id` or `object_mol_id`/`object_scaffold_id` that exists in
   `molecules` / `markush_scaffolds`. `missing` and `rejected` carry none.
5. **P5 — Verification.** `corroborated` requires at least one
   `{source, result: "pass"}` entry; `contradicted` requires at least one
   `{result: "fail"}`. `insufficient_evidence` means no check could run.
6. **P6 — Commit.** `committed` requires `geometry_complete=1`,
   `verification_status != 'contradicted'`, at least one structure reference and
   no `abstain_reason`.
7. **P7 — Abstention is explicit.** `abstained` requires `abstain_reason`.
   Dropping a candidate without a row is forbidden.
8. **P8 — Model gate.** `source='llm'` starts `review_pending` and may commit
   only after `human_confirm` or at least one independent `pass`. The model never
   writes SMILES, `relation_type`, or `verification_status`.
9. **P9 — Closed vocabulary.** An unknown relation type is `abstained`
   (`out_of_scope`), never a new enum value.
10. **P10 — Append-only.** `superseded_by` points at another pair in the same
    document; no cycles; the superseded row is never mutated or deleted.

### Commit policy

| `source` | May commit without corroboration? | Condition |
|---|---|---|
| `rule` | Yes, `uncorroborated` | Exact, unambiguous label match; `geometry_complete=1`; one candidate only. |
| `llm` | No | Must be `human_confirm` or have an independent `pass`; otherwise `review_pending`. |
| `human` | Yes | `verification_status != 'contradicted'`; an audit row records the decision. |
| `imported` | Yes | The import declares its provenance and geometry; otherwise `review_pending`. |

Consumers read only `commit_status='committed'`. `review_pending` is visible in
the review center and excluded from facts, SAR and research answers.

## Mapping to existing code

| Current field / path | Contract field |
|---|---|
| `CompoundEntry.label_raw` / `label_key` | `label_anchor.label_raw` / `label_key` |
| `CompoundEntry.section_id` | anchor `anchor_kind='section_heading'` |
| `CompoundEntry.structure_status='resolved'` | `recognition_status='parsed'` + a separate `verification_status` |
| `CompoundEntry.linking_status='linked'` | `commit_status='committed'` only after the policy above |
| `CompoundEntry.entity_id` (canonical SMILES) | `relation_pair.subject_mol_id`; `entity_id` remains a deprecated projection |
| `PatentGapLink` (`label_raw`, `mol_id`, `evidence_ids`) | a `relation_pair` proposal with `source='llm'`, `commit_status='review_pending'` |
| `measurement_attribution` | a `reported_as` pair projection; pairs are canonical |
| `molecule_relations` | generic molecule↔molecule edges; not document-anchored; unchanged |
| `molecule_candidate_rejected` (Markush) | `member_of_genus` / `claim_scope` pair plus a review item; the issue is not the whole answer |
| `_queue_review_items` | unchanged: it already preserves a human decision on an unchanged item id |

## Consequences

- `associate_facts` becomes an index lookup: read `label_anchor` + candidates,
  write pairs. It no longer flattens every candidate's `properties` per run.
- `apply_gap_links` writes proposals instead of mutating `entity_id`; an LLM
  answer is no longer a fact by construction.
- `patent_facts.json` derives `CompoundEntry` and measurement attribution from
  committed pairs. Both remain projections, not authorities.
- Anchor coverage becomes a first-class metric: how many printed designations
  have an anchor, how many anchors have a structure, how many pairs are
  committed/abstained. The 20% is measured, not inferred.
- The MS mass rule upgrades from an issue to a verification source
  (`ms_mass`), with a pass/fail result on the pair.
- Markush stops being noise: a genus is a pair, and its variable table is stored
  beside it. Enumeration remains derived.
- The scanned-first geometry (`page_geometry`) lets review crops re-render at
  150–200 DPI without guessing the original scale.

## Non-goals

- No external format proposal, public benchmark or industry standard. This is an
  internal contract and an internal gold set.
- No new OCSR or VLM model. The contract is about where facts land, not which
  recognizer wins.
- No cross-document entity resolution in the document-local pass. Family-level
  identity is a later, separately evaluated layer.
- No model-written SMILES, no model-chosen relation type, no model-written
  verification verdict.
- No Markush enumeration as fact.
- No replacement of `source_evidence`.
- No XML/TIFF/DOCX producer in v1. The contract admits them, but none is
  scheduled.

## Implementation order

1. Add `page_geometry`, `label_anchor`, `relation_pair` to the canonical schema.
2. Extract writes `label_anchor` rows from section headings, table headers and
   row labels, captions and OCR labels; report coverage by document and source.
3. `associate_facts` switches to anchor lookup and writes
   `designated_as` / `exemplified_by` / `reported_as` pairs; `CompoundEntry`
   becomes a projection.
4. `apply_gap_links` writes `source='llm'`, `review_pending` proposals; consumers
   exclude them until accepted.
5. Add verification sources (`ms_mass`, `label_sequence`, `geometry_complete`)
   and backfill `verification_status`.
6. Markush: write `member_of_genus` and `claim_scope`; keep enumeration derived.
7. Freeze gold v1 against the new tables; measure pair F1 and the
   coverage–risk curve.

## Acceptance for the ADR

- A pair can be reconstructed from SQL alone: anchor + evidence + molecule +
  status.
- No new consumer reads `CompoundEntry.entity_id`.
- A rerun produces identical `anchor_id` and `pair_id` values.
- Every committed pair has complete geometry and either a named verification
  result or the explicit `rule` / `uncorroborated` exception.
- Every abstained label has a reason; no designation disappears silently.
