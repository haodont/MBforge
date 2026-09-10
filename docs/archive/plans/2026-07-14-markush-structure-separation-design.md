# Markush / R-基结构与正式分子分流设计

**日期**: 2026-07-14  
**状态**: 设计稿（评审收敛后），可写实现计划  
**目标**: Phase A 只完成「分类 + 主库降噪 + 落 markush 表 + 测试」，API / UI / promote / 挂载全部推迟到 Phase B。

---

## 1. 背景与问题

### 1.1 现象

PDF 管线（MolDetv2-FT → MolScribe → `normalize_molecules` → `persist_molecule_candidates`）会把下列结构**一律**写入 `molecules` 主表：

| 类型 | 专利示例 | 当前行为 | 期望 |
|---|---|---|---|
| 正式化合物 | E002 + NMR/LCMS 完整结构 | 入库 | 主库保留 |
| Markush 母核 | Formula I（含 R1/R2/A/W） | 入库 | **不进主库** |
| R/A 定义片段 | A1 环系 + 连接点 `{ }` + R4 | 入库 | **不进主库** |

结果：主库充斥连接点片段与变量骨架，列表杂乱，SAR/检索噪音大。

### 1.2 根因（代码现状，已验证）

- 提取路径：`MarkdownStage` → `extract_molecules_from_pdf` → `normalize_molecules` → `PersistStage` / `persist_molecule_candidates`。
- `normalize.py` **故意保留** `*`（Markush 通配原子），且无 `role` / `is_fragment` 分类。
- `persist_molecules.py` 对非 `rejected` 候选一律 upsert `molecules`。
- `evidence.role` 硬编码 `'detected'`；本期保持不动。
- 分子库 UI 无 Markush/R-基过滤。

### 1.3 设计决策

| 决策点 | 选择 |
|---|---|
| 分类依据 | **纯 SMILES / RDKit**，不引入上下文文本、不上 LLM |
| fragment 判定 | 含 dummy 原子 + 重原子数 ≤ 18；单连接点可 bonus 到 24 |
| scaffold 判定 | 含 dummy 原子但不够 fragment 条件 |
| 挂载 | Phase A **不挂载**，`scaffold_id = NULL` |
| promote/demote | Phase B 再做 |
| API / UI | Phase B 再做 |
| molecules 表 | **不加 role 列**；主库语义 = 只存 complete |
| evidence.role | 保持 `'detected'` 不变 |
| 历史数据 | Phase A 不迁移；Phase B 可选脚本 |

---

## 2. 目标与非目标

### 2.1 目标（Phase A）

1. 主库 `molecules` **仅**写入判定为 `complete` 的具体化合物（表上不加 `role` 列）。
2. `scaffold` / `fragment` 落入新表 `markush_scaffolds` / `markush_fragments`。
3. 分类器只依赖 SMILES / RDKit，运行稳定、可单测。
4. persist 路径不跨表迁移，只按 role 分流写入。
5. 单元测试覆盖分类规则与分流逻辑。

### 2.2 非目标（Phase A）

- 训练/部署专用结构分类模型。
- 使用上下文文本、caption、LLM。
- fragment → scaffold 自动挂载。
- promote / demote 角色迁移。
- Markush 列表 UI / 路由 API。
- 历史库清理。
- 更新 router smoke 测试（留到 Phase B）。

### 2.3 成功标准

投喂同时含 Formula I、A1 定义列表、E002 正式化合物的专利 PDF：

1. 主库列表只有 E002 类完整分子（无 A1 环系、无 Formula I）。
2. `markush_scaffolds` / `markush_fragments` 有对应记录（scaffold_id 为空）。
3. `pytest` 相关单测通过。
4. pipeline report.json 含 role 计数。

---

## 3. 角色模型

三档角色，在 persist 前决定：

```
role ∈ { complete, scaffold, fragment }
```

| role | 语义 | 存储 |
|---|---|---|
| `complete` | 具体、封闭、无 dummy 原子的化合物 | `molecules` + 现有 evidence / detections |
| `scaffold` | 带变量位点的 Markush 母核 / Formula | `markush_scaffolds` |
| `fragment` | R 基、A 环系、连接点侧链定义 | `markush_fragments`（`scaffold_id = NULL`） |

`rejected` 仍走现有 `normalize` 拒绝路径，**不**进入上述三档。

---

## 4. 分类规则

分类在 `normalize_molecules` 之后、persist 之前执行。  
新增纯函数模块 `pipeline/classify_structure_role.py`，便于单测。

输入：`NormalizedMolecule`（`canonical_smiles` / `esmiles`；**不**假定已缓存 RDKit mol —— 分类器内 `MolFromSmiles` 重解析）。

输出：在 `NormalizedMolecule.properties` 中写入 `"structure_role"`（本期先放 properties，后续可提升为 dataclass 字段）。

### 4.1 信号定义

