# Backend Library Root Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the Python backend so that every Library is a self-contained unit with a single `.mbforge/library.db`, `entities/` directory, internal PageIndex, and unified terminology (`entity_id` / `library_root`).

**Architecture:** Introduce a migration layer (`src/mbforge/core/migration.py`) that detects legacy layouts and moves data into the new structure; collapse `DatabaseManager`'s two-database model into one database managed by `LibraryStore`; rename all `doc_id` columns/params to `entity_id` and all `project_root` references to `library_root` across the backend.

**Tech Stack:** Python 3.12, FastAPI, SQLite, Pydantic 2, uv, pytest.

## Global Constraints

- Every module starts with `logger = get_logger(__name__)`; never `print()`.
- All errors inherit from `MBForgeError` with `status_code` + `error_code` class attrs.
- Use `from __future__ import annotations` to avoid runtime forward refs.
- Public functions must be fully type-annotated.
- Run `uv run ruff check src/` after file edits; keep line width 88.
- Run `uv run pytest tests/ -v` before claiming a task passes.
- Commit each task independently with a descriptive message.
- The backend must remain importable and the dev server (`uv run uvicorn mbforge.app:app`) must start after every task.

---

## File Structure

### New files

- `src/mbforge/core/migration.py` — Detects legacy library layouts and migrates them to the new structure.

### Modified files (grouped by responsibility)

- **Schema & connection**
  - `src/mbforge/core/database.py` — Collapse two databases into one; rename `doc_id` → `entity_id`; remove `project_root` column from `semantic_cache`; bump `SCHEMA_VERSION`.
  - `src/mbforge/core/library.py` — Store DB at `.mbforge/library.db`; store files under `entities/`; rename `documents` table → `entities`; rename `doc_id` → `entity_id`; add `tags`/`entity_tags`/`pages` tables.

- **Models**
  - `src/mbforge/models/library.py` — Rename `DocumentInfo` → `EntityInfo`, `doc_id` → `entity_id`.

- **Pipeline**
  - `src/mbforge/pipeline/runner.py` — `doc_id` → `entity_id`, `project_root` → `library_root`, paths `storage/` → `entities/`.
  - `src/mbforge/pipeline/extract_molecules.py` — `doc_id` → `entity_id`, `project_root` → `library_root`, crops path.
  - `src/mbforge/pipeline/persist_molecules.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.

- **Knowledge base & OpenKB**
  - `src/mbforge/core/knowledge_base.py` — `doc_id` → `entity_id`, paths.
  - `src/mbforge/openkb/adapter.py` — `project_root` → `library_root`, PageIndex path to `.mbforge/pageindex/`, wiki to `wiki/`.
  - `src/mbforge/openkb/compiler.py` — `doc_id` → `entity_id`, wiki output path.
  - `src/mbforge/openkb/indexer.py` — `doc_id` → `entity_id`.
  - `src/mbforge/openkb/query.py` — `doc_id` → `entity_id`.

- **Routers**
  - `src/mbforge/routers/library.py` — `doc_id` → `entity_id`; route `/documents/{doc_id}/file` → `/entities/{entity_id}/file`.
  - `src/mbforge/routers/documents.py` — `doc_id` → `entity_id`.
  - `src/mbforge/routers/pipeline.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `src/mbforge/routers/knowledge_base.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `src/mbforge/routers/detection_cache.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `src/mbforge/routers/legacy_models.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `src/mbforge/routers/coref.py` — return field `doc_id` → `entity_id`.
  - `src/mbforge/routers/pdf.py` — return field `doc_id` → `entity_id`.
  - `src/mbforge/routers/notes.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `src/mbforge/routers/agent.py` — `project_root` → `library_root`.
  - `src/mbforge/app.py` — verify router includes still valid.

- **Agent & utils**
  - `src/mbforge/agent/tools.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `src/mbforge/agent/sessions.py` — `project_root` → `library_root`.
  - `src/mbforge/utils/helpers.py` — remove `project_root` fallback in `resolve_root`/`validate_path`.
  - `src/mbforge/core/semantic_cache.py` — `project_root` → `library_root` or drop column.
  - `src/mbforge/core/file_scanner.py` — `doc_id` → `entity_id`.
  - `src/mbforge/models/molecule.py` — `project_root` → `library_root`.

- **Tests**
  - `tests/unit/pipeline/test_persist_molecules.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `tests/unit/test_routers_smoke.py` — `doc_id` → `entity_id`, `project_root` → `library_root`.
  - `tests/unit/test_mbforge_error.py` — `doc_id` → `entity_id`.
  - `tests/conftest.py` — add legacy-layout fixtures if needed.
  - `tests/unit/test_migration.py` — new tests for migration module.

---

## Task Decomposition

### Task 1: Create migration module skeleton

**Files:**
- Create: `src/mbforge/core/migration.py`
- Test: `tests/unit/test_migration.py`

**Interfaces:**
- Produces: `detect_legacy_layout(library_root: str | Path) -> bool`
- Produces: `migrate_library(library_root: str | Path) -> None`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from mbforge.core.migration import detect_legacy_layout


