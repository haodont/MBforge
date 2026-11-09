#!/usr/bin/env python
"""Build a browsable HTML report for the activity-table classification.

Inputs (all produced by the classification/grouping scripts):
  * logical_tables.jsonl  — logical tables with class / fragments / structure count
  * all_classes.jsonl     — fragment-level classifier output (SLANet Markdown for candidates)
  * table-crops dataset    — the crop PNGs

The report embeds downscaled JPEG thumbnails (written next to the HTML) so it
opens without a server; the "open original" link points at the crop file.
"""

from __future__ import annotations

import argparse
import html
import json
from collections import Counter
from pathlib import Path

from PIL import Image


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def fragment_rows(classes: list[dict]) -> dict[tuple[str, int, int], dict]:
    return {
        (row["source"], int(row["page"]), int(row["table"])): row for row in classes
    }


def crop_path(crops_dir: Path, source: str, page: int, table: int) -> Path:
    """Crops live under the PDF stem directory (``file.pdf`` → ``file/``)."""
    return crops_dir / Path(source).stem / f"p{int(page):04d}_t{int(table):02d}.png"


def make_thumbnail(image_path: Path, target: Path, width: int = 720) -> bool:
    if not image_path.is_file():
        return False
    with Image.open(image_path) as handle:
        image = handle.convert("RGB")
        scale = width / max(1, image.width)
        image = image.resize((width, max(1, int(image.height * scale))), Image.LANCZOS)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target, format="JPEG", quality=82)
    return True


def safe_id(logical_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in logical_id)[:80]


