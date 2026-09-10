# Phase 1: Molecule Extraction + Review Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect MolDetv2 + MolScribe to the document pipeline, extract molecules from PDF images and text, normalize/deduplicate them, persist them as reviewable candidates, and provide a minimal frontend to confirm/reject/edit them.

**Architecture:** Extend `pipeline/runner.py` with three new pipeline modules (`extract_molecules`, `normalize`, `persist_molecules`). Candidates are stored in the existing `molecule_detections` table with `status='pending'`. A review API moves confirmed candidates into the `molecules` table. The React frontend gets a minimal review panel.

**Tech Stack:** Python 3.11, FastAPI, RDKit, PyMuPDF, PIL, SQLite, React/TS

---

## File Structure

| File | Responsibility |
|---|---|
| `src/mbforge/pipeline/extract_molecules.py` | Extract molecules from PDF images (MolDet+MolScribe) and from text (SMILES regex) |
| `src/mbforge/pipeline/normalize.py` | Canonicalize SMILES, validate with RDKit, deduplicate candidates |
| `src/mbforge/pipeline/persist_molecules.py` | Persist candidates to `molecule_detections` table |
| `src/mbforge/core/database.py` | Extend `molecules` schema with review fields |
| `src/mbforge/pipeline/runner.py` | Wire extraction/normalization/persistence into the pipeline |
| `src/mbforge/routers/molecule.py` | Add review endpoint |
| `frontend/src/api/http/molecule.ts` | Add review API wrapper |
| `frontend/src/components/molecule/MoleculeReviewPanel.tsx` | Minimal review UI |
| `tests/unit/pipeline/test_extract_molecules.py` | Unit tests for extraction/normalization/persistence |
| `tests/integration/test_molecule_review.py` | Integration test for review flow |

---

## Task 1: Extend molecules schema for review workflow

**Files:**
- Modify: `src/mbforge/core/database.py`
- Test: `tests/unit/core/test_database_schema.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/core/test_database_schema.py`:

```python
from pathlib import Path
from mbforge.core.database import DatabaseManager


def test_molecules_table_has_review_columns(tmp_path: Path) -> None:
    db = DatabaseManager(str(tmp_path))
    db.initialize()
    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT name FROM pragma_table_info('molecules') WHERE name IN (?, ?, ?)",
            ("canonical_smiles", "reviewed_at", "review_status"),
        ).fetchall()
        names = {r["name"] for r in row}
    assert names == {"canonical_smiles", "reviewed_at", "review_status"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/core/test_database_schema.py -v
```

Expected: FAIL with `AssertionError` because columns don't exist.

- [ ] **Step 3: Modify database schema**

In `src/mbforge/core/database.py`, update `_MOL_SCHEMA` to add review columns to the `molecules` table definition:

```python
_MOL_SCHEMA = """
CREATE TABLE IF NOT EXISTS molecules (
    mol_id TEXT PRIMARY KEY,
    smiles TEXT NOT NULL,
    canonical_smiles TEXT,
    esmiles TEXT,
    name TEXT DEFAULT '',
    source_doc TEXT,
    activity REAL,
    activity_type TEXT,
    units TEXT,
    source_type TEXT DEFAULT 'manual',
    status TEXT DEFAULT 'active',
    review_status TEXT DEFAULT 'pending',
    reviewed_at TEXT,
    properties TEXT DEFAULT '{}',
    labels TEXT DEFAULT '[]',
    semantic_tags TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    fingerprint BLOB,
    created_at TEXT DEFAULT (datetime('now'))
);
...
"""
```

Also bump `SCHEMA_VERSION` from 2 to 3 and add a simple migration path in `_init_db`:

```python
if versioned:
    existing = conn.execute("SELECT version FROM schema_version").fetchone()
    if existing is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif existing["version"] < 3:
        # Migration: add review columns if they don't exist
        conn.execute("ALTER TABLE molecules ADD COLUMN canonical_smiles TEXT")
        conn.execute("ALTER TABLE molecules ADD COLUMN review_status TEXT DEFAULT 'pending'")
        conn.execute("ALTER TABLE molecules ADD COLUMN reviewed_at TEXT")
        conn.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/core/test_database_schema.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/database.py tests/unit/core/test_database_schema.py
git commit -m "feat(db): add review columns to molecules table"
```

---