```python
DUMMY_SYMBOLS = {"*"}
FRAGMENT_MAX_HEAVY = 18
FRAGMENT_SINGLE_ATTACH_BONUS = 6   # 单连接点时可放宽到 24
```

- `has_dummy`：RDKit mol 中存在 `a.GetSymbol() == "*"` 或 `a.GetAtomicNum() == 0` 的原子。
- `attachment_count`：dummy 原子数量。
- `heavy_atoms`：`mol.GetNumHeavyAtoms()`。

### 4.2 短路顺序

**Step 0 — 已 rejected**  
保持 `rejected`，跳过。

**Step 1 — fragment**

```
has_dummy
AND (
    heavy_atoms <= FRAGMENT_MAX_HEAVY
    OR (
        attachment_count == 1
        AND heavy_atoms <= FRAGMENT_MAX_HEAVY + FRAGMENT_SINGLE_ATTACH_BONUS
    )
)
→ fragment
```

**Step 2 — scaffold**

```
has_dummy AND not fragment
→ scaffold
```

**Step 3 — complete**

```
not has_dummy
→ complete
```

### 4.3 边界示例

| 输入 | 期望 role |
|---|---|
| E002 封闭结构 | `complete` |
| Formula I + 多个 `*` | `scaffold` |
| A1 噻唑环 + 单 `*` + ≤18 重原子 | `fragment` |
| 单 `*` 大侧链（24 重原子） | `fragment`（单连接点 bonus） |
| 双 `*` 中等结构（20 重原子） | `scaffold` |

### 4.4 稳定性

分类器自身永不抛异常。任何 RDKit 异常或空 mol 直接返回 `fragment`（激进兜底），并记 warning log。

---

## 5. 数据模型

### 5.1 新表（library.db / mol schema，版本 v6）

```sql
CREATE TABLE IF NOT EXISTS markush_scaffolds (
    scaffold_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    formula_label TEXT DEFAULT '',          -- 预留，Phase A 可空
    smiles TEXT NOT NULL,                    -- canonical / raw
    esmiles TEXT,
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending',           -- pending|confirmed|rejected
    properties TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ms_doc ON markush_scaffolds(doc_id);
CREATE INDEX IF NOT EXISTS idx_ms_status ON markush_scaffolds(status);

CREATE TABLE IF NOT EXISTS markush_fragments (
    fragment_id TEXT PRIMARY KEY,
    scaffold_id TEXT DEFAULT NULL,           -- Phase A 始终 NULL
    doc_id TEXT NOT NULL,
    label TEXT DEFAULT '',                   -- 预留，Phase A 可空
    smiles TEXT NOT NULL,
    esmiles TEXT,
    page INTEGER,
    bbox_x0 REAL, bbox_y0 REAL, bbox_x1 REAL, bbox_y1 REAL,
    crop_relpath TEXT,
    confidence REAL,
    status TEXT DEFAULT 'pending',
    properties TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (scaffold_id) REFERENCES markush_scaffolds(scaffold_id)
);
CREATE INDEX IF NOT EXISTS idx_mf_doc ON markush_fragments(doc_id);
CREATE INDEX IF NOT EXISTS idx_mf_scaffold ON markush_fragments(scaffold_id);
CREATE INDEX IF NOT EXISTS idx_mf_status ON markush_fragments(status);
```

ID 生成：Phase A 使用 `uuid4().hex[:16]` 作为文本主键（与 `molecules.mol_id` 同为 TEXT PRIMARY KEY，但采用随机 ID 避免同一文档内重复 SMILES 的冲突）。

### 5.2 现有表改动

- `molecules`：**不写** scaffold/fragment，**不加 role 列**。
- `evidence.role`：保持 `'detected'` 不变。
- `schema_version`：从 **v5 → v6**，新增 `_migrate_molecules_v5_to_v6()` 建两表。

### 5.3 与 SAR 的关系

本期不改 SAR。后续 Phase B 可读 `markush_scaffolds` + `markush_fragments` 作为先验。

---

## 6. 管线改动

### 6.1 数据流

```
extract_molecules_from_pdf / text
        │
        ▼
normalize_molecules()           # 现有：canonical + reject
        │
        ▼
classify_structure_roles()      # 新增：写 structure_role
        │
        ▼
persist_stage
   ├─ role=complete  → persist_molecule_candidates()   # 现逻辑
   ├─ role=scaffold  → persist_markush_scaffolds()     # 新
   └─ role=fragment  → persist_markush_fragments()     # 新
```

`register_molecules_from_text` 仅处理 `complete`（已有 `rejected` skip；再 skip 非 complete）。

### 6.2 不自动挂载

Phase A 所有 fragment 的 `scaffold_id = NULL`。挂载、orphan 管理推迟到 Phase B。

### 6.3 事务

`PersistStage._persist_molecules_and_links` 同一 txn 内：

