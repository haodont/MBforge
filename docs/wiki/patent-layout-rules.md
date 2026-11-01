# Patent layout rules (13-document corpus)

This page records the layout features that change extraction. It is measured, not
assumed: every rule below cites a document, a page and a real string or bbox from
`source_evidence`. The companion pages are
[patent taxonomy](patent-taxonomy.md) and
[patent extraction forms](patent-extraction-forms.md).

**Default input is a scanned PDF.** Eleven of the thirteen documents have no text
layer; `JP2023544789A` is native and `US20210128561A1` is hybrid. The page render,
not the OCR text, is the source of truth.

## 1. Page frame and reading order

### 1.1 Two-column pages

`US20250206734A1` page 32 is a two-column page:

| Position | Content |
|---|---|
| Left column, top | `Example 2. 3-(2,4-Difluorophenoxy)-…` and its drawing |
| Left column, middle | `Example 3. 3-(2,4-Difluorophenoxy)-7-(1-(2-phe-nylpyrrolidin-1-yl)ethyl)…` and its drawing |
| Right column, top | `Example 4. 5-(1-(1-(3-(2,4-Difluorophenoxy)-1,6-naphthyridin-7-yl)ethyl)…` and its drawing |
| Right column, bottom | `Step 1. 1-(3-(2,4-Difluorophenoxy)-1,6-naphthyridin-7-yl)ethan-1-ol` and its drawing |

A y-sort would put `Example 4` before `Example 3`; the correct order is
column-major: left column top-to-bottom, then right column top-to-bottom. The
producer must detect columns before assigning reading order.

### 1.2 One-column pages with margin furniture

- Chinese pages carry a full-width header/footer and a bracketed paragraph marker
  at the left margin: `[0680]`, `[0681]`, `[0688]`, `[0689]`
  (`CN120943813A` pages 94–95). The marker is not part of the paragraph text.
- Japanese pages carry `【実施例】`, `【0365】`, `【表16】`, `【化57】` and a
  vertical line-number strip at the right margin (`JP2023544789A` page 152:
  bbox x 551–569, text `10 20 30 …`). The strip is page furniture, not content.
- Printed page numbers do not equal the PDF page index:
  - `CN121270515A` PDF page 13 prints `11/19页`;
  - `US20250206734A1` PDF page 32 prints `31`;
  - `IL292693A` PDF page 45 prints `38`.
  The evidence store keys pages by the PDF index; a printed page number needs an
  offset map and must never be used as the primary page key.

### 1.3 Rotated or oversized tables

`US20260027089A1` pages 18+ have table bboxes whose `bbox_x1` reaches 2207 while
a portrait page is about 595 points wide. That is a landscape/rotated table, not
a malformed bbox. Rotation must be detected before table parsing; otherwise the
parser reads a 90° table as rows of structure noise.

### 1.4 Headers and footers

Every page has a header or footer block, but its position differs:

| Document | Header/footer | Evidence |
|---|---|---|
| `CN121270515A` | `CN 121270515 A` left, `说明书` centre, `11/19页` right | page 13 |
| `US20250206734A1` | `US 2025/0206734 A1` left, `Jun. 26, 2025` right, page `31` centre | page 32 |
| `IL292693A` | `WO 2021/092264` left, `PCT/US2020/059228` right, page `38` centre | page 45 |
| `JP2023544789A` | Japanese `明細書` and page furniture; line-number strip at the right | page 152 |

The producer already labels `head` and `foot`; section and table parsers must
ignore them rather than treating the repeated header as a sentence.

## 2. Heading grammar

### 2.1 Chinese

Observed forms:

| Form | Real string | Source |
|---|---|---|
| Numbered example | `[0143] 实施例7` | `CN121270515A` |
| Number runs into the name | `[0095] 实施例1N-((1R,3S)-3-…的合成` — the label is `1`, `N-` starts the name | `CN121270515A` p13 |
| Spaced number | `实施例 29`, `实施例 30`, `实施例 31` | `CN120943813A` p94 |
| Heading with formula | `实施例4：N-…(实施例4)的合成` | `CN121270515A` p18 |
| Product label | `实施例1` printed below the final drawing | `CN121270515A` p13 |
| Test example | `测试例2:肥大细胞β-氨基己糖苷酶释放测定` | `CN120943813A` p94 |