def test_detect_legacy_layout_true_when_storage_exists(tmp_path: Path) -> None:
    (tmp_path / "storage").mkdir()
    assert detect_legacy_layout(str(tmp_path)) is True


def test_detect_legacy_layout_false_for_fresh_root(tmp_path: Path) -> None:
    assert detect_legacy_layout(str(tmp_path)) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_migration.py -v`
Expected: FAIL with "cannot import name 'detect_legacy_layout'"

- [ ] **Step 3: Write minimal implementation**

```python
"""Library layout migration — detect and convert legacy directory structures."""

from __future__ import annotations

from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger("mbforge.core.migration")


def detect_legacy_layout(library_root: str | Path) -> bool:
    """Return True if the directory looks like a pre-refactor library."""
    root = Path(library_root)
    return (root / "storage").exists() or (root / "index").exists()


def migrate_library(library_root: str | Path) -> None:
    """Migrate a legacy library layout to the current structure."""
    raise NotImplementedError("migrate_library implemented in Task 6")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/migration.py tests/unit/test_migration.py
git commit -m "feat(core): add migration module skeleton

- detect_legacy_layout checks for legacy storage/ and index/ dirs
- migrate_library placeholder for upcoming migration logic"
```

---

### Task 2: Rename `doc_id` → `entity_id` in `database.py` schema

**Files:**
- Modify: `src/mbforge/core/database.py`
- Test: `tests/unit/test_database_schema.py` (new)

**Interfaces:**
- Consumes: existing `DatabaseManager` API
- Produces: schema strings where `doc_id` is replaced by `entity_id`; `record_ingest_event` parameter `doc_id` → `entity_id`

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from pathlib import Path

from mbforge.core.database import DatabaseManager, SCHEMA_VERSION


def test_schema_uses_entity_id_not_doc_id(tmp_path: Path) -> None:
    mgr = DatabaseManager(str(tmp_path))
    mgr.initialize()
    conn = sqlite3.connect(str(tmp_path / ".mbforge" / "library.db"))
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "entities" in tables or "ingest_events" in tables
        cols = {r[1] for r in conn.execute("PRAGMA table_info(ingest_events)")}
        assert "entity_id" in cols
        assert "doc_id" not in cols
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_database_schema.py -v`
Expected: FAIL (path or column mismatch)

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/core/database.py`:

1. Update module docstring:

```python
"""SQLite database manager — schema creation and connection management.

Single database per library:
- {library_root}/.mbforge/library.db: all business, ingest, molecule, and cache tables.
"""
```

2. Bump `SCHEMA_VERSION = 4`.

3. In `_KB_SCHEMA`, replace every `doc_id` with `entity_id`:

```python
_KB_SCHEMA = """
CREATE TABLE IF NOT EXISTS figure_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    label_bbox TEXT,
    label_text TEXT,
    ocr_conf REAL,
    image_path TEXT,
    UNIQUE(entity_id, page, label_bbox, label_text)
);
CREATE TABLE IF NOT EXISTS coref_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    mol_smiles TEXT,
    mol_bbox TEXT,
    mol_conf REAL,
    label_id INTEGER,
    label_text TEXT,
    label_bbox TEXT,
    confidence REAL,
    source TEXT DEFAULT 'geometric',
    is_confirmed INTEGER DEFAULT 0,
    image_path TEXT,
    UNIQUE(entity_id, page, mol_smiles, label_text)
);
CREATE TABLE IF NOT EXISTS ingest_queue (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    entity_id TEXT,
    status TEXT DEFAULT 'pending',
    stage TEXT,
    progress_pct REAL DEFAULT 0,
    pages_total INTEGER DEFAULT 0,
    pages_done INTEGER DEFAULT 0,
    retry_count INTEGER DEFAULT 0,
    error TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS ingest_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id TEXT NOT NULL,
    stage TEXT,
    level TEXT DEFAULT 'info',
    message TEXT,
    ts_ms INTEGER,
    task_id TEXT
);
CREATE TABLE IF NOT EXISTS semantic_cache (
    query_hash TEXT PRIMARY KEY,
    query_text TEXT NOT NULL,
    results TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    hit_count INTEGER DEFAULT 0,
    last_hit TEXT
);
CREATE INDEX IF NOT EXISTS idx_fl_doc_page ON figure_labels(entity_id, page);
CREATE INDEX IF NOT EXISTS idx_fl_text ON figure_labels(label_text);
CREATE INDEX IF NOT EXISTS idx_cp_doc_page ON coref_predictions(entity_id, page);
CREATE INDEX IF NOT EXISTS idx_cp_text ON coref_predictions(label_text);
CREATE INDEX IF NOT EXISTS idx_cp_smiles ON coref_predictions(mol_smiles);
CREATE INDEX IF NOT EXISTS idx_cp_confirmed ON coref_predictions(is_confirmed);
CREATE INDEX IF NOT EXISTS idx_iq_status ON ingest_queue(status);
CREATE INDEX IF NOT EXISTS idx_il_doc ON ingest_logs(entity_id);
CREATE TABLE IF NOT EXISTS molecule_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id INTEGER NOT NULL,
    entity_id TEXT NOT NULL,
    reject_reason TEXT,
    candidate_smiles TEXT,
    crop_relpath TEXT,
    created_at INTEGER,
    reviewed_at INTEGER,
    reviewer_action TEXT,
    review_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_mr_doc ON molecule_reviews(entity_id);
CREATE INDEX IF NOT EXISTS idx_mr_open ON molecule_reviews(reviewer_action) WHERE reviewer_action IS NULL;
CREATE TABLE IF NOT EXISTS ingest_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    entity_id TEXT,
    stage TEXT NOT NULL,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT,
    ts_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ie_task ON ingest_events(task_id, ts_ms);
"""
```

4. In `_MOL_SCHEMA`, replace `doc_id` with `entity_id`:

```python
CREATE TABLE IF NOT EXISTS molecule_detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mol_id TEXT,
    entity_id TEXT NOT NULL,
    page INTEGER NOT NULL,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    conf_moldet REAL,
    conf_molscribe REAL,
    vlm_verified_esmiles TEXT,
    vlm_confidence REAL,
    UNIQUE(mol_id, entity_id, page),
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id)
);
CREATE INDEX IF NOT EXISTS idx_md_doc_page ON molecule_detections(entity_id, page);
```

5. Update `record_ingest_event` signature and SQL:

```python
def record_ingest_event(
    database: DatabaseManager,
    *,
    task_id: str,
    entity_id: str | None,
    stage: str,
    level: str,
    message: str,
    data: dict | None,
    progress_pct: int | None,
    status: str | None,
) -> None:
    """Insert an ``ingest_events`` row and update ``ingest_queue`` progress / status."""
    ts_ms = int(time.time() * 1000)
    data_json = json.dumps(data or {}, ensure_ascii=False)
    with database.kb_conn() as conn:
        conn.execute(
            "INSERT INTO ingest_events (task_id, entity_id, stage, level, message, data_json, ts_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, entity_id, stage, level, message, data_json, ts_ms),
        )
        if progress_pct is not None or status is not None:
            conn.execute(
                "UPDATE ingest_queue SET stage = COALESCE(?, stage), progress_pct = COALESCE(?, progress_pct), "
                "status = COALESCE(?, status), updated_at = datetime('now') WHERE id = ?",
                (stage, progress_pct, status, task_id),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_database_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/database.py tests/unit/test_database_schema.py
git commit -m "refactor(database): rename doc_id to entity_id in schema

- Bump SCHEMA_VERSION to 4
- Replace doc_id with entity_id in _KB_SCHEMA and _MOL_SCHEMA
- Drop project_root column from semantic_cache (per-library DB)
- Update record_ingest_event parameter and SQL"
```

---

### Task 3: Collapse `DatabaseManager` into single library database

**Files:**
- Modify: `src/mbforge/core/database.py`
- Modify: `src/mbforge/core/library.py` (to call migration)
- Test: `tests/unit/test_database_schema.py`

**Interfaces:**
- Consumes: `LibraryStore` will create `.mbforge/library.db`
- Produces: `DatabaseManager.__init__(library_root)`, `kb_conn()` and `mol_conn()` both point to the same merged DB

- [ ] **Step 1: Write the failing test**

```python
def test_single_database_at_mbforge_library_db(tmp_path: Path) -> None:
    mgr = DatabaseManager(str(tmp_path))
    mgr.initialize()
    assert (tmp_path / ".mbforge" / "library.db").exists()
    with mgr.kb_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='molecules'"
        ).fetchall()
        assert rows
    with mgr.mol_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='ingest_events'"
        ).fetchall()
        assert rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_database_schema.py::test_single_database_at_mbforge_library_db -v`
Expected: FAIL (path mismatch)

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/core/database.py`:

