# TODO 索引

> 2026-09-06 重建；同日晚间随分层治理双轨完成刷新。旧交接（文档预览渲染错误修复）已归档至 `assets/docs/archive/todo/2026-09-04-handover-preview-render-error.md`。
> 2026-09-08 刷新：已完成批次归档（source-evidence / services-layer 移至 archive，src-naming 文件删除关闭）；`compat-code-audit.md` 补列入表；esmiles 第二份页边界实现（欠账4）确已合并清理。

| 文档 | 状态 | 下一个动作 |
| --- | --- | --- |
| `patent-examples-stage-plan.md` | 历史方案；Examples 解析已并入 PatentStage，当前实现以 `patent-sql-unified-stage-plan.md` 为准 | 不再按本文件新增 ExamplesStage；名称转结构与后续关联另立计划 |
| `compat-code-audit.md` | A 类 12 项直接删除全部执行（2026-09-07，后端 7/前端 5，含 db 补列迁移、PyInstaller 死分支、molecule_store.ts molStore* 段）；验证通过（ruff/tsc/eslint/vitest/后端分批单测） | **B 类 7 项待迁移后删除**（Badge `variant`、SettingSection 别名、http barrel、AppError 旧位置参数、Toast 双签名、theme.css legacy 令牌、pdf 注释）；**D1 `huggingface-hub` 依赖未声明**（pyproject 零命中）；D2 已随 A1/A2 解 |
| `ocr-only-evidence-activity-plan.md` | 前置背景；全量 OCR、Join 单路径和 `table_span` 已落地，活动解析由统一 Patent 计划接管 | 不再按本文件新增 ActivityStage；仅保留真实 OCR 输入抽查作为后续验收 |
| `patent-sql-unified-stage-plan.md` | 已实施：任务边界为 `Extract ∥ Detection → Markdown → Patent`；measurement 直接来自 SQL `text_span`/`table_span`，表级 evidence 即可，不新增行列实体 | 真实 OCR `table.block_content` 抽查完成后收尾；Link/Persist、数据库/API 另立计划 |
| `patent-link-replacement-plan.md` | 已实施：删除失效 Link 实现，将确定性 measurement/assay/molecule-evidence 关联并入 Patent | 用真实样本验收 `patent_facts.json`；Persist 仍不注册 |
| `molparser-simplification-plan.md` | **修订版（2026-09-10）**：经评审核实后结论收敛——P0 **无需执行**（`postprocess_caption` 已接入，`_strip_trailing_sep` 是 MBForge 契约 + 回归测试）；P1 原方案（整链换 `parse()`）**不执行**（C1–C7：无 token 分数/crop、bbox 不可逐值对齐且 `evidence_id` 参与哈希、证据集合不可变、资源与取消回归、回滚矛盾）；已执行置信度字段收敛，移除 MBForge 自算的 `scribe_conf` / `composite_conf`，当前只保留结构字段与 MolDet 检测分；P1 缩小版仍仅作后续评估 | bbox/权重/API 评估已完成（计划 §6）：上游 `MolDetDetector` 不传 `iou`（0.45→ultralytics 默认 0.7）、无 warmup、无 `max_per_call`，替换必然改变框集合 → **P1 缩小版撤回**；除 P2 独立对比研究外，本计划无待执行项。另注：仓库无任何 commit，动大改前先做文件快照 |

## 已归档（2026-09-08 刷新）

| 原文档 | 归档路径 | 完成状态 |
| --- | --- | --- |
| `source-evidence-pipeline-spec.md` | `assets/docs/archive/todo/2026-09-08-source-evidence-pipeline-spec.md` | 批次 A-E 实施完成（2026-09-07）；接入持久化 `run_id`、Extract∥Detection 最小 fork/join、失败分支恢复、原子 join、`document.map.json`、全下游 `evidence_ids`、独立 `source_evidence` SQL；后端全量 920 passed, 16 skipped。无待办 |
| `services-layer-plan.md` | `assets/docs/archive/todo/2026-09-08-services-layer-plan.md` | 2026-09-06 双轨 A/B 全部落地，services 布局唯一依据；无待办。遗留仅附录 A 前端观察（63 组件直连 api/http）为独立专项 |
| `src-naming-migration.md` | （文件删除，职责并入分层治理，未归档） | 清单完成，P0-P2 逐行 verified；目标已由 services-layer-plan 拍板，随 services-layer 关闭 |

