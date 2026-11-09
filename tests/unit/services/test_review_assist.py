"""Review-center AI assistance: bounded packet, safe paths, stored suggestion.

Functions under test: ``build_packet`` / ``assist_items`` / ``attach_suggestions``.

The contract that matters: the model receives the printed text and the original
images (never a path), the answer is a stored suggestion rather than a decision,
and a text-only configuration never pretends to have seen the drawing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mbforge.contracts.review_assist import AssistSuggestion
from mbforge.db.source_evidence import persist_source_evidence
from mbforge.db.sqlite.database import DatabaseManager
from mbforge.domain.evidence import SourceEvidence
from mbforge.foundation.errors import ValidationError
from mbforge.service.ports.review_assist import configure_review_assist_runtime
from mbforge.service.use_cases import review_assist

DOC = "doc1"


class _FakeRuntime:
    """Records every packet and answers with a candidate suggestion."""

    def __init__(self) -> None:
        self.calls: list = []

    def run(self, packet, *, timeout_seconds: float = 120.0) -> AssistSuggestion:
        self.calls.append(packet)
        return AssistSuggestion(
            status="answered",
            model="fake-vlm",
            vision=bool(packet.images),
            answer="answer=cand-1",
        )


def _seed(tmp_path: Path, *, crop_relpath: str | None = None) -> str:
    """One review item on page 3, its page text, and an optional crop image."""
    db = DatabaseManager.get(str(tmp_path))
    db.initialize()
    persist_source_evidence(
        tmp_path,
        [
            SourceEvidence.create(
                doc_id=DOC,
                page=3,
                bbox=(10.0, 800.0, 300.0, 840.0),
                raw_text="实施例17：目标化合物17的制备",
            ),
            SourceEvidence.create(
                doc_id=DOC,
                page=3,
                bbox=(10.0, 700.0, 300.0, 740.0),
                raw_text="目标化合物17的合成路线如下所示：",
            ),
            SourceEvidence.create(
                doc_id=DOC,
                page=5,
                bbox=(10.0, 500.0, 300.0, 540.0),
                raw_text="这一页离得很远，不应进入提示词。",
            ),
        ],
    )
    if crop_relpath is None:
        crops = tmp_path / "storage" / DOC / "crops"
        crops.mkdir(parents=True, exist_ok=True)
        image = crops / "mol.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        crop_relpath = str(image)
    with db.mol_conn() as conn:
        conn.execute(
            "INSERT INTO review_items ("
            "item_id, kind, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1, "
            "crop_relpath, smiles, name, confidence, reasons, context_text) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "item1",
                "review_required",
                DOC,
                3,
                10.0,
                500.0,
                300.0,
                540.0,
                crop_relpath,
                "CCO",
                "17",
                0.4,
                json.dumps(["context_mixture_or_isomer"]),
                "目标化合物17",
            ),
        )
        conn.commit()
    return crop_relpath


@pytest.fixture
def with_runtime() -> _FakeRuntime:
    runtime = _FakeRuntime()
    configure_review_assist_runtime(runtime)
    try:
        yield runtime
    finally:
        configure_review_assist_runtime(None)


def test_the_packet_carries_the_page_text_and_the_original_crop(
    tmp_path: Path, patch_config, with_runtime: _FakeRuntime
) -> None:
    _seed(tmp_path)
    patch_config(
        lambda cfg: (
            setattr(cfg.review, "enabled", True),
            setattr(cfg.vlm, "model", "vlm-test"),
        )
    )

    packet = review_assist.build_packet(str(tmp_path), "review_required", "item1")

    assert packet.page == 3
    assert "实施例17" in packet.text and "合成路线" in packet.text
    assert "离得很远" not in packet.text
    assert [image.kind for image in packet.images] == ["crop"]
    assert packet.images[0].data_base64.startswith("iVBOR")
    assert packet.vision_requested is True
    assert packet.text and not any(str(tmp_path) in packet.text for _ in [0])
    assert packet.candidates == []  # no recognized structures seeded


def test_the_original_images_are_captured_by_default_and_can_be_disabled(
    tmp_path: Path, patch_config, with_runtime: _FakeRuntime
) -> None:
    """The chat model may be multimodal, so images need no separate vlm entry."""
    _seed(tmp_path)
    patch_config(
        lambda cfg: (
            setattr(cfg.review, "enabled", True),
            setattr(cfg.vlm, "model", ""),
        )
    )

    packet = review_assist.build_packet(str(tmp_path), "review_required", "item1")

    assert [image.kind for image in packet.images] == ["crop"]
    assert packet.vision_requested is True

    patch_config(lambda cfg: setattr(cfg.review, "images", False))
    text_only = review_assist.build_packet(str(tmp_path), "review_required", "item1")
    assert text_only.images == []
    assert text_only.vision_requested is False


def test_a_crop_outside_the_document_is_never_read(
    tmp_path: Path, patch_config, with_runtime: _FakeRuntime
) -> None:
    _seed(tmp_path, crop_relpath="../../../etc/passwd")
    patch_config(
        lambda cfg: (
            setattr(cfg.review, "enabled", True),
            setattr(cfg.vlm, "model", "vlm-test"),
        )
    )

    packet = review_assist.build_packet(str(tmp_path), "review_required", "item1")

    assert packet.images == []


def test_the_answer_is_stored_and_reused_until_forced(
    tmp_path: Path, patch_config, with_runtime: _FakeRuntime
) -> None:
    _seed(tmp_path)
    patch_config(
        lambda cfg: (
            setattr(cfg.review, "enabled", True),
            setattr(cfg.vlm, "model", "vlm-test"),
        )
    )
    targets = [{"kind": "review_required", "item_id": "item1"}]

    first = review_assist.assist_items(str(tmp_path), targets)
    assert first[0]["status"] == "answered"
    assert first[0]["model"] == "fake-vlm"
    assert len(with_runtime.calls) == 1

    # A stored answer is reused: the same item never costs a second model call.
    second = review_assist.assist_items(str(tmp_path), targets)
    assert second[0]["status"] == "answered"
    assert len(with_runtime.calls) == 1

    forced = review_assist.assist_items(str(tmp_path), targets, force=True)
    assert forced[0]["status"] == "answered"
    assert len(with_runtime.calls) == 2
    stored = review_assist.assist_for(str(tmp_path), "review_required", "item1")
    assert stored is not None and stored["answer"] == "answer=cand-1"

    items = [{"id": "item1", "kind": "review_required", "payload": {"slot": 1}}]
    review_assist.attach_suggestions(str(tmp_path), items)
    assert items[0]["payload"]["slot"] == 1
    assert items[0]["payload"]["ai_assist"]["answer"] == "answer=cand-1"


def test_assistance_is_refused_when_disabled(tmp_path: Path, patch_config) -> None:
    _seed(tmp_path)
    patch_config(lambda cfg: setattr(cfg.review, "enabled", False))

    with pytest.raises(ValidationError):
        review_assist.assist_items(
            str(tmp_path), [{"kind": "review_required", "item_id": "item1"}]
        )


def test_the_automatic_pull_needs_both_switches(tmp_path: Path, patch_config) -> None:
    patch_config(
        lambda cfg: (
            setattr(cfg.review, "enabled", True),
            setattr(cfg.review, "auto", False),
        )
    )
    assert review_assist.schedule_auto_assist(str(tmp_path)) is False
    patch_config(lambda cfg: (setattr(cfg.review, "auto", True),))
    # Single-flight state is module-level; starting one is enough to prove the path.
    assert review_assist.schedule_auto_assist(str(tmp_path)) is True
