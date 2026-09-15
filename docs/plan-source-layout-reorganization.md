# Plan: 整理 `src/mbforge` 包结构

> 目标：降低 `src/mbforge` 的目录认知成本，使目录位置能直接表达代码职责和生命周期，
> 并收敛跨层传递的核心分子实体。本计划不改变 Pipeline 行为、数据库结构、API 请求响应、
> Torch DBSCAN、模型加载方式或产物格式。

## 当前基线（2026-09-14）

- `routers/`、`services/` 已基本按业务域分包，暂不重排。
- `core/`、`backends/`、`infra/`、`storage/` 一级边界基本清楚。
- 主要散乱点是 `pipeline/` 根目录：运行态、checkpoint、artifact、OCR、Patent 读侧混放。
- `pipeline/stage_artifacts.py` 已约 900 行，同时负责 branch I/O、join、转换和 hydration。
- `pipeline/detection/` 有 17 个 Python 文件，其中 PDF 提取的 5 个文件属于同一生命周期。
- `models/` 是 FastAPI/Pydantic schema，而 `infra/models/` 是模型运行时，名称存在歧义。
- `pipeline/persist/` 同时包含当前活动的 SourceEvidence 写入和未来未注册的 Persist 逻辑。
- 根目录 `.gitignore` 和 `TODO/INDEX.md` 已补齐；生成目录不再作为本次布局验收的阻断项。
- `InitialForkRunner` 的 `self.run` / `run()` 冲突已在当前代码中消除；完整后端测试当前为
  `829 passed`。
- 当前工作树还包含本计划之外的既有运行时迁移修改；全仓库 Ruff/format 的遗留报告需与该
  既有变更分开处理，本计划只对改动范围做静态检查。

## 整理原则

1. 先修复红色测试基线，再移动文件。
2. 一次只整理一个业务域或一种生命周期，不做全仓库大搬家。
3. 移动阶段不修改业务逻辑；行为优化单独提交。
4. 只有四个以上紧密相关文件时才新增子包，避免一文件一目录。
5. `__init__.py` 只导出稳定公共入口，不做隐式初始化或宽泛 `import *`。
6. 内部导入一次性更新；兼容 shim 只保留确实被外部入口依赖的路径。
7. 文件移动本身不新增测试；复用现有最低层契约测试。
8. 每个迁移批次独立提交、独立验证、可独立回滚。

### 深层子包导入约定

`detection/extraction/`、`pipeline/artifacts/`、`pipeline/run/` 等子包允许
表达生命周期边界，但跨 `mbforge` 业务包的导入统一使用绝对路径；相对导入只用于
同一子包或相邻模块。这样目录层级不会把导入写成难读的多级 `....`，也避免移动
文件后靠点数猜测包根。该约定只改变导入表达，不改变运行时边界或公共接口。

### 全局分子实体约定

`mbforge.core.entities.molecule.Molecule` 是唯一的结构分子领域对象，检测归一化、
上下文纠正、Markush 分类、artifact hydration、查询和未来 Persist 都使用同一类。
入库前允许 `mol_id` 为空，并携带运行态来源/检测信息；SQLite 仍将检测和证据保存为
独立关联表。`ExtractionResult` 和 `DetectionSource` 只表示原始观测，`CompoundEntry`
只表示专利文本条目，API/前端类型只表示传输边界，不再创建第二套分子实体。

## 目标结构

