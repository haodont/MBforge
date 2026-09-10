# MBForge 文献→分子→活性→SAR 闭环设计

**日期**: 2026-07-04  
**状态**: 设计稿，待评审  
**目标**: 从文献/专利 PDF 自动提取分子结构及活性数据，经人工复核后支持半自动 SAR 分析，为后续分子生成奠定基础。

---

## 1. 背景与目标

### 1.1 项目目标

MBForge 是一个面向早期药物开发的分子知识工作台，核心使命是：

> **把分散在文献/专利中的分子结构与活性数据，转化为可分析、可推理、可指导分子设计的结构化知识。**

具体闭环：

```
PDF（文献/专利）
    │
    ▼
提取分子结构 ──→ 提取活性数据 ──→ 标准化/去重 ──→ 人工复核
    │                                                    │
    └────────────────→ SAR 分析 ←────────────────────────┘
                              │
                              ▼
                        分子生成（第二阶段）
```

### 1.2 当前代码状态

**已具备基础：**

| 模块 | 状态 | 说明 |
|---|---|---|
| Python FastAPI 后端 | ✅ 完整 | 12 个 router，SQLite 双库 |
| OpenKB + PageIndex | ✅ 完整 | 文档索引、wiki 编译、搜索 |
| MolDetv2 + MolScribe | ✅ 完整 | 图像分子检测与识别 |
| 分子库 CRUD | ✅ 基础 | `molecules.db`，FTS5 搜索 |
| Agent（LangGraph） | ✅ 基础 | 5 个工具 |
| React/TS 前端 | ✅ 主前端 | 功能较完整 |
| Ingest Queue / Logs | ✅ 表已存在 | 待充分利用 |

**关键缺失：**

| 模块 | 状态 | 影响 |
|---|---|---|
| 图像分子入库 | ❌ 未连接 | `pipeline/runner.py` 只拿 bbox，未识别 SMILES，未写入数据库 |
| 文本 SMILES 提取 | ❌ 未实现 | 漏掉正文中直接写的 SMILES |
| 活性数据提取 | ❌ 未实现 | IC50/EC50/Ki 等无法自动抽取 |
| 分子标准化/去重 | ❌ 未系统实现 | 同一分子多次出现会重复入库 |
| SAR 分析 | ❌ 全 stub | `routers/sar.py` 返回空 |
| Agent SAR 工具 | ❌ 未实现 | Agent 无法做 SAR 推理 |

### 1.3 设计决策

基于用户确认：

- **数据源**: 学术文献 PDF + 专利 PDF
- **提取策略**: 混合模式（自动提取 + 人工复核）
- **SAR**: 先半自动（用户指定 scaffold），再扩展全自动
- **分子生成**: 第二阶段，当前不做
- **前端**: 保留 React/TS 主前端
- **部署**: 先不纠结分发，优先跑通功能闭环

---

## 2. 总体架构

### 2.1 选型：方案 1 管线增强型

在现有 `pipeline/runner.py` 基础上补全缺失环节，让一条 PDF 管线直接产出"标准化分子 + 活性数据"。

**理由：**

1. 与现有代码最匹配，改动最小，能最快验证闭环。
2. 当前 `MolImagePipeline`、`OpenKBAdapter`、前端都是为同步/半同步管线设计。
3. SAR 走"半自动 → 全自动"，先让用户手动指定 scaffold 跑通流程最自然。
4. 后续如需批量/异步，可无损迁移到任务队列模型。

### 2.2 数据流

