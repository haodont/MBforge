# Pipeline 数据正确性与韧性修复计划

> 状态：Batch A–C 已实施并验证（2026-07-27，见文末实施记录）；PIPE-04 由并行 Markush 审查工作承接，待协调  
> 创建日期：2026-07-27  
> 适用范围：`src/mbforge/pipeline/`、`src/mbforge/core/database.py` 及相关测试  
> 原则：先修数据正确性，再收敛重复逻辑，最后处理性能与取消韧性；每个阶段可独立验证、提交和回滚。

## 1. 目标

本计划处理当前 PDF pipeline 中已复核的数据错配、非原子补偿、上下文丢失、
Markush 关系缺失、重复匹配逻辑和长任务韧性问题。

完成后应满足：

- 分子检测、活动记录和证据表分别声明明确的页号语义，跨边界时显式转换，不再发生
  0-based/1-based 隐式比较。
- 文件持久化失败后的数据库补偿要么全部成功，要么全部回滚；补偿失败必须
  进入最终错误上下文，不能只写日志。
- MoleCode、活动行和分子候选使用完整、稳定且唯一的键关联，不使用
  SMILES 前缀或两份独立规则。
- Markush fragment 的未挂载状态可区分、可审查，并支持显式关联到 scaffold；
  不允许仅按同页或距离自动确认化学关系。
- 长文档处理的文本块读取、图片内存、取消检查和失败产物清理均有明确边界。
- 所有行为变化都有聚焦回归测试、可观测日志和原子提交。

## 2. 已复核问题基线