```text
src/mbforge/
├── app.py
├── backends/                    # 外部模型和推理后端
├── core/                        # 纯领域类型和规则
├── infra/                       # 进程、资源、模型生命周期、队列基础设施
├── models/                      # 暂留；后续可整体改名 schemas/
├── routers/                     # HTTP 边界，继续按业务域分包
├── services/                    # 用例层，继续按业务域分包
├── storage/                     # 路径、SQLite、DAO
├── utils/                       # 仅保留真正跨领域的小工具
└── pipeline/
    ├── __init__.py
    ├── runner.py                # 稳定公共门面
    ├── composition.py           # Stage 组合根
    ├── activity/
    ├── artifacts/
    │   ├── __init__.py
    │   ├── evidence_models.py   # Extract/Detection/Joined DTO
    │   ├── branch_io.py         # branch 文件读写
    │   ├── evidence_join.py     # join、去重、坐标校验
    │   ├── hydration.py         # artifact/SQL → PipelineContext
    │   ├── staging.py           # promote、cleanup、reap
    │   └── json_io.py           # 原子 JSON I/O
    ├── detection/
    │   ├── extraction/
    │   │   ├── __init__.py      # extract_molecules_from_pdf 等兼容入口
    │   │   ├── coordinator.py
    │   │   ├── config.py
    │   │   ├── crop_processor.py
    │   │   ├── page_detector.py
    │   │   └── page_renderer.py
    │   ├── image_preprocessing.py
    │   ├── normalization.py
    │   ├── recognition.py
    │   └── ...
    ├── extract/
    │   ├── __init__.py
    │   ├── text.py
    │   └── ocr_artifacts.py
    ├── markdown/
    ├── patent/
    │   ├── __init__.py
    │   ├── artifact.py
    │   ├── sections.py
    │   └── association.py
    ├── persist/                 # 未来 Persist redesign；不注册到当前 Runner
    │   ├── stage.py
    │   ├── molecules.py
    │   ├── activities.py
    │   ├── markush.py
    │   └── text_links.py
    ├── run/
    │   ├── __init__.py
    │   ├── context.py           # PipelineContext + RunContext，名称明确区分
    │   ├── models.py
    │   ├── checkpoint.py
    │   ├── ids.py
    │   ├── events.py
    │   ├── initial_fork.py
    │   ├── sequential.py
    │   └── finalize.py
    └── stages/                  # 仅保留当前注册的四个 Stage
        ├── base.py
        ├── extract_stage.py
        ├── detection_stage.py
        ├── markdown_stage.py
        └── patent_stage.py
```

跨 Extract、Detection、Runner 共同使用的取消控制保留在
`pipeline/cancellation.py`；不再为了目录对称性把它下沉到 `run/`，以免增加无收益的
导入层级。

## 接口兼容策略

| 当前路径 | 目标路径 | 处理方式 |
|---|---|---|
| `mbforge.pipeline.runner` | 保持不变 | 继续作为 worker/router 的稳定门面 |
| `mbforge.pipeline.detection.extraction` | 同名 package | `extraction/__init__.py` 重导出当前公共函数和常量 |
| `mbforge.pipeline.stage_result` | `mbforge.core.stage_result` | 内部导入已迁移，旧 shim 已删除 |
| `mbforge.pipeline.evidence_artifacts` | `pipeline.artifacts.evidence_models` | 迁移批次内更新生产代码和测试导入 |
| `mbforge.pipeline.stage_artifacts` | `pipeline.artifacts.*` | 按职责拆分，不保留新的单体聚合模块 |
| `mbforge.pipeline.run_artifacts` | `pipeline.artifacts.staging` | `runner.py` 可临时重导出必要公共函数 |
| `mbforge.pipeline.context` | `pipeline.run.context` | Stage 和 Runner 统一从新路径导入 |
| `mbforge.pipeline.patent_store` | `services.documents.patent_facts` | 读侧退出 Pipeline 层 |

## 实施批次

### 0. 恢复可验证基线

- [x] 修复 `InitialForkRunner` 的属性/方法重名，使完整后端测试恢复绿色（当前代码已无该冲突）。
- [x] 核对 `docs/plan-runner-split.md` 的“已完成”状态与当前代码一致；该文件在当前工作树中保持既有删除状态。
- [x] 恢复 `TODO/INDEX.md`，并将当前 Pipeline 事实写入索引。
- [x] 添加并补充根 `.gitignore`，忽略 `.venv/`、`__pycache__/`、`*.py[cod]`、
  `.pytest_cache/`、`.ruff_cache/`、`frontend/node_modules/`、`frontend/dist/`。
- [x] 记录完整后端测试 `829 passed` 及本次改动范围的 Ruff/format 验证结果；全仓静态检查的
  既有遗留项单独保留，不混入本次布局修改。

### 1. 收拢 Detection extraction

- [x] 建立 `pipeline/detection/extraction/` 子包。
- [x] `coordinator.py` 接收当前 `extraction.py` 的 PDF 编排入口。
- [x] `crop_processor.py` 接收 `CropProcessor`、`MolParserBatcher`、OCR crop 生命周期。
- [x] `config.py` 接收 `ExtractionConfig` 和默认值。
- [x] 移入 `page_detector.py`、`page_renderer.py`。
- [x] 在 `extraction/__init__.py` 保留当前导入和 monkeypatch 路径。
- [x] 删除旧的平铺 extraction 文件，确认不存在新旧双实现。

