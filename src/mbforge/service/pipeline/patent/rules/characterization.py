"""Deterministic characterization rules: printed spectra, routes, mass checks.

Every string here is copied verbatim from SQL evidence. A technique, a route's
steps, or a yield exists only where the document printed one, and a printed mass
that disagrees with a structure is recorded as evidence — never as an edit.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from mbforge.domain.evidence import SourceEvidence
from mbforge.foundation.ids import stable_id
from mbforge.service.pipeline.patent.rules.entries import (
    _MASS_SUFFIX_RE,
    _designation_keys,
)
from mbforge.service.pipeline.patent.sections import (
    ParsedSection as DocumentSection,
)
from mbforge.service.pipeline.patent.sections import example_token

#: Reports about a designation's family (name, route, characterization).
FAMILY_ISSUE_CODES: tuple[str, ...] = (
    "characterization_attribution",
    "compound_name_unresolved",
    "synthesis_route_unresolved",
)

#: A route is prose that prepares something: 制得/合成/収率/synthesized/prepared.
_ROUTE_SIGNAL_RE = re.compile(
    r"(?:制得|合成|製|収率|收率|产率|yield|synthes\w*|prepar\w*)", re.IGNORECASE
)
#: A step is only what the document printed as a step.
_STEP_MARKER_RE = re.compile(
    r"^\s*(?:步骤\s*\d|第\s*[一二三四五六七八九十\d]{1,3}\s*步|"
    r"Step\s*\d|\(\s*\d+\s*\)|（\s*\d+\s*）)",
    re.IGNORECASE,
)
_YIELD_RE = re.compile(
    r"(?:收率|収率|产率|yield)\s*[:：]?\s*\d+(?:\.\d+)?\s*%", re.IGNORECASE
)
#: ``制得化合物7`` / ``得白色固体化合物11`` / ``得到55mg化合物29`` — the route
#: names its own product. A printed amount may stand between the verb and the
#: designation (``得到55mg化合物29``), because the yield sentence puts the mass
#: first; a ``中间体`` product is an intermediate, not a compound.
_ROUTE_PRODUCT_RE = re.compile(
    r"(?:制得|得到|得)\s*"
    r"(?:\d+(?:\.\d+)?\s*(?:mg|g|kg|μg|ug|mL)?\s*)?"
    r"(?:[\u4e00-\u9fff]{0,4}(?:固体|粉末|油状物|油状|晶体))?\s*"
    r"(化合物\s*\d+[A-Za-z]?(?:-\d+)?)"
)
#: A shared-method or precedent sentence: the fact that a group of compounds was
#: made the same way (``synthesized using a similar method``, ``参考实施例1方法``).
_METHOD_NOTE_RE = re.compile(
    r"(?:similar method|analogous|in the same manner|according to the method|"
    r"参考实施例\s*\d+|按照?(?:与)?(?:上述|实施例\s*\d+)方法|按实施例\s*\d+的方法)",
    re.IGNORECASE,
)


#: ``元素分析`` / ``Anal. Calcd for …``.
_NMR_LINE_RE = re.compile(r"(?:\bNMR\b|核磁|氢谱)", re.IGNORECASE)
_MS_LINE_RE = re.compile(
    r"(?:\bMS\s*\(|\bLC[ -]?MS\b|\bLCMS\b|\bHRMS\b|\bMS\s*m/z\b|\bESI\b|质谱)",
    re.IGNORECASE,
)
_ELEMENTAL_LINE_RE = re.compile(
    r"(?:元素分析|\bAnal\.?\s*(?:Calcd|calc\.?)|calcd\.?\s*for)", re.IGNORECASE
)


MAX_CHARACTERIZATIONS = 60


#: heading names, which is how a scanned patent lays a step out.
_STEP_HEADING_RE = re.compile(
    r"(?:第[一二三四五六七八九十]+步|步骤\s*\d+|实施例\s*[\dA-Za-z-]+|中间体\s*[\dA-Za-z-]+)"
    r".*?(?:的)?(?:合成|制备|制法|制得)"
)
#: The heading usually names its product in parentheses after the chemistry:
#: ``…甲酰胺(A1-6)的合成``.
_HEADING_PRODUCT_RE = re.compile(
    r"[(（]\s*([A-Za-z0-9][\dA-Za-z-]{0,11})\s*[)）]\s*(?:的)?(?:合成|制备)"
)
#: How far above a characterization line its step heading may sit. Measured on
#: CN120329282A: 33 of 38 MS lines are exactly 5 rows below their heading and the
#: furthest observed is 17. The bound keeps a distant heading from lending its
#: designation to an unattached mass line.
_CHARACTERIZATION_HEADING_LOOKBACK = 24


#: ``MS (ESI) m/z: 456.2 [M+H]+`` — the printed mass and the adduct it names.
_MS_MZ_RE = re.compile(
    r"m/z[^0-9]{0,12}(?P<mz>\d+(?:\.\d+)?)\s*(?:\[\s*M\s*(?P<sign>[+-])\s*(?P<adduct>[A-Za-z0-9]+)\s*\]?)?",
    re.IGNORECASE,
)
#: Proton/electron-accurate adduct corrections (monoisotopic masses + electron).
ADDUCT_DELTA = {
    "+H": 1.00728,
    "+Na": 22.98922,
    "+K": 38.96316,
    "+NH4": 18.03383,
    "-H": -1.00728,
}
#: Tolerance the dormant matcher in ``detection/label_recovery`` already uses.
MASS_TOLERANCE_DA = 0.6


def _family_issues(
    characterizations: Sequence[Mapping[str, Any]],
    names: Sequence[Mapping[str, Any]],
    routes: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One report per passage that names no designation this document resolves.

    The report is a function of the passage's ``attribution``, so it is derived
    here rather than inline: the association pass can change that attribution, and
    the reports then have to be re-derived from the state it produced.
    """
    issues: list[dict[str, Any]] = []
    for family, code in (
        (characterizations, FAMILY_ISSUE_CODES[0]),
        (names, FAMILY_ISSUE_CODES[1]),
        (routes, FAMILY_ISSUE_CODES[2]),
    ):
        for item in family:
            if item["attribution"] != "unresolved":
                continue
            issues.append(
                {
                    "code": code,
                    "message": (
                        f"{code}: one printed passage names no designation this "
                        "document resolves"
                    ),
                    "severity": "info",
                    "evidence_ids": list(item["evidence_ids"][:50]),
                    "related_fact_id": None,
                }
            )
    return issues