## Task 2: Implement molecule extraction from PDF images

**Files:**
- Create: `src/mbforge/pipeline/extract_molecules.py`
- Test: `tests/unit/pipeline/test_extract_molecules.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/pipeline/test_extract_molecules.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from mbforge.pipeline.extract_molecules import extract_molecules_from_pdf
from mbforge.parsers.molecule.extraction_result import ExtractionResult


def test_extract_molecules_from_pdf_returns_empty_when_pipeline_unavailable(tmp_path: Path) -> None:
    with patch("mbforge.pipeline.extract_molecules.get_moldet", return_value=None):
        results = extract_molecules_from_pdf("dummy.pdf", str(tmp_path), "doc1")
    assert results == []


def test_extract_molecules_from_pdf_collects_results(tmp_path: Path) -> None:
    fake_pipeline = MagicMock()
    fake_pipeline.is_available.return_value = True
    fake_result = ExtractionResult(
        esmiles="CCO",
        name="ethanol",
        source="image",
        moldet_conf=0.9,
        scribe_conf=0.8,
        bbox_pdf=(10.0, 20.0, 30.0, 40.0),
        page_idx=0,
        mol_img_path=tmp_path / "crop.png",
        status="pending",
    )
    fake_pipeline.extract_page.return_value = [fake_result]

    with patch("mbforge.pipeline.extract_molecules.get_moldet", return_value=fake_pipeline), \
         patch("mbforge.pipeline.extract_molecules.fitz.open") as mock_fitz:
        mock_page = MagicMock()
        mock_page.rect.width = 595.0
        mock_page.rect.height = 842.0
        mock_pix = MagicMock()
        mock_pix.width = 100
        mock_pix.height = 100
        mock_pix.n = 3
        mock_pix.samples = bytes([0] * 100 * 100 * 3)
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc = MagicMock()
        mock_doc.__len__ = lambda _: 1
        mock_doc.load_page.return_value = mock_page
        mock_doc.__enter__ = MagicMock(return_value=mock_doc)
        mock_doc.__exit__ = MagicMock(return_value=False)
        mock_fitz.return_value = mock_doc

        results = extract_molecules_from_pdf("dummy.pdf", str(tmp_path), "doc1")

    assert len(results) == 1
    assert results[0].esmiles == "CCO"
    assert results[0].page_idx == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/pipeline/test_extract_molecules.py -v
```

Expected: FAIL because `extract_molecules_from_pdf` doesn't exist.

- [ ] **Step 3: Implement extraction module**

Create `src/mbforge/pipeline/extract_molecules.py`:

