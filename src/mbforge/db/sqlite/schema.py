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
CREATE TABLE IF NOT EXISTS molecule_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mol_a_id TEXT NOT NULL,
    mol_b_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    score REAL,
    metadata TEXT DEFAULT '{}',
    UNIQUE(mol_a_id, mol_b_id, relation_type),
    FOREIGN KEY (mol_a_id) REFERENCES molecules(mol_id),
    FOREIGN KEY (mol_b_id) REFERENCES molecules(mol_id)
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
CREATE INDEX IF NOT EXISTS idx_mr_type ON molecule_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_md_doc_page ON molecule_detections(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_md_mol ON molecule_detections(mol_id);
CREATE INDEX IF NOT EXISTS idx_md_evidence_id ON molecule_detections(evidence_id);
CREATE TABLE IF NOT EXISTS markush_scaffolds (
    scaffold_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    formula_label TEXT DEFAULT '',
    smiles TEXT NOT NULL,
    esmiles TEXT,
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending',
    properties TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ms_doc ON markush_scaffolds(doc_id);
CREATE INDEX IF NOT EXISTS idx_ms_status ON markush_scaffolds(status);
CREATE TABLE IF NOT EXISTS markush_fragments (
    fragment_id TEXT PRIMARY KEY,
    scaffold_id TEXT DEFAULT NULL,
    doc_id TEXT NOT NULL,
    label TEXT DEFAULT '',
    smiles TEXT NOT NULL,
    esmiles TEXT,
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending',
    properties TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (scaffold_id) REFERENCES markush_scaffolds(scaffold_id)
);
CREATE INDEX IF NOT EXISTS idx_mf_doc ON markush_fragments(doc_id);
CREATE INDEX IF NOT EXISTS idx_mf_scaffold ON markush_fragments(scaffold_id);
CREATE INDEX IF NOT EXISTS idx_mf_status ON markush_fragments(status);
-- Persist ``review_required`` candidates so users can decide
-- scaffold/fragment/complete/reject without losing data on re-import.
-- ``source_key`` is the stable identity for a candidate across
-- re-ingests; ``content_hash`` distinguishes a structurally changed
-- re-occurrence from an unchanged one.
CREATE TABLE IF NOT EXISTS markush_review_candidates (
    candidate_id TEXT PRIMARY KEY,
    source_key TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    predicted_role TEXT NOT NULL,
    smiles TEXT,
    esmiles TEXT,
    name TEXT DEFAULT '',
    raw_label TEXT DEFAULT '',
    normalized_label TEXT DEFAULT '',
    label_kind TEXT DEFAULT 'unknown',
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    moldet_confidence REAL,
    scribe_confidence REAL,
    composite_confidence REAL,
    reasons TEXT NOT NULL DEFAULT '[]',
    context_text TEXT DEFAULT '',
    properties TEXT NOT NULL DEFAULT '{}',
    recognition_status TEXT NOT NULL DEFAULT 'valid',
    review_status TEXT NOT NULL DEFAULT 'pending',
    review_version INTEGER NOT NULL DEFAULT 1,
    superseded_at TEXT,
    content_hash TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_mrc_doc ON markush_review_candidates(doc_id);
CREATE INDEX IF NOT EXISTS idx_mrc_review_status ON markush_review_candidates(review_status);
CREATE INDEX IF NOT EXISTS idx_mrc_predicted_role ON markush_review_candidates(predicted_role);
-- A superseded row keeps its source_key so an auditor can pair the old
-- decision with the replacement; only the *active* row per source_key
-- must be unique, hence a partial index.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mrc_source_key_active
    ON markush_review_candidates(source_key)
    WHERE superseded_at IS NULL;
-- Every detection associated with a review candidate, scaffold,
-- fragment, or generated molecule is recorded here so the review UI can
-- show the full multi-page / multi-bbox evidence chain.
CREATE TABLE IF NOT EXISTS markush_evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    context_text TEXT,
    moldet_confidence REAL,
    scribe_confidence REAL,
    composite_confidence REAL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_me_entity ON markush_evidence(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_me_doc ON markush_evidence(doc_id);
-- Append-only audit log for review actions (confirm / reject /
-- reopen / update). ``snapshot`` carries the full row state at the time
-- of the action so an auditor can reproduce the decision without joining
-- back to the still-changing main tables.
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
-- Attachment sites, R-group options, and mount relationships
-- (suggested / confirmed). ``markush_sites`` requires explicit atom-map
-- numbers via ``[*:1]``-style SMILES — implicit mapping by * position
-- order is intentionally disallowed.
CREATE TABLE IF NOT EXISTS markush_sites (
    site_id TEXT PRIMARY KEY,
    scaffold_id TEXT NOT NULL,
    site_label TEXT NOT NULL,
    atom_map_num INTEGER,
    attachment_count INTEGER NOT NULL DEFAULT 1,
    bond_type TEXT,
    source_text TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (scaffold_id) REFERENCES markush_scaffolds(scaffold_id)
);
CREATE INDEX IF NOT EXISTS idx_mst_scaffold ON markush_sites(scaffold_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_mst_label ON markush_sites(scaffold_id, site_label);
CREATE TABLE IF NOT EXISTS markush_options (
    option_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    fragment_id TEXT,
    normalized_smiles TEXT,
    definition_text TEXT NOT NULL DEFAULT '',
    constraints TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (site_id) REFERENCES markush_sites(site_id),
    FOREIGN KEY (fragment_id) REFERENCES markush_fragments(fragment_id)
);
CREATE INDEX IF NOT EXISTS idx_mo_site ON markush_options(site_id);
CREATE INDEX IF NOT EXISTS idx_mo_fragment ON markush_options(fragment_id);
CREATE TABLE IF NOT EXISTS markush_mounts (
    mount_id TEXT PRIMARY KEY,
    site_id TEXT NOT NULL,
    fragment_id TEXT NOT NULL,
    origin TEXT NOT NULL,
    confidence REAL,
    reasons TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'suggested',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (site_id) REFERENCES markush_sites(site_id),
    FOREIGN KEY (fragment_id) REFERENCES markush_fragments(fragment_id)
);
CREATE INDEX IF NOT EXISTS idx_mmnt_site ON markush_mounts(site_id);
CREATE INDEX IF NOT EXISTS idx_mmnt_fragment ON markush_mounts(fragment_id);
CREATE INDEX IF NOT EXISTS idx_mmnt_status ON markush_mounts(status);
-- Bounded enumeration: persist enumeration runs and
-- generated candidates so users can review them before promotion to the
-- ``molecules`` table. ``theoretical_count`` is computed up front so the
-- API can refuse oversized runs without doing the work.
CREATE TABLE IF NOT EXISTS markush_generation_runs (
    run_id TEXT PRIMARY KEY,
    scaffold_id TEXT NOT NULL,
    selection TEXT NOT NULL,
    theoretical_count INTEGER NOT NULL,
    requested_limit INTEGER NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    FOREIGN KEY (scaffold_id) REFERENCES markush_scaffolds(scaffold_id)
);
CREATE INDEX IF NOT EXISTS idx_mgen_scaffold ON markush_generation_runs(scaffold_id);
CREATE INDEX IF NOT EXISTS idx_mgen_status ON markush_generation_runs(status);
CREATE TABLE IF NOT EXISTS markush_generated_candidates (
    generated_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    scaffold_id TEXT NOT NULL,
    combination_key TEXT NOT NULL,
    smiles TEXT NOT NULL,
    canonical_smiles TEXT NOT NULL,
    assignments TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending',
    properties TEXT NOT NULL DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(run_id, combination_key),
    FOREIGN KEY (run_id) REFERENCES markush_generation_runs(run_id)
);
CREATE INDEX IF NOT EXISTS idx_mgc_run ON markush_generated_candidates(run_id);
CREATE INDEX IF NOT EXISTS idx_mgc_review ON markush_generated_candidates(review_status);
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
    method TEXT NOT NULL DEFAULT 'rule',  -- rule / model / human
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
# snapshot of its published patent facts plus the human conflict decisions.
# ``patent_facts.json`` is a rebuildable projection of this row, and
# ``source_evidence`` remains the only raw-evidence source; model output is
# never evidence. ``revision`` increments per successful commit;
# ``evidence_signature`` records the evidence set the snapshot was computed
# from, so a re-extract makes the row (and any decision whose stored signature
# no longer matches) stale instead of silently current. Column set is fixed by
# P0 of docs/plan-patent-agent-harness.md; document deletion clears the row,
# clearing the review queue does not.
_RESEARCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS research_sessions (
    session_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    updated_at REAL NOT NULL,
    payload TEXT NOT NULL CHECK (json_valid(payload))
);
CREATE INDEX IF NOT EXISTS idx_research_updated ON research_sessions(updated_at DESC);
CREATE TABLE IF NOT EXISTS research_task_requests (
    request_key TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    session_id TEXT NOT NULL REFERENCES research_sessions(session_id) ON DELETE CASCADE,
    PRIMARY KEY (request_key, doc_id)
);
"""

_PATENT_ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS patent_analysis_state (
    doc_id TEXT PRIMARY KEY,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    evidence_signature TEXT NOT NULL,
    analysis_status TEXT NOT NULL,          -- disabled / succeeded / fallback
    extraction_mode TEXT NOT NULL,          -- deterministic / hybrid
    payload TEXT NOT NULL,                  -- committed fact snapshot (strict contract)
    decisions TEXT NOT NULL DEFAULT '{}',   -- slot_id -> PatentDecision
    updated_at TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


_MOL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS mol_search USING fts5(
    name, notes, smiles, content='molecules', content_rowid='rowid'
);
"""
