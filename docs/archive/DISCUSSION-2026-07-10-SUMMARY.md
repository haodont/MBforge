# MBForge 产品定位讨论总结

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

> **日期**: 2026-07-10  
> **参与者**: 项目负责人 + Claude (Opus 4.8)  
> **议题**: MBForge 当前定位是否正确？后续开发重心应该在什么方向？

---

## 讨论背景

项目已完成：
- Python-only 后端迁移（Rust/Tauri → FastAPI）
- 9 阶段 pipeline（extract → density → rough_md → detect → insert_molecode → reorganize → pageindex → wiki → persist）
- 19 个 FastAPI routers
- React 19 前端（246 个文件）

存在的问题：
- 测试覆盖率仅 ~5%
- 架构设计隐含"生产级 AI co-pilot"目标（Evidence Links 为 P0）
- 不清楚是做"效率工具"还是"能力工具"

---

## 核心结论

### 一、定位调整

**之前**（过度承诺）：
```
Evidence-linked drug-design workbench
→ 隐含目标：95%+ 识别准确率 + 跨文献推理 + 类似 Cursor 的 co-pilot 体验
```

**现在**（现实可行）：
```
Open-source research baseline for molecular knowledge extraction
→ 明确目标：验证技术路线 + 85-90% 准确率 + 人工校验工作流
```

**价值主张**：
> "10 篇文献 2 天手工整理 → 30 分钟机器处理 + 2 小时人工校验"

### 二、关键判断

#### 1. Evidence Links 从 P0 降级到 P3

**原因**：
- 低频场景（用户 80% 时间在筛选，20% 在验证来源）
- 架构复杂度高（需要跨文献索引 + PDF annotation layer）
- ROI 低（PubChem/ChEMBL 有来源链接，但点击率极低）

**替代方案**（Phase 0）：
- Figure-Molecule Linking（点击分子 → 查看 crop 图片）
- 足够验证识别正确性

#### 2. 接受 85-90% 准确率，通过置信度透明化弥补

**理由**：
- Phase 0 是 research baseline，不是 SOTA
- 95%+ 需要单独立项（1000+ 篇标注 + GPU 集群 + 6 个月 + $10K-50K）
- 用户工作流本来就有人工校验环节

**实现方式**：
- 前端显示 0-100% 置信度
- 置信度 >0.8（60%）→ 直接接受
- 置信度 0.5-0.8（30%）→ 快速核验
- 置信度 <0.5（10%）→ 直接丢弃

#### 3. 测试覆盖是 P0，而非 P1

**理由**：
- 5% 覆盖率 = 不知道哪个改动会炸
- Pipeline 9 个阶段，失败都是静默的
- 开源项目质量底线：无测试 = 无法吸引贡献者
- 阻碍迭代：不敢重构

#### 4. Drug-Design Workflows 降级到 P3

**理由**：
- 需要高质量数据前提（85-90% 识别 + 70% 活性抽取 → 推理不可信）
- 需要领域知识图谱（靶点-疾病、分子-靶点关联）
- Phase 0 是"基础工具"，不是"能力工具"

### 三、Phase 0 Roadmap（6 周）

| Week | 重心 | 关键交付 |
|------|------|----------|
| 1-2 | 工程质量 | 测试覆盖 40%、错误处理、数据一致性 |
| 3-4 | 数据质量 | 置信度透明、Activity Extraction、Figure Linking |
| 5 | 用户体验 | Pipeline 进度可视化、Document Viewer |
| 6 | 文档 | README 修订、CONTRIBUTING.md、Issue 模板 |

**验收标准**：
- 测试覆盖率 ≥40%
- 10 篇文献平均抽取 15-30 分子，置信度 >0.8 占 60%+
- Activity Extraction 准确率 ≥70%
- 首次启动到处理第一个 PDF ≤2 分钟

---

## 优先级重排

| 功能 | 原优先级 | 新优先级 | Week | 理由 |
|------|---------|---------|------|------|
| **测试覆盖 40%** | P1 | **P0** | 1-2 | 质量底线 |
| **Pipeline 错误处理** | P1 | **P0** | 1-2 | 可观测性 |
| **数据一致性（事务）** | P1 | **P0** | 1-2 | 避免脏数据 |
| **置信度透明化** | 新增 | **P0** | 3 | 用户需知道哪些需校验 |
| **Activity Extraction** | 缺失 | **P1** | 3-4 | SAR 核心数据 |
| **Figure-Molecule Linking** | 缺失 | **P1** | 3-4 | 验证识别正确性 |
| **Pipeline 进度可视化** | P1 | **P2** | 5 | 体验优化 |
| **README 修订** | P2 | **P2** | 6 | 明确定位 |
| **Evidence Links** | **P0** | **P3** | Phase 1+ | 低频场景，ROI 低 |
| **Drug-Design Workflows** | P2 | **P3** | Phase 2+ | 需要高准确率前提 |
| **跨文献聚合** | P1 | **P3** | Phase 3+ | 需要中心化服务 |
| **数据网络效应** | 长期 | **P3** | Phase 3+ | 需要运营团队 |