```python
"""Molecule extraction from PDF images and text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

from ..parsers.molecule.extraction_result import ExtractionResult
from ..utils.logger import get_logger

if TYPE_CHECKING:
    import fitz

logger = get_logger("mbforge.pipeline.extract_molecules")

# Loose SMILES heuristic: non-space string containing typical SMILES characters
_SMILES_LIKE_PATTERN = re.compile(r"[A-Za-z0-9\(\)\[\]\=\#\+\-\\\\/@\.]{6,}")


def extract_molecules_from_pdf(
    pdf_path: str,
    project_root: str,
    doc_id: str,
    max_pages: int | None = None,
) -> list[ExtractionResult]:
    """Render PDF pages and extract molecule structures via MolDet + MolScribe.

    Args:
        pdf_path: Path to the PDF file.
        project_root: Project root directory for saving cropped images.
        doc_id: Document identifier.
        max_pages: Maximum number of pages to process (None = all).

    Returns:
        List of ExtractionResult candidates with status='pending'.
    """
    from ..backends.moldet import get_moldet

    pipeline = get_moldet()
    if pipeline is None or not pipeline.is_available():
        logger.warning("MolDet pipeline unavailable, skipping image molecule extraction")
        return []

    import fitz

    crop_dir = Path(project_root) / ".mbforge" / "crops" / doc_id
    crop_dir.mkdir(parents=True, exist_ok=True)

    doc: fitz.Document = fitz.open(pdf_path)
    results: list[ExtractionResult] = []

    try:
        pages_to_process = range(min(max_pages or len(doc), len(doc)))
        for page_idx in pages_to_process:
            page = doc.load_page(page_idx)
            zoom = 300 / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            img_array = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
                pix.height, pix.width, pix.n
            )
            image = Image.fromarray(img_array)

            page_results = pipeline.extract_page(
                image=image,
                page_idx=page_idx,
                page_w_pts=page.rect.width,
                page_h_pts=page.rect.height,
                image_w=pix.width,
                image_h=pix.height,
                dpi=300.0,
                cache_prefix=f"{doc_id}_page_{page_idx:04d}",
            )

            for r in page_results:
                if r.mol_img_path is not None:
                    # Relocate crop into project crop dir
                    target = crop_dir / Path(r.mol_img_path).name
                    if Path(r.mol_img_path) != target:
                        Path(r.mol_img_path).rename(target)
                    r.mol_img_path = target
                r.status = "pending"
                results.append(r)
    finally:
        doc.close()

    logger.info(
        "Extracted %d molecule image candidates from %s", len(results), doc_id
    )
    return results


def extract_molecules_from_text(text: str, doc_id: str) -> list[ExtractionResult]:
    """Extract SMILES strings from raw text and validate with RDKit.

    Args:
        text: Raw document text.
        doc_id: Document identifier.

    Returns:
        List of validated SMILES candidates.
    """
    from rdkit import Chem

    results: list[ExtractionResult] = []
    seen: set[str] = set()

    for match in _SMILES_LIKE_PATTERN.finditer(text):
        candidate = match.group(0)
        mol = Chem.MolFromSmiles(candidate)
        if mol is None:
            continue
        canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        if canonical in seen:
            continue
        seen.add(canonical)

        start = max(0, match.start() - 200)
        end = min(len(text), match.end() + 200)
        context = text[start:end]

        results.append(
            ExtractionResult(
                esmiles=canonical,
                name="",
                source="text",
                context_text=context,
                status="pending",
            )
        )

    logger.info(
        "Extracted %d text SMILES candidates from %s", len(results), doc_id
    )
    return results
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/pipeline/test_extract_molecules.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/extract_molecules.py tests/unit/pipeline/test_extract_molecules.py
git commit -m "feat(pipeline): extract molecules from PDF images and text"
```

---

## Task 3: Implement molecule normalization and deduplication

**Files:**
- Create: `src/mbforge/pipeline/normalize.py`
- Test: `tests/unit/pipeline/test_normalize.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/pipeline/test_normalize.py`:

```python
from mbforge.pipeline.normalize import normalize_molecules
from mbforge.parsers.molecule.extraction_result import ExtractionResult


def test_normalize_rejects_invalid_smiles() -> None:
    results = [ExtractionResult(esmiles="not-a-smiles", source="text")]
    normalized = normalize_molecules(results)
    assert len(normalized) == 1
    assert normalized[0].status == "rejected"


def test_normalize_deduplicates_same_smiles() -> None:
    results = [
        ExtractionResult(esmiles="CCO", source="image"),
        ExtractionResult(esmiles="CCO", source="text"),
    ]
    normalized = normalize_molecules(results)
    assert len(normalized) == 1
    assert normalized[0].canonical_smiles == "CCO"
    assert len(normalized[0].detections) == 2


def test_normalize_keeps_different_smiles() -> None:
    results = [
        ExtractionResult(esmiles="CCO", source="image"),
        ExtractionResult(esmiles="CCC", source="image"),
    ]
    normalized = normalize_molecules(results)
    assert len(normalized) == 2
```

