# Golden evaluation suite — US20260027089A1

This directory hosts the metric definitions and entrypoint that score a
pipeline candidate dump against the supervised
`US20260027089A1` golden reference at
`test_data/golden/US20260027089A1/reference.json`.

## Layout

| File | Purpose |
|---|---|
| `conftest.py` | Session-scoped fixture loading the golden reference JSON. |
| `test_eval_activity.py` | Activity extraction recall, page/value/target/operator accuracy. |
| `test_eval_molecule.py` | Structure presence, role classification, SMILES prediction match. |
| `test_eval_markush.py` | Markush leakage and role classification against the anchors. |
| `test_eval_stability.py` | Operational metric catalog (cost, latency, retries, errors). |
| `run_eval.py` | CLI entrypoint; emits a JSON report. |

## Running

```bash
# pytest entrypoints — sanity checks against empty/perfect candidates.
uv run pytest tests/eval/golden_us20260027089/ -q

# CLI scoring of a real pipeline dump.
python -m tests.eval.run_eval --golden US20260027089A1 \
    --candidate path/to/candidate.json \
    --output path/to/report.json
```

## Candidate schema

The candidate JSON may carry any subset of the following keys:

```jsonc
{
  "results": [           // activity rows
    {
      "compound_label": "E001",
      "pdf_page": 60,
      "value_original": 6.4,
      "value_canonical_nm": 398.107171,
      "target": "Human MrgprX2 Antagonist",
      "metric": "pIC50"
    }
  ],
  "molecules": [         // structure detection
    {
      "compound_label": "E001",
      "pdf_page": 60,
      "structure_image_present": true,
      "molecule_role": "concrete",
      "smiles_canonical": "..."
    }
  ],
  "run_summary": {       // optional operational metrics
    "run_id": "...",
    "tokens_in": 0,
    "tokens_out": 0,
    "usd_estimated": 0.0,
    "requests_total": 0,
    "requests_failed": 0,
    "requests_429": 0,
    "retries_total": 0,
    "checkpoint_resume_count": 0,
    "error_count": 0,
    "total_seconds": 0.0,
    "pdf_page_count": 100,
    "started_at": "2026-08-01T00:00:00Z",
    "finished_at": "2026-08-01T00:00:00Z",
    "status": "ok"
  }
}
```

## Metric definitions

### Activity (`eval_activity.py`)

| Metric | Definition |
|---|---|
| `label_recall` | Fraction of E001-E223 whose `compound_label` appears in the candidate. |
| `pdf_page_accuracy` | Of matched labels, fraction whose `pdf_page` agrees. |
| `value_exact_accuracy` | Of matched labels, fraction whose `value_original` is within ±0.05. |
| `value_canonical_nm_accuracy` | Of matched labels, fraction whose `value_canonical_nm` agrees within 5%. |
| `target_context_accuracy` | Of matched labels, fraction whose `target` + `metric` agree. |
| `operator_accuracy` | Of matched labels, fraction whose comparison operator agrees (`<`, `<=`, `=`, etc.). |
| `row_alignment_accuracy` | Of matched labels, fraction where page + value + target/metric + operator all agree. |

### Molecule (`eval_molecule.py`)

| Metric | Definition |
|---|---|
| `presence_recall` | Of matched labels, fraction whose candidate reports a structure image. |
| `label_recall` | Fraction of E001-E223 labels recovered. |
| `role_accuracy` | Of matched labels, fraction whose `molecule_role` matches the golden. |
| `smiles_match_rate` | Of rows with annotated canonical SMILES, fraction whose candidate canonical SMILES matches. |

### Markush (`eval_markush.py`)

| Metric | Definition |
|---|---|
| `leakage_count` | Number of golden markush anchors classified as `concrete`/`complete` by the candidate. Must be 0 in production. |
| `leakage_rate` | `leakage_count / anchors_total`. |
| `recall` | Fraction of golden markush anchors recovered by the candidate. |
| `role_classification_accuracy` | Of recovered anchors, fraction whose role is semantically safe; runtime `scaffold`, `fragment`, and `review_required` are safe Markush outcomes. |

### Stability (`eval_stability.py`)

The metric catalog is documented in `STABILITY_METRICS`. `validate_run_summary`
reports which keys are absent from a candidate `run_summary` block; an empty
return means the run covers every declared metric. No production claim should
be made from a single run; the catalog is the contract for what we expect
pipeline runs to emit.
