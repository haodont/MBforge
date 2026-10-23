"""Chinese chemistry-name parsing, vendored from the CMNP project.

A scanned patent often names a compound in prose — ``得到化合物
N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)-...`` — on a page where the
structure itself was never drawn as an image. MolDet cannot see a structure that
is not there, so the name is the only route back to it.

CMNP (https://github.com/.../CMNP, in-tree copy under ``chemname/``) is a
pure-stdlib rule parser for Chinese organic-chemistry names. This package is the
MBForge-side seam over it: it isolates the vendored module, never raises on bad
input, and refuses to hand back a SMILES that RDKit cannot parse.

The vendored parser is a moving target. Its SMILES assembly produces real
structures for the scaffolds measured so far (benzene/toluene/chlorobenzene/acetic
acid, pyrazole, quinoline), and it is still being extended — in particular
"thioamide" parents (``丙硫酰胺``) are not recognised yet, which is why several
long patent names stay ``pending_review``.

Callers must therefore treat a parse result as *evidence*, never as a confirmed
structure: ``status`` says what the parser managed, and only ``smiles_valid``
decides whether a structure may be used downstream at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from mbforge.foundation.chemname import parser as _parser
from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: What the parser managed to do with a name.
ParseStatus = Literal["ok", "pending_review", "error"]


@dataclass(frozen=True)
class ParsedName:
    """One name's parse result, safe to carry across a layer boundary.

    ``smiles`` is present only when RDKit accepts it. A name the parser reads but
    whose SMILES does not validate keeps its ``ast`` (useful for scaffold
    matching) and reports ``smiles_valid=False``.
    """

    name: str
    status: ParseStatus
    normalized: str = ""
    ast: dict[str, Any] | None = None
    smiles: str | None = None
    smiles_valid: bool = False
    warnings: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None

    @property
    def ok(self) -> bool:
        """Whether the name parsed into an AST."""
        return self.status == "ok" and self.ast is not None


def _rdkit_accepts(smiles: str | None) -> bool:
    """Whether RDKit can read *smiles* as a molecule.

    This is the gate that keeps an incomplete assembly step out of the database:
    the vendored parser can emit a string that is not a molecule at all, and a
    wrong structure is worse than a missing one.
    """
    if not smiles:
        return False
    try:
        from rdkit import Chem, RDLogger

        RDLogger.DisableLog("rdApp.*")
        return Chem.MolFromSmiles(smiles) is not None
    except Exception:  # noqa: BLE001 - a parser stack must never break extraction
        return False


def _ast_names_a_ring(ast: dict[str, Any] | None) -> bool:
    """Whether the parsed name describes at least one ring.

    The vendored parser's assembly step drops ring systems: ``氯苯``
    (chlorobenzene) parses to the SMILES ``C`` — a valid molecule, and the wrong
    one. RDKit's acceptance check cannot see that, so the AST is compared against
    the emitted SMILES: a name with rings must yield a SMILES with rings.
    """
    if not ast:
        return False
    stack: list[Any] = [ast]
    seen = 0
    while stack and seen < 2000:
        node = stack.pop()
        seen += 1
        if isinstance(node, dict):
            if node.get("type") == "ring":
                return True
            words = node.get("words")
            if isinstance(words, list) and any(
                isinstance(word, str) and ("环" in word or "苯" in word)
                for word in words
            ):
                return True
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return False


def _smiles_agrees_with_ast(smiles: str, ast: dict[str, Any] | None) -> bool:
    """Reject a SMILES that contradicts the structure the name describes.

    A ring-bearing name must produce a ring-bearing molecule. This catches the
    assembly step silently dropping the scaffold while still emitting valid SMILES.
    """
    if not _ast_names_a_ring(ast):
        return True
    from rdkit import Chem

    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:  # noqa: BLE001
        return False
    return mol is not None and mol.GetRingInfo().NumRings() > 0


def parse_name(raw: str) -> ParsedName:
    """Parse one Chinese chemistry name into an AST and, when possible, SMILES.

    Never raises: an unparseable or damaged name is ordinary input for a scanned
    patent, and the caller's job is to keep extracting.
    """
    name = (raw or "").strip()
    if not name:
        return ParsedName(name="", status="error", error="empty name")
    try:
        result = _parser.parse_one_with_smiles(name)
    except Exception as exc:  # noqa: BLE001 - the vendored parser may raise on odd input
        logger.debug("chemname: parse raised for %r: %s", name[:80], exc)
        return ParsedName(name=name, status="error", error=str(exc))

    status: ParseStatus = "ok" if result.get("status") == "ok" else "pending_review"
    ast = result.get("ast") if isinstance(result.get("ast"), dict) else None
    if status == "ok" and ast is None:
        status = "pending_review"
    smiles = result.get("smiles_gen") or result.get("smiles") or None
    valid = _rdkit_accepts(smiles) and _smiles_agrees_with_ast(smiles, ast)
    warnings = result.get("warn")
    return ParsedName(
        name=name,
        status=status,
        normalized=str(result.get("normalized") or ""),
        ast=ast,
        smiles=smiles if valid else None,
        smiles_valid=valid,
        warnings=tuple(warnings) if isinstance(warnings, list) else (),
    )


__all__ = ["ParsedName", "ParseStatus", "parse_name"]