1. Update `DatabaseManager.__init__`:

```python
class DatabaseManager:
    """Manages a single SQLite connection for a library."""

    def __init__(self, library_root: str | Path) -> None:
        self._root = Path(library_root)
        self._db_dir = self._root / ".mbforge"
        self._db_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._db_dir / "library.db"
        self._lock = threading.Lock()
        self._initialized = False
```

2. Update `get` parameter name:

```python
    @classmethod
    def get(cls, library_root: str | Path) -> DatabaseManager:
        """Get cached instance, avoiding repeated initialization."""
        key = str(Path(library_root).resolve())
        if key not in _db_cache:
            _db_cache[key] = cls(library_root)
        return _db_cache[key]
```

3. Update `initialize`:

```python
    def initialize(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._init_db(
                self._db_path,
                _KB_SCHEMA + _MOL_SCHEMA + _MOL_FTS,
                versioned=True,
            )
            self._initialized = True
            logger.info("DB initialized: %s", self._db_path)
```

4. Update connection context managers:

```python
    @contextmanager
    def kb_conn(self):
        self.initialize()
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @contextmanager
    def mol_conn(self):
        self.initialize()
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
```

5. Remove `kb_path` and `mol_path` properties (or keep returning `_db_path` for compatibility if anything uses them):

```python
    @property
    def db_path(self) -> Path:
        return self._db_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_database_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/database.py tests/unit/test_database_schema.py
git commit -m "refactor(database): collapse two databases into single library.db

- DatabaseManager now manages {library_root}/.mbforge/library.db
- kb_conn and mol_conn both yield connections to the same DB
- Remove separate knowledge_base.db and molecules.db paths"
```

