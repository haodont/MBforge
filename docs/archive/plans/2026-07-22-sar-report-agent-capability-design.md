# Agent SAR 分析能力设计方案

**日期**: 2026-07-22
**状态**: 设计稿（待评审）
**目标**: 让 `mbforge.agent` 能在用户给出一份专利/文献后，自主调度工具链产出结构-活性关系（SAR）分析报告，对标"诺华 STAT6 专利"那种 13 页样式的深度分析。

---

## 1. 背景与动机

### 1.1 现象

项目里 `src/mbforge/routers/sar.py` 已有 4 个端点（`find-scaffold` / `decompose` / `build-matrix` / `heatmap`），但全部是 Phase 0 stub，统一返回 `success:false`。前端 `frontend/src/components/sar/` 已经画好 `OverviewTab` / `RGroupTab` / `CliffsTab` / `RGroupMatrix` / `HeatmapPanel` / `MatrixTable` / `CompoundCard` 等组件，UI 框架在等数据。

用户拿出"诺华 WO2026/139841 A1（STAT6 芳香甲酰胺类化合物）"那份 13 页 PDF 样例来对照 —— 这是行业里标准的 SAR 分析报告样式，agent 目前完全无法产出。

### 1.2 现状盘点

**已经具备的（埋好但未连通）**：

| 模块 | 现状 | 路径 |
|---|---|---|
| 分子检测 | `moldet_v2_ft.py` 能从 PDF 图里框出分子 | `src/mbforge/backends/moldet_v2_ft.py` |
| 结构识别 | `molscribe.py` 把分子图转 SMILES | `src/mbforge/backends/molscribe.py` |
| 结构分类 | `classify_structure_role.py` 区分 complete/fragment/scaffold/Markush | `src/mbforge/pipeline/classify_structure_role.py` |
| 活性抽取 | `extract_activities.py` LLM 抽 IC50/Ki，含 row_label/row_smiles/page_num | `src/mbforge/pipeline/extract_activities.py` |
| Markush 表 | `markush_scaffolds` / `markush_fragments` 已建好 | `src/mbforge/core/database.py` |
| 分子库 | `molecules` 表有单值 `activity` 字段 | `src/mbforge/core/database.py` |
| Agent 框架 | LangGraph ReAct + 5 个基础工具 | `src/mbforge/agent/` |
| 前端 SAR UI | 7 个组件已就位，等数据 | `frontend/src/components/sar/` |

**当前 agent 5 个工具**：

```python
# src/mbforge/agent/tools.py:315
get_all_tools() → [
    kb_search,                 # 文档段落级搜索
    molecule_search,           # SMILES/名称匹配
    get_document_content,      # 文档页文本
    compute_molecule_properties,  # RDKit 算 MW/LogP/TPSA
    list_project_documents,    # 文档列表
]
```

**关键缺口**（按影响报告段落排序）：

1. ❌ **没有 `activities` 表** —— 现有 `molecules.activity` 是单值字段，SAR 报告需要 "分子 × 靶点 × 试验方法" 的多维数据
2. ❌ **抽取的活动数据没落库** —— `extract_activities` 跑完只返回 list，没有持久化
3. ❌ **没有 R-group 分解** —— RDKit `ReplaceCore` 没人调
4. ❌ **没有 MCS / Bemis-Murcko 母核提取** —— 找"公共骨架"的核心算法缺失
5. ❌ **没有结构相似度** —— Tanimoto on Morgan FP 没封装
6. ❌ **没有活性悬崖配对** —— 谁跟谁差多少倍没算法
7. ❌ **没有分子 SVG / 区域高亮渲染** —— 报告里的彩色 R1-R5 区域图无生成器
8. ❌ **agent 不知道有 SAR 这件事** —— system prompt 没引导，工具集不含 SAR 工具

### 1.3 设计目标

| 阶段 | 交付 | 阻塞/依赖 |
|---|---|---|
| P0 | `activities` 表 + 持久化 + 2 个查询工具 | 全部后续阶段的前置 |
| P1 | R-group 分解 + MCS + scaffold 聚类 | 报告 1、4 段 |
| P2 | Tanimoto + 活性悬崖 + diff SVG | 报告 3 段 |
| P3 | agent 端到端串联 + SAR 报告 prompt 模板 | 全流程跑通 |
| P4 | 用 Novartis 53 化合物 PDF 做金标准回放测试 | 验收 |

P0 完成后立即可见的价值：`molecule_search` 返回的每条化合物可以附带其全部活性记录；现有 pipeline 抽完 IC50 数据会真的落库。

---

## 2. SAR 报告结构（对标样本）

样本：诺华 WO2026/139841 A1 "AROMATIC CARBOXAMIDE COMPOUNDS AND METHODS OF USING THEREOF"，53 个化合物，2 个 assay（hSTAT6 TR-FRET / HaCaT hSTAT6 GFP）。

