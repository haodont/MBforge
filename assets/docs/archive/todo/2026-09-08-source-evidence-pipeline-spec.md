# 页面源证据与并行提取流水线规范

> 记录日期：2026-09-07  
> 状态：**批次 A-E 实施完成；全量后端验证通过（920 passed, 16 skipped）**。  
> 本文同时记录目标契约与当前实施状态；未完成部分的运行时行为仍以
> `docs/wiki/pipeline.md` 与代码为准。

## 1. 目标与核心决策

MBForge 以 `SourceEvidence` 作为唯一的页面源证据对象，表达最底层的
`{位置：内容}` 映射。它只由 Extract/Detection 从原始文本或图像中产生，
内容保持原样且对象不可修改。它同时支持两个方向：

- 从页面位置组织文本、图片和分子，生成可读 Markdown；
- 从 Candidate、专利条目、活性记录或 Markdown 内容反查原页位置。

不新增 `SourceAnchor`、`LayoutItem`、`EvidenceNode` 或通用证据基类。
Patent、Activity、Candidate 等都是基于 `SourceEvidence` 构建的二级对象。
解释结果不写回、也不复制成新的 `SourceEvidence`，只通过 `evidence_id`
引用底层证据。

Extract 与 Detection 都直接读取源 PDF，业务上互不依赖：

```text
PDF
├─ Extract   ──→ text/table/image SourceEvidence ─┐
└─ Detection ──→ molecule SourceEvidence + Candidate ├─→ join → Markdown
                                                        ↓
                         Patent → Examples? → Activity → Link → Persist
```

两个分支只写各自 artifact。join 验证并合并后，统一发布 `bbox.json`；Markdown
只负责把证据按位置关系投影为 `document.md` 和 `document.map.json`。

## 2. 当前代码基线

### 2.1 当前 `SourceEvidence`

`src/mbforge/core/evidence.py` 当前已经把位置与内容合并为一个冻结 dataclass：

```text
SourceEvidence
├─ doc_id
├─ page
├─ bbox
├─ evidence_id
├─ raw_text
├─ coref
└─ kind
```

批次 A 已完成以下修复：

- `create()` 按固定位置字段生成 ID，不再只哈希 `dict` 的字段名；
- `to_dict()`/`from_dict()` 完整保留 `coref` 和 bbox；
- 恢复仍被 Patent/Activity/Link 使用的 `_stable_id`；
- 增加页码、bbox、内容和相对路径校验；
- 新增 `tests/unit/core/test_evidence.py`，保护位置 ID 和 round-trip 契约。

当前实现已冻结这个边界：`SourceEvidence` 创建和反序列化都要求非空 bbox。
旧 Patent/Activity 序列化记录中的嵌入式 `evidence` 字段不属于当前 DTO，直接视为
无效；需要从当前 Extract/Detection 产物重新生成。新二级对象只保存已有的
`evidence_ids`，不能重新实例化或注册为 `SourceEvidence`。

### 2.2 当前流水线

- runner 为 Extract/Detection 提供固定初始 fork，后续仍以单一 `next_stage` 逐阶段重新入队。
- 两个 producer 各自写 run-scoped artifact；join 校验通过后才发布 v2 `bbox.json`。
- MarkdownStage 已接管 v2 路径的最终 `document.md` 写入；rough Markdown 仍是阶段内临时值。
- Detection 初始分支直接读取 PDF，不依赖 `ctx.extracted`；不存在旧顺序恢复路径。
- `_run.json` 持久化 `run_id` 和阶段状态；失败分支可单独重试，旧无 `run_id` 的 summary 明确拒绝。

Examples、Link 和 source_evidence 查询边界已接入：二级对象只保存已存在的
`evidence_ids`，查询服务只从独立的 `source_evidence` 表构造 `SourceEvidence`。

## 3. `SourceEvidence` 目标契约

### 3.1 字段语义

```text
doc_id: str
page: int                               # 1-based
bbox: tuple[float, float, float, float] # SourceEvidence 必须有值
evidence_id: str
raw_text: str = ""
coref: str = ""
kind: str
```

- `raw_text`：源文档中的原始文字，不做语义改写。
- `coref`：证据内容对应的资源相对路径，例如分子裁剪图或页面图片；必须位于
  `LibraryLayout` 管理范围内，不保存绝对路径、URL 或二进制内容。
- 分子编号等 OCR 指代符不属于 `coref`，保存在 Candidate 的 `refs` 中。
- `bbox` 是 SourceEvidence 的必填字段；格式必须是有限的四元
  `(x0, y0, x1, y1)`，且满足坐标顺序和页面边界约束。
