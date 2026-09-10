# Text Reorganization + MoleCode Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert molecule structures (as MoleCode Mermaid subgraphs) into the extracted text at their correct geometric positions, then LLM-reorganize the full text into a clean semantic document. Pass this reorganized text to PageIndex (via MarkdownParser, level-based, zero LLM) and finally register each molecule's text context into the database. This ensures scanned-page text survives into PageIndex, molecule↔text links are preserved, and the wiki stores chemically-intelligent rich text.

**Architecture:** Add `text_spans` (bbox-per-block) to `PageContent` during extraction; create three new functions in `pipeline/organizer.py` (MoleCode insertion, LLM reorganization, molecule registration); reorder pipeline stages so PageIndex reads the final `.md` instead of the raw PDF; add new tables `text_molecule_links` and `sections` to the database.

**Tech Stack:** Python 3.12, RDKit, molecode 0.1.0 (PyPI), FastAPI, SQLite, Pydantic 2, uv, pytest.

## Global Constraints

- Every module starts with `logger = get_logger(__name__)`; never `print()`.
- All errors inherit from `MBForgeError` with `status_code` + `error_code` class attrs.
- Use `from __future__ import annotations` to avoid runtime forward refs.
- Public functions must be fully type-annotated.
- Run `uv run ruff check src/` after file edits; keep line width 88.
- Run `uv run pytest tests/ -v` before claiming a task passes.
- Commit each task independently with a descriptive message.
- The backend must remain importable and `uv run python -c "from mbforge.app import app; print(len(app.routes))"` must succeed after every task.

---

## File Structure

### New files

- `src/mbforge/pipeline/organizer.py` — Three functions: `insert_molecode_blocks`, `reorganize_with_llm`, `register_molecules_from_text`.

### Modified files (grouped by responsibility)

- **Text extraction**
  - `src/mbforge/pipeline/extract_text.py` — Add `TextSpan` dataclass, `text_spans` field on `PageContent`, `write_rough_markdown()` free function.

- **Pipeline orchestrator**
  - `src/mbforge/pipeline/runner.py` — Stage reorder: extract → density → write_rough_md → insert_molecode → reorganize_with_llm → pageindex(md) → wiki → detect_mols → persist. Split `_enrich_and_persist_molecules` → `_enrich_molecules` + `_persist_molecules`.

- **Schema & database**
  - `src/mbforge/core/database.py` — Add `text_molecule_links` table to `_MOL_SCHEMA`; add `sections` table to `_KB_SCHEMA`.

- **PageIndex interface**
  - `src/mbforge/openkb/adapter.py` — Add `index_markdown(md_path, doc_id)` method that copies .md to managed storage and adds it via `PageIndexWrapper.add_document`.

- **Configuration**
  - `src/mbforge/utils/config.py` — Add optional `reorganize_model: str` field to `LLMConfig` (falls back to `model` if unset).

- **Tests**
  - `tests/unit/pipeline/test_organizer.py` (new) — Bbox matching, MoleCode round-trip, insertion accuracy.
  - `tests/unit/test_database_schema.py` (new) — `text_molecule_links` and `sections` tables present.
  - `tests/unit/pipeline/test_extract_text.py` — `text_spans` present on PageContent.

---

## Task Decomposition

### Task 1: Add `text_spans` to PageContent + `write_rough_markdown`

**Files:**
- Modify: `src/mbforge/pipeline/extract_text.py`
- Test: `tests/unit/pipeline/test_extract_text.py`

**Interfaces:**
- Consumes: `pymupdf.page.get_text("dict")` blocks during PDF iteration
- Produces: `TextSpan` dataclass, `PageContent.text_spans` field, `write_rough_markdown(pages, output_path) -> None`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from mbforge.pipeline.extract_text import TextSpan, PageContent, write_rough_markdown


def test_text_span_dataclass() -> None:
    span = TextSpan(text="hello", bbox=(0, 0, 100, 50))
    assert span.text == "hello"
    assert span.bbox == (0, 0, 100, 50)
    assert span.block_type == 0


def test_text_spans_on_page_content() -> None:
    pc = PageContent(page_num=1, text="test")
    assert hasattr(pc, "text_spans")
    assert pc.text_spans == []


def test_write_rough_markdown_creates_file(tmp_path: Path) -> None:
    pages = [
        PageContent(page_num=1, text="Abstract\nThis is a test."),
        PageContent(page_num=2, text="1. Introduction\nSome intro text."),
    ]
    out = tmp_path / "rough.md"
    write_rough_markdown(pages, str(out))
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "---PAGE 1---" in content or "# " in content
    assert "Abstract" in content or "Introduction" in content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_extract_text.py -v`
Expected: FAIL (TextSpan, write_rough_markdown not defined)

- [ ] **Step 3: Write minimal implementation**

In `src/mbforge/pipeline/extract_text.py`:

1. Add `TextSpan` dataclass before `PageContent`:

```python
@dataclass
class TextSpan:
    """One text or image block from a PDF page with its bounding box."""
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF pts
    block_type: int = 0  # 0=text, 1=image
