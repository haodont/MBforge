"""The vendored Chinese-name parser is a seam, and its output is chemistry.

Functions under test: ``mbforge.foundation.chemname.parse_name``.

Why this exists: a scanned patent often names a compound in prose on a page where
the structure was never drawn (a chiral SFC split reports only retention time and
LC-MS), so the printed name is the only route back to a structure. The vendored
CMNP parser reads those names; this seam decides what may reach the database.

The parser's SMILES assembly is being extended in its own repository, so a name it
reads may still yield no usable structure. The seam must therefore never hand on
an unchecked SMILES, and must never lose the AST — the AST is what scaffold
matching can use today.
"""

from __future__ import annotations

from rdkit import Chem, RDLogger
from rdkit.Chem import rdMolDescriptors

from mbforge.foundation.chemname import parse_name

RDLogger.DisableLog("rdApp.*")


def test_unparseable_input_returns_a_status_instead_of_raising() -> None:
    """Damaged names are ordinary input for a scanned patent, never an exception."""
    for raw in ("", "   ", "这不是一个化合物名称"):
        result = parse_name(raw)
        assert result.status in {"pending_review", "error"}
        assert result.ok is False
        assert result.smiles is None
        assert result.smiles_valid is False


def test_simple_molecules_produce_chemically_correct_smiles() -> None:
    """The structure a name yields is verified by formula and ring count.

    Checking only that RDKit parses the string is not enough — the assembly step
    has previously emitted ``C`` (methane) for ``氯苯``, which RDKit accepts
    happily. Formula plus ring count catches a dropped or altered scaffold.
    """
    expect = {
        "苯": ("C6H6", 1),
        "甲苯": ("C7H8", 1),
        "氯苯": ("C6H5Cl", 1),
        "乙酸": ("C2H4O2", 0),
    }

    for name, (formula, rings) in expect.items():
        result = parse_name(name)
        assert result.smiles_valid is True, f"{name} produced no usable SMILES"
        mol = Chem.MolFromSmiles(result.smiles or "")
        assert mol is not None
        assert rdMolDescriptors.CalcMolFormula(mol) == formula
        assert mol.GetRingInfo().NumRings() == rings


def test_a_ring_bearing_name_never_yields_an_acyclic_structure() -> None:
    """A name with a ring system must not come back as a chain.

    This is the guard that keeps a dropped scaffold out of the database: the AST
    states rings, so the SMILES must show rings, whatever the assembly did.
    """
    for ringed in ("苯", "甲苯", "氯苯"):
        result = parse_name(ringed)
        if not result.smiles:
            continue
        mol = Chem.MolFromSmiles(result.smiles)
        assert mol is not None and mol.GetRingInfo().NumRings() > 0


def test_ast_is_kept_even_when_no_usable_smiles_exists() -> None:
    """A missing SMILES must not throw away the AST.

    Callers use the AST's scaffold words to decide which drawn structure a name
    describes; that use does not depend on assembly being finished.
    """
    result = parse_name("甲苯")

    assert result.ast is not None
    assert result.ok is True


def test_heteroaromatic_scaffolds_parse_to_correct_structures() -> None:
    """Pyrazole and quinoline names must yield their real ring systems.

    These scaffolds dominate patent chemistry; a name the parser reads but whose
    SMILES drops or misbuilds the ring is worse than a refusal, because the wrong
    structure would enter the library silently. Formula and ring count decide.
    """
    expect = {
        "1H-吡唑-4-甲酰胺": ("C4H5N3O", 1),
        "喹啉-4-胺": ("C9H8N2", 2),
        "3-氯-1H-吡唑-4-甲酰胺": ("C4H4ClN3O", 1),
    }

    for name, (formula, rings) in expect.items():
        result = parse_name(name)
        assert result.smiles_valid is True, f"{name} produced no usable SMILES"
        mol = Chem.MolFromSmiles(result.smiles or "")
        assert mol is not None
        assert rdMolDescriptors.CalcMolFormula(mol) == formula
        assert mol.GetRingInfo().NumRings() == rings
