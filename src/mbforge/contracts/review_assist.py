"""Review-assist contracts: the bounded packet and the recorded suggestion.

A review item is the place where the deterministic rules refused to decide: a
drawing with an unread number, a structure flagged by context, a reading no
structure owns. The assist packet hands the model what a human reviewer would
look at - the printed text and the original images - and asks one bounded
question. The answer is a suggestion: it is stored next to the item, shown to
the reviewer, and never applied by itself.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

#: answered/refused are model outcomes; unavailable/error are transport or
#: configuration failures (no vision model, sidecar down, HTTP 4xx).
AssistStatus = Literal["answered", "refused", "unavailable", "error"]
AssistImageKind = Literal["crop", "page"]
AssistMediaType = Literal["image/png", "image/jpeg"]


class AssistImage(BaseModel):
    """One original image handed to the model.

    A crop is the exact molecule drawing the detector cut out of the page; a
    page image is the surrounding printed region, so the model can see the
    number the crop itself does not carry.
    """

    model_config = ConfigDict(extra="forbid")

    kind: AssistImageKind
    media_type: AssistMediaType = "image/png"
    label: str = ""
    page: int | None = None
    width: int | None = None
    height: int | None = None
    data_base64: str = Field(min_length=1)


class AssistCandidate(BaseModel):
    """A recognized structure the model may choose from (never invent)."""

    model_config = ConfigDict(extra="forbid")

    mol_id: str = ""
    smiles: str = ""
    name: str = ""
    page: int | None = None
    bbox: list[float] | None = None


class AssistPacket(BaseModel):
    """Everything one assist call may see, bounded by the caller.

    The model never receives a filesystem path: images travel as base64, text as
    bounded strings, and candidates as the identities the pipeline already
    recognized. vision_requested is False when no vision model is configured, so
    a text-only answer is never presented as if it had seen the drawing.
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    item_id: str
    doc_id: str = ""
    page: int | None = None
    question: str
    text: str = ""
    candidates: list[AssistCandidate] = Field(default_factory=list)
    images: list[AssistImage] = Field(default_factory=list)
    vision_requested: bool = False


class AssistSuggestion(BaseModel):
    """One model answer, stored beside the item and shown to the reviewer."""

    model_config = ConfigDict(extra="forbid")

    status: AssistStatus = "error"
    model: str = ""
    vision: bool = False
    answer: str = ""
    error: str = ""
