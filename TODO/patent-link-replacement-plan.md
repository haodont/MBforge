# Patent 内置关联与旧 Link 阶段清理计划

> 状态：已实施（2026-09-10）
>
> 目标：将本轮确定性关联收束到 `PatentStage`，删除当前失效的 Link 阶段代码，同时让 `patent_facts.json` 成为后续人工审核或 Persist 设计的唯一文档级输入。

> 实施结果：Patent 已完成三类确定性关联、共享标签正规化和非恢复性异常语义；旧 Link 发布/读取链已删除，Persist 保留但未注册，前端流水线只展示四个有效阶段。初始分支重试时，runner 会将已成功分支重新标定到当前 claim 的 run_id 后再 Join。

## 一、已确定的边界

当前有效流水线固定为：

```text
Extract ∥ Detection → Markdown → Patent
```

Patent 结束后流水线完成。Link 和 Persist 不注册、不执行；Patent 会将同时具备
具体 SMILES 和已关联活性测量的候选写入现有 `molecules` 表。Persist 的旧实现
暂时保留，等待独立设计其他投影。

本计划遵守以下约束：

- 不新增业务实体、数据库表、数据库字段或 `links.json`。
- 不把 Detection `candidate_id` 写入 `CompoundEntry.entity_id`；确定性关联成功后，
  `entity_id` 使用候选的 canonical SMILES（现有 `molecules.mol_id`）。
- 分子候选与 Patent entry 的关系通过现有 `entity_id` 和 `evidence_ids` 表达。
- SQL `source_evidence` 是唯一运行时 SourceEvidence 权威。
- 不使用页码接近、bbox 接近、字符区间、模糊包含或“最接近”规则。
- 不清理已有 `storage/{doc_id}` 运行数据，只停止旧产物的代码读取和生成。
- 不加入版本判断、旧格式兼容分支或历史数据迁移。

## 二、Patent 最终职责与数据契约

### 2.1 Patent 的输入

Patent 单次执行读取：

1. SQL 中当前 `doc_id` 的 `SourceEvidence`；
2. 当前文档的 Detection raw branch，通过现有 `load_detections()` 重建候选及其 SQL evidence IDs。

Patent 不读取 `activities.json`、`links.json`、`runs/current.json` 或 Markdown 字符映射。

Detection 候选必须满足以下来源约束后才能用于关联：

- 候选标签来自显式 OCR/文本标签，不从分子名称、SMILES 或邻近正文推断；
- 标签必须能回溯到候选自身的 Detection evidence；
- 候选 evidence ID 必须存在于当前文档的 SQL SourceEvidence 集合；
- `candidate.status == rejected` 或候选被判定为 Markush 时不得自动关联；
- 无标签、无 evidence ID、标签来源无法确认时保持未关联。

候选的 `refs`、`ocr_labels` 等现有字段只能作为标签载体，不能脱离其 SourceEvidence 来源单独作为可信关系。

### 2.2 Patent 的输出

继续发布：

```text
storage/{doc_id}/patent_facts.json
```

同时，对已确定关联且同时具备具体 canonical SMILES 与有效活性测量的候选，
在同一 Patent 阶段写入现有 SQLite `molecules` 表；不满足门槛的候选不入库。

保留现有主体结构：

```text
sections
entries
assay_methods
examples
measurements
issues
stats
```

不增加 `links`、`candidate_id` 或新的关联实体。

关联结果写入现有字段：

- `measurement.compound_entry_id`
- `measurement.assay_method_id`
- entry 的现有 `evidence_ids`
- 确定性关联成功且候选有 canonical SMILES 时填入现有 `entity_id`；否则保持 `null`

普通未关联是合法结果，不删除 fact，不使 Patent 失败。

只有同时满足以下条件的候选才进入分子数据库：

1. entry 与唯一 Detection candidate 已通过显式标签和当前 SQL evidence 关联；
2. candidate 有可持久化的具体 canonical SMILES，且不是 rejected/Markush；
3. 至少一条 measurement 已链接到该 entry，并包含数值或定性读数。

## 三、关联规则

### 3.1 标签规范化

entry、measurement reference 和 Detection candidate 必须使用同一套完整 token 规范化规则：

| 原始标签 | 规范化 key |
| --- | --- |
| `化合物20` | `20` |
| `化合物 20` | `20` |
| `compound 20` | `20` |
| `20` | `20` |
| `化合物20a` | `20a` |
| `20a` | `20a` |

规则要求：

