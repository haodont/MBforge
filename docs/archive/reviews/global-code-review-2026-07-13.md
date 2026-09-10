# MBForge 全局代码审查报告

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

## 1. 执行摘要

- **审查范围**：9 个并行审查子代理分别覆盖了 Backend routers/API contracts、Pipeline orchestration & stages、Core persistence & data layer、ML/AI backends & OCR chain、Agent & LLM integration、OpenKB & molecule parsers、Frontend architecture/state/HTTP bridge、Frontend components & UI/UX、Tests/QA & project tooling。
- **总体健康度评估**：**2.5 / 5**  
  架构分层清晰、测试覆盖面较好，但存在大量 Critical 级的安全、正确性与并发问题；若干核心功能（Agent 检索、OCR 回退、coref 标签映射、文件上传边界）在当前实现下无法正确或安全运行。
- **最紧迫的 3 个问题**  
  1. **路径遍历 / 任意文件系统访问**：多个 endpoint 直接消费 `pdf_path`/`library_root`，可读取服务器任意文件或枚举目录（`moldet_api.py:209-211`、`pdf.py:137`、`coref.py:337-338`、`library.py:155` 等）。  
  2. **Coref/ML 标签映射错误与 OCR 回退损坏**：`moldet_api.py:304` 用过滤后列表索引查 coref 标签导致张冠李戴；`local.py:34` 引用了不存在的 `get_rapid_ocr`，RapidOCR 页面级 fallback 失效；`extract_text.py:195-221` 对非连续扫描页会 `IndexError`。  
  3. **异步事件循环阻塞 + 全局状态污染 + 单例加载竞态**：大量同步 I/O/CPU 操作直接跑在 async handler 中；`organizer.py:278-279`/`openkb/*`/`mineru.py:53-58` 修改 `os.environ`；`moldet_v2_ft.py:240-244`、`molscribe.py:19-48`、`agent.py:59` 等单例无锁。

## 2. 按严重程度排序的问题清单

### 🔴 Critical（必须立即修复）

#### C1. 路径遍历 / 任意文件系统访问
- **文件路径/行号**：`src/mbforge/routers/moldet_api.py:209-211`、`src/mbforge/routers/pdf.py:137`、`src/mbforge/routers/pdf_render.py:49`、`src/mbforge/routers/coref.py:141-170`、`src/mbforge/routers/coref.py:337-338`、`src/mbforge/routers/detection_cache.py:12`、`src/mbforge/routers/moldet_api.py:335-359`、`src/mbforge/core/library.py:155`、`frontend/src/api/http/project.ts:246-249`
- **问题描述**：`pdf_path`/`library_root` 来自请求体后仅做 `Path.exists()` 或直接 `iterdir()`/`Path()` 拼接；上传文件 `filename` 未消毒即写入 `storage/{doc_id}/`。
- **影响**：可读取/触发推理服务器任意 PDF、枚举目录、写入 storage 外部文件；前端 `readTextFile` 也可越界读取 public 目录外文件。
- **建议修复**：所有路径必须经 `ArtifactResolver` / `LibraryLayout` 解析并 `relative_to` 校验；`filename` 使用 `Path(filename).name` 并拒绝分隔符。
- **原审查区域**：Backend routers / Core persistence / ML backends / OpenKB/parsers / Frontend components

#### C2. Coref/ML 标签与置信度映射错误
- **文件路径/行号**：`src/mbforge/routers/moldet_api.py:304`、`src/mbforge/routers/moldet_api.py:285-294`、`src/mbforge/routers/moldet_api.py:316`、`src/mbforge/parsers/molecule/coref_alt.py`（identifier bboxes 以 `text=""` 创建）
- **问题描述**：`coref_label_map.get(i, "")` 中的 `i` 是过滤后 `mol_boxes_px` 的索引，而非 `coref_result.bboxes` 的原始索引；标识框本身无文本；`scribe_conf` 硬编码为 `0.0`。
- **影响**：分子可能关联错误 coref 标签或标签被丢弃；下游无法获得真实 MolScribe 置信度。
- **建议修复**：在构造 `mol_boxes_px` 时保留原始 `bboxes` 索引作为 key；对 identifier crop 跑 OCR 填充文本；返回真实 confidence。
- **原审查区域**：Backend routers / ML backends / OpenKB/parsers

#### C3. OCR 回退链损坏 / RapidOCR 失效 / 索引错误
- **文件路径/行号**：`src/mbforge/backends/ocr/local.py:34`、`src/mbforge/backends/ocr/rapidocr_adapter.py:105-117`、`src/mbforge/pipeline/extract_text.py:195-221`
- **问题描述**：`local.py` 引用已删除的 `get_rapid_ocr`，导致 RapidOCR 页面 fallback 被静默丢弃；`rapidocr_adapter.py` 强制 `use_dml=True` 在非 DirectML 环境会失败；`_ocr_pages` 用绝对页码 `page_idx` 写入长度为 `len(page_indices)` 的列表，对非连续页触发 `IndexError`。
- **影响**：扫描页无法 OCR、coref 标签 OCR 回退不可用、pipeline 崩溃。
- **建议修复**：恢复页面级 RapidOCR 适配器；DML/CUDA/CPU 自动检测或配置化；按循环索引写入 results。
- **原审查区域**：ML backends / Pipeline

#### C4. 异步事件循环上的同步阻塞 I/O / CPU 工作
- **文件路径/行号**：`src/mbforge/pipeline/extract_text.py:215`、`src/mbforge/pipeline/extract_text.py:66-129`、`src/mbforge/pipeline/extract_molecules.py:100-189`、`src/mbforge/pipeline/organizer.py:291`、`src/mbforge/pipeline/extract_activities.py:289`、`src/mbforge/routers/chem.py`、`src/mbforge/routers/render.py:45`、`src/mbforge/routers/models_router.py:74`、`src/mbforge/routers/pipeline.py:49-83`、`src/mbforge/agent/tools.py`（RDKit 计算）
- **问题描述**：`time.sleep`、PyMuPDF、NumPy/PIL、MolScribe、LLM `invoke`、SQLite 扫描等同步操作直接在 async handler / stage 中执行。
- **影响**：单进程 backend 的事件循环被阻塞，并发 SSE/health/chat 请求全部卡顿。
- **建议修复**：统一用 `await loop.run_in_executor(None, ...)` 或共享线程池；pipeline runner 考虑整体丢进线程池。
- **原审查区域**：Pipeline / Routers / Agent

