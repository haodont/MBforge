"""Unit tests for the unified molecule recognition entry."""

from __future__ import annotations

from PIL import Image

import mbforge.service.pipeline.detection.recognition as recognize_mod
from mbforge.service.pipeline.detection.recognition import (
    RecognizedMolecule,
    recognize_molecule,
    select_primary_coref,
)


class _FakePredictResult:
    esmiles = "CCO<sep>NH2"
    smiles = "CCO"


# (coref reads, expected primary) — isolated reads win over inline fragments,
# and ties prefer the bare digit.
_COREF_CASES = [
    ([("26-a", (0, 0, 30, 10), True), ("26", (150, 200, 180, 230), True)], "26"),
    # A digit read from a prose line loses to an isolated read even when the
    # fragment sits further bottom-right (the '3' vs '21' case).
    ([("21", (10, 0, 30, 12), True), ("3", (150, 200, 170, 214), False)], "21"),
    ([("26-a", (0, 0, 30, 30), True), ("26", (0, 0, 30, 30), True)], "26"),
    ([], ""),
]


def test_select_primary_coref_ranks_isolated_bottom_right_reads() -> None:
    """Position decides first; inline fragments are demoted; ties prefer '26'."""
    for reads, expected in _COREF_CASES:
        assert select_primary_coref(reads) == expected, reads


def test_recognize_molecule_merges_backends_and_degrades(monkeypatch) -> None:
    """MolParser supplies the structure, OCR the labels; failures degrade."""
    image = Image.new("L", (10, 10), 255)
    others_image = Image.new("L", (5, 5), 0)
    seen: dict[str, object] = {}

    def fake_preprocess(img):
        seen["input"] = img
        return img, others_image

    def fake_predict(main):
        seen["main_is_input"] = main is image
        return _FakePredictResult()

    monkeypatch.setattr(recognize_mod, "preprocess_mol_image", fake_preprocess)
    monkeypatch.setattr(recognize_mod.molparser, "predict", fake_predict)
    monkeypatch.setattr(
        recognize_mod,
        "extract_label_reads",
        lambda img: [
            ("2", 0.98, (90, 120, 100, 132), True),
            ("4A", 0.95, (10, 5, 20, 15), True),
        ],
    )

    out = recognize_molecule(image)

    assert out == RecognizedMolecule(
        esmiles="CCO<sep>NH2",
        smiles="CCO",
        coref=["2", "4A"],
        coref_primary="2",
    )
    assert seen["input"] is image
    assert seen["main_is_input"] is True

    # No offcut fragments: OCR is skipped entirely.
    def fake_preprocess_none(img):
        return img, None

    def fail_ocr(img):  # pragma: no cover - must not be called
        raise AssertionError("OCR must not run when others is None")

    monkeypatch.setattr(recognize_mod, "preprocess_mol_image", fake_preprocess_none)
    monkeypatch.setattr(recognize_mod, "extract_label_reads", fail_ocr)

    out = recognize_molecule(Image.new("L", (8, 8), 255))
    assert out.coref == [] and out.coref_primary == ""
    assert out.esmiles == "CCO<sep>NH2"

    # MolParser failure: empty structure fields, but OCR labels still arrive.
    class _ErrorResult:
        esmiles = ""
        smiles = ""

    monkeypatch.setattr(
        recognize_mod,
        "preprocess_mol_image",
        lambda img: (img, Image.new("L", (5, 5), 0)),
    )
    monkeypatch.setattr(recognize_mod.molparser, "predict", lambda img: _ErrorResult())
    monkeypatch.setattr(
        recognize_mod,
        "extract_label_reads",
        lambda img: [("2", 0.9, (80, 110, 90, 122), True)],
    )

    out = recognize_molecule(Image.new("L", (8, 8), 255))
    assert out == RecognizedMolecule(
        esmiles="", smiles="", coref=["2"], coref_primary="2"
    )
