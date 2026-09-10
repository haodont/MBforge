"""Compare MolDet strategies: ROI-guided vs full-page detection.

This script runs both approaches on the same document and compares:
- Number of molecules detected
- Detection time
- Overlap between the two methods
"""

import json
import time
from pathlib import Path

import fitz
from PIL import Image

from mbforge.backends.moldet_v2_ft import detect_molecules, get_moldet


def run_full_page_detection(
    pdf_path: str, doc_id: str = "test", output_dir: Path | None = None
) -> dict:
    """Strategy A: Detect molecules on full PDF pages (no OCR guidance)."""
    print("\n=== Strategy A: Full-page MolDet ===")
    doc = fitz.open(pdf_path)
    detector = get_moldet()

    all_results = {}
    total_mols = 0
    total_time = 0

    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        zoom = 2.0  # Same as extract_molecules_from_pdf
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)

        img_array = (
            __import__("numpy")
            .frombuffer(pix.samples, dtype=__import__("numpy").uint8)
            .reshape(pix.height, pix.width, pix.n)
        )
        image = Image.fromarray(img_array)

        start = time.perf_counter()
        result = detect_molecules(image, detector=detector)
        elapsed = time.perf_counter() - start

        mols_on_page = len(result.bboxes)
        total_mols += mols_on_page
        total_time += elapsed

        page_bboxes = []
        for mol_idx, bbox_obj in enumerate(result.bboxes):
            # Convert normalized bbox to pixel coords; no side padding, bottom +10%
            x0 = int(bbox_obj.bbox[0] * pix.width)
            y0 = int(bbox_obj.bbox[1] * pix.height)
            x1 = int(bbox_obj.bbox[2] * pix.width)
            y1 = int(bbox_obj.bbox[3] * pix.height)

            # Compound numbers print below the drawing: extend bottom only
            h = y1 - y0
            y1_pad = min(pix.height, y1 + int(h * 0.15))

            crop = image.crop((x0, y0, x1, y1_pad))
            page_bboxes.append(
                {
                    "bbox": list(bbox_obj.bbox),
                    "score": round(bbox_obj.score, 3),
                }
            )

            # Save crop if output_dir is provided
            if output_dir:
                crop_path = (
                    output_dir
                    / f"full_page_{page_idx + 1:04d}_mol_{mol_idx:04d}_conf{bbox_obj.score:.2f}.png"
                )
                crop.save(crop_path)

        all_results[page_idx] = {
            "molecule_count": mols_on_page,
            "elapsed_ms": round(elapsed * 1000),
            "bboxes": page_bboxes,
        }

        if mols_on_page > 0:
            print(
                f"  Page {page_idx + 1}: {mols_on_page} molecules ({elapsed * 1000:.0f}ms)"
            )

    doc.close()

    summary = {
        "strategy": "full_page",
        "total_molecules": total_mols,
        "total_time_ms": round(total_time * 1000),
        "pages_with_molecules": sum(
            1 for r in all_results.values() if r["molecule_count"] > 0
        ),
        "page_results": all_results,
    }

    print(f"\n  Total: {total_mols} molecules in {total_time * 1000:.0f}ms")
    if output_dir:
        print(f"  Crops saved to: {output_dir}/full_page_*.png")
    return summary