Note: the test references `canonical_smiles` and `detections` fields that we'll add to a wrapper dataclass in the implementation.

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/pipeline/test_normalize.py -v
```

Expected: FAIL because `normalize_molecules` doesn't exist.

- [ ] **Step 3: Implement normalization module**

Create `src/mbforge/pipeline/normalize.py`:

```python
"""Normalize and deduplicate extracted molecule candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from rdkit import Chem

from ..parsers.molecule.extraction_result import ExtractionResult
from ..utils.logger import get_logger

logger = get_logger("mbforge.pipeline.normalize")


@dataclass
class DetectionSource:
    source: Literal["image", "text", "manual"]
    doc_id: str = ""
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    image_path: str | None = None
    confidence: float = 0.0


@dataclass
class NormalizedMolecule:
    canonical_smiles: str
    esmiles: str
    name: str
    source_type: Literal["image", "text", "manual"]
    detections: list[DetectionSource] = field(default_factory=list)
    status: Literal["pending", "rejected"] = "pending"
    reject_reason: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)


def normalize_molecules(
    results: list[ExtractionResult],
) -> list[NormalizedMolecule]:
    """Validate SMILES, canonicalize, and deduplicate candidates.

    Args:
        results: Raw extraction results.

    Returns:
        Normalized molecules, one per unique canonical SMILES.
    """
    by_smiles: dict[str, NormalizedMolecule] = {}

    for r in results:
        mol = Chem.MolFromSmiles(r.esmiles)
        if mol is None:
            logger.debug("Rejected invalid SMILES: %s", r.esmiles)
            by_smiles.setdefault(
                r.esmiles,
                NormalizedMolecule(
                    canonical_smiles=r.esmiles,
                    esmiles=r.esmiles,
                    name=r.name,
                    source_type=r.source,
                    status="rejected",
                    reject_reason="invalid_smiles",
                ),
            )
            continue

        canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        detection = DetectionSource(
            source=r.source,
            page=r.page_idx,
            bbox=r.bbox_pdf,
            image_path=str(r.mol_img_path) if r.mol_img_path else None,
            confidence=r.composite_conf or r.moldet_conf or r.scribe_conf,
        )

        if canonical in by_smiles:
            by_smiles[canonical].detections.append(detection)
            # Keep highest-confidence image path for display
            if detection.confidence > (
                by_smiles[canonical].detections[0].confidence
                if by_smiles[canonical].detections
                else 0
            ):
                by_smiles[canonical].detections.insert(0, detection)
                by_smiles[canonical].detections.pop()
        else:
            by_smiles[canonical] = NormalizedMolecule(
                canonical_smiles=canonical,
                esmiles=canonical,
                name=r.name,
                source_type=r.source,
                detections=[detection],
                status="pending",
                properties={"context_text": r.context_text},
            )

    return list(by_smiles.values())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/pipeline/test_normalize.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/normalize.py tests/unit/pipeline/test_normalize.py
git commit -m "feat(pipeline): normalize and deduplicate molecule candidates"
```

---

## Task 4: Implement persistence to molecule_detections

**Files:**
- Create: `src/mbforge/pipeline/persist_molecules.py`
- Test: `tests/unit/pipeline/test_persist_molecules.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/pipeline/test_persist_molecules.py`:

```python
from pathlib import Path

from mbforge.pipeline.persist_molecules import persist_molecule_candidates
from mbforge.pipeline.normalize import NormalizedMolecule, DetectionSource


def test_persist_creates_detection_rows(tmp_path: Path) -> None:
    from mbforge.core.database import DatabaseManager

    project_root = str(tmp_path)
    db = DatabaseManager(project_root)
    db.initialize()

    candidates = [
        NormalizedMolecule(
            canonical_smiles="CCO",
            esmiles="CCO",
            name="ethanol",
            source_type="image",
            detections=[
                DetectionSource(
                    source="image",
                    doc_id="doc1",
                    page=0,
                    bbox=(10.0, 20.0, 30.0, 40.0),
                    image_path="crops/doc1/crop.png",
                    confidence=0.72,
                )
            ],
            status="pending",
        )
    ]

    persist_molecule_candidates(project_root, "doc1", candidates)

    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT doc_id, page, conf_moldet, conf_molscribe FROM molecule_detections"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc1"
    assert rows[0]["page"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/pipeline/test_persist_molecules.py -v
```

Expected: FAIL because `persist_molecule_candidates` doesn't exist.

- [ ] **Step 3: Implement persistence module**

Create `src/mbforge/pipeline/persist_molecules.py`:

```python
"""Persist normalized molecule candidates to the database."""

from __future__ import annotations

from ..core.database import DatabaseManager
from ..utils.logger import get_logger
from .normalize import NormalizedMolecule

logger = get_logger("mbforge.pipeline.persist_molecules")


def persist_molecule_candidates(
    project_root: str,
    doc_id: str,
    candidates: list[NormalizedMolecule],
) -> None:
    """Write pending molecule candidates to molecule_detections table.

    Args:
        project_root: Project root directory.
        doc_id: Source document ID.
        candidates: Normalized molecule candidates.
    """
    db = DatabaseManager.get(project_root)
    db.initialize()

    with db.mol_conn() as conn:
        for c in candidates:
            if c.status == "rejected":
                continue

            # Use the highest-confidence detection for primary display
            primary = c.detections[0] if c.detections else None
            bbox = primary.bbox if primary else None
            conf_moldet = 0.0
            conf_molscribe = 0.0
            if primary:
                # Heuristic: image detections have composite confidence;
                # we store it in conf_moldet for simplicity.
                conf_moldet = primary.confidence

            conn.execute(
                """
                INSERT INTO molecule_detections (
                    doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
                    crop_relpath, conf_moldet, conf_molscribe,
                    vlm_verified_esmiles
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    primary.page if primary else None,
                    bbox[0] if bbox else None,
                    bbox[1] if bbox else None,
                    bbox[2] if bbox else None,
                    bbox[3] if bbox else None,
                    primary.image_path if primary else None,
                    conf_moldet,
                    conf_molscribe,
                    c.canonical_smiles,
                ),
            )

    logger.info(
        "Persisted %d molecule candidates for %s",
        len([c for c in candidates if c.status != "rejected"]),
        doc_id,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/pipeline/test_persist_molecules.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/persist_molecules.py tests/unit/pipeline/test_persist_molecules.py
git commit -m "feat(pipeline): persist molecule candidates to database"
```

---

## Task 5: Wire extraction into pipeline runner

**Files:**
- Modify: `src/mbforge/pipeline/runner.py`
- Test: `tests/unit/pipeline/test_runner.py` (create or extend)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/pipeline/test_runner.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from mbforge.pipeline.runner import run_pipeline


def test_run_pipeline_calls_molecule_extraction(tmp_path: Path) -> None:
    fake_extracted = MagicMock()
    fake_extracted.page_count = 1
    fake_extracted.raw_text = ""
    fake_extracted.parser = "pymupdf"
    fake_extracted.title = "Test"
    fake_extracted.pages = []

    with patch("mbforge.pipeline.runner.extract_pdf_text", return_value=fake_extracted), \
         patch("mbforge.pipeline.runner.OpenKBAdapter") as mock_adapter_class, \
         patch("mbforge.pipeline.runner.extract_molecules_from_pdf", return_value=[]) as mock_img, \
         patch("mbforge.pipeline.runner.extract_molecules_from_text", return_value=[]) as mock_text, \
         patch("mbforge.pipeline.runner.normalize_molecules", return_value=[]) as mock_norm, \
         patch("mbforge.pipeline.runner.persist_molecule_candidates") as mock_persist:

        mock_adapter = MagicMock()
        mock_adapter_class.return_value = mock_adapter

        result = run_pipeline(str(tmp_path / "test.pdf"), str(tmp_path), "doc1")

        assert result.doc_id == "doc1"
        mock_img.assert_called_once()
        mock_text.assert_called_once()
        mock_norm.assert_called_once()
        mock_persist.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/pipeline/test_runner.py -v
```

Expected: FAIL because runner doesn't call the new modules yet.

- [ ] **Step 3: Modify runner**

In `src/mbforge/pipeline/runner.py`:

1. Add imports at the top:

```python
from .extract_molecules import extract_molecules_from_pdf, extract_molecules_from_text
from .normalize import normalize_molecules
from .persist_molecules import persist_molecule_candidates
```

2. Replace the `_enrich_molecules` block in `run_pipeline`:

```python
    # Stage 4: Enrich (molecules)
    _emit("progress", "Extracting molecules from images...", stage="enrich")
    image_results = extract_molecules_from_pdf(
        pdf_path, project_root, doc_id, extracted.page_count
    )
    _emit(
        "complete",
        f"Detected {len(image_results)} molecule image candidates",
        stage="enrich",
    )

    _emit("progress", "Extracting molecules from text...", stage="enrich")
    text_results = extract_molecules_from_text(extracted.raw_text, doc_id)
    _emit(
        "complete",
        f"Detected {len(text_results)} text SMILES candidates",
        stage="enrich",
    )

    all_results = image_results + text_results

    _emit("progress", "Normalizing molecule candidates...", stage="enrich")
    normalized = normalize_molecules(all_results)
    valid_count = len([n for n in normalized if n.status != "rejected"])
    _emit(
        "complete",
        f"Normalized to {valid_count} unique candidates",
        stage="enrich",
    )

    _emit("progress", "Saving molecule candidates...", stage="enrich")
    persist_molecule_candidates(project_root, doc_id, normalized)
    _emit("complete", "Molecule candidates saved", stage="enrich")
```

3. Remove the old `_enrich_molecules` function or leave it unused.

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/pipeline/test_runner.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/runner.py tests/unit/pipeline/test_runner.py
git commit -m "feat(pipeline): wire molecule extraction into runner"
```

---

## Task 6: Add molecule review API

**Files:**
- Modify: `src/mbforge/routers/molecule.py`
- Modify: `src/mbforge/models/molecule.py`
- Test: `tests/integration/test_molecule_review.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_molecule_review.py`:

```python
from fastapi.testclient import TestClient
from mbforge.app import app

client = TestClient(app)


def test_review_confirm_creates_molecule(tmp_path) -> None:
    project_root = str(tmp_path)
    from mbforge.core.database import DatabaseManager

    db = DatabaseManager(project_root)
    db.initialize()

    # Seed a pending detection
    with db.mol_conn() as conn:
        conn.execute(
            """
            INSERT INTO molecule_detections (
                doc_id, page, vlm_verified_esmiles, crop_relpath
            ) VALUES (?, ?, ?, ?)
            """,
            ("doc1", 0, "CCO", "crops/doc1/crop.png"),
        )
        detection_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    response = client.post(
        "/api/v1/molecule/review",
        json={
            "project_root": project_root,
            "detection_id": detection_id,
            "action": "confirm",
            "smiles": "CCO",
            "name": "ethanol",
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "mol_id" in data

    with db.mol_conn() as conn:
        row = conn.execute(
            "SELECT * FROM molecules WHERE canonical_smiles = ?", ("CCO",)
        ).fetchone()
        assert row is not None
        assert row["name"] == "ethanol"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/integration/test_molecule_review.py -v
```

Expected: FAIL because `/api/v1/molecule/review` doesn't exist.

- [ ] **Step 3: Add request model and endpoint**

In `src/mbforge/models/molecule.py`, add:

```python
class MoleculeReviewRequest(BaseModel):
    project_root: str = Field(..., description="Project root directory")
    detection_id: int = Field(..., description="molecule_detections.id")
    action: Literal["confirm", "reject", "edit"] = Field(..., description="Review action")
    smiles: str | None = Field(None, description="Corrected SMILES for edit/confirm")
    name: str | None = Field(None, description="Molecule name")
    activity: float | None = Field(None, description="Activity value")
    activity_type: str | None = Field(None, description="Activity type")
    units: str | None = Field(None, description="Activity units")
```

In `src/mbforge/routers/molecule.py`, add:

```python
from ..models.molecule import MoleculeReviewRequest


@router.post("/review")
async def review_molecule(body: MoleculeReviewRequest) -> dict:
    validate_project_root(body.project_root)
    from ..core.database import DatabaseManager
    from rdkit import Chem

    db = DatabaseManager.get(body.project_root)
    db.initialize()

    with db.mol_conn() as conn:
        detection = conn.execute(
            "SELECT * FROM molecule_detections WHERE id = ?", (body.detection_id,)
        ).fetchone()

        if not detection:
            return {"success": False, "error": "detection not found"}

        if body.action == "reject":
            conn.execute(
                "DELETE FROM molecule_detections WHERE id = ?",
                (body.detection_id,),
            )
            return {"success": True}

        smiles = body.smiles or detection["vlm_verified_esmiles"]
        if not smiles:
            return {"success": False, "error": "no SMILES available"}

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return {"success": False, "error": "invalid SMILES"}

        canonical = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
        mol_id = str(uuid.uuid4())

        conn.execute(
            """
            INSERT OR REPLACE INTO molecules (
                mol_id, smiles, canonical_smiles, esmiles, name,
                source_doc, source_type, status, review_status, reviewed_at,
                activity, activity_type, units
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?)
            """,
            (
                mol_id,
                smiles,
                canonical,
                smiles,
                body.name or detection["vlm_verified_esmiles"][:20],
                detection["doc_id"],
                "image",
                "active",
                "confirmed",
                body.activity,
                body.activity_type,
                body.units,
            ),
        )

        conn.execute(
            "UPDATE molecule_detections SET mol_id = ? WHERE id = ?",
            (mol_id, body.detection_id),
        )

    return {"success": True, "mol_id": mol_id}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/integration/test_molecule_review.py -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/routers/molecule.py src/mbforge/models/molecule.py tests/integration/test_molecule_review.py
git commit -m "feat(api): add molecule review endpoint"
```

---

## Task 7: Add frontend review panel

**Files:**
- Create: `frontend/src/api/http/molecule.ts` (or extend existing)
- Create: `frontend/src/components/molecule/MoleculeReviewPanel.tsx`
- Modify: `frontend/src/components/MoleculeLibrary.tsx` or add route

- [ ] **Step 1: Add API wrapper**

Create or extend `frontend/src/api/http/molecule.ts`:

```typescript
import { httpPost } from './_utils'

export interface ReviewMoleculeRequest {
  project_root: string
  detection_id: number
  action: 'confirm' | 'reject' | 'edit'
  smiles?: string
  name?: string
  activity?: number
  activity_type?: string
  units?: string
}

export async function reviewMolecule(req: ReviewMoleculeRequest): Promise<{ success: boolean; mol_id?: string; error?: string }> {
  return httpPost<{ success: boolean; mol_id?: string; error?: string }>('/api/v1/molecule/review', req)
}
```

- [ ] **Step 2: Create review panel component**

Create `frontend/src/components/molecule/MoleculeReviewPanel.tsx`:

```tsx
import { useState } from 'react'
import { reviewMolecule } from '@/api/http/molecule'

interface PendingMolecule {
  id: number
  doc_id: string
  page: number
  vlm_verified_esmiles: string
  crop_relpath: string | null
  conf_moldet: number
}

interface Props {
  projectRoot: string
  pending: PendingMolecule[]
  onReviewed: () => void
}

export default function MoleculeReviewPanel({ projectRoot, pending, onReviewed }: Props) {
  const [current, setCurrent] = useState(0)
  const [smiles, setSmiles] = useState('')
  const [name, setName] = useState('')
  const item = pending[current]

  if (!item) return <div>No pending molecules</div>

  const handleAction = async (action: 'confirm' | 'reject') => {
    await reviewMolecule({
      project_root: projectRoot,
      detection_id: item.id,
      action,
      smiles: action === 'confirm' ? (smiles || item.vlm_verified_esmiles) : undefined,
      name: name || undefined,
    })
    setSmiles('')
    setName('')
    onReviewed()
    if (current < pending.length - 1) setCurrent(current + 1)
  }

  return (
    <div style={{ display: 'flex', gap: 16, padding: 16 }}>
      <div style={{ flex: 1 }}>
        {item.crop_relpath && (
          <img
            src={`/api/v1/project/file?path=${encodeURIComponent(item.crop_relpath)}`}
            alt="molecule crop"
            style={{ maxWidth: 300, border: '1px solid var(--border)' }}
          />
        )}
        <div>Page: {item.page}</div>
        <div>Confidence: {(item.conf_moldet * 100).toFixed(1)}%</div>
      </div>
      <div style={{ flex: 1 }}>
        <label>SMILES</label>
        <input
          value={smiles || item.vlm_verified_esmiles}
          onChange={(e) => setSmiles(e.target.value)}
          style={{ width: '100%', marginBottom: 8 }}
        />
        <label>Name</label>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          style={{ width: '100%', marginBottom: 16 }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => handleAction('confirm')}>Confirm</button>
          <button onClick={() => handleAction('reject')}>Reject</button>
        </div>
        <div>{current + 1} / {pending.length}</div>
      </div>
    </div>
  )
}
```

Note: The image source URL (`/api/v1/project/file`) may need to be created or use an existing static-file endpoint. If it doesn't exist, use a placeholder or add a simple file-serving endpoint in `routers/project.py`.

- [ ] **Step 3: Add pending molecule list endpoint**

In `src/mbforge/routers/molecule.py`, add:

```python
@router.post("/pending")
async def list_pending_molecules(body: MoleculeStatsRequest) -> dict:
    validate_project_root(body.project_root)
    from ..core.database import DatabaseManager

    db = DatabaseManager.get(body.project_root)
    db.initialize()
    with db.mol_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM molecule_detections WHERE mol_id IS NULL ORDER BY id"
        ).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}
```

Add corresponding frontend wrapper:

```typescript
export async function listPendingMolecules(projectRoot: string): Promise<{ success: boolean; items: PendingMolecule[] }> {
  return httpPost<{ success: boolean; items: PendingMolecule[] }>('/api/v1/molecule/pending', { project_root: projectRoot })
}
```

- [ ] **Step 4: Integrate into MoleculeLibrary or new page**

In `frontend/src/components/MoleculeLibrary.tsx` (or create a new route `/molecules/review`), add:

```tsx
import MoleculeReviewPanel from './molecule/MoleculeReviewPanel'
import { listPendingMolecules } from '@/api/http/molecule'

// Inside component:
const [pending, setPending] = useState<PendingMolecule[]>([])
const loadPending = async () => {
  const resp = await listPendingMolecules(projectRoot)
  if (resp.success) setPending(resp.items)
}
useEffect(() => { loadPending() }, [projectRoot])

return (
  <div>
    <h2>Review Molecules</h2>
    <MoleculeReviewPanel projectRoot={projectRoot} pending={pending} onReviewed={loadPending} />
  </div>
)
```

- [ ] **Step 5: Run frontend type check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: PASS (or fix any type errors).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/http/molecule.ts frontend/src/components/molecule/MoleculeReviewPanel.tsx frontend/src/components/MoleculeLibrary.tsx src/mbforge/routers/molecule.py
git commit -m "feat(frontend): add minimal molecule review panel"
```

---

## Task 8: Integration smoke test

**Files:**
- Test: `tests/integration/test_pipeline_molecule_extraction.py` (create)

- [ ] **Step 1: Write integration test**

Create `tests/integration/test_pipeline_molecule_extraction.py`:

```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from mbforge.pipeline.runner import run_pipeline


def test_pipeline_creates_pending_detections(tmp_path: Path) -> None:
    # Create a minimal PDF-like file path (test mocks fitz)
    pdf_path = tmp_path / "test.pdf"
    pdf_path.write_text("dummy")

    fake_extracted = MagicMock()
    fake_extracted.page_count = 1
    fake_extracted.raw_text = "CCO"
    fake_extracted.parser = "pymupdf"
    fake_extracted.title = "Test"
    fake_extracted.pages = []

    fake_result = MagicMock()
    fake_result.esmiles = "CCO"
    fake_result.name = ""
    fake_result.source = "image"
    fake_result.moldet_conf = 0.9
    fake_result.scribe_conf = 0.8
    fake_result.composite_conf = 0.72
    fake_result.bbox_pdf = (10.0, 20.0, 30.0, 40.0)
    fake_result.page_idx = 0
    fake_result.mol_img_path = tmp_path / "crop.png"
    fake_result.context_text = ""
    fake_result.status = "pending"

    with patch("mbforge.pipeline.runner.extract_pdf_text", return_value=fake_extracted), \
         patch("mbforge.pipeline.runner.OpenKBAdapter") as mock_adapter_class, \
         patch("mbforge.pipeline.runner.extract_molecules_from_pdf", return_value=[fake_result]), \
         patch("mbforge.pipeline.runner.extract_molecules_from_text", return_value=[]), \
         patch("mbforge.pipeline.runner.fitz.open") as mock_fitz:

        mock_adapter = MagicMock()
        mock_adapter_class.return_value = mock_adapter

        # Avoid actual PDF rendering in runner by not entering the fitz mock path
        run_pipeline(str(pdf_path), str(tmp_path), "doc1")

    from mbforge.core.database import DatabaseManager

    db = DatabaseManager(str(tmp_path))
    with db.mol_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM molecule_detections WHERE doc_id = ?", ("doc1",)
        ).fetchone()[0]

    assert count == 1
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/integration/test_pipeline_molecule_extraction.py -v
```

Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_pipeline_molecule_extraction.py
git commit -m "test(integration): pipeline creates pending molecule detections"
```

---

## Self-Review Checklist

- [x] **Spec coverage**: Each section of the Phase 1 design doc maps to tasks here.
- [x] **Placeholder scan**: No TBD/TODO; all code, commands, and expected outputs are explicit.
- [x] **Type consistency**: `NormalizedMolecule`, `DetectionSource`, `ExtractionResult` used consistently.
- [x] **Scope**: This plan produces a working molecule extraction + review loop without touching activity extraction or SAR.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-mbforge-phase1-molecule-extraction-plan.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach do you want?
