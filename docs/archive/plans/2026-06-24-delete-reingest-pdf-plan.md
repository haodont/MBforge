# PDF/文献删除与重新读取功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 MBForge 中实现已导入 PDF 的彻底删除，以及保留源 PDF 的重新读取（清空派生数据后重新入队）。

**Architecture:** 后端以 `Project::cleanup_document_data` 为统一清理核心，同步调用 `MoleculeDatabase`、`KnowledgeBase`、`IngestQueue` 和文件系统完成全量清理；`delete_document` 与 `reingest_document` 作为薄包装。前端在 `DocumentList` 每行添加删除/重读图标按钮，通过二次确认后调用新 Tauri 命令。

**Tech Stack:** Rust (Tauri v2, rusqlite, tokio), TypeScript (React 19, Vite 6), i18next.

---

## File Structure

| 文件 | 责任 |
|------|------|
| `src-tauri/src/core/molecule/molecule_store.rs` | 新增 `MoleculeDatabase` 同步方法：级联删除分子关系、检测索引 |
| `src-tauri/src/core/document/knowledge_base.rs` | 新增 `KnowledgeBase` 方法：删除 coref 标注、清理文件缓存 |
| `src-tauri/src/core/document/ingest_queue.rs` | 新增 `IngestQueue::delete_by_doc_id` |
| `src-tauri/src/core/project/project.rs` | 新增 `Project::cleanup_document_data` / `delete_document` / `reingest_document` |
| `src-tauri/src/commands/file_ops.rs` | 新增 `project_delete_document` / `project_reingest_document` 命令 |
| `src-tauri/src/commands/mod.rs` | 注册新命令 |
| `frontend/src/api/tauri/project.ts` | 新增 `deleteDocument` / `reingestDocument` 前端封装 |
| `frontend/src/i18n/locales/zh-CN.json` | 新增中文文案键 |
| `frontend/src/i18n/locales/en.json` | 新增英文文案键 |
| `frontend/src/components/project/DocumentList.tsx` | 添加删除/重读按钮与确认对话框 |

---

## Task 1: MoleculeDatabase 同步清理关系与检测索引

**Files:**
- Modify: `src-tauri/src/core/molecule/molecule_store.rs`

### Step 1: 确保关系/检测表存在

在 `impl MoleculeDatabase` 内新增辅助函数（放在 `setup_schema` 之后）：

```rust
fn ensure_relations_and_detections_schema(conn: &Connection) -> Result<(), String> {
    conn.execute_batch(
        "CREATE TABLE IF NOT EXISTS molecule_relations (
            id INTEGER PRIMARY KEY,
            mol_a_id TEXT NOT NULL,
            mol_b_id TEXT NOT NULL,
            relation_type TEXT NOT NULL CHECK(relation_type IN ('similar','same_as','scaffold','cluster')),
            score REAL,
            metadata TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(mol_a_id, mol_b_id, relation_type)
        );
        CREATE INDEX IF NOT EXISTS idx_relations_type ON molecule_relations(relation_type);
        CREATE INDEX IF NOT EXISTS idx_relations_a ON molecule_relations(mol_a_id);
        CREATE INDEX IF NOT EXISTS idx_relations_b ON molecule_relations(mol_b_id);

        CREATE TABLE IF NOT EXISTS molecule_detections (
            id INTEGER PRIMARY KEY,
            mol_id TEXT NOT NULL,
            doc_id TEXT NOT NULL,
            page INTEGER NOT NULL,
            bbox_x0 REAL NOT NULL,
            bbox_y0 REAL NOT NULL,
            bbox_x1 REAL NOT NULL,
            bbox_y1 REAL NOT NULL,
            crop_relpath TEXT,
            conf_moldet REAL,
            conf_molscribe REAL,
            vlm_verified_esmiles TEXT,
            vlm_confidence REAL,
            detected_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(mol_id, doc_id, page)
        );
        CREATE INDEX IF NOT EXISTS idx_detect_doc_page ON molecule_detections(doc_id, page);
        CREATE INDEX IF NOT EXISTS idx_detect_mol ON molecule_detections(mol_id);",
    )
    .map_err(|e| format!("Failed to ensure relations/detections schema: {e}"))?;
    Ok(())
}
```

### Step 2: 按 mol_id 列表删除关系

