# 数据质量阶段设计方案

> **Status**: 设计文档（部分能力已落地，以代码与 `TODO/INDEX.md` 为准）  
> **Target**: Phase 0 Week 3-4 (2026-07-24 ~ 08-07)  
> **Goal**: 在现有模型能力下，最大化输出数据的可用性和可验证性  
> **Note (2026-07-14)**: 文中「9-stage」指旧子步骤展开；现行顶层为 **7 logical stages**
> （见 [pipeline-stages.md](../architecture/pipeline-stages.md)）。

---

## 一、设计原则

### 1.1 透明优先于准确
- ✅ 显示置信度 + 原始证据，让用户判断
- ❌ 黑盒自动纠正（会掩盖模型错误）

### 1.2 Evidence-driven
- 所有数据必须可追溯到原文（图片 crop + 文本位置 + bbox）
- 用户可通过"打开原文"按钮验证任何数据点

### 1.3 渐进增强
1. **Phase 0.1** (本阶段): Schema + Pipeline + 基础 UI
2. **Phase 0.2**: Confidence histogram + 批量操作
3. **Phase 0.3**: Activity 图表可视化 + 关联分析

### 1.4 Phase 0 范围约束
- ❌ 不做跨文献聚合（同一分子在多篇文献中 = 多条记录）
- ❌ 不做模型 fine-tune（85-90% 准确率即可）
- ❌ 不做自动纠错（置信度 <0.5 标记为 "Pending Review"）

---

## 二、数据库 Schema

### 2.1 Confidence 透明化（已完成 90%）

**当前状态：**
- `molecules` 表已有 `composite_conf` 字段（Evidence Phase 1）
- `evidence` 表记录每个分子的来源（figure/text）+ 置信度

**补充工作：**
```sql
-- molecules 表增加字段（migration script）
ALTER TABLE molecules ADD COLUMN detection_conf REAL;    -- MolDet 检测置信度
ALTER TABLE molecules ADD COLUMN recognition_conf REAL;  -- MolScribe 识别置信度

-- composite_conf 计算规则（在 persist_molecules.py 中实现）
-- composite_conf = detection_conf * 0.4 + recognition_conf * 0.6
-- 权重设计基于：识别准确率(MolScribe)比检测准确率(MolDet)对最终 SMILES 质量影响更大
```

**数据来源：**
- `detection_conf`: `extract_molecules.py` 中 MolDet 返回的 bbox confidence
- `recognition_conf`: `extract_molecules.py` 中 MolScribe 返回的 SMILES confidence

### 2.2 Activity Extraction（新增）

```sql
CREATE TABLE activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mol_id TEXT NOT NULL,                     -- FK to molecules.mol_id
  doc_id TEXT NOT NULL,
  page_num INTEGER,                         -- 1-based page number
  
  -- Activity 数据
  activity_type TEXT NOT NULL,              -- 'IC50' | 'Ki' | 'EC50' | 'Kd' | 'ED50'
  value REAL,                               -- 数值（统一转为 nM）
  value_original REAL,                      -- 原始数值
  unit TEXT,                                -- 原始单位 'nM' | 'μM' | 'mM' | 'pM'
  operator TEXT,                            -- '=' | '<' | '>' | '~' | '>='
  target TEXT,                              -- 靶点 'EGFR' | 'HER2' | 'CDK4/6'
  assay_type TEXT,                          -- 'enzymatic' | 'cellular' | 'binding'
  
  -- Provenance
  raw_text TEXT NOT NULL,                   -- "IC50 = 10 nM (EGFR, enzymatic)"
  extraction_method TEXT DEFAULT 'llm',     -- 'llm' | 'regex' | 'manual'
  confidence REAL,                          -- LLM 置信度 0-1
  
  -- Evidence link
  evidence_kind TEXT,                       -- 'table' | 'text' | 'figure_caption'
  evidence_bbox TEXT,                       -- JSON: {x0, y0, x1, y1} for table/caption
  
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (mol_id) REFERENCES molecules(mol_id) ON DELETE CASCADE
);

CREATE INDEX idx_activities_mol_id ON activities(mol_id);
CREATE INDEX idx_activities_doc_id ON activities(doc_id);
CREATE INDEX idx_activities_type ON activities(activity_type);
CREATE INDEX idx_activities_conf ON activities(confidence);
```