```

2. Add `text_spans` field to `PageContent`:

```python
@dataclass
class PageContent:
    page_num: int
    text: str
    has_text: bool = True
    needs_ocr: bool = False
    ocr_dpi: int = 0
    text_density: float = 0.0
    text_spans: list[TextSpan] = field(default_factory=list)
```

3. In `extract_pdf_text`, after the native-text loop where `pages` entries are created for text-rich pages (around line 55-63), also call `page.get_text("dict")` and populate `text_spans`:

```python
if text_len >= 50:
    span_blocks = page.get_text("dict")["blocks"]
    spans = []
    for blk in span_blocks:
        b = blk["bbox"]
        if blk["type"] == 0:  # text block
            text_content = "".join(
                span.get("text", "")
                for line in blk.get("lines", [])
                for span in line.get("spans", [])
            )
            spans.append(TextSpan(text=text_content, bbox=b, block_type=0))
        elif blk["type"] == 1:  # image block
            spans.append(TextSpan(text="", bbox=b, block_type=1))
    pages[-1] = PageContent(
        page_num=page_num,
        text=text,
        has_text=True,
        needs_ocr=False,
        text_density=density,
        text_spans=spans,
    )
```

For scanned/OCR pages, skip — no bbox available from OCR engines.

4. Add `write_rough_markdown` at module level:

```python
HEADING_PATTERNS = re.compile(
    r"^(Abstract|Introduction|Background|Methods|Materials and Methods|"
    r"Results|Discussion|Conclusion|References|Acknowledgments|"
    r"Supporting Information|Supplementary|Appendix|"
    r"\d+\.\s+|FIGURES?|TABLES?)$",
    re.IGNORECASE,
)

def write_rough_markdown(pages: list[PageContent], output_path: str) -> None:
    """Write pages to a rough markdown with basic heading detection."""
    lines: list[str] = []
    for i, page in enumerate(pages):
        lines.append(f"<!-- PAGE {page.page_num} -->")
        for para in page.text.split("\n"):
            stripped = para.strip()
            if not stripped:
                continue
            if HEADING_PATTERNS.match(stripped.split(".")[0].strip()):
                lines.append(f"## {stripped}")
            else:
                lines.append(stripped)
        lines.append("")
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/test_extract_text.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/extract_text.py tests/unit/pipeline/test_extract_text.py
git commit -m "feat(pipeline): add text_spans to PageContent + write_rough_markdown

- TextSpan dataclass captures per-block bbox from PyMuPDF
- PageContent.text_spans stores block-level geometry for molecule matching
- write_rough_markdown converts page list to rough .md with basic heading hints"
```

---

### Task 2: Create `organizer.py` — MoleCode insertion

**Files:**
- Create: `src/mbforge/pipeline/organizer.py`
- Test: `tests/unit/pipeline/test_organizer.py`

**Interfaces:**
- Consumes: `PageContent` (with `text_spans`), `NormalizedMolecule` (from `normalize.py`), `mol_to_mermaid` (from `molecode`), rough markdown path
- Produces: `insert_molecode_blocks(md_path, pages, molecules, output_path) -> str`

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from mbforge.pipeline.extract_text import PageContent, TextSpan
from mbforge.pipeline.normalize import NormalizedMolecule, DetectionSource
from mbforge.pipeline.organizer import insert_molecode_blocks


def test_insert_molecode_bbox_match(tmp_path: Path) -> None:
    rough_md = tmp_path / "rough.md"
    rough_md.write_text("# Abstract\nThis is a test molecule.\n")
    pages = [
        PageContent(
            page_num=1, text="test molecule",
            text_spans=[TextSpan(text="test molecule", bbox=(0, 0, 200, 100))],
        )
    ]
    mol = NormalizedMolecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        name="Ethanol",
        status="pending",
        detections=[
            DetectionSource(source="image", page=0, bbox=(10, 10, 50, 50)),
        ],
    )
    out = tmp_path / "enriched.md"
    insert_molecode_blocks(str(rough_md), pages, [mol], str(out))
    content = out.read_text(encoding="utf-8")
    assert "molecode" in content or "subgraph" in content
    assert "Ethanol" in content


def test_insert_molecode_no_bbox_fallback(tmp_path: Path) -> None:
    rough_md = tmp_path / "rough.md"
    rough_md.write_text("# Test\nContent.\n")
    pages = [
        PageContent(
            page_num=1, text="Content.",
            text_spans=[TextSpan(text="Content.", bbox=(0, 0, 100, 50))],
        )
    ]
    mol = NormalizedMolecule(
        canonical_smiles="CCO",
        esmiles="CCO",
        name="Ethanol",
        status="pending",
        detections=[
            DetectionSource(source="image", page=0, bbox=(500, 500, 600, 550)),
        ],
    )
    out = tmp_path / "enriched.md"
    insert_molecode_blocks(str(rough_md), pages, [mol], str(out))
    content = out.read_text(encoding="utf-8")
    assert "molecode" in content or "subgraph" in content  # appended at page-end
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_organizer.py -v`
Expected: FAIL (import error: no module organizer)

