"""Activity extraction evaluator (golden-agnostic).

Consumes a candidate extraction (a JSON dump of the pipeline's activity
stage) and scores it against the supervised golden rows. The evaluator
reports the following metrics:

    label_recall             fraction of golden labels recovered
    pdf_page_accuracy        fraction of hits whose pdf_page matches
    value_exact_accuracy     fraction of hits whose displayed value matches
                             within ±value_atol (loose to absorb OCR noise)
    value_canonical_nm_acc   fraction of hits whose canonical-nM matches
                             within ±canonical_nm_rtol
    target_context_accuracy  fraction of hits whose target/metric match
    operator_accuracy        fraction of hits whose comparison operator matches
    row_alignment_accuracy   fraction of hits with consistent label+page+value+
                              target+operator

Candidate schema::

    {"results": [{"compound_label": "E001",
                  "pdf_page": 60,
                  "value_original": 6.4,
                  "value_canonical_nm": 398.1,
                  "target": "...",
                  "metric": "pIC50"}, ...]}
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ActivityMetrics:
    """Numeric metrics emitted by the activity evaluator."""

    label_recall: float
    pdf_page_accuracy: float
    value_exact_accuracy: float
    value_canonical_nm_accuracy: float
    target_context_accuracy: float
    operator_accuracy: float
    row_alignment_accuracy: float
    matched: int
    unmatched_golden: int
    unmatched_candidate: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def by_label(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index rows by ``compound_label`` (or fallback ``label``).

    Markush anchors use ``label`` whereas activity rows use
    ``compound_label``. This helper accepts both so a single index
    drives every evaluator.
    """
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = row.get("compound_label") or row.get("label")
        if isinstance(label, str) and label:
            out.setdefault(label, row)
    return out


def _close_enough(a: float, b: float, *, atol: float, rtol: float) -> bool:
    return abs(a - b) <= max(atol, rtol * max(abs(a), abs(b)))


def _normalize_operator(value: Any) -> str:
    """Normalize operator aliases while defaulting missing legacy values."""
    return {"≤": "<=", "≥": ">=", "≈": "~"}.get(
        str(value or "=").strip(), str(value or "=").strip()
    )


def score_activity(
    golden_rows: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    value_atol: float = 0.05,
    canonical_nm_rtol: float = 0.05,
) -> ActivityMetrics:
    """Score a candidate extraction against the golden activity rows."""
    gold_by_label = by_label(golden_rows)
    cand_by_label = by_label(candidate.get("results", []))

    common_labels = sorted(set(gold_by_label) & set(cand_by_label))
    gold_only = sorted(set(gold_by_label) - set(cand_by_label))
    cand_only = sorted(set(cand_by_label) - set(gold_by_label))

    label_recall = len(common_labels) / max(len(gold_by_label), 1)

    if not common_labels:
        return ActivityMetrics(
            label_recall=label_recall,
            pdf_page_accuracy=0.0,
            value_exact_accuracy=0.0,
            value_canonical_nm_accuracy=0.0,
            target_context_accuracy=0.0,
            operator_accuracy=0.0,
            row_alignment_accuracy=0.0,
            matched=0,
            unmatched_golden=len(gold_only),
            unmatched_candidate=len(cand_only),
        )

    page_hits = value_hits = nm_hits = target_hits = operator_hits = aligned = 0
    for label in common_labels:
        gold = gold_by_label[label]
        cand = cand_by_label[label]
        page_ok = gold.get("pdf_page") == cand.get("pdf_page")
        if page_ok:
            page_hits += 1

        g_val = gold.get("value_original")
        c_val = cand.get("value_original")
        value_ok = (
            isinstance(g_val, (int, float))
            and isinstance(c_val, (int, float))
            and _close_enough(float(g_val), float(c_val), atol=value_atol, rtol=0.0)
        )
        if value_ok:
            value_hits += 1

        g_nm = gold.get("value_canonical_nm")
        c_nm = cand.get("value_canonical_nm")
        nm_ok = (
            isinstance(g_nm, (int, float))
            and isinstance(c_nm, (int, float))
            and _close_enough(
                float(g_nm), float(c_nm), atol=0.0, rtol=canonical_nm_rtol
            )
        )
        if nm_ok:
            nm_hits += 1

        target_ok = gold.get("target") == cand.get("target") and gold.get(
            "metric"
        ) == cand.get("metric")
        if target_ok:
            target_hits += 1

        gold_operator = _normalize_operator(
            gold.get("operator_original") or gold.get("operator")
        )
        candidate_operator = _normalize_operator(
            cand.get("operator_original") or cand.get("operator")
        )
        operator_ok = gold_operator == candidate_operator
        if operator_ok:
            operator_hits += 1

        if page_ok and value_ok and target_ok and operator_ok:
            aligned += 1

    n = len(common_labels)
    return ActivityMetrics(
        label_recall=label_recall,
        pdf_page_accuracy=page_hits / n,
        value_exact_accuracy=value_hits / n,
        value_canonical_nm_accuracy=nm_hits / n,
        target_context_accuracy=target_hits / n,
        operator_accuracy=operator_hits / n,
        row_alignment_accuracy=aligned / n,
        matched=n,
        unmatched_golden=len(gold_only),
        unmatched_candidate=len(cand_only),
    )