```rust
/// Delete all relations where either endpoint is in `mol_ids`.
pub fn delete_relations_for_mol_ids(&self, mol_ids: &[String]) -> Result<usize, String> {
    if mol_ids.is_empty() {
        return Ok(0);
    }
    Self::ensure_relations_and_detections_schema(&self.conn)?;
    let placeholders: Vec<String> = (0..mol_ids.len()).map(|i| format!("?{}", i + 1)).collect();
    let sql = format!(
        "DELETE FROM molecule_relations WHERE mol_a_id IN ({}) OR mol_b_id IN ({})",
        placeholders.join(","),
        placeholders.join(",")
    );
    let mut stmt = self
        .conn
        .prepare(&sql)
        .map_err(|e| format!("Prepare failed: {e}"))?;
    let params: Vec<&dyn rusqlite::ToSql> = mol_ids.iter().map(|s| s as &dyn rusqlite::ToSql).collect();
    let affected = stmt
        .execute(rusqlite::params_from_iter(mol_ids.iter()))
        .map_err(|e| format!("Failed to delete relations: {e}"))?;
    Ok(affected)
}
```

### Step 3: 按 doc_id 删除检测索引

```rust
/// Delete all molecule detections for one document.
pub fn delete_detections_for_doc(&self, doc_id: &str) -> Result<usize, String> {
    Self::ensure_relations_and_detections_schema(&self.conn)?;
    let affected = self
        .conn
        .execute(
            "DELETE FROM molecule_detections WHERE doc_id = ?1",
            rusqlite::params![doc_id],
        )
        .map_err(|e| format!("Failed to delete detections for doc {doc_id}: {e}"))?;
    Ok(affected)
}
```

### Step 4: 编译检查

Run:
```bash
cd src-tauri && cargo check
```

Expected: no errors.

### Step 5: Commit

```bash
git add src-tauri/src/core/molecule/molecule_store.rs
git commit -m "feat(molecule): add sync cleanup for relations and detections"
```

---

## Task 2: KnowledgeBase 清理 coref 标注

**Files:**
- Modify: `src-tauri/src/core/document/knowledge_base.rs`

### Step 1: 新增 `delete_figure_annotations`

在 `impl KnowledgeBase` 的 coref CRUD 区域新增：

```rust
/// 删除某文档的所有 figure_labels 和 coref_predictions 标注。
pub fn delete_figure_annotations(&self, doc_id: &str) -> AppResult<usize> {
    let conn = self.fts_conn.lock().map_err(|e| e.to_string())?;
    let labels = conn.execute(
        "DELETE FROM figure_labels WHERE doc_id = ?1",
        rusqlite::params![doc_id],
    )?;
    let preds = conn.execute(
        "DELETE FROM coref_predictions WHERE doc_id = ?1",
        rusqlite::params![doc_id],
    )?;
    log::info!(
        "Deleted figure annotations for {}: {} labels, {} predictions",
        doc_id, labels, preds
    );
    Ok(labels + preds)
}
```

### Step 2: 编译检查

Run:
```bash
cd src-tauri && cargo check
```

Expected: no errors.

### Step 3: Commit

```bash
git add src-tauri/src/core/document/knowledge_base.rs
git commit -m "feat(kb): add delete_figure_annotations for document cleanup"
```

---

## Task 3: IngestQueue 按文档删除任务

**Files:**
- Modify: `src-tauri/src/core/document/ingest_queue.rs`

### Step 1: 新增 `delete_by_doc_id`

在 `impl IngestQueue` 的 `delete_task` 之后新增：

```rust
/// 删除某文档的所有队列任务（无论状态），用于文档彻底删除或重新读取前清理。
pub async fn delete_by_doc_id(&self, doc_id: &str) -> AppResult<usize> {
    let conn = self.conn.lock().await;
    let changed = conn.execute(
        "DELETE FROM ingest_queue WHERE doc_id = ?1",
        params![doc_id],
    )?;
    let _ = conn.execute(
        "DELETE FROM ingest_logs WHERE doc_id = ?1",
        params![doc_id],
    );
    log::info!("IngestQueue: deleted {} tasks/logs for doc {}", changed, doc_id);
    Ok(changed)
}
```

### Step 2: 添加单元测试

在 `mod tests` 中新增：