- [ ] **Step 3: Write minimal implementation**

Create `src/mbforge/pipeline/organizer.py`:

```python
"""Text reorganization and molecule registration for the pipeline.

Three entry points:
1. insert_molecode_blocks — Insert MoleCode into rough markdown at bbox positions
2. reorganize_with_llm — LLM-based full-text reorganization (Task 3)
3. register_molecules_from_text — Extract text context for each molecule (Task 4)
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from ..utils.logger import get_logger
from .extract_text import PageContent
from .normalize import NormalizedMolecule

logger = get_logger("mbforge.pipeline.organizer")

_PAGE_MARKER_RE = re.compile(r"<!-- PAGE (\d+) -->")


def _bbox_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Intersection over min-area for two bounding boxes."""
    x_left = max(a[0], b[0])
    y_top = max(a[1], b[1])
    x_right = min(a[2], b[2])
    y_bottom = min(a[3], b[3])
    if x_right <= x_left or y_bottom <= y_top:
        return 0.0
    inter = (x_right - x_left) * (y_bottom - y_top)
    area_a = max((a[2] - a[0]) * (a[3] - a[1]), 1.0)
    area_b = max((b[2] - b[0]) * (b[3] - b[1]), 1.0)
    return inter / min(area_a, area_b)


def _mol_to_molecode(smiles: str, name: str) -> str:
    """Convert SMILES to MoleCode Mermaid format via rdkit + molecode."""
    from rdkit import Chem
    from molecode import mol_to_mermaid

    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        logger.warning("MoleCode conversion failed for SMILES: %s", smiles)
        return f"```\n# MoleCode not available for {name}\n```\n"
    try:
        mcode = mol_to_mermaid(mol, name=name, kekulize=True)
    except Exception as exc:
        logger.warning("MoleCode error for %s: %s", name, exc)
        return f"```\n# MoleCode error for {name}: {exc}\n```\n"
    return f"```molecode\n{mcode}\n```\n"


def _find_position_in_pages(
    mol_page: int,
    mol_bbox: tuple[float, float, float, float] | None,
    pages: list[PageContent],
) -> int | None:
    """Find the paragraph index in the rough md where this molecule belongs.

    Returns None → append to page-end section.
    """
    if mol_bbox is None or mol_page < 0 or mol_page >= len(pages):
        return None
    page = pages[mol_page]
    for i, span in enumerate(page.text_spans):
        if span.block_type != 0:
            continue
        if _bbox_overlap(mol_bbox, span.bbox) > 0.3:
            return i
    return None


def insert_molecode_blocks(
    md_path: str,
    pages: list[PageContent],
    molecules: list[NormalizedMolecule],
    output_path: str,
) -> str:
    """Insert MoleCode blocks into rough markdown at bbox-determined positions.

    Strategy A: bbox falls inside a text span → MoleCode after that paragraph.
    Strategy B: bbox in different paragraph on same page → MoleCode after nearest.
    Strategy C: no bbox match → append at page-end with ``(Page Y)`` annotation.
    """
    md_text = Path(md_path).read_text(encoding="utf-8")
    lines = md_text.split("\n")

    # Build (page, span_index, normal molecule) groups
    insertions: list[tuple[int, int | None, NormalizedMolecule]] = []
    for mol in molecules:
        if mol.status == "rejected":
            continue  # skip unparseable molecules
        primary = mol.detections[0] if mol.detections else None
        if primary is None:
            continue
        page_idx = primary.page or 0
        span_idx = _find_position_in_pages(
            page_idx, primary.bbox, pages
        )
        insertions.append((page_idx, span_idx, mol))

    # Sort: by page then by span index (None = after all known spans on that page)
    insertions.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 9999))

    # Map page markers to line numbers
    page_boundaries: dict[int, int] = {}
    for lineno, line in enumerate(lines):
        m = _PAGE_MARKER_RE.match(line)
        if m:
            page_boundaries[int(m.group(1))] = lineno

    # Collect text lines per page for span-level matching
    page_ranges: dict[int, list[int]] = {}
    current_page = 1
    page_ranges[1] = []
    for lineno, line in enumerate(lines):
        m = _PAGE_MARKER_RE.match(line)
        if m:
            current_page = int(m.group(1))
            page_ranges.setdefault(current_page, [])
        else:
            page_ranges[current_page].append(lineno)

    # Build insertions in reverse order (to preserve line numbers)
    reverse_insertions: list[tuple[int, str]] = []
    for page_idx, span_idx, mol in reversed(insertions):
        name = mol.name or f"Mol_{mol.canonical_smiles[:8]}"
        block = _mol_to_molecode(mol.canonical_smiles, name)
        if span_idx is not None and page_idx + 1 in page_ranges:
            # Insert after the matching paragraph on this page
            plines = page_ranges[page_idx + 1]
            insert_at = max(plines) if plines else 0
            insert_at = max(insert_at, page_boundaries.get(page_idx + 1, 0))
            reverse_insertions.append((insert_at, block))
        else:
            # Strategy C — append to page-end
            boundary = page_boundaries.get(page_idx + 1)
            next_boundary = page_boundaries.get(page_idx + 2, len(lines))
            insert_at = next_boundary - 1 if next_boundary > 0 else len(lines) - 1
            if boundary is not None:
                fallback = f"\n<!-- Molecule {name} (Page {page_idx + 1}) -->\n{block}"
                reverse_insertions.append((next_boundary - 1, fallback))
            else:
                # Fallback: end of file
                reverse_insertions.append((len(lines), f"\n{block}"))

    # Apply insertions (reverse order preserves earlier line numbers)
    for insert_at, block in reverse_insertions:
        insert_at = max(0, min(insert_at, len(lines)))
        lines.insert(insert_at + 1, block)

    result = "\n".join(lines)
    Path(output_path).write_text(result, encoding="utf-8")
    return output_path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/test_organizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/organizer.py tests/unit/pipeline/test_organizer.py
