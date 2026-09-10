# Coref Concurrent Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一 `(library_root, doc_id, page)` 的并发 coref 冷页请求幂等持久化，避免唯一约束导致 HTTP 500。

**Architecture:** 保留前端同时读取 labels 与 predictions 的 `Promise.all`。后端 `_persist_page()` 改为数据库级幂等写入：每个 `figure_labels` 插入使用 `INSERT OR IGNORE`，随后按唯一键查询稳定 `id`，再用该 `id` 写入 prediction；prediction 也使用 `INSERT OR IGNORE`。这样跨线程、跨 FastAPI 请求、跨进程共享同一 SQLite 文件时，只有首个写入创建行，其余请求复用已提交行，不依赖进程内锁。

**Tech Stack:** Python 3.12、FastAPI、SQLite、uv、pytest。

## 文件结构

| 文件 | 责任 |
|---|---|
| `src/mbforge/routers/coref.py` | 保持 `figure_labels`/`coref_predictions` 持久化幂等，并将 ephemeral label id 映射到稳定数据库 id。 |
| `tests/unit/routers/test_coref.py` | 用真实临时 SQLite 数据库并发调用 `_persist_page()`，验证不会抛出 `IntegrityError` 且只保留一套行。 |

## 全局约束

- Python 3.12、`uv`、Ruff 88 列格式。
- 不修改前端并发请求；它是合法读取模式。
- 不修改 schema 或唯一约束；唯一约束是最终去重边界。
- 不吞没非唯一约束、SQLite I/O、序列化错误；它们必须继续失败并回滚。
- 每条预测使用已查询的稳定 `label_id`，不可使用并发请求中的 ephemeral id。
- 不提交已有用户工作区改动；仅暂存本任务文件时必须显式指定文件路径。

---

### Task 1: 添加并发持久化回归测试

**Files:**
- Modify: `tests/unit/routers/test_coref.py:1-233`

**Interfaces:**
- 调用：`mbforge.routers.coref._persist_page()`。
- 依赖：`DatabaseManager.get()` 创建的真实临时 SQLite 数据库。
- 断言：两个同页并发写入均成功；数据库中只存在一个 label 和一个 prediction；prediction 指向该 label。

- [ ] **Step 1: 添加并发工具与 router module import**

在 `tests/unit/routers/test_coref.py` 顶部 imports 改为：

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from mbforge.core.database import DatabaseManager
from mbforge.routers import coref
```

- [ ] **Step 2: 添加失败回归测试**

在现有 `test_coref_ensure_for_image` 后添加：

```python
def test_persist_page_concurrent_duplicates_are_idempotent(tmp_path: Path) -> None:
    labels = [
        {
            "id": -1,
            "label_bbox": [0.3, 0.3, 0.4, 0.4],
            "label_text": "Fig 1",
            "ocr_conf": 0.8,
            "image_path": None,
        }
    ]
    predictions = [
        {
            "id": -1,
            "mol_smiles": None,
            "mol_bbox": [0.1, 0.1, 0.2, 0.2],
            "mol_conf": 0.9,
            "label_id": -1,
            "label_text": "Fig 1",
            "label_bbox": [0.3, 0.3, 0.4, 0.4],
            "confidence": 0.9,
            "source": "geometric_ft",
            "is_confirmed": False,
            "image_path": None,
        }
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                coref._persist_page,
                str(tmp_path),
                "doc-1",
                1,
                labels,
                predictions,
            )
            for _ in range(2)
        ]
        results = [future.result() for future in futures]

    db = DatabaseManager.get(str(tmp_path))
    with db.kb_conn() as conn:
        labels_rows = conn.execute(
            "SELECT id FROM figure_labels WHERE doc_id = ? AND page = ?",
            ("doc-1", 1),
        ).fetchall()
        prediction_rows = conn.execute(
            "SELECT label_id FROM coref_predictions WHERE doc_id = ? AND page = ?",
            ("doc-1", 1),
        ).fetchall()

    assert len(results) == 2
    assert len(labels_rows) == 1
    assert len(prediction_rows) == 1
    assert prediction_rows[0]["label_id"] == labels_rows[0]["id"]