验证范围：

```powershell
uv run pytest tests/unit/pipeline/test_extract_molecules.py `
  tests/unit/pipeline/test_preprocess.py `
  tests/unit/pipeline/test_extract_text.py -q
uv run ruff check src/mbforge/pipeline/detection tests/unit/pipeline/test_extract_molecules.py
```

### 2. 建立 Artifact 子包并拆分 `stage_artifacts.py`

- [x] 先移动纯 DTO：`evidence_artifacts.py` → `artifacts/evidence_models.py`。
- [x] 提取通用 JSON I/O，不让 join 代码操作临时文件细节。
- [x] 提取 Extract/Detection branch 的 save/load/path 逻辑到 `branch_io.py`。
- [x] 提取 join、dedupe、bbox/页面约定校验到 `evidence_join.py`。
- [x] 提取上下文重建到 `hydration.py`。
- [x] 将 staging promote/cleanup/reap 移到 `artifacts/staging.py`。
- [x] 删除 `stage_artifacts.py` 单体文件及内部私有函数跨模块调用。

验收要求：

- Join 的输入输出 DTO 不变。
- SourceEvidence SQL 行数、ID、排序和去重结果不变。
- staging 只能操作 `LibraryLayout` 验证后的文档目录。
- 现有 artifact、runner、重摄取和清理测试全部通过。

### 3. 收拢 Pipeline run 生命周期

- [x] 移动 `PipelineContext` 和 `RunContext` 到 `run/context.py`，保留两个明确类名。
- [x] `stage_checkpoint.py` → `run/checkpoint.py`。
- [x] `run_ids.py` → `run/ids.py`。
- [x] 取消控制保留在跨阶段的 `pipeline/cancellation.py`，不再下沉到 `run/`。
- [x] 更新 `runner.py`、worker、service、stage 导入。
- [x] 保持 `pipeline.runner` 的公共符号、函数签名和结果字段不变。

验收要求：

- Extract ∥ Detection 固定并行关系不变。
- 一次 worker claim 只执行一个顺序 Stage 的语义不变。
- resume、retry、cancel、checkpoint 和 cleanup 行为不变。
- `runner.py` 保持薄门面，不重新吸收运行细节。

### 4. 建立 Extract 与 Patent 子包

- [x] `extract_text.py` → `extract/text.py`。
- [x] `ocr_artifacts.py` → `extract/ocr_artifacts.py`。
- [x] `sections.py` → `patent/sections.py`。
- [x] `artifacts.py` 中 Patent DTO → `patent/artifact.py`。
- [x] 从 `PatentStage._associate_facts` 提取纯关联逻辑到 `patent/association.py`。
- [x] `patent_store.py` → `services/documents/patent_facts.py`。

### 5. 分离活动 SourceEvidence 与未来 Persist

- [x] 统计 `pipeline/persist/` 每个函数的当前生产调用方。
- [x] 将 Join 当前使用的 SourceEvidence SQL 边界迁到 `storage/source_evidence.py`。
- [x] 将未注册的 `PersistStage` 移到 `pipeline/persist/stage.py`。
- [x] `pipeline/stages/` 只保留当前注册的 Extract、Detection、Markdown、Patent。
- [x] 更新 `TODO/INDEX.md`，明确活动 SourceEvidence 写入与未来 Persist 的边界。

### 6. 可选：解决 `models` 与 `utils` 命名问题（暂缓）

- [ ] 确认 `src/mbforge/models/` 全部是 API schema 后，再整体改名为 `schemas/`；本轮不做，避免扩大导入深度和变更面。
- [ ] 仅对已经形成文件群的域建立 schema 子包，例如 `schemas/markush/`。
- [ ] `utils/file_scanner.py` → `services/documents/scanner.py`。
- [ ] `utils/capabilities.py` → `services/system/capabilities.py` 或 `infra/environment/`。
- [ ] 审计 `utils/runtime.py`，把 ID、async 和路径校验移动到各自真实归属。
- [ ] 不为只含一个小文件的领域新建目录。

### 7. 收敛全局分子实体

