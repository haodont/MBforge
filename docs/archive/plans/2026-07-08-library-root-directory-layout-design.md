# Library Root 目录结构重设计

## 背景与动机

当前 `library_root` 下的路径设计存在以下问题：

1. **数据库文件分散且命名混乱**：`library.db`、`index/knowledge_base.db`、`index/molecules.db` 三处存放，职责交叉。
2. **`knowledge_base.db` 名不副实**：实际存放了 `ingest_queue`、`ingest_events`、`ingest_logs`、`semantic_cache` 等运行时数据，并非纯粹知识库。
3. **隐藏目录与非隐藏数据混放**：`.mbforge/`、`storage/`、`index/` 同级，用户难以区分哪些是内部数据、哪些是可操作文件。
4. **旧版遗留路径与新结构并存**：`index/doc_trees.json` 与 `openkb/wiki` 并存，`project_root` 与 `library_root` 混用。
5. **全局 PageIndex 与 library 数据分离**：PageIndex 放在全局配置目录，导致 library 不是真正自包含的单元。
6. **术语不统一**：group / collection / project / library 混用，概念边界模糊。

本设计旨在：

- 明确 `library` 是**完全独立的资料库项目**，可复制、备份、迁移、删除。
- 统一层级命名：Library → Collection → Entity → Tag。
- 合并数据库到单一 `library.db`。
- 清晰区分用户可见数据与内部运行时数据。
- 将 PageIndex 迁入每个 library 内部。

---

## 层级命名定义

| 层级 | 英文 | 含义 | 关系 |
|---|---|---|---|
| **Library** | Library | 独立资料库/项目 | 顶层容器，拥有自己的数据库、索引、文件 |
| **Collection** | Collection | 大方向集合/分组 | 一个 Entity 可属于多个 Collection；支持层级 |
| **Entity** | Entity | 单份文献/PDF | 最小文献单位，对应原 `doc_id` |
| **Tag** | Tag | 文献细分关键词 | 一个 Entity 可打多个 Tag；类似 article keywords |

> **术语排除**：
> - 不再使用 **group**，统一为 **collection**。
> - 不再使用 **project_root**，统一为 **library_root**。
> - UI 中的“标签页”改称 **Page**，避免与 **Tag** 发音/拼写混淆；原 `AppContext` 中的 `Tab` 类型同步重命名为 `Page`。

---

## 目录结构设计

```text
{library_root}/
├── entities/                               # 用户可见：文献实体
│   └── {entity_id}/
│       ├── {filename}.pdf                  # 原始 PDF
│       ├── pages/
│       │   └── page_*.txt                  # 每页提取/ocr 后的纯文本
│       └── report.json                     # 流水线处理报告
├── wiki/                                   # 用户可见：OpenKB wiki 输出
│   └── summaries/
│       └── {entity_id}.md
└── .mbforge/                               # 内部运行时数据
    ├── library.db                          # 单一合并数据库
    │                                       #   ← collections
    │                                       #   ← collection_members
    │                                       #   ← entities
    │                                       #   ← tags
    │                                       #   ← entity_tags
    │                                       #   ← ingest_queue
    │                                       #   ← ingest_events
    │                                       #   ← ingest_logs
    │                                       #   ← molecules
    │                                       #   ← molecule_images
    │                                       #   ← molecule_relations
    │                                       #   ← molecule_detections
    │                                       #   ← molecule_reviews
    │                                       #   ← semantic_cache
    │                                       #   ← figure_labels
    │                                       #   ← coref_predictions
    │                                       #   └── pages               ← Page 视图状态（可选持久化；与 Tag 不同，Tag 是 Entity 关键词）
    ├── pageindex/                          # OpenKB PageIndex 索引
    ├── crops/
    │   └── {entity_id}/
    │       └── *.png                       # 分子结构裁切图
    └── logs/                               # 按 library 隔离的日志
```

### 目录职责说明

