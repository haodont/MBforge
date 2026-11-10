"""Contract tests for the capability registry."""

from __future__ import annotations

import asyncio

import pytest

from mbforge.foundation.errors import CapabilityForbiddenError
from mbforge.service.capabilities import (
    CapabilityContext,
    all_capabilities,
    invoke,
)


def test_capability_names_are_unique_and_schemas_generate() -> None:
    capabilities = all_capabilities()
    names = [capability.name for capability in capabilities]
    assert len(names) == len(set(names))
    assert {"resolve_document", "submit_extraction", "get_patent_result"} <= set(names)
    for capability in capabilities:
        assert capability.input_model.model_json_schema()
        assert capability.output_model.model_json_schema()


def test_readonly_mode_rejects_mutating_capability() -> None:
    with pytest.raises(CapabilityForbiddenError):
        asyncio.run(
            invoke(
                "submit_extraction",
                CapabilityContext(library_root="/tmp/library", mode="readonly"),
                {"doc_id": "missing"},
            )
        )