```rust
#[tokio::test]
async fn test_delete_by_doc_id() {
    let (_dir, queue) = setup_queue();
    let id1 = queue.enqueue("a.pdf".into(), "doc1".into()).await.unwrap();
    let id2 = queue.enqueue("b.pdf".into(), "doc2".into()).await.unwrap();

    let deleted = queue.delete_by_doc_id("doc1").await.unwrap();
    assert_eq!(deleted, 1);

    let remaining: Vec<_> = queue.list_all().await.unwrap();
    assert_eq!(remaining.len(), 1);
    assert_eq!(remaining[0].id, id2);
}
```

### Step 3: 运行测试

Run:
```bash
cd src-tauri && cargo test --lib document::ingest_queue::tests::test_delete_by_doc_id
```

Expected: test passes.

### Step 4: Commit

```bash
git add src-tauri/src/core/document/ingest_queue.rs
git commit -m "feat(queue): add delete_by_doc_id for document cleanup"
```

---

## Task 4: Project 统一清理函数

**Files:**
- Modify: `src-tauri/src/core/project/project.rs`

### Step 1: 重写 `gc_document_data` 为完整的 `cleanup_document_data`

将现有 `gc_document_data` 替换为以下实现。注意保持签名同步，因为 `remove_document` 仍调用它。

```rust
/// 删除文档的所有派生数据。若 `keep_source` 为 true，保留 `source.pdf` 与 `.mbforge/index.json`。
fn cleanup_document_data(root: &Path, doc_id: &str, source_filename: &str, source_path: Option<&str>, keep_source: bool) -> Result<(), String> {
    let mut errors: Vec<String> = Vec::new();

    // 1. 检测缓存
    let dp_cache = DetectionCache::for_document_project(root, doc_id);
    if let Err(e) = dp_cache.clear_doc(doc_id) {
        errors.push(format!("detection cache (doc): {e}"));
    }
    let legacy_cache = DetectionCache::new(root);
    let _ = legacy_cache.clear_doc(doc_id);
    if !source_filename.is_empty() {
        let _ = legacy_cache.clear_doc(source_filename);
    }

    // 2. 分子数据库：按 source_doc 查 mol_id，再级联删除关系、检测、图片、分子。
    if let Ok(db) = MoleculeDatabase::open(root) {
        let targets: Vec<String> = [source_filename, doc_id]
            .iter()
            .filter(|s| !s.is_empty())
            .flat_map(|key| {
                db.search_by_source(key)
                    .unwrap_or_default()
                    .into_iter()
                    .map(|r| r.mol_id)
            })
            .collect::<std::collections::HashSet<_>>()
            .into_iter()
            .collect();

        if let Err(e) = db.delete_relations_for_mol_ids(&targets) {
            errors.push(format!("molecule relations: {e}"));
        }
        if let Err(e) = db.delete_detections_for_doc(doc_id) {
            errors.push(format!("molecule detections: {e}"));
        }
        for mol_id in &targets {
            if let Err(e) = db.delete_molecule(mol_id) {
                errors.push(format!("molecule {mol_id}: {e}"));
            }
        }
    }

    // 3. 知识库：向量 + 文档树 + coref 标注 + 文件缓存
    let root_str = root.to_string_lossy().to_string();
    if let Ok(kb) = get_or_init_kb(&root_str) {
        if let Err(e) = kb.remove_document(doc_id) {
            errors.push(format!("knowledge base: {e}"));
        }
        if let Err(e) = kb.delete_figure_annotations(doc_id) {
            errors.push(format!("figure annotations: {e}"));
        }
        if let Some(sp) = source_path {
            let full = root.join(sp);
            if let Err(e) = kb.file_cache().invalidate(&full) {
                errors.push(format!("file cache: {e}"));
            }
        }
    }

    // 4. 摘要
    if let Ok(sm) = SummaryManager::new(root) {
        if let Err(e) = sm.delete(doc_id) {
            errors.push(format!("summary: {e}"));
        }
    }

    // 5. 处理队列：直接通过 knowledge_base.db 同步连接删除该 doc 的任务和日志
    let kb_db_path = root.join(crate::core::constants::INDEX_DIR).join("knowledge_base.db");
    if kb_db_path.exists() {
        if let Ok(conn) = rusqlite::Connection::open(&kb_db_path) {
            let _ = conn.execute("DELETE FROM ingest_queue WHERE doc_id = ?1", rusqlite::params![doc_id]);
            let _ = conn.execute("DELETE FROM ingest_logs WHERE doc_id = ?1", rusqlite::params![doc_id]);
        }
    }

    // 6. 文件系统：保留或删除 DocumentProject 目录
    let project_dir = root.join(PROJECTS_DIR).join(doc_id);
    if project_dir.exists() {
        if keep_source {
            let paths = [
                project_dir.join("text.md"),
                project_dir.join("report.md"),
                project_dir.join("cache"),
                project_dir.join("molecules"),
                project_dir.join("reports"),
            ];
            for p in &paths {
                if p.exists() {
                    let res = if p.is_dir() {
                        std::fs::remove_dir_all(p)
                    } else {
                        std::fs::remove_file(p)
                    };
                    if let Err(e) = res {
                        errors.push(format!("fs cleanup {:?}: {e}", p));
                    }
                }
            }
        } else if let Err(e) = std::fs::remove_dir_all(&project_dir) {
            errors.push(format!("remove project dir {:?}: {e}", project_dir));
        }
    }

    if errors.is_empty() {
        Ok(())
    } else {
        Err(format!(
            "cleanup_document_data for {} completed with errors: {}",
            doc_id,
            errors.join("; ")
        ))
    }
}
```

