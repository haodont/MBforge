"""Notes endpoints — per-library markdown notes with backlinks.

Thin HTTP shell: validation and async wrapping only; persistence and
business rules live in :mod:`mbforge.application.use_cases.documents.notes`.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from mbforge.application.dto.notes import (
    NoteEntry,
    NotesBacklinksRequest,
    NotesBacklinksResponse,
    NotesDeleteRequest,
    NotesDeleteResponse,
    NotesGetRequest,
    NotesGetResponse,
    NotesListRequest,
    NotesListResponse,
    NotesSaveRequest,
    NotesSaveResponse,
)
from mbforge.application.use_cases.documents import notes as notes_service
from mbforge.interfaces.http._path_utils import resolve_root

router = APIRouter()


@router.post("/list", response_model=NotesListResponse)
async def notes_list(body: NotesListRequest) -> NotesListResponse:
    library_root = resolve_root(body)
    index = await asyncio.to_thread(notes_service.load_index, library_root)
    return NotesListResponse(success=True, notes=[NoteEntry(**n) for n in index])


@router.post("/get", response_model=NotesGetResponse)
async def notes_get(body: NotesGetRequest) -> NotesGetResponse:
    library_root = resolve_root(body)
    text = await asyncio.to_thread(notes_service.read_note, library_root, body.note_id)
    return NotesGetResponse(success=True, notes=text)


@router.post("/save", response_model=NotesSaveResponse)
async def notes_save(body: NotesSaveRequest) -> NotesSaveResponse:
    library_root = resolve_root(body)
    note = body.note
    await asyncio.to_thread(
        notes_service.write_note, library_root, note.id, note.content
    )
    entry = NoteEntry(
        id=note.id,
        title=note.title,
        tags=list(note.tags),
        links=list(note.links),
        created_at=note.created_at,
        updated_at=note.updated_at,
    )
    await asyncio.to_thread(
        notes_service.upsert_index_entry,
        library_root,
        note.id,
        entry.model_dump(by_alias=True),
    )
    return NotesSaveResponse(success=True, note=entry)


@router.post("/delete", response_model=NotesDeleteResponse)
async def notes_delete(body: NotesDeleteRequest) -> NotesDeleteResponse:
    library_root = resolve_root(body)
    await asyncio.to_thread(notes_service.delete_note, library_root, body.note_id)
    await asyncio.to_thread(
        notes_service.remove_index_entry, library_root, body.note_id
    )
    return NotesDeleteResponse(success=True)


@router.post("/backlinks", response_model=NotesBacklinksResponse)
async def notes_backlinks(body: NotesBacklinksRequest) -> NotesBacklinksResponse:
    library_root = resolve_root(body)
    result = await asyncio.to_thread(
        notes_service.backlinks_for, library_root, body.target_id
    )
    return NotesBacklinksResponse(
        success=True, backlinks=[NoteEntry(**n) for n in result]
    )