**设计说明：**
1. **value vs value_original**: 前者统一为 nM（便于比较/排序），后者保留原始单位
2. **operator**: 处理 `>1000 nM` / `~50 μM` 等不精确值
3. **evidence_bbox**: Phase 0 可选（需要从 PDF 提取表格 bbox，工作量大）
4. **mol_id 可为空**: 某些表格提到的化合物未在文中画出结构（Phase 0 不关联）

### 2.3 Figure Linking（已完成）

**当前状态（Evidence Phase 1 已实现）：**
- `evidence` 表已有 `figure` 类型（存储 crop 图片路径 + bbox）
- `ArtifactResolver.crop()` 管理图片路径
- `routers/library.py:_resolve_crop_artifact()` 提供图片访问 API

**无需额外 schema 改动。**

---

## 三、Pipeline 改造

### 3.1 Stage 插入点

**逻辑展开（设计时子步骤；现行顶层为 7 stages，Activity 已是独立阶段）：**
```
Extract → Density → Markdown(rough_md+detect+molecode) → Reorganize
→ Activity → Index(pageindex+wiki) → Persist(mols+links+doc)
```

**历史草案曾写「Stage 7.5 extract_activities」——已并入 `ActivityStage`，以下伪代码仅作设计痕迹：**

```python
# runner.py STAGE_PCT 更新
STAGE_PCT = {
    "extract": 10,
    "density": 18,
    "rough_md": 22,
    "detect": 32,
    "insert_molecode": 40,
    "popo": 48,
    "reorganize": 55,
    "pageindex": 68,
    "wiki": 78,
    "persist_mols": 82,       # 原 85 → 82
    "register_links": 86,     # 原 92 → 86
    "extract_activities": 92, # 新增
    "persist": 100,           # 原 100 保持
}
```

**阶段定位：**
- **在 persist_mols 之后**: 需要 `mol_id` 关联 activity
- **可选失败**: `recoverable=True`，失败不影响分子数据
- **跳过条件**: `text_only` 文档且无表格

### 3.2 Activity Extraction 实现

见 `src/mbforge/pipeline/extract_activities.py`（已创建）。

**核心逻辑：**
1. 从 `reorganized.md` 提取 Markdown 表格（正则匹配 `|...|` 行）
2. 每个表格用 LLM 解析（Few-shot prompt + JSON output）
3. 单位标准化（μM/mM → nM）
4. 写入 `activities` 表（通过 `db.transaction()` 与 persist_mols 共享）

**LLM 调用参数：**
```python
ChatOpenAI(
    model="gpt-4o-mini",  # 便宜且足够（$0.15/1M tokens）
    temperature=0.0,       # 确定性抽取
    max_tokens=2048,       # 单表格输出不会超过
)
```

**Few-shot 示例设计：**
- 输入：ChEMBL-like SAR 表格（3-5 行，2-3 列）
- 输出：JSON array，包含 confidence 字段
- 覆盖边缘情况：`>1000`、`n.d.`（not determined）、`-`（未测试）

### 3.3 Confidence 持久化

**修改 `pipeline/persist_molecules.py`：**
```python
def persist_molecule_candidates(
    library_root: str,
    doc_id: str,
    candidates: list[NormalizedMolecule],
    conn: sqlite3.Connection | None = None,
) -> None:
    # ... 现有逻辑 ...
    
    # 新增：写入 detection_conf + recognition_conf
    for candidate in candidates:
        detection_conf = candidate.detection_score  # 从 MolDet 获取
        recognition_conf = candidate.smiles_confidence  # 从 MolScribe 获取
        composite_conf = detection_conf * 0.4 + recognition_conf * 0.6
        
        conn.execute(
            """
            UPDATE molecules
            SET detection_conf = ?, recognition_conf = ?, composite_conf = ?
            WHERE mol_id = ?
            """,
            (detection_conf, recognition_conf, composite_conf, candidate.mol_id),
        )
```

**数据来源（需在 `extract_molecules.py` 中补充）：**
```python
# extract_molecules.py 中 MolDet 调用
detections = moldet.detect(image)
for det in detections:
    det.confidence  # bbox 检测置信度 → detection_conf

# MolScribe 调用
smiles, conf = molscribe.predict(crop_image)
# conf → recognition_conf
```

