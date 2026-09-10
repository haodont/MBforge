"""Stage contract and registry (pure in-memory, no I/O).

This is the shared vocabulary between pipeline stages (which declare
themselves via :func:`register`) and the infra executor (which consumes
the registry). It depends only on typing and the :mod:`mbforge.core.stage_result`
DTO — core must never import pipeline or infra.

Adding a stage = write the stage class and decorate it:

    @register(after="markdown")
    class PatentStage:
        name = "patent"

        def execute(self, ctx) -> StageResult: ...

The execution order is derived from the registry (:data:`ORDER`); the
pipeline runner walks it and the queue worker re-queues the stage
returned by ``StageResult.next_stage``. Manual STAGE_ORDER maintenance
is forbidden (TODO/services-layer-plan.md §6.5).
"""

from __future__ import annotations

from typing import Any, ClassVar, Protocol, runtime_checkable

from .stage_result import StageResult

__all__ = ["ORDER", "REGISTRY", "Stage", "next_after", "register"]

# Registered stage instances by stage name. Instances must be stateless:
# all per-run state lives in PipelineContext, never on the stage object.
REGISTRY: dict[str, Any] = {}
# Derived execution order — deterministic because every stage declares
# its predecessor via ``after=`` (except the first stage, which omits it).
ORDER: list[str] = []


@runtime_checkable
class Stage(Protocol):
    """Contract every pipeline stage satisfies.

    - ``name``: stable stage identifier (used for checkpoints, resume and
      progress reporting) — never derived from the class name.
    - ``execute(ctx) -> StageResult``: reads from ctx, mutates it in place.
    """

    name: ClassVar[str]

    def execute(self, ctx: Any) -> StageResult: ...


def register(stage_cls: type | None = None, *, after: str | None = None) -> Any:
    """Decorator: register a stage class (instantiated once, stateless).

    Usable both bare (``@register``) and parameterized
    (``@register(after="extract")``).

    ``after`` names the stage this one follows, anchoring the derived
    order independent of module import order. Omit it for the first
    stage only.

    Raises:
        ValueError: on duplicate stage names or unknown ``after`` targets.
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
        REGISTRY[name] = cls()
        if after is None:
            ORDER.append(name)
        else:
            ORDER.insert(ORDER.index(after) + 1, name)
        return cls

    if stage_cls is None:
        return _register
    return _register(stage_cls)


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
