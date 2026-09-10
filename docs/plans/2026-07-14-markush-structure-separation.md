# Markush / R-基结构与正式分子分流 — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split pipeline-detected structures into `complete` (main library) vs `scaffold` / `fragment` (new `markush_*` tables) based purely on RDKit dummy-atom signals; no API / UI / migration / mounting changes.

**Architecture:** New pure classifier `pipeline/classify_structure_role.py` writes `properties["structure_role"]`. New `pipeline/persist_markush.py` writes scaffold/fragment rows in same txn as `persist_molecule_candidates`. Schema bumps v5→v6 with two new tables and idempotent migration. `organizer.register_molecules_from_text` skips non-complete. Pipeline report.json gets `structure_role_counts`.

**Tech Stack:** Python 3.12, RDKit, SQLite, pytest. No new deps.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/mbforge/pipeline/classify_structure_role.py` | **NEW** | Pure function: SMILES → `complete`/`scaffold`/`fragment` |
| `src/mbforge/pipeline/persist_markush.py` | **NEW** | Write `markush_scaffolds` / `markush_fragments` rows |
| `src/mbforge/core/database.py` | MODIFY | Schema v5→v6, two tables, migration function |
| `src/mbforge/pipeline/stages/persist_stage.py` | MODIFY | Call classifier, route by role, cover-delete markush, extend compensation |
| `src/mbforge/pipeline/organizer.py` | MODIFY | `register_molecules_from_text` skip non-complete |
| `tests/unit/pipeline/test_classify_structure_role.py` | **NEW** | Classifier unit tests |
| `tests/unit/pipeline/test_persist_markush.py` | **NEW** | Persist routing unit tests |
| `tests/unit/core/test_database.py` | MODIFY | Migration v5→v6 assertion |

No router/UI/router-smoke changes (Phase B).

---

## Task 1: Schema v5→v6 with markush tables + migration

**Files:**
- Modify: `src/mbforge/core/database.py:22,108-191,275-319,466-568`
- Test: `tests/unit/core/test_database.py` (new)

- [ ] **Step 1: Write failing migration test**

Append to `tests/unit/core/test_database.py` (or create if absent):

```python
from mbforge.core.database import DatabaseManager, SCHEMA_VERSION


def test_markush_tables_exist_after_init(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('markush_scaffolds','markush_fragments')"
        ).fetchall()
    names = {r[0] for r in rows}
    assert names == {"markush_scaffolds", "markush_fragments"}


def test_markush_table_indices_exist(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        idx = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_ms_%' OR name LIKE 'idx_mf_%'"
        ).fetchall()
    names = {r[0] for r in idx}
    assert {"idx_ms_doc", "idx_ms_status", "idx_mf_doc", "idx_mf_scaffold", "idx_mf_status"} <= names


def test_schema_version_is_v6(tmp_path):
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        v = conn.execute("SELECT version FROM schema_version").fetchone()[0]
    assert v == SCHEMA_VERSION == 6
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
uv run pytest tests/unit/core/test_database.py -v
```

Expected: FAIL — tables missing, version still 5.

- [ ] **Step 3: Bump schema and add tables**

In `src/mbforge/core/database.py`:

1. Line 22: change `SCHEMA_VERSION = 5` → `SCHEMA_VERSION = 6`.
2. Append the two new tables + indexes to `_MOL_SCHEMA` (before the trailing `CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);`):

```sql
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
```

3. In `_init_db` (line ~304), add `if existing[0] < 6: self._migrate_molecules_v5_to_v6(conn)` before the final `UPDATE schema_version`.

4. Add method after `_migrate_molecules_v4_to_v5`:

```python
def _migrate_molecules_v5_to_v6(self, conn: sqlite3.Connection) -> None:
    """v5 -> v6: add markush_scaffolds and markush_fragments tables.

    The schema is already part of _MOL_SCHEMA so greenfield init creates
    both tables. This migration only runs on legacy DBs; CREATE IF NOT
    EXISTS keeps it idempotent.
    """
    conn.executescript(
        """
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
        """
    )
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/unit/core/test_database.py -v
```

Expected: PASS.

- [ ] **Step 5: Run full core + pipeline tests, expect no regression**

```bash
uv run pytest tests/unit/core tests/unit/pipeline -v
```

Expected: PASS (only the new tests are added; no existing tests touched).

- [ ] **Step 6: Commit**

```bash
git add src/mbforge/core/database.py tests/unit/core/test_database.py
git commit -m "feat(db): add markush_scaffolds and markush_fragments tables (schema v6)"
```

---

## Task 2: Pure classifier `pipeline/classify_structure_role.py`

**Files:**
- Create: `src/mbforge/pipeline/classify_structure_role.py`
- Test: `tests/unit/pipeline/test_classify_structure_role.py` (new)

- [ ] **Step 1: Write failing classifier tests**

Create `tests/unit/pipeline/test_classify_structure_role.py`:

```python
from mbforge.pipeline.classify_structure_role import (
    classify_structure_role,
    DUMMY_SYMBOLS,
    FRAGMENT_MAX_HEAVY,
    FRAGMENT_SINGLE_ATTACH_BONUS,
)
from mbforge.pipeline.normalize import NormalizedMolecule