| 段 | 标题 | 关键产物 | 依赖 |
|---|---|---|---|
| 0 | 专利头 | WO 号 / 药企 / 公开日 / 优先权 / IPC 分类 | KB search 即可凑齐（前期），未来可加专利专用工具 |
| 1 | 一、结构药效关系总览 | 参考分子 SMILES + R1-R5 染色区域 + 每个 R-位点卡片 | R-group 分解 + 区域高亮渲染 |
| — | 核心结论 | 4 条带 fold-change 的总结 | 跨区域聚合 + LLM 总结 |
| 2 | 二、活性分布 | 两个 assay 维度的直方图（≤30/30-50/50-100/100-300/>300 nM） | bin 聚合 + 前端图表 |
| 3 | 三、活性悬崖 | 配对：结构差异名 + 倍数差 + Tanimoto 相似度 | Tanimoto + 配对排序 + diff SVG |
| 4 | 四、关键母核系列 | 母核聚类，每簇带 N 个成员 + 系列内差异 | Bemis-Murcko + 簇内排序 |
| 5 | 五、优先关注化合物 | Top-N 排序卡片 | 跨 assay 综合排名 |
| 6 | 六、推荐设计策略 | "推荐 / 规避 / 设计依据" 三段式 | 规则 + 证据反查 + LLM 推理 |

---

## 3. P0 详细设计 —— 数据底座

### 3.1 目标

1. 新建 `activities` 表，支持多靶点 × 多试验方法
2. `extract_activities` 跑完直接落库
3. agent 加 2 个查询工具：`list_activities` / `get_compound_activities`
4. 现有 5 个工具的能力不降级，向后兼容

### 3.2 非目标（P0 范围外）

- R-group 分解（→ P1）
- 母核聚类 / 活性悬崖（→ P1、P2）
- 报告生成 / agent 端到端（→ P3）
- 旧数据回填（P0 不做，提供一次性脚本放 P4 之后）

### 3.3 schema 改动

新增表：

```sql
-- 每个分子 × 每个靶点 × 每个试验方法 = 一行
CREATE TABLE IF NOT EXISTS activities (
    activity_id TEXT PRIMARY KEY,
    mol_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,    -- IC50 / Ki / EC50 / Kd / ED50
    value REAL NOT NULL,             -- 标准化到 nM
    value_original REAL,             -- 原始值
    unit_original TEXT,              -- nM / μM / mM
    operator TEXT DEFAULT '=',
    target TEXT,                     -- 蛋白/酶名
    assay_type TEXT,                 -- enzymatic / cellular / binding
    assay_description TEXT,          -- "hSTAT6 TR-FRET" / "HaCaT hSTAT6 GFP"
    confidence REAL,
    page_num INTEGER,
    table_idx INTEGER,
    row_idx INTEGER,
    col_idx INTEGER,
    row_label TEXT,
    row_smiles TEXT,
    raw_text TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id)
);
CREATE INDEX IF NOT EXISTS idx_act_mol ON activities(mol_id);
CREATE INDEX IF NOT EXISTS idx_act_doc ON activities(doc_id);
CREATE INDEX IF NOT EXISTS idx_act_target ON activities(target);
CREATE INDEX IF NOT EXISTS idx_act_assay ON activities(assay_description);
CREATE INDEX IF NOT EXISTS idx_act_row ON activities(doc_id, table_idx, row_label);
```

**关于 `molecules.activity`**：保留作为"主活性"便利字段（多数分子只有一条主 IC50），但**新代码必须读写 `activities` 表**。`molecule_service.search_molecules` 返回时可 join `activities` 把完整记录带出来。

### 3.4 持久化层

新建 `src/mbforge/pipeline/persist_activities.py`：

```python
def persist_activities(library_root, doc_id, records: list[ActivityRecord]) -> int:
    """把 ActivityRecord 列表写入 activities 表，跳过无 mol_id 的记录。返回写入条数。
    
    Idempotent: 用 (mol_id, doc_id, activity_type, target, assay_description, value)
    复合键做 UNIQUE 防止重复落库。
    """
```

并在 `pipeline/runner.py` 的 `STAGES` 注册表里挂上，跑在 `extract_activities` 之后。

### 3.5 agent 新增工具

在 `src/mbforge/agent/tools.py` 末尾追加：

```python
async def list_activities(
    doc_id: str,
    target: str = "",
    assay_description: str = "",
    config: RunnableConfig,
) -> str:
    """List activities for a document, optionally filtered by target/assay.

    Args:
        doc_id: Document identifier
        target: Protein/enzyme name (e.g. "STAT6", "EGFR"); empty = all
        assay_description: Assay name (e.g. "hSTAT6 TR-FRET"); empty = all
    """

async def get_compound_activities(
    query: str,                    # SMILES / 化合物名 / mol_id
    config: RunnableConfig,
) -> str:
    """Get all activities (any target/assay) for a single compound.

    Args:
        query: SMILES, compound name, or mol_id
    """
```

`get_all_tools()` 把这两个加进去（不要破坏现有 5 个）。

### 3.6 验收标准

1. 喂入 Novartis WO2026/139841 PDF（或任意带活性表格的文献），跑完整 pipeline：
   - `activities` 表里 53 个化合物 × 2 个 assay = 106 条记录
   - `molecule_search("化合物 66")` 返回的 JSON 包含 `hSTAT6 TR-FRET 4 nM; HaCaT hSTAT6 GFP 6 nM`