#### C5. 全局 `os.environ` 修改（API 密钥 / SSL）
- **文件路径/行号**：`src/mbforge/pipeline/organizer.py:278-279`、`src/mbforge/openkb/indexer.py:40-41`、`src/mbforge/openkb/compiler.py:52-53`、`src/mbforge/openkb/query.py:29-30`、`src/mbforge/backends/ocr/mineru.py:53-58`
- **问题描述**：每次调用都写 `OPENAI_API_KEY`、`OPENAI_API_BASE`、`SSL_CERT_FILE` 等全局环境变量。
- **影响**：并发请求配置互相覆盖、密钥泄漏到子进程、全局 SSL 状态被篡改。
- **建议修复**：将 `api_key`/`base_url`/`verify` 作为调用参数直接传给 litellm/httpx。
- **原审查区域**：Pipeline / OpenKB / OCR

#### C6. 不安全的模型反序列化
- **文件路径/行号**：`src/mbforge/parsers/molecule/molscribe_inference/interface.py:53`、`tests/unit/parsers/test_molscribe_decoder_replay.py:86,145`
- **问题描述**：使用 `torch.load(..., weights_only=False)` 加载 MolScribe checkpoint。
- **影响**：被篡改的模型文件可导致任意代码执行。
- **建议修复**：优先 `weights_only=True`；若必须关闭，加 SHA-256 校验并注释原因。
- **原审查区域**：Parsers / Tests/tooling

#### C7. Agent 工具与会话不可用
- **文件路径/行号**：`src/mbforge/agent/tools.py:31,55,77`、`src/mbforge/agent/tools.py:54-56`、`src/mbforge/routers/agent.py:62-73`、`src/mbforge/routers/agent.py:160-174`、`src/mbforge/agent/sessions.py:20`、`frontend/src/api/http/agent.ts:142-147`
- **问题描述**：KB/分子/文档搜索工具全部硬编码 `library_root=""`；`molecule_search` 在已运行的事件循环里 `new_event_loop()` + `run_until_complete()`；`agent_init` 接收 `sidecar_url` 但忽略；`agent_chat_stream` 追加空字符串输入；session history 无上限；前端调用不存在的 `PUT /api/v1/agent/session/{id}/project`。
- **影响**：Agent 无法检索用户实际库、可能死锁/崩溃、会话 404、长会话 OOM。
- **建议修复**：通过 graph `configurable` 传递 `library_root`；工具改为同步调用或正确 async；实现 `/project` endpoint；校验并 strip 用户输入；给 history 加 cap/sliding window。
- **原审查区域**：Agent / Frontend architecture

#### C8. 上传/文件读取无边界与文件名路径遍历
- **文件路径/行号**：`src/mbforge/routers/library.py:152`、`src/mbforge/core/library.py:155`
- **问题描述**：`await file.read()` 无大小上限；`filename` 直接拼接到目标路径。
- **影响**：大文件上传 OOM；恶意文件名可逃逸 `storage/{doc_id}/`。
- **建议修复**：流式写入并设置最大上传尺寸；消毒文件名。
- **原审查区域**：Backend routers / Core persistence

#### C9. 模型 / Agent 单例加载竞态
- **文件路径/行号**：`src/mbforge/backends/moldet_v2_ft.py:240-244`、`src/mbforge/backends/molscribe.py:19-48`、`src/mbforge/parsers/molecule/coref_alt.py:159-169`、`src/mbforge/routers/agent.py:59`
- **问题描述**：模块级单例在并发首次调用时无锁。
- **影响**：可能加载多个 YOLO/MolScribe/Agent 实例，撑爆 GPU/CPU 内存。
- **建议修复**：加 `threading.Lock`/`asyncio.Lock` 保护初始化。
- **原审查区域**：ML backends / Parsers / Routers

#### C10. 前端硬编码后端地址
- **文件路径/行号**：`frontend/src/api/http/agent.ts:105`、`frontend/src/hooks/useErrorReport.ts:14`、`frontend/src/components/project/pdf/usePdfViewer.ts:94,469`、`frontend/src/components/discover/ChatTab.tsx:25`
- **问题描述**：直接写死 `http://127.0.0.1:18792/...`，绕过 Vite proxy。
- **影响**：Docker/反向代理/自定义端口下聊天流、PDF 图片、错误上报全部失效。
- **建议修复**：统一使用相对路径 `/api/v1/...` 或可配置 `API_BASE`。
- **原审查区域**：Frontend architecture / Frontend components

#### C11. `OpenKBAdapter.search` 中 `asyncio.run` 调用
- **文件路径/行号**：`src/mbforge/openkb/adapter.py:95-98`
- **问题描述**：同步方法内调用 `asyncio.run(search_wiki(...))`，未保证不在运行事件循环中。
- **影响**：若在 async handler 中直接调用会抛 `RuntimeError`。
- **建议修复**：改为 async 方法或显式 guard。
- **原审查区域**：OpenKB

#### C12. `popo.py` 生成并执行字符串代码
- **文件路径/行号**：`src/mbforge/backends/popo.py:137-191`
- **问题描述**：用 f-string 拼接 Python driver 脚本并执行，`model_path` 直接注入。
- **影响**：路径含引号会 SyntaxError，存在代码注入与维护风险。
- **建议修复**：使用静态 driver，通过环境变量/JSON stdin 传参。
- **原审查区域**：ML backends

