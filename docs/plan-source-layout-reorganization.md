# Plan: 整理 `src/mbforge` 包结构

> 目标：降低 `src/mbforge` 的目录认知成本，使目录位置能直接表达代码职责和生命周期。
> 本计划只做模块移动、命名和大文件按职责拆分；不改变 Pipeline 行为、数据库结构、
> API 请求响应、Torch DBSCAN、模型加载方式或产物格式。

## 当前基线（2026-09-13）

- `routers/`、`services/` 已基本按业务域分包，暂不重排。
- `core/`、`backends/`、`infra/`、`storage/` 一级边界基本清楚。
- 主要散乱点是 `pipeline/` 根目录：运行态、checkpoint、artifact、OCR、Patent 读侧混放。
- `pipeline/stage_artifacts.py` 已约 900 行，同时负责 branch I/O、join、转换和 hydration。
- `pipeline/detection/` 有 17 个 Python 文件，其中 PDF 提取的 5 个文件属于同一生命周期。
- `models/` 是 FastAPI/Pydantic schema，而 `infra/models/` 是模型运行时，名称存在歧义。
- `pipeline/persist/` 同时包含当前活动的 SourceEvidence 写入和未来未注册的 Persist 逻辑。
- 根目录缺少 `.gitignore`，`__pycache__` 等生成目录增加了视觉噪声。
- 仓库约定引用的 `TODO/INDEX.md` 当前不存在；涉及 Pipeline、storage、API 的搬迁前需恢复
  或确认新的架构索引位置。
- 当前完整后端测试基线是 `817 passed, 10 failed`。10 个失败来自
  `InitialForkRunner.__init__` 的 `self.run` 属性遮蔽 `run()` 方法；开始目录迁移前必须先恢复
  绿色基线。

## 整理原则

1. 先修复红色测试基线，再移动文件。
2. 一次只整理一个业务域或一种生命周期，不做全仓库大搬家。
3. 移动阶段不修改业务逻辑；行为优化单独提交。
4. 只有四个以上紧密相关文件时才新增子包，避免一文件一目录。
5. `__init__.py` 只导出稳定公共入口，不做隐式初始化或宽泛 `import *`。
6. 内部导入一次性更新；兼容 shim 只保留确实被外部入口依赖的路径。
7. 文件移动本身不新增测试；复用现有最低层契约测试。
8. 每个迁移批次独立提交、独立验证、可独立回滚。

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
    │   ├── cancellation.py
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

## 接口兼容策略

| 当前路径 | 目标路径 | 处理方式 |
|---|---|---|
| `mbforge.pipeline.runner` | 保持不变 | 继续作为 worker/router 的稳定门面 |
| `mbforge.pipeline.detection.extraction` | 同名 package | `extraction/__init__.py` 重导出当前公共函数和常量 |
| `mbforge.pipeline.stage_result` | `mbforge.core.stage_result` | 先更新内部导入；确认无外部依赖后删除旧 shim |
| `mbforge.pipeline.evidence_artifacts` | `pipeline.artifacts.evidence_models` | 迁移批次内更新生产代码和测试导入 |
| `mbforge.pipeline.stage_artifacts` | `pipeline.artifacts.*` | 按职责拆分，不保留新的单体聚合模块 |
| `mbforge.pipeline.run_artifacts` | `pipeline.artifacts.staging` | `runner.py` 可临时重导出必要公共函数 |
| `mbforge.pipeline.context` | `pipeline.run.context` | Stage 和 Runner 统一从新路径导入 |
| `mbforge.pipeline.patent_store` | `services.documents.patent_facts` | 读侧退出 Pipeline 层 |

## 实施批次

### 0. 恢复可验证基线

- [ ] 修复 `InitialForkRunner` 的属性/方法重名，使完整后端测试恢复绿色。
- [ ] 核对 `docs/plan-runner-split.md` 的“已完成”状态与当前代码一致。
- [ ] 恢复 `TODO/INDEX.md`，或更新仓库规范中的索引路径。
- [ ] 添加根 `.gitignore`，忽略 `.venv/`、`__pycache__/`、`*.py[cod]`、
  `.pytest_cache/`、`.ruff_cache/`、`frontend/node_modules/`、`frontend/dist/`。
- [ ] 记录完整测试、Ruff 和格式检查的真实基线。

### 1. 收拢 Detection extraction

- [ ] 建立 `pipeline/detection/extraction/` 子包。
- [ ] `coordinator.py` 接收当前 `extraction.py` 的 PDF 编排入口。
- [ ] `crop_processor.py` 接收 `CropProcessor`、`MolParserBatcher`、OCR crop 生命周期。
- [ ] `config.py` 接收 `ExtractionConfig` 和默认值。
- [ ] 移入 `page_detector.py`、`page_renderer.py`。
- [ ] 在 `extraction/__init__.py` 保留当前导入和 monkeypatch 路径。
- [ ] 删除旧的平铺 extraction 文件，确认不存在新旧双实现。

