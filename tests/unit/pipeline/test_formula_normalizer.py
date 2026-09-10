from mbforge.pipeline.detection.formula_normalization import normalize_patent_formulas


def test_normalize_patent_formulas_repairs_ocr_notation() -> None:
    text = r"\mathrm{C*{3 - 6}}、\mathrm{S(O)*2R^{g}}$、或 $\\mathrm{NR^{d}S(O)2R^{g}}$"

    result = normalize_patent_formulas(text)

    assert r"$\mathrm{C}_{3 - 6}$" in result
    assert r"$\mathrm{S(O)2R^{g}}$" in result
    assert r"$\mathrm{NR^{d}S(O)2R^{g}}$" in result
