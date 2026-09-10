# Phase 0 Scope: What We Build vs. What We Skip

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

> **Version**: 1.0  
> **Date**: 2026-07-10  
> **Context**: MBForge 定位调整——从"AI co-pilot"降级为"open-source research baseline"

---

## 核心问题：为什么需要明确边界？

在 2026-07-10 的产品定位讨论中，我们发现：

1. **过度承诺的风险**：之前的架构设计（Evidence Links as P0、Drug-Design Workflows）隐含了"接近生产级 AI co-pilot"的目标，但这需要：
   - 95%+ SMILES 识别准确率（需专有模型 fine-tune + 1000+ 篇标注数据）
   - 跨文献推理能力（需领域知识图谱 + 强化学习）
   - 6-12 个月开发周期 + GPU 集群 + 药化专家团队

2. **现实约束**：作为开源科研项目：
   - 使用现有开源模型（MolDetv2-FT + MolScribe），接受 85-90% 准确率
   - 目标用户是研究者（接受"机器初筛 + 人工校验"工作流）
   - 验证技术路线可行性，而非立即商业化

3. **优先级错位**：之前把 Evidence Links（低频场景）定为 P0，而测试覆盖（质量基础）是 P1。

**Phase 0 的使命**：在现有模型能力下，做出"可信赖的工具"（测试覆盖 + 错误处理 + 数据一致性），而非"功能完整的产品"（跨文献聚合 + 高级推理）。

---

## Phase 0 Build List（6 周交付）

### ✅ Infrastructure（Week 1-2）
| 功能 | 理由 | 验收标准 |
|------|------|----------|
| 测试覆盖 ≥40% | 开源项目的质量底线 | `pytest --cov` 输出 pipeline/core ≥60% |
| Pipeline 错误处理 | 失败时可定位根因 | 前端显示具体失败阶段 + 错误码 |
| 数据一致性（事务） | 中途失败不产生脏数据 | 重复上传、kill 进程后数据库无 orphan records |

### ✅ Structured Data Quality（Week 3-4）
| 功能 | 理由 | 验收标准 |
|------|------|----------|
| 置信度透明化 | 用户需知道哪些分子需人工校验 | Molecule Library 显示 0-100% 置信度 + 筛选 |
| Activity Extraction | SAR 分析的核心数据（IC50/Ki） | 准确率 ≥70%（人工抽查 50 条） |
| Figure-Molecule Linking | 验证识别是否正确 | 点击分子 → 查看原始 crop 图片 |

### ✅ UX Polish（Week 5）
| 功能 | 理由 | 验收标准 |
|------|------|----------|
| Pipeline 进度可视化 | 5-10 分钟执行，用户需知道当前状态 | 9 阶段进度条 + 预估剩余时间 |
| Document Viewer | 验证 LLM 重整质量 | 三 tab（Source PDF / Raw / Reorganized） |

### ✅ Documentation（Week 6）
| 文档 | 理由 | 验收标准 |
|------|------|----------|
| README 修订 | 明确"research baseline"定位 | 写明 85-90% 准确率 + 需人工校验 |
| CONTRIBUTING.md | 外部贡献者上手指南 | 有 3+ 外部贡献者提交 PR/Issue |
| Issue 模板 | 收集 bug + 数据标注 | bug_report.yml + model_accuracy.yml |

---

## Phase 0 Skip List（推迟到 Phase 1-3）

### ❌ Evidence Links（从 P0 降级为 P2）

**原计划**：
- 新增 `evidence` 表（molecule_id + doc_id + page_idx + bbox_pdf + confidence）
- MoleculeRecord 重构为聚合对象（一个 SMILES → 多条 evidence）
- 前端"点击分子 → 跳转 PDF 原文 + bbox 高亮"

**为什么跳过**：
1. **低频场景**：用户 80% 的时间在"找出所有 IC50 < 100 nM 的化合物"（需要 structured data），只有 20% 的时间在"质疑某个数据 → 回原文验证"（需要 evidence）
2. **架构复杂度高**：需要跨文献索引 + 去重聚合 + 前端 PDF annotation layer，至少 2 周开发量
3. **ROI 低**：PubChem/ChEMBL 都有"来源文献"链接，但点击率极低（用户更关心聚合后的数据质量）

**Phase 0 替代方案**：
- Figure-Molecule Linking（点击分子 → 查看 crop 图片）已足够验证识别正确性
- 如果用户真需要跳回 PDF，可手动打开 Source PDF + 搜索 SMILES

**何时重启**：Phase 2（当跨文献聚合和数据质量达到"用户愿意深挖证据"的程度）

---

### ❌ Drug-Design Workflows（从 P2 降级为 P3）

**原计划**：
- Agent 工具扩展：`compare_molecules_sar`、`find_activity_data`、`trace_molecule_evidence`
- 前端 SAR Workbench 页面（多选分子 → 对比表格）
- Multi-target 推理（"找出同时抑制 EGFR 和 HER2 的化合物"）