```
PDF 上传
    │
    ▼
┌────────────────────────────────────────┐
│ Stage 1: Document Ingest               │
│  - 文本提取（PyMuPDF / OCR fallback）   │
│  - PageIndex / OpenKB 索引              │
│  - Wiki 摘要                            │
└────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────┐
│ Stage 2: Molecule Extraction           │
│  - 图像：PDF 页面 → MolDet → MolScribe  │
│  - 文本：SMILES 正则 + RDKit 验证       │
│  - 保存裁剪图像，记录 PDF bbox          │
└────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────┐
│ Stage 3: Activity Extraction           │
│  - 表格/正文活性值匹配                  │
│  - IC50 / EC50 / Ki / pIC50 + 单位      │
│  - 靶点、细胞系、实验条件（可选）       │
│  - 与分子按名称/上下文关联              │
└────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────┐
│ Stage 4: Normalization & Deduplication │
│  - RDKit canonical SMILES               │
│  - 盐/溶剂剥离（可选）                  │
│  - 同结构合并，冲突标记                 │
└────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────┐
│ Stage 5: Human Review                  │
│  - 确认/拒绝/编辑分子                   │
│  - 修正活性值                           │
│  - 标记 false positive                  │
└────────────────────────────────────────┘
    │
    ▼
┌────────────────────────────────────────┐
│ Stage 6: SAR Analysis                  │
│  - 用户指定 scaffold / 核心结构         │
│  - R-group 分解                         │
│  - 活性矩阵 + 热图                      │
│  - 导出 SAR 假设                        │
└────────────────────────────────────────┘
```

### 2.3 模块划分

| 模块 | 路径 | 职责 |
|---|---|---|
| 图像分子提取 | `pipeline/extract_molecules.py` | 对 PDF 逐页调用 `MolImagePipeline`，输出 `ExtractionResult` |
| 文本分子提取 | `pipeline/extract_molecules.py` | 从正文匹配 SMILES 并验证 |
| 活性提取 | `pipeline/extract_activity.py` | 从文本/表格提取活性数据 |
| 标准化/去重 | `pipeline/normalize.py` | canonical SMILES、合并、冲突检测 |
| 持久化 | `pipeline/persist_molecules.py` | 写入 `molecules.db` |
| 骨架/R-group | `chem/scaffold.py` | Murcko scaffold、R-group 分解 |
| SAR 分析 | `chem/sar.py` | SAR 矩阵、热图数据 |
| SAR API | `routers/sar.py` | 替换 stub，实现真正接口 |
| 分子 API 扩展 | `routers/molecule.py` | 复核、批量确认、冲突解决 |
| Agent 工具扩展 | `agent/tools.py` | 增加 SAR、scaffold 工具 |

---

## 3. 核心模块详细设计

### 3.1 分子提取模块（`pipeline/extract_molecules.py`）

#### 3.1.1 图像来源

复用现有 `MolImagePipeline.extract_page()`，它已经包含：

- MolDetv2 整页检测
- 区域裁剪
- MolScribe SMILES 识别
- 坐标转换到 PDF 空间
- `ExtractionResult` 输出

新增 `extract_molecules_from_pdf()` 封装：

```python
def extract_molecules_from_pdf(
    pdf_path: str,
    project_root: str,
    doc_id: str,
    max_pages: int | None = None,
) -> list[ExtractionResult]:
    ...
```

**关键处理：**

- 如果 GPU/模型不可用，返回空列表并记录 warning，不阻塞管线。
- 裁剪图像统一保存到 `{project_root}/.mbforge/crops/{doc_id}/`。
- 默认处理全部页面；`max_pages` 用于测试/调试。

#### 3.1.2 文本来源

```python
def extract_molecules_from_text(
    text: str,
    doc_id: str,
) -> list[ExtractionResult]:
    ...
```

**第一阶段实现：**

- 用正则匹配疑似 SMILES 的字符串（连续非空格字符，含 `C`、`N`、`O`、数字、`=`、`#`、`(`、`)`、`[`、`]` 等）。
- 用 `RDKit.Chem.MolFromSmiles()` 验证。
- 验证通过后转为 canonical SMILES。
- 截取上下文前 500 字符。

**第二阶段（后续迭代）：**