def run_roi_guided_detection(
    pdf_path: str, library_root: str, doc_id: str, output_dir: Path | None = None
) -> dict:
    """Strategy B: Use OCR figure bboxes to guide MolDet (current approach)."""
    print("\n=== Strategy B: ROI-guided MolDet (current) ===")

    # Load figure bboxes from persisted page files
    pages_dir = Path(library_root) / "storage" / doc_id / "pages"
    if not pages_dir.exists():
        raise FileNotFoundError(f"Pages directory not found: {pages_dir}")

    # Read all page figure JSON files (support both old and new formats)
    import json as _json

    page_figure_data = {}

    # Try new format first: page_NNNN.json with figure_bboxes field
    new_format_files = sorted(pages_dir.glob("page_*.json"))
    if new_format_files and "figure_bboxes" in _json.loads(
        new_format_files[0].read_text(encoding="utf-8")
    ):
        for json_file in new_format_files:
            data = _json.loads(json_file.read_text(encoding="utf-8"))
            page_num = data.get("page_num")
            figure_bboxes = data.get("figure_bboxes", [])
            if figure_bboxes:
                page_figure_data[page_num - 1] = figure_bboxes  # Convert to 0-based
    else:
        # Fall back to old format: page_NNNN_figures.json
        for figures_file in sorted(pages_dir.glob("page_*_figures.json")):
            data = _json.loads(figures_file.read_text(encoding="utf-8"))
            page_num = data.get("page_num")
            bboxes = data.get("bboxes", [])
            if bboxes:
                page_figure_data[page_num - 1] = bboxes  # Already in PDF coords

    if not page_figure_data:
        print("  No figure bboxes found in page files")
        return {
            "strategy": "roi_guided",
            "total_molecules": 0,
            "total_time_ms": 0,
            "pages_with_ocr_figures": 0,
            "pages_with_molecules": 0,
            "page_results": {},
        }

    detector = get_moldet()
    all_results = {}
    total_mols = 0
    total_time = 0

    # Re-open PDF for rendering
    pdf_doc = fitz.open(pdf_path)

    for page_idx, figure_bboxes in sorted(page_figure_data.items()):
        pymupdf_page = pdf_doc.load_page(page_idx)
        page_w_pts = pymupdf_page.rect.width
        page_h_pts = pymupdf_page.rect.height
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = pymupdf_page.get_pixmap(matrix=mat, alpha=False)

        img_array = (
            __import__("numpy")
            .frombuffer(pix.samples, dtype=__import__("numpy").uint8)
            .reshape(pix.height, pix.width, pix.n)
        )
        image = Image.fromarray(img_array)

        scale_x_px = pix.width / page_w_pts if page_w_pts > 0 else 0
        scale_y_px = pix.height / page_h_pts if page_h_pts > 0 else 0

        page_mols = 0
        page_start = time.perf_counter()

        for fig_idx, (x0, y0_ll, x1, y1_ll) in enumerate(figure_bboxes):
            # Convert PDF coords to pixel coords
            px1 = int(round(x0 * scale_x_px))
            py1_top = int(round((page_h_pts - y1_ll) * scale_y_px))
            px2 = int(round(x1 * scale_x_px))
            py2_bot = int(round((page_h_pts - y0_ll) * scale_y_px))

            if px2 <= px1 or py2_bot <= py1_top:
                continue

            roi_crop = image.crop((px1, py1_top, px2, py2_bot))
            roi_res = detect_molecules(roi_crop, ft_detector=detector)

            # Convert ROI-local bboxes back to full-page normalized coords
            roi_w = max(1, px2 - px1)
            roi_h = max(1, py2_bot - py1_top)

            for mol_idx, cb in enumerate(roi_res.bboxes):
                page_mols += 1

                # Save the molecule crop from within the ROI; bottom +10% only
                if output_dir:
                    mol_x0 = int(cb.bbox[0] * roi_w)
                    mol_y0 = int(cb.bbox[1] * roi_h)
                    mol_x1 = int(cb.bbox[2] * roi_w)
                    mol_y1 = int(cb.bbox[3] * roi_h)

                    # Compound numbers print below the drawing: extend bottom only
                    h = mol_y1 - mol_y0
                    mol_y1_pad = min(roi_h, mol_y1 + int(h * 0.15))

                    mol_crop = roi_crop.crop((mol_x0, mol_y0, mol_x1, mol_y1_pad))
                    crop_path = (
                        output_dir
                        / f"roi_guided_{page_idx + 1:04d}_fig{fig_idx:02d}_mol{mol_idx:02d}_conf{cb.score:.2f}.png"
                    )
                    mol_crop.save(crop_path)

        page_elapsed = time.perf_counter() - page_start
        total_mols += page_mols
        total_time += page_elapsed

        all_results[page_idx] = {
            "molecule_count": page_mols,
            "elapsed_ms": round(page_elapsed * 1000),
            "ocr_figure_count": len(figure_bboxes),
        }

        if page_mols > 0:
            print(
                f"  Page {page_idx + 1}: {page_mols} molecules from {len(figure_bboxes)} ROIs ({page_elapsed * 1000:.0f}ms)"
            )

    pdf_doc.close()

    summary = {
        "strategy": "roi_guided",
        "total_molecules": total_mols,
        "total_time_ms": round(total_time * 1000),
        "pages_with_ocr_figures": len(page_figure_data),
        "pages_with_molecules": sum(
            1 for r in all_results.values() if r["molecule_count"] > 0
        ),
        "page_results": all_results,
    }

    print(f"\n  Total: {total_mols} molecules in {total_time * 1000:.0f}ms")
    if output_dir:
        print(f"  Crops saved to: {output_dir}/roi_guided_*.png")
    return summary


