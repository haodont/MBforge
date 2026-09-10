# 专利实施例信息提取方案（ExamplesStage）

> 2026-09-05 记录。§六 已拍板（2026-09-06）。线 2（LLM 名称提取）/线 3（合成结构化）待实施。
>
> **线 2/LinkStage 实施前欠账（2026-09-06 交叉审核裁定，全部有 file:line 依据）**：
> 1. 标号覆盖缺口：`pipeline/labels.py:14-18` 正则数字起始，`化合物I-1` 罗马式与裸数字指代
>    `21` 均不匹配（语料确认含此形态）——labels 会静默为空，需扩正则 + 测试语料。
> 2. 键空间分裂：ExampleRecord.labels（裸 token 含连字符）、PatentStage label_key（`化合物N`
>    前缀，`_COMPOUND_TOKEN_RE` 不含 `11-a`）、ActivityRecord.reference_key
>    （`activity/normalization.py:363-394`，`21-a` → unresolved）三空间不同源且无大小写归一——
>    线 2 关联与 LinkStage 前先在 labels.py（或 core/patent）定唯一规范化函数。
> 3. `esmiles_insert.py:176` 现算 candidate id 传 `doc_id=""`（跨文档可撞，文档内无害）；
>    examples 段前端节点待功能落地时补（当前事件回落末段显示）。
> 2026-09-06 更新：§二 接入方式已按 stage 注册表机制（`core/stage.py`，分层治理落地）改写；
> §一 现状证据的行号快照仍为 2026-09-05 时点，实施前以代码为准。
> 2026-09-06 实施前勘误：document.md 由 **DetectionStage** 产出（`detection_stage.py` 从 rough_md
> 拷贝并清洗，`MarkdownStage` 只产 rough md），§二中"MarkdownStage 产物"表述据此修正；
> 2026-09-08 第一阶段实施：Patent/Examples 共用 `pipeline/sections.py`；PatentSectionModel
> 增加 `evidence_ids`，Examples 继续保留原有 `examples_facts.json` 字段形状；标题证据与段落
> 证据均通过 `document.map.json` 精确区间投影，缺失/错误 map 不做兜底猜测。
> 标号正则实际位于 `pipeline/persist/text_links.py:15-19`（原记 `persist_text_links.py`）。
> 语料确认（用户）：中文专利含中文命名、英文专利含英文 IUPAC 命名，描述中混用 `21 / 21-a / 化合物I-1` 式标号指代。
> 产物目标（用户确认）：名字→结构候选 + 合成步骤结构化 + 实施例↔化合物↔活性关联，全部要。

## 一、现状缺口（已在代码中逐条验证）

| 缺口 | 证据 |
| --- | --- |
| 活性只认表格，prose 活性语句零提取 | `extract_activities_from_document` 仅扫 `_extract_tables_from_markdown` |
| 靶点硬编码 | `_infer_document_target` 只认 MRGPRX2（`extract_activities.py:160`） |
| 正文无 SMILES（用户确认正文只有化学命名） | 闲置的 `extract_molecules_from_text`（`extract_molecules.py:781`，正则抓 SMILES）对本场景无用，本方案不采用 |
| 实施例信息零提取 | markdown 生成不识别"实施例/Example"标题（`markdown_stage.py:19` `_HEADING_PATTERNS` 无此项）；`persist_text_links.py:15` 标号正则只做"标号↔E-SMILES 块"邻近链接 |
| 无名字→结构能力 | 仓库无 OPSIN/name-to-structure 任何实现（无 chem/ 模块，AGENTS.md 已过时） |

可复用资产：
- 标号正则 `_EXPLICIT_COMPOUND_LABEL_RE`（`persist_text_links.py:15-19`）已支持 `化合物N / 实施例N / compound N / example N`，含 `21-a` 式后缀
- `normalize_reference_label`（`activity_normalization.py:363`）已把 "1a" 式行标规范成 reference_key — 实施例↔活性关联对齐到同一键空间
- `make_candidate_id`（`extract_molecules.py:54`，SHA-256 稳定 ID）、`_paced_invoke`（LLM 限速/重试，`extract_activities.py:470`）、cancel/artifact 模式直接复用
- 阶段序列现由 `core/stage.py` 注册表派生（分层治理后），当前顺序
  `extract → markdown → detection → patent → activity → persist`；document.md 由
  MarkdownStage 产出，ExamplesStage 排在其后即可读到

## 二、总体设计：新增 `ExamplesStage`