def bar(value: int, total: int, color: str) -> str:
    pct = 100.0 * value / total if total else 0.0
    return (
        f'<div class="bar"><span style="width:{pct:.1f}%;background:{color}"></span>'
        f"<b>{value}</b><em>{pct:.1f}%</em></div>"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--logical", required=True)
    parser.add_argument("--classes", required=True, help="candidate fragment reads")
    parser.add_argument("--crops-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--title", default="活性表识别报告")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    thumbs = out_dir / "thumbs"
    out_dir.mkdir(parents=True, exist_ok=True)
    crops_dir = Path(args.crops_dir).resolve()

    logical = load_jsonl(Path(args.logical))
    classes = fragment_rows(load_jsonl(Path(args.classes)))
    counts = Counter(row["class"] for row in logical)
    total = len(logical)
    ordered = sorted(
        logical,
        key=lambda row: (
            {"activity": 0, "pk": 1, "activity?": 2}.get(row["class"], 9),
            row["source"],
            row["fragments"][0]["page"],
            row["fragments"][0]["table"],
        ),
    )

    colors = {
        "activity": "#1f9d55",
        "pk": "#2b6cb0",
        "activity?": "#c05621",
        "analytical": "#718096",
        "other": "#a0aec0",
        "glossary": "#805ad5",
        "synthesis": "#dd6b20",
    }
    bars = "".join(
        f'<div class="row"><span class="label">{html.escape(name)}</span>'
        f"{bar(value, total, colors.get(name, '#718096'))}</div>"
        for name, value in counts.most_common()
    )

    cards: list[str] = []
    for row in ordered:
        if row["class"] not in {"activity", "pk", "activity?"}:
            continue
        first = row["fragments"][0]
        source = row["source"]
        page = int(first["page"])
        table = int(first["table"])
        meta = classes.get((source, page, table)) or {}
        crop = Path(meta.get("file") or "") if meta.get("file") else Path()
        if not crop.is_file():
            crop = crop_path(crops_dir, source, page, table)
        thumb_name = f"{safe_id(row['logical_id'])}.jpg"
        has_thumb = make_thumbnail(crop, thumbs / thumb_name)
        signals = meta.get("signals") or {}
        metrics = ", ".join(signals.get("activity_metrics") or []) or "—"
        pk = ", ".join(signals.get("pk_metrics") or []) or "—"
        markdown = str(meta.get("markdown") or "").strip()
        read_class = str(meta.get("class") or "")
        fragment_pages = " · ".join(
            f"p{f['page']}t{f['table']}" for f in row["fragments"]
        )
        classes_in_group = ", ".join(
            sorted({f.get("class", "") for f in row["fragments"] if f.get("class")})
        )
        card = [
            f'<article class="card" data-class="{html.escape(row["class"])}">',
            f'<div class="card-head"><b>{html.escape(source)}</b>'
            f'<span class="tag t-{row["class"].replace("?", "q")}">{html.escape(row["class"])}</span></div>',
            f'<div class="sub">p{page} · {html.escape(row["class_source"])} · '
            f"结构 {row['structure_count']} · fragments {len(row['fragments'])}"
            f"（{html.escape(fragment_pages)}）</div>",
            f'<div class="sub">metrics: {html.escape(metrics)} | pk: {html.escape(pk)}'
            f" | SLANet 复核: {html.escape(read_class or '—')}"
            f" | fragment classes: {html.escape(classes_in_group or '—')}</div>",
        ]
        if has_thumb:
            card.append(
                f'<a href="file:///{crop.as_posix()}" target="_blank">'
                f'<img loading="lazy" src="thumbs/{thumb_name}"></a>'
            )
        else:
            card.append('<div class="missing">crop missing</div>')
        if markdown:
            card.append(
                f"<details><summary>SLANet Markdown</summary><pre>{html.escape(markdown[:4000])}</pre></details>"
            )
        card.append("</article>")
        cards.append("\n".join(card))

    multi = [row for row in logical if len(row["fragments"]) > 1]
    multi_rows = "\n".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(row["source"]),
            html.escape(
                " · ".join(f"p{f['page']}t{f['table']}" for f in row["fragments"])
            ),
            html.escape(row["class"]),
            html.escape(row["class_source"]),
        )
        for row in sorted(
            multi, key=lambda r: (r["source"], r["fragments"][0]["page"])
        )[:200]
    )

    page_html = f"""<!doctype html>
<meta charset="utf-8">
<title>{html.escape(args.title)}</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; background: #f7f8fa; color: #1a202c; }}
  header {{ padding: 24px 28px 8px; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  .muted {{ color: #718096; }}
  .stats {{ display: flex; gap: 14px; flex-wrap: wrap; padding: 12px 28px; }}
  .stat {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 12px 16px; min-width: 130px; }}
  .stat b {{ display: block; font-size: 22px; }}
  .panel {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; margin: 14px 28px; padding: 16px 18px; }}
  .row {{ display: flex; align-items: center; gap: 10px; margin: 4px 0; }}
  .row .label {{ width: 110px; color: #4a5568; }}
  .bar {{ flex: 1; display: flex; align-items: center; gap: 8px; }}
  .bar span {{ display: block; height: 12px; border-radius: 6px; min-width: 2px; }}
  .bar b {{ font-size: 12px; }}
  .bar em {{ font-style: normal; color: #a0aec0; font-size: 12px; }}
  .filters {{ padding: 0 28px 4px; }}
  .filters button {{ border: 1px solid #cbd5e0; background: #fff; border-radius: 999px; padding: 6px 14px; margin-right: 8px; cursor: pointer; }}
  .filters button.active {{ background: #1a202c; color: #fff; border-color: #1a202c; }}
  .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); padding: 10px 28px 40px; }}
  .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }}
  .card img {{ width: 100%; height: auto; border: 1px solid #edf2f7; border-radius: 6px; }}
  .card-head {{ display: flex; justify-content: space-between; gap: 8px; }}
  .sub {{ color: #4a5568; font-size: 12px; }}
  .tag {{ font-size: 11px; padding: 2px 8px; border-radius: 999px; color: #fff; }}
  .t-activity {{ background: #1f9d55; }}
  .t-pk {{ background: #2b6cb0; }}
  .t-activityq {{ background: #c05621; }}
  pre {{ white-space: pre-wrap; word-break: break-word; background: #f7fafc; border: 1px solid #edf2f7; padding: 8px; border-radius: 6px; font-size: 11px; max-height: 280px; overflow: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12px; }}
  th, td {{ border-bottom: 1px solid #edf2f7; padding: 6px 8px; text-align: left; }}
  details summary {{ cursor: pointer; color: #2b6cb0; font-size: 12px; }}
  .hidden {{ display: none; }}
</style>
<header>
  <h1>{html.escape(args.title)}</h1>
  <div class="muted">2844 张表格 crop → 2566 个逻辑表；下表是 activity / pk / activity? 候选（其余类别已排除）。</div>
</header>
<div class="stats">
  <div class="stat"><b>{total}</b>逻辑表</div>
  <div class="stat"><b>{counts.get("activity", 0)}</b>activity</div>
  <div class="stat"><b>{counts.get("pk", 0)}</b>pk</div>
  <div class="stat"><b>{counts.get("activity?", 0)}</b>activity?</div>
  <div class="stat"><b>{len(multi)}</b>多片段逻辑表</div>
  <div class="stat"><b>{sum(1 for r in logical if r["class"] in {"activity", "pk", "activity?"} and r["structure_count"] > 0)}</b>带结构的候选</div>
</div>
<div class="panel"><h3>类别分布</h3>{bars}</div>
<div class="filters">
  <button class="active" onclick="filter('all', this)">全部 ({len(cards)})</button>
  <button onclick="filter('activity', this)">activity ({counts.get("activity", 0)})</button>
  <button onclick="filter('pk', this)">pk ({counts.get("pk", 0)})</button>
  <button onclick="filter('activity?', this)">activity? ({counts.get("activity?", 0)})</button>
</div>
<main class="grid">
{"".join(cards)}
</main>
<div class="panel"><h3>多片段逻辑表（前 200）</h3>
<table><thead><tr><th>source</th><th>fragments</th><th>class</th><th>class_source</th></tr></thead>
<tbody>{multi_rows}</tbody></table></div>
<script>
function filter(kind, button) {{
  document.querySelectorAll('.filters button').forEach(b => b.classList.remove('active'));
  button.classList.add('active');
  document.querySelectorAll('.card').forEach(card => {{
    card.classList.toggle('hidden', kind !== 'all' && card.dataset.class !== kind);
  }});
}}
</script>
"""
    (out_dir / "activity_report.html").write_text(page_html, encoding="utf-8")
    print(f"wrote {out_dir / 'activity_report.html'} ({len(cards)} candidate cards)")


if __name__ == "__main__":
    main()
