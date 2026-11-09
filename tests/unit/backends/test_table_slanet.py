"""``table_slanet.predict_table``: degradation and cell-text attribution.

The recognizer is best-effort enrichment: without weights it must report a
clear error state, and ``predict_table`` must return an empty string instead
of raising. No test here downloads weights or touches the network.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from mbforge.foundation.inference import table_slanet
from mbforge.foundation.inference.ocr import page_text


def test_predict_table_keeps_label_at_cell_edge_without_borrowing_neighbours(
    monkeypatch,
) -> None:
    """CN121270515A p20: recognised 6 must survive SLANet's slight box error.

    Existing coverage only checks unavailable models. This protects real
    cell attribution through the public image-to-HTML boundary without weights.
    """
    vocabulary = table_slanet._STRUCTURE_CHARS
    tokens = ["sos", "<tr>", "<td></td>", "</tr>", "eos"]
    probs = np.zeros((1, len(tokens), len(vocabulary)), dtype=np.float32)
    for index, token in enumerate(tokens):
        probs[0, index, vocabulary.index(token)] = 1
    boxes = np.zeros((1, len(tokens), 4), dtype=np.float32)
    boxes[0, 2] = [491.46252 / 833, 188.37361 / 273, 518.71161 / 833, 212.65633 / 273]
    monkeypatch.setattr(
        table_slanet, "_SESSION", SimpleNamespace(run=lambda *args: [boxes, probs])
    )
    monkeypatch.setattr(table_slanet, "_AVAILABLE", True)
    monkeypatch.setattr(table_slanet, "_preprocess", lambda image: (image, 1.0))

    def recognize(image, regions):
        result = {}
        for text, line in (
            ("6", [[509, 188], [528, 187], [531, 215], [512, 216]]),
            ("5", [[98, 184], [120, 184], [120, 218], [98, 218]]),
            ("7", [[523, 188], [525, 188], [525, 212], [523, 212]]),
        ):
            region = page_text._region_for_box(regions, line)
            if region is not None:
                result[region] = text
        return result

    monkeypatch.setattr(page_text, "read_text_in_boxes", recognize)
    html = table_slanet.predict_table(np.zeros((273, 833, 3), dtype=np.uint8))
    assert "<td>6</td>" in html
    assert "<td>5</td>" not in html
    assert "<td>7</td>" not in html


def test_molecule_areas_are_masked_and_replaced_by_their_cell_token(
    monkeypatch,
) -> None:
    """A structure drawn in a table cell is not read as text.

    The cell keeps a token at the structure's row/column position, and any
    printed label beside the drawing survives next to it. Only cell-text
    recognition sees the masked copy; the caller's crop is left untouched.
    """
    vocabulary = table_slanet._STRUCTURE_CHARS
    tokens = ["sos", "<tr>", "<td></td>", "<td></td>", "</tr>", "eos"]
    probs = np.zeros((1, len(tokens), len(vocabulary)), dtype=np.float32)
    for index, token in enumerate(tokens):
        probs[0, index, vocabulary.index(token)] = 1
    boxes = np.zeros((1, len(tokens), 4), dtype=np.float32)
    # Two cells: left [10,10,100,80], right [110,10,200,80] on a 220x120 crop.
    boxes[0, 2] = [10 / 220, 10 / 120, 100 / 220, 80 / 120]
    boxes[0, 3] = [110 / 220, 10 / 120, 200 / 220, 80 / 120]
    monkeypatch.setattr(
        table_slanet, "_SESSION", SimpleNamespace(run=lambda *args: [boxes, probs])
    )
    monkeypatch.setattr(table_slanet, "_AVAILABLE", True)
    monkeypatch.setattr(table_slanet, "_preprocess", lambda image: (image, 1.0))

    seen: dict[str, np.ndarray] = {}

    def recognize(image, regions):
        seen["image"] = np.array(image)
        return {"slanet-cell-0": "1", "slanet-cell-1": "12.5"}

    monkeypatch.setattr(page_text, "read_text_in_boxes", recognize)

    image = np.zeros((120, 220, 3), dtype=np.uint8)
    molecule = {"token": "[MOL:0]", "bbox": [112, 12, 198, 78]}
    html = table_slanet.predict_table(image, molecule_cells=[molecule])

    # The structure drawing is blanked before recognition...
    assert (seen["image"][20:70, 120:190] == 255).all()
    # ...without touching the text cell or the caller's crop.
    assert (seen["image"][20:70, 20:90] == 0).all()
    assert (image[20:70, 120:190] == 0).all()
    # The token stays in the cell that holds the drawing, next to its label.
    assert "<td>1</td>" in html
    assert "<td>[MOL:0] 12.5</td>" in html


def test_unavailable_model_degrades_without_network(monkeypatch) -> None:
    """Missing weights record a clear error state on ``load``, and
    ``predict_table`` then returns ``""`` without raising or downloading."""
    monkeypatch.setattr(table_slanet, "_SESSION", None)
    monkeypatch.setattr(table_slanet, "_AVAILABLE", False)
    monkeypatch.setattr(table_slanet, "_ERROR", "")
    monkeypatch.setattr(
        "mbforge.server.resource_manager.ResourceManager.get_slanet_path",
        lambda: None,
    )
    monkeypatch.setattr(
        "mbforge.server.resource_manager.ResourceManager.ensure",
        lambda resource_id: None,
    )

    table_slanet.load()
    assert table_slanet._SESSION is None
    assert table_slanet._AVAILABLE is False
    assert "not found" in table_slanet._ERROR

    # The predictor degrades to an empty string instead of raising.
    monkeypatch.setattr(table_slanet, "_ERROR", "not loaded")
    monkeypatch.setattr(table_slanet, "load", lambda device=None: None)
    image = np.zeros((40, 80, 3), dtype=np.uint8)
    assert table_slanet.predict_table(image) == ""