- [x] 将 `core.entities.molecule.Molecule` 定为入库前后共用的唯一核心分子类。
- [x] 将运行态 `sources`、`detections`、`reject_reason` 合并进 `Molecule`；入库前允许空 `mol_id`。
- [x] 迁移 Detection normalization/correction、artifact join/hydration、Markdown、Markush、
  查询和 recorrection 服务的类型签名与构造。
- [x] 删除 `NormalizedMolecule` 和 `_rebuild_normalized_molecule` 兼容层。
- [x] 保留 `ExtractionResult`、`DetectionSource`、`CompoundEntry`、SourceEvidence 及 API schema
  的独立语义边界。
- [x] 不修改数据库 schema、REST 请求响应或 artifact JSON 结构。

验证范围：

```powershell
.venv\Scripts\python.exe -m pytest tests/unit/core/test_molecule.py `
  tests/unit/pipeline/test_normalize.py tests/unit/pipeline/test_molecule_corrector.py `
  tests/unit/pipeline/test_persist_markush.py tests/unit/core/test_markush_review_service.py `
  tests/unit/services/test_markush_review.py tests/unit/services/test_recorrection_service.py `
  tests/unit/pipeline/test_stage_artifacts.py tests/unit/services/test_pdf_layout.py `
  tests/unit/services/test_pdf_document_bboxes.py tests/unit/services/test_molecule_queries.py `
  tests/unit/pipeline/test_patent_stage.py tests/unit/pipeline/test_markdown_helpers.py `
  tests/unit/routers/test_markush_router.py -q
```

## 每批验证门槛

1. 先运行该批次影响的最小现有测试集。
2. 运行 `uv run ruff check src tests`。
3. 运行改动路径的 `uv run ruff format --check ...`。
4. 运行完整 `uv run pytest tests/ -q`。
5. 使用 `rg` 确认旧内部导入路径归零。
6. 使用 `git diff --check` 检查空白和冲突标记。
7. 不因文件移动重复增加单元测试；只有发现未保护的公共契约时才补一个最低层测试。

## 非目标

- 不修改 Torch DBSCAN 或图像预处理算法。
- 不更换 MolDet、MolParser、RapidOCR 或 PaddleOCR 后端。
- 不改变 Extract ∥ Detection → Markdown → Patent 阶段顺序。
- 不启用当前未注册的 PersistStage。
- 不修改数据库 schema 或引入 migration。
- 不调整 REST 路径、请求体或响应体。
- 不借目录整理清理无关业务代码或批量删除测试。

## 风险与回滚

- `extraction.py` 从模块变为 package 时，测试 monkeypatch 路径最容易回归；先建立
  `extraction/__init__.py` 导出，再更新内部实现。
- Artifact 与 Run 互相导入较多，必须按“DTO → I/O → join → hydration → runner”的顺序移动，
  避免循环导入。
- `models` 改名影响面大，应作为最后一个独立批次，不和 Pipeline 搬迁混合。
- 每个批次使用独立 Conventional Commit；若失败，只回滚当前批次，不回滚已验证的前序整理。

建议提交序列：

```text
fix(pipeline): restore runner test baseline
chore(repo): ignore generated workspace files
refactor(detection): group pdf extraction components
refactor(pipeline): split artifact responsibilities
refactor(pipeline): consolidate run lifecycle modules
refactor(pipeline): group extract and patent modules
refactor(persist): separate active evidence storage
refactor(api): rename request response models to schemas
```

## 完成定义

- [x] `pipeline/` 根目录只保留稳定入口、组合根和跨阶段取消控制，不再平铺多种 artifact/run/patent 文件。
- [x] `pipeline/stages/` 只包含当前注册阶段。
- [x] 活动 SourceEvidence 写入不再隐藏在“未来 Persist”包中。
- [x] `Molecule` 成为检测、纠正、查询和持久化共用的唯一核心分子实体；`NormalizedMolecule` 已删除。
- [x] 所有生产代码使用新内部导入路径；仅明确公共路径保留兼容导出。
- [x] 完整 backend test 通过（`829 passed`）；本批分子实体回归通过（`155 passed`）。
- [x] 本批改动路径的 Ruff 与 format 检查通过；全仓已有静态遗留项单独保留。
- [x] 文档中的目录树、活动阶段和代码实际状态一致。

全仓库 Ruff/format 的既有遗留报告不属于本次布局改动，已在当前基线中单独记录，避免
借目录整理覆盖其他工作树变更。