验证范围：

```powershell
uv run pytest tests/unit/pipeline/test_extract_molecules.py `
  tests/unit/pipeline/test_preprocess.py `
  tests/unit/pipeline/test_extract_text.py -q
uv run ruff check src/mbforge/pipeline/detection tests/unit/pipeline/test_extract_molecules.py
```

### 2. 建立 Artifact 子包并拆分 `stage_artifacts.py`

- [ ] 先移动纯 DTO：`evidence_artifacts.py` → `artifacts/evidence_models.py`。
- [ ] 提取通用 JSON I/O，不让 join 代码操作临时文件细节。
- [ ] 提取 Extract/Detection branch 的 save/load/path 逻辑到 `branch_io.py`。
- [ ] 提取 join、dedupe、bbox/页面约定校验到 `evidence_join.py`。
- [ ] 提取上下文重建到 `hydration.py`。
- [ ] 将 staging promote/cleanup/reap 移到 `artifacts/staging.py`。
- [ ] 删除 `stage_artifacts.py` 单体文件及内部私有函数跨模块调用。

验收要求：

- Join 的输入输出 DTO 不变。
- SourceEvidence SQL 行数、ID、排序和去重结果不变。
- staging 只能操作 `LibraryLayout` 验证后的文档目录。
- 现有 artifact、runner、重摄取和清理测试全部通过。

### 3. 收拢 Pipeline run 生命周期

- [ ] 移动 `PipelineContext` 和 `RunContext` 到 `run/context.py`，保留两个明确类名。
- [ ] `stage_checkpoint.py` → `run/checkpoint.py`。
- [ ] `run_ids.py` → `run/ids.py`。
- [ ] `cancellation.py` → `run/cancellation.py`。
- [ ] 更新 `runner.py`、worker、service、stage 导入。
- [ ] 保持 `pipeline.runner` 的公共符号、函数签名和结果字段不变。

验收要求：

- Extract ∥ Detection 固定并行关系不变。
- 一次 worker claim 只执行一个顺序 Stage 的语义不变。
- resume、retry、cancel、checkpoint 和 cleanup 行为不变。
- `runner.py` 保持薄门面，不重新吸收运行细节。

### 4. 建立 Extract 与 Patent 子包

- [ ] `extract_text.py` → `extract/text.py`。
- [ ] `ocr_artifacts.py` → `extract/ocr_artifacts.py`。
- [ ] `sections.py` → `patent/sections.py`。
- [ ] `artifacts.py` 中 Patent DTO → `patent/artifact.py`。
- [ ] 从 `PatentStage._associate_facts` 提取纯关联逻辑到 `patent/association.py`。
- [ ] `patent_store.py` → `services/documents/patent_facts.py`。

### 5. 分离活动 SourceEvidence 与未来 Persist

- [ ] 统计 `pipeline/persist/` 每个函数的当前生产调用方。
- [ ] 将 Join 当前使用的 SourceEvidence SQL 边界迁到 `storage/` 或明确的 artifact repository。
- [ ] 将未注册的 `PersistStage` 移到 `pipeline/persist/stage.py`。
- [ ] `pipeline/stages/` 只保留当前注册的 Extract、Detection、Markdown、Patent。
- [ ] 更新文档，明确哪些 persistence helper 仍为活动路径，避免把整个包误标成 dead code。

### 6. 可选：解决 `models` 与 `utils` 命名问题

- [ ] 确认 `src/mbforge/models/` 全部是 API schema 后，再整体改名为 `schemas/`。
- [ ] 仅对已经形成文件群的域建立 schema 子包，例如 `schemas/markush/`。
- [ ] `utils/file_scanner.py` → `services/documents/scanner.py`。
- [ ] `utils/capabilities.py` → `services/system/capabilities.py` 或 `infra/environment/`。
- [ ] 审计 `utils/runtime.py`，把 ID、async 和路径校验移动到各自真实归属。
- [ ] 不为只含一个小文件的领域新建目录。

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

- [ ] `pipeline/` 根目录只保留稳定入口和组合根，不再平铺多种 artifact/run/patent 文件。
- [ ] `pipeline/stages/` 只包含当前注册阶段。
- [ ] 活动 SourceEvidence 写入不再隐藏在“未来 Persist”包中。
- [ ] 所有生产代码使用新内部导入路径；仅明确公共路径保留兼容导出。
- [ ] 完整 backend test、Ruff、格式检查通过。
- [ ] 文档中的目录树、活动阶段和代码实际状态一致。