- 化合物名 → SMILES 解析（可接 OPSIN、PubChem API、LLM NER）。
- 与图像检测结果做 coreference（名称 ↔ 结构图）。

#### 3.1.3 与 `pipeline/runner.py` 的衔接

替换现有 `_enrich_molecules()` 调用：

```python
# Stage 4: Enrich (molecules)
image_results = extract_molecules_from_pdf(
    pdf_path, project_root, doc_id, extracted.page_count
)
text_results = extract_molecules_from_text(extracted.raw_text, doc_id)
all_results = image_results + text_results

# Stage 5: Activity extraction
activity_results = extract_activity(
    text=extracted.raw_text,
    molecules=all_results,
)

# Stage 6: Normalize + persist
normalized = normalize_and_deduplicate(all_results, activity_results)
persist_molecule_candidates(project_root, doc_id, normalized)
```

提取结果以 `status='pending'` 进入待复核状态，不直接写入 `molecules` 主表。

---

### 3.2 活性数据提取模块（`pipeline/extract_activity.py`）

#### 3.2.1 目标

从 PDF 文本/表格中提取：

- 活性值（numeric）
- 活性类型：`IC50`, `EC50`, `Ki`, `Kd`, `pIC50`, `pKi` 等
- 单位：`nM`, `uM`, `mM`, `ng/mL` 等
- 靶点/酶/受体名称（可选）
- 细胞系/实验条件（可选）
- 关联的化合物标识（名称、编号）

#### 3.2.2 实现策略

**第一阶段：规则 + 正则**

```python
ACTIVITY_PATTERN = re.compile(
    r'(IC50|EC50|Ki|Kd|pIC50|pKi)\s*[:=]?\s*([0-9]+\.?[0-9]*)\s*(nM|uM|μM|mM|µM|ng/mL)',
    re.IGNORECASE,
)
```

- 在正文和表格文本中匹配。
- 向前向后取 200 字符作为上下文。
- 从上下文中提取化合物名/编号（简单正则：大写字母+数字，如 `Compound 1`、`3a`、`12b`）。

**第二阶段：LLM 辅助**

对规则提取结果置信度低的段落，调用 LLM 做结构化抽取：

```json
{
  "activities": [
    {
      "compound_name": "Compound 3a",
      "activity_type": "IC50",
      "value": 12.5,
      "unit": "nM",
      "target": "AChE",
      "cell_line": "HEK293",
      "confidence": 0.85
    }
  ]
}
```

LLM 仅作为补充，不替代规则（规则更快、更确定、成本更低）。

#### 3.2.3 与分子的关联

**匹配优先级：**

1. 化合物名完全匹配图像/文本提取的分子 `name`。
2. 如果分子没有 name，用上下文距离最近匹配。
3. 多个候选时标记为"待人工确认"。

关联结果写入 `molecule_detections.activity_*` 字段或独立 `activities` 表（见数据模型）。

---

### 3.3 标准化与去重模块（`pipeline/normalize.py`）

#### 3.3.1 标准化

对每一个 `ExtractionResult`：

1. 用 `RDKit.Chem.MolFromSmiles()` 解析 SMILES。
2. 失败则标记 `status='rejected'`，原因 `invalid_smiles`。
3. 成功则生成 `canonical_smiles = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)`。
4. 可选：剥离盐/溶剂（用 RDKit SaltRemover），生成 `parent_smiles` 用于去重。

#### 3.3.2 去重

**去重键：**

- 主键：`canonical_smiles`
- 如果启用了 parent 模式，也可用 `parent_smiles`

**合并策略：**

- 同一 `canonical_smiles` 多次出现时，合并来源信息（多个 doc_id、page、bbox）。
- 保留置信度最高的 `mol_img_path`。
- 活性数据合并为列表。
- 如果同名但 SMILES 不同，标记为 `name_conflict`。

#### 3.3.3 输出