def extract_synthesis_routes(
    sections: Sequence[DocumentSection],
    blocks_by_id: Mapping[str, SourceEvidence],
    doc_id: str,
) -> list[dict]:
    """Extract preparation routes from the example/preparation sections.

    The route lives in the *body*, not under a ``合成路线`` heading: none of the
    thirteen corpus documents prints such a heading, so this rule is built on the
    forms the corpus does print —

    * ``The following compounds were synthesized using a similar method…``
    * ``参考实施例1方法，制得化合物36.8mg，收率16.5%`` (CN121270515A)
    * ``ＤＭＡ(2 mL)中、2-ブロモ-N-(中間体71)(92 m g、0.2 57 m mο1)に、`` (JP2023544789A)

    Every string is copied verbatim; a step exists only where the document printed
    one (``步骤1`` / ``第1步`` / ``Step 1`` / ``(1)``), and the yield is the printed
    expression, never a converted number.
    """
    from mbforge.domain.patent import compound_label_key, example_label_key

    routes: list[dict] = []
    for section in sections:
        if section.kind not in ("example", "preparation"):
            continue
        blocks = [
            (evidence_id, blocks_by_id[evidence_id])
            for evidence_id in section.evidence_ids
            if evidence_id in blocks_by_id
        ]
        body = "\n".join(item.raw_text or "" for _, item in blocks)
        if not body.strip() or not _ROUTE_SIGNAL_RE.search(body):
            continue

        steps: list[dict] = []
        current: dict | None = None
        for evidence_id, item in blocks:
            for line in (item.raw_text or "").splitlines():
                if _STEP_MARKER_RE.match(line):
                    current = {
                        "step_no": len(steps) + 1,
                        "text": line.strip(),
                        "evidence_ids": [evidence_id],
                    }
                    steps.append(current)
                    continue
                if current is not None and line.strip():
                    current["text"] = f"{current['text']}\n{line.strip()}"
                    if evidence_id not in current["evidence_ids"]:
                        current["evidence_ids"].append(evidence_id)

        note = next(
            (
                line.strip()
                for _, item in blocks
                for line in (item.raw_text or "").splitlines()
                if _METHOD_NOTE_RE.search(line)
            ),
            "",
        )
        yield_match = _YIELD_RE.search(body)
        product_match = _ROUTE_PRODUCT_RE.search(body)
        product_raw = ""
        if product_match is not None:
            # ``参考实施例1方法，制得化合物36.8mg，收率16.5%`` prints a mass, not
            # compound 36 — the same quantity guard the entry pass uses.
            tail = body[product_match.end(1) :]
            if not _MASS_SUFFIX_RE.match(tail):
                product_raw = product_match.group(1)
        token = example_token(section)
        # Declaration beats inference (forms §8.4): a product the route prints is
        # its own identity; otherwise the section's own label designates it.
        label_key = (
            compound_label_key(product_raw)
            or (example_label_key(token) if token else None)
            or ""
        )
        label_raw = product_raw or (f"实施例{token}" if token else "")
        routes.append(
            {
                "route_id": stable_id(
                    "route", doc_id, str(section.page_start or 0), section.title
                ),
                "section_id": section.section_id,
                "kind": section.kind,
                "title": section.title,
                "label_raw": label_raw,
                "label_key": label_key,
                "product_label": product_raw,
                "page_start": section.page_start,
                "page_end": section.page_end,
                "evidence_ids": list(section.evidence_ids),
                "steps": steps,
                "step_count": len(steps),
                "yield_raw": yield_match.group(0) if yield_match else "",
                "method_note": note,
                "attribution": "resolved" if label_key else "unresolved",
            }
        )
    return routes