- `raw_text` 与 `coref` 至少一个非空，禁止创建只有位置、没有内容的空证据。
- 缺少 bbox 或 bbox 格式错误的源记录不能形成 SourceEvidence；二级对象不走
  SourceEvidence 构造路径，只能引用已有 evidence_id。

首版 `kind` 只保留当前已有值，并为分子区域增加一个值：

- `text_span`
- `table_cell`
- `image_region`
- `ocr_label`
- `molecule_region`

不在本次把这些值重命名为 `text/table/image/molecule`，避免无收益迁移。

### 3.2 坐标契约

- bbox 单位统一为 PDF point，原点在左下，x 向右、y 向上。
- bbox 对应应用页面旋转后的视觉页框；每页 `width/height/rotation` 只在 page frame 保存一次。
- writer 必须在 artifact 输出边界完成坐标转换；reader 不再按来源猜测或翻转。
- 必须满足 `page >= 1`；必须提供 bbox，并满足
  `0 <= x0 <= x1 <= width`、`0 <= y0 <= y1 <= height`。
 `bbox=None` 直接视为无效输入，不能构造当前 `SourceEvidence`；
 `SourceEvidence.create()` 和 `from_dict()` 均直接拒绝。
- JSON 使用四元素数组，Python 对象使用固定顺序 tuple；序列化不得改变数字顺序。

### 3.3 稳定 ID

`evidence_id` 只标识来源位置，不标识解释结果。canonical bbox 非空时，生成输入固定为：

```text
doc_id \x1f page \x1f kind \x1f x0 \x1f y0 \x1f x1 \x1f y1
```

规则：

- bbox 先量化到 0.01 point，再按固定字段顺序编码为 UTF-8；
- 使用 `sha256(...).hexdigest()[:32]`；
- ID 不包含 `raw_text`、`coref`、置信度、审核状态或 E-SMILES；
- 同一位置重新提取仍得到同一 ID；同页不同 bbox 必须得到不同 ID；
- `create()`、`to_dict()`、`from_dict()` 是唯一构造与 round-trip 契约；
- `_stable_id` 继续只用于现有 Patent/Activity 业务 ID；它不参与 SourceEvidence ID。

旧的 page-only 记录没有几何身份，不生成新的 canonical evidence ID；它们不能进入
`bbox.json v2`，必须从 Extract/Detection 的原始证据重新解析并引用 canonical
`evidence_id`。

### 3.4 不可变边界

Candidate 状态、E-SMILES、模型置信度、审核结论、Patent/Activity 解释结果不得塞入
`SourceEvidence`。重新处理生成新的 artifact，不原地修改已经被下游引用的证据。

## 4. Artifact 契约

所有 artifact 使用合法 JSON、显式 `schema_version` 和 `extra="forbid"` DTO。
并行分支不得写共享日志或共享 artifact；运行信息继续使用现有阶段 summary 和日志机制。

### 4.1 ExtractArtifact

```json
{
  "doc_id": "example",
  "run_id": "run-id",
  "pages": [
    {"page": 1, "width": 612.0, "height": 792.0, "rotation": 0}
  ],
  "evidence": [
    {
      "doc_id": "example",
      "page": 1,
      "bbox": [72.0, 700.0, 540.0, 720.0],
      "evidence_id": "...",
      "raw_text": "Example text",
      "coref": "",
      "kind": "text_span"
    }
  ]
}
```

Extract 只保留 page frame 与 `text_span/table_cell/image_region/ocr_label` 证据，不再持久化：

- 可由 `evidence[].raw_text` 拼回的整文 `raw_text` 或 `page.text` 副本；
- OCR 请求/响应原文、重试和耗时明细；
- rough Markdown；
- 已由 `coref` 指向的图片二进制或重复路径列表。

### 4.2 DetectionArtifact

```json
{
  "doc_id": "example",
  "run_id": "run-id",
  "pages": [
    {"page": 1, "width": 612.0, "height": 792.0, "rotation": 0}
  ],
  "evidence": [
    {
      "doc_id": "example",
      "page": 1,
      "bbox": [100.0, 400.0, 220.0, 520.0],
      "evidence_id": "...",
      "raw_text": "",
      "coref": "storage/example/crops/mol-0001.png",
      "kind": "molecule_region"
    }
  ],
  "candidates": [
    {
      "candidate_id": "candidate-0001",
      "evidence_ids": ["..."],
      "confidence": 0.92,
      "status": "accepted",
      "esmiles": "...",
      "refs": ["1"],
      "reject_reason": null
    }
  ],
  "molecule_stats": {}
}
```

