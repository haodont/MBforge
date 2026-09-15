"""Classify normalized structures as concrete molecules or Markush parts.

The classifier is deliberately conservative around *contextual* Markush
signals.  A recognizer can turn a generic structure into a syntactically valid
closed SMILES, so ``no dummy atom`` is not sufficient evidence that a structure
belongs in the concrete-molecule library.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from rdkit import Chem, RDLogger

from mbforge.core.molecule import Molecule
from mbforge.utils.logger import get_logger

logger = get_logger("mbforge.pipeline.detection.structure_role")

RDLogger.DisableLog("rdApp.*")

DUMMY_SYMBOLS = {"*"}
FRAGMENT_MAX_HEAVY = 18
FRAGMENT_SINGLE_ATTACH_BONUS = 6
EXTENDED_FRAGMENT_MAX_HEAVY = FRAGMENT_MAX_HEAVY + FRAGMENT_SINGLE_ATTACH_BONUS
PROPERTY_KEY = "structure_role"
REASONS_KEY = "structure_role_reasons"
REVIEW_REQUIRED = "review_required"

# These markers are intentionally narrow.  A lone capital ``R`` is too noisy
# (it occurs in normal prose and compound labels), whereas a numbered R group,
# a formula designation, or explicit generic-structure wording is actionable.
#
# Each entry pairs a regex with a stable reason code.
# Reason codes are the public contract returned to the UI; the *order* of
# the patterns is not significant, but their *kind strings* must not drift
# without a coordinated update to the API and frontend.
_MARKUSH_CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "context_markush_keyword",
        re.compile(r"(?<![A-Za-z])markush(?![A-Za-z])", re.IGNORECASE),
    ),
    (
        "context_generic_formula",
        re.compile(
            r"(?<![A-Za-z])(?:general|generic)\s+(?:formula|structure)(?![A-Za-z])",
            re.IGNORECASE,
        ),
    ),
    (
        "context_formula_label",
        re.compile(
            r"(?<![A-Za-z0-9])formula\s+\(?[ivxlcdm]+\)?(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "context_optional_substitution",
        re.compile(r"\boptionally\s+substituted\b", re.IGNORECASE),
    ),
    (
        "context_variable_group",
        re.compile(
            r"\b(?:variable|unresolved)\s+(?:group|moiety|substituent)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "context_numbered_r_group",
        re.compile(
            r"(?<![A-Za-z0-9])R\s*[0-9₀-₉]+(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
    (
        "context_r_group_prose",
        re.compile(r"\b(?:R\s*group|substituent)s?\b", re.IGNORECASE),
    ),
    # A-labelled rings/attachment fragments are common in the source corpus.
    (
        "context_abstract_ring",
        re.compile(
            r"(?<![A-Za-z0-9])A\s*[0-9₀-₉]+(?![A-Za-z0-9])",
            re.IGNORECASE,
        ),
    ),
)

# Letter-suffixed labels in the reviewed patent are synthesis intermediates
# (for example ``1a`` or ``21-e``), while uppercase labels such as ``4A`` and
# ``4B`` are final stereoisomer labels.  A step-like label alone is not
# sufficient evidence on a general corpus (the same suffix appears in benign
# compound numbering), so the rule below is paired with the corroborating
# context tokens in ``INTERMEDIATE_CONTEXT_TOKENS``.  Only the combination
# withholds a candidate; a bare ``4A`` must remain eligible for the concrete
# library when its surrounding evidence is unambiguous.
_SYNTHETIC_INTERMEDIATE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:\d+[a-z](?:-\d+)?|\d+-[a-z](?:-\d+)?|\d+[A-Z]-\d+)(?![A-Za-z0-9])"
)

# Lower-cased tokens that corroborate a step-like label as a synthesis
# intermediate.  Presence of any of these (substring, case-insensitive) in the
# candidate's surrounding context is required to escalate the label signal
# into a review queue entry.  The list mixes English and the Chinese patent
# convention; ASCII tokens are stored lower-cased and the scan lower-cases
# the candidate context before matching.
INTERMEDIATE_CONTEXT_TOKENS: frozenset[str] = frozenset(
    {
        "intermediate",
        "intermediated",
        "intermediates",
        "中间体",
        "synthesis",
        "synthesis-step",
        "synthesized",
        "synthesis step",
        "precursor",
    }
)

# These signals are intentionally contextual.  A closed SMILES can be a
# valid RDKit molecule even when the source drawing represents a mixture or a
# provisional stereochemical assignment, so such candidates must not be
# silently promoted to the concrete library.
_AMBIGUITY_CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "context_mixture_or_isomer",
        re.compile(
            r"(?:mixture|mixed\s+isomer|stereoisomer(?:ic)?|enantiomer(?:ic)?|"
            r"diastereomer(?:ic)?|racemate|isomeric\s+mixture|"
            r"混合物|异构体|对映体|非对映体|外消旋|手性拆分|拆分产物|拆分)",
            re.IGNORECASE,
        ),
    ),
    (
        "context_stereochemistry_uncertain",
        re.compile(
            r"(?:(?<![A-Za-z])(?:Z\s*/\s*E|E\s*/\s*Z)(?![A-Za-z])|"
            r"(?:stereochemistry|configuration|geometry)\s*"
            r"(?:is\s+)?(?:uncertain|unknown|tentative|undetermined|"
            r"not\s+determined)|"
            r"(?:构型|双键构型|立体化学)\s*(?:暂定|暂不确定|不确定|未知)|"
            r"(?:暂定|暂不确定)\s*(?:构型|立体化学))",
            re.IGNORECASE,
        ),
    ),
)

# Stable reason codes for the dummy-atom branches. The strings here are
# the public contract returned by the API; they must not drift without a
# coordinated update to the API and frontend.
_DUMMY_REASONS = {
    "fragment": "dummy_atom_fragment",
    "scaffold": "dummy_atom_scaffold",
}


def _context_values(molecule: Molecule) -> list[str]:
    """Collect bounded, human-readable context used for role classification."""
    values: list[str] = []
    if molecule.name:
        values.append(molecule.name)
    properties = molecule.properties
    for key in (
        "context_texts",
        "detection_names",
        "role_contexts",
        "mixture_or_isomer_note",
        "stereochemistry_status",
    ):
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
            values.extend(item for item in value if isinstance(item, str))
    # Keep classification bounded even when a document contributes many
    # detections.  Presence of a marker is what matters, not full text volume.
    return [value[:1000] for value in values if value.strip()]


def _label_values(molecule: Molecule) -> list[str]:
    """Collect candidate labels without scanning broad prose contexts."""
    values: list[str] = []
    if molecule.name:
        values.append(molecule.name)
    properties = molecule.properties
    for key in (
        "normalized_label",
        "raw_coref_label",
        "label",
        "formula_label",
        "detection_names",
    ):
        value = properties.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
            values.extend(item for item in value if isinstance(item, str))
    return [value[:200] for value in values if value.strip()]


def _markush_context_signals(values: Iterable[str]) -> list[str]:
    """Return stable reason codes for contextual Markush markers."""
    signals: list[str] = []
    for value in values:
        for reason, pattern in _MARKUSH_CONTEXT_PATTERNS:
            if pattern.search(value) and reason not in signals:
                signals.append(reason)
    return signals


def _ambiguity_context_signals(values: Iterable[str]) -> list[str]:
    """Return stable reason codes for mixture/isomer uncertainty markers."""
    signals: list[str] = []
    for value in values:
        for reason, pattern in _AMBIGUITY_CONTEXT_PATTERNS:
            if pattern.search(value) and reason not in signals:
                signals.append(reason)
    return signals


def _intermediate_label_signals(
    label_values: Iterable[str], context_values: Iterable[str]
) -> list[str]:
    """Return a review signal for step-like labels with intermediate context.

    A bare lowercase-suffix label such as ``1a`` is corpus-specific; on a
    general corpus it would shadow many benign labels.  The signal fires only
    when a step-like label is paired with at least one corroborating token
    from ``INTERMEDIATE_CONTEXT_TOKENS`` in the candidate's surrounding
    evidence.  Without that context the candidate falls through to the normal
    final-label path (same as ``4A``/``4B``).
    """
    has_step_label = any(
        _SYNTHETIC_INTERMEDIATE_LABEL_RE.search(value) for value in label_values
    )
    if not has_step_label:
        return []
    if not _has_intermediate_context(context_values):
        return []
    return ["context_synthetic_intermediate_label"]


def _has_intermediate_context(values: Iterable[str]) -> bool:
    """Return True when any value contains a corroborating intermediate token."""
    for value in values:
        lowered = value.lower()
        if any(token in lowered for token in INTERMEDIATE_CONTEXT_TOKENS):
            return True
    return False


def _dummy_counts(smiles: str) -> tuple[bool, int, int] | None:
    """Return dummy presence, count, and heavy atoms, or ``None`` if invalid."""
    if not smiles.strip():
        return None
    try:
        parsed = Chem.MolFromSmiles(smiles)
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not parse structure role SMILES %r: %s", smiles, exc)
        return None
    if parsed is None:
        return None
    dummy_count = sum(
        atom.GetSymbol() in DUMMY_SYMBOLS or atom.GetAtomicNum() == 0
        for atom in parsed.GetAtoms()
    )
    return dummy_count > 0, dummy_count, parsed.GetNumHeavyAtoms()


def classify_structure_role(molecule: Molecule) -> str:
    """Classify a candidate and store the result in its properties.

    Rejected candidates remain rejected; callers decide whether to persist them.
    Invalid or empty SMILES conservatively become review candidates so they
    cannot enter the complete-molecule library through a malformed fallback
    path.  Normalized invalid records are normally already ``rejected`` and do
    not reach this branch.
    """
    if molecule.status == "rejected":
        return "rejected"

    reasons: list[str] = []
    counts = _dummy_counts(molecule.canonical_smiles)
    if counts is None:
        role = REVIEW_REQUIRED
        reasons.append("invalid_or_empty_structure")
    else:
        has_dummy, attachment_count, heavy_atoms = counts
        if molecule.properties.get("markush") is True and not has_dummy:
            role = REVIEW_REQUIRED
            reasons.append("markush_without_dummy")
        elif not has_dummy:
            context_values = _context_values(molecule)
            context_signals = _markush_context_signals(context_values)
            context_signals.extend(_ambiguity_context_signals(context_values))
            label_signals = _intermediate_label_signals(
                _label_values(molecule), context_values
            )
            if context_signals or label_signals:
                # A closed SMILES plus Formula I/R-group context is precisely
                # the failure mode we must not silently import as a concrete
                # molecule.  Preserve it for review instead.
                role = REVIEW_REQUIRED
                reasons.extend(context_signals)
                reasons.extend(label_signals)
            else:
                role = "complete"
        elif heavy_atoms <= FRAGMENT_MAX_HEAVY or (
            attachment_count == 1 and heavy_atoms <= EXTENDED_FRAGMENT_MAX_HEAVY
        ):
            role = "fragment"
            reasons.append(_DUMMY_REASONS["fragment"])
        else:
            role = "scaffold"
            reasons.append(_DUMMY_REASONS["scaffold"])

    if not reasons and role == "complete":
        reasons.append("closed_structure_without_markush_context")
    molecule.properties[PROPERTY_KEY] = role
    molecule.properties[REASONS_KEY] = reasons
    return role