#: Spectra and elemental lines as the corpus prints them: ``1H NMR (400 MHz,
#: CDCl3) δ …``, ``MS (ESI) m/z: 456.2 [M+H]+``, ``LCMS: m/z 329.0 [M+H]+``,


def declared_product_labels(text: str) -> list[str]:
    """Return the compound designations a preparation passage prints as its product.

    ``参考实施例1方法，制得化合物36.8mg`` prints a mass, not compound 36, so the
    same quantity guard the entry pass uses applies here. The function exists so
    the association can ask the *document* which compound an example produced
    instead of assuming an example and a compound sharing a number are the same.
    """
    labels: list[str] = []
    for match in _ROUTE_PRODUCT_RE.finditer(text or ""):
        if _MASS_SUFFIX_RE.match((text or "")[match.end(1) :]):
            continue
        token = match.group(1).strip()
        if token and token not in labels:
            labels.append(token)
    return labels


def _technique_of(line: str) -> str | None:
    """The technique a printed line belongs to, or ``None`` when it is neither."""
    if _NMR_LINE_RE.search(line):
        return "nmr"
    if _MS_LINE_RE.search(line):
        return "ms"
    if _ELEMENTAL_LINE_RE.search(line):
        return "elemental"
    return None


#: A preparation step's own heading: ``第三步：(1S,3R)-…(A1-6)的合成``. A


def _characterization_owner(
    evidence: Sequence[SourceEvidence],
    row: SourceEvidence,
    order: int,
) -> str:
    """The designation a characterization line inherits from its step heading.

    A characterization line often arrives as its own evidence row
    (``[0168] LC-MS,M/Z(ESI):444.1[M+H]+`` is 33 characters) while the compound it
    describes is named by the preparation heading printed above it. A step's body
    sits between the two: measured on CN120329282A, 38 of 38 printed MS lines have
    a step heading earlier on their page, 33 of them at exactly 5 rows. Looking
    only at the immediately preceding row therefore finds almost nothing.

    Only a *step heading* grants the link, and only the designation that heading
    itself prints. A reading printed above the spectrum does not: the reading's
    compound and the spectrum's compound are not necessarily the same, and binding
    a mass to the wrong structure corrupts the very check these lines feed.

    The search stops at the page boundary and at a bounded distance, so a long
    document cannot lend a distant heading's designation to a stray mass line.
    """
    if order <= 0:
        return ""
    for back in range(1, _CHARACTERIZATION_HEADING_LOOKBACK + 1):
        index = order - back
        if index < 0:
            break
        previous = evidence[index]
        if previous.page != row.page:
            break
        text = previous.raw_text or ""
        if not _STEP_HEADING_RE.search(text):
            continue
        keys = _designation_keys(text)
        if len(keys) == 1:
            return keys[0]
        product = _HEADING_PRODUCT_RE.search(text)
        if product is not None:
            product_keys = _designation_keys(product.group(1))
            if len(product_keys) == 1:
                return product_keys[0]
        return ""
    return ""


