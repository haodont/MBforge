"""Text helpers: truncation and chunking."""

from __future__ import annotations


def truncate_text(text: str, max_len: int = 200) -> str:
    """截断文本."""
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def split_text_chunks(
    text: str, chunk_size: int = 512, overlap: int = 128
) -> list[str]:
    """按字符数分块，优先在段落/句子边界分割.

    注意：DocumentProcessor 已不再使用此函数（改用 section-level 分块）。
    保留作为通用文本切分工具供其他模块使用。
    """
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = min(start + chunk_size, text_len)
        if end < text_len:
            # 尝试在换行处分割
            nl = text.rfind("\n", start, end)
            if nl > start + chunk_size // 2:
                end = nl + 1
            else:
                # 尝试在句号处分割
                period = text.rfind("。", start, end)
                if period > start + chunk_size // 2:
                    end = period + 1
                else:
                    space = text.rfind(" ", start, end)
                    if space > start + chunk_size // 2:
                        end = space + 1
        chunks.append(text[start:end].strip())
        start = end - overlap
        if start < 0:
            start = 0
        if start >= end or start >= text_len:
            break
    return [c for c in chunks if c]
