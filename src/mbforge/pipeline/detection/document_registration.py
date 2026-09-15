"""Document-scoped molecule submission tool for cloud LLM extraction.

The tool is deliberately a collector, not a database writer.  A model can
submit several observations while reading a page or a table; the pipeline
later runs the collected :class:`ExtractionResult` objects through the same
RDKit normalization and Markush classification used by MolParser and text
extraction.
"""

from __future__ import annotations

import asyncio
import json
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool, tool

from mbforge.core.molecule import Molecule
from mbforge.core.types import ExtractionResult
from mbforge.pipeline.cancellation import TaskCancelledError
from mbforge.utils.logger import get_logger

from .normalization import normalize_molecules
from .structure_role import classify_structure_role

logger = get_logger("mbforge.pipeline.detection.document_registration")

_VALID_SOURCES = {"text", "image", "manual"}


class MoleculeRegistrationError(ValueError):
    """Raised when an LLM submission violates the candidate contract."""


def _validated_bbox(
    bbox: list[float] | None,
) -> tuple[float, float, float, float] | None:
    if bbox is None:
        return None
    if len(bbox) != 4 or not all(math.isfinite(float(value)) for value in bbox):
        raise MoleculeRegistrationError("bbox must contain four finite numbers")
    return tuple(float(value) for value in bbox)  # type: ignore[return-value]


@dataclass
class MoleculeRegistrationSession:
    """Collect molecule observations for one document without writing them."""

    doc_id: str
    _results: list[ExtractionResult] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def submit(
        self,
        *,
        esmiles: str,
        name: str = "",
        page_num: int | None = None,
        bbox: list[float] | None = None,
        context_text: str = "",
        confidence: float = 0.5,
        source: str = "text",
        role_hint: str = "",
    ) -> dict[str, Any]:
        """Validate and buffer one model-produced molecule observation.

        ``page_num`` is the public 1-based document page number.  The internal
        extraction contract keeps the existing 0-based page index.  ``role_hint``
        is retained as evidence only; it never overrides the deterministic
        Markush classifier.
        """
        smiles = str(esmiles or "").strip()
        if not smiles:
            raise MoleculeRegistrationError("esmiles is required")
        if source not in _VALID_SOURCES:
            raise MoleculeRegistrationError(
                f"source must be one of {sorted(_VALID_SOURCES)}"
            )
        if page_num is not None and page_num < 1:
            raise MoleculeRegistrationError("page_num is 1-based and must be >= 1")
        if not math.isfinite(float(confidence)) or not 0.0 <= confidence <= 1.0:
            raise MoleculeRegistrationError("confidence must be between 0 and 1")
        normalized_bbox = _validated_bbox(bbox)
        properties: dict[str, Any] = {"tool_submission": True}
        if role_hint:
            properties["llm_role_hint"] = role_hint[:200]
        if context_text:
            properties["role_context"] = context_text[:2000]

        result = ExtractionResult(
            esmiles=smiles,
            smiles=smiles,
            name=str(name or "").strip(),
            source=source,  # type: ignore[arg-type]
            moldet_conf=float(confidence) if source == "image" else 0.0,
            bbox_pdf=normalized_bbox,
            page_idx=page_num - 1 if page_num is not None else None,
            context_text=str(context_text or "")[:2000],
            status="pending",
            properties=properties,
        )

        # Run the same local validation immediately so the tool can tell the
        # model whether a submission is structurally usable.  The final pass
        # still re-normalizes all submissions to merge duplicate observations.
        candidate = normalize_molecules([result])[0]
        classify_structure_role(candidate)
        with self._lock:
            self._results.append(result)
            submission_index = len(self._results) - 1
        return {
            "accepted": candidate.status != "rejected",
            "submission_index": submission_index,
            "canonical_smiles": candidate.canonical_smiles,
            "status": candidate.status,
            "structure_role": candidate.properties.get("structure_role"),
            "review_reasons": candidate.properties.get("structure_role_reasons", []),
            "reference_label": result.name or None,
            "page_num": page_num,
        }

    def finalize(self) -> list[Molecule]:
        """Return merged candidates for the existing persistence stages."""
        with self._lock:
            results = list(self._results)
        candidates = normalize_molecules(results)
        for candidate in candidates:
            classify_structure_role(candidate)
        return candidates

    @property
    def submission_count(self) -> int:
        """Return the number of buffered submissions."""
        with self._lock:
            return len(self._results)