---

## 输出文档

### 新建（4 个，1160 行）

1. **`TODO/PHASE0-ROADMAP.md`** (459 行)
   - 6 周详细计划
   - 每周任务分解 + 验收标准
   - Phase 1-3 预览

2. **`docs/architecture/PHASE0-SCOPE.md`** (362 行)
   - Build List vs Skip List
   - 决策框架（3 个问题筛选功能）
   - FAQ（为什么 Evidence Links 不是 P0？）

3. **`TODO/IMMEDIATE-ACTIONS.md`** (180 行)
   - Week 1 立即启动的 4 个任务
   - 具体代码示例
   - 并行任务建议

4. **`.claude/memory/mbforge-product-thesis.md`** (159 行，更新)
   - 产品定位修正
   - Phase 0-3 边界
   - 立即要做的事

### 更新（1 个）

5. **`TODO/INDEX.md`**
   - P0-P3 重新排序
   - 新增 C-6~C-9、R-10~R-12、D-9~D-12
   - Snapshot 更新为 2026-07-10

---

## 立即行动（Week 1）

### 🔴 P0-1: Pipeline 集成测试（3 天）
- 创建 `tests/integration/test_pipeline_flow.py`
- 准备 fixture PDF（5 页，2-3 个分子结构图）
- 验证数据库 + 文件系统 + OpenKB 三层输出

### 🔴 P0-2: Pipeline 单元测试（2 天）
- `tests/unit/pipeline/test_extract_molecules.py`（Mock MolDet/MolScribe）
- `tests/unit/pipeline/test_normalize.py`（去重逻辑）

### 🔴 P0-3: database.py 测试（2 天）
- **先实现** `core/database.py` 的 `transaction()` context manager
- `tests/unit/core/test_database.py`（CRUD + 事务回滚）

### 🔴 P0-4: Router smoke tests（1 天）
- 更新 `tests/unit/test_routers_smoke.py`
- 自动化生成 19 个 router 测试

### 验收目标
```bash
uv run pytest tests/ --cov=src/mbforge --cov-report=term
# 期望：pipeline ≥60%, core ≥60%, routers ≥30%, TOTAL ≥15%
```

---

## Phase 0 不做的事

### ❌ 明确跳过（推迟到 Phase 1-3）

1. **Evidence Links**（点击分子跳转 PDF bbox 高亮）
2. **Drug-Design Workflows**（SAR 对比、multi-target 分析）
3. **95%+ 识别准确率**（fine-tune MolScribe）
4. **跨文献分子聚合**（同一 SMILES 在多文献 → 单条记录）
5. **数据网络效应**（用户校正 → 模型改进飞轮）

**统一回复模板**（当有人提 Issue/PR）：
> "感谢建议！这是 Phase 1-3 的规划内容。Phase 0（当前）专注工程质量和数据透明。详见 `docs/architecture/PHASE0-SCOPE.md`。"

---

## 与通用 AI 的差异化

### 短期（Phase 0，6 周）
- 开源 + 本地部署
- 专业工作流（9 阶段 pipeline）
- 置信度透明（通用 AI 不提供）

### 中期（Phase 1，6 个月）
- 专有模型准确性（95%+ vs 通用 AI 的 70-80%）
- 需要单独立项 + GPU 集群

### 长期（Phase 2-3，12+ 个月）
- 领域知识图谱（靶点-分子关联）
- 数据网络（用户贡献 → 模型改进）

**风险**：
- 如果不做 Phase 1-3，MBForge 可能在 12 个月内被通用 AI 取代
- 但作为开源科研项目，这是**可接受的**（学术价值已实现）

---

## 决策框架

### 判断一个功能是否在 Phase 0？

#### 问题 1: 是否阻碍"可信赖的工具"目标？
- **Yes** → Phase 0（测试覆盖、错误处理、数据一致性）
- **No** → Phase 1+（Evidence Links、跨文献聚合）

#### 问题 2: 是否需要"Phase 0 没有的能力"？
| 能力 | Phase 0 有吗？ | 是否可跳过？ |
|------|---------------|-------------|
| 95%+ 识别准确率 | ❌ | ✅（接受 85-90% + 置信度透明） |
| 领域知识图谱 | ❌ | ✅（Phase 0 只做扁平表） |
| 跨文献索引 | ❌ | ✅（per-project vault 已够用） |
| 中心化服务 | ❌ | ✅（本地单用户工具） |

