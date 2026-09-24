# SLANet-1M as table parser on the Hiro-Layout path

Status: implemented 2026-09-23 (replaces the NanoTabVLM V2 plan, which was
abandoned: custom-torch VLM required vendored source + 283 MB weights +
tokenizer; SLANet-1M is a 7.6 MB ONNX model with zero new dependencies).

## Model

- `dimtri009/SLANet-1M` — PaddlePaddle SLANet fine-tune for table structure
  recognition (MIT); ONNX re-export `bdatdo0601/slanet-1m-onnx`
  (`slanet_1m.onnx` 7.6 MB + `inference.yml`).
- Input: 488×488 (longest side ≤ 488, ImageNet normalization, pad), BGR.
- Outputs: structure-token logits `(1, T, 30)` + per-token normalized xyxy
  box `(1, T, 4)`.
- Decoder follows PaddleOCR `TableLabelDecode` as re-implemented by
  rapid_table: `sos + merge(dict) + eos` character list, stop at first eos
  (idx > 0), `<td …>` openers carry cell boxes scaled by the original image
  size, all-zero boxes kept in order (skipped during cell OCR).
- Cell text is read by the existing local RapidOCR
  (`ocr.page_text.read_text_in_boxes`), then inserted into the HTML skeleton;
  `layout.table_html.html_table_to_markdown` normalizes it downstream.

## Integration (Hiro path)

- `ResourceManager` entry `slanet_table` (HF `bdatdo0601/slanet-1m-onnx`,
  exact files `slanet_1m.onnx` + `inference.yml`, MIT).
- Adapter `mbforge/adapters/inference/table_slanet.py` — lazy onnxruntime
  session (CUDA EP when available, CPU fallback), `predict_table(image) -> HTML`,
  best-effort enrichment (empty on any failure, never breaks the page).
- `table_recognizer="slanet"`; recognition is unconditional (the
  `read_tables` switch was removed — the ONNX weights download on first use
  and recognition is best-effort enrichment).
- `layout/parse.py:_fill_tables` crops Hiro `table` regions, calls
  `runtime.table_slanet.predict_table`, stores `region["html"]` /
  `region["text"]` (Markdown) → flows into `page_text` / `SourceEvidence`
  unchanged; activity parser consumes it without changes.
- Bonus fix: `model_locator` derived the cache repo tail from `ms_repo`
  only, so HF-only snapshot models (Hiro-Layout, SLANet-1M) were never found
  after download (`repo_name = (ms_repo or hf_repo or id)` fallback).

## Verified

- Unit: 77 focused tests pass (structure decode contract, `_fill_tables`
  fill/degradation with a fake recognizer, adapter no-weights degradation),
  Ruff clean — no weights/network/GPU required.
- Real weights on this machine: synthesized 2×4 table crop → correct HTML
  skeleton + RapidOCR cell text (`Compound | IC50 (nM)`, `1a | 12.5`, …) and
  Markdown pipe table.
- GPU: onnxruntime 1.30 CUDA EP needs **cuBLAS 13** (`cublasLt64_13.dll`),
  which torch cu128 does not ship (it bundles cuBLAS 12). Fixed by
  `uv pip install --python .venv/Scripts/python.exe nvidia-cublas`
  (provides `nvidia/cu13/bin/x86_64/cublasLt64_13.dll`) plus the
  `onnxruntime.preload_dlls()` call in `table_slanet.load()` (mirrors
  `hiro_layout._preload_gpu_dlls`: import torch first to pin its CUDA-12
  cuDNN, then preload). Session now reports `CUDAExecutionProvider` active.
  Note: `nvidia-cublas` is a runtime environment fix, intentionally **not**
  added to `pyproject.toml` — machines without it fall back to CPU.
- End-to-end (2026-09-24, `CN121270515A.pdf`, 23 scanned pages, single Extract
  branch): 8 Hiro `tab` regions, all 8 recognized into Markdown tables (e.g.
  `| 试剂和耗材 | 来源 | 批号 |`), 8 `tab` evidence rows in `source_evidence`.
- **Provider wiring bug found by that run**: `adapters/inference/__init__.py`
  binds the submodules the runtime provider resolves by attribute, and
  `table_slanet` was missing — so `_DynamicModule` raised `AttributeError` on
  every call and recognition silently degraded to empty (the enrichment
  try/except swallows it). Now imported and guarded by
  `tests/unit/test_runtime_provider.py`.

## Outstanding

- None. Recognition is unconditional on the Hiro path (the `read_tables`
  switch was removed) and verified end-to-end on a 23-page scanned patent.