### Step 2: 更新 `remove_document` 调用

在 `remove_document` 方法中，将原来的 `Self::gc_document_data(...)` 调用改为传入 `keep_source: false`：

```rust
Self::cleanup_document_data(
    &self.root,
    doc_id,
    &source_filename,
    entry.source_path.as_deref(),
    false,
);
```

### Step 3: 编译检查

Run:
```bash
cd src-tauri && cargo check
```

Expected: no errors.

### Step 4: Commit

```bash
git add src-tauri/src/core/project/project.rs
git commit -m "feat(project): implement complete cleanup_document_data"
```

---

## Task 5: Project 删除与重新读取方法

**Files:**
- Modify: `src-tauri/src/core/project/project.rs`

### Step 1: 新增 `delete_document`

在 `remove_document` 之后新增：

```rust
/// 彻底删除文档：清理所有数据，从索引移除，并删除 DocumentProject 目录。
pub fn delete_document(&mut self, doc_id: &str) -> Result<(), String> {
    let entry = self.get_document(doc_id).ok_or_else(|| {
        format!("Document {doc_id} not found")
    })?;
    let source_filename = entry
        .source_path
        .as_deref()
        .or_else(|| Some(entry.path.as_str()))
        .and_then(|p| Path::new(p).file_name())
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();
    let source_path = entry.source_path.clone();

    Self::cleanup_document_data(
        &self.root,
        doc_id,
        &source_filename,
        source_path.as_deref(),
        false,
    )?;

    let pos = self
        .index
        .iter()
        .position(|d| d.doc_id == doc_id)
        .ok_or_else(|| format!("Document {doc_id} not found"))?;
    let entry = self.index.remove(pos);
    if let Some(sp) = &entry.source_path {
        self.path_map.remove(&self.root.join(sp));
    }
    self.path_map.remove(&self.root.join(&entry.path));
    self.save_index();
    Ok(())
}
```

### Step 2: 新增 `reingest_document`

```rust
/// 重新读取文档：保留 source.pdf，清空派生数据，重置状态，并入队。
pub fn reingest_document(&mut self, doc_id: &str) -> Result<(), String> {
    let entry = self.get_document(doc_id).ok_or_else(|| {
        format!("Document {doc_id} not found")
    })?;
    if entry.doc_type != "pdf" {
        return Err(format!("Only PDF documents can be re-ingested: {doc_id}"));
    }
    let source_path = entry.source_path.clone().ok_or_else(|| {
        format!("Document {doc_id} has no source_path")
    })?;
    let source_filename = Path::new(&source_path)
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();

    // 清理派生数据，保留 source.pdf
    Self::cleanup_document_data(
        &self.root,
        doc_id,
        &source_filename,
        Some(&source_path),
        true,
    )?;

    // 重置 DocumentProject meta 状态
    if let Some(mut dp) = DocumentProject::load(&self.root, doc_id) {
        dp.meta.inspector_status = "pending".to_string();
        dp.meta.text_status = "pending".to_string();
        dp.meta.ocr_status = "pending".to_string();
        dp.meta.moldet_status = "not_processed".to_string();
        dp.meta.moldet_pages = Vec::new();
        dp.meta.index_status = "pending".to_string();
        let _ = dp.save_meta();
    }

    // 重置 Project index 状态
    self.set_document_status(doc_id, "inspector_status", "pending");
    self.set_document_status(doc_id, "text_status", "pending");
    self.set_document_status(doc_id, "ocr_status", "pending");
    self.set_document_status(doc_id, "moldet_status", "not_processed");
    self.set_document_status(doc_id, "index_status", "pending");

    Ok(())
}
```

