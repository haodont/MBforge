"""Regression coverage for the Patent-only pipeline boundary."""

from __future__ import annotations

from mbforge.application.pipeline.composition import effective_stage_names


def test_patent_is_the_current_pipeline_endpoint() -> None:
    assert effective_stage_names() == [
        "extract",
        "join",
        "markdown",
        "patent",
    ]
