# 交接 — 文档预览渲染错误修复（进行中）

> 2026-09-04 清空原 TODO（原内容见 git 历史 / `assets/docs/archive/todo/`），只保留本交接。

## 待办（未开工，独立于本交接）

- 专利实施例信息提取（ExamplesStage）：完整方案见 `TODO/patent-examples-stage-plan.md`，状态"已评审待拍板"，两个阻塞项待用户确认（py2opsin Java 依赖、中文名转结构默认值）。

## 任务

用户指示：「使用这个接口（`load_page_json`），修复点击文档打开文档预览界面的时候发生的渲染错误，先分析当前的情况」。
上一个任务（Queue 页面打开卡顿）已完成并验证，前端改动已提交，与本任务无关。

## 已查明的事实（勿重复排查）

1. **背景**：commit `c13acc7` 让 PersistStage 每页写 `storage/{doc_id}/pages/page_NNNN.json`
   （keys: `page_num, text, figure_bboxes, ocr_backend, ocr_images, ocr_elapsed_ms, ocr_error`）。
   `load_page_json(doc_id, library_root, page_num)` 在 `src/mbforge/pipeline/ocr_artifacts.py`，**目前零调用方**。
2. **未提交改动**（git 唯一脏文件）：`src/mbforge/routers/library.py:359-376`
   `library_get_page_text` 改为读 `pages/page_{page:04d}.json`，`json.loads` 后取 `data.get("text","")` 返回纯文本。这是**全代码库唯一**的 page 文件读取方。
3. **前端不消费 pages 端点**：`fetchPageText`（`frontend/src/api/http/library.ts:224`）零调用方；`fetchReportJson` 也未使用。仅凭代码**定位不到**报错点。
4. **预览链路**：Workspace.tsx `handleOpenDocument` → `openTab({type:'pdf'})` → PdfViewer。
   右栏 MarkdownPane（读 `document.md`）/WikiDrawer/分子 tab；左栏 PdfCanvas/PdfContinuousView（`GET /documents/{doc_id}/file`）。
   OCR 面板调 `POST /api/v1/pdf/ocr-layout`——`routers/pdf.py` 是**纯 stub**（返回空 blocks）。
   预览打开时的 fetch 均不读 page JSON。
5. **关键发现（真实数据）**：`library_root = C:\Users\10954\MBForge`（`load_global_config()`）。
   既有文档 `72e86100-32c9-4cc7-acda-d29faeccf65f` 的磁盘数据是**旧格式**：
   `pages/page_0001.txt` + `page_0001_figures.json`（figure bbox 单独成文件），同时存在
   `document_report.json` 与 `report.json`（疑与 `125a63d`/`c13acc7` 的改名有关）。
   → 未提交的端点改动对此文档**必然 404**。
6. **后端已尝试启动**：`uv run uvicorn mbforge.app:app --port 18792`（日志：
   `C:\Users\10954\AppData\Local\Temp\opencode\mbf-out.log` / `mbf-err.log`，进程 19888 打出
   "Waiting for application startup" 后未再确认）。健康检查当时仍连接拒绝，需重新确认或重启。

## 下一步（按序）

1. 确认后端在 18792 存活（`GET /api/v1/health`）；不通则重启，端口被占先杀残留进程。
2. 对 doc `72e86100-...` 逐一复现预览打开时的调用，找出报错接口：
   - `GET /api/v1/library/documents/{doc}/file`
   - `GET /api/v1/library/documents/{doc}/markdown`
   - `POST /api/v1/detection-cache/get`（`{library_root, doc_id, ...}`，见 `frontend/src/api/http/detection_cache.ts:66`）
   - `POST /api/v1/pdf/ocr-layout`
3. **先复现再修**：前端不读 pages 端点，报错点大概率在 report.json/document_report.json 之类改名不匹配或 markdown/file 之外；不要继续猜。
4. 修复走最小 diff、打在根因处（ponytail 模式）。若确需把 page JSON 接入预览，后端统一用 `load_page_json`，不要裸读文件。
5. 验证：`uv run ruff check src tests`；后端改动跑 `uv run pytest tests/ -q`（或聚焦用例）；
   动了前端则 `npm --prefix frontend run lint && npm --prefix frontend run test && npm --prefix frontend run build`。
6. 完成后向用户简报：报错根因、修了哪里、如何验证。

## 环境

- 工作目录 `C:\Users\10954\Desktop\MBForge`；Python 一律 `uv run`（系统 python 无 pydantic）。
- 后端端口 18792，Vite 5173（`npm --prefix frontend run dev:all` 联动）。
- 测试目录：`tests/unit`、`tests/integration`；前端测试与组件同目录 `*.test.ts(x)`。
