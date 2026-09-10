# Markush 临时归档与分子活性正式接入计划

- 日期：2026-08-31
- 状态：已完成 Markush 归档和分子活性后端读接口；前端消费和其他优化待后续阶段
- 原则：先保留可用能力，再移出未接入的实验性代码；所有归档操作可逆。

## 决策边界

### 分子活性：保留并规划正式接入

本次不删除、不移动分子活性相关代码。当前活性链路已有阶段、解析、匹配、持久化和测试覆盖，后续以现有实现为基础收口正式接口：

- 保留 `src/mbforge/pipeline/extract_activities.py`、`activity_parsing/`、`activity_matching.py`、`activity_normalization.py`。
- 保留 `src/mbforge/pipeline/stages/activity_stage.py` 和 `persist_activities.py`。
- 保留 `src/mbforge/core/activity_service.py`，后续将其正式接入查询/服务边界。
- 保留现有活性相关路由、前端调用和测试，不在本次归档中改行为。

### Markush：只归档未接入的扩展内容

当前 Markush 主流程已经被路由、持久化、审查队列、站点/选项/挂接和前端界面使用，本次不关闭该能力。只归档没有生产调用者、仍是占位或未完成接线的三个扩展模块：

| 当前路径 | 归档路径 | 原因 |
| --- | --- | --- |
| `src/mbforge/chem/markush_advanced.py` | `docs/archive/code/markush/markush_advanced.py` | 高级约束/环系统接口未接入，基线枚举为空结果 |
| `src/mbforge/pipeline/extract_markush_definitions.py` | `docs/archive/code/markush/extract_markush_definitions.py` | 不在当前 `STAGES` 中，LLM 提取仍返回空结果 |
| `src/mbforge/core/markush_events.py` | `docs/archive/code/markush/markush_events.py` | 没有当前生产或测试调用者 |

归档不等于删除：使用 `git mv` 保留文件内容和历史。`extract_markush_definitions.py` 已有工作树改动，移动时原样保留，不覆盖、不回滚。

## 审计依据与状态映射

本计划以当前工作树的代码引用为准，并参考历史分析 [project-analysis-2026-08-19.md](../archive/analysis/project-analysis-2026-08-19.md)；历史报告中已完成或已失效的建议不直接当作当前任务。当前证据入口为 `src/mbforge/pipeline/runner.py:119` 的实际阶段注册、`src/mbforge/core/activity_service.py` 的活性读操作，以及 `src/mbforge/pipeline/persist_activities.py` 的活性持久化/审查分流。

每项建议使用以下状态，避免把“保留”“待审计”“已在工作树删除”和“已完成”混为一谈：

| 状态 | 含义 |
| --- | --- |
| 本轮执行 | 本次只做三个未接入 Markush 文件的可逆归档 |
| 既有改动待验收 | 工作树已经删除的旧模块，只核对引用、测试和构建，不重复操作 |
| 后续待审计 | 先确认活动调用者和兼容性，再决定删除、归档或补实现 |
| 测量后优化 | 先建立可重复基线和验收阈值，再改性能/结构 |
| 明确保留 | 活性链路、已接入 Markush 主流程和仍被调用的知识库能力 |

## TODOs

- [x] 建立 `docs/archive/code/markush/`，加入归档说明和精确回退映射。
- [x] 移动三个未接入 Markush 扩展文件，并确认活动源码无引用。
- [x] 确认分子活性文件仍在原路径，ActivityStage 到 PersistStage 的当前链路不变。
- [x] 运行 Markush/活性聚焦测试、Ruff 和差异检查。
- [x] 修正活动 Wiki 中将 `markush_events.py` 描述为当前运行时实现的内容。

## 其他删除与优化建议（纳入后续计划）

以下项目来自本次代码审计，已经按当前工作树重新分层。它们先进入同一计划，不在本次 Markush 归档中顺手扩大修改面。

### A. 工作树中已经在进行的删除：只验收，不重复操作

当前工作树已经删除、但尚未由本计划重新执行的内容包括：

- 旧的 pipeline 模块和阶段：`chunk_scheduler.py`、`classify.py`、`llm_client.py`、`molecode_insert.py`、`reorganize.py`、`density_stage.py`、`index_stage.py`、`reorganize_stage.py`。
- 旧实验脚本和结果：`experiments/e2e/`、`experiments/three_methods/` 中当前差异标记为删除的文件。
- 仅服务于旧实现的测试：`test_chunk_scheduler.py`、`test_llm_client.py`、`test_molecode_position.py`、`test_organizer.py`、`test_reorganize.py` 及已删除的旧 eval 入口。
- 已从界面移除的 `frontend/src/components/project/ReorganizedPane.tsx`。

后续只检查活动源码引用、测试入口和构建结果；不再次删除、不用本计划覆盖这些既有改动。如果发现仍有调用者，记录为阻塞项并单独恢复/迁移，不在本次归档中猜测处理。

### B. 低风险删除/归档候选：先做引用审计

