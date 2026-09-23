"""Library file scanner — discover supported documents and walk the file tree.

Historically lived in `core/project.py` as project-lifecycle primitives. After
the project→library migration, scanning is a pure file-system concern with no
tie to library state, so it now lives in its own module. Pipeline enqueue uses
`scan_library_files`; the rest of the codebase that needs file enumeration
imports from here instead of the orphan path.
"""

from __future__ import annotations

from pathlib import Path

from mbforge.foundation.logger import get_logger

logger = get_logger("mbforge.foundation.file_scanner")

MBFORGE_DIR = ".mbforge"

SUPPORTED_EXTS: frozenset[str] = frozenset(
    {".pdf", ".md", ".txt", ".sdf", ".mol", ".mol2", ".pdb", ".smi"}
)

# Directories that are always skipped in a recursive scan — they pull in
# large build artefacts, dependency caches, or sensitive areas.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        "target",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".codex",
        ".claude",
        "archived",
        "ref",
        "tools",
    }
)


class FileNode:
    """Lightweight tree node; intentionally a plain dataclass-ish object so
    routers can dump it via Pydantic or `model_dump` as needed."""

    __slots__ = ("name", "path", "is_dir", "children", "doc_id", "file_type")

    def __init__(
        self,
        name: str,
        path: str,
        is_dir: bool = False,
        children: list[FileNode] | None = None,
        doc_id: str | None = None,
        file_type: str = "",
    ) -> None:
        self.name = name
        self.path = path
        self.is_dir = is_dir
        self.children = children or []
        self.doc_id = doc_id
        self.file_type = file_type

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "is_dir": self.is_dir,
            "children": [c.to_dict() for c in self.children],
            "doc_id": self.doc_id,
            "file_type": self.file_type,
        }


def scan_library_files(
    root: str | Path,
    *,
    recursive: bool = False,
) -> list[str]:
    """Return the relative paths of supported documents under `root`.

    Args:
        root: Library root directory.
        recursive: When True, walk subdirectories (skipping heavy/irrelevant
            ones via `_SKIP_DIRS`). When False, list only the root directory.

    Returns:
        Sorted list of POSIX-style relative paths (forward slashes even on
        Windows). Paths starting with `.mbforge` or `.` are skipped so we
        never surface internal state to the UI.
    """
    p = Path(root)
    if not p.exists():
        return []

    if recursive:
        files: list[str] = []
        for f in p.rglob("*"):
            parts = f.relative_to(p).parts
            # Drop if any directory component is a skip target or starts with `.`
            if any(part in _SKIP_DIRS or part.startswith(".") for part in parts[:-1]):
                continue
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                rel = f.relative_to(p).as_posix()
                if rel.startswith(MBFORGE_DIR) or rel.startswith("."):
                    continue
                files.append(rel)
        return sorted(files)

    # Non-recursive: only direct children
    out: list[str] = []
    for f in p.iterdir():
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
            out.append(f.name)
    return sorted(out)


def build_file_tree(root: str | Path) -> list[FileNode]:
    """Walk `root` recursively, returning a UI-renderable file tree.

    Hidden directories, the `.mbforge/` metadata directory, and entries with
    non-supported extensions are omitted. Permission errors are swallowed per
    directory so one unreadable folder doesn't blank the tree.
    """
    p = Path(root)
    if not p.exists():
        return []

    def _walk(dir_path: Path) -> list[FileNode]:
        try:
            entries = sorted(
                dir_path.iterdir(),
                key=lambda e: (not e.is_dir(), e.name.lower()),
            )
        except PermissionError:
            logger.warning("Permission denied scanning %s", dir_path)
            return []

        nodes: list[FileNode] = []
        for entry in entries:
            if entry.name.startswith(".") or entry.name == MBFORGE_DIR:
                continue
            rel = str(entry.relative_to(p))
            if entry.is_dir():
                children = _walk(entry)
                if children:
                    nodes.append(
                        FileNode(
                            name=entry.name, path=rel, is_dir=True, children=children
                        )
                    )
            elif entry.suffix.lower() in SUPPORTED_EXTS:
                nodes.append(
                    FileNode(
                        name=entry.name,
                        path=rel,
                        is_dir=False,
                        file_type=entry.suffix.lstrip("."),
                    )
                )
        return nodes

    return _walk(p)


__all__ = [
    "MBFORGE_DIR",
    "SUPPORTED_EXTS",
    "FileNode",
    "scan_library_files",
    "build_file_tree",
]
