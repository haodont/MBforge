"""Canonical SQLite DDL for the unified library database.

Pure constants only — connection handling, idempotent column backfills, and
other runtime logic live in :mod:`mbforge.db.sqlite.database`.
"""

_KB_SCHEMA = """
-- Ingest queue and logs
CREATE TABLE IF NOT EXISTS ingest_queue (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    doc_id TEXT,
    status TEXT DEFAULT 'pending',
    claimed_by TEXT,
    heartbeat_ts TEXT,
    stage TEXT,
    run_id TEXT,
    retry_count INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
-- Stage DAG edges: one row per (node -> prerequisite). A node in
-- ``ingest_queue`` (status ``blocked``) becomes ``pending`` only once every
-- prerequisite has succeeded (see infra/ingest/queue.advance_dependents).
CREATE TABLE IF NOT EXISTS ingest_stage_deps (
    doc_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    depends_on TEXT NOT NULL,
    PRIMARY KEY (doc_id, run_id, stage, depends_on)
);
-- One row per (document, run): owns the attempt's run_id and the
-- exactly-once publication guard (``finalized``) so concurrent final-node
-- completions cannot promote the same run twice.
CREATE TABLE IF NOT EXISTS ingest_runs (
    doc_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    finalized INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (doc_id, run_id)
);
CREATE TABLE IF NOT EXISTS ingest_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    stage TEXT,
    level TEXT DEFAULT 'info',
    message TEXT,
    ts_ms INTEGER,
    task_id TEXT,
    run_id TEXT,
    data TEXT
);
CREATE INDEX IF NOT EXISTS idx_il_run ON ingest_logs(doc_id, run_id);
CREATE INDEX IF NOT EXISTS idx_iq_status ON ingest_queue(status);
CREATE INDEX IF NOT EXISTS idx_iq_doc ON ingest_queue(doc_id, run_id);
-- One queue node per (document, run, stage): lets a re-enqueue be idempotent
-- via INSERT OR IGNORE.
CREATE UNIQUE INDEX IF NOT EXISTS uq_iq_doc_run_stage
    ON ingest_queue(doc_id, run_id, stage)
    WHERE doc_id IS NOT NULL AND run_id IS NOT NULL AND stage IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_isd_stage ON ingest_stage_deps(doc_id, run_id, stage);
CREATE INDEX IF NOT EXISTS idx_il_doc ON ingest_logs(doc_id);
-- Library documents. doc_id is the SHA-256 hex digest of the document's bytes,
-- so the primary key doubles as the content address: identical bytes always
-- map to one row. file_name is UNIQUE — the library rejects two documents that
-- share a name — which is why no filename scan is needed to enforce it.
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL DEFAULT '',
    page_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_documents_created ON documents(created_at);
"""

_MOL_SCHEMA = """
CREATE TABLE IF NOT EXISTS molecules (
    mol_id TEXT PRIMARY KEY,
    smiles TEXT NOT NULL,
    esmiles TEXT,
    name TEXT DEFAULT '',
    source_doc TEXT,
    activity REAL,
    activity_type TEXT,
    units TEXT,
    source_type TEXT DEFAULT 'manual',
    status TEXT DEFAULT 'active',
    properties TEXT DEFAULT '{}',
    labels TEXT DEFAULT '[]',
    semantic_tags TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    fingerprint BLOB,
    canonical_smiles TEXT,
    review_status TEXT DEFAULT 'pending',
    reviewed_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS molecule_images (
    image_id TEXT PRIMARY KEY,
    mol_id TEXT NOT NULL,
    image_path TEXT,
    page INTEGER,
    vlm_esmiles TEXT,
    vlm_confidence REAL,
    is_structure_diagram INTEGER DEFAULT 0,
    bbox_in_image TEXT,
    moldet_conf REAL,
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id)
);
CREATE TABLE IF NOT EXISTS molecule_detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mol_id TEXT,
    doc_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    conf_moldet REAL,
    conf_molscribe REAL,
    vlm_verified_esmiles TEXT,
    vlm_confidence REAL,
    evidence_id TEXT,
    context_text TEXT,
    UNIQUE(mol_id, doc_id, page),
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id)
);
CREATE INDEX IF NOT EXISTS idx_m_smiles ON molecules(smiles);
CREATE INDEX IF NOT EXISTS idx_m_source ON molecules(source_doc);
CREATE INDEX IF NOT EXISTS idx_m_status ON molecules(status);
CREATE INDEX IF NOT EXISTS idx_m_type ON molecules(source_type);
CREATE INDEX IF NOT EXISTS idx_m_canonical ON molecules(canonical_smiles);
CREATE INDEX IF NOT EXISTS idx_mi_mol ON molecule_images(mol_id);
CREATE INDEX IF NOT EXISTS idx_md_doc_page ON molecule_detections(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_md_mol ON molecule_detections(mol_id);
CREATE INDEX IF NOT EXISTS idx_md_evidence_id ON molecule_detections(evidence_id);
-- Append-only audit log for review actions (confirm / reject / reopen).
-- ``snapshot`` carries the full row state at the time of the action so an
-- auditor can reproduce the decision without joining back to the
-- still-changing main tables. The table name is historical: it now records
-- every ``review_items`` decision.
CREATE TABLE IF NOT EXISTS markush_decisions (
    decision_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    previous_state TEXT,
    new_state TEXT,
    reason TEXT DEFAULT '',
    snapshot TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_md_entity ON markush_decisions(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_md_action ON markush_decisions(action);
"""

