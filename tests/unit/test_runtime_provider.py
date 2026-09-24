"""Runtime provider composition contract.

The runtime provider resolves several capabilities by attribute on lazily
imported modules. A capability whose module was never bound on its package
raises ``AttributeError`` at *call* time, which every enrichment call site
swallows — so the feature degrades to a silent no-op instead of failing loudly.
Table recognition did exactly that on every run because ``table_slanet`` was
missing from ``adapters.inference``'s own imports.
"""

from __future__ import annotations

from mbforge.adapters.runtime.provider import create_runtime_provider

#: Capability -> the callable the pipeline actually invokes on it.
_PIPELINE_CALLABLES = {
    "hiro_layout": "detect_regions",
    "table_slanet": "predict_table",
    "ocr_page_text": "read_text_in_boxes",
    "moldet": "detect_molecules",
    "molparser": "predict",
}


def test_pipeline_capabilities_expose_their_entry_point() -> None:
    """Each capability the pipeline calls must expose that callable."""
    provider = create_runtime_provider()

    for capability, callable_name in _PIPELINE_CALLABLES.items():
        resolved = getattr(provider, capability)
        entry_point = getattr(resolved, callable_name, None)
        assert callable(entry_point), (
            f"runtime capability {capability!r} has no {callable_name}()"
        )
