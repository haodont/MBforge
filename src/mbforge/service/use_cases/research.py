"""Persistent visible conversations, bounded sidecar turns and scoped tool access."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from uuid import uuid4

from mbforge.contracts.research import (
    ResearchArtifactReference,
    ResearchContext,
    ResearchDone,
    ResearchError,
    ResearchEvent,
    ResearchMessage,
    ResearchMoleculeReference,
    ResearchRuntimeSpec,
    ResearchSession,
    ResearchSessionSummary,
    ResearchTaskReference,
    ResearchTurnRequest,
    ResearchTurnScope,
)
from mbforge.foundation.errors import ConflictError, NotFoundError, ValidationError
from mbforge.foundation.layout import LibraryLayout
from mbforge.foundation.logger import get_logger
from mbforge.ports.repositories import get_repositories
from mbforge.service.ports.research import get_research_registry, get_research_runtime
from mbforge.service.use_cases.pipeline.ingest import enqueue, list_tasks

logger = get_logger(__name__)


def _load(root: str, session_id: str) -> ResearchSession:
    session = get_repositories(root).research.get(session_id)
    if session is None:
        raise NotFoundError("Research conversation not found")
    return session


def _update(
    root: str, session_id: str, change: Callable[[ResearchSession], ResearchSession]
) -> ResearchSession:
    repository = get_repositories(root).research
    for _ in range(3):
        current = _load(root, session_id)
        updated = change(current).model_copy(
            update={"revision": current.revision + 1, "updated_at": time.time()}
        )
        try:
            repository.save(updated, current.revision)
            return updated
        except ConflictError:
            continue
    raise ConflictError("Research conversation changed; reload it")


def create_session(root: str, title: str) -> ResearchSession:
    session = ResearchSession(id=uuid4().hex, title=title, updated_at=time.time())
    get_repositories(root).research.save(session, None)
    return session


def get_session(root: str, session_id: str) -> ResearchSession:
    session = _load(root, session_id)
    orphaned = {
        message.id
        for message in session.messages
        if message.status == "pending"
        and not get_research_registry().active(root, session_id, message.request_id)
    }
    if not orphaned:
        return session
    return _update(
        root,
        session_id,
        lambda current: current.model_copy(
            update={
                "messages": [
                    message.model_copy(update={"status": "stopped"})
                    if message.id in orphaned
                    else message
                    for message in current.messages
                ]
            }
        ),
    )


def list_sessions(root: str) -> list[ResearchSessionSummary]:
    return get_repositories(root).research.list_sessions()


def import_session(root: str, session: ResearchSession) -> ResearchSession:
    """Import local visible history once; importing never runs a model or a tool."""
    existing = get_repositories(root).research.get(session.id)
    if existing is not None:
        return existing
    session = session.model_copy(
        update={
            "revision": 1,
            "pi_context_used": False,
            "context": session.context.model_copy(
                update={"allow_patent_analysis": False}
            ),
            "messages": [
                message.model_copy(update={"status": "stopped"})
                if message.status == "pending"
                else message
                for message in session.messages
            ],
        }
    )
    try:
        get_repositories(root).research.save(session, None)
    except ConflictError:
        return _load(root, session.id)
    return session


def delete_session(root: str, session_id: str) -> bool:
    session = _load(root, session_id)
    if any(
        get_research_registry().active(root, session_id, message.request_id)
        for message in session.messages
    ):
        raise ConflictError("Stop the reply before deleting this conversation")
    if session.pi_context_used and get_research_runtime().is_active(session_id):
        raise ConflictError(
            "Wait for the reply to finish stopping before deleting this conversation"
        )
    # Deleting a conversation does not cancel queue work or remove its artifacts.
    return get_repositories(root).research.delete(session_id, session.revision)


async def validate_context(root: str, context: ResearchContext) -> ResearchContext:
    repositories = get_repositories(root)
    for doc_id in context.document_ids:
        if await asyncio.to_thread(repositories.documents.get, doc_id) is None:
            raise ValidationError("A selected document is unavailable in this library")
    molecules: list[ResearchMoleculeReference] = []
    for reference in context.molecule_refs:
        molecule = await asyncio.to_thread(
            repositories.molecules.get_row, reference.mol_id
        )
        if molecule is None:
            raise ValidationError("A selected molecule is unavailable in this library")
        molecules.append(
            ResearchMoleculeReference(
                mol_id=reference.mol_id,
                name=str(molecule.get("name") or reference.mol_id)[:160],
            )
        )
    tasks = await list_tasks(root) if context.task_refs else []
    for reference in context.task_refs:
        if not any(
            task["id"] == reference.task_id
            and task["run_id"] == reference.run_id
            and task["doc_id"] == reference.doc_id
            for task in tasks
        ):
            raise ValidationError("A selected task is unavailable in this library")
    if context.allow_patent_analysis and not context.document_ids:
        raise ValidationError("Select documents before authorizing Patent analysis")
    return context.model_copy(
        update={
            "document_ids": list(dict.fromkeys(context.document_ids)),
            "molecule_refs": molecules,
        }
    )


@dataclass(frozen=True)
class PreparedTurn:
    root: str
    session_id: str
    request_id: str
    credential: str | None
    replay: ResearchMessage | None = None


async def prepare_turn(
    root: str, session_id: str, request: ResearchTurnRequest
) -> PreparedTurn:
    if not request.message.strip():
        raise ValidationError("A research question is required")
    session = await asyncio.to_thread(get_session, root, session_id)
    previous_user = next(
        (
            message
            for message in session.messages
            if message.request_id == request.request_id and message.role == "user"
        ),
        None,
    )
    if previous_user:
        if (
            previous_user.content != request.message
            or previous_user.context != request.context
        ):
            raise ConflictError(
                "Request identifier was already used for a different message"
            )
        reply = next(
            message
            for message in session.messages
            if message.request_id == request.request_id and message.role == "assistant"
        )
        if reply.status == "pending":
            raise ConflictError("This reply is already running")
        return PreparedTurn(root, session_id, request.request_id, None, reply)
    if len(session.messages) >= 200:
        raise ValidationError("This research conversation reached its 100-turn limit")
    context = await validate_context(root, request.context)
    scope = ResearchTurnScope(
        library_root=root,
        session_id=session_id,
        request_id=request.request_id,
        context=context,
        message=request.message,
        history=session.messages,
    )
    credential = get_research_registry().register(scope)
    try:
        user = ResearchMessage(
            id=uuid4().hex,
            request_id=request.request_id,
            role="user",
            content=request.message,
            context=request.context,
        )
        assistant = ResearchMessage(
            id=uuid4().hex,
            request_id=request.request_id,
            role="assistant",
            content="",
            status="pending",
        )
        await asyncio.to_thread(
            _update,
            root,
            session_id,
            lambda current: current.model_copy(
                update={
                    "title": request.message[:48]
                    if not current.messages
                    else current.title,
                    "context": context,
                    "pi_context_used": True,
                    "messages": [*current.messages, user, assistant],
                }
            ),
        )
    except BaseException:
        get_research_registry().revoke(credential)
        raise
    return PreparedTurn(root, session_id, request.request_id, credential)


def resolve_scope(credential: str) -> ResearchTurnScope:
    scope = get_research_registry().resolve(credential)
    if scope is None:
        raise NotFoundError("Research turn is no longer active")
    return scope


def runtime_spec(credential: str) -> ResearchRuntimeSpec:
    scope = resolve_scope(credential)
    return ResearchRuntimeSpec(
        session_id=scope.session_id,
        session_file=str(
            LibraryLayout(scope.library_root).research_session_file(scope.session_id)
        ),
        message=scope.message,
        context=scope.context,
        history=scope.history,
    )


def _update_reply(
    turn: PreparedTurn, change: Callable[[ResearchMessage], ResearchMessage]
) -> None:
    _update(
        turn.root,
        turn.session_id,
        lambda session: session.model_copy(
            update={
                "messages": [
                    change(message)
                    if message.role == "assistant"
                    and message.request_id == turn.request_id
                    else message
                    for message in session.messages
                ]
            }
        ),
    )


async def stream_turn(turn: PreparedTurn) -> AsyncIterator[ResearchEvent]:
    if turn.replay:
        from mbforge.contracts.research import (
            ResearchArtifactEvent,
            ResearchReviewEvent,
            ResearchTaskEvent,
        )

        for reference in turn.replay.task_refs:
            yield ResearchTaskEvent(reference=reference)
        for artifact in turn.replay.artifact_refs:
            yield ResearchArtifactEvent(reference=artifact)
        for review in turn.replay.review_refs:
            yield ResearchReviewEvent(items=[review])
        yield ResearchDone(text=turn.replay.content, status=turn.replay.status)
        return
    if turn.credential is None:
        raise ValueError("An active turn must have a credential")
    text = ""
    terminal = False
    try:
        async for event in get_research_runtime().stream(turn.credential):
            if event.type == "delta":
                text += event.text
                if len(text) > 60_000:
                    raise ValueError("Research response exceeded its size limit")
            elif event.type == "task":
                await asyncio.to_thread(
                    _update_reply,
                    turn,
                    lambda message, reference=event.reference: message.model_copy(
                        update={
                            "task_refs": [*message.task_refs, reference]
                            if not any(
                                item.task_id == reference.task_id
                                for item in message.task_refs
                            )
                            else message.task_refs
                        }
                    ),
                )
            elif event.type == "artifact":
                await asyncio.to_thread(
                    _update_reply,
                    turn,
                    lambda message, reference=event.reference: message.model_copy(
                        update={
                            "artifact_refs": [
                                item
                                for item in message.artifact_refs
                                if item.doc_id != reference.doc_id
                            ]
                            + [reference]
                        }
                    ),
                )
            elif event.type == "review":
                reference = event.items[0] if event.items else None
                if reference is not None:
                    await asyncio.to_thread(
                        _update_reply,
                        turn,
                        lambda message, ref=reference: message.model_copy(
                            update={
                                "review_refs": [
                                    item
                                    for item in message.review_refs
                                    if item.item_id != ref.item_id
                                ]
                                + [ref]
                            }
                        ),
                    )
            elif event.type in ("done", "error"):
                if event.type == "done":
                    text, status = event.text, event.status
                else:
                    status = "failed"
                await asyncio.to_thread(
                    _update_reply,
                    turn,
                    lambda message, content=text, reply_status=status: (
                        message.model_copy(
                            update={"content": content, "status": reply_status}
                        )
                    ),
                )
                terminal = True
            yield event
            if terminal:
                break
        if not terminal:
            raise ValueError("Research stream ended without a terminal event")
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Research transport failed (%s)", type(exc).__name__)
        await asyncio.to_thread(
            _update_reply,
            turn,
            lambda message: message.model_copy(
                update={"content": text, "status": "failed"}
            ),
        )
        terminal = True
        yield ResearchError(
            message="The research assistant disconnected. Your conversation and background tasks are retained."
        )
    finally:
        try:
            if not terminal:
                await asyncio.shield(
                    asyncio.to_thread(
                        _update_reply,
                        turn,
                        lambda message: message.model_copy(
                            update={"content": text, "status": "stopped"}
                        ),
                    )
                )
        finally:
            get_research_registry().revoke(turn.credential)


async def start_patent_analysis(
    credential: str, doc_ids: list[str]
) -> list[ResearchTaskReference]:
    scope = resolve_scope(credential)
    if not scope.context.allow_patent_analysis or not set(doc_ids).issubset(
        scope.context.document_ids
    ):
        raise ValidationError(
            "Patent analysis must be explicitly authorized for selected documents in this turn"
        )
    if not doc_ids:
        raise ValidationError("Select at least one document")
    turn = PreparedTurn(
        scope.library_root, scope.session_id, scope.request_id, credential
    )
    references: list[ResearchTaskReference] = []
    for doc_id in dict.fromkeys(doc_ids):
        session = await asyncio.to_thread(_load, scope.library_root, scope.session_id)
        reply = next(
            message
            for message in session.messages
            if message.request_id == scope.request_id and message.role == "assistant"
        )
        existing = [
            reference for reference in reply.task_refs if reference.doc_id == doc_id
        ]
        if existing:
            references.extend(existing)
            continue
        evidence = await asyncio.to_thread(
            get_repositories(scope.library_root).evidence.list, doc_id
        )
        run_id = await enqueue(
            scope.library_root,
            doc_id,
            stages=("patent",) if evidence else ("extract", "markdown", "patent"),
            request_key=f"{scope.session_id}:{scope.request_id}",
        )
        tasks = await list_tasks(scope.library_root)
        added = [
            ResearchTaskReference(
                task_id=task["id"], run_id=task["run_id"], doc_id=task["doc_id"]
            )
            for task in tasks
            if task["doc_id"] == doc_id and task["run_id"] == run_id
        ]
        await asyncio.to_thread(
            _update_reply,
            turn,
            lambda message, added=added: message.model_copy(
                update={
                    "task_refs": list(
                        {
                            reference.task_id: reference
                            for reference in [*message.task_refs, *added]
                        }.values()
                    )
                }
            ),
        )
        references.extend(added)
    return references


async def record_artifact(
    credential: str, reference: ResearchArtifactReference
) -> None:
    scope = resolve_scope(credential)
    turn = PreparedTurn(
        scope.library_root, scope.session_id, scope.request_id, credential
    )
    await asyncio.to_thread(
        _update_reply,
        turn,
        lambda message: message.model_copy(
            update={
                "artifact_refs": [
                    item
                    for item in message.artifact_refs
                    if item.doc_id != reference.doc_id
                ]
                + [reference]
            }
        ),
    )


async def abandon_turn(turn: PreparedTurn) -> None:
    if turn.credential is None:
        return
    try:
        session = await asyncio.to_thread(_load, turn.root, turn.session_id)
        if any(
            message.request_id == turn.request_id
            and message.role == "assistant"
            and message.status == "pending"
            for message in session.messages
        ):
            await asyncio.to_thread(
                _update_reply,
                turn,
                lambda message: (
                    message.model_copy(update={"status": "stopped"})
                    if message.status == "pending"
                    else message
                ),
            )
    finally:
        get_research_registry().revoke(turn.credential)