| 路径 | 可见性 | 内容 | 来源 |
|---|---|---|---|
| `entities/{entity_id}/` | 用户可见 | 原始 PDF、每页文本、报告 | 上传/导入 + pipeline |
| `wiki/` | 用户可见 | OpenKB 编译的 wiki 摘要 | WikiCompiler |
| `.mbforge/library.db` | 内部 | 合并数据库 | LibraryStore + DatabaseManager |
| `.mbforge/pageindex/` | 内部 | OpenKB PageIndex 索引 | PageIndexWrapper |
| `.mbforge/crops/{entity_id}/` | 内部 | 分子检测裁切图 | extract_molecules.py |
| `.mbforge/logs/` | 内部 | 该 library 的运行日志 | logger |

---

## 单个 Entity 输入后的存储流程

1. **接收文件**
   - 通过上传或导入接收 PDF。
   - 生成 `entity_id`（UUID）。
   - 计算 MD5，做去重校验。

2. **保存原始文件**
   - 复制 PDF 到 `entities/{entity_id}/{filename}.pdf`。
   - 在 `library.db.entities` 插入元数据：
     - `entity_id`、`title`、`file_name`、`storage_path`、`md5`、`page_count`、`status`、`source`、`created_at`、`updated_at`。

3. **运行 pipeline**
   - Stage 1（Extract）：提取文本，低字数页走 OCR 链。
   - Stage 2（Density）：分类为 `text_only` / `mixed` / `image_only`。
   - Stage 3（PageIndex）：构建树式索引，存入 `.mbforge/pageindex/`。
   - Stage 4（Wiki）：编译 wiki，输出到 `wiki/summaries/{entity_id}.md`。
   - Stage 5（Enrich）：图像分子检测 → SMILES 识别 → 归一化 → 持久化。
   - Stage 6（Persist）：保存每页文本和报告。

4. **保存处理产物**
   - 每页文本：`entities/{entity_id}/pages/page_*.txt`。
   - 汇总报告：`entities/{entity_id}/report.json`。
   - 分子裁切图：`.mbforge/crops/{entity_id}/*.png`。
   - 分子检测记录：`library.db.molecule_detections`。

5. **组织与标注**
   - 用户可将 Entity 加入一个或多个 Collection。
   - 用户可给 Entity 打一个或多个 Tag。

---

## 数据库 Schema 调整

### 新增/调整表

```sql
-- 文献实体（原 documents）
CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    file_name TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    md5 TEXT NOT NULL,
    page_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'pending',
    source TEXT DEFAULT 'import',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 集合（原 collections）
CREATE TABLE collections (
    collection_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id TEXT,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (parent_id) REFERENCES collections(collection_id)
);

-- 集合成员：多对多
CREATE TABLE collection_members (
    collection_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, entity_id),
    FOREIGN KEY (collection_id) REFERENCES collections(collection_id),
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE
);

-- 标签
CREATE TABLE tags (
    tag_id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    color TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 实体标签：多对多
CREATE TABLE entity_tags (
    entity_id TEXT NOT NULL,
    tag_id TEXT NOT NULL,
    PRIMARY KEY (entity_id, tag_id),
    FOREIGN KEY (entity_id) REFERENCES entities(entity_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
);

```

> **以下表的完整列定义直接继承自现有实现**，本次设计不做列级调整，唯一要求是将其中的 `doc_id` 统一重命名为 `entity_id`：
>
> - 来源：`src/mbforge/core/database.py`
>   - `ingest_queue`（将 `doc_id` → `entity_id`）
>   - `ingest_events`（将 `doc_id` → `entity_id`）
>   - `ingest_logs`（将 `doc_id` → `entity_id`）
>   - `molecules`
>   - `molecule_images`
>   - `molecule_relations`
>   - `molecule_detections`（将 `doc_id` → `entity_id`）
>   - `molecule_reviews`（将 `doc_id` → `entity_id`）
>   - `mol_search`（FTS5 虚拟表）
>   - `semantic_cache`
>   - `figure_labels`（将 `doc_id` → `entity_id`）
>   - `coref_predictions`（将 `doc_id` → `entity_id`）

