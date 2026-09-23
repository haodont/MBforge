from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from pathlib import Path

from mbforge.application.pipeline.labels import (
    _EXPLICIT_COMPOUND_LABEL_RE,
    _explicit_compound_labels,
    _label_token,
)
from mbforge.application.pipeline.markdown.markers import _ESMILES_BLOCK_RE, _HEADING_RE
from mbforge.domain.molecule import Molecule
from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

__all__ = [
    "_EXPLICIT_COMPOUND_LABEL_RE",
    "_distant_label_contexts",
    "_explicit_compound_labels",
    "_label_token",
]


def _distant_label_contexts(
    text: str,
    name: str,
    blocks: list[re.Match[str]],
    *,
    window: int = 300,
    limit: int = 3,
) -> list[str]:
    """Collect nearby prose for explicit compound-label mentions.

    A structure block can be separated from the synthesis
    paragraph that explains a mixture, stereoisomer split, or provisional
    configuration. The block-local window remains the primary context; this
    helper adds only explicitly prefixed mentions such as ``化合物4A`` or
    ``compound 28`` and ignores occurrences inside ESMILES blocks.
    """
    token = _label_token(name)
    if not token:
        return []
    pattern = re.compile(
        rf"(?:(?:compound|example|molecule)\s+|(?:化合物|实施例)\s*)"
        rf"{re.escape(token)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )

    def in_esmiles_block(position: int) -> bool:
        return any(block.start() <= position < block.end() for block in blocks)

    contexts: list[str] = []
    for match in pattern.finditer(text):
        if in_esmiles_block(match.start()):
            continue
        start = max(0, match.start() - window)
        end = min(len(text), match.end() + window)
        excerpt = text[start:end].replace("\n", " ").strip()
        if excerpt and excerpt not in contexts:
            contexts.append(excerpt[:1200])
        if len(contexts) >= limit:
            break
    return contexts


def _find_esmiles_in_text(
    text: str, esmiles: str, candidate_id: str | None = None
) -> tuple[int, int, str] | None:
    matches = list(_ESMILES_BLOCK_RE.finditer(text))

    def _located(match: re.Match[str]) -> tuple[int, int, str]:
        start = match.start()
        end = match.end()
        headings = list(_HEADING_RE.finditer(text[:start]))
        section_title = headings[-1].group(2) if headings else ""
        return (start, end, section_title)

    if candidate_id:
        needle = f"%% candidate={candidate_id}"
        for match in matches:
            if any(line.strip() == needle for line in match.group(1).splitlines()):
                return _located(match)
    if esmiles:
        needle = esmiles.strip()
        for match in matches:
            if any(line.strip() == needle for line in match.group(1).splitlines()):
                return _located(match)
    return None


def enrich_molecule_contexts_from_markdown(
    md_path: str, molecules: list[Molecule], *, window: int = 300
) -> int:
    md_text = Path(md_path).read_text(encoding="utf-8")
    blocks = list(_ESMILES_BLOCK_RE.finditer(md_text))
    enriched = 0
    for molecule in molecules:
        if molecule.status == "rejected":
            continue
        position = _find_esmiles_in_text(
            md_text,
            molecule.esmiles,
            candidate_id=molecule.properties.get("candidate_id"),
        )
        if position is None:
            continue
        block_start, block_end, section_title = position
        excerpt_start = max(0, block_start - window)
        excerpt_end = min(len(md_text), block_end + window)
        excerpt = md_text[excerpt_start:excerpt_end].replace("\n", " ").strip()
        if section_title:
            excerpt = f"{section_title}: {excerpt}"
        if not excerpt:
            continue
        contexts: list[str] = molecule.properties.setdefault("role_contexts", [])
        context_added = False
        if excerpt not in contexts:
            contexts.append(excerpt[:1200])
            context_added = True
        for label_context in _distant_label_contexts(
            md_text, molecule.name, blocks, window=window
        ):
            if label_context in contexts:
                continue
            contexts.append(label_context)
            context_added = True
        # A block can have an image placeholder as its name, so the distant
        # lookup above cannot always derive a token.  Recover a label only
        # when the surrounding prose contains exactly one explicit compound
        # designation; multiple labels remain ambiguous and are ignored.
        surrounding = (
            md_text[excerpt_start:block_start] + "\n" + md_text[block_end:excerpt_end]
        )
        context_labels = _explicit_compound_labels(surrounding)
        if len(context_labels) == 1:
            labels = molecule.properties.setdefault("explicit_context_labels", [])
            if context_labels[0] not in labels:
                labels.append(context_labels[0])
                context_added = True
        if context_added:
            enriched += 1
    return enriched


def register_molecules_from_text(
    fine_md_path: str,
    molecules: list[Molecule],
    doc_id: str,
    library_root: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    from mbforge.application.ports import get_database

    md_text = Path(fine_md_path).read_text(encoding="utf-8")

    def _do_inserts(active_conn: sqlite3.Connection) -> None:
        now_ms = int(time.time() * 1000)
        for mol in molecules:
            if mol.status == "rejected" or mol.properties.get("structure_role") not in (
                None,
                "complete",
            ):
                continue
            name = mol.name or f"Mol_{mol.canonical_smiles[:8]}"
            position = _find_esmiles_in_text(
                md_text,
                mol.esmiles,
                candidate_id=mol.properties.get("candidate_id"),
            )
            if position is not None:
                block_start, block_end, _section_title = position
                excerpt_start = max(0, block_start - 200)
                excerpt_end = min(len(md_text), block_end + 200)
                text_excerpt = md_text[excerpt_start:excerpt_end].replace("\n", " ")
                code_text = md_text[block_start:block_end]
                char_start, char_end = block_start, block_end
            else:
                text_excerpt = "position unresolved"
                code_text = ""
                char_start, char_end = 0, 0
            # Ensure molecules row exists (canonical aggregate).
            active_conn.execute(
                """
                INSERT INTO molecules
                    (mol_id, smiles, esmiles, name, source_doc, source_type,
                     status, canonical_smiles)
                VALUES (?, ?, ?, ?, ?, 'text', 'pending', ?)
                ON CONFLICT(mol_id) DO UPDATE SET
                    canonical_smiles = COALESCE(molecules.canonical_smiles, excluded.canonical_smiles),
                    source_doc = COALESCE(NULLIF(molecules.source_doc, ''), excluded.source_doc),
                    name = CASE
                        WHEN TRIM(COALESCE(molecules.name, '')) = '' THEN excluded.name
                        ELSE molecules.name
                    END
                """,
                (
                    mol.canonical_smiles,
                    mol.canonical_smiles,
                    mol.esmiles,
                    name,
                    doc_id,
                    mol.canonical_smiles,
                ),
            )
            active_conn.execute(
                """INSERT INTO text_molecule_links
                   (doc_id, mol_id, text_excerpt, role,
                    code_text, char_start, char_end, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    doc_id,
                    mol.canonical_smiles,
                    text_excerpt[:500],
                    "mentioned",
                    code_text[:1000],
                    char_start,
                    char_end,
                    now_ms,
                ),
            )
            # First-class evidence row (text kind).
            active_conn.execute(
                """
                INSERT INTO evidence
                    (canonical_smiles, mol_id, doc_id, page,
                     context_text, code_text, role, kind, source_type)
                VALUES (?, ?, ?, NULL, ?, ?, 'mentioned', 'text', 'text')
                """,
                (
                    mol.canonical_smiles,
                    mol.canonical_smiles,
                    doc_id,
                    text_excerpt[:500],
                    code_text[:1000],
                ),
            )

    if conn is not None:
        # Caller owns the transaction; just do the inserts.
        _do_inserts(conn)
        logger.info(
            "register_molecules_from_text: %d rows inserted (shared txn) for doc_id=%s",
            len(molecules),
            doc_id,
        )
        return

    # Legacy path: own the transaction.
    db = get_database(library_root)
    db.initialize()
    with db.mol_conn() as local_conn:
        local_conn.execute("BEGIN")
        try:
            _do_inserts(local_conn)
            local_conn.commit()
            logger.info(
                "register_molecules_from_text: %d rows inserted for doc_id=%s",
                len(molecules),
                doc_id,
            )
        except Exception:
            local_conn.rollback()
            raise


async def register_molecules_from_text_async(
    fine_md_path: str,
    molecules: list[Molecule],
    doc_id: str,
    library_root: str,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Async wrapper that runs molecule registration off the event loop."""
    return await asyncio.to_thread(
        register_molecules_from_text,
        fine_md_path,
        molecules,
        doc_id,
        library_root,
        conn=conn,
    )