#### 问题 3: ROI 是否足够高？
| 功能 | 开发成本 | 用户价值 | ROI | 决策 |
|------|---------|---------|-----|------|
| 测试覆盖 40% | 2 周 | 高（质量保障） | 高 | Phase 0 |
| Activity Extraction | 1 周 | 高（SAR 核心数据） | 高 | Phase 0 |
| Evidence Links | 2 周 | 低（20% 低频场景） | 低 | Phase 1+ |
| Drug-Design Workflows | 4 周 | 中（需高质量数据） | 低 | Phase 2+ |

---

## 关键对话摘录

### 为什么定位需要调整？

> **问题**：过度承诺的风险  
> **回答**：之前的架构设计（Evidence Links as P0、Drug-Design Workflows）隐含了"接近生产级 AI co-pilot"的目标，但这需要 95%+ 准确率 + 跨文献推理 + 6-12 个月开发周期。作为开源科研项目，现实约束是：使用现有模型、接受 85-90% 准确率、验证技术路线可行性。

### Evidence Links 的价值被高估了？

> **问题**：真实工作流中，用户真的需要"点击分子跳转 PDF 原文"吗？  
> **回答**：如果 LLM 已经总结了「化合物 A 在文献 X 中 IC50 = 10 nM」，用户为什么还要跳回 PDF？除非 LLM 总结错了 → 但这时候问题是"LLM 准确性"，而非"缺少 evidence link"。高频场景（80%）是"找出所有 IC50 < 100 nM 的化合物"（需要 structured data），低频场景（20%）才是"质疑某个数据 → 回原文验证"（需要 evidence）。你在为 20% 的低频场景设计 80% 的架构复杂度。

### 为什么不追求 95%+ 准确率？

> **问题**：85-90% 准确率够用吗？用户会不会不信任？  
> **回答**：够用，**只要置信度透明**。研究者的工作流本来就是：粗筛（快速浏览 100 篇）→ 精读（挑出 10 篇）→ 手工整理（抄 SMILES）。MBForge 的价值是"把 2 天工作压缩为 30 分钟机器 + 2 小时校验"。关键是明确告知置信度，让用户做出正确的信任决策。

---

## 后续步骤

### Phase 0 验收后（6 周）

根据以下指标决定下一步：

| 指标 | 如果达标 | 下一步 |
|------|---------|--------|
| 置信度 >0.8 占 60%+ | ✅ | → Phase 1（模型 fine-tune） |
| 用户抱怨"不准" | ✅ | → Phase 1 |
| 用户要求"更多功能" | ✅ | → Phase 2（推理能力） |
| 有 GPU + 标注预算 | ✅ | → Phase 1 |
| 没有预算 | ✅ | → 继续优化 Phase 0 |

### Phase 1（如果启动，6 个月）
- Fine-tune MolScribe（目标 95%+）
- 训练 Activity Extraction 模型
- 需要：1000+ 篇标注 + GPU 集群

### Phase 2（如果启动，6 个月）
- 跨文献 SAR 知识图谱
- Multi-target 分析、子结构推理
- 需要：领域专家标注 + 强化学习

### Phase 3（如果启动，12 个月）
- 中心化服务（用户贡献 → 模型改进）
- 商业化（SaaS / 企业版）
- 需要：隐私方案 + 运营团队

---

## 文档索引

| 文档 | 路径 | 用途 |
|------|------|------|
| **产品定位** | `.claude/memory/mbforge-product-thesis.md` | 产品哲学 + Phase 0-3 边界 |
| **6 周计划** | `TODO/PHASE0-ROADMAP.md` | 详细任务分解 + 验收标准 |
| **Phase 0 边界** | `docs/architecture/PHASE0-SCOPE.md` | Build List vs Skip List + 决策框架 |
| **Week 1 任务** | `TODO/IMMEDIATE-ACTIONS.md` | 立即启动的 4 个任务 |
| **总任务板** | `TODO/INDEX.md` | P0-P3 Master Task Board |
| **本讨论总结** | `docs/architecture/DISCUSSION-2026-07-10-SUMMARY.md` | 完整讨论记录 |

---

## 最后的话

### 给项目负责人

**你的定位 60 分正确，但需要升级**：
- ✅ 细分市场 + 技术壁垒 + 真实痛点
- ⚠️ 从"knowledge base"升级到"co-pilot"需要 Phase 1-3
- ⚠️ Evidence Links 是架构上的优雅，但用户需要的是数据质量

**Phase 0 的使命**：
> 在现有模型能力下，做出"可信赖的工具"（测试覆盖 + 错误处理 + 数据一致性），而非"功能完整的产品"（跨文献聚合 + 高级推理）。

**记住**：
> **Phase 0 是「可信赖的工具」，不是「功能完整的产品」。**  
> **优先级：工程质量 > 数据透明 > 用户体验 > 炫酷功能。**

现在就开始吧！🚀

---

**讨论结束时间**: 2026-07-10  
**下次 checkpoint**: 2026-07-17（Week 1 验收）
