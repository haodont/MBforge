# Phase 0 Roadmap: Research Baseline Validation

> **Last Updated**: 2026-07-10  
> **Duration**: 6 weeks (2026-07-10 to 2026-08-21)  
> **Goal**: 将 MBForge 从"能跑的 demo"升级为"可信赖的开源科研工具"

---

## 阶段定位

**MBForge Phase 0 = Open-Source Research Baseline**

### 我们要做什么
- ✅ 验证"图像分子识别 + 结构化抽取 + LLM 重整"技术路线的可行性
- ✅ 为药化/材料科学研究者提供文献整理起点（接受 85-90% 准确率 + 人工校验）
- ✅ 建立工程质量标准（测试覆盖、错误处理、数据一致性）
- ✅ 积累真实使用场景和数据（为后续模型改进提供基础）

### 我们不做什么
- ❌ 不追求 95%+ 识别准确率（需要专有模型 fine-tune，单独立项）
- ❌ 不构建"AI co-pilot"级推理能力（multi-target SAR、反向合成建议等）
- ❌ 不做数据网络效应（用户校正 → 全局模型改进）
- ❌ 不做跨文献分子去重聚合（当前是 per-project vault）

---

## 核心指标（Phase 0 验收标准）

### 工程质量
- [ ] **测试覆盖率 ≥40%**（critical path ≥60%）
  - `pipeline/` 模块 ≥60%
  - `core/` 模块 ≥60%
  - `routers/` 模块 ≥30%（smoke tests）
- [ ] **错误可观测**：Pipeline 失败时前端显示具体阶段 + 错误信息
- [ ] **数据一致性**：重复上传、中途失败不产生脏数据

### 数据质量
- [ ] **分子识别**：10 篇文献平均每篇抽取 15-30 个分子，置信度 >0.8 的占 60%+
- [ ] **活性抽取**（新增）：准确率 ≥70%（人工抽查 50 条 IC50/Ki 数据）
- [ ] **Figure Linking**：用户可查看每个分子的原始 crop 图片

### 用户体验
- [ ] **启动速度**：首次启动到处理第一个 PDF ≤2 分钟（含模型下载）
- [ ] **进度透明**：Pipeline 执行时显示当前阶段 + 预估剩余时间
- [ ] **容错能力**：网络中断、模型加载失败时显示明确错误（不白屏）

### 文档完整性
- [ ] **README** 明确说明"研究工具，85-90% 准确率，需人工校验"
- [ ] **CONTRIBUTING.md** 提供完整开发环境搭建指南
- [ ] **Issue 模板**收集 bug report + 数据标注（为后续模型改进积累数据）

---

## Week 1-2: P0 基础质量（2026-07-10 ~ 07-24）

### 目标
确保现有功能稳定可靠，Pipeline 失败时可定位根因。

### 任务列表

#### 1. Pipeline 测试覆盖（5 天）
- [ ] **集成测试**：`tests/integration/test_pipeline_flow.py`
  ```python
  def test_full_pipeline_with_5page_pdf():
      """完整六阶段流程，验证每个阶段输出"""
      result = run_pipeline("fixtures/sample_5pg.pdf", ...)
      assert result.page_count == 5
      assert result.indexed_count == 1
      # 验证数据库写入
      db = DatabaseManager.get(...)
      docs = db.execute("SELECT * FROM documents WHERE doc_id=?", ...)
      assert len(docs) == 1
  ```
- [ ] **单元测试**：`tests/unit/pipeline/test_extract_molecules.py`
  - Mock MolDet/MolScribe 后端（返回固定 SMILES）
  - 验证 `extract_molecules_from_pdf` 输出 `ExtractionResult` 结构
- [ ] **单元测试**：`tests/unit/pipeline/test_normalize.py`
  - 输入 10 个 SMILES（含重复、异构体）
  - 验证 RDKit 规范化 + 去重逻辑