def _nm(esmiles: str) -> NormalizedMolecule:
    return NormalizedMolecule(
        canonical_smiles=esmiles, esmiles=esmiles, name=""
    )


def test_classify_complete_no_dummy():
    mol = _nm("CCO")
    assert classify_structure_role(mol) == "complete"


def test_classify_complete_aromatic():
    mol = _nm("c1ccccc1OC")
    assert classify_structure_role(mol) == "complete"


def test_classify_fragment_single_attach_small():
    # A1 thiazole + single *, well below fragment max
    mol = _nm("*c1cscn1")
    assert classify_structure_role(mol) == "fragment"


def test_classify_fragment_single_attach_bonus():
    # Larger single-* chain (24 heavy atoms) → fragment via bonus
    chain = "*" + "C" * 23
    mol = _nm(chain)
    assert classify_structure_role(mol) == "fragment"


def test_classify_scaffold_multi_dummy_medium():
    # Two dummies + heavy ~20 → not fragment (multi attach + heavy>18)
    smiles = "*c1ccc(*)cc1" + "C" * 13
    mol = _nm(smiles)
    assert classify_structure_role(mol) == "scaffold"


def test_classify_scaffold_multi_dummy_large():
    # Two dummies + many heavy → scaffold (not fragment by bonus either)
    smiles = "*c1ccc(*)cc1" + "C" * 30
    mol = _nm(smiles)
    assert classify_structure_role(mol) == "scaffold"


def test_classify_rejected_passthrough():
    mol = NormalizedMolecule(
        canonical_smiles="bogus", esmiles="bogus", name="",
        status="rejected",
    )
    assert classify_structure_role(mol) == "complete"  # rejected handled separately


def test_classify_invalid_smiles_falls_back_to_fragment():
    mol = _nm("@@@")
    assert classify_structure_role(mol) == "fragment"


def test_classify_writes_structure_role_property():
    mol = _nm("CCO")
    classify_structure_role(mol)
    assert mol.properties["structure_role"] == "complete"


def test_constants_exposed():
    assert "*" in DUMMY_SYMBOLS
    assert FRAGMENT_MAX_HEAVY == 18
    assert FRAGMENT_SINGLE_ATTACH_BONUS == 6
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
uv run pytest tests/unit/pipeline/test_classify_structure_role.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement classifier**

Create `src/mbforge/pipeline/classify_structure_role.py`:

```python
"""Classify normalized molecules into complete / scaffold / fragment.

Pure functions only — no DB / IO. Called from
``pipeline.stages.persist_stage`` right before persistence so that role is
stable across all downstream writers (molecules / markush tables /
report.json).

Rules (Phase A, see the companion design in this directory §4):

* ``rejected`` molecules are skipped by the caller; this module does not
  re-classify them.
* ``fragment``: has dummy atom AND heavy_atoms <= 18, OR single attachment
  AND heavy_atoms <= 24.
* ``scaffold``: has dummy atom but not fragment.
* ``complete``: no dummy atom.
* Any RDKit error or empty mol → ``fragment`` (aggressive fallback).
"""
from __future__ import annotations

from rdkit import Chem, RDLogger

from ..utils.logger import get_logger
from .normalize import NormalizedMolecule

logger = get_logger("mbforge.pipeline.classify")

# Silence RDKit's stderr noise from malformed SMILES — we already swallow
# exceptions below.
RDLogger.DisableLog("rdApp.*")

DUMMY_SYMBOLS = {"*"}
FRAGMENT_MAX_HEAVY = 18
FRAGMENT_SINGLE_ATTACH_BONUS = 6
EXTENDED_MAX_HEAVY = FRAGMENT_MAX_HEAVY + FRAGMENT_SINGLE_ATTACH_BONUS  # 24

PROPERTY_KEY = "structure_role"
VALID_ROLES = {"complete", "scaffold", "fragment"}


def _has_dummy_and_counts(smiles: str) -> tuple[bool, int, int]:
    """Return ``(has_dummy, attachment_count, heavy_atoms)``.

    Returns ``(False, 0, 0)`` if RDKit cannot parse the SMILES.
    """
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception as exc:  # noqa: BLE001
        logger.debug("RDKit parse error for %r: %s", smiles, exc)
        return False, 0, 0
    if mol is None:
        return False, 0, 0
    heavy = mol.GetNumHeavyAtoms()
    dummies = sum(
        1 for a in mol.GetAtoms() if a.GetSymbol() in DUMMY_SYMBOLS or a.GetAtomicNum() == 0
    )
    return dummies > 0, dummies, heavy


def classify_structure_role(mol: NormalizedMolecule) -> str:
    """Return the role string and write it onto ``mol.properties``.

    Rejected molecules keep status as-is and yield ``"complete"`` here;
    caller must check ``mol.status`` separately before routing.
    """
    role = _classify(mol.canonical_smiles or mol.esmiles)
    mol.properties[PROPERTY_KEY] = role
    return role


def _classify(smiles: str) -> str:
    has_dummy, attachment_count, heavy = _has_dummy_and_counts(smiles)
    if not has_dummy:
        if smiles:
            return "complete"
        # Empty / unparseable → aggressive fallback to fragment
        logger.warning("Unparseable SMILES in classify; defaulting to fragment")
        return "fragment"

    # fragment: small OR single attachment with extended budget
    if heavy <= FRAGMENT_MAX_HEAVY:
        return "fragment"
    if attachment_count == 1 and heavy <= EXTENDED_MAX_HEAVY:
        return "fragment"
    return "scaffold"
```

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/unit/pipeline/test_classify_structure_role.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/classify_structure_role.py tests/unit/pipeline/test_classify_structure_role.py
git commit -m "feat(pipeline): add structure-role classifier (complete/scaffold/fragment)"
```

---

## Task 3: Markush persist module

**Files:**
- Create: `src/mbforge/pipeline/persist_markush.py`
- Test: `tests/unit/pipeline/test_persist_markush.py` (new)

- [ ] **Step 1: Write failing persist tests**

Create `tests/unit/pipeline/test_persist_markush.py`:

```python
import sqlite3