A heading may be a section start or a product label. Both are `@example:N`, but
only the one adjacent to the drawing is a clean label anchor.

### 2.2 Japanese

| Form | Real string | Source |
|---|---|---|
| Section marker | `【実施例】` | `JP2023544789A` p152 |
| Numbered example | `実施例1` | p152 |
| Spaced number | `実施例 1 0 3`, `実施例1 04` | p184, p187 |
| Full-width digit | `実施例２および3` | p155 |
| Intermediate/step | `工程1`, `工程2`, `中間体` | p153 |

The native text layer inserts spaces inside numbers and uses full-width digits.
Normalize the token, not the `label_raw`: the anchor keeps `実施例 1 0 3` verbatim.

### 2.3 English

| Form | Real string | Source |
|---|---|---|
| Numbered compound example | `Example 2. 3-(2,4-Difluorophenoxy)-…` | `US20250206734A1` p32 |
| Lettered assay | `Example A. MRGPRX2 FLIPR Calcium Mobilization Assay` | p42 |
| Lettered assay with colon | `Example C: MRGPRX2 β-Arrestin Assay` | p42 |
| Range | `Examples 2-4 were synthesized in an analogous manner` | `WO2022152853A1` p24 |
| Line-break hyphenation | `dif-luoropiperidine`, `naphthyri-din-7-yl` | `US20250206734A1` p32 |
| Lettered compound | `Example E50:(first eluting)` | `IL292693A` |

De-hyphenate line breaks before matching a name. A lettered example is not
automatically a compound: `Example A–F` in `US20250206734A1` are assays
(FLIPR, IP1 HTRF, β-Arrestin, Caco2, whole blood, intrinsic clearance), while
`Example 1–8` are compounds.

### 2.4 Machine-translated documents

`KR20250121245A` and `WO2025163462A1` have **no** `Example`/`实施例` headings;
their tables start with OCR-damaged headers such as `号 | 子至 | IUPAC` and
`世京 | 7丕 | IUPAC`. The heading vocabulary was lost in translation. The correct
behavior is to abstain, not to invent a section from a table header.

### 2.5 Key spaces

| Printed form | Key space | Rule |
|---|---|---|
| `实施例7`, `Example 7` | `@example:7` | A section identity |
| `化合物7`, `Compound 7` | `7` | A compound designation |
| Table header `实施例编号`, cell `29` | `@example:29` | Header declares the key space |
| Table header `化合物编号`, cell `实施例 29` | `@example:29` | The printed prefix overrides the header (`CN120943813A` p94) |
| `E02`, `E020` | example / internal code | `E02` is an example token; `E020` is an internal code; declare per document |
| `化合物4-P2 or 4-P4` | ambiguous | Two compounds in one label; do not choose one silently |

## 3. Label ↔ structure adjacency

There is no fixed direction. Four observed layouts:

| Layout | Real case | Rule |
|---|---|---|
| Label below drawing | `CN121270515A` p3 claim 4: labels `1`–`6` centered below six drawings; label centre x inside the drawing x-span | Vertical gap is small (~18 pt); use centre-x containment |
| Heading above drawing | `US20250206734A1` p32: `Example 2` above its drawing; `Example 4` above its drawing in the right column | Use the heading's column and the next drawing below it |
| Label and structure in table cells | `IL292693A` p45: `E02` in the first cell, drawing in the `Structure` cell, analytical data in the third | The molecule bbox lies inside the table; bind by row and column |
| Label in table, structure below table | `CN120943813A` p95: `阳参化合物` row; `[0687] 阳参化合物结构如下：` followed by the drawing | Search the caption paragraph below the table; do not require the structure in the row |
| Cross-page | `JP2023544789A` p152 `実施例1`; product in the scheme on p153 | The anchor and the structure may have different `page` values; keep both evidence ids |