def compare_strategies(full_page: dict, roi_guided: dict) -> dict:
    """Generate comparison report."""
    print("\n=== Comparison Report ===")
    print(f"{'Metric':<30} {'Full-page':>12} {'ROI-guided':>12}")
    print("-" * 60)
    print(
        f"{'Total molecules':<30} {full_page['total_molecules']:>12} {roi_guided['total_molecules']:>12}"
    )
    print(
        f"{'Total time (ms)':<30} {full_page['total_time_ms']:>12} {roi_guided['total_time_ms']:>12}"
    )
    print(
        f"{'Pages with molecules':<30} {full_page['pages_with_molecules']:>12} {roi_guided.get('pages_with_molecules', 'N/A'):>12}"
    )

    ratio = full_page["total_molecules"] / max(1, roi_guided["total_molecules"])
    print(f"\nMolecule ratio (full/roi): {ratio:.2f}x")

    time_ratio = full_page["total_time_ms"] / max(1, roi_guided["total_time_ms"])
    print(f"Time ratio (full/roi): {time_ratio:.2f}x")

    return {
        "full_page": full_page,
        "roi_guided": roi_guided,
        "molecule_ratio": ratio,
        "time_ratio": time_ratio,
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print(
            "Usage: python compare_moldet_strategies.py <pdf_path> <library_root> [doc_id]"
        )
        print("\nExample:")
        print(
            "  python compare_moldet_strategies.py \\\\?\\C:\\Users\\10954\\MBForge\\storage\\72e86100-32c9-4cc7-acda-d29faeccf65f\\source.pdf \\\\?\\C:\\Users\\10954\\MBForge"
        )
        sys.exit(1)

    pdf_path = sys.argv[1]
    library_root = sys.argv[2]
    doc_id = sys.argv[3] if len(sys.argv) > 3 else "test_doc"

    # Create output directory for crops
    output_dir = Path(__file__).parent / "moldet_comparison_crops"
    output_dir.mkdir(exist_ok=True)

    print(f"PDF: {pdf_path}")
    print(f"Library: {library_root}")
    print(f"Doc ID: {doc_id}")
    print(f"Crop output: {output_dir}")

    # Run both strategies
    full_page_result = run_full_page_detection(pdf_path, doc_id, output_dir=output_dir)
    roi_guided_result = run_roi_guided_detection(
        pdf_path, library_root, doc_id, output_dir=output_dir
    )

    # Compare
    comparison = compare_strategies(full_page_result, roi_guided_result)

    # Save results
    output_path = Path(__file__).parent / "moldet_comparison.json"
    output_path.write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nResults saved to: {output_path}")
    print(f"Crop images saved to: {output_dir}")