import pytest

from mbforge.core.database import DatabaseManager
from mbforge.pipeline.normalize import NormalizedMolecule, DetectionSource
from mbforge.pipeline.persist_markush import (
    persist_markush_scaffolds,
    persist_markush_fragments,
)


def _nm(esmiles: str, status: str = "pending") -> NormalizedMolecule:
    return NormalizedMolecule(
        canonical_smiles=esmiles,
        esmiles=esmiles,
        name="",
        detections=[DetectionSource(source="image", page=1, bbox=(0, 0, 1, 1),
                                     image_path="crop.png", confidence=0.9)],
        status=status,
    )


@pytest.fixture
def db(tmp_path) -> DatabaseManager:
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    return db


def test_persist_scaffold_writes_row(db):
    scaffold = _nm("*c1ccc(*)cc1")
    scaffold.properties["structure_role"] = "scaffold"
    scaffold.formula_label = "Formula I"
    with db.mol_conn() as conn:
        persist_markush_scaffolds("doc-1", [scaffold], conn=conn)
        rows = conn.execute(
            "SELECT scaffold_id, doc_id, smiles, formula_label "
            "FROM markush_scaffolds"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc-1"
    assert rows[0]["smiles"] == "*c1ccc(*)cc1"
    assert rows[0]["formula_label"] == "Formula I"


def test_persist_fragment_writes_row(db):
    frag = _nm("*c1cscn1")
    frag.properties["structure_role"] = "fragment"
    frag.label = "A1"
    with db.mol_conn() as conn:
        persist_markush_fragments("doc-1", [frag], conn=conn)
        rows = conn.execute(
            "SELECT fragment_id, doc_id, smiles, label, scaffold_id "
            "FROM markush_fragments"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc-1"
    assert rows[0]["smiles"] == "*c1cscn1"
    assert rows[0]["label"] == "A1"
    assert rows[0]["scaffold_id"] is None  # Phase A: no mounting


def test_persist_skips_non_matching_role(db):
    scaffold = _nm("*c1ccc(*)cc1")
    scaffold.properties["structure_role"] = "complete"  # misclassified
    with db.mol_conn() as conn:
        persist_markush_scaffolds("doc-1", [scaffold], conn=conn)
        rows = conn.execute("SELECT COUNT(*) AS cnt FROM markush_scaffolds").fetchall()
    assert rows[0][0] == 0


def test_persist_skips_rejected(db):
    frag = _nm("*c1cscn1")
    frag.status = "rejected"
    frag.properties["structure_role"] = "fragment"
    with db.mol_conn() as conn:
        persist_markush_fragments("doc-1", [frag], conn=conn)
        rows = conn.execute("SELECT COUNT(*) AS cnt FROM markush_fragments").fetchall()
    assert rows[0][0] == 0


def test_persist_requires_conn():
    with pytest.raises(ValueError):
        persist_markush_scaffolds("doc-1", [], conn=None)
    with pytest.raises(ValueError):
        persist_markush_fragments("doc-1", [], conn=None)
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
uv run pytest tests/unit/pipeline/test_persist_markush.py -v
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement persist module**

Create `src/mbforge/pipeline/persist_markush.py`:

```python
"""Persist scaffold / fragment candidates to markush_* tables.

Phase A behavior:

* Only writes rows whose ``NormalizedMolecule.properties["structure_role"]``
  matches the table (``"scaffold"`` or ``"fragment"``). Mismatched roles are
  skipped — defensive guard against call-site bugs.
* Skips ``rejected`` molecules.
* Fragment ``scaffold_id`` is always ``NULL`` (no mounting in Phase A).
* Caller owns the transaction (function only takes a live ``conn``).
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Iterable

from ..utils.logger import get_logger
from .normalize import NormalizedMolecule

logger = get_logger("mbforge.pipeline.persist_markush")

ROLE_SCAFFOLD = "scaffold"
ROLE_FRAGMENT = "fragment"


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def _primary(mol: NormalizedMolecule):
    return mol.detections[0] if mol.detections else None


def _row_values(mol: NormalizedMolecule, doc_id: str) -> tuple | None:
    primary = _primary(mol)
    if primary is None:
        logger.warning(
            "Skipping markush row with no detections for %s (%s)",
            doc_id, mol.esmiles,
        )
        return None
    bbox = primary.bbox
    return (
        mol.canonical_smiles or mol.esmiles,
        mol.esmiles,
        primary.page,
        bbox[0] if bbox else None,
        bbox[1] if bbox else None,
        bbox[2] if bbox else None,
        bbox[3] if bbox else None,
        primary.image_path,
        primary.confidence,
    )


def persist_markush_scaffolds(
    doc_id: str,
    candidates: Iterable[NormalizedMolecule],
    *,
    conn: sqlite3.Connection | None,
) -> int:
    """Write scaffold rows for candidates tagged ``structure_role="scaffold"``.

    Returns the number of rows written.
    """
    if conn is None:
        raise ValueError("persist_markush_scaffolds requires an open conn")
    written = 0
    for mol in candidates:
        if mol.status == "rejected":
            continue
        if mol.properties.get("structure_role") != ROLE_SCAFFOLD:
            continue
        values = _row_values(mol, doc_id)
        if values is None:
            continue
        smi, esmi, page, x0, y0, x1, y1, crop, conf = values
        properties = dict(mol.properties)
        conn.execute(
            """
            INSERT INTO markush_scaffolds
                (scaffold_id, doc_id, formula_label,
                 smiles, esmiles, page,
                 bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 crop_relpath, confidence, properties)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id(),
                doc_id,
                mol.formula_label if hasattr(mol, "formula_label") else "",
                smi,
                esmi,
                page,
                x0, y0, x1, y1,
                crop,
                conf,
                _serialize_properties(properties),
            ),
        )
        written += 1
    return written


def persist_markush_fragments(
    doc_id: str,
    candidates: Iterable[NormalizedMolecule],
    *,
    conn: sqlite3.Connection | None,
) -> int:
    """Write fragment rows for candidates tagged ``structure_role="fragment"``.

    Phase A always stores ``scaffold_id = NULL`` (no mounting).
    """
    if conn is None:
        raise ValueError("persist_markush_fragments requires an open conn")
    written = 0
    for mol in candidates:
        if mol.status == "rejected":
            continue
        if mol.properties.get("structure_role") != ROLE_FRAGMENT:
            continue
        values = _row_values(mol, doc_id)
        if values is None:
            continue
        smi, esmi, page, x0, y0, x1, y1, crop, conf = values
        properties = dict(mol.properties)
        conn.execute(
            """
            INSERT INTO markush_fragments
                (fragment_id, scaffold_id, doc_id, label,
                 smiles, esmiles, page,
                 bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                 crop_relpath, confidence, properties)
            VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _new_id(),
                doc_id,
                mol.label if hasattr(mol, "label") else "",
                smi,
                esmi,
                page,
                x0, y0, x1, y1,
                crop,
                conf,
                _serialize_properties(properties),
            ),
        )
        written += 1
    return written


def _serialize_properties(properties: dict) -> str:
    import json
    return json.dumps(properties, ensure_ascii=False, default=str)


def delete_markush_for_doc(doc_id: str, *, conn: sqlite3.Connection) -> None:
    """Remove markush rows for a document (used for cover-overwrite)."""
    conn.execute("DELETE FROM markush_scaffolds WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM markush_fragments WHERE doc_id = ?", (doc_id,))
```

Note: `NormalizedMolecule` currently has no `formula_label` / `label` field. The `hasattr` guards make this forward-compatible; if those fields are absent, empty string is stored.

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/unit/pipeline/test_persist_markush.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/persist_markush.py tests/unit/pipeline/test_persist_markush.py
git commit -m "feat(pipeline): persist_markush scaffolds/fragments writer"
```

---

## Task 4: Wire classifier + routing into `PersistStage`

**Files:**
- Modify: `src/mbforge/pipeline/stages/persist_stage.py:106-145,199-230`
- Test: existing `tests/unit/pipeline/test_stages.py` must still pass

- [ ] **Step 1: Write failing routing test**

Append to `tests/unit/pipeline/test_stages.py`:

```python
class TestPersistStageRoutesByRole:
    """Persist stage must route by structure_role and report counts."""

    def test_only_complete_enters_molecules(self, tmp_path: Path) -> None:
        from mbforge.pipeline.normalize import NormalizedMolecule, DetectionSource
        from mbforge.pipeline.classify_structure_role import classify_structure_role

        db = DatabaseManager.get(str(tmp_path))
        db.initialize()

        complete = NormalizedMolecule(
            canonical_smiles="CCO", esmiles="CCO", name="ethanol",
            detections=[DetectionSource(source="image", page=1,
                                         bbox=(0, 0, 1, 1),
                                         image_path="a.png", confidence=0.9)],
            status="pending",
        )
        scaffold = NormalizedMolecule(
            canonical_smiles="*c1ccc(*)cc1", esmiles="*c1ccc(*)cc1", name="Formula I",
            detections=[DetectionSource(source="image", page=1,
                                         bbox=(0, 0, 1, 1),
                                         image_path="b.png", confidence=0.8)],
            status="pending",
        )
        fragment = NormalizedMolecule(
            canonical_smiles="*c1cscn1", esmiles="*c1cscn1", name="A1",
            detections=[DetectionSource(source="image", page=1,
                                         bbox=(0, 0, 1, 1),
                                         image_path="c.png", confidence=0.7)],
            status="pending",
        )
        for m in (complete, scaffold, fragment):
            classify_structure_role(m)

        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="doc-routing",
            candidates=[complete, scaffold, fragment],
            extracted=MagicMock(page_count=1, pages=[]),
            document_md_path=tmp_path / "document.md",
        )
        (tmp_path / "document.md").write_text("# Doc", encoding="utf-8")
        ctx.molecule_stats = {"molecule_count": 1, "rejected_count": 0,
                              "sources": ["image"], "pending_review_count": 1}

        result = PersistStage().execute(ctx)
        assert result.status == "success", result.message

        # Only ethanol in molecules table
        mols = db.execute(
            "SELECT mol_id FROM molecules WHERE mol_id != ''",
            db="mol",
        )
        assert {r["mol_id"] for r in mols} == {"CCO"}

        # Scaffold and fragment in markush tables
        scaffolds = db.execute(
            "SELECT smiles FROM markush_scaffolds WHERE doc_id = ?",
            ("doc-routing",), db="mol",
        )
        assert {r["smiles"] for r in scaffolds} == {"*c1ccc(*)cc1"}
        fragments = db.execute(
            "SELECT smiles FROM markush_fragments WHERE doc_id = ?",
            ("doc-routing",), db="mol",
        )
        assert {r["smiles"] for r in fragments} == {"*c1cscn1"}

        # report.json contains structure_role_counts
        report = json.loads(
            (tmp_path / "storage" / "doc-routing" / "report.json").read_text()
        )
        assert report["structure_role_counts"] == {
            "complete": 1, "scaffold": 1, "fragment": 1,
        }

    def test_compensate_removes_markush_rows(self, tmp_path: Path) -> None:
        db = DatabaseManager.get(str(tmp_path))
        db.initialize()

        scaffold = NormalizedMolecule(
            canonical_smiles="*c1ccc(*)cc1", esmiles="*c1ccc(*)cc1", name="",
            detections=[DetectionSource(source="image", page=1,
                                         bbox=(0, 0, 1, 1),
                                         image_path="b.png", confidence=0.8)],
            status="pending",
        )
        from mbforge.pipeline.classify_structure_role import classify_structure_role
        classify_structure_role(scaffold)

        # Pre-seed via failed stage path: simulate successful molecules+markush
        # write, then a failed _persist_document, and assert compensation
        # cleans BOTH molecule evidence AND markush rows.
        with db.mol_conn() as conn:
            conn.execute(
                "INSERT INTO markush_scaffolds "
                "(scaffold_id, doc_id, smiles) VALUES (?, ?, ?)",
                ("sx1", "doc-fail", "*c1ccc(*)cc1"),
            )
            conn.execute(
                "INSERT INTO markush_fragments "
                "(fragment_id, doc_id, smiles) VALUES (?, ?, ?)",
                ("fx1", "doc-fail", "*c1cscn1"),
            )

        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="doc-fail",
            candidates=[],
            extracted=MagicMock(page_count=1, pages=[]),
            document_md_path=tmp_path / "document.md",
        )
        stage = PersistStage()
        stage._persist_document = lambda _ctx: (_ for _ in ()).throw(
            OSError("disk full")
        )
        result = stage.execute(ctx)
        assert result.status == "error"
        assert (
            db.execute(
                "SELECT COUNT(*) AS cnt FROM markush_scaffolds WHERE doc_id = ?",
                ("doc-fail",), db="mol",
            )[0]["cnt"]
            == 0
        )
        assert (
            db.execute(
                "SELECT COUNT(*) AS cnt FROM markush_fragments WHERE doc_id = ?",
                ("doc-fail",), db="mol",
            )[0]["cnt"]
            == 0
        )