#### 2. Core 模块测试（3 天）
- [ ] **database.py**：CRUD + 事务
  ```python
  def test_transaction_rollback():
      """插入失败时回滚"""
      with pytest.raises(Exception):
          with db.transaction():
              db.insert_document(...)
              raise Exception("Simulated failure")
      # 验证数据库无脏数据
      assert db.count_documents() == 0
  ```
- [ ] **knowledge_base.py**：SQLite FTS/Wiki 搜索与旧库只读回退

#### 3. Router Smoke Tests（2 天）
- [ ] 自动化脚本生成 18 个 router 的基础测试：
  ```python
  # tests/unit/test_routers_smoke.py (已存在，需补全)
  @pytest.mark.parametrize("endpoint", [
      "/api/v1/health",
      "/api/v1/documents/list",
      "/api/v1/kb/search",
      # ... 18 个
  ])
  def test_router_responds(client, endpoint):
      response = client.get(endpoint)
      assert response.status_code in [200, 422]  # 422 = missing params
  ```

#### 4. 错误处理改进（4 天）
- [ ] **Pipeline 阶段结果标准化**：
  ```python
  @dataclass
  class StageResult:
      status: Literal["success", "warning", "error"]
      stage: str
      message: str
      data: dict | None = None
      error_code: str | None = None  # "MOLDET_UNAVAILABLE", "OCR_TIMEOUT"
  ```
- [ ] **SSE 错误事件**：`routers/pipeline.py` 增加 `error` 事件类型
  ```json
  {
    "stage": "detect",
    "event": "error",
    "message": "MolDet model unavailable",
    "error_code": "MOLDET_UNAVAILABLE",
    "recoverable": false
  }
  ```
- [ ] **前端错误处理**：`useIngestPipeline.ts` 监听 `error` 事件，显示 Toast + 详情对话框

#### 5. 数据一致性（3 天）
- [ ] **事务边界**：`pipeline/runner.py` 增加：
  ```python
  with DatabaseManager.transaction(root):
      _persist_document(...)
      _persist_molecules(...)
      # 任何阶段失败 → 回滚
  ```
- [ ] **doc_id 冲突处理**：`routers/documents.py` 的 `/upload`
  ```python
  if doc_id_exists and not overwrite:
      raise MBForgeError(
          ErrorCode.DOCUMENT_EXISTS,
          f"Document {doc_id} already exists. Use overwrite=true to replace."
      )
  ```

### 验收标准
```bash
# 测试覆盖
uv run pytest tests/ --cov=src/mbforge --cov-report=term
# 输出：
# pipeline/     65%
# core/         62%
# routers/      35%
# TOTAL         42%

# 错误可观测
# 上传损坏的 PDF → 前端显示 "PDF parsing failed at extract stage: FileDataError"
# 而非 "Unknown error"

# 数据一致性
# Pipeline 执行到 detect 阶段手动 kill 进程 → 重启后数据库无 orphan records
```

---

## Week 3-4: P1 数据质量（2026-07-24 ~ 08-07）

### 目标
在现有模型能力下，最大化输出数据的可用性和可验证性。

### 任务列表

#### 6. 分子识别置信度透明化（3 天）
- [ ] **数据库 schema**：`molecules` 表已有 `composite_conf`，确保持久化
- [ ] **前端 UI**：`Molecule Library` 增加置信度列
  ```tsx
  <TableColumn>
    <Progress value={molecule.composite_conf * 100} />
    <Text>{(molecule.composite_conf * 100).toFixed(1)}%</Text>
  </TableColumn>
  ```
- [ ] **筛选功能**：
  - 置信度 <0.5 标记为"Pending Review"（黄色徽章）
  - 增加"只显示高置信度（>0.8）"筛选器
  - "批量接受高置信度"按钮