# Canonical page evidence shared by Extract, Markdown and all interpretation
# layers. One row per page location: ``kind`` is the producer's own label and
# ``raw_text`` is the single payload column (recognized text, Markdown table, or
# the molecule observation JSON).  A region the producer located but could not
# read carries an empty payload.
_SOURCE_EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS source_evidence (
    evidence_id TEXT PRIMARY KEY NOT NULL,
    doc_id TEXT NOT NULL,
    page INTEGER NOT NULL CHECK (page >= 1),
    bbox_x0 REAL NOT NULL,
    bbox_y0 REAL NOT NULL,
    bbox_x1 REAL NOT NULL,
    bbox_y1 REAL NOT NULL,
    raw_text TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    -- Zero-based reading position inside the page. The producer writes the
    -- layout's column-aware order here; 0 is the legacy default and falls
    -- back to the geometric tie-breakers when every row of a page is 0.
    reading_order INTEGER NOT NULL DEFAULT 0,
    CHECK (bbox_x0 >= 0 AND bbox_y0 >= 0 AND bbox_x0 <= bbox_x1 AND bbox_y0 <= bbox_y1)
);
CREATE INDEX IF NOT EXISTS idx_se_doc_page_kind
    ON source_evidence(doc_id, page, kind);
-- idx_se_doc_page_order is created by _migrate_molecule_schema after it has
-- ensured the reading_order column exists on a pre-existing database.
CREATE INDEX IF NOT EXISTS idx_se_doc_bbox
    ON source_evidence(doc_id, bbox_x0, bbox_y0, bbox_x1, bbox_y1);