Consequences:

- A pair's geometry check must accept a cross-page pair when both boxes are
  inside their own pages.
- A label is not always a `label_anchor` with a structure on the same page.
- The same example can print its number twice (section heading and product
  label). Both are anchors; the product label is the one adjacent to the drawing.

## 4. Table shapes

### 4.1 Simple activity table

`CN120943813A` p95:

```
| 化合物编号 | MRGPRX2 拮抗剂活性 IC50(nM) |
| 化合物 7-P1 | <0.001 |
| 化合物 15   | 0.19   |
| 化合物 5    | 0.03   |
| 化合物 26   | 0.041  |
| 阳参化合物  | 0.2    |
```

The structure for the `阳参化合物` row is in the paragraph below the table, not in
a cell. This is the simplest table shape and the one the current parser handles
best.

### 4.2 Repeated (label, value) pairs

`CN120943813A` p94 is four columns:

```
| 化合物编号 | MRGPRX2 IP-1 IC50(nM) | 化合物编号 | MRGPRX2 IP-1 IC50(nM) |
| 化合物1-P4 | 21                   | 实施例 29  | 29                   |
| 化合物2    | 51                   | 实施例 30  | 36                   |
| 化合物4-P2 or 4-P4 | 15           | 实施例 31  | 65                   |
```

The two label streams are independent. The OCR markdown lost most values
(`| 化合物2 | | 实施例 30 | 36 |`); the page image shows them. The parser must
reconstruct the four-column grid from the page, not trust the OCR table text.
The right stream uses `实施例 29` under a `化合物编号` header; the prefix wins.

### 4.3 Split header over two rows

`CN121270515A` p21:

```
| 化合物编号 | IC50(nM) | | | |
| MRGPRX1 | MRGPRX2 | MRGPRX3 | MRGPRX4 |
| 4（化合WO2022067094物1） | ++ | +++ | ++ | ++ |
| 实施例1 | 十 | ++++ | 十 | 十 |
```

The metric row and the target row must be joined before the data rows are read.
`十` is OCR for `+`; record it as an OCR issue, do not silently normalize.

### 4.4 Merged or dropped label cells

`CN121270515A` p20:

```
| 实施例编号 | MRGPRX2 抑制 | 实施例编号 | MRGPRX2 抑制 |
| 1 | ++++ | 2 | ++++ |
| 3 | ++++ | 4 | ++++ |
| 5 | ++++ |   | ++++ |
```

The OCR text has a blank second label; the page image shows `5` and `6`. The
`6` was dropped. A blank label cell inherits a designation only within the same
column and only when the layout shows a span; a dropped label is an OCR issue,
not an empty cell.

### 4.5 Structure-column tables

`IL292693A` p45–47:

```
| Example number | Structure | Analytical data | LCMS Method |
| E02 | [drawing] | 1H NMR… LCMS m/z: 280.1 | A |
| E03 | [drawing] | 1H NMR… LCMS m/z: 298.0 | A |
| E08 | [drawing] | Chloroform-d… | A |
```

The `Structure` cell is a raster image; the OCR text in that cell is fragment
noise (`H3C H3C`). The molecule evidence bbox lies inside the table. The parser
must classify the cell as a structure cell, not parse its text as a compound.

### 4.6 Table split across pages

`US20250206734A1` Table A starts in the right column of page 42 (rows 1–8) and
continues on page 43 (rows 9–25) with the header repeated:

```
| Example | MRGPRX2 FLIPR | MRGPRX2 IP1 HTRF | MRGPRX2 β-Arrestin |
```

The table continuation must be bound by the repeated header/caption, not by
page-local row numbering. `ND` means no data; `±` in the OCR text is a misread of
`+` in several rows (the legend defines `+`, `++`, `+++`, `++++`, `ND`).

### 4.7 Legends and values

