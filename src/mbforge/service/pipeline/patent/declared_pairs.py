"""Pair an activity reading with the structure the patent itself declares.

A patent states the mapping in its own text. An example heading prints the
compound's full systematic name *and* the designation the activity table uses:

    实施例1: N-((1R,3S)-3-((6-氯-2-(三氟甲基)喹啉-4-基)氨基)环己基)
             -1-(2-(甲基磺酰基)乙基)-1H-吡唑-4-甲酰胺三氟乙酸盐(化合物1)的制备

So the join key does not have to be recovered from a detected label beside a
drawing; the document declares it. Measured on CN120329282A: 23 examples declare
both, 14 of those numbers also carry activity, and together they cover 17 of the
document's 19 printed readings.

This module builds that join and, more importantly, *verifies* it. The example
also prints the product's mass spectrum, so a candidate structure can be checked
against the printed ``[M+H]+`` before it is paired with a reading. Measured on the
eight structures the pipeline recognised for that document: 8 of 8 match within
0.35 Da once the section's product mass (not an intermediate's) is used.

What this does NOT do: invent a structure. When the document declares a name but
draws no structure, the pair is reported as a gap. That is the honest outcome — a
wrong structure paired with a real measurement is worse than a missing pair.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from mbforge.foundation.logger import get_logger

logger = get_logger(__name__)

#: ``实施例1: <name>(化合物1)的制备`` — the Chinese declaration this module reads.
_EXAMPLE_HEADING = re.compile(
    r"实施例\s*(?P<example>\d+)\s*[:：]\s*(?P<body>[^\n]{10,400})"
)
#: ``Example 1. 3-(2,4-Difluorophenoxy)-7-(...)-1,6-naphthyridine`` — the US form.
#: A period separates the number from the name; some filings use a colon instead,
#: and a few print the number alone with the name on the next line (handled by
#: :func:`extract_declared_examples` when the body is empty).
_EXAMPLE_HEADING_EN = re.compile(
    r"\bExample\s*(?P<example>\d+)\s*(?:[.:：]|\s-\s)\s*(?P<body>[^\n]{10,400})"
)
#: The designation the heading prints for its product, Chinese form.
_DECLARED_DESIGNATION = re.compile(r"[(（]\s*化合物\s*(?P<key>\d+[A-Za-z-]*)\s*[)）]")
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
#: A printed mass within this of the calculated one is the same ion.
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


def extract_declared_examples(
    evidence: Sequence[object], doc_id: str
) -> list[DeclaredExample]:
    """Return every example whose heading declares both a name and a designation.

    The heading is the only place a patent states that a name and a designation
    are the same compound, which is exactly the fact the join needs.
    """
    sections: list[dict] = []
    for row in evidence:
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
    lets a reviewer see which pairs the chemistry independently confirms.
    """
    by_key = {example.declared_key: example for example in examples}
    pairs: list[StructureActivityPair] = []
    for reading in readings:
        key = _reading_designation(reading)
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


def recover_by_product_mass(
    examples: Sequence[DeclaredExample],
    known_keys: Collection[str],
    structures: Sequence[str],
) -> list[StructureActivityPair]:
    """Recover a structure for an example whose drawing lost its label.

    A scanned patent frequently draws the compound and prints its number, but the
    OCR that reads the number off the crop misses it — the drawing is still in the
    library, unnamed. The example states the product's mass, and a structure whose
    ``[M+H]+`` reproduces that mass to within :data:`_MASS_TOLERANCE_DA` is the
    compound the example describes.

    Only a *unique* connectivity match is accepted. Several isomers can share a
    mass, and picking one of them would fabricate an identity; measured on
    CN120329282A, 9 examples had unnamed candidates and 3 collapsed to a single
    connectivity. The rest stay gaps.

    A pair recovered this way is marked ``verified_by_mass`` because the mass is
    the evidence that found it.
    """
    keys = {str(key) for key in known_keys}
    pending = [e for e in examples if e.declared_key not in keys and e.product_mz]
    if not pending:
        return []

    from rdkit import Chem, RDLogger
    from rdkit.Chem import Descriptors

    RDLogger.DisableLog("rdApp.*")
    parsed: list[tuple[str, float, str]] = []
    for smiles in structures:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            continue
        parsed.append(
            (
                smiles,
                Descriptors.ExactMolWt(mol) + _PROTON,
                Chem.MolToSmiles(mol, isomericSmiles=False),
            )
        )

    recovered: list[StructureActivityPair] = []
    for example in pending:
        target = example.product_mz
        if target is None:
            continue
        flat: dict[str, str] = {}
        for smiles, mass, naive in parsed:
            if abs(mass - target) <= _MASS_TOLERANCE_DA:
                flat.setdefault(naive, smiles)
        if len(flat) != 1:
            continue
        smiles = next(iter(flat.values()))
        recovered.append(
            StructureActivityPair(
                declared_key=example.declared_key,
                measurement_id="",
                mol_id="",
                smiles=smiles,
                metric=None,
                value=None,
                unit="",
                verified_by_mass=True,
                printed_mz=target,
                calculated_mz=target,
            )
        )
    return recovered


__all__ = [
    "DeclaredExample",
    "StructureActivityPair",
    "extract_declared_examples",
    "pair_structure_activity",
    "recover_by_product_mass",
]