"""

# Append-only molecule corrections and the unified review queue.
# Review items intentionally keep their source payload as JSON so new review
# kinds can be added without a schema change.
_REVIEW_V12_SCHEMA = """
CREATE TABLE IF NOT EXISTS molecule_corrections (
    correction_id INTEGER PRIMARY KEY AUTOINCREMENT,
    mol_id TEXT NOT NULL,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mc_mol ON molecule_corrections(mol_id, created_at);

CREATE TABLE IF NOT EXISTS review_items (
    item_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    doc_id TEXT,
    page INTEGER,
    bbox_x0 REAL,
    bbox_y0 REAL,
    bbox_x1 REAL,
    bbox_y1 REAL,
    crop_relpath TEXT,
    smiles TEXT,
    name TEXT,
    confidence REAL,
    reasons TEXT NOT NULL DEFAULT '[]',
    context_text TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    payload TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ri_status_kind ON review_items(status, kind);
CREATE INDEX IF NOT EXISTS idx_ri_doc ON review_items(doc_id);
"""

# Patent activity readings as first-class rows.
#
# The split matters: a printed reading is complete, traceable data whether or
# not its compound has a recognized structure — a patent frequently prints
# ``化合物 77-A, IC50 = 12 nM, page 152`` long before anything knows which drawn
# structure that designation owns. ``measurements`` therefore stores the reading
# with NO structural requirement, and ``measurement_attribution`` stores the
# ``reading -> structure`` links as zero-or-more rows that are filled in
# incrementally. ``entry_id`` (the printed designation) is likewise optional.
#
# ``evidence_grade`` separates a figure the document printed from one a model
# produced. Phase A writes only ``measured``; later compute paths (structure
# prediction) must never reuse this column to claim a measurement.
#
# ``measurements.measurement_id`` is the deterministic id the Patent stage
# already mints (doc + page + metric + raw value + row label), so a re-run
# upserts the same row instead of duplicating it.
_MEASUREMENTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    measurement_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    entry_id TEXT,                        -- printed designation, nullable
    assay_method_id TEXT,                 -- owning assay section, nullable
    metric TEXT,                          -- IC50 / Ki / inhibition %
    activity_type TEXT NOT NULL DEFAULT 'activity',
    measurement_kind TEXT DEFAULT 'quantitative',
    original_value REAL,
    original_unit TEXT DEFAULT '',
    canonical_value REAL,
    canonical_unit TEXT DEFAULT '',
    operator TEXT DEFAULT '',
    scale TEXT DEFAULT 'linear',
    value_text TEXT,
    qualitative_raw TEXT DEFAULT '',
    qualitative_rank INTEGER,
    qualitative_scheme TEXT DEFAULT '',
    qualitative_label TEXT DEFAULT '',
    target TEXT,
    species TEXT,
    assay_type TEXT,
    assay_description TEXT,
    raw_text TEXT DEFAULT '',
    page_num INTEGER,
    table_idx INTEGER,
    row_idx INTEGER,
    col_idx INTEGER,
    row_label TEXT DEFAULT '',
    reference_raw TEXT DEFAULT '',
    reference_key TEXT DEFAULT '',
    reference_type TEXT DEFAULT '',
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    provenance TEXT NOT NULL DEFAULT '{}',
    evidence_grade TEXT NOT NULL DEFAULT 'measured',
    review_status TEXT NOT NULL DEFAULT 'pending',
    linking_status TEXT NOT NULL DEFAULT 'pending',
    run_id TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_meas_doc ON measurements(doc_id);
CREATE INDEX IF NOT EXISTS idx_meas_target ON measurements(target);
CREATE INDEX IF NOT EXISTS idx_meas_assay ON measurements(assay_description);
CREATE INDEX IF NOT EXISTS idx_meas_doc_order
    ON measurements(doc_id, page_num, table_idx, row_idx);
CREATE INDEX IF NOT EXISTS idx_meas_grade ON measurements(evidence_grade);

CREATE TABLE IF NOT EXISTS measurement_attribution (
    attribution_id TEXT PRIMARY KEY,
    measurement_id TEXT NOT NULL,
    mol_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,                 -- denormalized for document-scoped cleanup
    method TEXT NOT NULL DEFAULT 'rule',  -- rule / model / human / agent
    confidence REAL,
    evidence_id TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(measurement_id, mol_id, method),
    FOREIGN KEY (measurement_id) REFERENCES measurements(measurement_id)
        ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mat_meas ON measurement_attribution(measurement_id);
CREATE INDEX IF NOT EXISTS idx_mat_mol ON measurement_attribution(mol_id);
CREATE INDEX IF NOT EXISTS idx_mat_doc ON measurement_attribution(doc_id);
"""

# Committed Patent-analysis state: ONE row per document — the authoritative
# snapshot of its published patent facts. ``patent_facts.json`` is a rebuildable
# projection of this row, and ``source_evidence`` remains the only raw-evidence
# source; model output is never evidence. ``revision`` increments per successful
# commit; ``evidence_signature`` records the evidence set the snapshot was
# computed from, so a re-extract makes the row stale instead of silently current.
# Document deletion clears the row; clearing the review queue does not.
_PATENT_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS patent_analysis_state (
    doc_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    evidence_signature TEXT NOT NULL,
    analysis_status TEXT NOT NULL,          -- disabled / succeeded / fallback
    extraction_mode TEXT NOT NULL,          -- deterministic / hybrid
    payload TEXT NOT NULL,                  -- committed fact snapshot (strict contract)
    updated_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


_MOL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS mol_search USING fts5(
    name, notes, smiles, content='molecules', content_rowid='rowid'
);
"""

# ADR 0001 relation-pair contract. The canonical unit is a document-local
# relation pair, not a molecule or a fact row. ``label_anchor`` records a
# printed designation slot (the fact); ``relation_pair`` records the resolution
# (the assertion); ``page_geometry`` carries the scanned-page metadata geometry
# checks need. Structures are referenced by mol_id only — a pair never stores
# SMILES. The local library is disposable development data, so the canonical
# schema is updated directly and no migration is written.
_RELATION_SCHEMA = """
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
"""