#### 7. Activity Data Extraction（7 天，核心功能）
- [ ] **数据库 schema**：新增 `activities` 表
  ```sql
  CREATE TABLE activities (
    id INTEGER PRIMARY KEY,
    molecule_id INTEGER,  -- FK to molecules.id
    doc_id TEXT NOT NULL,
    page_idx INTEGER,
    activity_type TEXT,   -- 'IC50' | 'Ki' | 'EC50' | 'Kd'
    value REAL,           -- 数值
    unit TEXT,            -- 'nM' | 'μM' | 'mM'
    target TEXT,          -- 靶点名称 'EGFR', 'HER2'
    assay_type TEXT,      -- 实验类型 'enzymatic' | 'cellular'
    confidence REAL,      -- LLM 置信度
    raw_text TEXT,        -- 原始表述 "IC50 = 10 nM"
    created_at TIMESTAMP
  );
  ```
- [ ] **Pipeline 模块**：`pipeline/extract_activities.py`
  ```python
  def extract_activities_from_page(
      page_text: str,
      tables: list[dict],  # from extract_text
      page_idx: int,
      doc_id: str,
      llm: BaseChatModel
  ) -> list[ActivityRecord]:
      """
      LLM prompt:
      - Input: page_text + tables (Markdown 格式)
      - Output: JSON array of {activity_type, value, unit, target, confidence}
      - Few-shot examples: 从 ChEMBL 选 5 个典型 SAR 表格
      """
  ```
- [ ] **Router 接口**：`routers/molecule.py` 增加 `GET /molecules/{id}/activities`
- [ ] **前端 UI**：Molecule 详情页增加"Activities"tab，表格展示

#### 8. Figure-Molecule Linking（4 天）
- [ ] **数据库持久化**：`molecules` 表已有 `mol_img_path`（crop 图片路径），确保写入
- [ ] **Router 接口**：`routers/molecule.py` 增加 `GET /molecules/{id}/crop`
  ```python
  @router.get("/{mol_id}/crop")
  async def get_molecule_crop(mol_id: int, library_root: str):
      mol = db.get_molecule(mol_id)
      if not mol.mol_img_path or not Path(mol.mol_img_path).exists():
          raise MBForgeError(ErrorCode.CROP_NOT_FOUND, ...)
      return FileResponse(mol.mol_img_path, media_type="image/png")
  ```
- [ ] **前端 UI**：Molecule 详情页增加"Original Crop"按钮 → 弹窗显示图片
- [ ] **缺失处理**：如果 crop 图片不存在，显示 placeholder + "Re-extract from PDF"按钮

### 验收标准
```bash
# 置信度透明化
# 上传 1 篇文献 → 抽取 20 个分子 → 前端显示置信度分布（如 12 个 >0.8，5 个 0.5-0.8，3 个 <0.5）

# Activity Extraction
# 上传包含 SAR 表格的文献（如 J. Med. Chem. 论文）
# 人工验证：抽取 50 条 IC50 数据，准确率 ≥70%（允许单位转换错误，但数值和靶点必须正确）

# Figure-Molecule Linking
# 点击任意分子 → 查看 crop 图片 → 能肉眼确认"这个图对应这个 SMILES"
```

---

## Week 5: P2 用户体验（2026-08-07 ~ 08-14）

### 目标
降低使用门槛，提升工具流畅度。

### 任务列表

#### 9. Pipeline 进度可视化（3 天）
- [ ] **模型预热**（可选）：`app.py` lifespan 增加环境变量控制
  ```python
  if os.getenv("MBFORGE_PREWARM_MODELS"):
      models = os.getenv("MBFORGE_PREWARM_MODELS").split(",")
      for model in models:
          if model == "moldet":
              from .backends.moldet_v2_ft import MolDetv2FTDetector
              MolDetv2FTDetector().load()
  ```
- [ ] **SSE 事件扩展**：增加 `model_loading` 事件
  ```json
  {
    "stage": "detect",
    "event": "model_loading",
    "message": "Loading MolDet (first time: 10-15s)",
    "estimated_seconds": 12
  }
  ```