```python
@dataclass
class NormalizedMolecule:
    canonical_smiles: str
    esmiles: str
    name: str
    source_type: Literal["image", "text", "manual"]
    detections: list[DetectionSource]  # doc_id, page, bbox, image_path, conf
    activities: list[ActivityEntry]
    status: Literal["pending", "rejected"]
    reject_reason: str | None
```

---

### 3.4 持久化模块（`pipeline/persist_molecules.py`）

#### 3.4.1 待复核数据

先写入 `molecule_detections` 表：

```sql
INSERT INTO molecule_detections (
    mol_id, doc_id, page, bbox_x0, bbox_y0, bbox_x1, bbox_y1,
    crop_relpath, conf_moldet, conf_molscribe, vlm_verified_esmiles,
    vlm_confidence, activity_value, activity_type, units, target
) VALUES (...);
```

注意：这里的 `mol_id` 此时可能为空（未确认），待复核后生成。

#### 3.4.2 复核后写入 molecules 主表

用户在前端确认一个分子后：

1. 生成 `mol_id`（UUID 或基于 SMILES 的哈希）。
2. 写入 `molecules` 表：`canonical_smiles`、`esmiles`、`name`、`activity`、`activity_type`、`units`、`source_doc` 等。
3. 更新 `molecule_detections.mol_id`。
4. 如果拒绝，更新 `molecule_detections` 状态为 `rejected`。

---

### 3.5 SAR 分析模块

#### 3.5.1 骨架识别（`chem/scaffold.py`）

**第一阶段：用户指定 scaffold**

用户通过前端输入一个核心 SMILES，或从已确认分子列表中选择一个作为 scaffold。

**第二阶段：自动 Murcko scaffold（后续）**

```python
from rdkit.Chem.Scaffolds import MurckoScaffold
scaffold = MurckoScaffold.GetScaffoldForMol(mol)
```

对一组分子计算 Murcko scaffold，找出最常见 scaffold 作为候选。

#### 3.5.2 R-group 分解（`chem/scaffold.py`）

使用 RDKit `RGroupDecomposition`：

```python
from rdkit.Chem import rdRGroupDecomposition

core = Chem.MolFromSmiles(scaffold_smiles)
mols = [Chem.MolFromSmiles(s) for s in molecule_smiles_list]
groups, unmatched = rdRGroupDecomposition.RGroupDecompose([core], mols, asSmiles=True)
```

输出：

```python
{
    "core_smiles": "...",
    "r_labels": ["R1", "R2", "R3"],
    "rows": [
        {"mol_id": "...", "r_groups": {"R1": "C", "R2": "F"}, "activity": 12.5},
        ...
    ],
    "unmatched_count": 2
}
```

#### 3.5.3 SAR 矩阵与热图（`chem/sar.py`）

基于 R-group 分解结果：

- 对每个 R-group 位置，列出所有取代基。
- 构建矩阵：行=化合物，列=R-group 位置 + 活性值。
- 计算每个取代基在每个位置的平均活性。
- 输出热图数据（颜色映射活性高低）。

```python
{
    "heatmap": [
        {"r_label": "R1", "substituent": "F", "mean_activity": 5.2, "count": 4},
        {"r_label": "R1", "substituent": "Cl", "mean_activity": 12.5, "count": 3},
        ...
    ]
}
```

#### 3.5.4 SAR API（`routers/sar.py`）

替换现有 stub，实现：

```python
@router.post("/find-scaffold")
async def find_scaffold(body: FindScaffoldRequest) -> ScaffoldResponse

@router.post("/decompose")
async def decompose(body: DecomposeRequest) -> DecomposeResponse

@router.post("/build-matrix")
async def build_matrix(body: BuildMatrixRequest) -> MatrixResponse

@router.post("/heatmap")
async def heatmap(body: HeatmapRequest) -> HeatmapResponse
```

---

## 4. 数据模型

### 4.1 现有表复用