---

### Task 4: Rename `doc_id` → `entity_id` in `LibraryStore` schema and methods

**Files:**
- Modify: `src/mbforge/core/library.py`
- Test: `tests/unit/test_library_store.py` (new or extend existing)

**Interfaces:**
- Consumes: `EntityInfo` from `src/mbforge/models/library.py`
- Produces: `entities` table, `entity_id` parameter names, `entities/` storage directory

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from pathlib import Path

from mbforge.core.library import LibraryStore


def test_library_store_uses_entities_table(tmp_path: Path) -> None:
    store = LibraryStore.get(str(tmp_path))
    entity = store.add_uploaded_file(b"hello", "test.pdf")
    assert entity.entity_id
    conn = sqlite3.connect(str(tmp_path / ".mbforge" / "library.db"))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(entities)")}
        assert "entity_id" in cols
        assert "doc_id" not in cols
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_library_store.py -v`
Expected: FAIL (cannot import or column mismatch)

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/core/library.py`:

1. Update module docstring:

```python
"""LibraryStore — unified data store for the Zotero-style library.

Manages a single `library.db` in `{library_root}/.mbforge/` and an entity
storage directory per imported PDF under `{library_root}/entities/{entity_id}/`.
"""
```

2. Update schema:

```python
_LIBRARY_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    entity_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    md5 TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    source TEXT DEFAULT 'import',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES collections(collection_id)
);

CREATE TABLE IF NOT EXISTS collection_members (
    collection_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, entity_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id),
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    tag_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entity_tags (
    entity_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (entity_id, tag_id),
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS pages (
    page_id TEXT PRIMARY KEY,
    entity_id TEXT,
    page_type TEXT,
    scroll_position REAL,
    extra_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
"""  # fmt: skip
```

3. Remove `tasks` table (or keep it but rename `doc_id` → `entity_id` if still used; assume removed after confirming no callers).

4. Update `__init__`:

```python
    def __init__(self, library_root: str | Path) -> None:
        self._root = Path(library_root).resolve()
        self._db_path = self._root / ".mbforge" / "library.db"
        self._entities_dir = self._root / "entities"
        self._initialized = False
```

5. Update `_ensure_initialized`:

```python
    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        ensure_dir(self._root)
        ensure_dir(self._entities_dir)
        self._init_db()
        self._initialized = True
```

6. Update `_init_db` to run migration before init:

```python
    def _init_db(self) -> None:
        """Create or migrate library.db."""
        from .migration import detect_legacy_layout, migrate_library

        if detect_legacy_layout(self._root):
            migrate_library(self._root)
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.executescript(_LIBRARY_SCHEMA)
            from .database import DatabaseManager

            conn.executescript(DatabaseManager.molecule_schema())
            conn.commit()
            logger.info("Library DB initialized at %s", self._db_path)
        finally:
            conn.close()
```

7. Replace every `doc_id` local variable/parameter/SQL with `entity_id` and every `self._storage_dir` with `self._entities_dir`.

8. Update `add_uploaded_file`, `_register`, `get_document`, `delete_document`, `list_documents`, `search_documents`, `update_document_status`, `add_to_collection`, `remove_from_collection`, `storage_path`, `resolve_file`, `_get_doc_by_md5`, `_require_doc`.

For example, `add_uploaded_file` becomes:

```python
    def add_uploaded_file(
        self, content: bytes, filename: str, title: str = ""
    ) -> EntityInfo:
        self._ensure_initialized()
        if not content:
            raise MBForgeError("Empty file", detail=filename)
        if not filename:
            raise MBForgeError("Missing filename")

        md5 = hashlib.md5(content).hexdigest()
        existing = self._get_entity_by_md5(md5)
        if existing is not None:
            raise MBForgeError(
                "Document already imported",
                detail=f"MD5 collision with entity_id={existing}",
            )

        entity_id = str(uuid.uuid4())
        safe_title = title.strip() if title else Path(filename).stem
        entity_subdir = self._entities_dir / entity_id
        try:
            ensure_dir(entity_subdir)
            dest = entity_subdir / filename
            dest.write_bytes(content)
        except (OSError, PermissionError) as e:
            raise MBForgeError("Failed to store file", detail=str(e)) from e

        storage_path = f"entities/{entity_id}/{filename}"
        conn = sqlite3.connect(str(self._db_path))
        try:
            conn.execute(
                """INSERT INTO entities (entity_id, title, file_name, storage_path, md5)
                   VALUES (?, ?, ?, ?, ?)""",
                (entity_id, safe_title, filename, storage_path, md5),
            )
            conn.commit()
        finally:
            conn.close()

        logger.info("Uploaded entity registered: %s (id=%s)", safe_title, entity_id)
        return EntityInfo(
            entity_id=entity_id,
            title=safe_title,
            file_name=filename,
            page_count=0,
            status="pending",
            created_at="",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_library_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/library.py tests/unit/test_library_store.py
git commit -m "refactor(library): rename documents to entities and doc_id to entity_id

- Rename documents table to entities
- Rename collection_members.doc_id to entity_id
- Add tags, entity_tags, pages tables
- Store files under entities/ instead of storage/"
```