#### C13. 数据库与文件系统操作不一致
- **文件路径/行号**：`src/mbforge/core/library.py:153-172`、`src/mbforge/core/library.py:199-221`、`src/mbforge/core/library.py:255-275`、`src/mbforge/pipeline/stages/persist_stage.py:38-64`
- **问题描述**：文件写入后再 INSERT、DB 删除后再删目录、DB commit 后再写文件；任一步失败都会留下孤儿文件或库状态不一致。
- **影响**：存储泄漏、DB 与磁盘状态不一致。
- **建议修复**：调整顺序或引入两阶段/saga；失败时补偿回滚。
- **原审查区域**：Core persistence / Pipeline

#### C14. 同步 HTTP 客户端阻塞异步 OCR 探测
- **文件路径/行号**：`src/mbforge/routers/ocr.py:41,69,98`
- **问题描述**：在 async route 里创建 `httpx.Client` 做同步出站请求。
- **影响**：阻塞事件循环。
- **建议修复**：改用 `httpx.AsyncClient`。
- **原审查区域**：Backend routers

#### C15. 删除/列表端点缺少异常处理 / 错误契约不一致
- **文件路径/行号**：`src/mbforge/routers/documents.py:29-37`、`src/mbforge/routers/library.py:158-162`、`src/mbforge/routers/molecule.py`
- **问题描述**：部分 endpoint 自己 catch `MBForgeError` 返回 `{"success": false}` + HTTP 200，绕过 `app.py` 的集中处理器，丢失 `error_code`/`severity`/`category`；有的端点完全不处理异常。
- **影响**：前端 `AppError` 无法正确识别错误类型，用户看到未分类 500。
- **建议修复**：统一抛出 `MBForgeError` 子类，由 `app.py` 统一渲染。
- **原审查区域**：Backend routers

#### C16. `LibraryStore` 返回错误 HTTP 状态码
- **文件路径/行号**：`src/mbforge/core/library.py:124`、`src/mbforge/core/library.py:540`、`src/mbforge/core/library.py:555`
- **问题描述**：文件/集合/文档不存在时抛出默认 `status_code=500` 的 `MBForgeError`。
- **影响**：前端无法区分“不存在”与服务器错误。
- **建议修复**：使用 `status_code=404, error_code="not_found"` 或定义子类。
- **原审查区域**：Core persistence

#### C17. 测试固件掩盖失败 / 测试认可路径遍历
- **文件路径/行号**：`tests/unit/test_routers_smoke.py:42-43`、`tests/unit/routers/test_pdf.py:22`
- **问题描述**：`client` fixture 在 `finally` 里 `c.close()` 但未确保 `c` 已绑定，会覆盖启动异常；`test_pdf.py` 对任意绝对 `pdf_path` 返回 200+空列表。
- **影响**：启动失败被掩盖；路径遍历被当作可接受行为。
- **建议修复**：`c = None` 并 `if c:` 关闭；更新测试为期望 400/422/404。
- **原审查区域**：Tests/tooling

#### C18. 前端 HTTP 桥接关键缺陷
- **文件路径/行号**：`frontend/src/api/http/_utils.ts:14`、`frontend/src/api/http/_utils.ts:85`、`frontend/src/api/http/notes.ts:24,37,45,54`、`frontend/src/api/http/library.ts:48`
- **问题描述**：`API_BASE = ''` 在非 Vite 环境或 jsdom 中解析失败；`httpFetch` 无条件加 `Content-Type: application/json`（会破坏 multipart/GET/DELETE）；`notes.ts` 仍发送 `libraryRoot` 而非 `library_root`（Phase 6 已移除别名）；`importDocument` 绕过 `httpFetch` 且不检查 `resp.ok`。
- **影响**：字段契约失效、multipart 上传失败、错误处理缺失、测试报 `Failed to parse URL`。
- **建议修复**：默认 `API_BASE = '/api/v1'` 或环境可覆盖；仅在 body 为字符串且无显式 header 时设 JSON Content-Type；统一字段为 `library_root`；`importDocument` 走 `httpFetch`。
- **原审查区域**：Frontend architecture

### 🟠 Important（建议近期修复）

#### I1. `project_root` 参数与文档仍保留，违背 Phase 6 清理
- **文件路径/行号**：`src/mbforge/pipeline/runner.py:128,146-152`、`tests/unit/pipeline/test_stages.py:101-124`、`AGENTS.md`
- **问题描述**：`run_pipeline` 仍接受 `project_root` 并回退；测试仍在验证该兼容行为；`AGENTS.md` 声称已移除。
- **建议修复**：删除 `project_root` 参数与回退，更新测试和文档。
- **原审查区域**：Pipeline / Tests/tooling / Docs

#### I2. API 边界使用原始 `dict`
- **文件路径/行号**：`src/mbforge/routers/molecule.py`、`src/mbforge/routers/library.py`、`src/mbforge/routers/agent.py`
- **问题描述**：返回/接受 `list[dict]`、`dict`，违反 AGENTS.md “API 边界不使用 raw dict”。
- **建议修复**：在 `src/mbforge/models/` 定义 Pydantic request/response 模型。
- **原审查区域**：Backend routers / Agent

#### I3. Lifespan prewarm 为 fire-and-forget
- **文件路径/行号**：`src/mbforge/app.py:42-43`
- **问题描述**：启动时把 `check_environment`/`_prewarm` 丢进 executor 不 await，立即报告 ready。
- **建议修复**：await startup futures 后再 `yield`，或提供 readiness probe。
- **原审查区域**：App

#### I4. 数据库连接/缓存无界与双连接问题
- **文件路径/行号**：`src/mbforge/core/database.py:23`、`src/mbforge/core/library.py:68`、`src/mbforge/core/database.py:330,345`、`src/mbforge/core/database.py:269-274`
- **问题描述**：`_db_cache`、`_store_cache` 无逐出；统一库布局下 `kb_conn()`/`mol_conn()` 仍开两个独立连接；双检锁使用普通 `bool`。
- **建议修复**：使用 `lru_cache`/有界 map；同文件返回同一连接；用 `threading.Event`。
- **原审查区域**：Core persistence