复用 `molecules` 和 `molecule_detections` 表。

`molecules` 表已支持：

- `smiles`, `esmiles`, `name`, `source_doc`
- `activity`, `activity_type`, `units`
- `status`, `source_type`, `properties`, `labels`, `notes`
- `fingerprint`

**需要扩展：**

- `molecules` 增加 `canonical_smiles TEXT` 字段用于稳定去重。
- `molecules` 增加 `reviewed_at TEXT` 记录复核时间。

### 4.2 新增/强化表

#### activities 表（可选，如果一对多）

如果同一个分子有多个活性值（不同靶点、不同实验），建议拆出独立表：

```sql
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mol_id TEXT NOT NULL,
    doc_id TEXT NOT NULL,
    activity_type TEXT NOT NULL,  -- IC50 / EC50 / Ki / Kd / pIC50
    value REAL,
    units TEXT,
    target TEXT,
    cell_line TEXT,
    conditions TEXT,
    source_quote TEXT,
    confidence REAL,
    FOREIGN KEY (mol_id) REFERENCES molecules(mol_id)
);
CREATE INDEX IF NOT EXISTS idx_act_mol ON activities(mol_id);
CREATE INDEX IF NOT EXISTS idx_act_doc ON activities(doc_id);
```

**第一阶段简化：** 先把活性存在 `molecules.activity` 单字段，等出现一对多场景再拆表。

---

## 5. API 设计

### 5.1 管线触发

已有：`POST /api/v1/pipeline/enqueue`

保持不变，但内部 `run_pipeline` 会调用新增的提取/标准化/持久化模块。

### 5.2 分子复核 API（扩展 `routers/molecule.py`）

```python
class MoleculeReviewRequest(BaseModel):
    project_root: str
    detection_id: int       # molecule_detections.id
    action: Literal["confirm", "reject", "edit"]
    smiles: str | None = None   # edit 时提供
    name: str | None = None
    activity: float | None = None
    activity_type: str | None = None
    units: str | None = None

@router.post("/review")
async def review_molecule(body: MoleculeReviewRequest) -> dict
```

### 5.3 SAR API（重写 `routers/sar.py`）

```python
class FindScaffoldRequest(BaseModel):
    project_root: str
    mol_ids: list[str] | None = None   # 未指定则自动找
    auto: bool = False

class DecomposeRequest(BaseModel):
    project_root: str
    core_smiles: str
    mol_ids: list[str]

class BuildMatrixRequest(BaseModel):
    project_root: str
    core_smiles: str
    mol_ids: list[str]
    activity_type: str = "IC50"  # 用什么活性值构建矩阵

class HeatmapRequest(BaseModel):
    project_root: str
    core_smiles: str
    mol_ids: list[str]
    activity_type: str = "IC50"
```

---

## 6. 前端界面设计

### 6.1 复核界面

在现有 `MoleculeLibrary` 或新增 `Review` 页面：

- 左侧：待复核分子列表（按文档分组）。
- 中间：分子结构图（用 RDKit 渲染或显示裁剪图像）。
- 右侧：
  - SMILES 编辑框
  - 名称编辑框
  - 检测置信度
  - 来源上下文（PDF 页、bbox、原文）
  - 提取到的活性数据（可编辑）
  - 操作按钮：确认 / 拒绝 / 跳过

### 6.2 SAR 分析界面

新增 `/sar` 路由或集成到 MoleculeLibrary：

- 第一步：选择数据集（已确认分子）。
- 第二步：指定 scaffold（输入 SMILES 或从列表选）。
- 第三步：执行 R-group 分解。
- 第四步：展示 SAR 矩阵和热图。
- 第五步：导出结果（CSV / JSON）。

### 6.3 最小前端改动

第一阶段不追求完美 UI，目标是把数据展示出来、让人能复核。可用表格 + 简单图片展示。

---

## 7. Agent 工具扩展