- `CN121270515A` p20 legend: `注：“++++”1nM<IC50<20nM`, `“+++”20nM<IC50<100nM`.
- `US20250206734A1` p42 legend: `++++ ≤0.1 nM`, `+++ >0.1–100 nM`,
  `++ >100–1000 nM`, `+ >1000 nM`, `ND` no data.
- `ND` is missing data, never zero.
- `±` is ambiguous OCR; flag it, never coerce to `+`.
- `化合物4-P2 or 4-P4` is a disjunction; do not pick one.

## 5. Structure representation

- Scanned PDFs carry raster drawings. MolDet boxes and MolParser SMILES are the
  only structure source; the OCR text around a drawing is not a structure.
- Markush claims (`CN121270515A` p2) carry a scaffold drawing with E-SMILES
  `<sep><a>0:Ar</a>…`; the variable definitions are in the claim text. Store the
  scaffold and the variable table; do not enumerate.
- Deuterated compounds are common (`CN121270515A`: `D3C`, `OCD3`, `[2H]`).
  InChIKey does not encode isotopes; use `exact_isotopes` and compare isomeric
  SMILES.
- A structure cell in a table is a raster image. Its OCR text (`H3C H3C`,
  `N. HN S`, `Cl NH HN O=φ=0`) is fragment noise, not a SMILES or a label.
- Reaction schemes (`JP2023544789A` p153, `【化57】`) contain multiple nodes; the
  example heading belongs to the final product, not to an intermediate.

## 6. Per-document feature matrix

| Document | Pages | Render | Lang | Layout | Heading forms | Table forms | Structure forms |
|---|---:|---|---|---|---|---|---|
| `CN120329282A` | 113 | scanned | zh | one-column | `实施例1:…`, `化合物77`, `实施例 N` | huge `结构｜命名｜LC-MS` tables p92+ | raster, table structure column |
| `CN120943813A` | 95 | scanned | zh | one-column | `实施例23-…`, `测试例2:…` | simple p95, repeated pairs p94 | raster, table structure column |
| `CN121270515A` | 23 | scanned | zh | one-column | `实施例1N-…`, `实施例1`, `实施例 29` | split header, merged cells, legend | raster, Markush claims, deuterated |
| `IL292693A` | 75 | scanned | en | one-column | `Example E01`, `Example E02` | structure-column synthesis tables | raster table cells |
| `JP2023544789A` | 400 | native | ja | one-column + line numbers | `【実施例】`, `実施例1`, `実施例 1 0 3` | intermediate/structure tables | raster, reaction schemes |
| `KR20250121245A` | 36 | scanned | en (machine) | one-column | none; table headers only | `号｜子至｜IUPAC` (OCR damage) | raster table cells |
| `US20210128561A1` | 67 | hybrid | en | two-column | `[0199]`, `Overview of…` | assay table p51 | raster |
| `US20250206734A1` | 56 | scanned | en | two-column | `Example 2.`, `Example A.`, `Examples 2-4` | Table A split p42–43 | raster, heading above drawing |
| `US20260027089A1` | 100 | scanned | en | landscape/rotated | `Compound E001` | huge structure tables p18+ (`bbox_x1≈2207`) | raster table cells |
| `WO2022152853A1` | 66 | scanned | en | one-column | `Example 1`, `Examples 2-4` | `Example number｜Compound name` p14–16 | raster |
| `WO2025002360A1` | 66 | scanned | zh | one-column | `实施例`, Chinese text | structure tables p21+ | raster table cells |
| `WO2025163462A1` | 70 | scanned | en (machine) | one-column | none | `世京｜7丕｜IUPAC` (OCR damage) | raster table cells |
| `WO2025223036A1` | 69 | scanned | zh | one-column | `实施例35：化合物35的制备` | structure tables p13 | raster table cells |

Two language facts matter:

1. `WO2025002360A1` and `WO2025223036A1` are **Chinese-language** WO
   publications. The `WO` prefix does not imply English.
2. `KR20250121245A` and `WO2025163462A1` are machine-translated; their heading
   vocabulary is gone. A translation-aware heading dictionary or abstention is
   required.

