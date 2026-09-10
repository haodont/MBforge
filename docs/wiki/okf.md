# Open Knowledge Format（OKF）适配规范

本文记录 MBForge 对 Open Knowledge Format（OKF）0.1 草案的本地约定。OKF 是一个以 Markdown 和 YAML frontmatter 表达知识的、与厂商无关的格式；本页是 MBForge 的适配说明，不代表当前所有 library 产物已经自动导出为完整的 OKF bundle。

## 目标

- 让生成的知识可以被人直接阅读，也可以被脚本和 agent 逐步解析。
- 保留 Markdown 的版本控制、链接和引用能力，避免把知识锁定在数据库或 UI 中。
- 将“生成的知识库”和“用户自己的笔记”放在同一个 Knowledge 工作区中，但保留两者不同的来源和编辑边界。

## Bundle 目录约定

一个 OKF bundle 是一组层级化的 `.md` 文件。文件去掉 `.md` 后的 bundle-relative 路径就是 concept ID。`index.md` 用作目录入口，`log.md` 用作按日期倒序排列的变更记录；其他 Markdown 文件都是 concept 文档。

未来 MBForge 导出 bundle 时，根目录 `index.md` 可以声明：

```yaml
okf_version: "0.1"
```

当前 library 内部文件仍由 MBForge 的 `ArtifactResolver` 管理，不应在业务代码中直接拼接存储路径。

## Concept 文档格式

每个非保留 Markdown 文件应以 YAML frontmatter 开始，并至少提供非空的 `type`：

```markdown
---
type: concept
title: MRGPRX2
description: 与本概念相关的简短说明
resource: library://wiki/concepts/mrgprx2
tags:
  - target
timestamp: 2026-07-15T19:00:00+08:00
---

# MRGPRX2

正文使用标准 Markdown。需要时可使用 `# Schema`、`# Examples` 和 `# Citations` 等约定标题。
```

推荐字段的含义如下：

| 字段 | MBForge 用途 |
|---|---|
| `type` | `summary`、`concept`、`entity`、`molecule`、`note` 等知识类型 |
| `title` | 列表和页面标题 |
| `description` | 索引、搜索结果中的短摘要 |
| `resource` | 原始文档、library artifact 或外部资源的稳定引用 |
| `tags` | 检索和筛选标签 |
| `timestamp` | 生成或最后更新的时间 |
| 自定义字段 | 可保留 `doc_id`、`library_root`、`source_pages` 等 MBForge 元数据 |

解析器必须容忍未知字段；因此新增 MBForge 元数据不应破坏通用 OKF 消费者。

## 链接、公式和引用

- bundle 内链接优先使用以 `/` 开头的 bundle-relative 路径，必要时也可使用相对链接。
- 引用集中放在 `# Citations` 下，以编号列表指向论文、文档或资源 URL。
- 正文继续使用 Markdown；LaTeX 公式应保留在 Markdown 源文本中，并由前端公式组件渲染。
- MoleCode 是 MBForge 的分子结构文本表示；结构预览可额外生成 RDKit SVG，但不应以 SVG 替代可版本控制的 MoleCode 源文本。

## MBForge 的边界

`LibraryWiki` 展示的是由 library 生成的只读知识；`Notes` 保存用户主动编辑的内容。统一入口只统一导航和检索体验，不把生成内容静默写回用户笔记，也不把笔记伪装成自动生成的 concept。后续若实现“导出 OKF bundle”，应明确记录来源、时间和生成工具。

## 校验清单

导出或新增知识文件时检查：

1. UTF-8 编码，扩展名为 `.md`。
2. 非 `index.md`、`log.md` 的文件有可解析 frontmatter，且 `type` 非空。
3. `index.md` 和 `log.md` 遵循保留文件规则。
4. 内部链接、引用和 `resource` 能追溯到来源；断链应在校验报告中可见。
5. 生成内容与用户笔记的来源字段保持可区分。

## 外部规范

- [OKF README](https://github.com/GoogleCloudPlatform/knowledge-catalog/tree/main/okf)
- [OKF SPEC.md（v0.1 Draft）](https://raw.githubusercontent.com/GoogleCloudPlatform/knowledge-catalog/main/okf/SPEC.md)
- [OKF LICENSE.md](https://raw.githubusercontent.com/GoogleCloudPlatform/knowledge-catalog/main/okf/LICENSE.md)