#### I5. `knowledge_base.search` 广泛吞掉异常
- **文件路径/行号**：`src/mbforge/core/knowledge_base.py:36`
- **问题描述**：catch `Exception` 后返回 fallback dict。
- **建议修复**：捕获具体 OpenKB/backend 异常，或返回带 `error_code` 的结构。
- **原审查区域**：Core persistence

#### I6. 模型下载缺少完整性校验
- **文件路径/行号**：`src/mbforge/core/resource_manager.py:492-628`
- **问题描述**：从 ModelScope 下载多 GB 模型文件不做 checksum/size 校验。
- **建议修复**：`ResourceInfo` 加 SHA-256/expected size，下载后校验。
- **原审查区域**：Core persistence

#### I7. `extract_activities` 向本地 `base_url` 发送真实 API key
- **文件路径/行号**：`src/mbforge/pipeline/extract_activities.py:279-283`
- **问题描述**：`api_key=cfg.llm.api_key or "dummy"` 会把真实 key 发到自托管 endpoint。
- **建议修复**：本地/自托管 endpoint 不显式传 key，或按 provider 显式配置。
- **原审查区域**：Pipeline

#### I8. Activity 列检测使用松散子串匹配
- **文件路径/行号**：`src/mbforge/pipeline/extract_activities.py:233-235`
- **问题描述**：`str(rec.value_original) in cell` 会导致 `12.5` 匹配 `112.5`。
- **建议修复**：精确归一化比较或带容差数值比较。
- **原审查区域**：Pipeline

#### I9. Stage 假设前置输出非 `None`
- **文件路径/行号**：`src/mbforge/pipeline/stages/index_stage.py:69`、`src/mbforge/pipeline/stages/reorganize_stage.py:59`、`src/mbforge/pipeline/stages/persist_stage.py:127-133`
- **问题描述**：直接解引用 `ctx.density`/`ctx.extracted` 等，前置 recoverable 错误后可能 `AttributeError`。
- **建议修复**：加显式空值检查或返回缺失上下文错误。
- **原审查区域**：Pipeline

#### I10. 化学元素白名单可能拒绝有效分子
- **文件路径/行号**：`src/mbforge/pipeline/normalize.py:170-178`
- **问题描述**：白名单排除常见金属与主族元素，拒绝有机金属/无机物。
- **建议修复**：配置化并文档化行为。
- **原审查区域**：Pipeline

#### I11. `_map_span_idx_to_line` 可能把 MoleCode 块插入错误位置
- **文件路径/行号**：`src/mbforge/pipeline/organizer.py:137-148`
- **问题描述**：只用 span 前 20 个字符作为子串 needle，重复文本时定位错误。
- **建议修复**：使用行索引 + 页边界等更精确锚点。
- **原审查区域**：Pipeline

#### I12. `IndexStage` 每次调用新建 `ThreadPoolExecutor`
- **文件路径/行号**：`src/mbforge/pipeline/stages/index_stage.py:18-31`
- **问题描述**：每篇文档创建一个单 worker executor，造成线程抖动/泄漏。
- **建议修复**：使用模块级共享 executor 或 `asyncio.to_thread`。
- **原审查区域**：Pipeline

#### I13. `moldet_api` 请求参数未校验范围
- **文件路径/行号**：`src/mbforge/routers/moldet_api.py:213-217`
- **问题描述**：`dpi`、置信度阈值、`page` 未做范围校验；过高 dpi 可耗尽内存。
- **建议修复**：Pydantic 模型加 `ge`/`le` 或 clamp。
- **原审查区域**：Backend routers / OpenKB/parsers

#### I14. Coref 缓存键不足 / 缓存无界
- **文件路径/行号**：`src/mbforge/routers/coref.py:131-138`、`src/mbforge/routers/coref.py:133-137`
- **问题描述**：缓存键未包含 dpi/阈值/模型版本；过期条目未清理，全为 fresh 时超过 256。
- **建议修复**：参数入键；加 LRU/大小上限。
- **原审查区域**：Backend routers / OpenKB/parsers

#### I15. `PageIndexWrapper.add_document` 忽略调用方 `doc_id`
- **文件路径/行号**：`src/mbforge/openkb/indexer.py:58-65`
- **问题描述**：接受 `doc_id` 但调用 `col.add(pdf_path)` 返回 PageIndex 自分配 ID。
- **建议修复**：使用传入 `doc_id` 或删除参数。
- **原审查区域**：OpenKB

#### I16. `decode_base64_image` 未校验输入
- **文件路径/行号**：`src/mbforge/utils/helpers.py:157-164`
- **问题描述**：任意 base64 解码并 PIL open，无大小/MIME 限制。
- **建议修复**：加尺寸上限、限制图片 MIME。
- **原审查区域**：OpenKB/parsers / Utils

#### I17. `molscribe.predict_batch` 未真正批处理
- **文件路径/行号**：`src/mbforge/backends/molscribe.py:94-100`
- **问题描述**：循环单张调用 `predict`，未利用后端 batch 能力。
- **建议修复**：全部转 PIL 后一次性 `_MODEL.predict_images(images)`。
- **原审查区域**：ML backends

#### I18. MinerU SSL 全局修改 / ZIP 下载无边界
- **文件路径/行号**：`src/mbforge/backends/ocr/mineru.py:53-58`、`src/mbforge/backends/ocr/mineru.py:290-302`
- **问题描述**：修改 `SSL_CERT_FILE` 影响全局；ZIP 整体读入内存，不限制条目/大小。
- **建议修复**：`verify=certifi.where()` 传参；流式下载、限制总字节与条目数。
- **原审查区域**：ML backends / OCR

#### I19. Agent LLM 工厂与流式错误处理
- **文件路径/行号**：`src/mbforge/agent/llm_factory.py:51-55`、`src/mbforge/agent/graph.py:107-110`、`src/mbforge/routers/agent.py:187-194`
- **问题描述**：`ollama` 被错误要求 API key；`request_timeout` 未传给 LangChain；`stream_agent_response` 吞异常后重抛导致客户端收到重复错误；SSE 只处理 `chunk`/`tool_call`/`tool_result`，忽略 `error` 事件。
- **建议修复**：单独处理 `ollama`、传 timeout、统一错误事件流。
- **原审查区域**：Agent

