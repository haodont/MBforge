"""Pair an activity reading with the structure the patent itself declares.

A patent states the mapping in its own text. An example heading prints the
compound's full systematic name *and* the designation the activity table uses:

    实施例1: N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)
             -1-(2-(甲基磺酰基)乙基)-1H-吡唑-4-甲酰胺三氟乙酸盐(化合物1)的制备

So the join key does not have to be recovered from a detected label beside a
drawing; the document declares it. Measured on CN120329282A: 23 examples declare
both, 14 of those numbers also carry activity, and together they cover 17 of the
document's 19 printed readings.

The example's printed mass can be compared with the candidate's calculated
``[M+H]+`` as a consistency check. Mass agreement cannot establish structure
identity or distinguish isomers and must never supply a missing designation.

What this does NOT do: invent a structure. When the document declares a name but
draws no structure, the pair is reported as a gap. That is the honest outcome — a
wrong structure paired with a real measurement is worse than a missing pair.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mbforge.domain.evidence_kind import IMAGE, MOLECULE, UnknownKind, category_of
from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: ``实施例1: <name>(化合物1)的制备`` — the Chinese declaration this module reads.
_EXAMPLE_HEADING = re.compile(
    r"实施例\s*(?P<example>\d+)\s*[:：]\s*(?P<body>[^\n]{2,400})"
)
#: ``Example 1. 3-(2,4-Difluorophenoxy)-7-(...)-1,6-naphthyridine`` — the US form.
#: The name must be in the same evidence row, after a period or colon.
_EXAMPLE_HEADING_EN = re.compile(
    r"\bExample\s*(?P<example>\d+)\s*(?:[.:：]|\s-\s)\s*(?P<body>[^\n]{10,400})"
)
#: The designation the heading prints for its product, Chinese form. The
#: filing also writes ``(目标化合物11)``; the qualifier is the document saying
#: "the product of this example", not a different designation.
_DECLARED_DESIGNATION = re.compile(
    r"[(（]\s*(?:目标)?\s*化合物\s*(?P<key>\d+[A-Za-z-]*)\s*[)）]"
)
#: ``实施例17：目标化合物17的制备`` declares the same relation without
#: parentheses. Only a heading that *starts* with the phrase counts, so a name
#: that merely mentions a prepared compound cannot claim the example.
_BARE_DECLARATION = re.compile(
    r"^\s*(?:目标)?\s*化合物\s*(?P<key>\d+[A-Za-z-]*)\s*(?:的)?\s*(?:制备|合成)"
)
#: The designation in an English filing: ``Compound 1`` / ``(Compound 1)``.
_DECLARED_DESIGNATION_EN = re.compile(r"\b[Cc]ompound\s+(?P<key>\d+[A-Za-z]?)\b")
#: PDF typesetting splits a word across a line: ``dif-luoropiperidin`` is
#: ``difluoropiperidin``. The split is a hyphen between two lowercase runs; a real
#: substituent hyphen (``1-yl``, ``4,4-difluoro``) has a digit or bracket on the
#: left, so it is left alone.
_LINEBREAK_HYPHEN = re.compile(r"(?<=[a-z])-(?=[a-z]{2,})")
#: A salt or solvate is stated after the parent name; the structure is the parent.
_SALT_SUFFIX_EN = re.compile(
    r"\s*(?:hydrochloride|hydrobromide|trifluoroacetate|sulfate|phosphate|"
    r"sodium salt|potassium salt|acetate|mesylate|salt|hydrate)(?:\s+hydrate)?\s*$",
    re.IGNORECASE,
)
#: A salt form is stated after the parent name; the structure belongs to the parent.
_SALT_SUFFIX = re.compile(
    r"(?:三氟乙酸盐|盐酸盐|氢溴酸盐|硫酸盐|磷酸盐|钠盐|钾盐|醋酸盐|甲磺酸盐|"
    r"三氟甲磺酸盐|盐)\s*$"
)
#: ``m/z 544.2 [M+H]+`` / ``LC-MS,M/Z(ESI):544.2[M+H]+`` / ``m/z=406.2``.
#: The separators vary by filing and font: a colon, an equals sign, or nothing.
_MS_VALUE = re.compile(
    r"(\d{2,4}(?:\.\d+)?)\s*\[\s*M\s*[+-]"
    r"|M\s*[/／]\s*Z[^:：=]{0,20}[:：=]?\s*(\d{2,4}(?:\.\d+)?)",
    re.IGNORECASE,
)
#: Monoisotopic proton mass; ``[M+H]+`` is the neutral mass plus this.
_PROTON = 1.00728
#: Tolerance for mass consistency; agreement does not establish identity.
_MASS_TOLERANCE_DA = 0.6


@dataclass(frozen=True)
class DeclaredExample:
    """One example section: the designation it declares and its product mass."""

    example: str
    declared_key: str
    name: str
    page: int
    evidence_ids: tuple[str, ...]
    product_mz: float | None


@dataclass(frozen=True)
class StructureActivityPair:
    """A reading joined to the structure the document declares for it."""

    declared_key: str
    measurement_id: str
    mol_id: str
    smiles: str
    metric: str | None
    value: float | None
    unit: str
    verified_by_mass: bool
    printed_mz: float | None
    calculated_mz: float | None


def _is_text_row(row: object) -> bool:
    """Whether evidence can print a declaration.

    A molecule row stores its detection JSON, whose nearby-text fields repeat
    headings verbatim: reading it would mint a second declaration of the same
    example on the detection's page, and shift that section's product mass.
    A producer that never registered its label is treated as text, not dropped.
    """
    kind = str(getattr(row, "kind", "") or "")
    if not kind:
        return True
    try:
        return category_of(kind) not in {IMAGE, MOLECULE}
    except UnknownKind:
        return True


def extract_declared_examples(
    evidence: Sequence[object], doc_id: str
) -> list[DeclaredExample]:
    """Return every example whose heading declares both a name and a designation.

    This reader handles headings; declarations in running prose are read elsewhere.
    """
    sections: list[dict] = []
    for row in evidence:
        if not _is_text_row(row):
            continue
        text = str(getattr(row, "raw_text", "") or "")
        page = int(getattr(row, "page", 0) or 0)
        evidence_id = str(getattr(row, "evidence_id", "") or "")
        declaration = _parse_heading(text)
        if declaration is not None:
            sections.append(
                {
                    "example": declaration[0],
                    "declared_key": declaration[1],
                    "name": declaration[2],
                    "page": page,
                    "evidence_ids": [evidence_id],
                    "mz": [],
                }
            )
            continue
        if not sections:
            continue
        value = _mass_value(text)
        if value is not None:
            sections[-1]["mz"].append(value)

    examples: list[DeclaredExample] = []
    for section in sections:
        masses = section["mz"]
        examples.append(
            DeclaredExample(
                example=section["example"],
                declared_key=section["declared_key"],
                name=section["name"],
                page=section["page"],
                evidence_ids=tuple(section["evidence_ids"]),
                # The product's own characterization is the last mass printed in
                # its section: each earlier one belongs to an intermediate step.
                product_mz=masses[-1] if masses else None,
            )
        )
    logger.debug("declared examples for %s: %d", doc_id, len(examples))
    return examples


def _parse_heading(text: str) -> tuple[str, str, str] | None:
    """``(example, declared_key, name)`` from one evidence row, or ``None``.

    Two filing styles are recognised:

    * Chinese: ``实施例1: <name>(化合物1)的制备`` — the designation is printed in
      parentheses beside the name.
    * US/English: ``Example 1. 3-(2,4-Difluorophenoxy)-…-1,6-naphthyridine`` — the
      example number usually *is* the designation an activity table cites, so it is
      used directly; a ``Compound N`` in the same row wins when present, because
      that is the designation the document explicitly names.
    """
    heading = _EXAMPLE_HEADING.search(text)
    if heading is not None:
        body = heading.group("body")
        designation = _DECLARED_DESIGNATION.search(body)
        if designation is not None:
            name = body[: designation.start()].strip()
            name = _SALT_SUFFIX.sub("", name).strip(" ，,。;；：:")
            return heading.group("example"), designation.group("key"), name
        bare = _BARE_DECLARATION.match(body)
        if bare is not None:
            # ``实施例17：目标化合物17的制备`` states its product without
            # parentheses: the heading prepares that designation and no other.
            return heading.group("example"), bare.group("key"), ""

    heading = _EXAMPLE_HEADING_EN.search(text)
    if heading is not None:
        body = _LINEBREAK_HYPHEN.sub("", heading.group("body"))
        designation = _DECLARED_DESIGNATION_EN.search(body)
        key = (
            designation.group("key")
            if designation is not None
            else heading.group("example")
        )
        name = body
        if designation is not None and designation.start() > 0:
            name = body[: designation.start()]
        name = _SALT_SUFFIX_EN.sub("", name).strip(" .,;:")
        if name:
            return heading.group("example"), key, name
    return None


def _mass_value(text: str) -> float | None:
    match = _MS_VALUE.search(text)
    if match is None:
        return None
    raw = match.group(1) or match.group(2)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _exact_mass(smiles: str) -> float | None:
    if not smiles:
        return None
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import Descriptors

        RDLogger.DisableLog("rdApp.*")
        mol = Chem.MolFromSmiles(smiles)
        return Descriptors.ExactMolWt(mol) if mol is not None else None
    except Exception:  # noqa: BLE001 - a join must never break extraction
        return None


def _reading_designation(reading: Mapping[str, object]) -> str:
    """The designation a reading cites.

    A measurement stores it under ``provenance.reference_key`` (the printed
    ``化合物8`` normalised to ``8``); a plain dict caller may also pass it flat.
    """
    for key in ("reference_key", "declared_key"):
        value = reading.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    provenance = reading.get("provenance")
    if isinstance(provenance, Mapping):
        for key in ("reference_key", "reference_raw"):
            value = provenance.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _reading_value(reading: Mapping[str, object]) -> tuple[float | None, str, str]:
    """``(value, unit, metric)`` from a measurement's own value payload.

    A measurement keeps its numbers in ``value`` (``original_value`` /
    ``original_unit``) rather than on the outer object, and its metric in
    ``metric`` or ``activity_type``.
    """
    payload = reading.get("value")
    payload = payload if isinstance(payload, Mapping) else {}
    raw = payload.get("original_value", reading.get("original_value"))
    unit = payload.get("original_unit", reading.get("original_unit")) or ""
    metric = reading.get("metric") or reading.get("activity_type") or ""
    value = float(raw) if isinstance(raw, int | float) else None
    return value, str(unit), str(metric)


def pair_structure_activity(
    examples: Sequence[DeclaredExample],
    readings: Sequence[Mapping[str, object]],
    structures_by_label: Mapping[str, str],
) -> list[StructureActivityPair]:
    """Join readings to structures through the designation the document declares.

    *structures_by_label* is ``{designation: smiles}`` for the structures the
    pipeline recognised. A reading whose designation is absent produces no pair:
    the document declared a name but drew no structure, and that is a gap rather
    than something to guess at.

    When the example prints a product mass, the pair carries whether the
    structure reproduces it. A mismatch does not suppress the pair — the reading
    and the designation are still the document's own statement — but the flag
    reports mass consistency for review, not independent identity verification.
    """
    by_key = {example.declared_key: example for example in examples}
    keys_by_example: dict[str, set[str]] = {}
    for example in examples:
        keys_by_example.setdefault(example.example, set()).add(example.declared_key)
    pairs: list[StructureActivityPair] = []
    for reading in readings:
        key = _reading_designation(reading)
        provenance = reading.get("provenance")
        if (
            isinstance(provenance, Mapping)
            and provenance.get("reference_type") == "example"
        ):
            # Example 2 can prepare compound 1; equal digits do not prove identity.
            declared_keys = keys_by_example.get(key, set())
            if len(declared_keys) != 1:
                continue
            key = next(iter(declared_keys))
        smiles = structures_by_label.get(key)
        if not key or not smiles:
            continue
        example = by_key.get(key)
        printed = example.product_mz if example is not None else None
        calculated = None
        verified = False
        if printed is not None:
            base = _exact_mass(smiles)
            if base is not None:
                calculated = base + _PROTON
                verified = abs(printed - calculated) <= _MASS_TOLERANCE_DA
        value, unit, metric = _reading_value(reading)
        pairs.append(
            StructureActivityPair(
                declared_key=key,
                measurement_id=str(reading.get("measurement_id") or ""),
                mol_id=str(reading.get("mol_id") or ""),
                smiles=smiles,
                metric=metric or None,
                value=value,
                unit=unit,
                verified_by_mass=verified,
                printed_mz=printed,
                calculated_mz=calculated,
            )
        )
    return pairs


__all__ = [
    "DeclaredExample",
    "StructureActivityPair",
    "extract_declared_examples",
    "pair_structure_activity",
]