1. `DELETE FROM markush_scaffolds WHERE doc_id = ?`
2. `DELETE FROM markush_fragments WHERE doc_id = ?`
3. complete → molecules + detections + evidence + links
4. scaffold → `markush_scaffolds`
5. fragment → `markush_fragments`

任一步失败整 txn 回滚。这样同一文档重跑 ingest 会覆盖旧 markush 记录（与 detections 按 doc 覆盖语义对齐）。

文档级 persist 失败时的补偿（`_compensate_molecule_persistence`）须**扩展**：除 detections / evidence / links 外，删除该 `doc_id` 的 `markush_scaffolds` / `markush_fragments` 行，避免 DB 残留无文档产物。

### 6.4 report.json

在 pipeline report 中新增字段：

```json
{
  "structure_role_counts": {
    "complete": 12,
    "scaffold": 3,
    "fragment": 8
  }
}
```

---

## 7. 测试

| 层 | 内容 |
|---|---|
| unit | `classify_structure_role`：E002 / Formula I / A1 连接点 / 单连接点 bonus / 无 dummy → 期望 role |
| unit | `persist_markush_*`：complete 进 molecules；scaffold/fragment 进 markush 表，不进 molecules |
| unit | `database.py` migration v5→v6 后表存在、索引存在 |
| 可选 integration | 用预置 `ExtractionResult` 列表跑 markdown/persist stage，检查主库干净 |

不依赖真实 LLM / GPU。

---

## 8. 实现分期

### Phase A（本期必达）

1. DB schema v6 + `_migrate_molecules_v5_to_v6()` 建两表。
2. `pipeline/classify_structure_role.py` 纯函数分类器。
3. `pipeline/persist_markush.py`（或合并进 persist_stage）分流写入。
4. `pipeline/stages/persist_stage.py` 在事务内覆盖写 markush 表。
5. `pipeline/organizer.py` 的 `register_molecules_from_text` 跳过非 complete。
6. report.json `structure_role_counts`。
7. 单元测试覆盖分类与分流。

### Phase B（后续）

- `/api/v1/markush` router + promote/demote。
- fragment → scaffold 挂载启发式。
- Markush 列表 UI。
- 历史库清理脚本。
- router smoke / openapi snapshot 更新。

---

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 无 dummy 的噪声图（误检封闭垃圾）仍进主库 | Phase A 接受；Phase B 上下文/编号规则收紧 complete |
| 单 `*` 且重原子 >24 被标 scaffold | 不进主库即可；常量可调 |
| 双 `*` 小环（A1 两端连接）因 heavy≤18 进 fragment 而非 scaffold | Phase A 可接受（都不进主库）；Phase B 挂树时再区分 |
| MolScribe 把连接点读成普通原子 | 纯 SMILES 规则无法救；仍会进主库，留待 Phase B |
| 主库与 markush 双写不一致 | 同一事务、按 doc 覆盖；补偿删 markush |

---

## 10. 关键文件（预期触点）

| 文件 | 改动 |
|---|---|
| `src/mbforge/core/database.py` | schema v6、建表、迁移函数 |
| `src/mbforge/pipeline/classify_structure_role.py` | **新建** |
| `src/mbforge/pipeline/persist_molecules.py` | 仅 complete；其余跳过 |
| `src/mbforge/pipeline/persist_markush.py` | **新建**（或逻辑直接进 persist_stage） |
| `src/mbforge/pipeline/stages/persist_stage.py` | 分流 + 覆盖删除 |
| `src/mbforge/pipeline/organizer.py` | register 跳过非 complete |
| `src/mbforge/models/markush.py` | Phase A **可选**；无对外 API 时可直接 SQL/dict，Phase B 再加 Pydantic |
| `tests/unit/pipeline/test_classify_structure_role.py` | **新建** |
| `tests/unit/pipeline/test_persist_markush.py` | **新建** |
| `tests/unit/core/test_database.py` | 加 migration 断言 |

---

## 11. 验收清单

- [ ] 新 PDF：主库无 A1 连接点片段、无 Formula I。
- [ ] `markush_scaffolds` / `markush_fragments` 有对应记录，`scaffold_id` 为空。
- [ ] `pytest` 相关单测通过。
- [ ] report.json 含 `structure_role_counts`。
- [ ] 文档：本 spec + `docs/wiki/pipeline.md` 一句交叉引用（可选）。

---

## 12. 开放实现细节（writing-plans 阶段敲定）

1. `persist_markush` 独立模块 vs 直接写在 `persist_stage.py` 里（推荐独立模块，stage 只编排）。
2. 分类结果放 `properties["structure_role"]` 还是提升为 `NormalizedMolecule` 字段（Phase A 推荐 properties，少改 dataclass 调用面）。
3. report.json 字段名固定为 `structure_role_counts`（§6.4）。
4. classify 挂载点：markdown_stage 末 vs persist_stage 初（推荐 **persist 前单一入口**，stats 与落库一致）。
5. markush 主键：`uuid4().hex[:16]`（§5.1 已定）。