#### I20. 前端 HTTP 桥接重要缺陷（流/取消/类型安全）
- **文件路径/行号**：`frontend/src/api/http/sse.ts:96-125`、`frontend/src/api/http/sse.ts:71-79`、`frontend/src/api/http/download.ts:150-197`、`frontend/src/api/http/agent.ts:86-95`、`frontend/src/api/http/_utils.ts`
- **问题描述**：`fetchSSE` 不 abort 导致 stream 泄漏；重连 backoff 成功后不重置；`downloadModel` 取消不中止请求；`httpFetch<T>` 盲 `resp.json()` cast；`agentChat` 不检查 `success`。
- **建议修复**：返回 cleanup/AbortController；重置 backoff；验证 `success`；引入 Zod 等运行时校验。
- **原审查区域**：Frontend architecture

#### I21. 前端全局状态与轮询竞争
- **文件路径/行号**：`frontend/src/App.tsx:83-95`、`frontend/src/context/AppContext.tsx:79-82`、`frontend/src/App.tsx:99-109`、`frontend/src/context/AppContext.tsx:109-123,125-140`、`frontend/src/hooks/useIngestNotifications.ts:12-13,24-63`、`frontend/src/hooks/useMoleculeLibrary.ts:127-130`、`frontend/src/hooks/useSidecarEvents.ts:14-41`
- **问题描述**：`libraryRoot` 有 backend 状态与 `localStorage` 两个来源；tab updater 里嵌套 setState；ingest 轮询依赖 `[pathname]` 忽略 root 变化；`useMoleculeLibrary` 拉 10000 行客户端分页；`useSidecarEvents` 轮询但无暴露状态。
- **建议修复**：backend 状态为唯一真源；用 reducer 管理 tabs；轮询加入 `libraryRoot` 依赖或转 React Query；后端分页；移除/暴露 dead hook。
- **原审查区域**：Frontend architecture

#### I22. 前端组件重要缺陷
- **文件路径/行号**：`frontend/src/components/project/pdf/usePdfViewer.ts:285,469`、`frontend/src/components/project/pdf/useIngestPipeline.ts:25,54`、`frontend/src/components/project/ProcessingQueue.tsx:59,94,108,239`、`frontend/src/components/project/pdf/CorefBboxOverlay.tsx:229`、`frontend/src/components/molecule/MoleculeOverlay.tsx:92,98`、`frontend/src/components/ui/MermaidCode.tsx:72`、`frontend/src/components/chat/chatUtils.tsx:19`、`frontend/src/components/settings/SettingsPage.tsx:71`、`frontend/src/components/PdfCanvas.tsx:14-30,195`、`frontend/src/components/project/pdf/usePdfViewer.ts:80`、`frontend/src/components/discover/ChatTab.tsx:168`、`frontend/src/components/project/pdf/useIngestPipeline.ts:38,70`
- **问题描述**：object URL 未 revoke；`embedState` 死状态、task lookup 不依赖 `docId`；`logMap` 无界且预取 500 条/任务；按 SMILES 字符串等价配对 coref；`is_quick_scan` 用类型强转且 key 用索引；`dangerouslySetInnerHTML` 未 sanitize；系统主题 fallback 写死 dark；PDF.js document 不 destroy；base64 PNG 过大；路径归一化脆弱；Windows basename 错误；假设 `created_at` 为数字。
- **建议修复**：revoke URL；补全依赖与状态；LRU/按需取 log；用 `label_id`/prediction 关系配对；修正 schema；加 DOMPurify；读 `prefers-color-scheme`；destroy 文档；后端解析路径；跨平台 basename；校验时间类型。
- **原审查区域**：Frontend components

#### I23. 核心层其他重要问题
- **文件路径/行号**：`src/mbforge/core/resource_manager.py:869-881`、`src/mbforge/core/migration.py:137-219`、`src/mbforge/core/migration.py:296,427`、`src/mbforge/core/library.py:440-447`、`src/mbforge/core/library.py:312`、`src/mbforge/core/semantic_cache.py:40`、`src/mbforge/core/file_scanner.py:124`、`src/mbforge/routers/settings.py:19-25`、`src/mbforge/routers/knowledge_base.py:148,163,178`
- **问题描述**：`info` 可能 `None` 被访问；迁移模块重复 KB schema；SQL f-string 表名；循环变量命名误导；`LIKE ?` 未转义 `%/_`；semantic cache 吞异常；file scanner 静默跳过权限错误；secret redaction 过度（会隐藏 `keyword`/`monkey`）；`/kb/wiki/*` 把原始 `library_root` 传给 `LibraryLayout`。
- **建议修复**：guard、复用 schema、whitelist 表名、修改变量、escape wildcard、记录异常类型、log warning、精确 key 列表/词边界、传已解析的 `_root`。
- **原审查区域**：Core persistence / Routers

#### I24. 测试/工具配置漂移
- **文件路径/行号**：`pyproject.toml:123`、`pyproject.toml:151`、`pyproject.toml`（pytest-asyncio 未配置）、`tests/unit/test_routers_smoke.py`（全局状态 mutation）、`frontend/src/components/project/__tests__/ProcessingQueue.test.tsx`、`frontend/src/api/http/_utils.test.ts` + `frontend/src/api/http/__tests__/_utils.test.ts`、`tests/unit/test_version_consistency.py:3-7`、`AGENTS.md`
- **问题描述**：ruff target-version 为 py311 与 requires-python >=3.12 不匹配；ruff ignore 指向已删除 `src/mbforge/gui`；pytest-asyncio 未配置；fixture 直接赋值全局模块变量；测试缺 `libraryRoot`；`_utils` 测试重复；import 顺序违规；`AGENTS.md` 测试清单与 `project_root` 状态陈旧。
- **建议修复**：更新 target-version、移除 stale ignore、加 pytest-asyncio 配置、用 `monkeypatch`、补充 mock root、合并重复测试、fix import、刷新文档。
- **原审查区域**：Tests/tooling / Docs