```

Add `import json` to top of `test_stages.py`.

- [ ] **Step 2: Run new tests, expect FAIL**

```bash
uv run pytest tests/unit/pipeline/test_stages.py::TestPersistStageRoutesByRole -v
```

Expected: FAIL — routing does not yet split.

- [ ] **Step 3: Wire classifier + routing into `persist_stage.py`**

In `src/mbforge/pipeline/stages/persist_stage.py`:

1. Replace `_persist_molecules_and_links` body (lines 106-145) with:

```python
    def _persist_molecules_and_links(self, ctx: PipelineContext) -> None:
        """Persist molecules + markush + text links in single cross-DB txn.

        Phase A routing: classify each candidate into
        ``complete`` / ``scaffold`` / ``fragment`` via
        :mod:`mbforge.pipeline.classify_structure_role`, then write:

        * complete → existing ``molecules`` + ``evidence`` +
          ``molecule_detections`` + ``text_molecule_links`` (unchanged).
        * scaffold → ``markush_scaffolds``.
        * fragment → ``markush_fragments`` (``scaffold_id = NULL``).

        Cover-overwrite: any prior markush rows for this ``doc_id`` are
        deleted at the start of the txn so a re-run replaces cleanly.
        """
        if not ctx.candidates:
            logger.info("No molecules to persist for %s", ctx.doc_id)
            return

        from ..classify_structure_role import classify_structure_role
        from ..persist_markush import (
            delete_markush_for_doc,
            persist_markush_fragments,
            persist_markush_scaffolds,
        )
        from ..persist_molecules import persist_molecule_candidates

        # Classify every candidate once — writes onto properties.
        for c in ctx.candidates:
            classify_structure_role(c)

        db = DatabaseManager.get(str(ctx.library_root))

        # Counts for the pipeline report.
        role_counts = {"complete": 0, "scaffold": 0, "fragment": 0}
        for c in ctx.candidates:
            if c.status == "rejected":
                continue
            role = c.properties.get("structure_role")
            if role in role_counts:
                role_counts[role] += 1
        ctx.structure_role_counts = role_counts

        complete_candidates = [
            c for c in ctx.candidates
            if c.status != "rejected"
            and c.properties.get("structure_role") == "complete"
        ]
        scaffold_candidates = [
            c for c in ctx.candidates
            if c.status != "rejected"
            and c.properties.get("structure_role") == "scaffold"
        ]
        fragment_candidates = [
            c for c in ctx.candidates
            if c.status != "rejected"
            and c.properties.get("structure_role") == "fragment"
        ]

        def _register_links_in_txn(mol_conn: Any) -> None:
            """Register text links inside transaction (only complete roles)."""
            if not complete_candidates or not ctx.final_md_path:
                return
            from ..organizer import register_molecules_from_text

            register_molecules_from_text(
                str(ctx.final_md_path),
                complete_candidates,
                ctx.doc_id,
                str(ctx.library_root),
                conn=mol_conn,
            )

        with db.transaction() as (_kb_conn, mol_conn):
            # Cover-overwrite markush rows for this doc.
            delete_markush_for_doc(ctx.doc_id, conn=mol_conn)

            if complete_candidates:
                persist_molecule_candidates(
                    str(ctx.library_root),
                    ctx.doc_id,
                    complete_candidates,
                    conn=mol_conn,
                    activity_records=ctx.activity_records,
                )
            persist_markush_scaffolds(
                ctx.doc_id, scaffold_candidates, conn=mol_conn
            )
            persist_markush_fragments(
                ctx.doc_id, fragment_candidates, conn=mol_conn
            )
            _register_links_in_txn(mol_conn)

        logger.info(
            "Persisted %s for %s",
            role_counts,
            ctx.doc_id,
        )