### Step 3: 编译检查

Run:
```bash
cd src-tauri && cargo check
```

Expected: no errors.

### Step 4: Commit

```bash
git add src-tauri/src/core/project/project.rs
git commit -m "feat(project): add delete_document and reingest_document methods"
```

---

## Task 6: Tauri 命令

**Files:**
- Modify: `src-tauri/src/commands/file_ops.rs`
- Modify: `src-tauri/src/commands/mod.rs`

### Step 1: 在 `file_ops.rs` 新增命令

在 `delete_file` 命令之后新增：

```rust
/// 彻底删除 PDF 文档及其所有派生数据。
#[tauri::command]
pub async fn project_delete_document(project_root: String, doc_id: String) -> Result<(), String> {
    let root_path = wrap(resolve_path(&project_root))?;

    let mut project = crate::core::project::project::Project::open(&root_path).ok_or_else(|| {
        AppError::new(
            ErrorCode::ProjectOpen,
            format!("项目不存在: {}", root_path.display()),
        )
        .with_path(root_path.to_string_lossy())
        .to_string()
    })?;

    project.delete_document(&doc_id).map_err(|e| {
        AppError::new(ErrorCode::FileWrite, format!("删除文档失败: {e}")).to_string()
    })
}

/// 重新读取已有 PDF：保留源文件，清空所有抽取结果后重新入队。
#[tauri::command]
pub async fn project_reingest_document(
    project_root: String,
    doc_id: String,
) -> Result<(), String> {
    let root_path = wrap(resolve_path(&project_root))?;

    let mut project = crate::core::project::project::Project::open(&root_path).ok_or_else(|| {
        AppError::new(
            ErrorCode::ProjectOpen,
            format!("项目不存在: {}", root_path.display()),
        )
        .with_path(root_path.to_string_lossy())
        .to_string()
    })?;

    let source_path = project.get_document_source_path(&doc_id).ok_or_else(|| {
        AppError::new(
            ErrorCode::FileNotFound,
            format!("文档源文件未找到: {doc_id}"),
        )
        .to_string()
    })?;

    project.reingest_document(&doc_id).map_err(|e| {
        AppError::new(ErrorCode::FileWrite, format!("重新读取文档失败: {e}")).to_string()
    })?;

    let queue = crate::core::document::ingest_queue::IngestQueue::new(&project.root).map_err(|e| {
        AppError::new(ErrorCode::QueueFull, format!("打开处理队列失败: {e}")).to_string()
    })?;

    let file_path = source_path.to_string_lossy().to_string();
    queue
        .enqueue_with_stage(file_path, doc_id.clone(), "inspector", true)
        .await
        .map_err(|e| format!("重新入队失败: {e}"))?;

    Ok(())
}
```

### Step 2: 注册命令

在 `src-tauri/src/commands/mod.rs` 的 `file_ops` 分组中追加：

```rust
file_ops::project_delete_document,
file_ops::project_reingest_document,
```

### Step 3: 编译检查

Run:
```bash
cd src-tauri && cargo check
```

Expected: no errors.

### Step 4: Commit

```bash
git add src-tauri/src/commands/file_ops.rs src-tauri/src/commands/mod.rs
git commit -m "feat(commands): add project_delete_document and project_reingest_document"
```

---

## Task 7: Rust 测试

**Files:**
- Modify: `src-tauri/src/core/project/project.rs`

### Step 1: 扩展 `test_remove_document_cleans_orphaned_data`

在现有测试末尾追加断言：

```rust
// 验证 molecule_relations / molecule_detections 无残留
use crate::core::molecule::molecule_store::MoleculeDatabase;
let mol_db = MoleculeDatabase::open(root).unwrap();
assert!(mol_db.search_by_source(doc_id).unwrap().is_empty());
// 若之前插入了关系/检测，断言对应表为空（本测试主要验证不报错）。
```