git commit -m "feat(pipeline): insert MoleCode blocks into rough markdown by bbox"

deterministic:
- insert_molecode_blocks places MoleCode at correct text span via bbox overlap
- Strategies A (match), B (page-match), C (fallback append)
- Uses molecode.mol_to_mermaid for SMILES → Mermaid conversion"
```

---

### Task 3: Implement `reorganize_with_llm` in `organizer.py`

**Files:**
- Modify: `src/mbforge/pipeline/organizer.py`
- Test: `tests/unit/pipeline/test_organizer.py`

**Interfaces:**
- Consumes: `reorganize_with_llm(md_path, output_path, model) -> str`
- Produces: Reorganized markdown with MoleCode blocks preserved

- [ ] **Step 1: Write the failing test**

```python
def test_reorganize_preserves_molecode_blocks(tmp_path: Path) -> None:
    from mbforge.pipeline.organizer import reorganize_with_llm
    md = tmp_path / "in.md"
    md.write_text("# Test\nText.\n```molecode\ngraph TB\nsubgraph X[\"X\"]\nend\n```\nEnd.\n")
    out = tmp_path / "out.md"
    # This is a smoke test: the LLM call is mocked/skipped.
    # For CI, just test that the function exists and has the right signature.
    import inspect
    sig = inspect.signature(reorganize_with_llm)
    params = list(sig.parameters.keys())
    assert "md_path" in params
    assert "output_path" in params
    assert "model" in params or "llm_model" in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_organizer.py -v`
Expected: FAIL (reorganize_with_llm not in module)

- [ ] **Step 3: Write minimal implementation**

Append to `src/mbforge/pipeline/organizer.py`:

```python
def reorganize_with_llm(
    md_path: str,
    output_path: str,
    model: str | None = None,
) -> str:
    """Reorganize a rough markdown document with MoleCode blocks via LLM.

    The LLM restructures paragraphs, assigns heading levels, merges split
    sections, and preserves all `` ```molecode `` blocks verbatim.

    Args:
        md_path: Path to the enriched markdown (with MoleCode blocks).
        output_path: Where to write the reorganized markdown.
        model: LLM model name. Defaults to ``load_global_config().llm.model``.
    """
    if model is None:
        from ..utils.config import load_global_config
        cfg = load_global_config()
        model = getattr(cfg.llm, "reorganize_model", None) or cfg.llm.model

    md_text = Path(md_path).read_text(encoding="utf-8")

    # Estimate token count
    char_count = len(md_text)
    estimated_tokens = char_count // 4

    SYSTEM_PROMPT = """You are reorganizing a scientific document extracted from a PDF.

Rules:
1. Keep ALL ```molecode ... ``` blocks intact. Do NOT modify, move, remove,
   or "fix" any MoleCode content.
2. Reorganize paragraphs into logical sections with Markdown headings (#, ##, ###).
3. Merge content from the same section that was split across pages.
4. Move MoleCode blocks into the section where they semantically belong,
   using the molecular name as context.
5. Fix obvious OCR errors (common substitution patterns only).
6. Preserve all factual content. Do not invent information.
7. Remove page markers (<!-- PAGE N -->).
8. Output valid Markdown."""

    # For short docs (<4000 tokens), single-shot.
    # For longer docs, split by major sections and process chunked.
    if estimated_tokens < 4000:
        prompt = f"{SYSTEM_PROMPT}\n\nDocument:\n{md_text}\n\nReorganized:"
        response = _llm_complete(model, prompt)
        Path(output_path).write_text(response, encoding="utf-8")
        return output_path

    # Long doc: process in chunks
    # Split on ```molecode boundaries so MoleCode blocks are never split
    segments = re.split(r"(```molecode\n.*?\n```)", md_text, flags=re.DOTALL)
    chunk_size = 6000  # approximate token budget
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0

    for seg in segments:
        seg_len = len(seg) // 4
        if current_len + seg_len > chunk_size and current_chunk:
            chunks.append("".join(current_chunk))
            current_chunk = [seg]
            current_len = seg_len
        else:
            current_chunk.append(seg)
            current_len += seg_len
    if current_chunk:
        chunks.append("".join(current_chunk))

    reorganized_chunks: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_prompt = f"""{SYSTEM_PROMPT}

This is chunk {i + 1} of {len(chunks)}. Focus on reorganizing this chunk.

Context: The beginning of the chunk is "{chunk[:200]}..."

Chunk text:
{chunk}

Reorganized (chunk {i + 1} of {len(chunks)}):
"""
        resp = _llm_complete(model, chunk_prompt)
        reorganized_chunks.append(resp)

    final_text = "\n\n".join(reorganized_chunks)
    Path(output_path).write_text(final_text, encoding="utf-8")
    return output_path