在 `agent/tools.py` 中新增：

```python
@tool
def find_common_scaffold(mol_ids: list[str]) -> str:
    """Find the most common Murcko scaffold among given molecules."""

@tool
def decompose_r_groups(core_smiles: str, mol_ids: list[str]) -> str:
    """Perform R-group decomposition and return substituents table."""

@tool
def build_sar_heatmap(core_smiles: str, mol_ids: list[str], activity_type: str = "IC50") -> str:
    """Build SAR heatmap data for the given scaffold and molecules."""

@tool
def extract_activities_from_document(doc_id: str) -> str:
    """Re-run activity extraction for a document."""
```

Agent 可以回答类似问题：

> "这批 AChE 抑制剂里，R1 位换 F 和 Cl 哪个活性更好？"

---

## 8. 实现顺序（MVP 路线）

### Phase 1: 分子提取闭环（2-3 周）

1. 实现 `pipeline/extract_molecules.py`，把 MolDet+MolScribe 接入 runner。
2. 实现文本 SMILES 正则提取。
3. 实现 `pipeline/normalize.py` canonical SMILES + 基础去重。
4. 实现 `pipeline/persist_molecules.py`，写入 `molecule_detections`。
5. 前端最小复核界面：列表 + 图片 + 确认/拒绝。
6. 添加测试。

**Phase 1 验收标准：** 上传 PDF 后，能在前端看到提取出的分子候选及其结构图。

### Phase 2: 活性提取（2 周）

1. 实现 `pipeline/extract_activity.py` 规则提取。
2. 把活性数据挂到分子候选。
3. 复核界面支持编辑活性。
4. Agent 工具增加活性查询。

**Phase 2 验收标准：** 上传 PDF 后，分子候选带有 IC50/EC50 等活性值。

### Phase 3: SAR 分析（2-3 周）

1. 实现 `chem/scaffold.py` Murcko scaffold + R-group 分解。
2. 实现 `chem/sar.py` 矩阵和热图。
3. 重写 `routers/sar.py`。
4. 前端 SAR 界面。
5. Agent SAR 工具。

**Phase 3 验收标准：** 用户能选择一组分子和 scaffold，生成 SAR 热图。

### Phase 4: 自动化增强（后续）

- 自动 scaffold 发现
- LLM 辅助活性/名称提取
- 一对多 activities 表
- 批量任务队列化
- 分子生成接入

---

## 9. 风险与取舍

| 风险 | 影响 | 缓解 |
|---|---|---|
| MolScribe 识别精度不足 | 分子 SMILES 错误，后续 SAR 无意义 | 复核机制；低置信度标记；支持手动编辑 |
| 活性提取规则覆盖率低 | 漏提大量活性数据 | 先保证常见格式；后续加 LLM 补充 |
| R-group 分解失败率高 | SAR 热图缺数据 | 允许用户调整 scaffold；记录 unmatched |
| 多语言栈维护成本 | 前端/后端类型对齐 | 用 OpenAPI / Pydantic 生成 TS 类型 |
| 管线同步执行阻塞 UI | 大文档体验差 | Phase 1 先接受；Phase 4 再异步化 |

---

## 10. 未决问题

1. 是否新增 `activities` 独立表，还是先存在 `molecules` 单字段？
2. 化合物名 → SMILES 解析是否在 Phase 1 做，还是延后？
3. 盐/溶剂剥离是否默认开启？
4. SAR 热图的颜色映射和统计方式（mean / median / best）？

---

## 11. 结论

本设计采用**管线增强型方案**，在现有 MBForge 基础上补齐：

1. 图像/文本分子提取与入库
2. 活性数据自动提取
3. 标准化、去重、人工复核
4. 半自动 SAR 分析

保留 React/TS 前端作为主力界面，暂不做分子生成，优先跑通"PDF → 分子 + 活性 → SAR"的数据闭环。