## 7. Design implications

### Producer

1. **Classify each page** as native, scanned, hybrid or rotated before choosing
   OCR or text-layer input.
2. **Detect columns** and assign reading order column-major. A y-sort is wrong on
   `US20250206734A1` p32. Persist the order in `source_evidence.reading_order`;
   the SQL loader reads it back, so the Patent stage does not re-sort by y.
3. **Classify headers/footers and line-number strips** as furniture, not content.
   Never use the printed page number as the page key without an offset map.
4. **Detect rotation** before table parsing. A table bbox wider than the page is
   a rotation signal, not a bad box.
5. **Reconstruct the table grid** from the page when cells are merged or the OCR
   markdown has blanks (`CN120943813A` p94). A blank label is not an empty cell.
6. **Classify structure cells**: a cell with a drawing has a molecule bbox; its
   OCR text is noise. Do not feed it to the label parser.
7. **Normalize the heading token**, not `label_raw`: full-width digits, spaces
   inside `実施例 1 0 3`, line-break hyphenation in `dif-luoropiperidin`.
8. **Declare the key space**: section heading, table header, or label prefix.
   The prefix wins over the header (`实施例 29` under `化合物编号`).
9. **Keep the OCR issue** on the anchor when a label or value is damaged; never
   silently correct it.

### `label_anchor`

- Emit one anchor per printed slot, including table-cell anchors and product
  labels. The current table evidence row is the whole table; per-row/cell anchors
  are required for fair table precision.
- Allow the anchor and the structure to be on different pages (JP example 1).
- Store the anchor kind (`section_heading`, `table_cell`, `prose`, `claim_text`)
  and the source (`ocr_text`, `ocr_label`, `table_cell`).
- Use centre-x containment and a vertical-gap threshold for label-below/above;
  use row/column containment for table cells.

### Verification

- `table_complete` is fail-closed: every non-empty value cell must be attributed,
  or the table is refused.
- `ND` is missing, not zero; `±` is ambiguous, not `+`. The table parser excludes
  `ND`/`NA`/`NT` from the completeness count and publishes no measurement for
  that cell; it is not an inactivity rank.
- A `Structure` cell is a drawing, not text; its OCR string is not a label.
- A cross-page pair is valid when both boxes are inside their own pages.
- `exact_isotopes` is required for deuterated patents.

### What not to do

- Do not sort a page by y alone.
- Do not merge `实施例N` and `化合物N`.
- Do not parse a structure-cell OCR string as a compound.
- Do not treat `ND` as 0 or `±` as `+`.
- Do not assume the table bbox is the page width.
- Do not assume a label is always above or always below the drawing.
- Do not trust a printed page number as the PDF page index.

## 8. Open layout questions

1. **Rotated tables** (`US20260027089A1`): page rotation metadata is not stored;
   the producer must record it before the table parser can be evaluated.
2. **Huge structure tables** (`CN120329282A` p92+): the structure cell, the
   compound name and the LC-MS value are in one row, but the OCR table text is
   noise. A row-level structure-cell binding is not implemented.
3. **Japanese intermediate tables** (`JP2023544789A` p95+): `中間体 | 名称 |
   構造 | HNMR | LC/MS`; the label may be blank and the structure is a drawing.
4. **Machine-translated headings**: `KR20250121245A` and `WO2025163462A1` have no
   heading vocabulary; a translation-aware dictionary or an explicit abstention
   is required.
5. **Disjunction labels**: `化合物4-P2 or 4-P4` is two compounds in one cell; the
   current parser reports it as unresolved. The gold set must record the
   ambiguity, not pick one.
6. **Cross-page table continuations**: `US20250206734A1` Table A p42–43; the
   header repeat is the only continuation signal.

## 9. How to extend

Add a row only with a real page, a real string and a rejected neighbour. A layout
category that does not change the producer, the anchor or the table parser does
not belong on this page. The companion
[extraction forms](patent-extraction-forms.md) records the parser-level forms;
this page records the page-level geometry that decides where those forms live.
