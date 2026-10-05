"""Native PDF text near a detected molecule box.

That text is *context*, not evidence: it feeds the Markush role context so a
molecule can be classified against the paragraph that introduces it. Blocks are
ranked by centre distance to the box and truncated to keep one molecule's
context small.
"""

from __future__ import annotations

#: Upper bound on the returned context, in characters.
MAX_CONTEXT_CHARS = 1000
#: How many of the nearest blocks are joined.
MAX_CONTEXT_BLOCKS = 4


def nearby_block_text(
    blocks: object,
    bbox: tuple[float, float, float, float],
) -> str:
    """Return native PDF text near *bbox* (PDF points, top-left origin).

    Never raises: a missing or malformed ``blocks`` payload yields an empty
    string, so a page whose native text could not be read still extracts.
    """
    if not isinstance(blocks, (list, tuple)):
        return ""

    x0, y0, x1, y1 = bbox
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    pad_x = max(18.0, width * 0.75)
    pad_y = max(24.0, height * 1.5)
    query = (x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y)

    nearby: list[tuple[float, str]] = []
    for block in blocks:
        if not isinstance(block, (list, tuple)) or len(block) < 5:
            continue
        try:
            bx0, by0, bx1, by1 = (float(value) for value in block[:4])
        except (TypeError, ValueError):
            continue
        text = block[4].strip() if isinstance(block[4], str) else ""
        if not text:
            continue
        if bx1 < query[0] or bx0 > query[2] or by1 < query[1] or by0 > query[3]:
            continue
        distance = abs((bx0 + bx1) / 2 - (x0 + x1) / 2) + abs(
            (by0 + by1) / 2 - (y0 + y1) / 2
        )
        nearby.append((distance, text))

    nearby.sort(key=lambda item: item[0])
    return " ".join(text for _, text in nearby[:MAX_CONTEXT_BLOCKS])[:MAX_CONTEXT_CHARS]