### Step 2: 新增 reingest 测试

在 `mod tests` 末尾新增：

```rust
#[test]
fn test_reingest_document_resets_status() {
    let tmp = TempDir::new().unwrap();
    let root = tmp.path();

    // 创建源 PDF
    let src = root.join("source.pdf");
    std::fs::write(&src, b"%PDF-1.4 fake pdf content").unwrap();

    let mut project = Project::open(root).unwrap();
    let entry = project.add_file(&src).unwrap();
    let doc_id = entry.doc_id;

    // 模拟处理完成状态
    project.set_document_status(&doc_id, "inspector_status", "text_based");
    project.set_document_status(&doc_id, "text_status", "done");
    project.set_document_status(&doc_id, "index_status", "done");

    // 重新读取
    project.reingest_document(&doc_id).unwrap();

    let doc = project.get_document(&doc_id).unwrap();
    assert_eq!(doc.inspector_status, "pending");
    assert_eq!(doc.text_status, "pending");
    assert_eq!(doc.index_status, "pending");
    assert_eq!(doc.ocr_status, "pending");
    assert_eq!(doc.moldet_status, "not_processed");

    // source.pdf 必须保留
    let dp_dir = root.join(PROJECTS_DIR).join(&doc_id);
    assert!(dp_dir.join(PROJECT_SOURCE_FILE).exists());
}
```

### Step 3: 运行测试

Run:
```bash
cd src-tauri && cargo test --lib project::tests::test_remove_document_cleans_orphaned_data
cd src-tauri && cargo test --lib project::tests::test_reingest_document_resets_status
```

Expected: both pass.

### Step 4: Commit

```bash
git add src-tauri/src/core/project/project.rs
git commit -m "test(project): add reingest and cleanup assertions"
```

---

## Task 8: 前端 API 封装

**Files:**
- Modify: `frontend/src/api/tauri/project.ts`

### Step 1: 新增函数

在 `deleteFile` 之后新增：

```typescript
/** 彻底删除 PDF 文档及其所有派生数据。 */
export async function deleteDocument(projectRoot: string, docId: string): Promise<void> {
  return invokeWithError(
    () => invoke('project_delete_document', { projectRoot, docId }),
    ErrorCode.ProjectOpen,
  )
}

/** 重新读取已有 PDF：清空派生数据后重新入队。 */
export async function reingestDocument(projectRoot: string, docId: string): Promise<void> {
  return invokeWithError(
    () => invoke('project_reingest_document', { projectRoot, docId }),
    ErrorCode.ProjectOpen,
  )
}
```

### Step 2: 类型检查

Run:
```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

### Step 3: Commit

```bash
git add frontend/src/api/tauri/project.ts
git commit -m "feat(api): add deleteDocument and reingestDocument bridges"
```

---

## Task 9: i18n 文案

**Files:**
- Modify: `frontend/src/i18n/locales/zh-CN.json`
- Modify: `frontend/src/i18n/locales/en.json`

### Step 1: 在 zh-CN.json 追加

在 `doc.enqueueFailed` 之后追加：

```json
  "doc.reingest": "重新读取",
  "doc.delete": "删除",
  "doc.reingestConfirm": "将清空 {{filename}} 的所有抽取结果并重新读取，是否继续？",
  "doc.deleteConfirm": "将永久删除 {{filename}} 及其所有分子、向量和笔记，是否继续？",
  "doc.reingestSuccess": "已重新读取 {{filename}}",
  "doc.deleteSuccess": "已删除 {{filename}}",
  "doc.reingestError": "重新读取失败：{{error}}",
  "doc.deleteError": "删除失败：{{error}}",
```

### Step 2: 在 en.json 追加

在 `doc.enqueueFailed` 之后追加：

```json
  "doc.reingest": "Re-ingest",
  "doc.delete": "Delete",
  "doc.reingestConfirm": "Clear all extracted results for {{filename}} and re-ingest?",
  "doc.deleteConfirm": "Permanently delete {{filename}} and all associated molecules, vectors, and notes?",
  "doc.reingestSuccess": "Re-ingested {{filename}}",
  "doc.deleteSuccess": "Deleted {{filename}}",
  "doc.reingestError": "Re-ingest failed: {{error}}",
  "doc.deleteError": "Delete failed: {{error}}",
