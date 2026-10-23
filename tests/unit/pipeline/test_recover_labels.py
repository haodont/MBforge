"""Tests for MS-guided label recovery of placeholder-named molecules.

Scanned patents leave some final-compound figures without an OCR-readable
label; the preparation text's "化合物N … MS m/z X" paragraph plus the
family core re-attaches the label when mass, page and uniqueness agree.

Fixtures reuse the WO2026037254A1 family: the Markush scaffolds define the
core, and placeholder candidates are recognised family members whose figure
label was lost.
"""

from __future__ import annotations

from unittest.mock import MagicMock

# ``label_recovery`` imports ``markdown.markers``, so importing the module
# before its ``markdown`` parent package would close a cycle; the package
# re-exports the entry point, which keeps this test file order-independent.
from mbforge.service.pipeline.activity.family_gate import derive_family_core
from mbforge.service.pipeline.markdown import recover_labels_from_ms

SCAFFOLD_1 = (
    "*CC1(C*)CC(NC(=O)c2c([8*])nn([9*])c2[7*])CC(Nc2cc(C(F)(F)F)nc3ccc(Cl)cc23)C1"
)
SCAFFOLD_2 = "*/C=C1\\C=C(Nc2cc(C(F)(F)F)nc3ccc(Cl)cc23)CC(NC(=O)c2cnn(C)c2)C1"
SCAFFOLD_3 = "*c1ccc2nc(C(F)(F)F)cc(N[C@H]3C/C(=C/COC)C[C@@H](NC(=O)c4cnn(C)c4)C3)c2c1"

# A genuine family member whose figure label was lost to OCR.
FAMILY_MEMBER = "Cn1cc(C(=O)N[C@@H]2CC(=O)C[C@H](Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)C2)cn1"


def _mz_of(smiles: str) -> float:
    """[M+H]+ m/z of the largest fragment, computed the same way as the module."""
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    mol = Chem.MolFromSmiles(smiles)
    frags = Chem.GetMolFrags(mol, asMols=True)
    main = max(frags, key=lambda frag: frag.GetNumHeavyAtoms())
    return float(rdMolDescriptors.CalcExactMolWt(main)) + 1.0073


def _candidate(
    smiles: str,
    *,
    name: str = "",
    role: str = "complete",
    page_index: int = 24,
    status: str = "pending",
) -> MagicMock:
    cand = MagicMock()
    cand.status = status
    cand.canonical_smiles = smiles
    cand.esmiles = smiles
    cand.name = name
    cand.properties = {"structure_role": role}
    cand.detections = [MagicMock(page=page_index)]
    return cand


def _core() -> str:
    scaffolds = [
        _candidate(smiles, role="scaffold")
        for smiles in (SCAFFOLD_1, SCAFFOLD_2, SCAFFOLD_3)
    ]
    core = derive_family_core(scaffolds)
    assert core is not None
    return core


def _prep_paragraph(page: int, label: str, mz: float) -> str:
    return (
        f"<!-- PAGE {page} -->\n"
        f"得白色固体化合物{label}（7 mg，收率33%）。"
        f"MS m/z {mz:.1f} [M+H]$^{{+}}$。\n"
    )


def test_recovers_label_for_a_placeholder_figure_matching_the_prep_mass() -> None:
    """A figure on page P with the prep paragraph's mass on P±1 gets its label."""
    cand = _candidate(FAMILY_MEMBER, page_index=24)  # figure on page 25
    md = _prep_paragraph(25, "11", _mz_of(FAMILY_MEMBER))

    recoveries = recover_labels_from_ms(md, [cand], _core())

    assert len(recoveries) == 1
    assert recoveries[0].label == "11"
    assert recoveries[0].page == 25
    assert cand.name == "11"
    assert cand.properties["label_source"] == "ms_context"
    assert abs(cand.properties["ms_mz"] - _mz_of(FAMILY_MEMBER)) < 0.1

    # Rendered image markup is also an unlabeled figure placeholder.
    html = _candidate(
        FAMILY_MEMBER,
        name='<div style="text-align: center;"><img src="structure.jpg" /></div>',
        page_index=24,
    )

    recoveries = recover_labels_from_ms(md, [html], _core())

    assert [recovery.label for recovery in recoveries] == ["11"]
    assert html.name == "11"