1. **前端兼容包装**：审计 `frontend/src/api/http/molecule.ts`、`molecule_store.ts`、`molecule_chem.ts` 及其调用者。没有活动调用者的旧 barrel/deprecated wrapper 迁入归档；仍有调用者时先改为直接使用 `molecule_admin.ts` 等 canonical client，再删除包装层。
2. **废弃 CLI 入口**：`src/mbforge/__main__.py` 的 `--gui` 仅保留兼容警告。确认启动脚本和用户文档不再依赖后删除参数及对应分支。
3. **失败关闭的未实现接口**：盘点 `routers/chem.py`、`routers/sar.py` 和 `routers/detection_cache.py` 中的未实现端点。没有前端/外部调用者的接口直接归档；仍被调用的接口要么补齐真实实现，要么返回统一、可识别的错误，不保留“空成功”语义。
4. **兼容别名与旧路径**：审计 `routers/_path_utils.py`、`utils/paths.py`、`core/markush_review.py` 及旧存储 fallback。只有在无活动调用者、无需读取既有数据，并获得兼容性决策后才删除；数据库兼容分支需先有 ADR，不能凭清理目的直接改 schema。

### C. 结构和性能优化：以测量和验收为前置

1. **pipeline 边界收口**：以 `src/mbforge/pipeline/runner.py:119` 的四阶段 `Extract → Markdown → Activity → Persist` 为唯一运行事实，清除活动文档中的旧七阶段/`IndexStage`/`ReorganizeStage` 描述；知识库索引保持独立服务，不重新塞回 pipeline。`AGENTS.md:3` 仍有旧的 `Index` 描述，应在单独的文档变更中提出修正；本轮不修改现有贡献者指南。
2. **持久化和任务可靠性**：为当前进程内队列补充可恢复状态、重启后恢复策略、GPU 并发限制和失败重试观测；先补队列/删除顺序/DB 与文件晋升的失败测试，再决定是否引入持久队列，避免先增加基础设施。
3. **LLM 边界统一**：继续使用 `infra.llm` 作为基础设施入口，清除任何回流到 `agent` 包的重复工厂依赖；不新增第二套 provider 配置或 fallback 实现。
4. **前端请求与渲染**：统一 React Query 的 query key、失效策略和 SSE 更新入口；只有在性能采样确认瓶颈后才做虚拟滚动、`memo`/`useMemo` 或 PDF worker 化，避免用缓存和组件拆分掩盖数据一致性问题。
5. **大文件拆分**：`core/library.py`、`core/database.py`、`pipeline/extract_activities.py`、Markush 服务和主要前端页面体量较大。仅沿已存在的职责边界拆分，并为每次拆分保留一个消费者测试；不为“看起来大”而增加 facade、factory 或新层。
6. **真实样本质量门**：把扫描 PDF、GPU 模型、云 OCR/LLM、Markush 审查到枚举、活性证据展示纳入可重复的验收矩阵；当前只做文本/单元测试的结果不能标记为完整通过。

所有“测量后优化”必须先记录固定环境（Python 3.12、项目 `.venv`、`uv`，以及是否启用 GPU）、可提交的脱敏样本、连续至少 3 次的 p50/p95 基线和目标指标。最低验收线是行为测试零回归；若声称性能收益，目标必须达到相对基线至少 20% 改善，否则只保留结构性改动，不引入新缓存、worker、队列或组件层。当前没有合格基准样本时，先建立基准任务并停止在计划阶段。

### D. 已完成或暂不重复列入的事项

- `sections.molecule_count` 的废弃字段和相关索引统计已从当前实现清理，不再重复安排。
- 当前知识库索引仍被独立搜索/知识库接口使用，不因没有 `IndexStage` 就删除 `knowledge_index.py`。
- Markush 的保守分类、`review_required` 分流、审查队列和受控枚举属于已接入主流程，继续保留，不作为 dead code 清理。

## 后续执行顺序

1. 本次：完成三个未接入 Markush 文件的可逆归档，验证既有删除差异不受影响。
2. 下一阶段：按本计划完成分子活性契约、服务/API、前端消费和端到端验收。
3. 再下一阶段：逐项处理兼容包装、未实现接口和废弃 CLI；每项先做引用审计再决定删除或归档。
4. 最后：在真实样本和性能数据支持下处理队列可靠性、PDF/前端性能和大文件拆分。

## 分子活性正式接入路线

