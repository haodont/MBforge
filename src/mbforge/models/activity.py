from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ActivityRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    activity_id: str | None = None
    review_id: str | None = None
    source: Literal["activities", "review_items"]
    status: Literal["persisted", "pending", "confirmed", "rejected"]
    mol_id: str | None = None
    doc_id: str
    activity_type: str
    value: float | None = None
    value_original: float | None = None
    unit_original: str | None = None
    operator: str | None = None
    measurement_kind: str | None = None
    metric: str | None = None
    value_canonical: float | None = None
    unit_canonical: str | None = None
    operator_original: str | None = None
    scale: str | None = None
    value_text: str | None = None
    qualitative_raw: str | None = None
    qualitative_rank: int | None = None
    qualitative_scheme: str | None = None
    qualitative_label: str | None = None
    reference_raw: str | None = None
    reference_key: str | None = None
    reference_type: str | None = None
    target: str | None = None
    assay_type: str | None = None
    assay_description: str | None = None
    confidence: float | None = None
    page_num: int | None = None
    table_idx: int | None = None
    row_idx: int | None = None
    col_idx: int | None = None
    row_label: str | None = None
    row_smiles: str | None = None
    raw_text: str | None = None
    created_at: str | None = None
    reasons: list[str] = Field(default_factory=list)
