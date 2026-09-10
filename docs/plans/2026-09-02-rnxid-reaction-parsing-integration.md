# RNXID 反应图解解析能力接入设计分析

> 日期:2026-09-02 · 状态:草案(供评审) · 关联文档:RNXID (arXiv:2603.15011v2)、MinerU.Chem (arXiv:2608.03525v3)
> 本文件回答:"RNXID 这个项目能给 MBForge 带来什么、在 pipeline 的哪个位置接入、以什么形态接入、成本与风险如何"。

---

## 0. TL;DR(结论先行)

1. **RNXID 解决的是 MBForge 当前完全空白的能力:反应图(reaction diagram)的结构化解析**。MBForge 已捕获分子(E-SMILES)、Markush、活动值(IC50 等),但文献中最富信息量的"反应式/合成路线/条件"至今是死图。
2. **其副产品 Mid-Mapper(分子框↔标识符映射)与现有 `recover_labels.py` 正好互补**:后者是文本侧(MS m/z 证据),前者是图像侧(bold 编号识别),两者可联合把标识符可靠挂到分子上,替代当前 Activity 链接"名称→SMILES→page-proximity"的脆弱回退。
3. **接入形态建议 = 新增一个 pipeline Stage(ReactionStage)+ 新增 reaction 数据模型 + 后端镜像现有 `backends/` 模式**,不侵入现有 4 阶段主链;标识符对齐做成 Markdown 阶段的可选强化。
4. **现实约束**:RNXID 模型/数据/代码尚未开源(论文承诺 release);本地 GPU 为 RTX 3070 Ti 8GB,可跑 3B 级 VL(INT4)但不宜跑完整 7B+ RxnDP 训练。因此推荐"先接 Idt-TE(纯文本 LLM,可立即复用现有 llm 配置)→ 再上图像侧(云端零样本/Mid-Mapper)→ 等开源模型发布后替换"。MinerU.Chem 已上线在线服务,是图像侧最快的验证通道。

---

## 1. 当前 MBForge pipeline(现状基线)

规范模型见 `docs/wiki/pipeline.md`,4 逻辑阶段,`STAGES` 注册于 `src/mbforge/pipeline/runner.py:119`:

```
PDF → Extract → Markdown → Activity → Persist
```

| 阶段 | 覆盖能力 | 关键实现 |
|---|---|---|
| Extract | 文本+OCR 链(MinerU→Paddle→GLM,cloud-only) | `extract_text.py`, `backends/ocr/` |
| Markdown | 分子检测(MolDetv2-FT YOLO26n)+ 识别(MolParser→E-SMILES)+ 标签/Markush 分类 + rough MD | `extract_molecules.py`, `recover_labels.py`, `classify_structure_role.py`, `esmiles_insert.py` |
| Activity | 表格活动值(IC50/Ki/EC50/Kd)确定性解析 + LLM 补全,链接分子 | `extract_activities.py`, `activity_parsing/` |
| Persist | molecule/activity/link 入库 + Markush review gate | `persist_*.py` |

**现有能力盲区**:
- 反应式/合成路线/条件 → 不解析(只有 image 落盘)。
- 化合物编号(label)只靠文本恢复(`recover_labels.py`,MS m/z 匹配);图内 bold 编号不识别。
- 分子↔文本链接靠 page-proximity 回退,无"标识符级"精确对齐。
- 无 reaction 实体 schema(DB 无 reaction 表)。

---

## 2. 两份论文在技术生态中的位置

三者同源:MBForge 的 OCR 链首位后端即 MinerU;识别后端 MolParser(dptech)→ 即 MinerU.Chem Table 3 中的 "Uni-Parser MolParser 1.5 (E-SMILES)"。RNXID 与 MinerU.Chem 同属上海 AI Lab(Jiang Wu / Conghui He)体系,后者的 **Molecule Identifier Extraction 模块直接源自 RNXID 的 Mid-Mapper**。因此集成是"近亲基因",不是异种拼接。

### RNXID(arXiv:2603.15011v2)— 反应图解解析
| 组件 | 能力 | 可迁移性 |
|---|---|---|
| **IdtVP** | 以图中天然 bold 标识符(1a/2b)作视觉提示,激活 VLM 预训练化学知识;零样本优于 BIVP/BROS | 提示词策略,任何 VL API 可复用;需画框工具 |
| **Mid-Mapper** | Qwen2.5-VL-3B(蒸馏 Gemini),把 MolYOLO 框映射到语义标识符,无标签分子自动赋虚拟 id | 3B 模型,INT4 可本地跑(3070 Ti) |
| **RxnDP 主模型** | 输出结构化 JSON reactions[]:reactants/products/conditions,组件类型 Idt/Mol/Txt;SFT + Re3-DAPO | 需 7B+ VL,云端最稳;训练需 H200 级 |
| **Idt-TE** | 纯文本 LLM 级联 4 步(anchor 抽取→依赖分类→共指消解→反应抽取),以标识符为主键 | 纯 LLM,直接复用 MBForge llm 配置 |
| **跨模态验证** | 视觉结果 ↔ 文本结果经共享标识符对齐:Precision Refinement(文本纠 OCR/视觉错)+ Contextual Enrichment(文本补全反应条件) | 与 MBForge Activity/正文语义天然契合 |