- Detection 直接读取 PDF，不读取 ExtractArtifact 或 `ctx.extracted`。
- MolDet 输出 bbox；裁剪、MolParser 和 RapidOCR 仍属于 Detection 内部流程。
- MolDet 只要产生分子候选，就必须先把对应 crop 存入本次 run 的 staging archive
  或 canonical `crops/`；保存失败是 Detection error，不得生成无图候选。
- 裁剪图路径只保存在对应 `molecule_region.coref`，且 writer 必须确认文件已归档；
  Candidate 不重复保存 bbox 或路径。
- `molecule_region` 的 crop 和 bbox 是最底层结构证据；OCR `raw_text`、MolParser
  的 E-SMILES/SMILES、置信度和状态都是可出错的解释层字段，不能覆盖或替代它。
- `refs` 只保存非空、去重后的分子指代符；启发式排序不能改变 Candidate 身份。
- 成功但零候选时仍写合法空 artifact。
- Detection 不生成 rough/final Markdown。

### 4.3 DocumentEvidenceArtifact 与 `bbox.json`

Extract、Detection 都成功后，join 校验 `doc_id/run_id/page frame/evidence_id`，再原子发布：

```json
{
  "doc_id": "example",
  "run_id": "run-id",
  "conventions": {
    "unit": "pdf-points",
    "origin": "bottom-left",
    "page": "1-based",
    "bbox": "[x0,y0,x1,y1]"
  },
  "pages": [],
  "evidence": [],
  "candidates": [],
  "molecule_stats": {}
}
```

规则：

- 只有 join 可以写 `storage/{doc_id}/artifacts/bbox.json`；
- 使用临时文件加原子替换，不再 read-modify-write section merge；
- `evidence[]` 中每条记录必须是原始文本/图像 SourceEvidence，且 bbox 存在、
  格式正确并落在对应 page frame 内；
- `candidates[].evidence_ids` 必须全部指向同文件中的有效 SourceEvidence；
- 重叠的 image、text、molecule 证据全部保留；重叠不等于重复；
- 是否在 Markdown 中抑制重复展示属于投影规则，不得删除 canonical evidence；
- v1 payload 不属于当前契约；重新处理时必须直接生成 v2，禁止适配或迁移。

## 5. 并行执行、checkpoint 与恢复

首版只实现一个固定 fork/join，不建设通用 DAG、工作流 DSL 或第三方调度器。

### 5.1 最小执行模型

```text
initial branches: extract || detection
join requires:    extract=success AND detection=success
then:             markdown → patent → examples? → activity → link → persist
```

- runner 为一个未完成提交生成并持久化唯一 `run_id`，阶段重试和分支恢复时复用；
  从头启动且上一次已完成全部有效阶段时，先清理旧 staging 状态再生成新的 `run_id`。
- 初始阶段用标准库 `ThreadPoolExecutor(max_workers=2)` 并行执行两个独立 stage context；
  两个 context 只共享只读的 PDF 路径、library root、doc_id、run_id 和取消信号。
- Detection 的 GPU 调用继续经过现有 `gpu_gate()`。
- 每个分支独立写 `{run_id}/extract.json` 或 `{run_id}/detection.json` 和阶段 summary。
- 一个分支失败时保留另一分支成功 artifact；重试只运行失败分支。
- join 只接受同一 `run_id` 的两个 success artifact。
- “零候选”是 Detection success；模型异常、artifact 缺失或坐标校验失败是 error。
- Detection 失败时不得生成或覆盖最终 Markdown。

### 5.2 checkpoint

checkpoint 至少记录：

```text
schema_version
run_id
stages.extract.status
stages.detection.status
stages.markdown.status
...
```

状态只需 `pending/running/success/error`。旧线性 checkpoint 返回明确的
`INCOMPATIBLE_CHECKPOINT`，由操作人员重新提交，不自动从头循环。

## 6. Markdown 编排与反向映射

### 6.1 确定性编排

MarkdownStage 只读取 `DocumentEvidenceArtifact`：

- Extract 产生的文本证据顺序作为页面文本主序，不做全局文本重写；
- 非文本证据使用 `(page, -y1, x0, -y0, x1, kind_rank, evidence_id)` 稳定排序；
- 每个非文本证据的插入槽位，由其几何排序键之前出现的文本块数量决定；
- 同一槽位按 `image_region → molecule_region → evidence_id` 排序；
- 无文本页直接按上述几何键输出图片和分子块；
- 相同输入不受线程完成顺序和 artifact 原始数组顺序影响；
- 不使用语义相似度、最近文字、跨页归属或页末兜底。