```

2. Update `_persist_document` report dict (around line 162-179) to include the new field. After `"molecule_sources": ...`:

```python
            "structure_role_counts": getattr(ctx, "structure_role_counts", {}),
```

3. Extend `_compensate_molecule_persistence` (around line 199-230) — after the `text_molecule_links` delete, add:

```python
            db.execute(
                "DELETE FROM markush_scaffolds WHERE doc_id = ?",
                (ctx.doc_id,),
                db="mol",
            )
            db.execute(
                "DELETE FROM markush_fragments WHERE doc_id = ?",
                (ctx.doc_id,),
                db="mol",
            )
```

- [ ] **Step 4: Run new tests, expect PASS**

```bash
uv run pytest tests/unit/pipeline/test_stages.py -v
```

Expected: PASS — both new tests + existing tests.

- [ ] **Step 5: Run full pipeline test suite**

```bash
uv run pytest tests/unit/pipeline -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mbforge/pipeline/stages/persist_stage.py tests/unit/pipeline/test_stages.py
git commit -m "feat(pipeline): persist stage routes by structure_role + cover-overwrites markush"
```

---

## Task 5: `register_molecules_from_text` skips non-complete

**Files:**
- Modify: `src/mbforge/pipeline/organizer.py:686-690`
- Test: extend `tests/unit/pipeline/test_organizer.py`

- [ ] **Step 1: Write failing test**

Append to `tests/unit/pipeline/test_organizer.py`:

```python
def test_register_molecules_from_text_skips_non_complete(tmp_path):
    """register_molecules_from_text must skip scaffold/fragment molecules."""
    from mbforge.core.database import DatabaseManager
    from mbforge.pipeline.classify_structure_role import classify_structure_role
    from mbforge.pipeline.normalize import NormalizedMolecule, DetectionSource
    from mbforge.pipeline.organizer import register_molecules_from_text

    db = DatabaseManager.get(str(tmp_path))
    db.initialize()

    md_path = tmp_path / "fine.md"
    md_path.write_text(
        "Some text.\n\n```esmiles\nCCO\n```\n\nMore text.\n\n"
        "```esmiles\n*c1ccc(*)cc1\n```\n\nEnd.\n",
        encoding="utf-8",
    )

    complete = NormalizedMolecule(
        canonical_smiles="CCO", esmiles="CCO", name="ethanol",
        detections=[DetectionSource(source="image", page=1)],
        status="pending",
    )
    scaffold = NormalizedMolecule(
        canonical_smiles="*c1ccc(*)cc1", esmiles="*c1ccc(*)cc1", name="Formula I",
        detections=[DetectionSource(source="image", page=1)],
        status="pending",
    )
    fragment = NormalizedMolecule(
        canonical_smiles="*c1cscn1", esmiles="*c1cscn1", name="A1",
        detections=[DetectionSource(source="image", page=1)],
        status="pending",
    )
    for m in (complete, scaffold, fragment):
        classify_structure_role(m)

    register_molecules_from_text(
        str(md_path),
        [complete, scaffold, fragment],
        "doc-skip",
        str(tmp_path),
    )

    links = db.execute(
        "SELECT mol_id FROM text_molecule_links WHERE doc_id = ?",
        ("doc-skip",), db="mol",
    )
    assert {r["mol_id"] for r in links} == {"CCO"}
    # Scaffold/fragment molecules must NOT exist as text links.
