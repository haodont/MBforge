"""Unit tests for the Markush parser and coverage checker.

These tests are anchored on the real WO2026037254A1 Markush structure
(Formula I): a cyclohexane core with three attachment points carrying
R³, R⁴, and (R⁵)ₘ (m ∈ {0..4}). R¹ and R² are bound to the nitrogen
of the urea-bearing arm of the scaffold; concrete compounds 1-28
substitute those positions with H, F, methylene, cyclopropyl, and
small alkyl/alkenyl groups.

We do not need every compound here — a handful of representative
SMILES is enough to exercise the parse + coverage paths. The
constant scaffold piece across all examples is the CF₃/Cl-quinoline
arm with a 1-methyl-pyrazole-4-carboxamide; we collapse it to a
generic placeholder in the synthetic fixtures to keep the SMILES
short and RDKit-friendly.
"""

from __future__ import annotations

import pytest

from mbforge.domain.markush import check_markush_coverage, parse_markush

# Synthetic Markush that mirrors Formula I's cyclohexane core with
# three R-group attachment points. Each ``[*:N]`` is the explicit
# atom-map identity required by the parser; the carbonyl-amide tail is
# collapsed to ``[*:5]`` so the scaffold has five explicit sites.
FORMULA_I_SCAFFOLD = (
    "[*:1]C1CC([*:2])C([*:3])CC1[*:4]"  # cyclohexane + 4 sites (R³,R⁴,R⁵,R¹-stub)
)
FORMULA_I_FULL = (
    # Minimal 4-site form: cyclohexane + 3 R-sites + 1 carbonyl stub.
    # (Real Formula I has R³, R⁴, (R⁵)ₘ, R¹, R² but we collapse the
    # nitrogen arms to single attachment points for the parser test.)
    "[*:1]C1CCC([*:2])([*:3])C1[*:4]"
)

# Compound 1 from page 8 of the patent — the H/H variant.
# The CF₃/Cl quinoline + pyrazole are collapsed to ``X~Y`` for brevity.
COMPOUND_1 = "FC(F)(F)c1cc2c(Cl)cc(NC(=O)NC3CCC(C(=O)NC4=CN(C)N=C4)CC3)cc2nc1"


@pytest.fixture
def parsed_full():
    return parse_markush(
        FORMULA_I_FULL,
        r_group_definitions={
            "R1": "H or C1-4 alkyl",
            "R2": "H or halogen",
            "R3": "H or C1-4 alkyl",
            "R4": "C1-6 alkyl or cycloalkyl",
        },
    )


def test_parse_markush_extracts_sites_definitions_and_warns(parsed_full):
    """``parse_markush`` maps ``[*:N]`` to ``sites``, keeps caller-supplied
    ``r_groups`` definitions, and warns on a bare ``*`` (no explicit atom map)."""
    labels = [s.site_label for s in parsed_full.sites]
    assert labels == ["R1", "R2", "R3", "R4"]
    assert [s.atom_map_num for s in parsed_full.sites] == [1, 2, 3, 4]

    label_to_def = {r.label: r.definition for r in parsed_full.r_groups}
    assert label_to_def["R1"] == "H or C1-4 alkyl"
    assert label_to_def["R4"] == "C1-6 alkyl or cycloalkyl"

    unlabelled = parse_markush("CCC*CCC")
    assert unlabelled.warnings, "expected an explicit-atom-map warning"
    assert any("explicit atom map" in w for w in unlabelled.warnings)


def test_check_markush_coverage_verdicts(parsed_full):
    """Coverage verdicts: absent core → ``none``; present core without textual
    R definitions → ``unknown`` (never a silent ``full``); a bare
    ``[*:N]``-only query → ``full``."""
    match_level, sites, details, _ = check_markush_coverage(parsed_full, "c1ccccc1")
    assert match_level == "none"
    assert sites == []
    assert any("core" in d for d in details)

    # A bare ``[*:N]``-only query trivially satisfies every site.
    bare = "[*:1]C1CCC([*:2])([*:3])C1[*:4]"
    match_level, sites, _, _ = check_markush_coverage(parsed_full, bare)
    assert match_level == "full"
    assert all(s.judgment == "within_scope" for s in sites)

    # Core present but no textual R definitions to certify a substituent:
    # the verdict must NOT be ``full``.
    parsed = parse_markush("CC[*:1]CC")
    match_level, sites, _, _ = check_markush_coverage(parsed, "CCN(CC)CC")
    assert match_level in {"unknown", "none"}, (
        f"expected unknown/none, got {match_level}"
    )
    if sites:
        assert all(s.judgment == "unknown" for s in sites)

    # Compound 1 (H-substituted variant) must never be silently called ``full``.
    compound_core = parse_markush("[*:1]C1CCC(C(=O)N)([*:3])C1[*:4]")
    match_level, _, details, _ = check_markush_coverage(compound_core, COMPOUND_1)
    assert match_level in {"none", "unknown"}, (
        f"unexpected match_level={match_level}; details={details}"
    )


def test_check_markush_coverage_degrades_on_bad_input():
    """Invalid SMILES or an empty Markush → ``unknown`` with a diagnostic, never
    a crash or a false ``full``."""
    parsed = parse_markush("[*:1]C1CCC([*:2])([*:3])C1[*:4]")
    match_level, _, _, _ = check_markush_coverage(parsed, "not a smiles @@@")
    assert match_level == "unknown"

    empty = parse_markush("")
    match_level, _, details, _ = check_markush_coverage(empty, "CCO")
    assert match_level == "unknown"
    assert details, "expected at least one diagnostic detail"
