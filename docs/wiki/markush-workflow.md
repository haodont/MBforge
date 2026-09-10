# Markush 工作流

MBForge 的 Markush 功能支持专利化学中的通用结构（Markush 结构）管理、覆盖匹配和受控枚举。

## 概述

Markush 结构是化学专利中用于描述一系列化合物的抽象表示，通常包含：

- **Scaffold（骨架）**：核心结构，带有 R-group 占位符（如 `[*:1]`, `[*:2]`）
- **Fragment（片段）**：可在特定位点替换的 R-group 定义
- **Attachment sites（连接位点）**：标记了 atom-map 的替换位置

**示例**：专利 Formula I 可能定义为：

```
Core: [*:1]C1CCC([*:2])([*:3])C1[*:4]
R1: H, CH3, CF3
R2: OH, NH2
R3: H, Cl
R4: phenyl, pyridyl
```

## 工作流阶段

### 1. 自动检测和分类

PDF 导入时，MBForge 管道自动识别潜在的 Markush 结构：

- 包含 dummy atoms (`*`) 的 SMILES
- 带有 "Formula I"、"R₁" 等标签的结构
- 上下文含有 "wherein"、"is selected from" 等专利术语

**分类原因码**（Phase 0 标签规范化）：

- `context_markush_keyword` — 上下文含 Markush 关键词
- `context_generic_formula` — 标签为 "Formula I/II" 等
- `context_formula_label` — 标签含 R-group 编号
- `dummy_atom_scaffold` — 结构含多个 dummy atoms
- `dummy_atom_fragment` — 结构含单个 dummy atom

候选进入 **审查队列**（`markush_review_candidates` 表），状态为 `pending`。

### 2. 人工审查

**审查 UI**（Phase 3）提供三列布局：

```
┌───────────────┬──────────────────────┬──────────────────────┐
│ 审查队列       │ 结构和原始证据         │ 审查/修正面板          │
│               │                      │                      │
│ pending 12    │ crop vs RDKit        │ predicted: scaffold  │
│ scaffold 4    │ PDF page 8           │ Formula I            │
│ fragment 7    │ nearby text          │ [确认骨架]            │
│ orphan 3      │ all detections       │ [具体分子] [驳回]      │
└───────────────┴──────────────────────┴──────────────────────┘
```

**审查动作**（Phase 2 API）：

- **confirm_scaffold** — 确认为 Markush 骨架（进入 `markush_scaffolds`）
- **confirm_fragment** — 确认为 R-group 片段（进入 `markush_fragments`）
- **confirm_complete** — 确认为完整分子（进入 `molecules`）
- **reject** — 驳回（识别错误、低质量）
- **reopen** — 重新打开已确认的决定

审查决策写入 `markush_decisions` 审计表，支持乐观锁（`expected_version`）。

### 3. Attachment Site 建模

**Phase 4** 引入显式位点关联：

确认为 scaffold 后，系统要求：

1. **解析 atom-map**：`[*:1]`, `[*:2]` 等必须显式标注
2. **创建 sites**：每个 `[*:N]` 生成一个 `markush_sites` 行
3. **定义 R-group options**：人工或 LLM 辅助添加每个位点的可用片段

**Site 编辑器 UI**（`SiteEditor.tsx`）：

```
Site R1 [*:1]
  ├─ Options: 3 defined
  │   ├─ H (fragment_id: frag-001)
  │   ├─ CH3 (fragment_id: frag-002)
  │   └─ CF3 (fragment_id: frag-003)
  └─ Mounts: 2 suggested, 0 confirmed
```

**挂载建议**（`markush_mounts` 表）：

- `origin = coref` — 标签共现（如 R1 标签同时出现在 scaffold 和 fragment 附近）
- `origin = text_definition` — LLM 从文本抽取的定义关联
- `origin = proximity` — 仅页面距离（不自动确认）
- `origin = manual` — 用户手动关联

### 4. 覆盖匹配

**Phase 5** 实现 `POST /api/v1/chem/markush-check`：

检查具体分子是否在 Markush 定义范围内：

```http
POST /api/v1/chem/markush-check
{
  "scaffold_id": "scaffold-abc123",
  "query_smiles": "C1CCC(C)(O)C1c2ccccc2"
}
```

**响应**：

```json
{
  "match_level": "full",
  "core_overlap_ratio": 1.0,
  "site_results": [
    {"site_label": "R1", "judgment": "within_scope", "matched_option": "H"},
    {"site_label": "R2", "judgment": "within_scope", "matched_option": "OH"},
    {"site_label": "R4", "judgment": "within_scope", "matched_option": "phenyl"}
  ]
}
```

**match_level 枚举**：

- `full` — 核心匹配且所有取代基在定义内
- `partial` — 核心匹配但部分取代基超范围
- `scaffold_only` — 仅核心匹配，取代基未定义
- `none` — 核心不匹配
- `unknown` — 定义不完整，无法判断

**三态判断**（避免假阴性）：

- `within_scope` — 明确在定义内
- `outside_scope` — 明确超出定义
- `unknown` — 定义缺失或无法结构化（自然语言描述）

### 5. 受控枚举

**Phase 6** 实现有界枚举 `POST /api/v1/markush/enumeration/run`：

从 scaffold + site selections 生成具体分子组合：