---

## 四、API 设计

### 4.1 Molecule API 扩展

```python
# routers/molecule.py 新增接口

@router.get("/{mol_id}/activities")
async def get_molecule_activities(mol_id: str, library_root: str) -> list[dict]:
    """获取分子的所有 activity 数据"""
    db = DatabaseManager.get(library_root)
    rows = db.execute(
        "SELECT * FROM activities WHERE mol_id = ? ORDER BY confidence DESC",
        (mol_id,),
    ).fetchall()
    return [dict(row) for row in rows]

@router.get("/{mol_id}/evidence")
async def get_molecule_evidence(mol_id: str, library_root: str) -> list[dict]:
    """获取分子的所有 evidence（figure + text）"""
    db = DatabaseManager.get(library_root)
    rows = db.execute(
        "SELECT * FROM evidence WHERE canonical_smiles = (SELECT canonical_smiles FROM molecules WHERE mol_id = ?)",
        (mol_id,),
    ).fetchall()
    return [dict(row) for row in rows]

@router.get("/{mol_id}/crop")
async def get_molecule_crop(mol_id: str, library_root: str) -> FileResponse:
    """获取分子的 crop 图片（已在 Evidence Phase 1 实现）"""
    # 从 evidence 表获取 figure 类型的 artifact_path
    db = DatabaseManager.get(library_root)
    row = db.execute(
        """
        SELECT artifact_path FROM evidence
        WHERE canonical_smiles = (SELECT canonical_smiles FROM molecules WHERE mol_id = ?)
          AND kind = 'figure'
        LIMIT 1
        """,
        (mol_id,),
    ).fetchone()
    
    if not row or not row["artifact_path"]:
        raise HTTPException(404, "Crop image not found")
    
    from ..core.artifact import ArtifactResolver
    resolver = ArtifactResolver(library_root)
    # artifact_path 格式: "crops/page_0003_mol_0002.png"
    doc_id = "..."  # 需要从 molecules 表查询 source_doc
    crop_path = resolver.crop(doc_id, Path(row["artifact_path"]).name)
    
    if not crop_path.is_file():
        # Fallback to legacy location
        crop_path = resolver.legacy_crop(doc_id, Path(row["artifact_path"]).name)
    
    if not crop_path.is_file():
        raise HTTPException(404, "Crop image file not found on disk")
    
    return FileResponse(crop_path, media_type="image/png")
```

### 4.2 Settings API 扩展

```python
# routers/settings.py 新增

@router.get("/confidence_threshold")
async def get_confidence_threshold() -> dict:
    """获取置信度阈值配置"""
    cfg = load_global_config()
    return {
        "high": cfg.quality.confidence_high or 0.8,    # 高置信度阈值
        "low": cfg.quality.confidence_low or 0.5,      # 低置信度阈值（需人工审核）
    }

@router.put("/confidence_threshold")
async def update_confidence_threshold(high: float, low: float) -> dict:
    """更新置信度阈值"""
    # 写入 ~/.config/MBForge/config.json
    cfg = load_global_config()
    cfg.quality.confidence_high = high
    cfg.quality.confidence_low = low
    update_settings(cfg)
    return {"success": True}
```

---

## 五、前端 UI 设计

### 5.1 Molecule Library 置信度列

**位置**: `frontend/src/components/molecule/MoleculeTable.tsx`

**新增列：**
```tsx
<TableColumn key="confidence" width={120}>
  <TableHeader>置信度</TableHeader>
  <TableCell>
    {(item) => (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Progress 
          value={item.composite_conf * 100} 
          size="sm"
          color={item.composite_conf >= 0.8 ? 'success' : item.composite_conf >= 0.5 ? 'warning' : 'danger'}
        />
        <Text size="sm">{(item.composite_conf * 100).toFixed(0)}%</Text>
      </div>
    )}
  </TableCell>
</TableColumn>
```

**筛选器扩展：**
```tsx
// MoleculeLibrary.tsx 筛选面板
<Select label="置信度" value={confFilter} onChange={setConfFilter}>
  <SelectItem key="all">全部</SelectItem>
  <SelectItem key="high">高（≥80%）</SelectItem>
  <SelectItem key="medium">中（50-80%）</SelectItem>
  <SelectItem key="low">低（<50%，需审核）</SelectItem>
</Select>
```