- [ ] **前端进度条**：`PdfPipelineFlow.tsx` 显示：
  - 当前阶段名称 + 图标
  - 9 个阶段的进度条（当前阶段高亮）
  - 预估剩余时间（基于历史平均，localStorage 缓存）

#### 10. Document Viewer 实现（4 天）
- [ ] **组件结构**：`DocumentViewer.tsx` 三 tab 布局
  ```tsx
  <Tabs>
    <TabList>
      <Tab>Source PDF</Tab>
      <Tab>Raw Markdown</Tab>
      <Tab>Reorganized</Tab>
    </TabList>
    <TabPanels>
      <TabPanel><PdfViewer path={`/api/v1/documents/${docId}/source.pdf`} /></TabPanel>
      <TabPanel><MarkdownViewer readonly content={roughMd} /></TabPanel>
      <TabPanel><MarkdownEditor content={reorganizedMd} onSave={...} /></TabPanel>
    </TabPanels>
  </Tabs>
  ```
- [ ] **PDF 高亮**（bonus）：点击 Molecule Library 中的分子 → PDF 跳转到对应页 + bbox 红框
  - 使用 `react-pdf` 的 annotation layer
  - 需要 `molecules.bbox_pdf` 数据

---

## Week 6: P2 配置 + P3 文档（2026-08-14 ~ 08-21）

### 任务列表

#### 11. Settings 页面完善（3 天）
- [ ] **OCR 配置**：`routers/settings.py` 增加
  ```python
  @router.get("/ocr_config")
  async def get_ocr_config():
      cfg = load_global_config()
      return cfg.ocr  # 返回 configs/ocr.yaml 内容
  
  @router.put("/ocr_config")
  async def update_ocr_config(config: OcrConfig):
      # 写入 ~/.config/MBForge/ocr.yaml（优先级高于 configs/）
      ...
  ```
- [ ] **前端 UI**：`PdfParseSection.tsx` 增加
  - OCR Provider 拖拽排序（MinerU / PaddleOCR / GLMOCR）
  - "Enable OCR fallback"开关
- [ ] **Model Management**：新增 `SettingsModelSection.tsx`
  - 显示已下载模型列表（调用 `ResourceManager.list_models()`）
  - "Clear Cache"按钮（删除 `~/.cache/huggingface/`）

#### 12. 文档更新（4 天）
- [ ] **README.md** 大幅修订（分三批写入）：
  ```markdown
  # 第一批（What is MBForge）
  ## What is MBForge?
  
  MBForge is an **open-source research tool** for extracting structured molecular knowledge from scientific literature (PDF papers). It combines image-based molecule recognition (MolDetv2-FT + MolScribe) with LLM-powered text reorganization to help researchers build searchable molecular databases.
  
  **Current Status: Phase 0 (Research Baseline)**
  - ✅ Suitable for: literature screening + manual validation workflow
  - ⚠️ Molecule recognition accuracy: ~85-90% (requires human review)
  - ❌ Not suitable for: production environments, regulatory submissions
  
  ### Core Workflow
  (保留现有流程图，更新阶段数 9 stages)
  
  # 第二批（Known Limitations）
  ## Known Limitations
  
  We believe in transparency. Here are the current limitations:
  
  ### Recognition Accuracy
  - **Molecule recognition**: ~85-90% (based on MolScribe baseline)
  - **Activity extraction**: ~70% (LLM-based, requires validation)
  - **OCR quality**: depends on PDF quality and provider (MinerU > PaddleOCR > GLMOCR)
  
  ### Performance
  - **First-call latency**: 5-30s model loading (MolDet/MolScribe)
  - **Pipeline duration**: 5-10 min for typical 20-page paper
  - **No parallel processing**: pages processed sequentially
  
  ### Data Quality
  - **No cross-document deduplication**: same molecule in multiple papers = multiple records
  - **Limited activity data parsing**: only table-based IC50/Ki (no figure extraction yet)
  - **No validation against external databases** (PubChem/ChEMBL)
  
  # 第三批（Tech Stack + Roadmap）
  (保留现有技术栈表格，增加 Phase 0-3 路线图)
  ```