```

- [ ] **Step 2: Run test, expect FAIL**

```bash
uv run pytest tests/unit/pipeline/test_organizer.py -v -k "skips_non_complete"
```

Expected: FAIL — organizer writes all.

- [ ] **Step 3: Add skip in `register_molecules_from_text`**

In `src/mbforge/pipeline/organizer.py`, inside `_do_inserts` (line 685-686), add a guard after the `status == "rejected"` check:

```python
        for mol in molecules:
            if mol.status == "rejected":
                continue
            # Phase A: only persist text links for complete structures.
            # Scaffold/fragment rows live in markush_* tables, not molecules.
            if mol.properties.get("structure_role") not in (None, "complete"):
                continue
```

(Note: `None` keeps legacy callers working when the caller has not run the classifier yet — fallback to "complete" semantics preserves current behavior.)

- [ ] **Step 4: Run test, expect PASS**

```bash
uv run pytest tests/unit/pipeline/test_organizer.py -v
```

Expected: PASS — all tests including the new one.

- [ ] **Step 5: Run full pipeline + organizer tests**

```bash
uv run pytest tests/unit/pipeline -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/mbforge/pipeline/organizer.py tests/unit/pipeline/test_organizer.py
git commit -m "feat(pipeline): register_molecules_from_text skips non-complete roles"
```

---

## Task 6: Verify end-to-end + cross-DB transaction rollback

**Files:**
- Test: `tests/unit/pipeline/test_stages.py` (one extra scenario)

- [ ] **Step 1: Add integration-style test for atomicity**

Append to `tests/unit/pipeline/test_stages.py`:

```python
class TestPersistStageAtomicity:
    """If any persist step raises, the txn must roll back markush + molecules."""

    def test_markush_write_failure_rolls_back(self, tmp_path: Path) -> None:
        db = DatabaseManager.get(str(tmp_path))
        db.initialize()

        scaffold = NormalizedMolecule(
            canonical_smiles="*c1ccc(*)cc1", esmiles="*c1ccc(*)cc1", name="",
            detections=[DetectionSource(source="image", page=1,
                                         bbox=(0, 0, 1, 1),
                                         image_path="b.png", confidence=0.8)],
            status="pending",
        )
        from mbforge.pipeline.classify_structure_role import classify_structure_role
        classify_structure_role(scaffold)

        ctx = PipelineContext(
            pdf_path=tmp_path / "x.pdf",
            library_root=tmp_path,
            doc_id="doc-rollback",
            candidates=[scaffold],
            extracted=MagicMock(page_count=1, pages=[]),
            document_md_path=tmp_path / "document.md",
        )
        (tmp_path / "document.md").write_text("# Doc", encoding="utf-8")
        ctx.molecule_stats = {"molecule_count": 0, "rejected_count": 0,
                              "sources": [], "pending_review_count": 0}

        # Force a failure in persist_markush_scaffolds to test rollback.
        with patch(
            "mbforge.pipeline.persist_markush.persist_markush_scaffolds",
            side_effect=RuntimeError("simulated"),
        ):
            with pytest.raises(RuntimeError, match="simulated"):
                PersistStage()._persist_molecules_and_links(ctx)

        # No markush rows for this doc_id
        scaffolds = db.execute(
            "SELECT COUNT(*) AS cnt FROM markush_scaffolds WHERE doc_id = ?",
            ("doc-rollback",), db="mol",
        )
        assert scaffolds[0]["cnt"] == 0