#### I25. 缺失测试覆盖
- **文件路径/行号**：`tests/unit/backends/`（OCR backends 无测试）、`tests/unit/openkb/`（adapter/indexer 集成缺失）、`src/mbforge/parsers/molecule/coref_alt.py` / `coords.py` / `preprocess.py` / `extraction_result.py`、`src/mbforge/core/resource_manager.py` 下载安装路径、`src/mbforge/core/artifact.py` symlink/`..` 边界、`tests/unit/core/` 并发锁库行为、`tests/unit/pipeline/test_extract_molecules.py` 失败分支、`src/mbforge/core/library.py` 错误路径
- **问题描述**：上述关键路径缺少直接测试，多个 Critical/Important 问题本可被单测捕获。
- **建议修复**：补齐对应单元/集成测试，尤其路径 traversal、OCR fallback、并发单例。
- **原审查区域**：Tests/tooling

#### I26. OpenKB 读取 wiki 源文件无大小限制
- **文件路径/行号**：`src/mbforge/openkb/query.py:107-113`
- **问题描述**：把整个 wiki 树 `.md`/`.json` 读入内存，恶意大文件可 OOM。
- **建议修复**：加文件大小上限并跳过超限文件。
- **原审查区域**：OpenKB

#### I27. MolDetv2-FT 置信度阈值不一致
- **文件路径/行号**：`src/mbforge/backends/moldet_v2_ft.py:71`、`src/mbforge/parsers/molecule/coref_alt.py:177-178`
- **问题描述**：detector 默认 `conf=0.5`，下游 `mol_conf_threshold=0.3`，导致 0.3–0.5 区间 box 被上游提前丢弃。
- **建议修复**：统一阈值或让 detector 成为可配置 gate。
- **原审查区域**：ML backends / Parsers

#### I28. `coref_alt` 检测加载器广泛吞异常
- **文件路径/行号**：`src/mbforge/parsers/molecule/coref_alt.py:159-169`
- **问题描述**：catch `Exception` 后返回 `None`，隐藏安装错误/CUDA OOM/模型损坏。
- **建议修复**：捕获具体异常并传播意外错误，或在 health 暴露。
- **原审查区域**：Parsers

#### I29. `coref_alt` 废弃参数与 stale 注释
- **文件路径/行号**：`src/mbforge/parsers/molecule/coref_alt.py:172-179`、模块 docstring、`_bbox_iou` 注释
- **问题描述**：`page_width`/`page_height` 被 `_pair_corefs` 忽略；docstring 仍称“无需 OCR”；`_bbox_iou` 注释说 pixel bboxes 但输入已归一化。
- **建议修复**：删除无用参数或文档化；更新注释。
- **原审查区域**：Parsers

### 🟡 Minor（可择机改进）

#### M1. 代码风格、导入与日志一致性
- **文件路径/行号**：`src/mbforge/routers/render.py:52`、`tests/unit/test_version_consistency.py:3-7`、`src/mbforge/backends/__init__.py:13` / `backends/ocr/local.py:22` / `mineru.py:29` / `paddleocr.py:21` / `glmocr.py:32` / `chain.py:27`、`src/mbforge/core/resource_manager.py:22`、`src/mbforge/core/library.py:203,270`、`src/mbforge/parsers/molecule/coref_alt.py` / `coords.py`、`frontend/src/context/AppContext.tsx:2`
- **问题描述**：ruff W292 缺换行、import 顺序、多处使用 `logging.getLogger` 而非项目 `get_logger`、函数内延迟 import、中英注释混杂、`../utils/path` 未用 `@/` 别名。
- **建议修复**：`ruff format/check`、统一 logger、上移 import、统一英文注释、修别名。
- **原审查区域**：All

#### M2. 陈旧注释与文档字符串
- **文件路径/行号**：`src/mbforge/routers/documents.py:1`、`src/mbforge/routers/molecule.py:1`、`src/mbforge/app.py:67-70`、`src/mbforge/core/database.py:1-6`、`src/mbforge/pipeline/runner.py:138`、`src/mbforge/pipeline/context.py:30-31`、`src/mbforge/backends/ocr/local.py:1-9`、`src/mbforge/agent/graph.py:19-29`
- **问题描述**：docstring 仍提已废弃别名、错误路由器数量、两库布局、合并前阶段、不存在的 `get_rapid_ocr`、未实际抛出的异常类型 TODO。
- **建议修复**：逐条更新注释与文档。
- **原审查区域**：Backend routers / Core / Pipeline / OCR / Agent

#### M3. 死代码 / 重复代码
- **文件路径/行号**：`src/mbforge/routers/health.py` + `src/mbforge/routers/health_router.py`、`src/mbforge/routers/models_router.py:56-84`、`src/mbforge/backends/moldet.py` / `moldet_v2_ft.py`（`default_model_dir`）、`frontend/src/api/http/molecule.ts`、`frontend/src/api/http/project.ts`、`frontend/src/hooks/useSidecarEvents.ts`、`frontend/src/hooks/useDocResult.ts:6-11,36-37`
- **问题描述**：两套 health router 仅一套注册；RDKit render 端点重复；`default_model_dir` 重复；frontend molecule/project HTTP 层多为占位；`useSidecarEvents` 无消费；字段已废弃。
- **建议修复**：删除/合并重复模块，清理占位代码。
- **原审查区域**：Backend routers / ML backends / Frontend

#### M4. 魔法数字与硬编码默认值
- **文件路径/行号**：`src/mbforge/routers/text.py:80`、`src/mbforge/backends/moldet_v2_ft.py:65,191-199`、`src/mbforge/backends/ocr/rapidocr_adapter.py:156`、`src/mbforge/agent/llm_factory.py`、`src/mbforge/pipeline/extract_text.py:76`、`src/mbforge/pipeline/extract_molecules.py:25`、`src/mbforge/pipeline/organizer.py:336`、frontend 各组件
- **问题描述**：阈值、模型名、base URL、worker 数、分页/日志限制、debounce 时间等散落各处。
- **建议修复**：集中到 `config/constants` 并附推导说明。
- **原审查区域**：Backend / Frontend

