"""InitialForkRunner — the fixed parallel Extract ∥ Detection fork.

Moved out of ``run_pipeline`` with behavior preserved:

- runs the pending Extract/Detection branches concurrently in a thread pool,
- journalizes running/success/error stage summaries,
- aligns a previously-successful branch onto the current run and reaps a
  superseded branch run,
- joins the two branch artifacts exactly once (``_try_join``) into SQL
  ``source_evidence`` and assembles ``ctx`` for the downstream stages,
- returns a ``PipelineResult`` with ``next_stage="markdown"`` when the fork is
  done, or raises (branch errors take precedence over join errors; user
  cancellation propagates as ``TaskCancelledError``).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING, Any

from ...core.stage import REGISTRY as STAGE_REGISTRY
from ...utils.logger import get_logger
from ..cancellation import PIPELINE_CANCELLED, TaskCancelledError
from ..context import PipelineContext
from ..stage_checkpoint import (
    latest_stage_run_id,
    load_run_checkpoint,
    load_stage_summary,
    save_stage_summary,
)
from .state import RunContext

if TYPE_CHECKING:
    from .events import PipelineEventSink

logger = get_logger("mbforge.pipeline.runner")


class InitialForkRunner:
    """Owns the Extract ∥ Detection fork lifecycle for one invocation."""

    def __init__(
        self, run: RunContext, sink: PipelineEventSink, active_stages: list[Any]
    ) -> None:
        self.run = run
        self.ctx = run.ctx
        assert self.ctx is not None
        self.sink = sink
        self.active_stages = active_stages
        self.resume_from_stage = run.resume_from_stage

        self.branch_names = [stage.name for stage in active_stages[:2]]
        self.branch_stages: dict[str, Any] = {}
        self.pending_branches: list[str] = []
        self.branch_contexts: dict[str, PipelineContext] = {}
        self.branch_results: dict[str, Any] = {}
        self.branch_errors: list[tuple[str, BaseException]] = []
        self.join_errors: list[BaseException] = []
        self.extract_artifact: Any = None
        self.detection_artifact: Any = None
        self.source_evidence_count = 0
        self.candidates: list[Any] = []
        self.join_attempted = False

    # -- gating --------------------------------------------------------------

    def _real_initial_fork(self) -> bool:
        return (
            len(self.active_stages) >= 2
            and self.active_stages[0] is STAGE_REGISTRY.get("extract")
            and self.active_stages[1] is STAGE_REGISTRY.get("detection")
        )

    def should_run(self) -> bool:
        """Whether this invocation must run (or re-run) the initial fork."""
        if not (
            self._real_initial_fork() and self.branch_names == ["extract", "detection"]
        ):
            return False
        if self.resume_from_stage is None:
            return True
        # A completed initial fork falls through to the sequential path unless a
        # manual branch retry marked one branch pending again below.
        fork_checkpoint = load_run_checkpoint(self.run.staging_dir) or {}
        fork_statuses = fork_checkpoint.get("stages", {})
        branches_complete = all(
            fork_statuses.get(name, {}).get("status") == "success"
            for name in self.branch_names
        )
        join_complete = fork_statuses.get("join", {}).get("status") == "success"
        return (not branches_complete or not join_complete) and (
            self.resume_from_stage in self.branch_names
        )

    # -- executors -----------------------------------------------------------

    def _new_branch_context(self, name: str) -> PipelineContext:
        ctx = self.ctx
        return PipelineContext(
            pdf_path=ctx.pdf_path,
            library_root=ctx.library_root,
            doc_id=ctx.doc_id,
            task_id=ctx.task_id,
            ocr_config=dict(ctx.ocr_config),
            staging_dir=self.run.staging_dir,
            run_id=self.run.run_id,
            branch=name,
        )

    def _execute_branch(self, name: str) -> tuple[Any, PipelineContext]:
        branch_ctx = self._new_branch_context(name)
        started = time.perf_counter()
        result = self.branch_stages[name].execute(branch_ctx)
        result.elapsed_ms = round((time.perf_counter() - started) * 1000)
        return result, branch_ctx

    def _align_branch_to_current_run(self, stage_name: str) -> None:
        from ..stage_artifacts import (
            load_detection_branch,
            load_extract_branch,
            save_detection_branch,
            save_extract_branch,
        )

        previous_run_id = latest_stage_run_id(self.run.staging_dir, stage_name)
        if not previous_run_id or previous_run_id == self.run.run_id:
            return
        if stage_name == "extract":
            branch = load_extract_branch(
                self.run.library_root, self.ctx.doc_id, previous_run_id
            )
            if branch is None:
                raise RuntimeError("extract branch artifact is incomplete")
            save_extract_branch(
                self.run.library_root,
                branch.model_copy(update={"run_id": self.run.run_id}),
            )
        elif stage_name == "detection":
            branch = load_detection_branch(
                self.run.library_root, self.ctx.doc_id, previous_run_id
            )
            if branch is None:
                raise RuntimeError("detection branch artifact is incomplete")
            save_detection_branch(
                self.run.library_root,
                branch.model_copy(update={"run_id": self.run.run_id}),
            )
        else:
            return

        summary = load_stage_summary(self.run.staging_dir, stage_name)
        if summary is not None:
            save_stage_summary(
                self.run.staging_dir,
                stage_name,
                status=str(summary.get("status") or "success"),
                elapsed_ms=int(summary.get("elapsed_ms") or 0),
                message=str(summary.get("message") or ""),
                context=(
                    summary.get("context")
                    if isinstance(summary.get("context"), dict)
                    else None
                ),
                error_code=(
                    str(summary["error_code"]) if summary.get("error_code") else None
                ),
                run_id=self.run.run_id,
            )

    def _try_join(self) -> bool:
        """Join exactly once when both initial branches are successful."""
        checkpoint = load_run_checkpoint(self.run.staging_dir) or {}
        statuses = checkpoint.get("stages", {})
        if self.join_attempted:
            return False
        if not all(
            statuses.get(name, {}).get("status") == "success"
            for name in self.branch_names
        ):
            return False
        self.join_attempted = True

        from ..persist.source_evidence import persist_source_evidence
        from ..stage_artifacts import (
            _candidates_from_evidence,
            detection_results,
            join_evidence_artifacts,
            load_detection_branch,
            load_extract_branch,
        )

        for branch_name in self.branch_names:
            self._align_branch_to_current_run(branch_name)
        extract_run_id = (
            latest_stage_run_id(self.run.staging_dir, "extract")
            or self.run.run_id
            or ""
        )
        detection_run_id = (
            latest_stage_run_id(self.run.staging_dir, "detection")
            or self.run.run_id
            or ""
        )
        extract_artifact = load_extract_branch(
            self.run.library_root, self.ctx.doc_id, extract_run_id
        )
        detection_artifact = load_detection_branch(
            self.run.library_root, self.ctx.doc_id, detection_run_id
        )
        if extract_artifact is None or detection_artifact is None:
            raise RuntimeError("initial fork artifacts are incomplete")
        joined = join_evidence_artifacts(extract_artifact, detection_artifact)
        self.source_evidence_count = persist_source_evidence(
            self.run.library_root, joined
        )
        self.candidates = _candidates_from_evidence(
            detection_results(detection_artifact), joined.evidence
        )
        save_stage_summary(
            self.run.staging_dir,
            "join",
            status="success",
            message="Joined extract and detection evidence",
            run_id=self.run.run_id,
        )
        self.extract_artifact = extract_artifact
        self.detection_artifact = detection_artifact
        return True

    # -- orchestration -------------------------------------------------------

    def run_fork(self) -> Any:
        """Run the pending initial-fork branches and return the joined result."""
        from ..stage_artifacts import (
            _extracted_from_evidence,
            load_document_evidence,
            summarize_molecules,
        )

        checkpoint = load_run_checkpoint(self.run.staging_dir) or {}
        statuses = checkpoint.get("stages", {})
        self.pending_branches = [
            name
            for name in self.branch_names
            if statuses.get(name, {}).get("status") != "success"
        ]
        self.branch_stages = {stage.name: stage for stage in self.active_stages[:2]}

        for name in self.pending_branches:
            save_stage_summary(self.run.staging_dir, name, status="running")
            self.sink.emit("start", f"Starting {name} branch", stage=name)

        with ThreadPoolExecutor(
            max_workers=max(1, len(self.pending_branches)),
            thread_name_prefix="mbforge-branch",
        ) as executor:
            futures = {
                executor.submit(self._execute_branch, name): name
                for name in self.pending_branches
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result, branch_ctx = future.result()
                    self.branch_contexts[name] = branch_ctx
                    self.branch_results[name] = result
                    self.run.stage_timings[name] = result.elapsed_ms
                    self.sink.emit_stage_result(result)
                    if result.status == "error" and not result.recoverable:
                        self.branch_errors.append(
                            (name, RuntimeError(result.message or "stage failed"))
                        )
                    # A fresh run ID is minted per claim, so a re-run supersedes
                    # the previous attempt's run. Record the new run ID, then reap
                    # the superseded branch run once the re-run succeeded.
                    previous_run_id = latest_stage_run_id(self.run.staging_dir, name)
                    save_stage_summary(
                        self.run.staging_dir,
                        name,
                        status=("error" if result.status == "error" else "success"),
                        elapsed_ms=result.elapsed_ms,
                        message=result.message,
                        context=result.context,
                        error_code=result.error_code,
                        run_id=self.run.run_id,
                    )
                    if (
                        result.status != "error"
                        and previous_run_id
                        and previous_run_id != self.run.run_id
                    ):
                        from ..run_artifacts import reap_stage_run

                        reap_stage_run(
                            self.run.staging_dir,
                            self.run.library_root,
                            self.ctx.doc_id,
                            name,
                            previous_run_id,
                        )
                except BaseException as exc:
                    self.branch_errors.append((name, exc))
                    save_stage_summary(
                        self.run.staging_dir,
                        name,
                        status="error",
                        message=str(exc),
                        run_id=self.run.run_id,
                    )
                    if isinstance(exc, TaskCancelledError):
                        self.sink.emit(
                            "cancelled",
                            "Pipeline cancelled by user",
                            stage=name,
                            error_code=PIPELINE_CANCELLED,
                        )
                    else:
                        self.sink.emit(name, f"Exception: {exc}", error=str(exc))
                else:
                    try:
                        self._try_join()
                    except BaseException as exc:
                        self.join_errors.append(exc)

        if not self.join_attempted and not self.branch_errors:
            try:
                self._try_join()
            except BaseException as exc:
                self.join_errors.append(exc)

        if self.branch_errors:
            name, error = self.branch_errors[0]
            if isinstance(error, TaskCancelledError):
                raise error
            raise RuntimeError(f"{name} branch failed: {error}") from error
        if self.join_errors:
            raise self.join_errors[0]
        if self.extract_artifact is None or self.detection_artifact is None:
            raise RuntimeError("initial branches are not ready to join")

        self.ctx.document_evidence = load_document_evidence(
            self.run.library_root, self.ctx.doc_id
        )
        self.ctx.source_evidence_count = self.source_evidence_count
        self.ctx.extracted = _extracted_from_evidence(
            self.extract_artifact, self.ctx.document_evidence
        )
        self.ctx.candidates = self.candidates
        self.ctx.molecule_stats = summarize_molecules(
            self.candidates,
            dict(self.detection_artifact.meta.get("molecule_stats", {})),
        )

        self.ctx.duration_ms = self.run.elapsed_ms()
        self.sink.emit(
            "info",
            f"Initial branches joined in {self.ctx.duration_ms}ms — next: markdown",
            stage="pipeline",
        )
        return self.run.as_public_result(
            completed_stage="detection", next_stage="markdown"
        )


__all__ = ["InitialForkRunner"]
