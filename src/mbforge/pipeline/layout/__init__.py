"""Layout region detection pipeline (independent of the cloud OCR layout).

Modules:

- :mod:`~mbforge.pipeline.layout.labels` — detector label → RegionType → category
- :mod:`~mbforge.pipeline.layout.regions` — region assembly and px/pt conversion
- :mod:`~mbforge.pipeline.layout.merge` — intra-detector de-duplication (R1/R2/R5)
- :mod:`~mbforge.pipeline.layout.reading_order` — column-aware reading order
- :mod:`~mbforge.pipeline.layout.parse` — the per-page orchestration entry point

Cross-model arbitration (a layout region vs a molecule box) is **not** here: the
join stage already owns it (``evidence_join._join_evidence_dedupe``).
"""

from __future__ import annotations

__all__: list[str] = []