| ID | 优先级 | 结论 | 当前证据 | 目标状态 |
|---|---|---|---|---|
| PIPE-01 | P0 | 活性页号为 1-based，检测页号为 0-based，同页回退无法命中 | `persist_molecules.py` 使用 `primary.page` 直接查询由 `rec.page_num` 建立的索引；row label/完整 SMILES 对齐仍可工作 | 跨边界显式转换，同页回退恢复工作 |
| PIPE-02 | P1 | figure 与 table/table_row 的 `evidence.page` 基准不一致 | figure 写 0-based `primary.page`，table/table_row 写 1-based `page_num` | 所有 evidence 行采用 1-based 用户页号 |
| PIPE-03 | P1 | 文件写入失败后的六条补偿 DELETE 分别提交 | `_compensate_molecule_persistence()` 连续调用 `db.execute()` | 单一事务补偿，失败向上传播并带完整上下文 |
| PIPE-04 | P1 | Markush fragment 全部以 `scaffold_id = NULL` 写入 | `persist_markush_fragments()` 的 INSERT 显式写 NULL | 支持显式候选关系和人工确认挂载 |
| PIPE-05 | P1 | 分子 evidence 上下文忽略 LLM 增强后的 `role_contexts` | `_candidate_context_text()` 只读取 `context_texts` | 合并原始和增强上下文并保留来源 |
| PIPE-06 | P1 | MoleCode 位置允许 `smiles[:12]` 前缀命中 | `_find_molecode_position()` 使用前 12 字符查找 | 使用完整结构键或稳定 candidate ID 精确匹配 |
| PIPE-07 | P1 | 同一 canonical molecule 合并时，首次名称永久覆盖后续更优名称 | `_merge_detection()` 不更新 `NormalizedMolecule.name` | 按明确质量规则确定名称并记录候选来源 |
| PIPE-08 | P1 | 活性-分子行匹配逻辑存在两份实现 | `persist_molecules.py` 与 `persist_activities.py` 均定义 `_link_activity_to_molecule()` | 提取为单一纯函数，两条写入链共用同一结果 |
| PIPE-09 | P2 | 每个分子重复调用同页 `page.get_text("blocks")` | 分子循环内调用 `_nearby_page_text(page, ...)` | 每页读取一次 blocks，再对多个 bbox 过滤 |
| PIPE-10 | P2 | 整篇文档的 PIL crops 在一次批处理前全部驻留内存 | `crop_entries` 保存所有页的 `Image.Image` | 有界批次推理，批次结束立即释放图片 |
| PIPE-11 | P2 | 取消标记在正常完成或取消完成后不移除 | 模块级 `_cancelled_task_ids` 仅在重试时 `discard` | 任务终态统一清理，重复取消保持幂等 |
| PIPE-12 | P2 | 取消只在 stage 边界检查 | `run_pipeline()` 仅在执行 stage 前检查 | 长 stage 在页、批次、chunk 和重试边界检查 |
| PIPE-13 | P2 | 失败/取消/重导入可能留下孤儿 OCR 图片和 crops | runner 终态清理只覆盖临时 Markdown | 用本次运行清单或 staging 目录清理未提交产物 |
| PIPE-14 | P2 | 活性 LLM JSON 解析只识别小写 ` ```json ` fence | `_extract_json_from_response()` 的正则区分大小写且格式单一 | 支持常见 fence 变体，非法 JSON 显式报告 |
| PIPE-15 | P2 | LLM 输出长度低于输入 50% 就整体降级，缺少行为依据 | organizer 的短文档和长文档路径均使用固定比例 | 以结构完整性为主，长度仅作为观测信号 |
| PIPE-16 | P2 | `activity_count_written` 是运行时动态属性 | `PersistStage` 赋值，但 `PipelineContext` 未声明 | 在 dataclass 中定义并直接读取 |

### 明确排除的误报

以下项目不进入修复范围，但保留结论以避免重复调查：

- `DatabaseManager.get()` 并非每次创建新实例。当前实现带
  `@functools.lru_cache(maxsize=128)`，按解析后的 library root 缓存。
- “补偿删除 Markush 表时选错数据库”不符合当前实现。当前
  `DatabaseManager` 将 `_kb_path` 和 `_mol_path` 都指向统一的
  `.mbforge/library.db`，Markush 表也属于 molecule schema。需要修复的是多条
  DELETE 各自提交，而不是切换 `db="kb"`。

## 3. 页号契约

### 3.1 决策

定义两个不可混用的类型语义，并明确存储边界：

- `PageIndex`：用于 PyMuPDF、检测模型、`DetectionSource.page`、
  `molecule_detections.page` 和 detection-cache API，0-based。
- `PageNumber`：用于 Markdown `<!-- PAGE N -->`、`activities.page_num`、
  `evidence.page` 和用户界面，1-based。

不进行全仓库字段重命名。最小改动是在 pipeline 的持久化边界提供唯一转换函数，
例如 `page_index_to_number(page_index)`，并在写数据库和比较活动记录前转换。

`markush_scaffolds.page`、`markush_fragments.page` 和其他未声明字段不在本任务中
顺手改基准；先在后续 schema/API 设计中单独声明。历史库若已写入 0-based figure
evidence，本轮不盲目批量加一；先提供审计脚本按文档对照 `page_count`、Markdown
marker 和检测记录生成 dry-run 报告，确认后再单独迁移。

### 3.2 实施

1. 在 pipeline 公共模块新增带类型注解的转换函数，拒绝负数和非法值。
2. `persist_molecule_candidates()`：
   - 用转换后的 `primary_page_number` 构建/查询同页活动索引。
   - `molecule_detections.page` 继续写 `PageIndex`，不破坏 detection cache。
   - figure、table 和 table_row evidence 均写 `PageNumber`。
   - `used_pages` 也使用 `PageNumber`。
3. 逐个检查读取 `evidence.page` 的 API/UI，确保不再二次 `+1`；逐个检查
   `molecule_detections.page` 的调用方仍按 0-based 使用。
4. 增加历史数据审计命令，仅输出受影响文档和行数；迁移必须另立任务并支持
   `--dry-run`。

### 3.3 验收

- 检测页 `page_idx=0` 与活动 `page_num=1` 能命中同页回退。
- `molecule_detections.page` 对第一页仍存 0；figure、table 和 table_row evidence
  对第一页都存 1。
- 第二页及末页用例通过，防止只修第一页。
- `None` 页号不参与邻近匹配，且不会被默认成第一页。
- API 返回页号与 PDF Viewer 展示页一致。

## 4. 原子补偿与失败可观测性

### 4.1 决策

保留“数据库先提交、文件后写入、失败后补偿”的当前总体流程，避免本轮引入跨
SQLite 与文件系统的伪事务。只修复补偿本身的原子性和错误传播。

### 4.2 实施

1. 将按 `doc_id` 删除 molecule detections、evidence、links、Markush 和
   activities 的逻辑下沉为接收现有连接的单一函数。
2. `_compensate_molecule_persistence()` 使用一次 `db.transaction()`，在同一
   `mol_conn` 中执行全部 DELETE。
3. 任一 DELETE 失败时回滚全部补偿，不留下“删了一半”的状态。
4. 补偿异常不得吞掉：
   - 原始文件持久化异常保留为主异常。
   - 补偿异常以 exception chaining 或结构化 context 附加。
   - StageResult/SSE 至少包含 `PERSIST_DOCUMENT_FAILED`、原始异常类型和
     `compensation_failed=true`。
5. 记录每张表删除行数，成功时输出结构化汇总；不得记录真实分子数据。

### 4.3 验收

- 在第 1、3、6 条 DELETE 人工注入异常时，所有表行数均保持补偿前状态。
- 全部 DELETE 成功时，文档专属行被清除，共享 molecule 行不误删。
- 补偿失败时 pipeline 明确失败，错误上下文同时包含文件错误和补偿错误。
- 重新导入同一文档仍满足幂等性。

## 5. 统一分子、MoleCode 与活性关联

### 5.1 合并上下文（PIPE-05）

将 `_candidate_context_text()` 改为按固定顺序合并：

1. `context_texts`：原始提取上下文。
2. `role_contexts`：organizer 增强上下文。

去空白、稳定去重并分别限制单条和总长度。为避免后续无法判断来源，在 evidence
properties 或结构化字段中保留 `raw` / `reorganized` 来源；如果本轮不改 schema，
至少在拼接文本中使用稳定分隔标记，并在后续 schema 任务中拆列。

验收用例必须证明：

- 只有 `role_contexts` 时 evidence 不为空。
- 相同文本不会重复。
- 原始文本先于增强文本，截断稳定且不会切出超过数据库约束的内容。

### 5.2 精确 MoleCode 定位（PIPE-06）

1. MoleCode block 增加稳定 `candidate_id` 元数据；ID 由
   `doc_id + canonical_smiles + page_number + bbox` 确定性生成。
2. organizer 重排前后必须原样保留该 ID。
3. `enrich_molecule_contexts_from_markdown()` 优先按 candidate ID 精确匹配。
4. 兼容历史 Markdown 时，按完整 `%% smiles=<canonical_smiles>` 精确匹配；名称
   只能在结果唯一时作为最后回退。
5. 删除 `smiles[:12]` 逻辑，不保留模糊前缀兼容。

验收用例包含两个前 12 字符相同、后续结构不同的 SMILES，必须分别得到正确段落；
重复名称不能静默选择第一个块。

### 5.3 名称选择（PIPE-07）

新增纯函数对合并后的名称候选排序，不再让输入顺序决定结果。建议顺序：

1. 已规范化的 compound/example 标签。
2. 非空且通过标签规范化的 OCR 名称。
3. 其他非空名称。
4. 同等级取 composite confidence 更高者，再用原始顺序稳定打平。

`detection_names` 继续保存所有候选；最终选择规则和来源写入 properties，便于审查。
不得用 LLM 决定确定性的标签优先级。

### 5.4 单一活性匹配器（PIPE-08）

1. 新建无数据库副作用的公共 matcher，例如 `activity_matching.py`。
2. matcher 一次返回完整 `ActivityMatch`：
   `candidate_key`、`record_key`、`kind`、`page_number` 和理由。
3. `persist_molecules.py` 与 `persist_activities.py` 都消费同一批 match，不再各自
   维护 `used_rows`。
4. 匹配优先级保持现有行为：row label 精确匹配 → 完整 SMILES 匹配 → 同页回退。
5. 同页回退必须显式标记低置信度，不把邻近推断伪装成行级精确匹配。

验收要求同一输入下 activities 表、molecule activity 聚合字段和 evidence 指向
完全一致；重复行只能分配一次。

## 6. Markush fragment 关联闭环

PIPE-04 不是简单地把 NULL 替换为任意 scaffold ID。化学关系不明确时应继续复核，
遵循“不确定就隔离，不进入具体分子库”的现有边界。

### 6.1 最小数据模型

新增显式关系表，而不是复用 `markush_fragments.scaffold_id` 表达尚未确认的候选：

```text
markush_fragment_links
  link_id
  scaffold_id
  fragment_id
  site_label
  status          # suggested / confirmed / rejected
  evidence        # label/context/page/bbox references
  reason_code
  review_version
  created_at / updated_at
