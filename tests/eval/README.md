# Dual-golden pipeline evaluation

This directory contains the repeatable regression entrypoint for the two
supervised reference documents. The source PDFs remain external; only the
reviewed JSON references and tests are stored in the repository.

## Golden coverage

| Golden | Scope | Stable acceptance focus |
|---|---|---|
| `US20260027089A1` | 100-page scanned patent; 223 activity rows (`E001`–`E223`) | pIC50 value/page/target alignment and Formula I/R-group leakage |
| `WO2026037254A1` | 49-page patent; 27 IC50 rows (`1`–`19`, `21`–`28`) | `<` boundary preservation, MRGPRX2 context, Markush/intermediate/isomer review routing |

WO compound `20` is absent from the source table and must not be invented.
The v1 molecule references intentionally do not score exact SMILES.

Both references are structurally valid v2 calibration sets, but neither is a
fully double-reviewed production gold set yet. Each currently has two
`pending_manual` activity rows; most rows have a designated visual reviewer
but do not have a `second_reviewer`. The integrity validator reports these as
warnings. Primary activity metrics exclude pending rows while retaining their
counts in the evaluation report.

## Run the regression suite

```powershell
uv run pytest tests/eval/golden_us20260027089 tests/eval/golden_wo2026037254 -q
```

To score a pipeline-produced candidate dump:

```powershell
python -m tests.eval.run_eval `
  --golden WO2026037254A1 `
  --candidate path/to/candidate.json `
  --output path/to/report.json
```

Run the command once for each `--golden` value when comparing both documents.
The report covers activity, concrete-molecule anchors, Markush anchors, the
operational metric contract, and golden-reference validation metadata.

## Role contract

The runtime classifier uses `complete`, `scaffold`, `fragment`, and
`review_required`:

- only `complete` may enter the concrete molecule library;
- `scaffold` and `fragment` are Markush records;
- `review_required` is retained for manual review.

The evaluator maps `complete` to the supervised `concrete` role. For Markush
anchors, `scaffold`, `fragment`, and `review_required` are all safe non-concrete
outcomes; `complete` is counted as leakage. A golden concrete anchor with
`expected_review_required=true` must be returned as `review_required`.

Activity row alignment includes the compound label, PDF page, displayed value,
target/metric, and comparison operator. Thus `< 500 nM` is not equivalent to
`500 nM`.