**位置与接入**（按 `core/stage.py` 注册表机制，组合规则见 `pipeline/composition.py`）：
`@register(after="patent")` 排在 Patent 之后、Activity 之前——它切分 document.md
（DetectionStage 产物，见状态行勘误）并使 Activity 可复用文档级靶点。注意 patent-link §1 的
"7 段"目标架构**不含** Examples（其 7 段 = extract/markdown/detection/patent/
activity/link/persist）；若 Link（M3）与 Examples 均落地，全序为
`extract → markdown → detection → patent → examples → activity → link → persist`（8 段）。
`examples_enabled` 关闭时的过滤机制（实施拍板 2026-09-06）：过滤实现在
**`pipeline/composition.py` 组合根**——`effective_stage_names()` 按
`load_global_config().llm.examples_enabled`（默认 `False`，opt-in）过滤注册表
序，runner 的 per-invocation 执行列表与 stage_checkpoint 的 next_stage/summary
遍历共用同一份列表，配置开关不可能使执行与 checkpoint 记账失步；stage 模块
始终被 import（house pattern：stage 延迟重量级 import，注册本身廉价）。
执行失败语义与 ActivityStage 相同：warning + recoverable，不阻断主链。

**ctx 新增**（`pipeline/context.py`）：`examples: list[ExampleRecord]`、`example_stats: dict`。

**核心原则：每实施例段一次 LLM 调用，一个 prompt 同时返回三类结果**（控制配额）：

```json
{"names": [{"label": "21-a", "name": "4-(3-氯-4-氟苯基)-..."}],
 "synthesis": {"starting_materials": [...], "reagents": [...], "conditions": "...", "yield": "...", "references_examples": ["2"]},
 "document_target": "EGFR"}
```

## 三、三条提取线

### 线 2 — 化学名提取 + 名字→结构（LLM 辅助 + 确定性校验）
- LLM 只负责"标号→名称"映射，**禁止生成 SMILES**（防幻觉结构）；名称必须在原文可回溯匹配，否则丢弃
- 名字→结构按语言分策略（拍板 2026-09-06，§六）：
  - **英文**：py2opsin（本地确定性，Java 依赖已接受）；失败→仅存名称
  - **中文**：**CMNP**（自研规则解析器 https://github.com/haodont/CMNP ，内嵌快照
    vendor 至 `src/mbforge/vendor/cmnp/`，改名避让其顶层 `parser.py` 模块名，快照
    记录来源 commit；vendor 落地在线 2 执行）。CMNP 现状：纯标准库、中文药名→JSON
    AST、**暂不产出 SMILES**（README 明示 SMILES 组装为后续工作）、未选 license、
    233 条回归语料 ~94% 解析率。故 zh=cmnp 现阶段产物为**名称 + CMNP 解析状态**
    （`parsed` / `pending_review`），**不建结构候选**；CMNP 支持 SMILES 组装后自动
    升级为结构候选（届时沿用 pending_review 人审门槛，RDKit 仅做可解析性校验）
- 转换结果与现有图像候选按 canonical_smiles 去重合并：撞车只补 name 关联，不新建候选

### 线 3 — 合成步骤结构化 + 文档级靶点（LLM，可配置关闭）
- 同一次调用返回原料/试剂/条件/收率/中间体引用（"按实施例2方法"→谱系边表）
- 文档级靶点顺带在此提取（标题/发明内容段），替代 `_infer_document_target` 硬编码，ActivityStage 直接受益

### 关联落地（Persist 扩展，不新表）
- 实施例↔结构：`text_molecule_links` 加 role=`synthesized_in_example`（或复用 evidence 表）
- 实施例↔活性：`ExampleRecord.labels` 经 `normalize_reference_label` 归一后与 `ActivityRecord.reference_key` 匹配

## 四、配置与测试

- `config.llm` 新增：`examples_enabled`（默认 `False`，opt-in；composition 根过滤）、`examples_max_concurrency`（复用 activity 限速模式，线 2）、
  `name_to_structure` 按语言分策略（线 2 实施时重写现有三选一 Literal）：en 固定 `opsin`；zh 为 `cmnp`（默认，见 §三 线 2）|`off`（只存名称）
- 单测：实施例切分（`21/21-a/I-1` 标号，`tests/unit/pipeline/test_markdown_helpers.py:72` 已有中文语料样式）、名称回溯校验、opsin 失败路径、label↔reference_key 对齐
- 集成：中文样例专利 md → 全链路 artifact

## 五、实施顺序（原子提交）

1. 线 2：名称提取 + OPSIN + CMNP vendor（zh=cmnp 暂记解析状态不建候选）
2. 线 3：合成结构化 + 靶点泛化
3. Persist 关联打通

## 六、拍板记录（2026-09-06，已解除实施阻塞）

1. **py2opsin 依赖 Java JAR**（~50MB，可离线运行）→ **接受**。英文 name→structure
   走本地 py2opsin，不引入英文 LLM 转结构路径。
2. **中文名转结构默认值** → **采用自研 CMNP**（https://github.com/haodont/CMNP ），
   接入方式为内嵌快照 vendor（CMNP 现无 pyproject、顶层模块名 `parser.py`、未选
   license，git 依赖暂不可行；CMNP 出 SMILES 能力后再评估正式依赖方式）。
   现阶段 zh 线产物 = 名称 + CMNP 解析状态，不建结构候选（见 §三 线 2）。