#### M5. 前端 UI/UX 细节
- **文件路径/行号**：`frontend/src/components/settings/SettingsPage.tsx`（Cancel 行为）、`frontend/src/components/library/LibraryPanel.tsx:95`、`frontend/src/components/library/GroupsPanel.tsx`、`frontend/src/components/molecule/MoleculeFilters.tsx`、`frontend/src/components/settings/ApiKeyInput.tsx` / `SidecarCard.tsx`、`frontend/src/components/project/PdfViewer.tsx:278`、`frontend/src/components/molecule/MoleculeTable.tsx`、`frontend/src/hooks/useTheme.ts:12`、`frontend/src/api/http/agent.ts:97-101`、`src/mbforge/agent/graph.py:102`、`frontend/src/api/sse.ts` / `frontend/src/api/http/agent.ts`、`frontend/src/components/discover/ChatTab.tsx`
- **问题描述**：按钮无响应、递归无深度限制、`NaN`、timeout 未清理、分页不 clamp、全选逻辑低效、忽略系统主题、TS 事件类型与后端不匹配、工具输出静默截断、工具事件不展示、重复初始化 session。
- **建议修复**：逐项修正交互与类型。
- **原审查区域**：Frontend components / Agent

#### M6. 类型与测试质量小改进
- **文件路径/行号**：`src/mbforge/pipeline/stage_result.py:15-30`、`src/mbforge/agent/sessions.py`（`AgentState` 用 `Any`）、`src/mbforge/app.py:73`、`frontend` 多处测试、`tests/conftest.py:77`、前端 `__tests__` 布局
- **问题描述**：`PipelineErrorCode` 为类字符串常量无类型检查；`AgentState` 字段类型弱；middleware 未类型化；测试断言过浅；patch 范围不足；测试目录与 AGENTS.md 约定不一致。
- **建议修复**：改用 `Enum`/`Literal`、加类型、用 `monkeypatch`、合并重复 `_utils` 测试、迁移到 co-located `*.test.*`。
- **原审查区域**：Pipeline / Agent / Tests/tooling

#### M7. Pipeline/Organizer 资源清理与冗余
- **文件路径/行号**：`src/mbforge/pipeline/extract_text.py:18,64`、`src/mbforge/pipeline/stages/markdown_stage.py:63-65,83-85`、`src/mbforge/pipeline/runner.py:241-246`、`src/mbforge/pipeline/organizer.py:336`、`src/mbforge/openkb/compiler.py:56-63`、`src/mbforge/openkb/query.py:145-150`
- **问题描述**：`fitz` 重复 import；异常时临时文件未清理；每次运行都验证 stage 协议；chunk budget 无解释；短文档路径 `source_path` 可能不存在；页码正则窄。
- **建议修复**：去重 import、try/finally 清理、协议验证移导入期、文档化预算、校验路径、扩展正则。
- **原审查区域**：Pipeline / OpenKB

#### M8. 其他 Minor
- **文件路径/行号**：`src/mbforge/core/knowledge_base.py:87-92`、`src/mbforge/parsers/molecule/extraction_result.py:68-84`、`src/mbforge/openkb/adapter.py:69-78`、`src/mbforge/core/library.py:175-182,224-231`、`frontend/src/components/OcrConfigModal.tsx:137,146` + `AppShell.tsx:56`
- **问题描述**：`get_document_pages` 全量读内存；`ExtractionResult.from_dict` 过于宽松；OpenKB adapter 直接 `shutil.copy2` 且未校验源路径；`created_at` 返回空字符串；`OcrConfigModal` 引用未定义 `close` 但当前永不渲染。
- **建议修复**：按需流式/迭代、加 Pydantic 校验、经 `ArtifactResolver` 校验源路径、返回真实时间戳、删除或修复 modal。
- **原审查区域**：Core / Parsers / OpenKB / Frontend components

## 3. 按主题聚类的问题

### 主题 1：路径遍历 / 不安全文件系统访问
- **涉及问题**：C1、C8、C17、I16、I23（knowledge_base.py 传原始 root）、I25（缺少 traversal 测试）、M8（adapter copy2）
- **整体建议**：以 `ArtifactResolver`/`LibraryLayout` 为唯一权威入口，所有 request path 必须 `resolve()` + `relative_to()` 校验；上传文件名消毒；base64 图片加大小/MIME 限制；测试必须把“绝对路径探测”改为期望 400/422/404。

### 主题 2：异步阻塞 I/O / 并发安全
- **涉及问题**：C4、C9、C14、I12、I17、I19（RDKit 计算）、I28、M7
- **整体建议**：建立共享线程池；所有模型加载加锁；所有 sync CPU/IO（RDKit、MolScribe、PyMuPDF、SQLite 扫描、LLM invoke、OCR 探测）通过 `run_in_executor`/`to_thread` 调度；统一 `AsyncClient` 做外网调用。

### 主题 3：API 契约与类型安全
- **涉及问题**：C2、C15、C16、C18、I2、I13、I19、I20、I24、M2、M6
- **整体建议**：后端端点全部改用 Pydantic request/response 模型；前端关键响应引入 Zod/运行时校验；统一 `error_code`/`severity`/`category` 返回；完成 Phase 6 的 `project_root` 清理；更新 `AGENTS.md` 以匹配实际代码。

### 主题 4：错误处理与边界情况
- **涉及问题**：C3（OCR IndexError）、C11、C15、C17、I5、I9、I23、I28、M2、M7
- **整体建议**：用结构化错误替代 `except Exception`；stage 间上下文加空值守卫；OpenKB adapter 明确 sync/async 边界；清理 stale 异常类 TODO。

### 主题 5：ML / Coref / OCR 正确性
- **涉及问题**：C2、C3、C6、C9、I14、I16、I17、I18、I26、I27、I29、M4、M8
- **整体建议**：修正 coref 索引映射；OCR identifier crops 获取真实文本；恢复 RapidOCR 页面 fallback；统一置信度阈值；模型反序列化切 `weights_only=True`；OCR/ZIP/图片加资源边界。