### MinerU.Chem — 工作流参考(五模块后处理层)
```
MinerU 通用解析(Markdown+layout)
  → a. Chemistry relevance filter(图/表区域化学相关二分类)
  → b. Molecule structure detection(MolYOLO)
  → c. Molecule identifier extraction(Mid-Mapper)
  → d. Molecule structure recognition(CARBON 图 → MolFile/SMILES)
  → e. Reaction scheme parsing(→ Reaction Summary List)
输出: Molecule Summary List + Reaction Summary List(带 page/bbox/id/交叉引用)
```
**对 MBForge 最有价值的借鉴**:① 化学层作为"后处理层"叠加在通用解析之上——MBForge 已天然如此;② 输出"与源码位置绑定的两个 Summary List"(可追溯性)——对应 MBForge 的 evidence/crops/pages 体系;③ 反应记录尽量回链到分子记录——正是我们要建的 reaction→molecule 外键。

---

## 3. 能力映射:RNXID ↔ MBForge

| MBForge 现有 | RNXID 对应 | 重叠/互补 | 动作 |
|---|---|---|---|
| MolDetv2-FT 检测 | MolYOLO(上游,RNXID 用它画框) | 同角色不同模型 | **不替换**,RNXID 输入直接吃 MBForge 现有 crop/bbox |
| MolParser → SMILES | 识别(IdtVP 只需"分子存在",不需结构) | 互补:RxnDP 输出 Idt/Mol,结构解析仍归 MolParser | 并存 |
| `recover_labels.py`(文本+MS 证据) | Mid-Mapper(图内 bold 编号) | **强互补**:两套证据合并→高置信 label↔molecule | 新增图侧证据源 |
| `extract_activities.py`(表格 IC50) | Idt-TE(正文反应/条件抽取) | 互补:前者属性表,后者 procedure/条件 | 新增 |
| — (无 reaction 实体) | RxnDP 输出 JSON reactions | **空白填补** | 新增 Stage + schema |
| Activity 链接 name→SMILES→page-proximity | 共享标识符跨模态对齐 | 升级:标识符作稳定 join key | 强化 Markdown 阶段 |
| Markush review queue | —(RNXID 不含 Markush) | 无冲突;MinerU.Chem 亦将 Markush 列为 future | — |

---

## 4. 推荐接入设计

### 4.1 设计原则
1. **不侵入现有 4 阶段主链**:新能力作为"化学信息扩展层",沿用 `StageExecutor` 协议,便于独立开关/降级。
2. **标识符为一级公民**:doc 内唯一 join key,把 molecule(图)、reaction(图)、activity(表)、procedure 文本(正文)四类信息用同一把钥匙串起来。
3. **全部候选先落 review**:沿用现有 Markush review/role gate 哲学,reaction 记录必须可溯源(page/bbox/crop)+ 可复核。
4. **云端/本地双轨,默认降级**:图像侧 VLM 可走云端(zero-shot IdtVP)或本地(Mid-Mapper 3B);无后端时 reaction 解析留空并计事件,不阻塞主链。

### 4.2 Pipeline 形态(目标)

```
PDF
 → Extract
 → Markdown   (现有: 分子+ESMILES;强化: Idt-Map 把 bold 编号挂到 molecule crop)
 → Activity
 → [NEW] Reaction      ← RNXID 家族:图侧 RxnDP(IdtVP) + 文本侧 Idt-TE,标识符对齐
 → Persist    (现有 molecule/activity;新增 reaction 实体+标识符 join 索引)
```

- `ReactionStage` 置于 Activity 之后、Persist 之前:可复用 Markdown 的 crop/bbox 与 Activity 的页面文本,把 reaction 中 Idt 组件 resolve 成 molecule/activity 引用。
- 文本侧子流程 **Idt-TE 可与 ActivityStage 并行**(都吃 document.md),仅以标识符做最终对齐,避免顺序耦合。

### 4.3 数据模型(草案)

沿用 `{library_root}/.mbforge/library.db`(unified)。新增表:

```
reactions(doc_id, rxn_idx, page, bbox, role_sources JSON, review_status, evidence...)
reaction_components(rxn_id, slot[reactant|product|condition|reagent], kind[Idt|Mol|Txt],
                    identifier, molecule_id FK?, text, bbox, amount/yield...)
标识符 join 索引: identifier ↔ molecule_candidate_id ↔ activity_row_id(替代 page-proximity)
```

参考 MinerU.Chem Reaction Summary List 字段集(reactants/products/conditions + 回链 molecule 记录);RNXID 输出 JSON(reactions[] 见论文 Fig.1)作为原始 evidence 落 `report.json` 同构扩展。

### 4.4 后端组织(镜像现有模式)

```
backends/rxnid/
  midmapper.py     # 图像侧:输入 molecule crops+page → 输出 {bbox→identifier}(本地 Qwen2.5-VL-3B INT4 或云端)
  rxndp.py         # 反应图解析:IdtVP 提示词管线 → reactions[] JSON(可空实现=无后端)
  idt_te.py        # 文本侧:级联 4 步 LLM 抽取(复用 infra/llm 的 ChatOpenAI 客户端与 pacing/concurrency 边界)
```
配置键(沿 `AppConfig` 模式,进 settings UI):`reaction.enabled`、`reaction.image_backend`(none/midmapper/cloud)、`reaction.text_backend`、`reaction.max_concurrency` 等。对等现有 `llm.activity_max_concurrency` 等既有约束模式。

### 4.5 ESMILES/Markdown 风格一致

反应块仿现有 ` ```esmiles ``` ` block + `%% page=` / `%% candidate=` 注释头机制(`esmiles_insert.py:_format_esmiles_block`),新增 ` ```reaction ``` ` block + `%% page=/%% rxn=` 头,保证可回溯与文档内一致性。

---

## 5. 落地路径(三档,可裁剪)

| 阶段 | 内容 | 依赖 | 工作量量级 |
|---|---|---|---|
| **L0 文本侧先行** | 移植 Idt-TE 为文本 reaction 抽取(仅 LLM,零新模型):复用现有 llm 配置,产出 reaction 候选入 review | 无模型依赖;论文 Table 9–12 已给出完整 prompt | 小(先做) |
| **L1 图像侧接入** | (a) 验证通道:MinerU.Chem 在线服务/MinerU 平台 Chemistry 模式 or Gemini 零样本 IdtVP;(b) 本地 Mid-Mapper(3B INT4,3070 Ti)替代云端标识符映射 | 需要 VL 端点;3B 模型权重量化后 ~2–3 GB VRAM | 中 |
| **L2 自托管 RxnDP** | 等 RNXID 开源(或重训)后在本地 7B VL INT4 跑完整反应解析;ScannedRxn 数据用于评估鲁棒性 | 开源 release 或训练预算 | 视 release |

建议顺序 **L0 → L1a → L1b → L2**,每档独立可交付、可开关。

---

## 6. 风险与开放问题

| 项 | 说明 | 缓解 |
|---|---|---|
| RNXID 未开源 | 论文仅承诺 "will release";代码/权重/数据尚不可得 | L0 的 Idt-TE 有完整 prompt 可立即实现;L1a 用在线服务;Mid-Mapper 蒸馏自 Gemini,可自行蒸馏 |
| 8 GB VRAM 上限 | 7B+ VL 推理 INT4 可行但 RxnDP 零样本质量(论文 7B 仅 16.7 Hybrid-F1)远逊闭源 | 图像侧默认走云端;本地只跑 Mid-Mapper |
| IdtVP 需在图上绘制编号 | 无标识符分子需先赋虚拟 id 并画上去(Ink-Aware 渲染) | L1 内置画框/编号工具,输入复用现有 crop 渲染(200 DPI) |
| 数据模型演进 | reaction 表是 MBForge 首个"图源结构化实体",需与 Markush review 门一致 | 先落 review queue 再 confirm,遵循 role gate 先例 |
| 重复/冲突标识符 | 全 doc 唯一性约束是跨模态对齐前提 | Mid-Mapper 赋 id 后做冲突检测,冲突进 review |
| 与 MinerU.Chem 定位重叠 | 若 MBForge 未来整体改用 MinerU.Chem 做后处理层,本设计可对齐其 Summary List 数据契约 | 4.3 字段集已按其对齐 |

---

## 7. 参考

- RNXID: *Molecular Identifier Visual Prompt and Verifiable Reinforcement Learning for Chemical Reaction Diagram Parsing*, arXiv:2603.15011v2(`ref/RNXID.pdf`)
- MinerU.Chem: arXiv:2608.03525v3(`ref/MinerUChem.pdf`)
- MBForge: `docs/wiki/pipeline.md`、`docs/wiki/esmiles.md`、`src/mbforge/pipeline/`