```

### Step 3: Commit

```bash
git add frontend/src/i18n/locales/zh-CN.json frontend/src/i18n/locales/en.json
git commit -m "feat(i18n): add delete/reingest confirmation and toast keys"
```

---

## Task 10: DocumentList UI

**Files:**
- Modify: `frontend/src/components/project/DocumentList.tsx`

### Step 1: 导入依赖

在文件顶部新增：

```typescript
import { ask } from '@tauri-apps/plugin-dialog'
import { RefreshCwIcon, TrashIcon } from '../icons'
import { deleteDocument, reingestDocument } from '../../api/tauri/project'
```

（若 `RefreshCwIcon` / `TrashIcon` 不存在，请在 `frontend/src/components/icons/index.ts` 中按现有模式导出对应 SVG 图标。）

### Step 2: 新增状态与处理函数

在组件内新增：

```typescript
const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set())
const [reingestingIds, setReingestingIds] = useState<Set<string>>(new Set())

const handleDelete = async (doc: DocumentEntry) => {
  if (!projectRoot) return
  const confirmed = await ask(
    t('doc.deleteConfirm', { filename: doc.title || doc.doc_id }),
    { title: t('doc.delete'), kind: 'warning' }
  )
  if (!confirmed) return
  setDeletingIds(prev => new Set(prev).add(doc.doc_id))
  try {
    await deleteDocument(projectRoot, doc.doc_id)
    showToast(t('doc.deleteSuccess', { filename: doc.title || doc.doc_id }), 'success')
    onRefreshDocs?.()
  } catch (e) {
    console.error('[DocumentList] delete failed:', e)
    showToast(t('doc.deleteError', { error: String(e) }), 'error')
  } finally {
    setDeletingIds(prev => {
      const next = new Set(prev)
      next.delete(doc.doc_id)
      return next
    })
  }
}

