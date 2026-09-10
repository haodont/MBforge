# References & Acknowledgments

> Last updated: 2026-07-15.
> MBForge builds on the work of many open-source projects and services.
> Thank you to the teams behind each.

---

## Core Frameworks

| Project | License | Used for |
|---|---|---|
| [FastAPI](https://fastapi.tiangolo.com/) | MIT | Python backend (REST + SSE) |
| [LangChain](https://www.langchain.com/) | MIT | LLM provider abstraction (pipeline content extraction) |
| [React](https://react.dev/) | MIT | Frontend UI framework |
| [Vite](https://vitejs.dev/) | MIT | Frontend build tool |
| [Pydantic](https://docs.pydantic.dev/) | MIT | Request/response validation |

## PDF Parsing

| Project | License | Used for |
|---|---|---|
| [pdfplumber](https://github.com/jsvine/pdfplumber) | MIT | Text + layout extraction |
| [pypdfium2](https://github.com/pypdfium2-team/pypdfium2) | Apache-2.0 | Page rendering (image fallback) |
| [MinerU](https://mineru.net/) | Commercial API | Cloud OCR for difficult PDFs |
| [UniParser](https://uniparser.dp.tech/) | Commercial API | Cloud document parsing |
| [LlamaIndex LlamaParse](https://www.llamaindex.ai/) | Commercial API | Cloud parsing fallback |

> **Removed**: pdf-inspector, lopdf, PyMuPDF (replaced by pdfplumber + pypdfium2).

## Cheminformatics

| Project | License | Used for |
|---|---|---|
| [RDKit](https://www.rdkit.org/) | BSD-3-Clause | Fingerprints, descriptors, SMILES parsing |
| [MolParser](https://github.com/dptech-corp/MolParser) | Apache-2.0 | Molecule image → E-SMILES recognition + postprocessing |
| [OpenBabel](https://openbabel.org/) | GPL-2.0 | Format conversion (optional) |
| [E-SMILES](https://github.com/dptech-corp/MolParser) | — | Extended SMILES spec (MolParser format) |

### MolParser Sub-dependencies

| Component | License | Source |
|---|---|---|
| Transformers (`MolParserVisionEncoderDecoderModel`) | Apache-2.0 | [HuggingFace transformers](https://github.com/huggingface/transformers) |
| timm (`vit_tiny_r_s16_p8_224`) | Apache-2.0 | [timm (rwightman)](https://github.com/huggingface/pytorch-image-models) |

## AI Models

| Model | License | Source |
|---|---|---|
| Qwen3-Embedding-0.6B | Apache-2.0 | [Qwen (Alibaba)](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) |
| Qwen3-Reranker-0.6B | Apache-2.0 | [Qwen (Alibaba)](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) |
| MolDetv2-YOLO26 | cc-by-nc-sa-4.0 | [UniParser/MolDetv2-YOLO26](https://huggingface.co/UniParser/MolDetv2-YOLO26) |
| MolParser-Mobile | cc-by-nc-sa-4.0 | [UniParser/MolParser-Mobile](https://huggingface.co/UniParser/MolParser-Mobile) |

## Storage & Retrieval

| Project | License | Used for |
|---|---|---|
| [SQLite](https://www.sqlite.org/) | Public Domain | Business data persistence |
| SQLite FTS5 | Public Domain | Native full-text search over document Markdown |
| [sentence-transformers](https://www.sbert.net/) | Apache-2.0 | Embedding model framework |
| [HuggingFace Transformers](https://huggingface.co/docs/transformers) | Apache-2.0 | Model loading & inference |

## Knowledge Format References

| Project / specification | License | Status in MBForge | Used for |
|---|---|---|---|
| [Open Knowledge Format (OKF)](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf) | Apache-2.0 | Reference specification; not a runtime dependency | Portable Markdown + YAML knowledge bundles and the unified Knowledge workspace model |
| [OKF reference agent](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf/src/reference_agent) | Apache-2.0 | Reference implementation; not bundled | Understanding how OKF documents can be discovered and consumed by an agent |

The local adaptation and its current boundaries are documented in
[`wiki/okf.md`](wiki/okf.md). This table distinguishes software used at runtime
from third-party projects consulted for format and architecture decisions.

> **Removed**: ChromaDB, rusqlite, Zvec, OpenKB, and PageIndex. MBForge now uses
> SQLite FTS5 and deterministic Markdown/Wiki artifacts for local retrieval.

## ML Inference

| Project | License | Used for |
|---|---|---|
| [PyTorch](https://pytorch.org/) | BSD-3-Clause | ML backend (CUDA 12.8 optional) |
| [Ultralytics (YOLO)](https://ultralytics.com/) | AGPL-3.0 | MolDetv2 object detection |

## Design Inspirations

| Project | Reference |
|---|---|
| [OpenViking](https://github.com/volcengine/OpenViking) | Knowledge base architecture |
| [TencentDB-Agent-Memory](https://github.com/Tencent/TencentDB-Agent-Memory) | Agent memory system design |
| [RxnScribe](https://github.com/thomas0809/RxnScribe) | Reaction diagram parsing |
| [OpenChemIE](https://github.com/CrystalEye42/OpenChemIE) | Chemical information extraction |

## LLM Extraction Methodology

| Work | Use |
|---|---|
| [Dagdelen et al. 2024 (Nature Comm. 15:1418)](https://doi.org/10.1038/s41467-024-45563-x) | LLM-NERRE: joint NER + relation extraction. Our post-process prompt borrows the JSON schema and the "canonicalization is extraction" principle. |

## Academic Papers

| Paper | Use |
|---|---|
| "MolParser: End-to-end Visual Recognition of Molecule Structures in the Wild" (arXiv:2411.11098) | E-SMILES format + OCSR architecture reference |
| Qwen3 technical report | Embedding/reranker architecture reference |

---

*If you maintain one of the projects above and would like to be acknowledged
differently, or if any attribution is incorrect, please open an issue.*