### 5.2 Molecule Detail Panel - Evidence Tab

**位置**: `frontend/src/components/molecule/MoleculeDetailDrawer.tsx`

**新增 Tab：**
```tsx
<Tabs>
  <Tab key="overview">概览</Tab>
  <Tab key="evidence">Evidence</Tab>  {/* 新增 */}
  <Tab key="activities">Activities</Tab>  {/* 新增 */}
</Tabs>

{/* Evidence Tab 内容 */}
<TabPanel key="evidence">
  <EvidenceList moleculeId={molecule.mol_id} />
</TabPanel>
```

**EvidenceList 组件：**
```tsx
function EvidenceList({ moleculeId }: { moleculeId: string }) {
  const { data: evidenceList } = useSWR(
    `/api/v1/molecule/${moleculeId}/evidence`,
    fetcher
  )

  return (
    <div>
      {evidenceList?.map((ev) => (
        <Card key={ev.id}>
          <CardHeader>
            <Badge color={ev.kind === 'figure' ? 'primary' : 'secondary'}>
              {ev.kind}
            </Badge>
            <Text>Page {ev.page_num}</Text>
          </CardHeader>
          <CardBody>
            {ev.kind === 'figure' && (
              <Image 
                src={`/api/v1/molecule/${moleculeId}/crop`}
                alt="Molecule crop"
                width={200}
              />
            )}
            {ev.kind === 'text' && (
              <Code>{ev.snippet}</Code>
            )}
            <Button 
              size="sm" 
              onPress={() => onOpenPdf(ev.doc_id, ev.page_num, ev.bbox)}
            >
              打开原文
            </Button>
          </CardBody>
        </Card>
      ))}
    </div>
  )
}
```

### 5.3 Activities Tab

**组件设计：**
```tsx
function ActivitiesTab({ moleculeId }: { moleculeId: string }) {
  const { data: activities } = useSWR(
    `/api/v1/molecule/${moleculeId}/activities`,
    fetcher
  )

  return (
    <Table>
      <TableHeader>
        <Column>Type</Column>
        <Column>Value</Column>
        <Column>Target</Column>
        <Column>Assay</Column>
        <Column>Confidence</Column>
        <Column>Actions</Column>
      </TableHeader>
      <TableBody>
        {activities?.map((act) => (
          <Row key={act.id}>
            <Cell><Badge>{act.activity_type}</Badge></Cell>
            <Cell>
              {act.operator} {act.value_original} {act.unit}
              <Text size="xs" color="muted">({act.value.toFixed(1)} nM)</Text>
            </Cell>
            <Cell>{act.target || '-'}</Cell>
            <Cell>{act.assay_type || '-'}</Cell>
            <Cell>
              <Progress value={act.confidence * 100} size="sm" />
            </Cell>
            <Cell>
              <Button size="sm" onPress={() => openRawText(act.raw_text)}>
                查看原文
              </Button>
            </Cell>
          </Row>
        ))}
      </TableBody>
    </Table>
  )
}
```

---

## 六、实施计划

### 6.1 Week 3 (2026-07-24 ~ 07-31)

#### Day 1-2: Database Schema Migration
- [ ] 创建 `scripts/migrate_confidence_fields.py`（添加 detection_conf/recognition_conf）
- [ ] 创建 `scripts/migrate_activities_table.py`（新建 activities 表）
- [ ] 更新 `core/database.py` schema version v4 → v5

#### Day 3-4: Pipeline Integration
- [ ] 修改 `extract_molecules.py` 捕获 detection_conf + recognition_conf
- [ ] 修改 `persist_molecules.py` 写入三个置信度字段
- [ ] 在 `runner.py` 插入 Stage 7.5: extract_activities
- [ ] 添加 `_extract_activities()` 函数（调用 extract_activities.py）

#### Day 5-7: API Implementation
- [ ] `routers/molecule.py` 新增 3 个接口（activities/evidence/crop）
- [ ] `routers/settings.py` 新增置信度阈值配置接口
- [ ] 编写单元测试（mock LLM 响应）

### 6.2 Week 4 (2026-08-01 ~ 08-07)