- [ ] **CONTRIBUTING.md** 新建：
  ```markdown
  # Contributing to MBForge
  
  ## Development Setup
  (uv sync + npm install 步骤)
  
  ## Running Tests
  (pytest + vitest 命令)
  
  ## Code Style
  (ruff + eslint 规则)
  
  ## Commit Convention
  (复制 README 的 commit 规范)
  
  ## Pull Request Checklist
  - [ ] Tests added/updated (coverage ≥40% for new code)
  - [ ] Documentation updated (README/AGENTS/specs)
  - [ ] CHANGELOG entry added
  - [ ] Passes CI (tests + lint)
  ```

- [ ] **Issue 模板**：`.github/ISSUE_TEMPLATE/`
  ```yaml
  # bug_report.yml
  name: Bug Report
  description: Report a bug in MBForge
  body:
    - type: input
      id: version
      label: MBForge Version
      placeholder: "commit hash or tag"
    - type: dropdown
      id: component
      label: Component
      options: [Pipeline, Frontend, Backend, Agent, OCR]
    - type: textarea
      id: steps
      label: Steps to Reproduce
    - type: textarea
      id: logs
      label: Logs (from ~/.mbforge/logs/)
  
  # model_accuracy.yml
  name: Model Accuracy Issue
  description: Report incorrect SMILES recognition
  body:
    - type: textarea
      id: wrong_smiles
      label: Incorrect SMILES Output
    - type: textarea
      id: expected_smiles
      label: Expected SMILES
    - type: input
      id: crop_image
      label: Link to Crop Image (upload to issue)
    - type: input
      id: confidence
      label: Confidence Score (from Molecule Library)
  ```

---

## 验收检查表（Phase 0 完成标志）

### 功能完整性
- [ ] 上传 10 篇真实文献（药化 / 材料科学领域）
- [ ] 每篇平均抽取 15-30 个分子
- [ ] 置信度 >0.8 的分子占 60%+
- [ ] Activity Extraction 准确率 ≥70%（人工抽查 50 条）
- [ ] 所有分子可查看原始 crop 图片
- [ ] Pipeline 失败时前端显示具体错误阶段

### 工程质量
- [ ] 测试覆盖率 ≥40%（`pytest --cov`）
- [ ] CI 通过（GitHub Actions: tests + lint）
- [ ] 无 P0 级别 TODO（`TODO/INDEX.md` 中的 Critical 项全部 resolved）

### 文档质量
- [ ] README 明确说明"Phase 0 research baseline"
- [ ] CONTRIBUTING.md 提供完整开发指南
- [ ] 有 3+ 个外部贡献者提交 Issue（说明文档足够清晰）

### 社区反馈
- [ ] 在 Reddit / 药化论坛发布，收集 10+ 条用户反馈
- [ ] 记录准确率问题（为 Phase 1 模型 fine-tune 积累数据）

---

## Phase 1 Preview（Phase 0 完成后启动）

如果 Phase 0 验收通过，考虑启动以下方向（需单独立项）：

### Option A: 专有模型 Fine-Tune（6 个月）
- 目标：SMILES 识别准确率 →95%+
- 需求：1000+ 篇标注文献 + GPU 集群 + 药化专家标注

### Option B: 推理能力扩展（4 个月）
- SAR 知识图谱构建（跨文献分子关联）
- Multi-target 分析工具（"找出同时抑制 EGFR 和 HER2 的化合物"）

### Option C: 平台化（12 个月）
- 中心化服务（用户贡献 → 模型改进飞轮）
- 商业化探索（SaaS / 企业版）

**Phase 0 期间不做这些，专注基础质量。**