```http
POST /api/v1/markush/enumeration/preview
{
  "scaffold_id": "scaffold-abc123",
  "selection": [
    {"site_label": "R1", "atom_map_num": 1, "fragments": ["frag-001", "frag-002"]},
    {"site_label": "R2", "atom_map_num": 2, "fragments": ["frag-010"]}
  ]
}
```

**响应**：

```json
{
  "theoretical_count": 2,
  "preview": ["CC1CCC(C)(O)C1", "C1CCC(C)(O)C1"]
}
```

**执行枚举**：

```http
POST /api/v1/markush/enumeration/run
{
  "scaffold_id": "scaffold-abc123",
  "selection": [...],
  "requested_limit": 1000
}
```

生成产物写入 `markush_generated_candidates`，状态 `review_status = pending`。

**入库规则**：

- 枚举产物**不自动**进入 `molecules` 表
- 用户必须通过 `POST /api/v1/markush/generated/decide` 明确确认
- `action = confirm` 将产物提升至 `molecules`，并保留谱系（`run_id`、`scaffold_id`、组合键）

**约束**：

- 超过 `requested_limit` 时拒绝执行（不生成部分结果）
- 同一 `(run_id, combination_key)` 唯一（幂等）
- RDKit sanitize 失败记录在 `validation_status`

## 数据模型

### Schema 演进

| Version | Phase | 新增表 |
|---------|-------|--------|
| v11 | 1 | `markush_review_candidates`, `markush_evidence`, `markush_decisions` |
| v12 | 4 | `markush_sites`, `markush_options`, `markush_mounts` |
| v13 | 4 | (索引优化) |
| v14 | 6 | `markush_generation_runs`, `markush_generated_candidates` |

### 核心表关系

```
markush_review_candidates
    ├─ markush_evidence (多个检测框)
    └─ markush_decisions (审计记录)

确认后 →
    markush_scaffolds
        ├─ markush_sites
        │   ├─ markush_options (R-group 定义)
        │   └─ markush_mounts (fragment 关联)
        └─ markush_generation_runs
            └─ markush_generated_candidates

    markush_fragments
        └─ markush_mounts (反向关联到 sites)
```

### 重导入保护

**source_key** 机制（Phase 1）：

```python
source_key = f"{doc_id}|{page}|{quantized_bbox}|{normalized_label}"
```

- 相同 `source_key` + 相同 `content_hash` → 保留人工状态
- 相同 `source_key` + 不同 `content_hash` → 旧行标记 `superseded_at`，新行进入 `pending`
- 新 `source_key` → 新候选

## API 端点

### 审查队列

```http
POST /api/v1/markush/list
POST /api/v1/markush/get
POST /api/v1/markush/decide
POST /api/v1/markush/update
```

### Attachment Sites

```http
POST /api/v1/markush/sites/create
POST /api/v1/markush/sites/list
POST /api/v1/markush/options/create
POST /api/v1/markush/mounts/create
POST /api/v1/markush/mounts/decide
```

### 化学操作

```http
POST /api/v1/chem/markush-parse
POST /api/v1/chem/markush-check
```

### 枚举

```http
POST /api/v1/markush/enumeration/preview
POST /api/v1/markush/enumeration/run
POST /api/v1/markush/enumeration/results
POST /api/v1/markush/generated/decide
```

## 可观测性

**未来/尚未集成：结构化事件契约**

`markush_events.py` 已归档至 [`docs/archive/code/markush/markush_events.py`](../archive/code/markush/markush_events.py)，不是当前运行时的 Phase 12 实现。以下事件名称仅作为未来集成时的计划契约；当前不会写入结构化 Markush 事件日志：

- `markush_candidate_created`
- `markush_candidate_superseded`
- `markush_decision_applied`
- `markush_role_transitioned`
- `markush_mount_suggested`
- `markush_mount_confirmed`
- `markush_match_completed`
- `markush_generation_rejected`
- `markush_generation_completed`
- `markush_generated_promoted`

**未来 Pipeline 报告契约（尚未集成）**：

```json
{
  "markush": {
    "review_pending": 3,
    "scaffolds": 2,
    "fragments": 7,
    "unmounted_fragments": 4,
    "definition_extraction_errors": 1
  }
}
```

## 历史数据迁移

**脚本**（Phase 10）：

```bash
uv run python scripts/migrate_markush_review_data.py \
  --library-root ~/Documents/MyLibrary \
  --dry-run

# 验证无误后执行
uv run python scripts/migrate_markush_review_data.py \
  --library-root ~/Documents/MyLibrary \
  --apply
```

迁移内容：

- 旧 `markush_scaffolds` / `markush_fragments` → `markush_review_candidates`
- `storage/{doc_id}/report.json` 中的 `molecule_review_candidates` → 审查队列
- 自动生成 `source_key`、补全 `markush_evidence`
- 备份数据库（`library_backup_{timestamp}.db`）

## 限制

**暂不支持**：

- 法律意义上的专利权利要求判断
- 无限制全组合枚举（需显式 `requested_limit`）
- 自动根据页面距离确认 fragment 挂载（需人工审查）
- LLM 直接生成化学键（仅辅助文本定义抽取）
- 自动将枚举产物加入正式分子库（需显式 `confirm`）

## 参考

- [Pipeline stages](pipeline.md)
- [HTTP API](../api/README.md)
- [Architecture and code rules](architecture.md)