**为什么跳过**：
1. **需要高准确率数据作为前提**：85-90% 的识别准确率 + 70% 的活性抽取准确率 → 推理结果不可信（garbage in, garbage out）
2. **需要领域知识图谱**：Multi-target 分析需要"靶点-疾病"、"分子-靶点"关联知识，当前只有扁平表
3. **与 Phase 0 定位不符**：这是"能力工具"（解锁新能力），而 Phase 0 是"基础工具"（提高现有工作流效率）

**Phase 0 替代方案**：
- Agent 保持现有 5 个基础工具（`kb_search`、`molecule_search`、`get_document_content`、`compute_molecule_properties`、笔记）
- 用户可通过 Agent 聊天"请列出所有 IC50 < 100 nM 的化合物"（调用 `molecule_search` + LLM 筛选），但不做专门的 SAR 对比 UI

**何时重启**：Phase 2（当数据质量达到 95%+ 且有跨文献知识图谱）

---

### ❌ 跨文献分子去重聚合（从 P1 降级为 P3）

**原计划**：
- 同一 SMILES 在多篇文献出现 → `molecules` 表只有 1 条记录
- `evidence` 表记录每次出现（doc_id + page_idx + bbox_pdf）
- 前端"Molecule Detail"显示"出现在 5 篇文献中"

**为什么跳过**：
1. **需要全局索引**：当前是 per-project vault（一个文件夹 = 一个项目 = 一个 SQLite 数据库），跨项目聚合需要中心化索引
2. **冲突解决复杂**：同一 SMILES 在文献 A 中 IC50=10nM，文献 B 中 IC50=50nM → 如何聚合？（需要实验条件匹配 + 统计分析）
3. **Phase 0 场景不强烈**：研究者通常一次分析 5-10 篇同主题文献，分子重复率不高

**Phase 0 替代方案**：
- 保持 per-project vault（用户新建项目 → 上传文献 → 单项目内分析）
- 如果用户需要跨项目，手动导出 CSV + Excel 合并（或用 Agent 跨项目查询）

**何时重启**：Phase 3（当用户规模达到"需要中心化服务"的程度，如多团队协作、公共数据库）

---

### ❌ 数据网络效应（从长期愿景降级为"暂不考虑"）

**原计划**：
- 用户校正错误的 SMILES → 上传到中心化服务
- 积累标注数据 → fine-tune MolScribe → 全局模型改进
- 越用越准的飞轮

**为什么跳过**：
1. **需要中心化服务 + 隐私方案**：用户上传数据涉及文献版权和数据隐私
2. **需要运营团队**：标注数据清洗、模型训练、版本发布
3. **Phase 0 是本地单用户工具**：无需联网即可运行

**Phase 0 替代方案**：
- 提供 Issue 模板（`model_accuracy.yml`）收集错误案例
- 手动积累数据，为后续 fine-tune 做准备（但不承诺自动改进）

**何时重启**：Phase 3（当有商业化计划或社区规模达到"值得投入中心化服务"）

---

### ❌ 95%+ SMILES 识别准确率（单独立项）

**原计划**：
- Fine-tune MolScribe（目标准确率 95%+）
- 需要 1000+ 篇标注文献（每篇 10-50 个分子）

**为什么跳过**：
1. **需要大规模标注**：1000 篇 × 30 分子/篇 × 5 分钟/分子 = 2500 小时人工标注
2. **需要 GPU 集群**：MolScribe 基于 Swin Transformer，fine-tune 需要 A100 × 几天
3. **Phase 0 定位是 research baseline**：验证技术路线可行性，而非刷 SOTA

**Phase 0 替代方案**：
- 使用 MolScribe 的预训练模型（准确率 ~85-90%）
- 通过置信度透明化，让用户知道哪些需要人工校验
- 收集错误案例（via Issue 模板），为后续 fine-tune 积累数据

**何时重启**：Phase 1（需单独立项，预算 $10K-50K + 6 个月）

---

## Decision Framework: 如何判断一个功能是 Phase 0 还是 Phase 1-3？

用以下 3 个问题筛选：

### 1. 是否阻碍"可信赖的工具"目标？

- **Yes（Phase 0）**：测试覆盖、错误处理、数据一致性、置信度透明
- **No（Phase 1+）**：Evidence Links、跨文献聚合、高级推理

### 2. 是否需要"Phase 0 没有的能力"？

| 能力 | Phase 0 有吗？ | 如果没有，是否可跳过？ |
|------|---------------|---------------------|
| 95%+ 识别准确率 | ❌ | ✅（接受 85-90% + 人工校验） |
| 领域知识图谱 | ❌ | ✅（Phase 0 只做扁平表 + 基础检索） |
| 跨文献索引 | ❌ | ✅（per-project vault 已够用） |
| 中心化服务 | ❌ | ✅（本地单用户工具） |

### 3. ROI 是否足够高？