- 先做 Unicode NFKC、首尾清理和空白归一；
- 移除明确的 `化合物`、`compound`、`cmpd`、`cpd` 前缀；
- 只接受完整的数字主体加可选单字母后缀；
- 使用完整正则匹配，不能用前缀包含；
- `20` 与 `20a` 不相等；
- `20a` 与 `20A` 保持区分；
- `Example 20` 不进入 compound 匹配。

实现上应收敛现有 `label_key_for()` 和 `normalize_reference_label()` 的规则，避免 core 与 activity parser 各自维护不同正则。规范化函数保持纯函数，不引入新实体。

### 3.2 measurement → compound_entry

1. 从 `measurement.provenance.reference_key` 取得规范化 key；
2. 仅接受 `reference_type == "compound"`；
3. 在当前文档 entry 索引中做完整 key 相等匹配；
4. 若全局有多个同 key entry，再使用 measurement evidence IDs 与 section evidence IDs 的唯一交集消歧；
5. 仍不唯一时不写 `compound_entry_id`，保留 measurement 并写固定 issue。

不得按 entry 列表顺序选第一个结果。

### 3.3 measurement → assay_method

1. 用 measurement 的 `evidence_ids` 与每个 section 的完整 `evidence_ids` 求交集；
2. 只有唯一 section 且该 section 只有一个 assay method 时写入 `assay_method_id`；
3. 必须使用 section 全量 evidence IDs，不能只使用 `title_evidence_ids`；
4. 多 section、无 section 或多个 assay method 时保持空值并写 issue。

### 3.4 compound_entry → Detection candidate

1. 从候选已有的显式 OCR/文本标签中提取标签；
2. 通过统一标签函数得到 candidate key；
3. 与 entry `label_key` 做完整相等匹配；
4. 候选必须唯一、非 rejected、非 Markush，并且拥有至少一个当前 SQL evidence ID；
5. 将候选 Detection evidence IDs 去重后并入 entry 现有 `evidence_ids`；
6. 关联成功且候选有 canonical SMILES 时写入现有 `entity_id`，不新增候选字段；
7. 多候选、无标签、标签来源不可信或无 evidence 时不合并。

这里的“唯一”指规范化标签对应唯一的具体 `NormalizedMolecule` 候选，不是唯一 bbox、唯一页码或唯一字符串片段。

## 四、固定 issue code

三类关联均必须把原因写入现有 `PatentFactsArtifact.issues`，不能只留下空字段：

| code | 含义 |
| --- | --- |
| `compound_reference_unresolved` | measurement 没有可解析或明确的 compound reference |
| `compound_entry_ambiguous` | reference key 对应多个 entry，无法唯一消歧 |
| `assay_method_unresolved` | measurement 无法唯一归属 assay method |
| `molecule_label_unresolved` | Detection 候选没有可验证的显式标签 |
| `molecule_candidate_ambiguous` | 一个标签对应多个具体候选 |
| `molecule_candidate_rejected` | 候选为 rejected 或 Markush |
| `molecule_evidence_unresolved` | 候选缺少当前 SQL evidence ID |
| `dangling_fact_reference` | 关联目标不存在于当前 Patent facts |

issue 至少包含：`code`、`message`、`severity`、`evidence_ids`、`related_fact_id`。沿用现有 issue 结构，不新增 Issue 实体。

## 五、旧 Link 代码清理

### 5.1 必须删除

- `src/mbforge/pipeline/stages/link_stage.py`
- `src/mbforge/core/linking.py`
- `tests/unit/pipeline/test_link_stage.py`
- `LinkArtifact`
- `load_links()`

### 5.2 必须清理但不删除 Persist 实现

- `run_artifacts.publish_run()` 的 `links` 参数、Link 发布分支和 `links.json` manifest 记录；
- `run_ids.py` 的 Link artifact 映射、`PUBLISHING_STAGES` 中的 Link 项及 Link 专属 stage-map 处理；
- `patent_store.py` 的 `_load_run_json()` 和 Link 专属导入（确认无其他调用者后删除）；
- `persist_stage.py` 的 `@register(after="link")` 及 `register` 导入；Persist 类保持可被未来独立调用，但不注册；
- `artifacts.py` 中只被 Link 使用的 `RunManifest`、`RunPointer`、`StageRunPointer`，仅在引用审计确认无其他调用者后删除；
- `run_artifacts.py` 中只服务运行目录 Link 发布/回收的部分；保留 Extract/Detection 分支回收所需逻辑；
- 旧 `link` 键只忽略，不读取、不回写、不参与回收；不能因发布 Patent 而把未知 Link 键重新写回 stage map。

删除后执行一次全仓库引用审计，确认没有源码、测试、工具或文档仍引用 Link 专属接口。不得因为清理 Link 而删除 Markush review 的 `markush_link` 业务含义或 Notes 链接。