```sql
-- UI Page 视图状态（可选持久化；与 Tag 不同，Tag 是 Entity 关键词）
CREATE TABLE pages (
    page_id TEXT PRIMARY KEY,
    entity_id TEXT,
    page_type TEXT,                          -- 原 tab_type，避免与 Tag 混淆
    scroll_position REAL,
    extra_json TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### 索引与约束

- `entities(md5)`：去重。
- `entities(status)`：按状态筛选。
- `collections(parent_id)`：层级树。
- `collection_members(entity_id)`：快速查找某实体所属集合。
- `entity_tags(entity_id)`、`entity_tags(tag_id)`：快速标签查询。
- `molecule_detections(entity_id, page)`：按实体和页码查询。
- `ingest_events(task_id, ts_ms)`：队列事件流。

---

## 废弃的旧路径与迁移

| 旧路径 | 新路径 | 处理方式 |
|---|---|---|
| `{library_root}/library.db` | `.mbforge/library.db` | 迁移合并 |
| `{library_root}/index/knowledge_base.db` | `.mbforge/library.db` | 表结构迁入 |
| `{library_root}/index/molecules.db` | `.mbforge/library.db` | 表结构迁入 |
| `{library_root}/index/doc_trees.json` | 删除 | 由 OpenKB wiki 替代 |
| `{library_root}/storage/{doc_id}/` | `entities/{entity_id}/` | 目录重命名，表中外键同步更新（`doc_id` → `entity_id`） |
| `{library_root}/.mbforge/openkb/wiki/` | `wiki/` | 上移到可见目录 |
| `{library_root}/.mbforge/notes/` | 待定 | 见“未确切定义的事项” |
| 全局 PageIndex | `.mbforge/pageindex/` | 按 library 隔离 |
| 代码中 `project_root` | `library_root` | 统一命名 |

### 迁移策略（概要）

1. 启动时检测旧结构是否存在。
2. 创建 `.mbforge/library.db` 和新目录结构。
3. 从旧数据库读取数据，写入新数据库。
4. 移动 `storage/{doc_id}/` → `entities/{entity_id}/`，并同步将数据库中外键列 `doc_id` 重命名为 `entity_id`。
5. 移动 `.mbforge/openkb/wiki/` → `wiki/`。
6. 迁移 PageIndex：
   - 若全局 PageIndex 文件可按原 `doc_id` 直接提取对应条目，则复制到 `.mbforge/pageindex/` 并按 `entity_id` 重命名/重写外键；
   - 若无法直接提取或格式不兼容，则重新运行 `index_document` 流程重建 PageIndex。
7. 标记迁移完成，避免重复执行。

> 详细迁移脚本在 implementation plan 中设计。

---

## 未确切定义的事项

以下概念/文件形式在本次设计中**尚未最终确定**，需要后续讨论或实现时明确：

### 1. Note（笔记）

- 当前位置：`{library_root}/.mbforge/notes/`（`src/mbforge/routers/notes.py:24`）。
- 未确定：
  - 笔记是绑定到 Entity，还是全局/Collection 级？
  - 存储格式是 Markdown、JSON 还是直接入 `library.db`？
  - 是否支持富文本、附件、版本历史？
- 建议方向：Entity 级笔记存入 `entities/{entity_id}/notes/` 或 `library.db.notes`；全局笔记存入 `wiki/notes/`。

### 2. Molecule（分子）的独立性

- 当前分子数据分散在 `molecules.db`、`.mbforge/crops/`、`molecule_reviews` 表。
- 未确定：
  - Molecule 是全局对象还是属于某个 Entity？
  - 同一个 SMILES 在多个 Entity 中出现时，是复用一条 molecule 记录还是各自独立？
  - 分子图片是存在文件系统还是数据库 BLOB？
- 建议方向：Molecule 作为全局对象，通过 `molecule_detections(entity_id, ...)` 关联到 Entity；图片继续存文件系统，路径存数据库。

### 3. Report.json 的 Schema

- 当前 `report.json` 包含 `doc_id`、`page_count`、`doc_kind`、`molecule_count` 等；随本设计推进，`doc_id` 字段将重命名为 `entity_id`。
- 未确定：
  - 是否需要加入 `entity_id`、`collection_ids`、`tags`？
  - 是否需要加入 pipeline 各阶段耗时/错误详情？
  - 是否需要版本号字段以便迁移？

### 4. Wiki 的文件结构

- 当前仅确认 `wiki/summaries/{entity_id}.md`。
- 未确定：
  - 是否会有 `wiki/concepts/`、`wiki/entities/`、`wiki/index.json`？
  - wiki 文件是否只读，还是允许用户编辑？
  - 是否支持跨 Entity 的聚合 wiki 页面？

### 5. PageIndex 的内部格式

- PageIndex 内部结构由 OpenKB 决定。
- 未确定：
  - 是否允许用户直接查看/修改 `.mbforge/pageindex/`？
  - 删除 Entity 时是否级联删除其 PageIndex 节点？
  - 多个 library 之间的 PageIndex 是否允许未来重新共享？

### 6. UI Page（原 Tab，标签页）持久化

- 当前 `AppContext` 中 Tab/Page 是内存状态；术语已固定为 **Page**。
- 未确定：
  - 是否持久化到 `library.db.pages`？
  - 持久化哪些字段（滚动位置、缩放、侧边栏状态）？
  - 切换 Library 时是否恢复该 Library 的 Page 状态？

### 7. Semantic Cache 的格式

- 当前 `semantic_cache.results` 是 JSON 字符串。
- 未确定：
  - 是否改为按 Entity 拆分缓存？
  - 缓存失效策略是什么（按 Entity 更新、按时间、手动清除）？

### 8. Figure Labels / Coref Predictions

- 当前表存在但使用率不高。
- 未确定：
  - 是否继续保留？
  - 是否与 molecule_detections 合并？
  - 是否只在 image_only / mixed 文档中生成？

### 9. Ingest Queue / Events / Logs 的生命周期

- 未确定：
  - 成功处理完成后是否删除 `ingest_queue` 记录？
  - `ingest_events` 和 `ingest_logs` 保留多久？
  - 是否需要归档或自动清理？

### 10. Collection 的层级深度

- 当前 `collections` 表支持 `parent_id`。
- 未确定：
  - 是否允许无限嵌套？
  - UI 是否只展示两层（Collection / Sub-collection）？
  - Collection 与 Tag 的边界是否需要限制（例如 Collection 用于大方向，Tag 用于细关键词）？

### 11. Tag 的元数据

- 未确定：
  - Tag 是否支持颜色、图标、描述？
  - 是否允许 Tag 分组或层级？
  - Tag 名称是否全局唯一？

### 12. 原始 PDF 的命名策略

- 当前保留原始文件名。
- 未确定：
  - 是否重命名为 `{entity_id}.pdf` 以简化路径？
  - 是否保留原文件名并在数据库中记录？
  - 文件名冲突时如何处理？

### 13. 版本控制与备份

- 未确定：
  - 是否提供 `.mbforge/manifest.json` 记录 library 版本和 schema 版本？
  - 是否支持导出/导入单个 library（压缩包形式）？
  - 是否支持 git 友好型结构（例如文本化报告、避免二进制文件混放）？

---

## 推荐实现顺序

1. **第一阶段**：统一术语（`project_root` → `library_root`，`group` → `collection`）。
2. **第二阶段**：合并数据库到 `.mbforge/library.db`，保持旧路径兼容。
3. **第三阶段**：迁移 `storage/{doc_id}/` → `entities/{entity_id}/`，并完成 `doc_id` → `entity_id` 的外键重命名。
4. **第四阶段**：将 PageIndex 迁入 `.mbforge/pageindex/`。
5. **第五阶段**：将 wiki 上移到 `wiki/`，清理 `index/` 和 `doc_trees.json`。
6. **第六阶段**：实现 Tag 和持久化 Page（视 UI 需求）。
7. **第七阶段**：补充未定义事项的决策（Note、Molecule 独立性等）。

---

## 总结

本设计将 `library_root` 重新组织为三层：

- **用户可见层**：`entities/`、`wiki/`
- **内部数据层**：`.mbforge/library.db`、`.mbforge/pageindex/`、`.mbforge/crops/`、`.mbforge/logs/`
- **层级语义**：Library → Collection → Entity → Tag

核心目标是让每个 Library 成为**完全独立、可迁移、可备份**的资料库单元，同时消除当前路径和术语上的混乱。