| 功能 | 开发成本 | 用户价值 | ROI | 决策 |
|------|---------|---------|-----|------|
| 测试覆盖 40% | 2 周 | 高（质量保障） | 高 | Phase 0 |
| Activity Extraction | 1 周 | 高（SAR 核心数据） | 高 | Phase 0 |
| Evidence Links | 2 周 | 低（20% 低频场景） | 低 | Phase 1+ |
| Drug-Design Workflows | 4 周 | 中（需高质量数据前提） | 低 | Phase 2+ |

**原则**：Phase 0 只做"高 ROI + 不需要新能力"的功能。

---

## Communication: 如何向用户/贡献者传达边界？

### README.md（首页）

```markdown
## What is MBForge?

MBForge is an **open-source research tool** for extracting structured molecular knowledge from scientific literature.

**Current Status: Phase 0 (Research Baseline)**
- ✅ Suitable for: literature screening + manual validation workflow
- ⚠️ Molecule recognition accuracy: ~85-90% (based on MolScribe baseline)
- ❌ Not suitable for: production environments, regulatory submissions

## Roadmap

- **Phase 0 (2026 Q3)**: Engineering quality + data transparency → 6 weeks
- **Phase 1 (2026 Q4)**: Fine-tune models for 95%+ accuracy → 6 months (separate project)
- **Phase 2 (2027 Q1)**: Reasoning capabilities (SAR analysis, multi-target) → 6 months
- **Phase 3 (2027 Q2+)**: Platform (cross-document, collaboration) → 12 months
```

### CONTRIBUTING.md

```markdown
## What We're Building (Phase 0)

MBForge Phase 0 focuses on **engineering quality and data transparency**, not advanced AI capabilities.

**In Scope**:
- ✅ Test coverage ≥40%
- ✅ Error handling and data consistency
- ✅ Activity extraction (IC50/Ki) with ≥70% accuracy
- ✅ Confidence transparency (let users know what to validate)

**Out of Scope** (Phase 1+):
- ❌ 95%+ recognition accuracy (needs fine-tuning)
- ❌ Drug-design workflows (SAR comparison, multi-target analysis)
- ❌ Cross-document aggregation
- ❌ Centralized data network

**If you want to contribute** outside Phase 0 scope, please open a discussion issue first.
```

### Issue 模板

```yaml
# feature_request.yml
- type: dropdown
  id: phase
  label: Which phase does this belong to?
  options:
    - Phase 0 (engineering quality)
    - Phase 1 (model accuracy)
    - Phase 2 (reasoning capabilities)
    - Phase 3 (platform features)
    - Unsure
```

---

## FAQ

### Q1: 为什么 Evidence Links 不是 P0？它看起来很酷啊！

**A**: Evidence Links **架构上很优雅**，但用户真正需要的是 **structured data + 推理能力**，而非"点击跳转 PDF"。

对比：
- **高频场景**（80%）：找出所有 IC50 < 100 nM 的化合物 → 需要 `activities` 表 + 筛选功能
- **低频场景**（20%）：质疑某个数据 → 回原文验证 → 需要 evidence links

Phase 0 优先做高频场景。Evidence Links 是加分项，不是核心价值。

### Q2: 85-90% 准确率够用吗？用户会不会不信任？

**A**: 够用，**只要置信度透明**。

研究者的工作流本来就是：
1. 粗筛（快速浏览 100 篇文献）
2. 精读（挑出 10 篇重点）
3. 手工整理（抄 SMILES + 活性数据到 Excel）

MBForge 的价值是"把粗筛 + 精读的 2 天工作压缩为 30 分钟机器处理 + 2 小时人工校验"。

关键：
- ✅ 置信度 >0.8 的分子（60%），用户可直接接受 → 节省 60% 时间
- ⚠️ 置信度 0.5-0.8 的分子（30%），用户快速核验 → 比从头整理快 50%
- ❌ 置信度 <0.5 的分子（10%），直接丢弃 → 不浪费用户时间

只要我们**明确告知置信度**，用户就能做出正确的信任决策。

### Q3: Phase 1 什么时候启动？如何决定？

**A**: Phase 0 验收后（6 周），根据以下指标决定：

| 指标 | 目标 | 如果达不到 |
|------|------|-----------|
| 测试覆盖率 | ≥40% | 继续补测试，延后 Phase 1 |
| 数据质量 | 置信度 >0.8 占 60%+ | 优先做 Phase 1（模型 fine-tune） |
| 社区反馈 | 10+ 用户反馈 | 如果用户都说"不准"→ 优先 Phase 1；如果说"缺功能"→ 考虑 Phase 2 |
| 资源 | 有标注预算或 GPU | 启动 Phase 1；否则继续优化 Phase 0 |

**Phase 1 是否启动的核心问题**：用户是因为"不准"放弃工具，还是接受"85-90% + 人工校验"的定位？

如果是前者 → Phase 1（模型改进）  
如果是后者 → Phase 2（功能扩展）

---

## Changelog

- **2026-07-10**: 初版，基于产品定位讨论结果
- Phase 0 边界明确：测试覆盖 + 数据质量 + 文档完整性
- Evidence Links、Drug-Design Workflows、跨文献聚合降级到 Phase 1-3
