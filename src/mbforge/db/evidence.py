"""Read helpers for the molecule ``evidence`` table.

The ``evidence`` table is the molecule-centric store of a document's observed
molecules (figure/text/table rows, each carrying page + bbox + context).  These
functions return flat row dicts; the service layer shapes them into the API
contract.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from mbforge.db.sqlite.database import DatabaseManager

_COLUMNS = (
    "id, evidence_id, canonical_smiles, doc_id, page, "
    "bbox_x0, bbox_y0, bbox_x1, bbox_y1, crop_relpath, "
    "context_text, code_text, role, kind, confidence, source_type, created_at"
)


def list_molecule_evidence(
    library_root: str | Path, canonical_smiles: Sequence[str]
) -> list[dict[str, Any]]:
    """Return every ``evidence`` row for the given canonical SMILES.

    Sort order: canonical_smiles, kind, doc_id, page, id (the list view and the
    full-chain view share it; the caller applies its own per-molecule limit).
    """
    canonicals = [c for c in canonical_smiles if c]
    if not canonicals:
        return []
    placeholders = ",".join("?" for _ in canonicals)
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            f"SELECT {_COLUMNS} FROM evidence "
            f"WHERE canonical_smiles IN ({placeholders}) "
            "ORDER BY canonical_smiles, kind, doc_id, page, id",
            canonicals,
        ).fetchall()
    return [dict(row) for row in rows]


def evidence_for_molecules(
    library_root: str | Path,
    mol_ids: Sequence[str],
    canonicals: Sequence[str],
) -> list[dict[str, Any]]:
    """Return ``evidence`` rows matching any ``mol_id`` or canonical SMILES."""
    mol_ids = [m for m in mol_ids if m]
    canonicals = [c for c in canonicals if c]
    clauses: list[str] = []
    params: list[Any] = []
    if mol_ids:
        clauses.append(f"mol_id IN ({','.join('?' * len(mol_ids))})")
        params.extend(mol_ids)
    if canonicals:
        clauses.append(f"canonical_smiles IN ({','.join('?' * len(canonicals))})")
        params.extend(canonicals)
    if not clauses:
        return []
    db = DatabaseManager.get(str(library_root))
    with db.mol_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM evidence WHERE {' OR '.join(clauses)}", params
        ).fetchall()
    return [dict(row) for row in rows]


__all__ = ["evidence_for_molecules", "list_molecule_evidence"]
