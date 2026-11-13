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


#: How many printed spectra one document may contribute. The bound exists to keep
#: the facts payload finite, but a patent prints one per compound, so a 200-page
#: filing has hundreds: at 60 the list stopped inside the early examples and every
#: later compound's mass was invisible to the mass checks (measured on
#: CN120943813A, whose 实施例44 is on page 90 of 103 — its LC-MS never arrived).
MAX_CHARACTERIZATIONS = 2000


#: heading names, which is how a scanned patent lays a step out.
_STEP_HEADING_RE = re.compile(
    r"(?:第[一二三四五六七八九十]+步|步骤\s*\d+|实施例\s*[\dA-Za-z-]+|中间体\s*[\dA-Za-z-]+)"
    r".*?(?:的)?(?:合成|制备|制法|制得)"
)
#: A CN example heading that states no verb: ``[0625] 实施例44``. Its product is
#: printed in the body below it (``得到33.75mg化合物44``), not in the title.
_BARE_EXAMPLE_HEADING_RE = re.compile(r"(?:实施例|実施例)\s*[\dA-Za-z-]+")

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
#: ``m/z: (M+H)+=558.0`` / ``m/z: (M+H-t-Bu)†=249.1`` — the value is printed
#: after the adduct, never inside it. Reading the first digits after ``m/z``
#: picked ``100`` out of ``(M+H-100)``, which invented a 128 Da mismatch.
_MS_MZ_PAREN_RE = re.compile(
    r"m/z\s*[:：]?\s*[（(]\s*M\s*(?P<expr>[^)）]*?)\s*[)）]\s*[†*+]?\s*=\s*"
    r"(?P<mz>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
#: ``[M+H]+ 456.2`` / ``[M-H]- 455.2`` — bracketed adduct, value after it.
_MS_MZ_BRACKET_RE = re.compile(
    r"\[\s*M\s*(?P<expr>[^\]]*?)\s*\][^0-9]{0,12}(?P<mz>\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
#: ``MS (ESI) m/z: 456.2 [M+H]+`` — the value first, the adduct after it.
_MS_MZ_VALUE_FIRST_RE = re.compile(
    r"m/z[^0-9]{0,12}(?P<mz>\d+(?:\.\d+)?)\s*\[?[（(]?\s*M\s*(?P<expr>[^\])）]*?)\s*[\])）]",
    re.IGNORECASE,
)
#: A bare ``m/z 456.2`` line with no adduct.
_MS_MZ_PLAIN_RE = re.compile(
    r"m/z[^0-9]{0,12}(?P<mz>\d+(?:\.\d+)?)", re.IGNORECASE
)
#: Proton/electron-accurate adduct corrections (monoisotopic masses + electron).
ADDUCT_DELTA = {
    "+H": 1.00728,
    "+Na": 22.98922,
    "+K": 38.96316,
    "+NH4": 18.03383,
    "-H": -1.00728,
}
#: Fragments a printed adduct expression may add or lose, by monoisotopic mass.
#: ``(M+H-t-Bu)`` and ``(M+H-100)`` are the corpus's two ways of printing a
#: protecting-group loss; a fragment that is not listed makes the expression
#: unreadable, and an unreadable adduct must not drive a mass check.
ADDUCT_FRAGMENT_MASS = {
    "H": 1.00728,
    "Na": 22.98922,
    "K": 38.96316,
    "NH4": 18.03383,
    "H2O": 18.01056,
    "CH3": 15.02347,
    "CH2": 14.01565,
    "C2H4": 28.03130,
    "t-Bu": 56.06260,
    "tBu": 56.06260,
    "Boc": 100.05243,
    "TFA": 113.99286,
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



def _example_body_product_keys(
    evidence: Sequence[SourceEvidence], start: int, stop: int, page: int | None
) -> set[str]:
    """The product designations an example's body states between two rows."""
    keys: set[str] = set()
    for index in range(start, min(stop, len(evidence))):
        row = evidence[index]
        if row.page != page:
            break
        text = row.raw_text or ""
        for line in text.splitlines():
            keys.update(_product_phrase_keys(line))
    return keys


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
            if _BARE_EXAMPLE_HEADING_RE.search(text):
                # The example heading names no product of its own; its body does.
                body_keys = _example_body_product_keys(
                    evidence, index + 1, order, row.page
                )
                if len(body_keys) == 1:
                    return next(iter(body_keys))
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


def _product_phrase_keys(text: str) -> list[str]:
    """Designations the passage names after a product verb (得/得到/制得).

    Used only to break a tie: a preparation sentence that prints two
    designations still says which one it *obtained*, and that is the compound
    whose printed mass the line carries.
    """
    last = None
    for match in re.finditer(r"(?:制得|得到|得)", text or ""):
        last = match
    if last is None:
        return []
    return _designation_keys((text or "")[last.end() :])


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
            if not label_key and len(line_keys) > 1:
                # A preparation paragraph names its reagents and its product, so
                # the line carries several designations. The product is the one
                # the sentence says it obtained (``…得化合物I-50-2(150mg)。
                # LC-MS:…``), which is the designation this mass belongs to.
                product_keys = _product_phrase_keys(stripped)
                if len(product_keys) == 1:
                    label_key = product_keys[0]
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

    One parser for the whole codebase: the mass check and the read surface must
    read a printed mass the same way, or they disagree about the same line. The
    value always follows the adduct (``(M+H)+=558.0``, ``(M+H-t-Bu)†=249.1``,
    ``[M-H]- 455.2``, ``m/z 456.2``), so the adduct is read first and the number
    after it — never the first number after ``m/z``, which lives inside the
    adduct expression.
    """
    text = raw_text or ""
    match = (
        _MS_MZ_PAREN_RE.search(text)
        or _MS_MZ_BRACKET_RE.search(text)
        or _MS_MZ_VALUE_FIRST_RE.search(text)
    )
    if match is not None:
        return float(match.group("mz")), match.group("expr").strip()
    match = _MS_MZ_PLAIN_RE.search(text)
    if match is None:
        return None
    return float(match.group("mz")), ""


def adduct_mass_delta(adduct: str) -> float | None:
    """The monoisotopic mass a printed adduct expression adds to the structure.

    ``H``, ``+H``, ``H-100``, ``H-t-Bu``, ``+Na``. ``None`` when any fragment is
    unknown, because an unreadable adduct cannot decide whether a printed mass
    agrees with a structure.
    """
    expression = str(adduct or "").strip()
    if not expression:
        return None
    if expression in ADDUCT_DELTA:
        return ADDUCT_DELTA[expression]
    # Fragments are matched longest first so ``t-Bu`` is one fragment and
    # ``H2O`` is not read as ``H`` + ``2O``.
    known = sorted(ADDUCT_FRAGMENT_MASS, key=len, reverse=True)
    total = 0.0
    index = 0
    while index < len(expression):
        sign = 1.0
        if expression[index] in "+-":
            sign = -1.0 if expression[index] == "-" else 1.0
            index += 1
            if index >= len(expression):
                return None
        for fragment in known:
            if expression.startswith(fragment, index):
                total += sign * ADDUCT_FRAGMENT_MASS[fragment]
                index += len(fragment)
                break
        else:
            match = re.match(r"\d+(?:\.\d+)?", expression[index:])
            if match is None:
                return None
            total += sign * float(match.group(0))
            index += len(match.group(0))
    return total


def _loss_expression(adduct: str) -> bool:
    """Whether a printed adduct subtracts a named group after the ion.

    ``-H`` and ``+H`` are plain ions; ``H-t-Bu`` (two fragments) is a loss
    expression whose meaning the document does not fix.
    """
    body = str(adduct or "").strip().lstrip("+-")
    return re.search(r"[+-]", body) is not None


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
        if _loss_expression(adduct):
            # ``(M+H-t-Bu)+`` is the corpus's loose way of printing a group
            # loss: on a Boc-protected amine it means the whole Boc (≈100 Da),
            # on another compound the alkene (≈56 Da). The notation does not say
            # which, so the line cannot decide whether a structure is wrong —
            # treating it as one mass would invent a 44 Da mismatch.
            continue
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


def mass_consistent_structures(
    characterizations: Sequence[dict],
    candidates: Sequence[Any],
    label_key: str,
    *,
    tolerance: float = MASS_TOLERANCE_DA,
    section_ids: Sequence[str] = (),
) -> list[Any]:
    """The structures whose calculated ion mass matches the mass printed for a label.

    When two drawings claim one designation the filing often settles it itself:
    the section that prepares the compound prints its ``LC-MS`` and only one of
    the two structures is consistent with it. Measured on CN121717757A, whose
    ``I-266-A`` has a claims drawing of ``C26H30…`` (572.2) and an example
    drawing of ``C25H28…`` (558.16) while 实施例26 prints ``(M+H)+ = 558.0``.

    Returns every candidate consistent with every mass printed for the label; an
    empty list means the printed mass does not decide (no line, or both match).
    """
    from mbforge.service.pipeline.detection.label_recovery import exact_mass

    printed: list[tuple[float, float]] = []
    section_scoped = False
    for item in characterizations:
        if item.get("technique") != "ms":
            continue
        # The line belongs to this designation either by name or by the section
        # that prepares it: a CN example prints ``MS…470.2`` for its product and
        # the table cites the compound under the example's number.
        by_name = str(item.get("label_key") or "") == label_key
        by_section = bool(section_ids) and str(
            item.get("section_id") or ""
        ) in section_ids
        if not by_name and not by_section:
            continue
        section_scoped = section_scoped or (by_section and not by_name)
        parsed = printed_ms_mz(str(item.get("raw_text") or ""))
        if parsed is None:
            continue
        printed.append(parsed)
    if not printed:
        return []

    consistent: list[Any] = []
    for candidate in candidates:
        structure_mass = exact_mass(
            str(getattr(candidate, "canonical_smiles", "") or "")
        )
        if structure_mass is None:
            continue
        def _matches(item: tuple[float, float], mass: float = structure_mass) -> bool:
            mz, adduct = item
            delta = adduct_mass_delta(adduct)
            return delta is not None and abs(mz - (mass + delta)) <= tolerance

        # A section may print several masses (its intermediates and its product),
        # so a section-scoped scope asks whether the structure explains *one* of
        # them; a line printed for the designation itself must explain it.
        # One designation can carry several printed masses: its own line and the
        # line the page prints for the product next to it. A single structure
        # cannot explain two different masses, so requiring it to explain all of
        # them decides nothing (measured: 44 had 470.2 and 478.2, the right
        # structure matched 470.2 to 0.06 Da and was still rejected). One match is
        # the evidence; the "exactly one candidate" rule keeps it honest.
        agrees = (
            any(_matches(item) for item in printed)
            if section_scoped or len(printed) > 1
            else all(_matches(item) for item in printed)
        )
        if agrees:
            consistent.append(candidate)
    return consistent