### 主题 6：Agent / LLM 集成
- **涉及问题**：C5、C7、I19、M5、M6
- **整体建议**：graph config 传递 `library_root`；工具避免在事件循环内新建 loop；实现缺失的 session project endpoint；给 history 加 cap；正确传递 timeout；SSE 处理 error 事件。

### 主题 7：前端状态管理与 HTTP 桥接
- **涉及问题**：C10、C18、I20、I21、I22、M3、M5、M6
- **整体建议**：统一 `API_BASE`；全部请求走 `httpFetch`；移除无条件 JSON Content-Type；以 backend 状态为 `libraryRoot` 唯一真源；用 reducer 重构 tabs；轮询/订阅改用 React Query；SSE 支持 abort。

### 主题 8：资源限制与内存安全
- **涉及问题**：C8、I6、I12、I14、I21（10000 rows）、I22（logMap）、I26、M7、M8
- **整体建议**：上传/下载/Wiki 文件/图片 base64 全部加 size cap；缓存使用 LRU；`ThreadPoolExecutor` 共享；前端分页后端化；PDF.js document 正确 destroy。

### 主题 9：测试覆盖与工具链
- **涉及问题**：C17、I1、I24、I25、M1、M6
- **整体建议**：补齐 OCR/backend/OpenKB/ArtifactResolver/并发单测；修复 fixture 与全局状态隔离；`pyproject.toml` 更新 target-version 与 pytest-asyncio；合并重复测试；刷新 `AGENTS.md`。

### 主题 10：文档/注释/配置漂移
- **涉及问题**：I1、I24、M2、M3、M4
- **整体建议**：统一英文注释；删除死代码；将魔法数字迁移到配置；更新 `AGENTS.md` 中 stage 数量、测试清单、目录结构说明。

## 4. 优先修复路线图

### 本周（安全 + 核心正确性）
- **目标**：消除可导致数据泄露、崩溃、核心功能失效的 Critical 风险。
- **修复项**：C1 路径遍历、C2 coref 标签映射、C3 OCR fallback/IndexError、C4 关键路径阻塞 I/O、C5 os.environ 污染、C6 unsafe `torch.load`、C7 Agent `library_root`/死锁、C8 上传大小/文件名、C9 单例加锁、C10 前端硬编码 URL、C14 OCR 探测 sync HTTP、C15/C16 错误契约与状态码、C17 测试 fixture、C18 前端 HTTP 桥接。
- **验收标准**：
  - 所有 endpoint 对 `pdf_path`/`library_root` 返回 400/422；无法通过绝对路径读取系统文件。
  - `pytest tests/unit/routers/test_pdf.py` 期望拒绝绝对路径。
  - Agent 工具在真实 session 下能命中用户库。
  - OCR 本地 fallback 测试通过；`_ocr_pages` 非连续页不抛 IndexError。
  - `uv run ruff check src/` 与 `pytest tests/unit/` 全绿。

### 本月（并发、资源边界、契约统一）
- **目标**：提升并发稳定性、资源可控性、API 契约一致性。
- **修复项**：I2 Pydantic 模型、I3 prewarm 就绪、I4 DB 缓存/双连接、I5/I23 异常处理、I6 下载校验、I7/I8/I10/I11 pipeline 细节、I12/I17 线程池/批处理、I13/I14 参数校验与缓存、I15 PageIndex doc_id、I18 MinerU SSL/ZIP、I19/I20/I21 前端流/状态、I26/I27/I28/I29 OpenKB/parsers 细节、M3/M7 清理死代码与冗余。
- **验收标准**：
  - 并发首次调用 MolDet/MolScribe 只产生一个实例。
  - 上传 > 上限文件返回 413；Wiki/图片读取带 size cap。
  - router/agent 全部使用 Pydantic 模型，`httpFetch` 不自动破坏 multipart。
  - `npx tsc --noEmit` 与 `npm run test` 无新增错误。

### 季度（测试覆盖、文档、工程体验）
- **目标**：补齐测试、统一文档、还清技术债。
- **修复项**：I25 缺失测试、I24 工具链配置、M1/M2/M4/M5/M6 风格/注释/常量/UI polish、I21 前端状态重构、I22 组件资源管理。
- **验收标准**：
  - OCR backends、OpenKB adapter/indexer、ArtifactResolver traversal、并发单测覆盖。
  - `AGENTS.md` 与代码一致；所有注释无 stale 引用。
  - 核心逻辑测试覆盖率 ≥70%。

## 5. 值得肯定的方面

- **清晰的分层与单一权威路径**：`LibraryLayout` + `ArtifactResolver` 集中管理库级与文档级路径，路径遍历防御在核心位置已成型。
- **集中式错误处理**：`app.py` 将 `MBForgeError` 映射为带 `error_code`/`severity`/`category` 的结构化 JSON，与前端 `AppError` 契约对齐。
- **阶段化 Pipeline 设计**：`StageExecutor` 协议 + `PipelineContext` + `StageResult` 使各阶段职责清晰，错误传播与可恢复性设计良好。
- **前端架构规范**：`httpFetch`、React Query、SSE 重连、类型化错误模型、严格 TypeScript 等基础设施已具备。
- **测试基础扎实**：`conftest.py` 提供 temp 库、自动清缓存、真实 SQLite/RDKit/文件 I/O；迁移测试覆盖 dry-run、幂等性、校验失败等场景。
- **失败降级与迁移友好**：OCR/coref 后端在不可用时空结果而非崩溃；`moldet_api.py` 对删除的 legacy endpoint 返回 `410 Gone`。
- **安全默认值**：外部链接使用 `noopener noreferrer`、KaTeX `trust: false`、Mermaid `securityLevel: 'strict'`、settings 端点会脱敏 API key。

---

**报告生成说明**：本报告基于 9 个子代理的审查输出综合整理，未引入输入文件以外的推断；所有文件路径与行号均来自原始子代理输出。
