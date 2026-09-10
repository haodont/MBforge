"""Capability probe regression tests.

Covers item 13 of the audit: the runtime must report which optional heavy
dependencies (local-models / gpu extras) are importable at startup without
raising, so the API boots even when model/GPU features are unavailable.
"""

from __future__ import annotations

from mbforge.utils.capabilities import (
    CapabilityProbe,
    log_capability_summary,
    probe,
)

# Display labels must match pyproject optional-dependencies group contents.
_EXPECTED_LABELS = {
    "torch",
    "transformers",
    "ultralytics",
    "timm",
    "scipy",
    "scikit-learn",
    "modelscope",
    "molparser",
    "cairosvg",
}


def test_probe_reports_expected_modules_and_sorted_lists() -> None:
    report = probe()
    assert isinstance(report, CapabilityProbe)
    assert set(report.available) | set(report.missing) == _EXPECTED_LABELS
    assert set(report.available) & set(report.missing) == set()
    assert list(report.available) == sorted(report.available)
    assert list(report.missing) == sorted(report.missing)
    assert isinstance(report.cuda_available, bool)

    summary = log_capability_summary()
    assert isinstance(summary, CapabilityProbe)
