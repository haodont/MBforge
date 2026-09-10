# Real scanned-PDF benchmark

The benchmark uses the configured cloud OCR providers. Local OCR was removed
from the project; extraction is intentionally cloud-only for production-like
validation of scanned documents.

## Run

Use the project Python environment and write evidence outside the repository:

```powershell
$out = 'C:\tmp\mbforge-real-pdf-run'
.\.venv\Scripts\python.exe scripts\benchmark_real_pdf.py `
  --pdf 'C:\path\to\scan.pdf' `
  --output $out `
  --gold-template "$out\gold.json"
```

The report records page-level text, provider, retries, elapsed time, failed
pages, peak RSS, and a SHA-256 of the input. The PDF and the OCR report must
stay outside git. Review `gold.json` against the original scan and fill only
the required anchors and minimum character counts; do not derive it from the
OCR output.

## Supervised comparison

After human review, compare the report with:

```powershell
.\.venv\Scripts\python.exe scripts\compare_real_pdf_gold.py `
  --report "$out\extraction-cloud.json" `
  --gold "$out\gold.json"
```

The command fails if the input identity/page count, title anchors, page
anchors, or minimum OCR success count do not match. This keeps OCR accuracy
separate from later persistence checks.

## Interpreting a run

- `ocr_stats.pages_succeeded / pages_requested` is the extraction success rate.
- `backend_counts` shows which cloud chain provider handled each job; local
  OCR is not present.
- `retry_count` and `elapsed_ms` expose transient failures and cost. A 429 is
  a provider quota/rate-limit event, not evidence that local OCR should be
  silently initialized.
- A full pipeline run must also inspect stage context and persisted
  molecule-role counts. A successful process exit alone is insufficient.