```

- [ ] **Step 3: 运行测试并确认现状失败**

运行：

```bash
uv run pytest tests/unit/routers/test_coref.py::test_persist_page_concurrent_duplicates_are_idempotent -q
```

预期：失败，`future.result()` 抛出 `sqlite3.IntegrityError`，错误包含：

```text
UNIQUE constraint failed: figure_labels.doc_id, figure_labels.page, figure_labels.label_bbox, figure_labels.label_text
```

- [ ] **Step 4: 仅提交测试（可选原子检查点）**

若仓库规则要求测试先行提交，执行：

```bash
git add tests/unit/routers/test_coref.py
git commit -m "test(coref): cover concurrent page persistence"
```

不要暂存任何其他当前工作区文件。

### Task 2: 将 coref 页面写入改为 SQLite 幂等操作

**Files:**
- Modify: `src/mbforge/routers/coref.py:394-465`
- Test: `tests/unit/routers/test_coref.py::test_persist_page_concurrent_duplicates_are_idempotent`

**Interfaces:**
- 输入：FT 输出的 ephemeral `label.id`，以及 prediction 的 ephemeral `label_id`。
- 输出：稳定数据库 label id 映射后的 labels/predictions。
- 失败语义：非冲突 SQLite 错误继续抛出；唯一键冲突变成读回同一行。

- [ ] **Step 1: 将 label 裸插入改为忽略冲突后查询稳定 id**

在 `_persist_page()` 的 label 循环中，将 `cur = conn.execute(...)` 与 `lastrowid` 赋值替换为：

```python
            label_bbox = _bbox_to_text(lab.get("label_bbox"))
            label_text = lab.get("label_text")
            conn.execute(
                """
                INSERT OR IGNORE INTO figure_labels
                    (doc_id, page, label_bbox, label_text, ocr_conf, image_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    page,
                    label_bbox,
                    label_text,
                    lab.get("ocr_conf"),
                    image_path if image_path is not None else lab.get("image_path"),
                ),
            )
            row = conn.execute(
                """
                SELECT id FROM figure_labels
                WHERE doc_id = ? AND page = ? AND label_bbox = ? AND label_text = ?
                """,
                (doc_id, page, label_bbox, label_text),
            ).fetchone()
            if row is None:
                raise RuntimeError("figure label insert did not produce a row")
            eph_label_to_db[eph_id] = int(row["id"])
```

保留循环其余逻辑。不要在 `except sqlite3.IntegrityError` 中返回空结果；`INSERT OR IGNORE` 必须只包住由 schema 唯一键定义的 label 写入。

- [ ] **Step 2: 将 prediction 裸插入改为幂等插入**

在 prediction 循环中，将：

```python
            conn.execute(
                """
                INSERT INTO coref_predictions
```

改为：

```python
            conn.execute(
                """
                INSERT OR IGNORE INTO coref_predictions
```

其余 columns、values、`mol_smiles` 空字符串归一化及 `db_label_id` 映射保持不变。

- [ ] **Step 3: 更新函数 docstring，声明并发语义**

将 `_persist_page()` docstring 改为：

```python
    """Idempotently persist FT output and return stable database rows.

    Ephemeral FT ids are remapped: label ephemeral id -> DB id, then
    prediction.label_id is rewritten to the DB label id. SQLite unique
    constraints deduplicate concurrent cold-page requests.
    """
```

- [ ] **Step 4: 运行定向回归测试**

运行：

```bash
uv run pytest tests/unit/routers/test_coref.py::test_persist_page_concurrent_duplicates_are_idempotent -q
```

预期：`1 passed`。

- [ ] **Step 5: 运行 coref router 测试文件**

运行：

```bash
uv run pytest tests/unit/routers/test_coref.py -q
```

预期：全部通过；确认原有确认、手工重配对、`ensure-for-image` 行为未变。

- [ ] **Step 6: 运行格式与 lint**

运行：

```bash
uv run ruff format --check src/mbforge/routers/coref.py tests/unit/routers/test_coref.py
uv run ruff check src/mbforge/routers/coref.py tests/unit/routers/test_coref.py
```

预期：两命令退出码为 `0`。

- [ ] **Step 7: 提交实现与测试**

执行：

```bash
git add src/mbforge/routers/coref.py tests/unit/routers/test_coref.py
git commit -m "fix(coref): make page persistence idempotent"
```

仅在用户要求提交或当前任务已被明确授权提交时执行；不要包含预存的无关工作区改动。

### Task 3: 端到端复现原始并发请求模式

**Files:**
- Modify: none
- Test: `tests/unit/routers/test_coref.py`

- [ ] **Step 1: 在隔离临时库执行两次并发持久化回归**

运行：

```bash
uv run pytest tests/unit/routers/test_coref.py::test_persist_page_concurrent_duplicates_are_idempotent -q -x
```

预期：退出码 `0`；无 `UNIQUE constraint failed`。

- [ ] **Step 2: 执行受影响测试集**

运行：

```bash
uv run pytest tests/unit/routers/test_coref.py tests/unit/core/test_database.py -q
```

预期：退出码 `0`。

- [ ] **Step 3: 记录验证结果**

交付说明必须包含：

```text
- 原因：两个前端请求并发越过空页读取，随后重复裸 INSERT。
- 修复：`_persist_page()` 对同一唯一键执行 INSERT OR IGNORE，再查询稳定 label id；prediction 同样幂等。
- 验证：并发回归、coref router 测试、Ruff 已运行并列出实际输出。
- 未改：前端 `Promise.all`、数据库 schema、已有数据。
```