2. agent 在 chat 里被问"这份专利里活性最好的化合物是什么"，能调 `list_activities` 排序后给出答案
3. 现有 5 个工具的所有现有测试仍然通过
4. 新增 `tests/unit/agent/test_sar_tools.py` 覆盖 `list_activities` / `get_compound_activities` 的核心路径
5. 新增 `tests/unit/pipeline/test_persist_activities.py` 覆盖落库和幂等

### 3.7 涉及文件

| 操作 | 路径 |
|---|---|
| 改 | `src/mbforge/core/database.py` —— 加 `activities` 表 DDL + 索引 |
| 改 | `src/mbforge/pipeline/runner.py` —— STAGES 加 `persist_activities` |
| 改 | `src/mbforge/pipeline/persist_activities.py` —— 新建 |
| 改 | `src/mbforge/core/molecule_service.py` —— `search_molecules` join `activities` 暴露完整记录 |
| 改 | `src/mbforge/agent/tools.py` —— 加 2 个工具 + 加进 `get_all_tools` |
| 改 | `src/mbforge/agent/graph.py` —— system prompt 加一行说明新工具 |
| 增 | `tests/unit/pipeline/test_persist_activities.py` |
| 增 | `tests/unit/agent/test_sar_tools.py` |
| 改 | `docs/api/README.md` —— 加 `activities` 相关端点说明（如有） |

---

## 4. P1 简述（详细设计另起文件）

| 工具 | 算法 | 落点 |
|---|---|---|
| `find_common_scaffold` | RDKit `FindMCS` + Bemis-Murcko fallback | `src/mbforge/agent/tools.py` |
| `decompose_to_rgroups` | RDKit `ReplaceCore` 拆 R1..R5 | 同上 |
| `cluster_by_scaffold` | Bemis-Murcko 聚类 + 簇内排序 | 同上 |
| 解 stub | `routers/sar.py` 4 个端点改真实现 | `src/mbforge/routers/sar.py` |

## 5. P2 简述

| 工具 | 算法 |
|---|---|
| `find_activity_cliffs` | Tanimoto on Morgan FP + 按 \|ΔpIC50\| 排序 |
| `activity_distribution` | bin 聚合（默认 5 档：≤30/30-50/50-100/100-300/>300 nM） |
| `render_molecule_svg` | RDKit `Draw.MolToImage` + 高亮 atom indices |
| `render_structure_diff_svg` | 找两分子 MCS，非共享区用不同色高亮 |

## 6. P3 简述

- `graph.py` 的 system prompt 改成"对一份专利做 SAR 分析时，按以下步骤调工具……"
- 加 `core/sar_report.py`：给定 doc_id，自动跑 P0-P2 全套工具，组装成报告结构化 JSON
- agent 加 `generate_sar_report(doc_id)` 顶层工具，把上面的 JSON 喂给 LLM 出 Markdown

## 7. P4 验收

- 拿 Novartis WO2026/139841 的 53 化合物做 fixture
- 跑端到端，验证：
  - 报告 1 段能识别出 R1-R5 五个区域
  - 报告 3 段能挑出 79→82、92→82、100→94、100→96 四对活性悬崖
  - 报告 4 段能聚出母核 01-06 六个簇
  - 报告 5 段能排出 Top 6 化合物

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| LLM 抽活性表格准确率 ~70% | 数据源噪音大 | P0 加 confidence 字段；前端按 confidence 过滤；Phase 0 roadmap 已声明"85-90% 准确率 + 人工校验" |
| RDKit MCS 在大分子集上慢 | 报告生成超时 | P1 加超时（30s）+ 缓存（`semantic_cache.py` 已有） |
| 母核聚类对 Markush 失效 | 报告 4 段漏簇 | P1 用 `classify_structure_role` 过滤掉 scaffold/fragment，只对 complete 聚类 |
| 现有前端 SAR 组件接口不对 | 解 stub 后 UI 不显示 | P3 前先用 Swagger 触发端点人工核对 JSON 结构 |
| 53 化合物级回归测试 fixture 制作贵 | P4 推迟 | P0-P2 用 5-10 个分子的合成 fixture 测，P4 再做全量 |

---

## 9. 决策点（评审时需确认）

| # | 决策 | 候选 | 推荐 |
|---|---|---|---|
| D1 | `activities` 表主键 | UUID / `(mol_id, target, assay_description, value)` 复合 | 复合（更利于去重） |
| D2 | `molecules.activity` 旧字段 | 保留 / 弃用 | 保留作"主活性"便利字段 |
| D3 | P0 是否同步改 molecule_service 返回结构 | 改 / 延后到 P1 | 改（影响前端 + 立即可见价值） |
| D4 | agent system prompt 改的位置 | `graph.py` 常量 / 数据库配置 | 沿用现有 `_SYSTEM_PROMPT` 常量 |
| D5 | 是否解 `sar.py` stub 推后 | P0 一起 / P1 才解 | P0 不解，避免 scope creep；P1 解 find-scaffold + decompose |