## 六、前端与文档同步

流水线 UI、SSE 阶段集合和重试选项统一只保留：

```text
extract / detection / markdown / patent
```

清理 `activity`、`link`、`persist` 的阶段显示和重试入口；保留非流水线的 review/Notes link 文案。

同步更新 README、`docs/wiki/pipeline.md`、`TODO/INDEX.md`：

- Patent 是当前流水线终点；
- Patent 已负责确定性文档内关联；
- 当前 Link 源码和产物不再存在；
- Persist 实现保留但未注册，后续需重新设计输入契约；
- 不描述旧 `links.json` 仍可被读取。

## 七、异常与运行语义

- 前置 Join/SQL 失败仍在 Patent 之前阻断；Patent 不重复创建前置失败分支；
- Patent 读取到空 Detection 候选时正常生成 facts，只产生未关联结果；
- 普通关联歧义、Markush、rejected、缺少标签只产生 issue，不使阶段失败；
- Patent 内部真正异常必须返回不可恢复的 `error`，不能返回会被 runner 当作成功继续执行的 `warning/recoverable=True`；
- 成功发布后仍使用现有文档根路径原子替换；`run_id` 只保留为本次运行元数据，不用于跨 artifact 版本一致性判断。

## 八、实施顺序

### 批次 1：先清理失效 Link 表面

1. 删除 Link stage/domain/test；
2. 清理 artifact publisher、run ID 映射和 Patent store；
3. 移除 Persist 注册装饰器；
4. 清理前端无效阶段；
5. 运行引用审计，确认只剩非流水线 link 语义。

### 批次 2：统一标签规范化

1. 统一 entry label 与 activity reference 的完整 token 规则；
2. 支持中文 `化合物` 前缀；
3. 保持后缀大小写区分；
4. 更新 entry ID 的生成输入；
5. 先完成规范化单测，再接入 Patent 关联。

### 批次 3：在 PatentStage 内完成三类关联

1. `_extract()` 只加载一次 SQL evidence，并加载 Detection candidates；
2. 先完成 sections、entries、assay methods、measurements 的基础生成；
3. 建立 entry、section、assay method、candidate 索引；
4. 按第三节规则填充现有关联字段和 entry evidence IDs；
5. 统一写入 issue code；
6. 组装并发布唯一的 `patent_facts.json`；对满足门槛的候选写入现有 `molecules` 表。

### 批次 4：更新说明和验收

1. 更新 README、wiki 和 TODO 索引；
2. 对真实样本重新运行 Patent；
3. 检查 `patent_facts.json` 中未关联事实仍存在；
4. 检查不存在新的 `links.json`，但不删除旧运行目录；
5. 完成最小后端和前端验证。

## 九、测试与验收

只扩展现有最近测试位置，不为每个删除文件单独新增测试。

### 后端必要测试

- 标签契约：`化合物20`、`compound 20`、`20` 相同；`20` 与 `20a` 不同；`20a` 与 `20A` 不同；`Example 20` 不进入 compound 匹配；
- Patent 关联：唯一 measurement→entry、唯一 measurement→assay_method、唯一候选 evidence 合并；
- 分子入库门槛：只有具体 SMILES 与已关联有效 measurement 同时存在时写入 `molecules`，
  结构单独存在时不写入；
- 保留数据：多候选、Markush、rejected、无标签候选不关联且原 fact 保留；
- 证据边界：合并到 entry 的候选 evidence ID 必须存在于当前 SQL SourceEvidence；
- 错误边界：Patent 真异常返回不可恢复 error，不被记录为成功；
- 阶段契约：有效阶段严格为四阶段，Link 不再注册或发布。

### 前端必要验证

- `npm exec -- tsc --noEmit`
- 受影响组件 ESLint
- `npm run build`

### 验收命令

```text
uv run pytest tests/unit/pipeline/test_patent_stage.py tests/unit/pipeline/test_activity_normalization.py tests/unit/pipeline/test_stage_registry.py tests/unit/pipeline/test_stage_artifacts.py -q
uv run ruff check src tests
npm exec -- tsc --noEmit
npm run build
```

最终检查：

```text
rg "LinkArtifact|load_links|links\.json|after=\"link\"|core\.linking" src tests frontend docs TODO
```

允许出现的例外仅限历史说明、已明确的删除记录和非流水线业务词；不得存在可执行的 Link 导入、注册、发布或读取路径。

## 十、回退方式

本计划只删除当前失效源码和引用，不修改数据库、不删除历史 storage 数据。若验证失败，可通过 Git 恢复本次删除和 Patent 代码改动；历史 `links.json` 不作为运行时输入恢复。