1. **稳定数据契约**：以现有 `ActivityRecord` 和 `activities` 表为基础，明确 molecule/doc/row/page 关联、原始值、标准化值、单位、置信度、证据位置和审查状态；禁止只保留模型推断而丢失原文证据。
2. **收口管线入口**：将 `ActivityStage` 的解析结果作为唯一管线输入，统一由 `PersistStage` 调用 `persist_activities`；保留空结果、重复摄入幂等和失败可重试语义。
3. **正式服务边界**：让 `core/activity_service.py` 承担数据库查询和审查操作，路由只做参数校验与编排；避免路由或前端重复实现 SQL/匹配规则。
4. **明确读模型与失败状态**：以 `activities` 为已写入记录，以 `review_items` 中的 `orphan_activity`/`low_activity_confidence` 为待处理记录，设计稳定的联合响应状态；解析失败必须保留文档、页码/表格位置和原始文本，不能用空列表掩盖失败。
5. **前端接入**：补齐稳定的 HTTP 响应模型、React Query 查询/变更钩子和证据展示；接口必须能区分已确认、待审查、未匹配和解析失败。当前 `routers/text.py` 只是按需解析预览，正式接入要补文档/分子查询消费方，而不是继续复制解析逻辑。
6. **验收**：用新 SQLite 验证端到端写入、重复摄入幂等、证据可追溯、单位/数值保真、异常不丢数据，并补齐 API 与前端消费方测试。聚焦测试入口包括 `tests/unit/pipeline/test_activity_normalization.py`、`test_activity_parsing.py`、`test_activity_row_alignment.py`、`test_extract_activities_helpers.py`、`test_persist_activities.py`、`tests/unit/routers/test_text.py`、`test_text_activities_endpoint.py`、`test_text_activity_selection.py` 和 `tests/integration/test_pipeline_flow.py`。

当前进度：管线写入链路沿用既有实现，`core/activity_service.py` 已提供联合读模型，
`GET /api/v1/activities/documents/{doc_id}` 已正式暴露持久化记录和活动审查记录。
前端消费、审查变更操作和端到端真实样本验收仍属于后续独立交付，不以接口已存在冒充全部接入完成。

## 验收与回退

- 归档目录中三个文件均存在且内容可读；`src/`、`tests/`、`frontend/` 的活动源码不再引用这三个未接入模块。
- `markush.py`、`markush_sites.py`、`markush_enumerate.py`、`markush_review.py`、`markush_service.py`、`persist_markush.py` 和 Markush 路由/UI 仍在原路径。
- 分子活性相关文件仍在原路径，当前 ActivityStage/PersistStage 测试不因归档失败。
- 只做聚焦验证；完整测试若受当前工作树既有改动影响，记录失败，不修改既有改动。

回退时按原映射反向执行：

```text
docs/archive/code/markush/markush_advanced.py
  -> src/mbforge/chem/markush_advanced.py
docs/archive/code/markush/extract_markush_definitions.py
  -> src/mbforge/pipeline/extract_markush_definitions.py
docs/archive/code/markush/markush_events.py
  -> src/mbforge/core/markush_events.py
```

## Final Verification Wave

- [x] 对 `src/mbforge/chem/markush_advanced.py`、`src/mbforge/pipeline/extract_markush_definitions.py`、`src/mbforge/core/markush_events.py` 执行 `test ! -e`，对三个归档目标执行 `test -s`，并用 `.omo/evidence/markush-archive-2026-08-31.txt` 的哈希证明内容未变。
- [x] `rg -n --glob '*.{py,ts,tsx}' 'markush_advanced|extract_markush_definitions|markush_events|MarkushDefinitionExtractor|validate_multi_attachment_mapping|enumerate_with_constraints' src tests frontend` 返回空；另一次 `rg` 确认 `extract_activities`、`ActivityStage`、`persist_activities`、`activity_service` 及活动 Markush主链路仍有引用。
- [x] 运行 `uv run ruff check src tests --select F401,SIM,C4`。
- [x] 运行 `uv run pytest tests/unit/chem/test_markush.py tests/unit/core/test_markush_sites.py tests/unit/core/test_markush_enumerate.py tests/unit/core/test_markush_review.py tests/unit/core/test_markush_review_service.py tests/unit/pipeline/test_persist_markush.py tests/unit/routers/test_markush_router.py tests/unit/routers/test_markush_enumeration_router.py tests/unit/routers/test_markush_sites_router.py tests/unit/pipeline/test_activity_normalization.py tests/unit/pipeline/test_activity_parsing.py tests/unit/pipeline/test_activity_row_alignment.py tests/unit/pipeline/test_extract_activities_helpers.py tests/unit/pipeline/test_persist_activities.py tests/unit/routers/test_text.py tests/unit/routers/test_text_activities_endpoint.py tests/unit/routers/test_text_activity_selection.py tests/integration/test_pipeline_flow.py -q`，预期退出码为 0；既有失败须单独记录。
- [x] 运行 `git diff --check -- docs/plans/2026-08-31-markush-archive-activity-integration.md docs/archive/code/markush`，并用 `git status --short -- <本次显式路径>` 记录本次路径变化；不要求整个已有脏工作树只剩本次文件。
- [x] 验证活动文件和已接入 Markush 文件均仍在原路径；`git diff --name-only` 不出现这些保留路径的本次改动。
- [x] 验证 `docs/wiki/markush-workflow.md` 将结构化事件和 Pipeline 报告标为未来契约，不再声称当前运行时写入。

## 非本次范围

- 不修改数据库 schema，不新增迁移。
- 不改动现有 Markush 审查与枚举主流程。
- 不实现分子活性前端页面和 React Query 消费，只完成本阶段的后端读接口。
- 不修改 `AGENTS.md` 或工作树中本次之前已有的实验文件、旧阶段和前端/文档改动；这些只在后续独立任务中按本计划处理。