---

### Task 5: Update `src/mbforge/models/library.py`

**Files:**
- Modify: `src/mbforge/models/library.py`
- Test: `tests/unit/test_models_library.py` (new)

**Interfaces:**
- Produces: `EntityInfo(entity_id=..., title=..., file_name=..., page_count=..., status=..., created_at=...)`

- [ ] **Step 1: Write the failing test**

```python
from mbforge.models.library import EntityInfo


def test_entity_info_has_entity_id() -> None:
    info = EntityInfo(entity_id="abc", title="T", file_name="f.pdf")
    assert info.entity_id == "abc"
    assert info.model_dump()["entity_id"] == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_models_library.py -v`
Expected: FAIL (EntityInfo not defined)

- [ ] **Step 3: Write minimal implementation**

```python
"""Pydantic models for the unified library (Zotero-style)."""

from __future__ import annotations

from pydantic import BaseModel


class EntityInfo(BaseModel):
    """A single imported entity in the library."""

    entity_id: str
    title: str
    file_name: str
    page_count: int = 0
    status: str = "pending"  # pending | indexing | ready | error
    created_at: str = ""


class CollectionInfo(BaseModel):
    """A collection in the library tree."""

    collection_id: str
    name: str
    parent_id: str | None = None
    entity_count: int = 0


class CollectionNode(CollectionInfo):
    """A collection node with nested children for tree rendering."""

    children: list[CollectionNode] = []


class LibraryStatus(BaseModel):
    """Library configuration status."""

    configured: bool
    root: str
    entity_count: int
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_models_library.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/models/library.py tests/unit/test_models_library.py
git commit -m "refactor(models): rename DocumentInfo to EntityInfo

- doc_id -> entity_id
- doc_count -> entity_count in CollectionInfo and LibraryStatus"
```

---

### Task 6: Implement migration logic

**Files:**
- Modify: `src/mbforge/core/migration.py`
- Test: `tests/unit/test_migration.py`

**Interfaces:**
- Consumes: legacy `{library_root}/library.db`, `{library_root}/index/*.db`, `{library_root}/storage/{doc_id}/`
- Produces: new `{library_root}/.mbforge/library.db`, `{library_root}/entities/{entity_id}/`

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from pathlib import Path

from mbforge.core.migration import migrate_library


def test_migrate_legacy_library(tmp_path: Path) -> None:
    # Arrange legacy layout
    (tmp_path / "storage" / "doc-1").mkdir(parents=True)
    (tmp_path / "storage" / "doc-1" / "a.pdf").write_bytes(b"pdf")
    old_db = tmp_path / "library.db"
    conn = sqlite3.connect(str(old_db))
    conn.executescript("""
        CREATE TABLE documents (doc_id TEXT PRIMARY KEY, title TEXT, file_name TEXT,
                                storage_path TEXT, md5 TEXT);
        INSERT INTO documents VALUES ('doc-1', 'A', 'a.pdf', 'doc-1/a.pdf', 'md5');
    """)
    conn.close()

    migrate_library(str(tmp_path))

    assert (tmp_path / "entities" / "doc-1" / "a.pdf").exists()
    new_db = tmp_path / ".mbforge" / "library.db"
    conn = sqlite3.connect(str(new_db))
    try:
        row = conn.execute(
            "SELECT entity_id, storage_path FROM entities WHERE entity_id = ?", ("doc-1",)
        ).fetchone()
        assert row is not None
        assert row[1] == "entities/doc-1/a.pdf"
    finally:
        conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_migration.py::test_migrate_legacy_library -v`
Expected: FAIL (NotImplementedError)

- [ ] **Step 3: Write minimal implementation**

```python
"""Library layout migration — detect and convert legacy directory structures."""

from __future__ import annotations

import sqlite3
import shutil
from pathlib import Path

from ..utils.logger import get_logger

logger = get_logger("mbforge.core.migration")


def detect_legacy_layout(library_root: str | Path) -> bool:
    """Return True if the directory looks like a pre-refactor library."""
    root = Path(library_root)
    return (root / "storage").exists() or (root / "index").exists()