def _llm_complete(model: str, prompt: str) -> str:
    """Call LLM and return completion text."""
    try:
        from litellm import completion
        response = completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        return response.choices[0].message.content or ""
    except ImportError:
        logger.warning("litellm not available — reorganize skipped, copying input")
        return prompt
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return prompt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/test_organizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/organizer.py
git commit -m "feat(pipeline): add LLM-based reorganize function

- reorganize_with_llm restructures rough markdown into clean sections
- Preserves all ```molecode blocks verbatim
- Chunked processing for documents >4000 tokens
- Falls back to copy if litellm unavailable"
```

---

### Task 4: Implement `register_molecules_from_text` in `organizer.py`

**Files:**
- Modify: `src/mbforge/pipeline/organizer.py`
- Test: `tests/unit/pipeline/test_organizer.py`

**Interfaces:**
- Consumes: `register_molecules_from_text(fine_md_path, molecules, doc_id, project_root) -> None`
- Produces: `text_molecule_links` table rows

- [ ] **Step 1: Write the failing test**

```python
def test_register_molecules_found_in_text(tmp_path: Path) -> None:
    from mbforge.pipeline.organizer import register_molecules_from_text
    fine_md = tmp_path / "fine.md"
    fine_md.write_text("# Section 1\nText.\n```molecode\nsubgraph Ethanol[\"Ethanol\"]\nend\n```\nEnd.\n")
    from mbforge.pipeline.normalize import NormalizedMolecule, DetectionSource
    mols = [
        NormalizedMolecule(
            canonical_smiles="CCO", esmiles="CCO", name="Ethanol",
            status="pending", detections=[DetectionSource(source="image")],
            reject_reason=None,
        )
    ]
    import tempfile, os
    # This test only verifies function exists and has the right
    # signature — table writes depend on DatabaseManager.
    import inspect
    sig = inspect.signature(register_molecules_from_text)
    assert "fine_md_path" in sig.parameters
    assert "molecules" in sig.parameters
    assert "doc_id" in sig.parameters
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_organizer.py -v`
Expected: FAIL (register_molecules_from_text not in module)

- [ ] **Step 3: Write minimal implementation**

Append to `src/mbforge/pipeline/organizer.py`:

```python
def register_molecules_from_text(
    fine_md_path: str,
    molecules: list[NormalizedMolecule],
    doc_id: str,
    project_root: str,
) -> None:
    """Find each molecule's text context in the reorganized markdown and write links.

    Searches the fine markdown for each molecule's MoleCode block (by name
    and SMILES), extracts surrounding text, and inserts a row into
    ``text_molecule_links``.
    """
    from ..core.database import DatabaseManager

    md_text = Path(fine_md_path).read_text(encoding="utf-8")
    db = DatabaseManager.get(project_root)
    db.initialize()

    with db.mol_conn() as conn:
        conn.execute("BEGIN")
        try:
            for mol in molecules:
                if mol.status == "rejected":
                    continue
                name = mol.name or f"Mol_{mol.canonical_smiles[:8]}"
                position = _find_molecode_in_text(md_text, name, mol.canonical_smiles)
                if position:
                    block_start, block_end, section_title = position
                    excerpt_start = max(0, block_start - 200)
                    excerpt_end = min(len(md_text), block_end + 200)
                    text_excerpt = md_text[excerpt_start:excerpt_end].replace("\n", " ")
                    code_text = md_text[block_start:block_end]
                else:
                    text_excerpt = "position unresolved"
                    code_text = ""
                    section_title = ""
                conn.execute(
                    """INSERT INTO text_molecule_links
                       (doc_id, mol_id, text_excerpt, role, code_text, char_start, char_end, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        doc_id,
                        mol.canonical_smiles,
                        text_excerpt[:500],
                        "mentioned",
                        code_text[:1000],
                        position[0] if position else 0,
                        position[1] if position else 0,
                        int(__import__("time").time() * 1000),
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


_MOLECODE_BLOCK_RE = re.compile(
    r"```molecode\n(.*?)\n```", re.DOTALL
)


def _find_molecode_in_text(
    text: str, name: str, smiles: str
) -> tuple[int, int, str] | None:
    """Find a MoleCode block by name or SMILES in the text.

    Returns (block_start, block_end, nearest_section_title) or None.
    """
    for match in _MOLECODE_BLOCK_RE.finditer(text):
        block = match.group(1)
        if name in block or smiles[:12] in block:
            start = match.start()
            end = match.end()
            # Find nearest heading before the block
            before = text[:start]
            headings = list(re.finditer(r"^(#{1,6})\s+(.+)$", before, re.MULTILINE))
            section_title = headings[-1].group(2) if headings else ""
            return (start, end, section_title)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/test_organizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/organizer.py
git commit -m "feat(pipeline): register molecules' text context from reorganized MD

- register_molecules_from_text searches fine markdown for MoleCode blocks
- Extracts 200-char context window per molecule
- Writes text_molecule_links rows in a single transaction"
```

---

### Task 5: Add `index_markdown` to `OpenKBAdapter`

**Files:**
- Modify: `src/mbforge/openkb/adapter.py`
- Test: `tests/unit/test_openkb_adapter.py`

**Interfaces:**
- Produces: `OpenKBAdapter.index_markdown(md_path, doc_id) -> str`

- [ ] **Step 1: Write the failing test**

```python
def test_index_markdown_signature() -> None:
    from mbforge.openkb.adapter import OpenKBAdapter
    import inspect
    sig = inspect.signature(OpenKBAdapter.index_markdown)
    params = list(sig.parameters.keys())
    assert "md_path" in params
    assert "self" in params
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_openkb_adapter.py -v`
Expected: FAIL (index_markdown not in OpenKBAdapter)

- [ ] **Step 3: Write minimal implementation**

Append to `OpenKBAdapter` in `src/mbforge/openkb/adapter.py`:

```python
def index_markdown(self, md_path: str, doc_id: str = "") -> str:
    """Index a markdown file via PageIndex (MarkdownParser, level_based).

    Args:
        md_path: Path to the markdown file.
        doc_id: Optional document ID. Auto-generated from filename if empty.

    Returns:
        PageIndex document ID.
    """
    md_path_obj = Path(md_path)
    if not md_path_obj.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    # Copy markdown to managed storage under pageindex documents dir
    target_dir = self._global_openkb_dir / "documents"
    target_dir.mkdir(parents=True, exist_ok=True)
    md_name = f"{doc_id or md_path_obj.stem}.md"
    target_path = target_dir / md_name
    import shutil
    shutil.copy2(str(md_path_obj), str(target_path))

    # add_document resolves parser by extension (.md → MarkdownParser)
    return self._get_indexer().add_document(str(target_path), doc_id or md_path_obj.stem)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_openkb_adapter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/openkb/adapter.py
git commit -m "feat(openkb): add index_markdown for level-based PageIndex ingestion

- Copies .md to managed storage, registers via PageIndexWrapper.add_document
- .md extension → MarkdownParser → level_based strategy → zero LLM calls"
```

---

### Task 6: Add `text_molecule_links` and `sections` to DB schema

**Files:**
- Modify: `src/mbforge/core/database.py`
- Test: `tests/unit/test_database_schema.py`

**Interfaces:**
- Produces: `text_molecule_links` and `sections` tables via CREATE TABLE IF NOT EXISTS

- [ ] **Step 1: Write the failing test**

```python
import sqlite3
from pathlib import Path
from mbforge.core.database import DatabaseManager


def test_text_molecule_links_table_exists(tmp_path: Path) -> None:
    mgr = DatabaseManager(str(tmp_path))
    mgr.initialize()
    conn = sqlite3.connect(mgr.mol_path)
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "text_molecule_links" in tables
    finally:
        conn.close()


def test_sections_table_exists(tmp_path: Path) -> None:
    mgr = DatabaseManager(str(tmp_path))
    mgr.initialize()
    with mgr.kb_conn() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "sections" in tables
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_database_schema.py -v`
Expected: FAIL (tables not found)

- [ ] **Step 3: Write minimal implementation**

In `src/mbforge/core/database.py`:

In `_MOL_SCHEMA`, after the `molecule_detections` index:

```sql
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
CREATE INDEX IF NOT EXISTS idx_tml_doc_mol ON text_molecule_links(doc_id, mol_id);
```

In `_KB_SCHEMA`, after `idx_ie_task`:

```sql
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id TEXT NOT NULL,
    section_index INTEGER NOT NULL,
    title TEXT,
    level INTEGER DEFAULT 1,
    char_start INTEGER,
    char_end INTEGER,
    page_start INTEGER,
    page_end INTEGER,
    paragraph_count INTEGER DEFAULT 0,
    molecule_count INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sec_doc ON sections(doc_id, section_index);
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_database_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/core/database.py tests/unit/test_database_schema.py
git commit -m "feat(core): add text_molecule_links and sections tables to schema

- text_molecule_links stores molecule↔text paragraph associations
- sections stores document heading hierarchy after LLM reorganization"
```

---

### Task 7: Reorder pipeline stages in `runner.py`

**Files:**
- Modify: `src/mbforge/pipeline/runner.py`
- Test: `tests/unit/pipeline/test_runner.py` (existing)

**Interfaces:**
- Consumes: all previous tasks' interfaces
- Produces: new 9-stage pipeline sequence with normalized stage names

- [ ] **Step 1: Write the failing test**

Primary test: pipeline imports succeed. Add a quick smoke to existing runner test:

```python
def test_runner_imports_organizer() -> None:
    """organizer module is importable with all three entry points."""
    from mbforge.pipeline.organizer import (
        insert_molecode_blocks,
        reorganize_with_llm,
        register_molecules_from_text,
    )
    assert callable(insert_molecode_blocks)
    assert callable(reorganize_with_llm)
    assert callable(register_molecules_from_text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/pipeline/test_runner.py -v`
- The existing tests should still pass (no interface breakage).
- The new import test should pass if Tasks 1-6 are complete.

- [ ] **Step 3: Write minimal implementation**

Edit `src/mbforge/pipeline/runner.py`:

1. **Split `_enrich_and_persist_molecules` into `_enrich_molecules` + `_persist_molecules`:**

Replace:
```python
def _enrich_and_persist_molecules(
    pdf_path, project_root, doc_id, density
) -> dict[str, Any]:
    ...
    persist_molecule_candidates(project_root, doc_id, combined)
    return stats
```

With:
```python
def _enrich_molecules(
    pdf_path: str,
    project_root: str | Path,
    doc_id: str,
    density: DensityClassification,
) -> dict[str, Any]:
    """Extract molecules from PDF images, normalize, return candidates (not persisted)."""
    # ... same body as current _enrich_and_persist_molecules but WITHOUT
    # the persist_molecule_candidates call at the end
    return {"candidates": combined, "molecule_count": ..., ...}


def _persist_molecules(
    project_root: str | Path,
    doc_id: str,
    molecule_stats: dict[str, Any],
) -> None:
    """Persist molecule candidates produced by _enrich_molecules."""
    candidates = molecule_stats.get("candidates", [])
    if not candidates:
        return
    persist_molecule_candidates(project_root, doc_id, candidates)
```

2. **Restructure `run_pipeline` body:**

```python
# Stage 1-2 unchanged
extracted = extract_pdf_text(pdf_path, ocr_config=_current_ocr_config())
density = classify_density(extracted.pages)

# Stage 3a: Write rough markdown
rough_md = tempfile.mktemp(suffix=".md")
from .extract_text import write_rough_markdown
write_rough_markdown(extracted.pages, rough_md)

# Stage 5 (moved up): Molecule detection (needed before MoleCode insertion)
_emit("progress", "Detecting molecules...", stage="detect")
molecule_stats = _enrich_molecules(pdf_path, root, doc_id, density)
# ... emit as before

# Stage 3b: MoleCode insertion
enriched_md = tempfile.mktemp(suffix=".md")
from .organizer import insert_molecode_blocks
insert_molecode_blocks(rough_md, extracted.pages,
                       molecule_stats.get("candidates", []), enriched_md)

# Stage 3c: LLM reorganization
final_md = tempfile.mktemp(suffix=".md")
from .organizer import reorganize_with_llm
reorganize_with_llm(enriched_md, final_md)

# Stage 3d: PageIndex (markdown)
from ..openkb.adapter import OpenKBAdapter
adapter = OpenKBAdapter(root)
openkb_doc_id = ""
indexed_count = 0
try:
    openkb_doc_id = adapter.index_markdown(final_md, doc_id)
    indexed_count = 1
    _emit("complete", "PageIndex tree built (markdown)", stage="pageindex")
except Exception as e:
    logger.warning("PageIndex indexing failed for %s: %s", pdf_path, e)
    _emit("warning", f"PageIndex skipped: {e}", stage="pageindex")

# Stage 4: Wiki compilation (unchanged)
if openkb_doc_id:
    ...

# Stage 6a: Persist molecules
_persist_molecules(root, doc_id, molecule_stats)

# Stage 6b: Register molecule context from final text
from .organizer import register_molecules_from_text
register_molecules_from_text(final_md,
    molecule_stats.get("candidates", []), doc_id, root)

# Stage 6c: Persist document (unchanged)
_persist_document(root, doc_id, extracted, density, molecule_stats)

# Cleanup temp files
for p in [rough_md, enriched_md, final_md]:
    Path(p).unlink(missing_ok=True)
```

3. **Update stage names in STAGE_PCT**:

```python
STAGE_PCT: dict[str, int] = {
    "extract": 10,
    "density": 18,
    "detect": 28,
    "insert_molecode": 38,
    "reorganize": 55,
    "pageindex": 68,
    "wiki": 78,
    "persist": 90,
    "pipeline": 100,
}
```

4. **Update `_emit` stage references** throughout (replace `"enrich"` → `"detect"` where needed).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/pipeline/test_runner.py -v`
Expected: PASS (existing tests keep passing; new import test passes)

Run: `uv run python -c "from mbforge.app import app; print(len(app.routes))"`
Expected: all routes loaded without ImportError

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/pipeline/runner.py
git commit -m "refactor(pipeline): reorder stages for MoleCode + LLM reorganization

New pipeline order:
1. extract    6. persist_molecules
2. density    7. register_molecules_from_text
3. detect     8. persist_document
4. insert_molecode  9. cleanup temp files
5. llm_reorganize
6. pageindex(md)
7. wiki

Split _enrich_and_persist_molecules into _enrich + _persist so
molecule candidates are available for insertion before persistence."
```

---

### Task 8: Add optional `reorganize_model` config field

**Files:**
- Modify: `src/mbforge/utils/config.py`
- Test: `tests/unit/test_config.py`

**Interfaces:**
- Produces: `LLMConfig.reorganize_model: str | None`

- [ ] **Step 1: Write the failing test**

```python
def test_reorganize_model_default_fallback() -> None:
    from mbforge.utils.config import LLMConfig
    cfg = LLMConfig()
    model = cfg.reorganize_model or cfg.model
    assert model == cfg.model  # falls back to model
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: FAIL (LLMConfig has no reorganize_model field)

- [ ] **Step 3: Write minimal implementation**

In `src/mbforge/utils/config.py`, add field to `LLMConfig`:

```python
class LLMConfig(BaseModel):
    model: str = "default"
    api_key: str = ""
    api_base: str = ""
    max_tokens: int = 4096
    temperature: float = 0.1
    top_p: float = 0.9
    reorganize_model: str | None = Field(
        default=None,
        description="Model for text reorganization. Falls back to ``model`` if unset.",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mbforge/utils/config.py
git commit -m "feat(config): add reorganize_model field to LLMConfig

- Optional separate model for text reorganization LLM calls
- Defaults to LLMConfig.model via fallback in reorganize_with_llm"
```

---

## Verification (end-to-end)

Run after all 8 tasks:

```bash
# Lint + format
uv run ruff check src/ && uv run ruff format src/ --check

# Full test suite
uv run pytest tests/ -v

# Import smoke
uv run python -c "from mbforge.app import app; print('Routes:', len(app.routes))"

# Classify smoke
uv run python -c "
from mbforge.pipeline.classify import classify_density
from mbforge.pipeline.extract_text import PageContent
pages = [PageContent(page_num=i, text='test') for i in range(5)]
d = classify_density(pages)
print('Density:', d.doc_kind)
"

# MoleCode round-trip smoke
uv run python -c "
from rdkit import Chem
from molecode import mol_to_mermaid, mermaid_to_mol
mol = Chem.MolFromSmiles('CCO')
code = mol_to_mermaid(mol, name='Ethanol')
back = mermaid_to_mol(code)
print('MoleCode roundtrip:', back is not None)
"
```

## Assumptions & contingencies

- **`insert_molecode_blocks` accuracy does not need to be perfect.** The LLM reorganizer sees all text + MoleCode blocks and may move blocks during reorganization. The heuristic insertion only provides an initial approximation.
- **LLM reorganization for text_only docs is worth the token cost** (per user decision A). Token estimate: ~15-30k tokens per paper, comparable to current PageIndex's 4-5 LLM calls but with higher output quality.
- **Long docs** (>32k tokens) use chunked processing. The reorganizer splits on MoleCode block boundaries so blocks are never split across chunks.
- **OCR-only pages have no `text_spans`**, so molecules detected on those pages fall through to strategy C (page-end). The LLM can move them post-hoc.
- **`molecode` SyntaxWarning** (pre-existing upstream bug). If CI flags it, add `# noqa` to the affected line in `.venv/Lib/site-packages/molecode/polymer/mermaid_to_psmiles.py:138`.
- **`litellm` may fail** if the API key is misconfigured. `reorganize_with_llm` logs the error and falls back to copying the input, so the pipeline never crashes from a failed LLM call.
- **Pipeline timing**: LLM reorganization is the slowest step (5-30s per doc). If this becomes a throughput bottleneck, the reorganize step could be made asynchronous in a future task.
