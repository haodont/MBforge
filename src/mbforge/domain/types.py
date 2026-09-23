"""Shared dataclasses for raw molecule detection records.

``DetectionSource`` and ``ExtractionResult`` describe observations produced
by detection backends.  The canonical molecule entity itself is
:class:`mbforge.domain.molecule.Molecule`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
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
    """分子提取结果.

    Attributes:
        esmiles: 识别出的 E-SMILES 字符串（Layer 2，含 <sep> 标签或纯 SMILES）
        smiles: Layer 1 纯 SMILES（RDKit 可解析；MolParser 输出含标签时由
            postprocess 分离，供下游 normalize/RDKit 使用）
        name: 化合物名称（可选）
        source: 来源类型：image=图像检测, text=文本正则, manual=手动录入
        moldet_conf: MolDetv2 检测置信度（图像来源时有效）
        bbox_pdf: PDF 坐标系中的边界框（点单位，左下原点）
        page_idx: PDF 页码（从 0 开始）
        context_text: 关联到的文本上下文（caption / 段落 / 表格单元格）
        mol_img_path: 裁剪保存的分子图像路径（图像来源时有效）
        status: 审核状态：pending=待确认, confirmed=已入库, rejected=已丢弃
    """

    esmiles: str
    smiles: str = ""
    name: str = ""
    source: Literal["image", "text", "manual"] = "image"
    moldet_conf: float = 0.0
    bbox_pdf: tuple[float, float, float, float] | None = None
    page_idx: int | None = None
    context_text: str = ""
    mol_img_path: Path | None = None
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    properties: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """序列化为字典."""
        return {
            "esmiles": self.esmiles,
            "smiles": self.smiles,
            "name": self.name,
            "source": self.source,
            "moldet_conf": self.moldet_conf,
            "bbox_pdf": self.bbox_pdf,
            "page_idx": self.page_idx,
            "context_text": self.context_text,
            "mol_img_path": str(self.mol_img_path) if self.mol_img_path else None,
            "status": self.status,
            "properties": self.properties,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ExtractionResult:
        """从字典反序列化."""
        img_path = data.get("mol_img_path")
        source = data.get("source", "image")
        raw_esmiles = data.get("esmiles", "") or data.get("smiles", "")
        smiles = data.get("smiles", "")
        if not smiles and source != "image":
            smiles = raw_esmiles
        return cls(
            esmiles=raw_esmiles,
            smiles=smiles,
            name=data.get("name", ""),
            source=source,
            moldet_conf=data.get("moldet_conf", 0.0),
            bbox_pdf=tuple(data["bbox_pdf"]) if data.get("bbox_pdf") else None,
            page_idx=data.get("page_idx"),
            context_text=data.get("context_text", ""),
            mol_img_path=Path(img_path) if img_path else None,
            status=data.get("status", "pending"),
            properties=data.get("properties", {}),
        )


__all__ = [
    "DetectionSource",
    "ExtractionResult",
    "strip_esmiles_tags",
]