## 测试基线备注（2026-09-06 集成收官更新）

存量 skip 清理与旧契约测试删除后，实测全量 **`999 passed, 18 skipped, 0 failed`**（含 2 个 fitz 渲染合成 PDF 的 RapidOCR 恢复集成测试）；前端 vitest 325 全过、build 通过。`routers/system/settings.py`/`resource.py` RootModel 改造已落定，此前的瞬态失败归零。被删除的 12 个旧契约测试（test_pipeline_flow 六段流、persist_activities 旧表契约等）待 7 段语义重写后补回。

## 其他已知不一致

- **Patent 关联已收口（2026-09-10）**：Link 源码、发布/读取链和前端无效阶段入口已移除；Patent 仅将同时具备具体 SMILES 与已关联活性测量的候选写入现有 `molecules` 表；Persist 实现保留但未注册，后续只根据 `patent_facts.json` 重新设计其余投影。

- **MinerU/GLM-OCR OCR 后端已移除（2026-09-07）**：仅保留 PaddleOCR 云后端。删除范围：`backends/ocr/mineru.py`、`glmocr.py`、`/api/v1/ocr/test-mineru|test-glmocr` 探测端点、`extract_text.py` MinerU 批量路径、`OCRConfig` 的 `mineru_*`/`glmocr_*`/`upload_batch_size` 字段（batch 为 MinerU 专属，随之移除）、前端设置 UI/OcrConfigModal/i18n 入口、`usePdfOcr.ts` legacy parser 分支；`chain.DEFAULT_PRIORITY` 收窄为 `("paddleocr",)`。不做兼容：旧 settings.json 残留字段与含 `parser=mineru` 的存量工件视为无效。

- `AGENTS.md` 已同步当前有效流水线到 Patent；Link/Persist 保留为后续边界，不影响本阶段证据契约。
- ~~`markdown/esmiles_insert.py` 第二份页边界实现~~（欠账4，已核代码确无 `_collect_page_boundaries`，与共享 helper 合并清理，2026-09-08）。
- **bbox 坐标系与运行时读源（2026-09-08，2026-09-09 更新）**：Extract OCR 与 Detection raw branch 均按页面保存 PDF 左下坐标；Join 只校验统一坐标约定并将最终 `SourceEvidence` 写入 SQL，不做旧坐标转换。运行时不回退读取旧 `pages.json`/`detections.json`，SQL `source_evidence` 为唯一证据存储。**不生成 `bbox.json`**，也不回写两个原始工件；SQL 失败保留同一 `run_id` 的 raw branch 供重试，且阻断下游。分阶段 stage CLI（`mbforge-stage-*`）及 `pipeline/cli` 包整体删除，运行时一律走 runner。DTO（`PageFrame`/`ExtractArtifact`/`DetectionArtifact`/`DocumentEvidenceArtifact`/`CandidateArtifact`）位于 `pipeline/evidence_artifacts.py`。
- **PDF 覆盖层分子 bbox 读源切换（2026-09-08）**：`MoleculeOverlay`/侧栏"当前页分子"从 SQL-backed raw Detection 结果读取 molecule bbox；交互 `molecule_detections` 仍可追加未覆盖的当前页结果。页面与坐标约定保持 1-based API 页码、0-based Detection 页索引、PDF 左下坐标。
- INDEX 中"预览渲染错误"任务（后端 page 端点改读 JSON、doc `72e86100-...` 旧格式数据）未验证完成即归档，如复现可从归档文件恢复上下文。
