"""Canonical SQLite DDL for the unified library database.

Pure constants only — connection handling, idempotent column backfills, and
other runtime logic live in :mod:`mbforge.storage.sqlite.database`.
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
-- User-defined collections (visible as library "Groups"). A parent delete
-- cascades to its whole subtree; a collection delete also drops membership.
-- Documents live on disk (JSON), so collection_documents only references
-- doc_id by application contract, not a SQL foreign key.
CREATE TABLE IF NOT EXISTS collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES collections(collection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_collection_parent ON collections(parent_id);
CREATE TABLE IF NOT EXISTS collection_documents (
    collection_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, doc_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_collection_documents_doc ON collection_documents(doc_id);
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
    UNIQUE(mol_id, doc_id, page),
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id)
);
CREATE TABLE IF NOT EXISTS text_molecule_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    mol_id TEXT NOT NULL,
    section_index INTEGER,
    page INTEGER,
    text_excerpt TEXT,
    role TEXT DEFAULT 'mentioned',
    code_text TEXT,
    char_start INTEGER,
    char_end INTEGER,
    created_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_m_smiles ON molecules(smiles);
CREATE INDEX IF NOT EXISTS idx_m_source ON molecules(source_doc);
CREATE INDEX IF NOT EXISTS idx_m_status ON molecules(status);
CREATE INDEX IF NOT EXISTS idx_m_type ON molecules(source_type);
CREATE INDEX IF NOT EXISTS idx_m_canonical ON molecules(canonical_smiles);
CREATE INDEX IF NOT EXISTS idx_mi_mol ON molecule_images(mol_id);
CREATE INDEX IF NOT EXISTS idx_mr_type ON molecule_relations(relation_type);
CREATE INDEX IF NOT EXISTS idx_tml_doc_mol ON text_molecule_links(doc_id, mol_id);
CREATE INDEX IF NOT EXISTS idx_md_doc_page ON molecule_detections(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_md_mol ON molecule_detections(mol_id);
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

# First-class evidence chain: every (molecule, document, page) combination where
# the molecule was observed — figure kind (with bbox + crop), text kind (with
# context excerpt + MoleCode block), or future table kind.
#
# `canonical_smiles` is the natural join key into `molecules.canonical_smiles`.
# We do NOT add a FOREIGN KEY because the pipeline writes evidence rows first
# (during detect / register) and only the admin router creates `molecules`
# rows on demand. Adding a FK would block the detect path. The join is
# enforced by application logic in routers/molecule.py.
_EVIDENCE_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_smiles TEXT NOT NULL,
    mol_id TEXT,
    doc_id TEXT NOT NULL,
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    context_text TEXT,
    code_text TEXT,
    role TEXT DEFAULT 'detected',
    kind TEXT NOT NULL,
    confidence REAL,
    source_type TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    row_label TEXT,
    table_idx INTEGER,
    row_idx INTEGER,
    col_idx INTEGER
);
CREATE INDEX IF NOT EXISTS idx_ev_cs ON evidence(canonical_smiles);
CREATE INDEX IF NOT EXISTS idx_ev_doc_page ON evidence(doc_id, page);
CREATE INDEX IF NOT EXISTS idx_ev_kind ON evidence(kind);
"""

# Canonical page evidence shared by Extract, Detection, Markdown and all
# interpretation layers. This is deliberately separate from ``evidence``,
# the existing molecule-observation table used by molecule queries.
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
    coref TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    CHECK (bbox_x0 >= 0 AND bbox_y0 >= 0 AND bbox_x0 <= bbox_x1 AND bbox_y0 <= bbox_y1),
    CHECK (length(trim(raw_text)) > 0 OR length(trim(coref)) > 0),
    UNIQUE(doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, kind)
);
CREATE INDEX IF NOT EXISTS idx_se_doc_page_kind
    ON source_evidence(doc_id, page, kind);
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

# Structured activity data: one row per (molecule, target, assay_description)
# combination. This is the first-class store for SAR queries
# (find compound best activity, rank by target, etc.); the `evidence` table
# still records *where* the activity came from (row_idx/table_idx/page) but
# does not store target/assay/value in queryable columns.
_ACTIVITIES_SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    mol_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,         -- IC50 / pIC50 / Ki / qualitative
    value REAL,                           -- comparable value; usually nM
    value_original REAL,                  -- value in the original unit
    unit_original TEXT,                   -- nM / μM / mM
    operator TEXT DEFAULT '=',
    measurement_kind TEXT DEFAULT 'quantitative',
    metric TEXT,
    value_canonical REAL,
    unit_canonical TEXT,
    operator_original TEXT,
    scale TEXT DEFAULT 'linear',
    value_text TEXT,
    qualitative_raw TEXT,
    qualitative_rank INTEGER,
    qualitative_scheme TEXT,
    qualitative_label TEXT,
    reference_raw TEXT,
    reference_key TEXT,
    reference_type TEXT,
    target TEXT,                          -- protein/enzyme name (e.g. STAT6)
    assay_type TEXT,                      -- enzymatic / cellular / binding
    assay_description TEXT,               -- human-readable assay name (e.g. hSTAT6 TR-FRET)
    confidence REAL,
    page_num INTEGER,
    table_idx INTEGER,
    row_idx INTEGER,
    col_idx INTEGER,
    row_label TEXT,
    row_smiles TEXT,
    raw_text TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_act_mol ON activities(mol_id);
CREATE INDEX IF NOT EXISTS idx_act_doc ON activities(doc_id);
CREATE INDEX IF NOT EXISTS idx_act_target ON activities(target);
CREATE INDEX IF NOT EXISTS idx_act_assay ON activities(assay_description);
CREATE INDEX IF NOT EXISTS idx_act_doc_target_assay
    ON activities(doc_id, target, assay_description);
CREATE INDEX IF NOT EXISTS idx_act_doc_row
    ON activities(doc_id, table_idx, row_idx);
"""


_MOL_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS mol_search USING fts5(
    name, notes, smiles, content='molecules', content_rowid='rowid'
);
"""