def migrate_library(library_root: str | Path) -> None:
    """Migrate a legacy library layout to the current structure.

    Moves {root}/storage/{doc_id}/ -> {root}/entities/{entity_id}/
    and renames doc_id columns to entity_id in the merged DB.
    """
    root = Path(library_root)
    mbforge_dir = root / ".mbforge"
    mbforge_dir.mkdir(parents=True, exist_ok=True)
    new_db_path = mbforge_dir / "library.db"

    old_library_db = root / "library.db"
    old_kb_db = root / "index" / "knowledge_base.db"
    old_mol_db = root / "index" / "molecules.db"
    storage_dir = root / "storage"
    entities_dir = root / "entities"

    # Move storage -> entities
    if storage_dir.exists():
        entities_dir.mkdir(parents=True, exist_ok=True)
        for subdir in storage_dir.iterdir():
            if subdir.is_dir():
                dest = entities_dir / subdir.name
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.move(str(subdir), str(dest))
                logger.info("Migrated storage %s -> entities %s", subdir.name, dest)
        shutil.rmtree(storage_dir, ignore_errors=True)

    # Attach and merge old databases into new library.db
    conn = sqlite3.connect(str(new_db_path))
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        if old_library_db.exists():
            _merge_db(conn, old_library_db, rename_doc_id=True)
        if old_kb_db.exists():
            _merge_db(conn, old_kb_db, rename_doc_id=True)
        if old_mol_db.exists():
            _merge_db(conn, old_mol_db, rename_doc_id=False)
        conn.commit()
    finally:
        conn.close()

    # Back up old databases
    if old_library_db.exists():
        shutil.move(str(old_library_db), str(mbforge_dir / "library.db.pre-migration"))
    if old_kb_db.exists():
        shutil.move(str(old_kb_db), str(mbforge_dir / "knowledge_base.db.pre-migration"))
    if old_mol_db.exists():
        shutil.move(str(old_mol_db), str(mbforge_dir / "molecules.db.pre-migration"))

    logger.info("Library migration complete for %s", root)


