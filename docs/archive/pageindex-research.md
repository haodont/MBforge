# PageIndex 调研报告：无向量、基于推理的 RAG 系统

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [README.md](README.md) · pipeline: [architecture/pipeline-stages.md](architecture/pipeline-stages.md).

> 调研日期：2026-06-14
> 调研人：MiMo Code Agent

> **状态更新（2026-07-05）**：本文档调研的 PageIndex 集成已通过 commit `4fbde55`
> （"feat: migrate KB from embed+rerank+Zvec to OpenKB + PageIndex"）落地在
> `src/mbforge/openkb/`。调研文本中提及的 `src-tauri/` 路径（如
> `document_tree.rs`、`pipeline.rs`、`src-tauri/src/parsers/`）是迁移前的
> Rust 实现路径，**src-tauri/ 已于 2026-07-05 从工作树删除**；如需查阅历史
> 代码可执行 `git log -- src-tauri/`。建议方案中关于"在 src-tauri/src/parsers/
> 添加 PageIndex 树生成模块"的提议未被采纳（实际走 OpenKB + PageIndex 独立
> 包路径，不嵌入业务后端）。

---

## 目录

1. [项目概述](#项目概述)
2. [核心理念](#核心理念)
3. [技术架构](#技术架构)
4. [与 MBForge 现有 RAG 对比](#与-mbforge-现有-rag-对比)
5. [集成可行性分析](#集成可行性分析)
6. [建议方案](#建议方案)
7. [结论](#结论)

---

## 项目概述

### PageIndex 是什么？

**PageIndex** 是由 VectifyAI 开发的开源项目，提供了一种全新的文档索引和检索方法：

> **"Why chunk and embed when you can reason and structure?"**
> （为什么要做分块和嵌入，而不是推理和结构化？）

- **GitHub**: https://github.com/VectifyAI/PageIndex
- **Stars**: 33,100+
- **License**: MIT
- **语言**: Python

### 核心特点

| 特点 | 说明 |
|------|------|
| **无向量数据库** | 使用文档结构和 LLM 推理进行检索，而非向量相似度搜索 |
| **无分块** | 文档按自然段落组织，而非人工分块 |
| **可追溯性** | 检索由推理驱动，基于明确的页面和章节引用 |
| **上下文感知** | 检索依赖完整上下文（对话历史、领域知识） |
| **类人检索** | 模拟人类专家导航和提取知识的方式 |

### 性能表现

- **FinanceBench**: 达到 98.7% 准确率（SOTA）
- **对比**: 大幅超越传统基于向量的 RAG 系统

---

## 核心理念

### 传统 RAG vs PageIndex

```
传统 RAG:
  文档 → 分块 → 嵌入 → 向量数据库 → 相似度搜索
  
PageIndex:
  文档 → LLM 推理 → 层次化树索引 → 树搜索 → 上下文感知检索
```

### 关键洞察

**"相似度 ≠ 相关性"**（Similarity ≠ Relevance）

- 传统向量检索：基于语义相似度
- PageIndex：基于推理的相关性

### 两步检索流程

1. **生成"目录"树结构索引**
   - 使用 LLM 分析文档结构
   - 构建层次化节点树
   - 每个节点包含：标题、摘要、页码范围、子节点

2. **基于推理的树搜索**
   - 模拟人类专家导航
   - 根据查询上下文推理
   - 返回最相关的节点和页码

---

## 技术架构

### 树结构示例

```json
{
  "title": "Financial Stability",
  "node_id": "0006",
  "start_index": 21,
  "end_index": 22,
  "summary": "The Federal Reserve...",
  "nodes": [
    {
      "title": "Monitoring Financial Vulnerabilities",
      "node_id": "0007",
      "start_index": 22,
      "end_index": 28,
      "summary": "The Federal Reserve's monitoring..."
    }
  ]
}
```

### PDF 处理流程

```
PDF 文档
  ↓
TOC 检测（扫描前 20 页）
  ↓
结构提取（LLM 分析）
  ↓
页面映射（逻辑章节 → 物理页码）
  ↓
验证（与实际内容比对）
  ↓
大节点分割（递归分割超大章节）
  ↓
摘要生成（可选）
```

### 支持的文档类型

| 类型 | 支持情况 |
|------|----------|
| PDF | ✅ 核心支持 |
| Markdown | ✅ 基于标题层次 |
| DOCX/PPTX/HTML | ✅ 通过 docling 转换 |
| 代码仓库 | ✅ 目录摘要生成 |

---

## 与 MBForge 现有 RAG 对比

### MBForge 当前架构

```
MBForge RAG:
  PDF 解析 → 分块 → FTS5 全文索引
                  ↓
              向量嵌入 → 语义搜索
                  ↓
              RRF 融合排序
                  ↓
              semantic_cache 缓存
```

### 对比分析

| 维度 | MBForge 现有 | PageIndex |
|------|-------------|-----------|
| **索引方式** | FTS5 + 向量嵌入 | LLM 推理 + 树结构 |
| **分块策略** | 固定大小分块 | 自然章节分块 |
| **检索方法** | 相似度 + 关键词 | 推理 + 树搜索 |
| **可追溯性** | chunk_id + 页码 | 节点路径 + 页码 |
| **上下文感知** | 有限 | 强（对话历史集成） |
| **延迟** | 低（预计算） | 高（LLM 推理） |
| **成本** | 低（一次性嵌入） | 高（每次检索 LLM 调用） |
| **多文档支持** | ✅ 原生支持 | ⚠️ 单文档为主 |
| **实时查询** | ✅ 适合 | ⚠️ 延迟较高 |

### MBForge 的优势

1. **成本效益**：向量嵌入是一次性成本，而 PageIndex 每次检索都需要 LLM 调用
2. **多文档检索**：MBForge 支持跨文档搜索，PageIndex 主要针对单文档
3. **实时性**：MBForge 检索延迟低，适合交互式查询
4. **混合搜索**：MBForge 结合 FTS5 + 向量 + Rerank，更灵活

### PageIndex 的优势

1. **可追溯性**：每个检索结果都有明确的章节引用
2. **上下文感知**：能根据对话历史调整检索
3. **准确性**：在 FinanceBench 上达到 98.7%
4. **结构化**：保留文档的自然层次结构

---

## 集成可行性分析

### 技术可行性

**✅ 高可行性**

1. **MBForge 已有类似实现**
   - `document_tree.rs` 已实现 TreeNode 结构
   - 支持层次化文档导航
   - 页码缓存机制已存在

2. **PageIndex 可作为补充**
   - 不需要完全替换现有 RAG
   - 可作为"深度分析"模式的检索后端

3. **LLM 基础设施已具备**
   - MBForge 已集成 OpenAI/Anthropic API
   - 可复用现有 LLM 客户端

### 集成方案

#### 方案 A：PageIndex 作为可选检索后端

```
用户查询
  ↓
检索策略选择器
  ├─→ 快速模式：现有 FTS5 + 向量
  └─→ 深度模式：PageIndex 树搜索
        ↓
      LLM 推理
        ↓
      返回结果 + 章节引用
```

**优点**：
- 不破坏现有功能
- 用户可选择
- 渐进式集成

**缺点**：
- 需要维护两套索引
- 增加代码复杂度

#### 方案 B：PageIndex 增强现有检索

```
用户查询
  ↓
现有 RAG 检索
  ↓
PageIndex 验证/重排序
  ↓
返回结果
```

**优点**：
- 利用现有索引
- 提升检索准确性
- 保持低延迟

**缺点**：
- 需要 LLM 调用
- 成本增加

#### 方案 C：混合模式（推荐）

```
用户查询
  ↓
快速检索（FTS5 + 向量）
  ↓
结果预筛选（Top-K）
  ↓
PageIndex 深度验证（可选）
  ↓
最终结果 + 章节引用
```

**优点**：
- 平衡速度和准确性
- 用户可控制深度
- 成本可控

### 实现复杂度评估

| 组件 | 复杂度 | 说明 |
|------|--------|------|
| PageIndex 树生成 | 中 | 需要适配 PDF 解析流程 |
| 树搜索算法 | 高 | 需要实现推理逻辑 |
| LLM 集成 | 低 | 复用现有客户端 |
| UI 集成 | 低 | 扩展现有结果展示 |
| 缓存机制 | 中 | 需要缓存树索引和推理结果 |

**估计工时**：2-3 周

---

## 建议方案

### 短期（1-2 个月）

1. **实验性集成**
   - 在 `src-tauri/src/parsers/` 添加 PageIndex 树生成模块
   - 复用现有的 `document_tree.rs` 结构
   - 支持 PDF 文档的层次化索引

2. **检索增强**
   - 在现有 RAG 检索后添加 PageIndex 验证步骤
   - 提升长文档检索准确性

3. **用户选项**
   - 在设置中添加"深度检索"开关
   - 用户可选择是否启用 PageIndex

### 中期（3-6 个月）

1. **完整集成**
   - 实现 PageIndex 树搜索算法
   - 集成对话历史上下文
   - 优化 LLM 调用成本

2. **性能优化**
   - 缓存常用文档的树索引
   - 增量更新机制
   - 本地 LLM 支持（减少 API 成本）

3. **分子科学适配**
   - 针对科学论文优化树结构
   - 支持化学结构图的节点标注
   - 活性数据的层次化组织

### 长期（6+ 个月）

1. **多文档 PageIndex**
   - 扩展支持跨文档检索
   - 构建文档关系图
   - 主题聚类和导航

2. **本地化部署**
   - 支持本地 LLM（Ollama）
   - 完全离线运行
   - 隐私保护

---

## 结论

### 核心发现

1. **PageIndex 是一个有前景的技术**
   - 33,100+ stars 证明了社区认可
   - 98.7% 准确率展示了技术优势
   - "无向量"理念挑战传统 RAG

2. **不建议完全替换 MBForge 现有 RAG**
   - 成本：PageIndex 每次检索需要 LLM 调用
   - 延迟：不适合实时交互查询
   - 多文档：现有 RAG 更擅长跨文档检索

3. **建议作为增强功能集成**
   - 混合模式：快速检索 + 深度验证
   - 用户可控：可选启用
   - 渐进式：先实验，后完整集成

4. **MBForge 已有基础设施**
   - `document_tree.rs` 提供了良好的基础
   - LLM 客户端可复用
   - 架构支持扩展

### 行动项

| 优先级 | 任务 | 负责人 | 预计时间 |
|--------|------|--------|----------|
| P0 | 评估 PageIndex 集成对检索准确性的提升 | TBD | 1 周 |
| P1 | 实验性集成 PDF 树生成 | TBD | 2 周 |
| P1 | 设计用户界面选项 | TBD | 1 周 |
| P2 | 实现混合检索模式 | TBD | 3 周 |
| P2 | 性能优化和缓存 | TBD | 2 周 |

---

## 参考资料

- [PageIndex GitHub](https://github.com/VectifyAI/PageIndex)
- [PageIndex Blog](https://pageindex.ai/blog/pageindex-intro)
- [FinanceBench 评估](https://github.com/VectifyAI/Mafin2.5-FinanceBench)
- [MBForge document_tree.rs](src-tauri/src/core/document/document_tree.rs)
- [MBForge pipeline.rs](src-tauri/src/parsers/pipeline.rs)

---

*本报告基于公开资料整理，仅供内部评估使用。*
