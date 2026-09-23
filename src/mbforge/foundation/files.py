"""Filesystem helpers: hashing, sizes, safe names, JSON I/O, base64 decode."""

from __future__ import annotations

import base64
import hashlib
import json as _json
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image


def sha256_file(path: Path) -> str:
    """计算文件 SHA256."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    """计算文本 SHA256."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    """计算字节内容 SHA256."""
    return hashlib.sha256(data).hexdigest()


def md5_file(path: Path) -> str:
    """计算文件 MD5."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_size_bytes(path: Path) -> int:
    """计算目录中所有文件的总大小（字节）."""
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def safe_filename(name: str) -> str:
    """将字符串转换为安全文件名."""
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def ensure_dir(path: Path) -> None:
    """确保目录存在."""
    path.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, data: Any) -> None:
    """将数据保存为 JSON 文件（缩进 2 空格）."""
    ensure_dir(path.parent)
    path.write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_json(path: Path, default: Any = None) -> Any:
    """加载 JSON 文件，失败时返回默认值.

    Any `OSError` (missing file, permission denied) or `JSONDecodeError`
    (corrupt file) returns the supplied default rather than propagating —
    callers use this for "best-effort" config lookups where a missing or
    corrupt file should not crash startup.
    """
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except Exception:  # noqa: BLE001 — see docstring; this is a "tolerate corrupt config" helper, not a parser.
        return default


def safe_json_loads[T](value: str | None, fallback: T) -> T:
    """Parse ``value`` as JSON, returning ``fallback`` on empty or invalid input."""
    if not value:
        return fallback
    try:
        return _json.loads(value)  # type: ignore[no-any-return]
    except (TypeError, _json.JSONDecodeError):
        return fallback


def decode_base64_to_tempfile(image_base64: str, ext: str = "png") -> str:
    """将 base64 编码的图片解码到临时文件，返回文件路径."""
    data = base64.b64decode(image_base64)
    with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as f:
        f.write(data)
        return f.name


def decode_base64_image(image_base64: str) -> Image.Image:
    """将 base64 编码的图片解码为 PIL Image 对象."""
    from io import BytesIO

    from PIL import Image

    data = base64.b64decode(image_base64)
    return Image.open(BytesIO(data))