def extract_characterization(
    evidence: Sequence[SourceEvidence], doc_id: str
) -> list[dict]:
    """Extract printed spectra and elemental data, verbatim, with their owner.

    The activity pass refuses these lines by design (``_NON_ACTIVITY_TABLE_RE``:
    ``NMR|LCMS|MS``), but the text itself is already SQL evidence. Nothing is
    re-typed or converted: the line is copied, the technique is named, and the
    designation is resolved only when the passage names exactly one.

    A line that names no designation of its own falls back to the nearest one
    printed above it on the same page, because that is how a preparation section
    is laid out: the step heading names the compound, the characterization line
    follows.

    The fallback is deliberately narrow — one designation owns at most one
    characterization *per technique* on a page. A page that prints several MS
    lines under one heading describes several compounds (a product and its
    intermediates), and letting all of them inherit the same designation would
    bind a mass to the wrong structure; that would corrupt the very check these
    lines feed. Those lines stay unresolved instead, which is what surfaces them
    as a gap for a reader to settle.
    """
    items: list[dict] = []
    seen: set[str] = set()
    for order, row in enumerate(evidence):
        text = row.raw_text or ""
        if not text.strip():
            continue
        row_keys = _designation_keys(text)
        for line in text.splitlines():
            technique = _technique_of(line)
            if technique is None:
                continue
            stripped = line.strip()
            line_keys = _designation_keys(stripped) or row_keys
            label_key = line_keys[0] if len(line_keys) == 1 else ""
            if not label_key:
                label_key = _characterization_owner(evidence, row, order)
            characterization_id = stable_id(
                "characterization", doc_id, row.evidence_id, technique, stripped
            )
            if characterization_id in seen:
                continue
            seen.add(characterization_id)
            items.append(
                {
                    "characterization_id": characterization_id,
                    "technique": technique,
                    "raw_text": stripped,
                    "label_key": label_key,
                    "page": row.page,
                    "evidence_ids": [row.evidence_id],
                    "attribution": "resolved" if label_key else "unresolved",
                }
            )
            if len(items) >= MAX_CHARACTERIZATIONS:
                return items
    return items


def printed_ms_mz(raw_text: str) -> tuple[float, str] | None:
    """The printed m/z and the adduct it names, or ``None`` for a line with neither.

    One parser for the whole codebase: the mass check and the read surface
    must read a printed mass the same way, or they disagree about the same line.
    """
    match = _MS_MZ_RE.search(raw_text or "")
    if match is None:
        return None
    adduct = f"{match.group('sign') or '+'}{match.group('adduct') or 'H'}"
    return float(match.group("mz")), adduct


def adduct_mass_delta(adduct: str) -> float | None:
    """The monoisotopic mass a printed adduct adds to the neutral structure."""
    return ADDUCT_DELTA.get(adduct)


def find_mass_mismatches(
    characterizations: Sequence[dict],
    candidates: Sequence[Any],
    *,
    tolerance: float = MASS_TOLERANCE_DA,
) -> list[dict]:
    """Printed MS mass versus the mass of the structure that claims the label.

    This is the detection half of a correction: a mismatch is *evidence*, never an
    edit. The structure the document recognized and the mass it printed for that
    designation disagree, which is worth a human's attention — and nothing here
    writes a SMILES or picks a replacement.
    """
    from mbforge.service.pipeline.detection.label_recovery import exact_mass
    from mbforge.service.pipeline.patent.candidate_labels import candidate_label_keys

    by_key: dict[str, Any] = {}
    for candidate in candidates:
        for key in candidate_label_keys(candidate):
            by_key.setdefault(key, candidate)

    mismatches: list[dict] = []
    for item in characterizations:
        if item.get("technique") != "ms" or not item.get("label_key"):
            continue
        candidate = by_key.get(str(item["label_key"]))
        if candidate is None:
            continue
        parsed = printed_ms_mz(str(item.get("raw_text") or ""))
        if parsed is None:
            continue
        printed, adduct = parsed
        delta_mass = adduct_mass_delta(adduct)
        if delta_mass is None:
            continue
        structure_mass = exact_mass(
            str(getattr(candidate, "canonical_smiles", "") or "")
        )
        if structure_mass is None:
            continue
        expected = structure_mass + delta_mass
        if abs(printed - expected) <= tolerance:
            continue
        mismatches.append(
            {
                "mol_id": str(getattr(candidate, "mol_id", "") or ""),
                "label_key": str(item["label_key"]),
                "printed_mz": printed,
                "adduct": adduct,
                "calculated_mass": round(structure_mass, 4),
                "delta": round(printed - expected, 4),
                "structure_smiles": str(
                    getattr(candidate, "canonical_smiles", "") or ""
                ),
                "raw_text": str(item.get("raw_text") or "")[:400],
                "evidence_ids": list(item.get("evidence_ids") or []),
            }
        )
    return mismatches