def test_exact_page_label_beats_neighbouring_label() -> None:
    """Two labels compete for one candidate; the exact-page label wins."""
    cand = _candidate(FAMILY_MEMBER, page_index=25)  # figure on page 26
    mz = _mz_of(FAMILY_MEMBER)
    md = _prep_paragraph(25, "15", mz) + _prep_paragraph(26, "13", mz)

    recoveries = recover_labels_from_ms(md, [cand], _core())

    assert [recovery.label for recovery in recoveries] == ["13"]
    assert cand.name == "13"


def test_no_recovery_without_page_window_mass_uniqueness_or_core() -> None:
    """Every guard holds: page window, same-page uniqueness, candidate role,
    parseability, and a usable family core."""
    markdown = _prep_paragraph(25, "11", _mz_of(FAMILY_MEMBER))

    # Figure outside the page window.
    far = _candidate(FAMILY_MEMBER, page_index=9)  # figure on page 10
    assert recover_labels_from_ms(markdown, [far], _core()) == []
    assert far.name == ""

    # Two distinct family structures with identical exact mass (492.18
    # [M+H]+) — a case that genuinely occurs in the document.
    isomer_a = "CC(C)=C1C[C@H](NC(=O)c2cnn(C)c2)C[C@H](Nc2cc(C(F)(F)F)nc3ccc(Cl)cc23)C1"
    isomer_b = "Cn1cc(C(=O)N[C@H]2C[C@@H](Nc3cc(C(F)(F)F)nc4ccc(Cl)cc34)CC3(CCC3)C2)cn1"
    first = _candidate(isomer_a, page_index=24)
    second = _candidate(isomer_b, page_index=24)
    assert recover_labels_from_ms(markdown, [first, second], _core()) == []
    assert first.name == ""
    assert second.name == ""

    # Non-complete roles and unparseable SMILES are skipped.
    scaffold = _candidate(FAMILY_MEMBER, role="scaffold", page_index=24)
    broken = _candidate("not-a-smiles", page_index=24)
    assert recover_labels_from_ms(markdown, [scaffold, broken], _core()) == []
    assert scaffold.name == ""
    assert broken.name == ""

    # No (or unusable) core means no recovery.
    cand = _candidate(FAMILY_MEMBER, page_index=24)
    assert recover_labels_from_ms(markdown, [cand], None) == []
    assert recover_labels_from_ms(markdown, [cand], "not-a-smarts") == []
    assert cand.name == ""


def test_only_persisted_final_structures_can_claim_a_label() -> None:
    """A label is owned by the candidate that persists; rejected, Markush-role
    and scaffold candidates must never withhold it.

    Regression: in WO2026037254A1 a rejected look-alike and a Markush scaffold
    carried the OCR label '11', leaving the MS-verified final compound
    unlabeled (and a rejected duplicate tied the same-page uniqueness check).
    """
    markdown = _prep_paragraph(25, "11", _mz_of(FAMILY_MEMBER))

    named = _candidate("CCO", name="11")
    placeholder = _candidate(FAMILY_MEMBER, page_index=24)
    assert recover_labels_from_ms(markdown, [named, placeholder], _core()) == []
    assert named.name == "11"
    assert placeholder.name == ""

    rejected_named = _candidate("CCO", name="11", status="rejected")
    placeholder = _candidate(FAMILY_MEMBER, page_index=24)
    recoveries = recover_labels_from_ms(
        markdown, [rejected_named, placeholder], _core()
    )
    assert [recovery.label for recovery in recoveries] == ["11"]
    assert placeholder.name == "11"
    assert rejected_named.name == "11"

    scaffold_named = _candidate(SCAFFOLD_2, name="11", role="scaffold")
    placeholder = _candidate(FAMILY_MEMBER, page_index=24)
    recoveries = recover_labels_from_ms(
        markdown, [scaffold_named, placeholder], _core()
    )
    assert [recovery.label for recovery in recoveries] == ["11"]
    assert placeholder.name == "11"
    assert scaffold_named.name == "11"

    good = _candidate(FAMILY_MEMBER, page_index=24)
    rejected_twin = _candidate(FAMILY_MEMBER, page_index=24, status="rejected")
    recoveries = recover_labels_from_ms(markdown, [good, rejected_twin], _core())
    assert [recovery.label for recovery in recoveries] == ["11"]
    assert good.name == "11"
    assert rejected_twin.name == ""