Candidate 只有在 `status == "accepted"` 且 E-SMILES 有效时才渲染；rejected 或无有效
E-SMILES 的 Candidate 继续保留在 artifact 和 review/persist 链路。

rough Markdown 只能是 MarkdownStage 内部临时值。复用并重构现有
`insert_esmiles_blocks`，不新增第二个插入器。

### 6.2 最终产物

标题补齐、公式清洗等变换全部完成后，再计算 Markdown offset 并一次发布：

```text
storage/{doc_id}/
├─ document.md
└─ document.map.json
```

`document.map.json` 最小结构：

```json
{
  "schema_version": 1,
  "doc_id": "example",
  "blocks": [
    {
      "block_id": "block-0001",
      "char_start": 0,
      "char_end": 12,
      "evidence_ids": ["..."]
    }
  ]
}
```

`char_start` 为包含端，`char_end` 为不包含端；offset 基于最终 UTF-8 解码后的 Python
字符串字符索引，不基于字节。重复文本必须通过 block offset 区分。

## 7. 查询与下游边界

首版只对单文档 `list[SourceEvidence]` 做 O(n) 扫描：

- `resolve(evidence_id)`：ID → SourceEvidence；
- `at(page, bbox)`：位置相交 → 全部 SourceEvidence；
- `find_text(query)`：规范化空白后的子串命中 → 全部 SourceEvidence；
- Candidate/E-SMILES → `evidence_ids` → 原页位置；
- Markdown 选区 → `document.map.json` → `evidence_ids` → 原页位置。

canonical `source_evidence` 表作为跨阶段源证据的 SQL 查询索引，按
`(doc_id, page, kind)` 和文档 bbox 建索引；它只接受已验证的 `SourceEvidence`，
  重复写入必须幂等，内容冲突必须失败。现有 molecule-only 的 `evidence` 表是独立的
  分子观测表，不与 `source_evidence` 混用。暂不新增 Repository、FTS 或 R-tree；
只有跨文档查询成为实际瓶颈时再增加索引。

当前查询入口为 `services/documents/source_evidence.py`：
`resolve(library_root, evidence_id)`、`at(library_root, doc_id, page, bbox)` 和
`find_text(library_root, doc_id, query)`。`at` 使用 bbox 相交规则，`find_text`
先折叠空白再做单文档线性扫描；三者都返回 `SourceEvidence`，不会返回二级对象。

Patent、Example、Activity、Link 和 review 对象只保存 `evidence_ids`，不复制 bbox，
也不创建新的 SourceEvidence。旧格式中的嵌入式 `list[SourceEvidence]` 不被当前
DTO 接受；必须重新生成并引用已有 ID，不得把无 bbox 的二级记录写入 canonical bbox。
人工审核只修改解释层对象，不修改原始 `SourceEvidence`。

## 8. 实施批次

### 批次 A：修复并冻结证据契约（已完成）

- `src/mbforge/core/evidence.py`：已固定位置 ID、校验和完整 round-trip；保留现有
  Patent/Activity 使用的 `_stable_id`。
- `src/mbforge/pipeline/stages/activity_stage.py`：已移除已废弃的 table_idx/row_idx/col_idx
  构造参数，Activity 只解析 ActivityRecord 对应的已有 `evidence_ids`，不再创建
  无 bbox 的 SourceEvidence。
- `tests/unit/core/test_evidence.py`：已验证 ID 区分位置、内容不改变 canonical ID、
  完整 round-trip 和非法 bbox 拒绝。
- 已验证 `core.activity`、`core.patent` 可导入，相关 Patent/Activity 测试通过。

### 批次 B：独立 producer 与 join

- `pipeline/cli/artifacts.py`：已增加严格的 v2 Extract/Detection/DocumentEvidence DTO
  及 PageFrame/CandidateArtifact；v2 DTO 是当前唯一契约。
- `stage_artifacts.py`：已实现 Extract/Detection 最小投影、统一左下坐标转换、
  分支独立原子写入、分支读取、join 校验和 canonical `bbox.json` 原子发布。
- join 已拒绝缺失 bbox、越界 bbox、候选悬空 `evidence_id` 和未归档的 molecule crop；
  Patent/Activity 等二级对象不进入 SourceEvidence producer 或 join 输入。
- producer stage 已在批次 C 接入 runner：每个任务的 `run_id` 持久化并复用，
  Extract/Detection 的独立 artifact 由固定 fork 生成，join 只在两者成功后发布。