const handleReingest = async (doc: DocumentEntry) => {
  if (!projectRoot) return
  const confirmed = await ask(
    t('doc.reingestConfirm', { filename: doc.title || doc.doc_id }),
    { title: t('doc.reingest'), kind: 'warning' }
  )
  if (!confirmed) return
  setReingestingIds(prev => new Set(prev).add(doc.doc_id))
  try {
    await reingestDocument(projectRoot, doc.doc_id)
    trackSelfTriggeredDoc(doc.doc_id)
    setJustEnqueuedIds(prev => new Set(prev).add(doc.doc_id))
    showToast(t('doc.reingestSuccess', { filename: doc.title || doc.doc_id }), 'success')
    onRefreshDocs?.()
  } catch (e) {
    console.error('[DocumentList] reingest failed:', e)
    showToast(t('doc.reingestError', { error: String(e) }), 'error')
  } finally {
    setReingestingIds(prev => {
      const next = new Set(prev)
      next.delete(doc.doc_id)
      return next
    })
  }
}
```

### Step 3: 在每行添加按钮

在 `canReindex` 按钮块之后、关闭 `</div>` 之前新增：

```tsx
{(doc.doc_type === 'pdf') && (
  <div className="project-doc-actions" onClick={(e) => e.stopPropagation()}>
    <Button
      variant="ghost"
      size="sm"
      title={t('doc.reingest')}
      loading={reingestingIds.has(doc.doc_id)}
      disabled={reingestingIds.has(doc.doc_id) || deletingIds.has(doc.doc_id) || isActivelyProcessing}
      onClick={() => handleReingest(doc)}
    >
      <RefreshCwIcon size={14} />
    </Button>
    <Button
      variant="ghost"
      size="sm"
      title={t('doc.delete')}
      loading={deletingIds.has(doc.doc_id)}
      disabled={reingestingIds.has(doc.doc_id) || deletingIds.has(doc.doc_id)}
      onClick={() => handleDelete(doc)}
      className="doc-delete-btn"
    >
      <TrashIcon size={14} />
    </Button>
  </div>
)}
```

### Step 4: 样式（可选）

在 `frontend/src/styles/project.css`（或对应样式文件）中添加：

```css
.doc-delete-btn {
  color: var(--danger, #c0392b);
}
.doc-delete-btn:hover {
  color: var(--danger-hover, #a93226);
  background: var(--danger-bg, rgba(192, 57, 43, 0.1));
}
```

若项目未使用 CSS 类覆盖，可跳过此步，使用内联 `style={{ color: 'var(--danger)' }}` 亦可。

### Step 5: 类型检查

Run:
```bash
cd frontend && npx tsc --noEmit
```

Expected: no errors.

### Step 6: Commit

```bash
git add frontend/src/components/project/DocumentList.tsx frontend/src/styles/project.css
git commit -m "feat(ui): add delete/reingest buttons to DocumentList"
```

---

## Task 11: 前端测试

**Files:**
- Modify: `frontend/src/components/project/DocumentList.test.tsx`（若不存在则创建）

### Step 1: 确认测试文件存在

Run:
```bash
ls frontend/src/components/project/
```

若不存在 `DocumentList.test.tsx`，创建它：

```typescript
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import DocumentList from './DocumentList'
import type { DocumentEntry } from '../../types'

vi.mock('@tauri-apps/plugin-dialog', () => ({
  ask: vi.fn(() => Promise.resolve(true)),
}))

vi.mock('../../api/tauri/project', () => ({
  deleteDocument: vi.fn(() => Promise.resolve()),
  reingestDocument: vi.fn(() => Promise.resolve()),
}))

vi.mock('../../api/tauri/pdf', () => ({
  inspectPdf: vi.fn(() => Promise.resolve()),
  confirmOcr: vi.fn(() => Promise.resolve()),
}))

vi.mock('../../api/tauri/ingest_queue', () => ({
  ingestEnqueue: vi.fn(() => Promise.resolve()),
  trackSelfTriggeredDoc: vi.fn(),
}))

vi.mock('../../hooks/useToast', () => ({
  showToast: vi.fn(),
}))

const makeDoc = (overrides: Partial<DocumentEntry> = {}): DocumentEntry => ({
  doc_id: 'doc-1',
  path: 'projects/doc-1/source.pdf',
  source_path: 'projects/doc-1/source.pdf',
  doc_type: 'pdf',
  title: 'Test Paper',
  indexed: true,
  hash: 'abc',
  inspector_status: 'text_based',
  text_status: 'done',
  ocr_status: 'not_processed',
  moldet_status: 'has_molecule',
  index_status: 'done',
  ...overrides,
})

describe('DocumentList actions', () => {
  it('renders delete and reingest buttons for indexed pdf', () => {
    render(<DocumentList docs={[makeDoc()]} isLoading={false} projectRoot="/tmp/p" onOpenFile={vi.fn()} />)
    expect(screen.getByTitle('重新读取')).toBeInTheDocument()
    expect(screen.getByTitle('删除')).toBeInTheDocument()
  })
})
```

### Step 2: 运行测试

Run:
```bash
cd frontend && npm test -- --run DocumentList
```

Expected: tests pass.

### Step 3: Commit

```bash
git add frontend/src/components/project/DocumentList.test.tsx
git commit -m "test(ui): add DocumentList delete/reingest button tests"
```

---

## Task 12: 最终验证

### Step 1: Rust 全量测试

Run:
```bash
cd src-tauri && cargo test --lib
```

Expected: all tests pass.

### Step 2: 前端类型检查与测试

Run:
```bash
cd frontend && npx tsc --noEmit && npm test -- --run
```

Expected: no type errors, tests pass.

### Step 3: Commit

```bash
git commit --allow-empty -m "chore: finalize delete/reingest feature"
```

---

## Spec Coverage Checklist

| Spec 需求 | 实现任务 |
|-----------|----------|
| 彻底删除 PDF + 所有派生数据 | Task 4, 5, 6 |
| 重新读取保留 source.pdf，清空派生数据 | Task 4, 5, 6 |
| 删除 molecule_relations / molecule_detections | Task 1, 4 |
| 删除 figure_labels / coref_predictions | Task 2, 4 |
| 删除 file_cache / ingest_queue | Task 3, 4 |
| 行内图标按钮入口 | Task 10 |
| 二次确认对话框 | Task 10 |
| i18n 文案 | Task 9 |
| Rust/前端测试 | Task 7, 11 |

---

## Placeholder Scan

- 无 TBD / TODO / "implement later"。
- 图标 `RefreshCwIcon` / `TrashIcon` 若不存在，需要在 `frontend/src/components/icons/index.ts` 中按现有模式补充（Task 10 Step 1 已说明）。