#### Day 1-3: Frontend UI
- [ ] `MoleculeTable.tsx` 增加置信度列 + 筛选器
- [ ] `MoleculeDetailDrawer.tsx` 增加 Evidence Tab
- [ ] `MoleculeDetailDrawer.tsx` 增加 Activities Tab
- [ ] `EvidencePanel.tsx` 实现"打开原文"功能（PDF 跳转 + bbox 高亮）

#### Day 4-5: E2E Testing
- [ ] 测试数据集：5 篇真实文献（含 SAR 表格）
- [ ] 人工验证：Activity 抽取准确率 ≥70%
- [ ] 边缘情况：`>1000 nM`、`n.d.`、多目标表格

#### Day 6-7: Documentation + Polish
- [ ] 更新 `PHASE0-ROADMAP.md` 进度
- [ ] 补充 `docs/specs/data-quality-phase-design.md`（本文档）
- [ ] 前端交互优化（loading 状态、error handling）

---

## 七、验收标准

### 7.1 功能完整性
- [ ] 上传包含 SAR 表格的文献 → `activities` 表有数据
- [ ] Molecule Library 显示置信度进度条（80%+ 绿色，50-80% 黄色，<50% 红色）
- [ ] 点击分子 → Evidence Tab 显示 crop 图片 + "打开原文"按钮可用
- [ ] Activities Tab 显示表格数据 + 置信度

### 7.2 数据质量
- [ ] Activity 抽取准确率 ≥70%（人工抽查 50 条 IC50/Ki 数据）
- [ ] 置信度分布合理（高/中/低 占比约 6:3:1）
- [ ] 所有分子的 `composite_conf` 字段有值（非 NULL）

### 7.3 工程质量
- [ ] 测试覆盖率 ≥40%（新增代码的覆盖率 ≥60%）
- [ ] Pipeline 失败时前端显示具体错误阶段
- [ ] 无 P0 级别 bug（数据丢失、白屏、无限循环）

---

## 八、已知限制（Phase 0 范围）

### 8.1 不做的事情
- ❌ 跨文献分子去重（同一 SMILES 在多篇文献 = 多条记录）
- ❌ Activity 聚合分析（同一分子的多个 IC50 值不自动平均/比较）
- ❌ Figure caption 抽取（仅做表格，caption 工作量大且准确率低）
- ❌ 分子-Activity 自动关联（表格中的化合物编号 "1a" 需人工映射到 SMILES）

### 8.2 Phase 1 扩展方向
如果 Phase 0 验收通过，考虑：
- **Activity 可视化**：IC50 heatmap、SAR cliff 检测
- **Confidence 直方图**：显示整个库的置信度分布
- **批量校正工作流**：筛选 confidence <0.5 的分子 → 人工审核 → 批量接受/拒绝

---

## 九、技术债务追踪

### 9.1 当前阶段引入的债务
1. **表格 bbox 缺失**：`activities.evidence_bbox` 字段当前为 NULL（需要从 PDF 提取表格位置）
2. **Page 映射缺失**：`activities.page_num` 字段当前为 NULL（需要从 reorganized.md 提取页码标记）
3. **单位标准化不完整**：`_normalize_to_nm()` 未处理非标准单位（如 "ng/mL"）
4. **LLM prompt 未优化**：Few-shot 示例固定，未针对不同领域（药化/材料）调整

### 9.2 还清计划
- **表格 bbox**：Phase 1 增加 PDF 表格检测（PyMuPDF + layout analysis）
- **Page 映射**：Phase 0.2 在 reorganize 阶段插入 `<!-- page: N -->` 标记
- **单位标准化**：Phase 1 增加 unit 配置文件（YAML）
- **Prompt 优化**：Phase 1 基于用户反馈迭代（收集 100+ 错误案例）

---

## 十、参考资料

### 10.1 相关文档
- `TODO/PHASE0-ROADMAP.md` — Phase 0 总体规划
- `TODO/EVIDENCE-PHASE1-COMPLETE.md` — Evidence 基础设施
- `docs/specs/molecular-representation.md` — SMILES/E-SMILES/MoleCode 规范
- `docs/architecture/error-logging.md` — 错误处理架构

### 10.2 外部参考
- ChEMBL SAR 表格标准：https://www.ebi.ac.uk/chembl/
- PubChem Bioassay 数据格式：https://pubchem.ncbi.nlm.nih.gov/
- MolScribe 论文（置信度计算）：https://arxiv.org/abs/2205.14311
