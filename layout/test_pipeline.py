import argparse
import json
from pathlib import Path

from pipeline import (
    MOLDET_WEIGHTS, detect_page, load_moldet, load_v3,
    merge_page, page_image, to_evidence_page,
)


def compare_outputs(before, after):
    a = json.loads((before / "detections.json").read_text(encoding="utf-8"))
    b = json.loads((after / "detections.json").read_text(encoding="utf-8"))
    for result in (a, b):
        result["config"].pop("out")
        result.pop("load_s")
        result["totals"].pop("avg_v3_ms")
        result["totals"].pop("avg_mol_ms")
        for page in result["pages"]:
            page.pop("v3_ms")
            page.pop("mol_ms")
    assert a == b, "detections.json differs beyond timing/output directory"
    assert json.loads((before / "evidence.json").read_text(encoding="utf-8")) == json.loads(
        (after / "evidence.json").read_text(encoding="utf-8")), "evidence.json differs"
    images = sorted(before.glob("*.overlay.jpg"))
    assert images, "No baseline overlays"
    assert {p.name for p in images} == {p.name for p in after.glob("*.overlay.jpg")}
    for path in images:
        assert path.read_bytes() == (after / path.name).read_bytes(), f"Overlay differs: {path.name}"
    print("PASS: JSON unchanged except timing/output directory; overlays byte-identical")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--compare", nargs=2, type=Path, metavar=("BEFORE", "AFTER"))
    args = ap.parse_args()
    if args.compare:
        compare_outputs(*args.compare)
        return
    path = next(iter(sorted((Path(__file__).resolve().parent.parent / "Sample").glob("*.png"))), None)
    assert path is not None, "No real input page found in Sample"
    image = page_image(path)
    v3 = load_v3()
    moldet = load_moldet(MOLDET_WEIGHTS["960_doc"])
    regions, mols, page, timing = detect_page(image, v3, moldet, doc_id=path.stem)
    assert regions, f"No layout regions detected: {path}"
    assert mols, f"No molecules detected: {path}"
    merged, stats = merge_page(regions, mols, page, doc_id=path.stem)
    evidence = to_evidence_page(regions, mols, page, doc_id=path.stem)
    assert merged, "No merged regions"
    assert any(e["kind"] == "molecule" for e in evidence), "No molecule evidence"
    assert page["width_px"] == image.width and page["height_px"] == image.height
    assert timing["v3_ms"] > 0 and timing["mol_ms"] > 0
    print(f"PASS: {path.name}: regions={len(regions)}, mols={len(mols)}, "
          f"merged={len(merged)}, evidence={len(evidence)}, stats={stats}")


if __name__ == "__main__":
    main()