```

- [ ] **Step 2: Run test, expect PASS**

```bash
uv run pytest tests/unit/pipeline/test_stages.py::TestPersistStageAtomicity -v
```

Expected: PASS (cross-DB transaction already wraps via `db.transaction()`).

- [ ] **Step 3: Run full unit test suite**

```bash
uv run pytest tests/unit -v
```

Expected: PASS.

- [ ] **Step 4: Final commit (atomic-merge per CLAUDE.md convention)**

Per CLAUDE.md "Commit Granularity — 一主题 = 一 commit", all five commits above (Tasks 1-5) together implement one feature (markush separation). Do **not** squash them — each task is independently revertable. The atomicity test in Task 6 rides along with Task 4 since it tests the same code surface. No separate commit needed.

- [ ] **Step 5: Manual smoke (optional but recommended)**

In a sample library root:

```bash
uv run python -c "
from mbforge.core.database import DatabaseManager
db = DatabaseManager.get('~/MBForge')
db.initialize()
print('markush_scaffolds:', db.execute('SELECT COUNT(*) AS cnt FROM markush_scaffolds', db='mol')[0]['cnt'])
print('markush_fragments:', db.execute('SELECT COUNT(*) AS cnt FROM markush_fragments', db='mol')[0]['cnt'])
print('schema version:', db.execute('SELECT version FROM schema_version', db='mol')[0]['version'])
"
```

Expected: schema_version == 6; tables created (counts may be 0 on fresh DB).

---

## Self-Review Checklist

- [x] Spec §2 success criteria covered:
  - 主库无 scaffold/fragment → Task 4 routing.
  - `markush_scaffolds` / `markush_fragments` 有记录, scaffold_id 空 → Task 3 + Task 4 tests.
  - `pytest` 单元测试通过 → Tasks 1-5 each step has run-tests.
  - report.json 含 `structure_role_counts` → Task 4 + Task 5.
- [x] No placeholders / TBD / "implement later".
- [x] Type consistency: `properties["structure_role"]` defined in Task 2, used in Task 3-5.
- [x] Constant `FRAGMENT_MAX_HEAVY = 18`, `FRAGMENT_SINGLE_ATTACH_BONUS = 6` match design spec §4.1.
- [x] ID format `uuid4().hex[:16]` matches design spec §5.1.
- [x] Schema migration function name `_migrate_molecules_v5_to_v6` matches spec §5.2.
- [x] `delete_markush_for_doc` cover-overwrite + compensation both spec'd in §6.3.
- [x] `structure_role_counts` field name fixed in §6.4.
- [x] `organizer` skip via `properties["structure_role"]` not complete field — non-breaking for legacy callers (None → treat as complete).

---

## Out of Scope (Phase B — explicitly NOT in this plan)

- `/api/v1/markush` router + promote/demote endpoints.
- fragment → scaffold auto-mounting.
- Markush list UI.
- Historical library migration script.
- router smoke / openapi snapshot updates.
- Evidence table `role` column changes (kept as `'detected'`).
- `molecules.role` column (intentionally not added per spec §5.2).