def create_molecule_registration_tool(
    session: MoleculeRegistrationSession,
) -> BaseTool:
    """Create an LLM-visible tool bound to one document session.

    The returned tool has no ``library_root`` or SQL access.  This makes it
    safe to use in parallel page workers and keeps commit/rollback ownership in
    the pipeline's final persistence transaction.
    """

    @tool("submit_molecule_candidate")
    async def submit_molecule_candidate(
        esmiles: str,
        name: str = "",
        page_num: int | None = None,
        bbox: list[float] | None = None,
        context_text: str = "",
        confidence: float = 0.5,
        source: str = "text",
        role_hint: str = "",
    ) -> str:
        """Submit one molecule observation for deterministic validation.

        Use the exact structure string visible in the source.  ``page_num`` is
        1-based and ``bbox`` uses PDF coordinates when known.  Do not submit a
        guessed SMILES; uncertain structures should be returned as review
        candidates by the caller.
        """
        try:
            payload = await asyncio.to_thread(
                session.submit,
                esmiles=esmiles,
                name=name,
                page_num=page_num,
                bbox=bbox,
                context_text=context_text,
                confidence=confidence,
                source=source,
                role_hint=role_hint,
            )
            return json.dumps(payload, ensure_ascii=False)
        except MoleculeRegistrationError as exc:
            return json.dumps(
                {
                    "accepted": False,
                    "error": str(exc),
                    "error_code": "invalid_submission",
                },
                ensure_ascii=False,
            )
        except Exception as exc:  # noqa: BLE001 - tool boundary must report failure
            logger.exception("Molecule registration tool failed")
            return json.dumps(
                {
                    "accepted": False,
                    "error": "molecule registration failed",
                    "error_code": type(exc).__name__,
                },
                ensure_ascii=False,
            )

    return submit_molecule_candidate


async def collect_molecule_candidates_with_tool(
    llm: Any,
    session: MoleculeRegistrationSession,
    source_text: str,
    *,
    max_chars: int = 16000,
    cancel_check: Callable[[], None] | None = None,
) -> tuple[list[Molecule], dict[str, int]]:
    """Run one cloud LLM tool-call pass and return normalized candidates.

    This adapter intentionally stops after collecting tool calls.  The model
    does not receive write access or an opportunity to mutate the database;
    the caller owns the final transaction.  Providers without LangChain
    ``bind_tools`` support fail explicitly so the pipeline can choose its
    existing detector path instead of silently pretending the pass ran.

    ``cancel_check`` is invoked before the LLM is called and again before
    each per-call ``ainvoke`` so the runner can abort the cloud pass on
    cooperative cancellation without waiting for the model to return.
    """
    if cancel_check is not None:
        cancel_check()
    bind_tools = getattr(llm, "bind_tools", None)
    if not callable(bind_tools):
        raise MoleculeRegistrationError("LLM provider does not support tool calls")

    registration_tool = create_molecule_registration_tool(session)
    try:
        bound_llm = bind_tools([registration_tool], tool_choice="required")  # type: ignore[union-attr]
    except TypeError:
        # Some OpenAI-compatible adapters support ``bind_tools`` but not the
        # optional ``tool_choice`` keyword.  Rebind without it; the prompt
        # still requires tool submission and the response is checked below.
        bound_llm = bind_tools([registration_tool])  # type: ignore[union-attr]

    prompt = f"""Read the following document text and submit every concrete or potentially Markush molecule observation by calling submit_molecule_candidate.

Requirements:
- Preserve the exact SMILES only when it is explicitly present or reliably extracted from the source.
- Preserve the compound label, page number, surrounding evidence, and any stated role hint.
- Never invent a SMILES. If only a label is available, do not submit it as a molecule.
- This is a text-only fallback path — set source to "text" for every submission.
- Use one tool call per observation; do not answer with prose.

Document text:
{source_text[:max_chars]}
"""
    response = await bound_llm.ainvoke(prompt)
    calls = getattr(response, "tool_calls", None) or []
    call_count = 0
    accepted_count = 0
    rejected_count = 0
    coerced_source_count = 0
    for call in calls:
        if cancel_check is not None:
            cancel_check()
        if not isinstance(call, dict):
            continue
        name = call.get("name") or call.get("function", {}).get("name")
        if name != "submit_molecule_candidate":
            continue
        arguments = call.get("args")
        if arguments is None:
            function = call.get("function") or {}
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    logger.warning("Ignoring malformed molecule tool arguments")
                    continue
        if not isinstance(arguments, dict):
            continue
        # The text-only fallback path must never claim image provenance.
        # Coerce source="image" to "text" so downstream metrics do not
        # mislabel these observations as detected-from-image.
        if arguments.get("source") == "image":
            arguments["source"] = "text"
            coerced_source_count += 1
        call_count += 1
        if cancel_check is not None:
            cancel_check()
        try:
            raw_result = await registration_tool.ainvoke(arguments)
            result = json.loads(raw_result)
        except TaskCancelledError:
            # Cooperative cancellation must abort the pipeline, not be
            # downgraded to a per-call rejection.
            raise
        except Exception as exc:  # noqa: BLE001
            # One malformed call must not discard previously-buffered
            # candidates; count it as a rejected call and continue.
            logger.warning(
                "Molecule tool call failed mid-pass (%s): %s",
                type(exc).__name__,
                exc,
            )
            rejected_count += 1
            continue
        if result.get("accepted"):
            accepted_count += 1
        else:
            rejected_count += 1

    return session.finalize(), {
        "tool_calls": call_count,
        "accepted_submissions": accepted_count,
        "rejected_submissions": rejected_count,
        "coerced_source_submissions": coerced_source_count,
        "buffered_submissions": session.submission_count,
    }


__all__ = [
    "MoleculeRegistrationError",
    "MoleculeRegistrationSession",
    "collect_molecule_candidates_with_tool",
    "create_molecule_registration_tool",
]
