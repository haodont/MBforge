# LLM 化学数据抽取参考规范（基于 Schilling-Wilhelmi et al., Chem. Soc. Rev. 2025）

> 版本: 1.0 · 日期: 2026-06-22  
> **性质**: 外部论文锚点 / 设计参考，**不是**现行代码 API 文档。文中 `src-tauri/` 等路径为迁移前快照。  
> 主参考论文: *Chem. Soc. Rev.* 2025, **54**, 1125–1150（DOI: [10.1039/d4cs00913d](https://doi.org/10.1039/d4cs00913d)）  
> 配套资源: [matextract.pub](https://matextract.pub) · [lamalab-org/matextract-book](https://github.com/lamalab-org/matextract-book)  
> 现行管线: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md)

---

## 0. 文档目的

把论文给出的**端到端 LLM 化学数据抽取框架**作为 MBForge 的外部锚点：

1. 用同一套术语对齐论文（preprocessing / interaction / postprocessing）
2. 明确**能做** vs **不能做** 的开发边界（基于现状盘点）
3. 给出可执行的**开发路径**（P0/P1/P2 优先级 + 验收条件）

避免 MBForge 自建一套与学界脱节的术语，也避免错失论文 §3.3 反复强调的"质量保证"环节。

---

## 1. 论文核心论点（Why this paper）

| 论点 | 论文位置 | 对 MBForge 的含义 |
|------|---------|-------------------|
| 化学/材料 99% 知识仍为非结构化文本 | §1, Fig. 1 | MBForge 的 PDF→knowledge 路线是"刚需"，方向正确 |
| 传统规则/小模型 = "death by 1000 cuts" | §1 | 多 backend OCR / 多 parser 不能取代质量评估 |
| LLM 让"通用 + 领域"可扩展 | §2, §3.2 | Agent + 工具路线正确，但**配套评估**才是关键 |
| 化学领域有"独特校验资源" | §3.3.2 | chematic 校验必须前置到生成环节，不是入库兜底 |
| 长链路 error amplification | §3.2.5 limitations | 当前 5+ 步 ReAct 必须加 self-reflection / critic |
| constrained decoding 是低垂果实 | §3.3.1, §15 future | **E-SMILES / MoleCode 本就是形式文法**，天然适合 |

**元论点**：论文反复出现的隐含命题是「评估 > 抽取」。MBForge 当前架构的隐含假设"管线越复杂越好"被论文否定。

---

## 2. 论文抽取框架（参考骨架）

论文 §3 给出端到端 5 阶段。MBForge 的所有开发活动按这 5 阶段归位：

```
┌────────────────────────────────────────────────────────────────────┐
│  [1] PREPROCESSING                                                  │
│      ├─ 1.1 数据获取：开源源 (EuroPMC/ChemRxiv/arXiv/USPTO/S2ORC)   │
│      ├─ 1.2 文档解析：VDU → Markdown (Nougat/Marker 等)             │
│      ├─ 1.3 文档清洗：剔除 refs/acknowledgments/headers/footers      │
│      └─ 1.4 上下文裁剪：chunking 决策树 (Fig. 5)                     │
│          ├─ 短文本 → 无需 chunking                                   │
│          ├─ 中文本 → semantic chunking                               │
│          └─ 大语料 → RAG + classification 预过滤                     │
├────────────────────────────────────────────────────────────────────┤
│  [2] LLM INTERACTION                                                │
│      ├─ 2.1 Prompt engineering: zero/few-shot, CoT, self-reflection │
│      ├─ 2.2 Schema format: YAML < JSON (token economy)             │
│      ├─ 2.3 Fine-tuning: LoRA/PEFT, human-in-the-loop 标注          │
│      └─ 2.4 Agentic: Planning + Reflection + Memory + Tool + Multi   │
├────────────────────────────────────────────────────────────────────┤
│  [3] POSTPROCESSING                                                 │
│      ├─ 3.1 Constrained decoding: outlines/instructor/jsonformer     │
│      ├─ 3.2 Domain validation: 守恒/价态/NMR-vs-formula 等         │
│      └─ 3.3 Evaluation: TP/FP/FN, F1, Hungarian match, canonical    │
├────────────────────────────────────────────────────────────────────┤
│  [4] DECISION TREES (Fig. 3 / 5 / 6)                                │
│      · 数据规模 → 选 chunking 策略                                  │
│      · 模态 → 选 VLM 或 OCR-LLM 管线                                │
│      · 任务表现 → 选 prompt/fine-tune/pre-train                      │
├────────────────────────────────────────────────────────────────────┤
│  [5] FRONTIERS (§4)                                                 │
│      4.1 multimodal · 4.2 cross-document linking                     │
│      4.3 scientific bias · 4.4 beyond-papers                        │
│      4.5 query-to-model · 4.6 benchmarks                            │
└────────────────────────────────────────────────────────────────────┘
```

---

## 3. 论文工具与库清单（技术雷达）

> 仅记录论文 §3 明确点名且**与 MBForge 现有栈兼容**的项。括号内为论文引用号。

### 3.1 解析与清洗
| 工具 | 论文位置 | 备注 |
|------|---------|------|
| Nougat (72) | §3.1.2 | Meta 学术 PDF→Markdown，端到端 |
| Marker (73) | §3.1.2 | 同上 |
| Tesseract (71) | §3.1.2 | OCR 经典；可作 baseline |
| ChemNLP (76) | §3.1.2 | regex 清洗参考 |

### 3.2 Prompt 与解码
| 工具 | 论文位置 | 备注 |
|------|---------|------|
| outlines (202) | §3.3.1 | **constrained decoding** 主推，含 grammar |
| instructor (203) | §3.3.1 | 同上，Pydantic 风格 |
| jsonformer (199) | §3.3.1 | 老牌 constrained decoding |
| marvin (204) | §3.3.1 | 同上 |
| OpenAI structured outputs | §3.3.1 | 商用 API；强约束 |
| DSPy (115) | §3.2.1 | prompt 自动优化 |
| LangChain (112) / LlamaIndex (113) | §3.2.1 | 模板框架 |

### 3.3 标注与评估
| 工具 | 论文位置 | 备注 |
|------|---------|------|
| Argilla (67) | §3.1.1 | 标注平台；human-in-the-loop |
| Doccano (68) | §3.1.1 | 同上 |
| pint (211) / unyt (212) | §3.3.2 | 单位标准化 |
| PubChem (209) | §3.3.2 | 化学名 canonical |
| Chemical Identifier Resolver (210) | §3.3.2 | 同上 |

### 3.4 化学专用工具（§3.2.4 明确点名）
| 工具 | 论文位置 | 备注 |
|------|---------|------|
| ReactionDataExtractor 2.0 (151) | §3.2.4 | 反应式抽取 |
| OpenChemIE (152) | §3.2.4 | 反应 + 文本 + 图 |
| SPIRES (207) | §3.3.1 | ontology grounding 范式 |
| PaperQA (79) | §3.2.5 | 引用遍历 / multi-agent 范式 |
| GoLLIE (125) | §3.2.2 | 任务 guideline 微调范式 |

---

## 4. MBForge 现状盘点（已验证，基于 2026-06-22 代码）

### 4.1 已对齐（✓ 论文背书）

| 论文条目 | MBForge 实现 | 位置 |
|---------|-------------|------|
| §3.1.2 VDU 多 backend | `extract_pdf_workflow` 可切换 MinerU/OCR | `src/mbforge/pipeline/runner.py` |
| §3.1.3 RAG | OpenKB + PageIndex 树推理 + dense rerank via LLM | `src/mbforge/openkb/` |
| §3.2.4 专用图工具 | MolDet (YOLO) + MolScribe (图→SMILES) | `src/mbforge/backends/moldet.py`, `molscribe.py` |
| §3.2.4 跨页关联 | moldet_coref | `src/mbforge/parsers/molecule/coref_alt.py` |
| §3.2.5 ReAct agent | 5 工具 + LangGraph | `src/mbforge/agent/` |
| §3.3.2 领域校验 | RDKit (SMILES, ECFP4, Tanimoto, MCS) | `src/mbforge/chem/` |
| 三层表示 | SMILES / E-SMILES / MoleCode | `docs/specs/esmiles-spec.md` |

### 4.2 缺口（✗ 论文强推，MBForge 缺失）

| # | 缺口 | 论文位置 | 证据（MBForge 代码） |
|---|------|---------|----------------|
| G1 | **constrained decoding** | §3.3.1, §15 future | agent 输出为 rig-core 自由字符串，无 JSON Schema 强制 |
| G2 | **F1 / precision / recall 评估** | §3.3.2 | `src-tauri/src/` 内 0 命中；pix2seq 训练 accuracy 与抽取无关 |
| G3 | **gold set** | §3.3.2 | `tests/integration/` 无抽取评测；`docs/pdf-pipeline-test/` 是旧 fixture |
| G4 | **self-reflection / critic** | §3.2.5, CoVe glossary | `grep self_reflect\|critic\|verifier` 在 agent/ 下 0 命中 |
| G5 | **chunking 决策树** | §3.1.3, Fig. 5 | `Cargo.toml:39` 仅 `text-splitter`（fixed-size），无 semantic / 分类预过滤 |
| G6 | **YAML schema 提示** | §3.2.1 Patiny & Godin | system prompt 全 JSON |
| G7 | **ontology grounding** (ChEBI/PubChem CID/MESH) | §3.3.1 SPIRES | 仅 chematic 内部 canonical，无外部 ontology 链接 |
| G8 | **文档清洗** (剔除 refs/acknowledgments/headers) | §3.1.2 | `extract.rs:1816` 仅做图像 markdown 增强，未剥离无用段落 |
| G9 | **temperature=0 强制** | §3.1, §3.3.1 | `core/agent/llm_gateway.rs:178` 实际写死 `temperature: 0.7` |
| G10 | **多 agent (creator + critic)** | §3.2.5 multi-agent | `rig_adapter.rs` 仅单 agent 注册 |
| G11 | **prompt 自动优化** (DSPy 类) | §3.2.1 | system prompt 全部硬编码模板 |
| G12 | **Human-in-the-loop 标注** | §3.2.2 Dagdelen | 无 Argilla/Doccano 集成 |
| G13 | **cross-document linking** | §4.2 | RAG 仅单文档内 chunk 检索，无 citation traversal |
| G14 | **VLM 替代管线 (A/B)** | §3.2.4 | 仅有 OCR+Moldet 管线，无 VLM 选项 |
| G15 | **负结果/失败案例库** | §4.3 | 无 |

### 4.3 MBForge 超前 / 论文未覆盖

- E-SMILES / MoleCode 三层表示（最天然 constrained decoding 目标）
- 跨页分子关联 (coref) 完整管线
- Tauri 桌面端到端封装

---

## 5. 开发边界（Can / Cannot / Conditional）

### 5.1 我们**能做**（CAN）

| 能力 | 论文支撑 | MBForge 路径 |
|------|---------|-------------|
| LLM-抽取闭环 | §3 全章 | 已具备 agent + 工具 + vector + chematic |
| 多模态分子图识别 | §3.2.4 | MolDet + MolScribe + coref |
| 知识库 + RAG 查询 | §3.1.3 | vector store + FTS5 |
| 三层分子表示 | 论文未涉及 | SMILES / E-SMILES / MoleCode 已规范 |
| 桌面端落地 | 论文未涉及 | Tauri 完整 |

### 5.2 我们**不能做**（CANNOT，不在范围）

| 能力 | 原因 | 决策 |
|------|------|------|
| 训练化学基模 (从零) | 论文 §3.2.3：Llama 3 用了 8M GPU-hours | **不做**，仅 fine-tune |
| 自建 embedding 模型 | MBForge 规模 < 20K chunks | 用 OpenKB PageIndex + LLM rerank |
| 自建 OCR | Nougat/Marker 论文强推 | 集成第三方 |
| 自建 VLM | 商用 GPT-4V/Claude 3 已 SOTA | 集成第三方 |
| 大规模科学文献挖掘 (跨出版商 TDM) | 论文 §3.1.1 详述版权陷阱 | 不做，由用户提供 PDF |
| 反应式自动合成实验 | 论文 §3.2.5 提 safety | 不做（仅推荐） |

### 5.3 条件性（CONDITIONAL，依赖外部条件）

| 能力 | 条件 | 备注 |
|------|------|------|
| 论文级 fine-tuning (LoRA) | 用户提供 100+ gold 样本 | §3.2.2 强推 P1 |
| ontology 链接 | PubChem/ChEBI 在线 API 可达 | §3.3.1 P1 |
| VLM 替代 | GPT-4V/Claude 3 API 配额 | §3.2.4 P2 |
| citation traversal | arxiv/PMC API 配额 | §4.2 P2 |
| Human-in-the-loop UI | 前端资源 + 用户标注流程 | §3.2.2 P2 |

### 5.4 专利域特化边界（Patent Domain）

> 专利抽取是 MBForge 差异化主战场，与科学论文目标不同：论文侧重反应/性质，专利侧重**法律级 claim 范围**。
> 论文 §3.2.4 明确点名 "many of these tools encounter problems with variable end groups mostly noted as 'R-group'" — 这是专利 Markush 结构的核心难点。

#### 5.4.1 专利 vs 论文：差异表

| 维度 | 科学论文 | 专利 | MBForge 影响 |
|------|---------|------|------------|
| 文档长度 | 10-30 页 | 50-500 页 | chunking + RAG 必须 robust |
| 命名 | IUPAC / 通用名 | 编号 + 化学名 + 商标名混用 | canonical 比对更复杂 |
| 结构 | Section 实验 + Results | Claim (Markush) + Example (具体) + Description | 需要 Markush 标签保留 |
| 关联粒度 | 章节内 | claim ↔ example ↔ reaction scheme 三层 join | 必须扩展 coref |
| 跨文档 | 引用即参考 | **专利族系**（US/EP/JP/CN 同族）+ 优先权 | 必须做 family traversal |
| 错误成本 | 低（科研辅助） | **高**（侵权分析法律风险） | CoVe + LLM-as-judge 非可选 |
| 法律语义 | 无 | "comprising" / "consisting of" / "wherein" | agent 工具需 claim-language 解析 |
| 分类 | CPC 可选 | **CPC 必须**（C07/A61K 等子领域） | 抽取结果反向 link CPC |

#### 5.4.2 专利抽取核心瓶颈（按优先级）

1. **Markush ↔ Example 映射**（核心）
   - Claim = 抽象 R-group / 通用结构
   - Example = 具体合成路径 + 具体化合物
   - 价值 = "example 是否落在 claim 范围内"
   - MBForge 已有 `core/chem/markush.rs` + `chemMarkushCheck`，但**未评估准确率**
   - 论文 §3.3.2 化学守恒校验范式直接适用

2. **跨页 + 跨文档 关联**（论文 §4.2 前沿）
   - 跨页：`moldet_coref` 已做 ✓
   - 跨族系：**未做**，是专利域最大缺口
   - 跨节：claim ↔ example ↔ reaction scheme 三层 join **未做**

3. **Hallucination 法律成本**（强制 CoVe + LLM-as-judge）
   - 论文 §3.3.2：第二 LLM 检查 factual inconsistency
   - 对专利：**比论文更必须**

4. **Claim 语言学解析**（待新增能力）
   - "comprising"（开放）vs "consisting of"（封闭）vs "wherein"（限定）
   - 律师用此判断侵权范围
   - 当前 agent 工具无此能力

5. **CPC 分类 link**（标准化）
   - USPTO/CPC code 与抽取结果 join
   - 论文 §3.3.1 SPIRES ontology grounding 范式

#### 5.4.3 专利域 CAN / CANNOT

| 类别 | 内容 |
|------|------|
| **CAN** | Markush 抽取与匹配；同族专利 link；CPC 分类 join；claim-language 解析；USPTO 数据接入；infringement 分析支持 |
| **CANNOT** | 实时侵权判定（仅辅助）；自动续期 / 失效跟踪（依赖 USPTO API）；多语种同族抽取（v1 仅 EN） |
| **CONDITIONAL** | LoRA 微调（P2-4，依赖 ≥200 gold 专利样本）；VLM 替代（P2-2，专利图特别密集） |

---

## 6. 开发路径（P0 / P1 / P2）

### P0 — 必须先做（建立质量基线）

> 不做 P0 之前，所有"提升抽取质量"的改动都是盲改。

| ID | 任务 | 论文位置 | 验收条件 | 工作量 |
|----|------|---------|---------|--------|
| P0-1 | **gold set + F1 harness** | §3.3.2 | (a) ≥50 gold PDF + 标注 JSON（其中**≥10 篇专利**，含 claim/example/R-group 标注）；(b) Rust 端实现 precision/recall/F1；(c) Hungarian assignment 多实例匹配；(d) Levenshtein fuzzy match；(e) `cargo run --bin eval` 跑通，给出端到端 baseline 数字；**(f) 专利子指标：claim-example mapping F1** | 2-3 周 |
| P0-2 | **temperature=0 强制（抽取路径）** | §3.1, §3.3.1 | `llm_gateway.rs` 中所有抽取调用显式 `temperature: 0.0`；其他任务（生成/对话）可保留；单元测试覆盖 | 半天 |
| P0-3 | **constrained decoding 接 E-SMILES（含 Markush）** | §3.3.1 | (a) 选定 `outlines` 或自实现 grammar；(b) Python 侧 LLM 调用接 E-SMILES **+ Markush 标签** 文法；(c) 落地后 SMILES 字段无效率显著下降（与 P0-1 对照）；(d) **专利：R-group 抽取保留率 ≥95%** | 1-2 周 |
| P0-4 | **chain-of-verification + LLM-as-judge** | §3.2.5 Reflection, CoVe glossary, §3.3.2 LLM-as-judge | (a) ReAct 主 agent 在"写入知识库"前插入 verifier 步骤（CoVe）；(b) **专利路径额外加 LLM-as-judge**（第二 LLM 检查 factual inconsistency）；(c) 成本/收益在 P0-1 上量化 | 3-5 天 |

### P1 — 应该做（论文强推）

| ID | 任务 | 论文位置 | 验收条件 | 工作量 |
|----|------|---------|---------|--------|
| P1-1 | **document cleaning** (剥 references/ack/headers) | §3.1.2 | `text.md` 阶段加 cleaning step；前后向量库大小对比 ≥ -30% | 3 天 |
| P1-2 | **semantic chunking + 分类预过滤** | §3.1.3, Fig. 5 | (a) 引入 semantic chunker（按 section/heading）；(b) 启发式分类器先过滤"含分子/反应信息"的 chunk；(c) 与 P0-1 对比 F1 | 1-2 周 |
| P1-3 | **ontology grounding** (ChEBI / PubChem CID) | §3.3.1 SPIRES | (a) 抽到的分子入库时尝试 PubChem REST；(b) 新增 `ontology_id` 列；(c) 与外部知识图谱可 join | 1 周 |
| P1-4 | **multi-agent (creator + critic)** | §3.2.5 multi-agent | `rig_adapter.rs` 增加 verifier agent；同一输入双 agent 投票；冲突时人工 review | 1-2 周 |
| P1-5 | **YAML schema 替换 JSON** | §3.2.1 Patiny & Godin | system prompt 模板改 YAML；token 减少 ≥20%（在固定测试 prompt 上验证） | 2 天 |
| P1-6 | **DSPy 引入可行性评估** | §3.2.1 | 评估报告 `docs/dspy-eval.md`：是否值得接入；如不接，明确理由 | 1 周 |
| P1-7 | **claim-example-reaction 三层 join**（专利域） | §4.2 + §5.4 | (a) DB schema 加 `claim_id` / `example_id` / `reaction_scheme_id` 三列；(b) 抽取阶段产出三层 ID 映射；(c) 评测 claim-example F1（独立于单分子 F1） | 1-2 周 |
| P1-8 | **同族专利 family traversal**（专利域，论文 §4.2 前沿提前） | §4.2 | (a) 新增 `agent 工具：patent_family(doc_id)` 抓 US/EP/JP/CN 同族；(b) 同族 join 入知识库；(c) 对同一发明跨语种 link | 2-3 周 |
| P1-9 | **Claim 语言学解析**（专利域） | §5.4 瓶颈 #4 | (a) 新增 `parse_claim_language(text)`：识别 "comprising" / "consisting of" / "wherein" 边界；(b) 输出 claim scope 类型（open/closed/limited）；(c) 律师 review 校验 | 1 周 |
| P1-10 | **CPC 分类 link**（专利域） | §3.3.1 SPIRES + §5.4 瓶颈 #5 | (a) 抽到的分子尝试映射 CPC code；(b) 知识库加 `cpc_code` 列；(c) 支持按 CPC 子领域检索 | 1 周 |

### P2 — 前沿（论文 §4 开放问题）

| ID | 任务 | 论文位置 | 验收条件 | 工作量 |
|----|------|---------|---------|--------|
| P2-1 | **citation traversal 工具（论文域）** | §4.2 | 新增 `agent 工具：cite_traverse(paper_id)`，抓 references 并入 RAG。**注：专利域对应任务已在 P1-8 提前** | 2-3 周 |
| P2-2 | **VLM 替代 A/B 实验** | §3.2.4 | (a) 选定一个 VLM API；(b) 与 OCR+Moldet 管线 A/B；(c) 写评估报告 | 2-3 周 |
| P2-3 | **Human-in-the-loop 标注 UI** | §3.2.2 Dagdelen | (a) 前端嵌入 Argilla 风格标注；(b) 标注数据驱动 LoRA 微调（见 P2-4） | 3-4 周 |
| P2-4 | **化学抽取 LoRA 微调** | §3.2.2 | (a) ≥200 gold 样本（依赖 P2-3）；(b) LoRA 微调基础 LLM；(c) 与 P0-1 对比 F1 | 2-3 周 |
| P2-5 | **负结果 / 失败案例库** | §4.3 | 设计 schema 收集"实验失败"案例；对抗 scientific bias | 1-2 周 |
| P2-6 | **query-to-model 探索** | §4.5 | 与 PaperQA 类系统对齐做 PoC | research |

---

## 7. 关键决策表（论文反复点名，MBForge 必须显式回答）

| 决策点 | 论文建议 | MBForge 当前 | 应改为 |
|--------|---------|-------------|--------|
| 抽取任务 temperature | 0 | 0.7 (`llm_gateway.rs:178`) | **0** |
| 抽取输出 schema | YAML 优于 JSON | JSON | YAML |
| Schema 约束方式 | constrained decoding | 无 | `outlines` / instructor |
| Agent 自检 | self-reflection + critic | 无 | 加 verifier agent |
| Chunking | 决策树选 semantic + 分类预过滤 | `text-splitter` fixed | semantic + 分类 |
| 文档清洗 | 剥 refs/ack/headers | 未做 | 加 step |
| 评估 | F1 + Hungarian + canonical SMILES 比对 | 无 | 建 harness |
| Ontology | 链接 ChEBI/PubChem | 仅 chematic 内部 | 链接外部 |
| Prompt 优化 | DSPy 自动 | 硬编码 | 评估 DSPy 后决定 |
| **专利路径 CoVe** | 强制 + LLM-as-judge | 无 | **强制**（法律成本） |
| **专利 R-group 抽取** | constrained decoding 含 Markush | E-SMILES 文法骨架存在但未约束 LLM | outlines grammar |
| **专利跨族系** | family traversal | 未做 | P1-8 |
| **Claim 语言学** | "comprising" vs "consisting of" 区分 | 无 | P1-9 |

---

## 8. 配套实践

### 8.1 论文→代码追踪

每次涉及抽取质量改动：

1. 跑 P0-1 harness 得 baseline 数字
2. 改动
3. 再跑 harness，对比 F1
4. 把"数字 + 改动 commit"写入 `TODO/<date>-<topic>.md`

### 8.2 新增 Agent 工具

参考 `docs/specs/architecture-conventions.md` + 本规范 §6 P1-4：新增工具同时考虑是否需要 verifier 工具。

### 8.3 文档同步

`TODO/INDEX.md` 与 `AGENTS.md §技术债务` 同步维护本规范引用。

---

## 9. 参考文献

> 完整 219 条参考文献见论文原文。本规范仅直接引用与 MBForge 决策相关的编号。

- 主参考: Schilling-Wilhelmi et al., *Chem. Soc. Rev.* 2025, **54**, 1125–1150, DOI 10.1039/d4cs00913d
- 配套书: https://matextract.pub · https://github.com/lamalab-org/matextract-book
- 关键二级引用（论文内编号）:
  - Ref 22 Hira et al. *Digital Discovery* 2024, 3, 1021
  - Ref 29 Jablonka et al. *Digital Discovery* 2023, 2, 1233
  - Ref 30 Zhang et al. *Chem. Sci.* 2024, 15, 10600
  - Ref 34 Dagdelen et al. *Nat. Commun.* 2024, 15, 1418
  - Ref 37 Polak & Morgan *Nat. Commun.* 2024, 15, 1569
  - Ref 75 Bran et al. （知识图谱抽取）
  - Ref 79 PaperQA
  - Ref 115 DSPy
  - Ref 116 Patiny & Godin（YAML schema）
  - Ref 123 LoRA
  - Ref 151 ReactionDataExtractor 2.0
  - Ref 152 OpenChemIE
  - Ref 199 jsonformer
  - Ref 202 outlines
  - Ref 203 instructor
  - Ref 207 SPIRES（ontology grounding）
  - Ref 220 Chain-of-Verification

---

## 10. 变更日志

- 2026-06-22 v1.1 加入专利域特化：§5.4（专利 vs 论文差异 + 核心瓶颈 5 条 + CAN/CANNOT）；P0-1/3/4 增强专利子指标；新增 P1-7~P1-10（claim-example join / family traversal / claim-language / CPC link）；P2-1 注明专利版已前移 P1-8；§7 决策表加 4 行专利项。
- 2026-06-22 v1.0 初版。基于 d4cs00913d.pdf 深度阅读 + MBForge 代码现状盘点。