def _merge_db(
    target: sqlite3.Connection, source_path: Path, rename_doc_id: bool
) -> None:
    """Attach source DB and copy tables into target, optionally renaming doc_id."""
    target.execute(f"ATTACH DATABASE ? AS src", (str(source_path),))
    try:
        tables = [
            r[0]
            for r in target.execute(
                "SELECT name FROM src.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        for table in tables:
            cols = [
                r[1]
                for r in target.execute(f"PRAGMA src.table_info({table})")
            ]
            if rename_doc_id and "doc_id" in cols:
                select_cols = ", ".join(
                    f"doc_id AS entity_id" if c == "doc_id" else c for c in cols
                )
            else:
                select_cols = ", ".join(cols)
            target.execute(
                f"INSERT OR IGNORE INTO {table} SELECT {select_cols} FROM src.{table}"
            )
    finally:
        target.execute("DETACH DATABASE src")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/migration.py tests/unit/test_migration.py
git commit -m "feat(core): implement legacy library migration

- Move storage/{doc_id}/ -> entities/{entity_id}/
- Merge library.db, index/knowledge_base.db, index/molecules.db into .mbforge/library.db
- Rename doc_id columns to entity_id during merge
- Back up old DBs in .mbforge/"
```

---

### Task 7: Update pipeline `runner.py`

**Files:**
- Modify: `src/mbforge/pipeline/runner.py`
- Test: existing pipeline tests

**Interfaces:**
- Consumes: `LibraryStore` with `entity_id`, `entities/` directory
- Produces: `PipelineResult.entity_id`, report.json with `entity_id`

- [ ] **Step 1: Write the failing test**

If no existing test covers runner signature, add:

```python
from mbforge.pipeline.runner import run_pipeline


def test_run_pipeline_accepts_library_root(tmp_path) -> None:
    # Minimal smoke: function accepts library_root keyword and entity_id
    # Full pipeline run requires fixtures; this test just checks signature.
    import inspect
    sig = inspect.signature(run_pipeline)
    assert "library_root" in sig.parameters
    assert "entity_id" in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_runner_signature.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/pipeline/runner.py`:

1. Rename `PipelineResult.doc_id` → `PipelineResult.entity_id`.
2. Rename `run_pipeline` parameter `doc_id` → `entity_id` and `project_root` → `library_root`.
3. Rename function parameter `doc_id` to `entity_id` and `project_root` to `library_root`.
4. Update internal references, report payload, and paths from `storage/{doc_id}` to `entities/{entity_id}`.
5. Update `_persist_document` to write to `entities/{entity_id}/pages/`.

Run the following mechanical replacements in `src/mbforge/pipeline/runner.py`:

```bash
sed -i 's/doc_id/entity_id/g; s/project_root/library_root/g; s|storage/|entities/|g' src/mbforge/pipeline/runner.py
```

Then review and fix any over-replacements (e.g., `entity_id_id`). Verify with:

```bash
grep -n "doc_id\|project_root\|storage/" src/mbforge/pipeline/runner.py || echo "clean"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/runner.py tests/unit/pipeline/test_runner_signature.py
git commit -m "refactor(pipeline): runner uses entity_id and library_root

- Rename doc_id -> entity_id and project_root -> library_root
- Persist pages under entities/{entity_id}/pages/"
```

---

### Task 8: Update pipeline `extract_molecules.py` and `persist_molecules.py`

**Files:**
- Modify: `src/mbforge/pipeline/extract_molecules.py`
- Modify: `src/mbforge/pipeline/persist_molecules.py`
- Test: `tests/unit/pipeline/test_persist_molecules.py`

**Interfaces:**
- Consumes: `entity_id`, `library_root`
- Produces: crops at `.mbforge/crops/{entity_id}/`

- [ ] **Step 1: Write the failing test**

```python
def test_persist_molecules_uses_entity_id(tmp_path) -> None:
    from mbforge.pipeline.persist_molecules import persist_molecules
    import inspect
    sig = inspect.signature(persist_molecules)
    assert "entity_id" in sig.parameters
    assert "library_root" in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_persist_molecules.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Run mechanical replacements:

```bash
sed -i 's/doc_id/entity_id/g; s/project_root/library_root/g' src/mbforge/pipeline/extract_molecules.py
sed -i 's/doc_id/entity_id/g; s/project_root/library_root/g' src/mbforge/pipeline/persist_molecules.py
```

Verify `entity_id` is used in `molecule_detections` INSERT and `.mbforge/crops/{entity_id}` path:

```bash
grep -n "entity_id\|crops/" src/mbforge/pipeline/extract_molecules.py src/mbforge/pipeline/persist_molecules.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/test_persist_molecules.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/extract_molecules.py src/mbforge/pipeline/persist_molecules.py tests/unit/pipeline/test_persist_molecules.py
git commit -m "refactor(pipeline): molecule stages use entity_id and library_root"
```

---

### Task 9: Update OpenKB adapter, compiler, indexer, query

**Files:**
- Modify: `src/mbforge/openkb/adapter.py`
- Modify: `src/mbforge/openkb/compiler.py`
- Modify: `src/mbforge/openkb/indexer.py`
- Modify: `src/mbforge/openkb/query.py`
- Test: add/update OpenKB tests

**Interfaces:**
- Consumes: `library_root`, `entity_id`
- Produces: PageIndex at `.mbforge/pageindex/`, wiki at `wiki/summaries/{entity_id}.md`

- [ ] **Step 1: Write the failing test**

```python
def test_openkb_adapter_paths(tmp_path: Path) -> None:
    from mbforge.openkb.adapter import OpenKBAdapter
    adapter = OpenKBAdapter(str(tmp_path))
    assert adapter.pageindex_dir == tmp_path / ".mbforge" / "pageindex"
    assert adapter.wiki_dir == tmp_path / "wiki"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/openkb/test_adapter_paths.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/openkb/adapter.py`:
- Rename `project_root` → `library_root`.
- Set `_pageindex_dir = library_root / ".mbforge" / "pageindex"`.
- Set `_wiki_dir = library_root / "wiki"`.
- Rename `doc_id` parameters → `entity_id`.

Edit `src/mbforge/openkb/compiler.py`:
- Rename `doc_id` → `entity_id`.
- Output path `wiki/summaries/{entity_id}.md`.

Edit `src/mbforge/openkb/indexer.py`:
- Rename `doc_id` → `entity_id`.

Edit `src/mbforge/openkb/query.py`:
- Rename `doc_id` → `entity_id`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/openkb/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/openkb/ tests/unit/openkb/
git commit -m "refactor(openkb): move PageIndex and wiki into library

- PageIndex now lives at .mbforge/pageindex/
- wiki now lives at wiki/
- Rename doc_id -> entity_id, project_root -> library_root"
```

---

### Task 10: Update `knowledge_base.py`

**Files:**
- Modify: `src/mbforge/core/knowledge_base.py`
- Test: update existing tests

**Interfaces:**
- Consumes: `library_root`, `entity_id`
- Produces: reads pages from `entities/{entity_id}/pages/`, reads wiki from `wiki/`

- [ ] **Step 1: Write the failing test**

```python
def test_kb_uses_entity_id(tmp_path: Path) -> None:
    from mbforge.core.knowledge_base import KnowledgeBase
    kb = KnowledgeBase(str(tmp_path))
    # Just verify attribute/method names
    assert hasattr(kb, "get_document_pages")
```

- [ ] **Step 2: Run test to verify it fails**

Run: existing KB tests
Expected: FAIL (signature mismatch)

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/core/knowledge_base.py`:

```bash
sed -i 's/doc_id/entity_id/g; s|storage/|entities/|g; s|\.mbforge/openkb/wiki|wiki|g' src/mbforge/core/knowledge_base.py
```

Verify with:

```bash
grep -n "doc_id\|storage/\|openkb/wiki" src/mbforge/core/knowledge_base.py || echo "clean"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/core/test_knowledge_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/knowledge_base.py tests/unit/core/test_knowledge_base.py
git commit -m "refactor(knowledge_base): use entity_id and new paths"
```

---

### Task 11: Update routers

**Files:**
- Modify: `src/mbforge/routers/library.py`
- Modify: `src/mbforge/routers/documents.py`
- Modify: `src/mbforge/routers/pipeline.py`
- Modify: `src/mbforge/routers/knowledge_base.py`
- Modify: `src/mbforge/routers/detection_cache.py`
- Modify: `src/mbforge/routers/legacy_models.py`
- Modify: `src/mbforge/routers/coref.py`
- Modify: `src/mbforge/routers/pdf.py`
- Modify: `src/mbforge/routers/notes.py`
- Modify: `src/mbforge/routers/agent.py`
- Test: `tests/unit/test_routers_smoke.py`

**Interfaces:**
- Consumes: `LibraryStore` with `entity_id`, merged DB
- Produces: API body/query keys `entity_id`, `library_root`

- [ ] **Step 1: Write the failing test**

Update `tests/unit/test_routers_smoke.py` to use `entity_id` and `library_root` body keys.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_routers_smoke.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Run the following mechanical replacements inside `src/mbforge/routers/`:

```bash
cd src/mbforge/routers
# Rename doc_id -> entity_id in variable names, body keys, and route params
sed -i 's/doc_id/entity_id/g' library.py documents.py pipeline.py knowledge_base.py detection_cache.py legacy_models.py coref.py pdf.py notes.py agent.py
# Rename project_root -> library_root in body keys, query params, and variables
sed -i 's/project_root/library_root/g' pipeline.py knowledge_base.py detection_cache.py legacy_models.py notes.py agent.py
```

Then manually edit `library.py` route path:

```python
@router.get("/entities/{entity_id}/file")
async def library_get_document_file(entity_id: str, library_root: str | None = None) -> FileResponse:
    root = _resolve_library_root({"library_root": library_root} if library_root else None)
    from ..core.library import LibraryStore

    from ..utils.helpers import MBForgeError

    class _DocumentNotFoundError(MBForgeError):
        status_code = 404
        error_code = "document_not_found"

    store = LibraryStore.get(root)
    pdf_path = store.resolve_file(entity_id)
    if pdf_path is None:
        raise _DocumentNotFoundError("Document file not found", detail=f"entity_id={entity_id}")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=Path(pdf_path).name,
    )
```

Verify no `doc_id` or `project_root` remains in `src/mbforge/routers/`:

```bash
grep -R "doc_id\|project_root" src/mbforge/routers/ || echo "clean"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_routers_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/routers/ tests/unit/test_routers_smoke.py
git commit -m "refactor(routers): align API with entity_id and library_root"
```

---

### Task 12: Update agent, sessions, helpers, semantic_cache, file_scanner, molecule models

**Files:**
- Modify: `src/mbforge/agent/tools.py`
- Modify: `src/mbforge/agent/sessions.py`
- Modify: `src/mbforge/utils/helpers.py`
- Modify: `src/mbforge/core/semantic_cache.py`
- Modify: `src/mbforge/core/file_scanner.py`
- Modify: `src/mbforge/models/molecule.py`
- Test: run full backend test suite

**Interfaces:**
- Produces: consistent use of `entity_id` and `library_root` across backend

- [ ] **Step 1: Write the failing test**

Run full test suite to surface remaining failures:

```bash
uv run pytest tests/ -v
```

Expected: multiple FAIL

- [ ] **Step 2: Run test to verify it fails**

(See above)

- [ ] **Step 3: Write minimal implementation**

Run mechanical replacements:

```bash
# agent/tools.py
sed -i 's/doc_id/entity_id/g; s/project_root/library_root/g' src/mbforge/agent/tools.py

# agent/sessions.py
sed -i 's/project_root/library_root/g' src/mbforge/agent/sessions.py

# core/semantic_cache.py
sed -i 's/project_root/library_root/g' src/mbforge/core/semantic_cache.py

# core/file_scanner.py
sed -i 's/doc_id/entity_id/g' src/mbforge/core/file_scanner.py

# models/molecule.py
sed -i 's/project_root/library_root/g' src/mbforge/models/molecule.py
```

Then manually edit `src/mbforge/utils/helpers.py` to remove `project_root`/`projectRoot` fallback in `resolve_root` and `validate_path`. For example, change:

```python
# Before (legacy)
root = body.get("library_root") or body.get("project_root") or config.library_root

# After
root = body.get("library_root") or config.library_root
```

Verify no `doc_id` or `project_root` remains in these files:

```bash
grep -n "doc_id\|project_root" src/mbforge/agent/tools.py src/mbforge/agent/sessions.py src/mbforge/core/semantic_cache.py src/mbforge/core/file_scanner.py src/mbforge/models/molecule.py src/mbforge/utils/helpers.py || echo "clean"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/agent/ src/mbforge/utils/helpers.py src/mbforge/core/semantic_cache.py src/mbforge/core/file_scanner.py src/mbforge/models/molecule.py
git commit -m "refactor(backend): final entity_id/library_root sweep"
```

---

### Task 13: Backend self-review and lint

**Files:**
- All modified backend files

- [ ] **Step 1: Run ruff**

Run: `uv run ruff check src/`
Expected: no errors

- [ ] **Step 2: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Run dev server smoke**

Run: `uv run uvicorn mbforge.app:app --host 127.0.0.1 --port 18792 --timeout-keep-alive 1 &`
Then: `curl http://127.0.0.1:18792/api/v1/library/status`
Expected: HTTP 200

- [ ] **Step 4: Commit**

```bash
git commit -m "chore(backend): lint and verify backend refactor" --allow-empty
```

---

## Self-Review Checklist

- [ ] **Spec coverage:** Every section of `docs/superpowers/specs/2026-07-08-library-root-directory-layout-design.md` maps to at least one task.
- [ ] **Placeholder scan:** No TBD, TODO, "implement later", or vague steps remain.
- [ ] **Type consistency:** `entity_id` is used everywhere; no `doc_id` remains in backend code.
- [ ] **Path consistency:** All backend paths use `entities/`, `.mbforge/library.db`, `.mbforge/pageindex/`, `wiki/`.
- [ ] **Test coverage:** Every task has a test step; full suite passes.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-08-backend-library-root-refactor.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