```

`markush_fragments.scaffold_id` 仅在关系被确认后同步，作为兼容查询字段；建议关系仍
保持 NULL。

### 6.2 关联规则

- 允许确定性生成“候选关系”的依据：同一文档、规范化 Formula/R-group 标签、
  明确文本定义和兼容 attachment map。
- 页面距离只能用于排序候选，不能自动确认。
- LLM 可提取文本中的 `Formula I: R1=...` 关系建议及证据片段，但不得直接更新
  `scaffold_id` 或创建化学键。
- 自动建议必须通过原子映射、价态和 RDKit sanitize 校验。
- 只有人工确认的关系可参与后续 mounting/enumeration。

### 6.3 验收

- 新 fragment 明确显示为 `unlinked` 或 `suggested`，不再把 NULL 当作无含义值。
- 单 scaffold、多个 R-group 和同名跨页 fragment 均可区分。
- 拒绝建议不会在重新导入后复活；确认关系有版本和审计记录。
- 未确认 fragment 永不进入具体 molecule 生成链。

此项涉及 schema 和审查接口，应与
`TODO/IMMEDIATE-ACTIONS.md` 中 Markush 完整实现计划协调；实现时只保留一个
schema 方案，避免两套关系表并存。

## 7. 性能、取消与产物生命周期

### 7.1 每页文本块缓存（PIPE-09）

- 每页进入分子循环前调用一次 `page.get_text("blocks")`。
- `_nearby_page_text()` 改为接收 blocks 数据，不再接收 page 并自行读取。
- 单元测试用调用计数证明一页多个分子只读取一次，且局部文本筛选行为不变。

### 7.2 有界 crop 批处理（PIPE-10）

- 引入可配置且有上限的 MolScribe batch size，默认值通过小规模基准确定，不在计划中
  猜测固定最优值。
- 每个批次完成：推理 → 保存 crop → 构建轻量 DetectionSource → `Image.close()` /
  释放引用，再进入下一批。
- `crop_entries` 不跨整篇文档持有 PIL 对象；只保留路径、bbox 和标量元数据。
- 性能验收同时记录峰值 RSS、总耗时和模型调用次数，避免以降低吞吐换取不可见收益。

### 7.3 协作式取消（PIPE-11、PIPE-12）

1. 用封装的 cancellation registry/token 替代路由直接访问模块私有 set。
2. 在 `run_pipeline()` 的 `finally` 中清除任务 ID，覆盖成功、失败和取消终态。
3. 路由在 pending future 尚未启动即取消成功时也显式清除注册项；不能依赖 runner
   的 `finally`。
4. 长 stage 增加检查点：
   - 文本/OCR：每页、每次重试前。
   - 分子提取：每页、每个 MolScribe batch 前后。
   - organizer：每个 chunk、每次 LLM 调用前后。
5. 已进入不可中断的第三方阻塞调用时不承诺立即强杀；调用返回后的第一个检查点必须
   停止后续写入。
6. 取消事件与普通失败使用不同 error code，队列最终状态保持 `cancelled`。

验收包括连续取消 1,000 个虚拟任务后 registry 大小回到 0，以及在多页提取、
批推理和多 chunk organizer 中分别取消。

### 7.4 失败产物清理（PIPE-13）

`storage/{doc_id}/images/` 和 `crops/` 在成功任务中是证据，不能无条件删除。采用：

- 每次运行写入 `storage/{doc_id}/.staging/{run_id}/` 或维护精确的本次写入清单。
- Persist 成功后原子提升或登记为正式 artifacts。
- 失败/取消只清理当前 `run_id` 的未提交文件。
- 重新导入先在新 staging 中生成，成功后再替换旧 artifacts；失败时保留上一版。
- 清理失败要记录精确路径和异常，但不得递归删除未验证的目录。

测试覆盖成功保留、失败清理、取消清理、重导入失败保留旧证据四种路径。

## 8. LLM 输出韧性与上下文声明

### 8.1 JSON fence（PIPE-14）

修复位置是 `extract_activities.py`，不是 organizer：

- 接受裸 JSON、`json`/`JSON`、带空格和换行的常见 fenced block。
- 只提取一个完整 JSON 数组；多个候选块或尾随非空内容必须显式告警。
- JSON decode、顶层类型和条目 schema 分开报错。
- 不使用正则“修复”缺括号、缺引号等无效 JSON，不静默猜测模型意图。

### 8.2 organizer 退化判断（PIPE-15）

移除“低于输入 50% 必然失败”的硬编码业务判定，改为结构不变量：

- PAGE marker 集合不减少。
- MoleCode block 数量、candidate ID 和完整 SMILES 元数据不减少。
- Markush 语义标记保护继续生效。
- 重复度和空输出检测继续生效。
- 长度比仅写入 metrics；如仍需阈值，必须由真实文档集测量后配置，并作为辅助信号，
  不能单独触发整体降级。

验收包含“合法精简到 40%”和“长度 90% 但丢失 PAGE/MoleCode”的对照用例。

### 8.3 PipelineContext 合同（PIPE-16）

在 `PipelineContext` dataclass 增加：

```python
activity_count_written: int = 0
```

同步 docstring，并将 `getattr(ctx, "activity_count_written", 0)` 改为直接访问。测试需
证明空活动和有活动路径均返回准确数量。

## 9. 实施顺序与原子提交

### Batch A：数据正确性阻断

1. `fix(pipeline): normalize persisted page numbers`
   - PIPE-01、PIPE-02。
2. `fix(pipeline): make persistence compensation atomic`
   - PIPE-03。
3. `refactor(pipeline): share deterministic activity matching`
   - PIPE-08，同时锁定页号契约。

Batch A 完成前不开始性能改造。

### Batch B：证据关联正确性

4. `fix(pipeline): preserve reorganized molecule context`
   - PIPE-05。
5. `fix(pipeline): match MoleCode blocks by stable identity`
   - PIPE-06。
6. `fix(pipeline): select merged molecule labels deterministically`
   - PIPE-07。
7. `fix(pipeline): declare persisted activity count`
   - PIPE-16。

### Batch C：运行韧性

8. `perf(pipeline): cache page text blocks and bound crop batches`
   - PIPE-09、PIPE-10；提交前提供测量结果。
9. `fix(pipeline): make cancellation cooperative and bounded`
   - PIPE-11、PIPE-12。
10. `fix(pipeline): clean only uncommitted run artifacts`
    - PIPE-13。
11. `fix(pipeline): validate LLM outputs by structure`
    - PIPE-14、PIPE-15。

### Batch D：Markush 关系

12. `feat(markush): persist reviewable scaffold fragment links`
    - PIPE-04；包含 schema migration、API、审查测试和文档。

每个提交只包含对应源代码、测试和直接相关文档。不得夹带当前工作区中已有的前端、
settings、health、server state 或其他未提交改动。

## 10. 验证矩阵

### 聚焦测试

计划新增或扩展：

- `tests/unit/pipeline/test_persist_molecules.py`
- `tests/unit/pipeline/test_persist_activities.py`
- `tests/unit/pipeline/test_activity_row_alignment.py`
- `tests/unit/pipeline/test_persist_stage.py`
- `tests/unit/pipeline/test_extract_molecules.py`
- `tests/unit/pipeline/test_extract_activities_helpers.py`
- `tests/unit/pipeline/test_organizer.py`
- `tests/unit/pipeline/test_normalize.py`
- `tests/unit/pipeline/test_runner.py`
- `tests/unit/pipeline/test_persist_markush.py`
- `tests/unit/pipeline/test_reingest_idempotency.py`

### 每个原子提交

```powershell
uv run ruff check <changed-python-files> <changed-test-files>
uv run ruff format <changed-python-files> <changed-test-files> --check
uv run pytest <focused-test-files> -q
git diff --check
```

Windows 下为 pytest 指定工作区内可写的 uv cache 和 `--basetemp`，避免把默认缓存
权限或临时目录错误误判为产品回归。

### Batch 结束

```powershell
uv run pytest tests/unit/pipeline/ -q
uv run pytest tests/integration/ -q
uv run ruff check src tests
uv run ruff format src tests --check
npm --prefix frontend run test
npm --prefix frontend run build
```

Markush 审查 UI/API 若在 PIPE-04 中发生变化，再运行 frontend lint、相关组件测试并
保存审查界面截图。

### 真实文档验收

选择至少三类脱敏测试文档：

1. 含 `<!-- PAGE N -->` 活性表和同页结构图。
2. 两个 SMILES 长前缀相同、MoleCode 分属不同段落。
3. 多页 Markush Formula、多个 R-group、含 OCR 图片。

记录：

- 活性精确匹配、同页回退、未匹配的数量。
- evidence 页号与 PDF Viewer 实际页的一致率。
- orphan/suggested/confirmed Markush fragment 数量。
- 取消延迟、峰值 RSS、crop 批次大小和清理文件数。

## 11. 可观测性

新增结构化 reason/error code：

- `PAGE_NUMBER_CONTRACT_VIOLATION`
- `ACTIVITY_ROW_MATCHED`
- `ACTIVITY_PAGE_FALLBACK`
- `ACTIVITY_UNMATCHED`
- `MOLECODE_ID_AMBIGUOUS`
- `PERSIST_COMPENSATION_FAILED`
- `MARKUSH_LINK_SUGGESTED`
- `MARKUSH_LINK_REVIEW_REQUIRED`
- `PIPELINE_CANCELLED`
- `ARTIFACT_CLEANUP_FAILED`
- `LLM_OUTPUT_STRUCTURE_LOST`
- `LLM_JSON_INVALID`

日志输出 doc/task/run ID、页号、计数和 reason code；不输出完整文献文本、真实库数据
或整段 SMILES 集合。

## 12. 回滚策略

- 页号修复：回滚代码不会自动改写历史数据；历史数据迁移单独提交、单独备份。
- 补偿修复：单提交回滚到旧补偿逻辑，不影响 schema。
- matcher/MoleCode：保留历史 Markdown 的完整 SMILES 兼容读取一版；candidate ID
  写入可独立回滚。
- staging artifacts：启用前保留旧路径读取兼容；回滚时只停止新 staging，不删除
  已提升的正式证据。
- Markush schema：迁移只新增表/列，不在 down migration 中删除用户审查数据；
  应用回滚后旧代码忽略新表。

## 13. 完成定义

只有同时满足以下条件，计划才可归档：

- PIPE-01 至 PIPE-16 均有对应提交、测试和验证记录，或有明确 ADR/TODO 说明为何
  延后。
- 所有 P0/P1 项完成；P2 若延期必须有测量数据、负责人和目标版本。
- 三类真实文档验收完成，没有活动错页、MoleCode 串段或失败后半补偿。
- 取消任务终态 registry 无残留，失败/取消不留下本次运行的孤儿图片。
- Markush fragment 未确认关系保持隔离，确认关系可追溯且不自动进入 molecules。
- `docs/wiki/pipeline.md`、相关 API 文档、`CHANGELOG.md` 和 `TODO/INDEX.md` 与实际
  行为同步。

## 14. 实施记录（2026-07-27)

### 已完成的原子提交（按落地顺序）

| 提交 | 覆盖项 | 说明 |
|---|---|---|
| `f339da4` fix(pipeline): select merged molecule labels deterministically | PIPE-07 | `normalize.py` 新增 `select_molecule_name()` 纯函数与 `name_candidates`/`name_selection` 溯源 |
| `d98b455` fix(pipeline): declare persisted activity count | PIPE-16 | `PipelineContext.activity_count_written` 声明,两处 getattr 改直接访问 |
| `73f43d2` fix(pipeline): normalize persisted page numbers | PIPE-01、PIPE-02 | 新增 `pipeline/pages.py`(`PageIndex`/`PageNumber`/`page_index_to_number`);figure/table/table_row evidence 与 `used_pages` 统一 1-based;`molecule_detections.page` 保持 0-based;新增 dry-run 审计脚本 `scripts/audit_page_numbers.py` |
| `ffe2815` fix(pipeline): make persistence compensation atomic | PIPE-03 | `delete_document_molecule_rows()` 单连接单事务补偿,失败回滚并向上传播;`persist_stage.py` 侧由并行提交 `57964df` 带入(内容同源) |
| `ffe7437` test(pipeline): align activity proximity test with page contract | 跟进 | 修正一个编码了旧错误页号比较的历史测试 |
| `a6407f6` fix(pipeline): match MoleCode blocks by stable identity | PIPE-06 | `make_candidate_id()`(SHA-256 前 16 hex);匹配顺序 candidate ID → 完整 SMILES → 唯一名称回退;删除 `smiles[:12]` 前缀逻辑 |
| `de4f4d1` refactor(pipeline): share deterministic activity matching | PIPE-08 | 新增 `activity_matching.py` 纯 matcher(`ActivityMatch` + `ACTIVITY_ROW_MATCHED`/`ACTIVITY_PAGE_FALLBACK`/`ACTIVITY_UNMATCHED`),两条写入链共用,`used_rows` 单一归属 |
| `58da312` fix(pipeline): preserve reorganized molecule context | PIPE-05 | `_candidate_context_text()` 合并 raw + reorganized,稳定去重、限长,`[context:reorganized]` 分隔标记 |
| `68db90f` fix(pipeline): validate LLM outputs by structure | PIPE-14、PIPE-15 | JSON fence 变体 + 分级报错(`LLM_JSON_INVALID`);移除 50% 长度硬规则,改 PAGE/MoleCode/candidate/SMILES 结构不变量(`LLM_OUTPUT_STRUCTURE_LOST`),长度比仅入 metrics |
| `1428929` fix(pipeline): make cancellation cooperative and bounded | PIPE-11、PIPE-12 | `cancellation.py` registry/token;终态统一清理;文本/分子/organizer 长 stage 检查点;`PIPELINE_CANCELLED` 独立错误码;1000 次取消幂等归零有测试 |
| `a5958bb` fix(pipeline): clean only uncommitted run artifacts | PIPE-13 | `run_artifacts.py` staging/promote/cleanup;成功保留、失败/取消清理当前 run、重导入失败保留旧证据(`ARTIFACT_CLEANUP_FAILED`) |
| `ce7a63f` perf(pipeline): cache page text blocks and bound crop batches | PIPE-09、PIPE-10 | 每页一次 `get_text("blocks")`;`moldet.molscribe_batch_size`(默认 16,上限 64,GPU 实测吞吐拐点);批次结束即释放 PIL |

### 验证结果(全部在最终工作区状态执行)

- `pytest tests/unit/pipeline/ -q`:233 passed,0 failed。
- `pytest tests/unit/ -q`:846 passed,4 failed —— 4 个失败全部位于并行 Markush 工作的在途文件(`tests/unit/chem/test_markush.py` ×2、`tests/unit/routers/test_chem.py`、`tests/unit/routers/test_molecule.py`),与本计划提交无关。
- `pytest tests/integration/ -q`:2 passed。
- `ruff check src tests`:18 个错误全部位于并行 Markush 工作文件(chem/markush、markush_enumerate、routers/markush 等);本计划提交的文件零错误。
- `ruff format --check`:仓库存在大量 HEAD 即有的格式漂移(82 文件);本计划新增/修改代码均 format-clean。
- `npm --prefix frontend run test`:315 passed / 1 failed —— 失败为用例硬编码 schema 版本 "11",并行 Markush 工作已升级 schema,属其在途状态。
- `npm --prefix frontend run build`:通过(3.09s,仅有既有的 chunk 体积警告)。

### PIPE-04 处置(延后,有明确承接方)

并行 Markush 审查工作(外部会话)已落地 `57964df`(review queue + 状态机 + API + 审查 UI,schema v11:markush_review_candidates / markush_evidence / markush_decisions)与 `c28debd`(attachment sites、R-group options、mount editor),仍在活跃推进中,且方向与本计划第 6 节一致(未确认隔离、人工确认挂载、审计可追溯)。按第 6 节"只保留一个 schema 方案"的约束,本计划未重复实现 `markush_fragment_links`,避免两套关系表并存。待该工作稳定后,需对照第 6.3 节验收清单逐项核对;若存在缺口(如 fragment↔scaffold 建议关系的显式持久化),另立补充任务。

### A-2 兼容层核查(2026-08-19,Task Group A)

对照第 6.3 节验收清单核对当前 schema v11 实现:

- `markush_fragments.scaffold_id` 是活跃、被使用的真实列(抽取时写入、`idx_mf_scaffold` 索引、`markush_mounts` FK、枚举读取),不是"确认后同步的兼容镜像列"。PIPE-R 第 6.1 节设想的 `markush_fragment_links` + `scaffold_id` 兼容同步**未实现**,假设已过时。关系确认状态由 `markush_sites.status` / `markush_mounts.status` 承载(站点级而非 fragment 级),方向与 6.3 一致(未确认隔离、人工确认、审计可追溯)。
- 结论:无残留兼容同步分支可删;`markush_fragments.scaffold_id` 保持现状。若后续需要 fragment↔scaffold 显式建议关系持久化,再单独设计,不复用该列。
- `activity_normalization.canonical_value_for_legacy`:审计确认**非死代码**——`persist_molecules.py`(4 处)与 `persist_activities.py`(2 处)两条持久化链共享的唯一"可比活性值"访问器,`value` 与 `value_canonical` 双字段语义被正常抽取路径承载(两者存同一 canonical nM)。**保留**,并在函数 docstring 标注"勿删"。原始删除尝试已回滚,回归测试全部还原。
- 配置(utils/config.py):删除启动期一次性旧配置迁移(`config.json`/`gui_state.json`/旧 platformdirs `settings.json`,约 80 行)。现仅读取 `~/MBForge/settings.json`;旧文件不再合并。已写入 TODO/INDEX.md 一次性备注(CONF-01)。
- OCR(backends/ocr/chain.py):MinerU→PaddleOCR→GLMOCR 回退链 + DoH pin 回退确认为**设计性韧性**而非兼容层,保留并写注释;旧 `mbforge_server`/`model_server` 回退残留已随主进程删除(见 CHANGELOG Removed)。
- ModelScope(core/model_locator.py):删除旧 SDK 缓存布局探测(`hub/{org}/{repo}` 与点号→`___` 编码 repo_name)。仅保留 canonical 布局:搜索 `models`/`hub/models`,快照 `""`/`models`/`hub/models`。旧布局命中者需重新下载(用户确认)。

### 已知遗留

- ~~历史库中 0-based figure evidence 未迁移~~ **已关闭(2026-07-29)**:
  `scripts/audit_page_numbers.py --dry-run` 对 `library_root` 全库审计,196 条
  figure evidence 全部符合 1-based 契约(`legacy_zero_based=0`,
  `unclassified=0`),无需迁移。
- `de4f4d1` 顺带带入了 `persist_activities.py` 中并行工作的两处未提交 hunk(review-queue 路由),内容已验证无误,但提交归属不干净,已告知。
- 真实文档验收(计划第 10 节三类脱敏文档)未执行,需要脱敏样本与人工核对,建议作为归档前的独立任务。