### 批次 C：最小 fork/join 与恢复（基础实现已完成）

- [x] runner 对初始两个分支使用标准库并发，不改造成通用 DAG 引擎。
- [x] checkpoint 保存 run_id 和逐阶段状态；失败只重试失败分支。
- [x] 两个 branch context 不共享可变状态；join 原子发布 canonical `bbox.json`。
- [x] 并发更新 `_run.json` 时串行合并阶段状态；恢复会验证 joined artifact 属于当前 `run_id`。
- [x] 进度 UI 读取并展示两个分支状态，不再用线性数组下标推断完成度。

### 批次 D：Markdown 与 map（已完成）

- [x] MarkdownStage 成为 v2 路径 `document.md` 的唯一写入者；rough Markdown 不持久化。
- [x] `document.map.json` 记录最终 Markdown 的 Python 字符 offset 与 `evidence_ids`。
- [x] 重构现有 E-SMILES 插入器消费 joined evidence 的统一坐标；文本保持 Extract 顺序，图片和分子按页面几何插入。
- [x] Detection 不再生成 rough/final Markdown；Markdown 是唯一文档写入者。

### 批次 E：下游引用和文档（已完成）

- [x] Patent、Activity、Examples、Link 均只保存已有的 `evidence_ids`；Examples
  通过 `document.map.json` 的精确字符区间关联 `examples_facts.json`，不按最近文字猜测。
- [x] LinkStage 发布扁平 `links.json`；只发布带有效源证据的
  `activity_measurement → compound_entry` `measured_for` 关联，缺失/悬空证据进入
  issue，不创建新的 SourceEvidence。
- [x] Persist 将 joined source evidence 幂等写入独立 `source_evidence` 表，并提供
  `services/documents/source_evidence.py` 的 ID、位置相交和文本查询。
- [x] CLI、README、wiki、AGENTS、context 注释和 TODO 索引已同步；Persist CLI
  直接消费 `--evidence`，不再要求独立的 `extracted.json`。
- [x] 旧 checkpoint/产物不迁移、不适配；运维恢复方式是重新提交或从失败分支继续当前
  `run_id`，而不是增加运行时兼容分支。

所有阶段（A-E）完成前只运行最小受影响测试，禁止执行全量测试；最终阶段全部完成后
已执行一次全量后端测试并通过（920 passed, 16 skipped）。不得顺带改动 molecule-only SQLite evidence 表、
增加搜索引擎或重写 Patent/Activity 业务规则。

## 9. 最小测试与验收

只保留能证明公共契约或防止静默数据错误的测试：

1. `SourceEvidence`：不同位置不碰撞；完整字段 round-trip 不丢失。
2. Artifact：三个 v2 DTO 严格校验，Candidate 引用必须可解析。
3. 坐标：两个 producer 都在 writer 出口转换为左下坐标。
4. 并行与恢复：两个分支实际重叠执行；一支失败只重试该支；run_id 不变。
5. writer ownership：producer 不写 `bbox.json`，join 原子发布。
6. Markdown：空候选、无文本页、稳定排序、重叠证据和 rejected 过滤。
7. 双向回溯：Markdown block 与 Candidate 都能回到准确 bbox。
8. 最小流程：`Extract || Detection → Markdown → Patent → Activity → Link → Persist`。

验收条件：

- 同一 PDF、同一配置重复运行得到相同 evidence ID、`bbox.json`、`document.md` 和 map；
- Extract 与 Detection 实际独立并行，Detection 不读取 ExtractArtifact；
- 两个 producer 不并发改写同一文件，也不共享可变 PipelineContext；
- `bbox.json` 中所有 Candidate 引用都可解析，所有 bbox 使用同一坐标契约；
- Extract 中每段源文本只持久化一次；
- Detection 失败不生成 Markdown，成功零候选仍生成纯文档；
- rejected/无 E-SMILES Candidate 不进入 Markdown，但保留供审核；
- 旧任务不会无限从头重跑；
- 最小受影响测试、Ruff 和前端类型检查通过。

## 10. 明确不做

- 不新增第二套页面证据对象。
- 不把 `SourceEvidence` 扩成任意 `metadata: dict` 容器。
- 不为单个 fork/join 引入第三方工作流引擎或通用 DAG DSL。
- 不新增共享 `stage_report.log`。
- 不因 bbox 相交删除原始证据。
- 不改动现有 molecule-only `evidence` 表；它与 canonical `source_evidence` 是两个独立
  业务表，不承担 SourceEvidence 的存储职责。
- 不自动修复损坏结构、无效 E-SMILES 或无法验证的 evidence 引用。
