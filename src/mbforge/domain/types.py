"""Shared dataclasses for raw molecule detection records.

``DetectionSource`` and ``ExtractionResult`` describe observations produced
by detection backends.  The canonical molecule entity itself is
:class:`mbforge.domain.molecule.Molecule`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class DetectionSource:
    """One concrete detection of a molecule in a document.

    Attributes:
        source: Origin of the detection (image model, text regex, manual entry).
        page: Page index in the PDF (0-based), if known.
        bbox: Bounding box in PDF coordinates (left, bottom, right, top), if known.
        image_path: Path to the cropped molecule image for image detections.
        confidence: MolDet detection confidence, normalized to [0, 1]. Used
            for ranking detections.
        conf_moldet: MolDet detection confidence for image detections.
        evidence_id: Runtime-only ID assigned after Join has canonicalized the
            page bbox. It is never written to the raw Detection artifact.
    """

    source: Literal["image", "text", "manual"]
    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    image_path: str | None = None
    confidence: float = 0.0
    conf_moldet: float = 0.0
    evidence_id: str | None = None


def strip_esmiles_tags(esmiles: str) -> str:
    """从 E-SMILES 提取 Layer 1 纯 SMILES（去掉 ``<sep>`` 及其后的扩展标签）.

    MolParser 输出 ``SMILES<sep>EXTENSION``；RDKit 只能解析 ``<sep>`` 之前的
    部分。无标签时原样返回。
    """
    if not esmiles:
        return ""
    return esmiles.split("<sep>", 1)[0]


@dataclass
class ExtractionResult:
    """一次分子观测（分子链路的原始产物）.

    Attributes:
        smiles: Layer 1 纯 SMILES（RDKit 可解析）
        esmiles: 识别出的 E-SMILES（Layer 2，含 ``<sep>`` 标签或纯 SMILES）
        moldet_conf: MolDetv2 检测置信度
        bbox_pdf: PDF 坐标系中的边界框（点单位，左下原点）。落库时不写进载荷——
            证据行的 ``bbox_x0..y1`` 列已承载它，解码时按行补回。
        page_idx: PDF 页码（从 0 开始）。同上，由证据行的 ``page`` 列承载。
        name: 化合物名称/编号（裁切标签 OCR 结果，可选）
        mol_img_path: 裁剪图的库内相对路径（``storage/{doc_id}/crops/{name}``）
        properties: 生产者附加的原始元数据
            （``markush`` / ``groups`` / ``role_context`` / ``ocr_labels`` /
            ``ocr_labels_primary``）
    """

    smiles: str
    esmiles: str = ""
    moldet_conf: float = 0.0
    bbox_pdf: tuple[float, float, float, float] | None = None
    page_idx: int | None = None
    name: str = ""
    mol_img_path: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典."""
        return {
            "smiles": self.smiles,
            "esmiles": self.esmiles,
            "moldet_conf": self.moldet_conf,
            "bbox_pdf": self.bbox_pdf,
            "page_idx": self.page_idx,
            "name": self.name,
            "mol_img_path": self.mol_img_path,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionResult:
        """从字典反序列化."""
        img_path = data.get("mol_img_path")
        raw_esmiles = data.get("esmiles", "") or data.get("smiles", "")
        smiles = data.get("smiles", "") or raw_esmiles
        return cls(
            smiles=smiles,
            esmiles=raw_esmiles,
            moldet_conf=data.get("moldet_conf", 0.0),
            bbox_pdf=tuple(data["bbox_pdf"]) if data.get("bbox_pdf") else None,
            page_idx=data.get("page_idx"),
            name=data.get("name", ""),
            mol_img_path=str(img_path) if img_path else None,
            properties=data.get("properties", {}),
        )


__all__ = [
    "DetectionSource",
    "ExtractionResult",
    "strip_esmiles_tags",
]
