"""Stage contract and registry (pure in-memory, no I/O).

This is the shared vocabulary between pipeline stages (which declare
themselves via :func:`register`), the runner that executes them and the
infra executor that consumes the registry. It depends only on typing and
dataclasses — core must never import pipeline or infra.

Adding a stage = write the stage class and decorate it:

    @register(after="markdown")
    class PatentStage:
        name = "patent"

        def execute(self, ctx) -> StageResult: ...

The execution order is derived from the registry (:data:`ORDER`); the
pipeline runner executes the single node the queue claimed, and the DAG
edges (:data:`DEPS`) decide when the next node becomes claimable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Protocol, runtime_checkable

__all__ = [
    "DEPS",
    "ORDER",
    "PipelineErrorCode",
    "REGISTRY",
    "StageExecutor",
    "StageResult",
    "dependencies",
    "next_after",
    "register",
]


class PipelineErrorCode:
    """Machine-readable error codes emitted by pipeline stages."""

    PDF_PARSE_ERROR = "PDF_PARSE_ERROR"
    OCR_UNAVAILABLE = "OCR_UNAVAILABLE"
    MOLDET_UNAVAILABLE = "MOLDET_UNAVAILABLE"
    EVIDENCE_JOIN_FAILED = "EVIDENCE_JOIN_FAILED"
    PATENT_EXTRACTION_FAILED = "PATENT_EXTRACTION_FAILED"
    PERSIST_MOLECULES_FAILED = "PERSIST_MOLECULES_FAILED"
    PERSIST_DOCUMENT_FAILED = "PERSIST_DOCUMENT_FAILED"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    PIPELINE_CANCELLED = "PIPELINE_CANCELLED"


@dataclass
class StageResult:
    """Outcome of a single pipeline stage.

    Errors are categorized by a machine-readable ``error_code`` and a
    ``recoverable`` flag so the runner can decide whether to continue (skip
    the stage) or abort the whole pipeline, and so the frontend can show
    actionable messages.

    Attributes:
        stage: Registered pipeline stage name.
        status: ``success``, ``warning`` (stage skipped but pipeline continues),
            or ``error`` (pipeline aborts).
        message: Human-readable description.
        error_code: Machine-readable code when status is not ``success``.
        recoverable: If ``True`` the runner logs a warning and continues; if
            ``False`` the runner emits an error event and aborts.
        context: Extra JSON-serializable data (e.g., exception type, counts).
        warnings: Non-fatal observations attached to a *successful* result
            (surfaced as events without changing stage status). A stage-level
            partial outcome — skipped work, unresolved gaps — belongs in
            ``status="warning"`` with ``recoverable=True`` instead.
    """

    stage: str
    status: Literal["success", "warning", "error"]
    message: str
    error_code: str | None = None
    recoverable: bool = False
    context: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0


# Registered stage instances by stage name. Instances must be stateless:
# all per-run state lives in PipelineContext, never on the stage object.
REGISTRY: dict[str, Any] = {}
# Derived execution order — deterministic because every stage declares
# its predecessor via ``after=`` (except the first stage, which omits it).
ORDER: list[str] = []
# Stage dependency DAG: ``DEPS[stage]`` lists the stages that must succeed
# before ``stage`` may run. ``after=`` supplies the single-predecessor
# default (the linear tail); a stage that fans in — e.g. the Extract ∥
# Detection join — declares its full prerequisite set via ``depends_on=``.
DEPS: dict[str, tuple[str, ...]] = {}


@runtime_checkable
class StageExecutor(Protocol):
    """Contract every pipeline stage satisfies.

    - ``name``: stable stage identifier (checkpoints, resume, the stage
      reported in its own ``StageResult``, and queue node naming) —
      never derived from the class name.
    - ``execute(ctx) -> StageResult``: reads from ctx, mutates it in place.

    Instances must be stateless: all per-run state lives in
    ``PipelineContext`` (pipeline layer, hence untyped here), never on the
    stage object.

    Example:
        class ExtractStage:
            name = "extract"

            def execute(self, ctx) -> StageResult:
                ctx.extracted = extract_pdf_text(str(ctx.pdf_path))
                return StageResult(stage="extract", status="success", message="")
    """

    name: ClassVar[str]

    def execute(self, ctx: Any) -> StageResult: ...


def register(
    stage_cls: type | None = None,
    *,
    after: str | None = None,
    depends_on: tuple[str, ...] | Sequence[str] | None = None,
) -> Any:
    """Decorator: register a stage class (instantiated once, stateless).

    Usable both bare (``@register``) and parameterized
    (``@register(after="extract")`` / ``@register(after="extract",
    depends_on=("extract", "detection"))``).

    ``after`` names the stage this one follows, anchoring the derived
    order independent of module import order. Omit it for the first
    stage only.

    ``depends_on`` declares the full prerequisite set for the execution
    DAG; it defaults to ``(after,)``. A fan-in stage (the Extract ∥
    Detection join) needs both predecessors, which a single ``after``
    cannot express.

    Raises:
        ValueError: on duplicate stage names or unknown ``after`` /
            ``depends_on`` targets.
    """

    def _register(cls: type) -> type:
        name = getattr(cls, "name", None)
        if not name or not isinstance(name, str):
            raise ValueError(f"{cls.__name__} must define a string `name`")
        if not callable(getattr(cls, "execute", None)):
            raise ValueError(f"{cls.__name__} must define `execute(ctx)`")
        if name in REGISTRY:
            raise ValueError(f"stage {name!r} is already registered")
        if after is not None and after not in ORDER:
            raise ValueError(
                f"stage {name!r} declares after={after!r}, which is not registered"
            )
        deps = (
            tuple(depends_on) if depends_on is not None else ((after,) if after else ())
        )
        for dep in deps:
            if dep not in REGISTRY:
                raise ValueError(
                    f"stage {name!r} declares depends_on={dep!r}, which is not registered"
                )
        REGISTRY[name] = cls()
        DEPS[name] = deps
        if after is None:
            ORDER.append(name)
        else:
            ORDER.insert(ORDER.index(after) + 1, name)
        return cls

    if stage_cls is None:
        return _register
    return _register(stage_cls)


def dependencies(stage: str) -> tuple[str, ...]:
    """Return the registered prerequisites of *stage* (empty for roots)."""
    return DEPS.get(stage, ())


def next_after(current: str | None) -> str | None:
    """Return the stage that follows *current*, or ``None`` at the end.

    Unknown/``None`` input resolves to the first stage, mirroring the
    historical ``stage_checkpoint.next_stage`` semantics (an unrecognised
    checkpoint restarts from the beginning).
    """
    if current is None:
        return ORDER[0] if ORDER else None
    try:
        idx = ORDER.index(current)
    except ValueError:
        return ORDER[0] if ORDER else None
    if idx + 1 < len(ORDER):
        return ORDER[idx + 1]
    return None
