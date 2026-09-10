# 兼容性代码审计清单

审计范围：`src/mbforge/`（Python 后端）、`frontend/src/` + 构建配置（React 19 / Vite 8 / TS）、`tests/`。
审计日期：2026-09-07。

## 判断基线

| 项 | 值 | 来源 |
|---|---|---|
| Python | `>=3.12,<3.13` | `pyproject.toml:33` |
| 平台 | Windows + Linux 双平台（进程治理代码显式分支） | `infra/process/*` |
| 前端 target | `ES2020`，无 browserslist | `frontend/tsconfig.json:3` |
| 打包 | 无 PyInstaller / 无 `.spec` / 无打包脚本 | 全仓 grep |
| DB 约定 | "Local SQLite is disposable development data: update the canonical schema directly and add migrations only after an owner-approved ADR" | `AGENTS.md` |

---

## B 类：先迁移调用方，再删除

| # | 文件路径:行 | 兼容目的 | 关键逻辑 | 迁移工作量 |
|---|---|---|---|---|
| B1 | `frontend/src/components/ui/Badge.tsx:8-13,21-24` | `variant` 旧 props 别名 | `function effectiveTone(tone, variant) { if (tone) return tone === 'loading' ? 'neutral' : tone; return variant ?? 'neutral' }` | 仍在用 `variant` 的 4 处：`StatusBadge.tsx:13,15,17,19`、`CompoundCard.tsx:70`、`MoleculeCardGrid.tsx:145`、`BacklinksPanel.tsx:16`。改用 `tone` 后删除 `variant` 字段与 `effectiveTone`。注意 `tone` 多一个 `'loading'` 值 |
| B2 | `frontend/src/components/ui/SettingSection.tsx:18-19` | 类型别名 | `export type SettingSectionProps = SettingItemProps` | `components/ui/types.ts:25` 有 re-export。确认无外部 import 后一并删除 |
| B3 | `frontend/src/api/http/index.ts:1-19` | "legacy importers" 聚合 barrel | `export * from './_utils'` … | 未发现 `from '@/api/http'` 裸导入（所有引用都带子路径）。确认后删整文件 |
| B4 | `frontend/src/utils/errors.ts:65-83` | `new AppError(code, msg, ctx)` 旧位置参数 | `if ('severity' in opts \|\| ...) {...} else { this.context = opts }` | 现存 3 处旧式调用 + `utils/__tests__/errors.test.ts:32,38,51`。改为 `new AppError(code, msg, { context })` 后删 else 分支 |
| B5 | `frontend/src/components/ui/Toast.tsx:50-61` | `showToast` 字符串/对象双签名 | `if (typeof messageOrItem === 'string') { item = {message, type} } else { item = messageOrItem }` | grep `showToast('` 旧式调用，迁移为对象签名后简化 |
| B6 | `frontend/src/styles/theme.css:39,71-74,92-94,105-108` | legacy 设计令牌别名 | `--border-light`、`--radius-sm/lg/xl`、`--shadow-card/elevated`、`--font-size-small/base/large/title` | 逐个 grep 引用；零引用即删 |
| B7 | `frontend/src/api/http/pdf.ts:40` + `components/project/pdf/usePdfDetections.ts:101` | 旧产物文件名注释 | 注释中提及 legacy `detections.json` 回退 | 纯注释，无代码；随文档清理 |

---

## C 类：保留（真实兼容，删除会破坏功能）

### C1 跨平台 / 操作系统（核心进程治理，必须保留）

| 文件:行 | 分支 | 说明 |
|---|---|---|
| `infra/process/filelock.py:103-110` | `os.name == "nt"` → `msvcrt.locking`；else → `fcntl.flock` | 解锁原语无跨平台统一 API |
| `infra/process/filelock.py:156-163` | `msvcrt.LK_NBLCK` vs `fcntl.LOCK_EX\|LOCK_NB` | 加锁原语 |
| `infra/process/discovery.py:54` | `_enumerate_windows()` vs `_enumerate_posix()` | 进程枚举（PowerShell/CIM vs `ps -eo`） |
| `infra/process/discovery.py:151` | `_port_listeners_windows()` vs `_posix()` | 端口监听（`netstat` vs `ss`） |
| `infra/process/discovery.py:222-249` | CIM `Win32_Process` vs `/proc/{pid}/status` | 父 PID 查询 |
| `infra/process/discovery.py:336` | `if os.name != "nt": return True` | CreationDate 校验在 POSIX 无对应语义 |
| `infra/process/identity.py:42-64` | `os.name == "nt"` → `ctypes.windll.kernel32.OpenProcess`；else → `os.kill(pid, 0)` | Windows 上 `os.kill(pid,0)` 语义不足 |
| `infra/process/reaper.py:255-262` | `platform.system() == "Windows"` → `taskkill /PID /F`；else → `os.kill(SIGKILL/SIGTERM)` | 终止原语 |
| `utils/logger.py:195` | `console_stream.reconfigure(encoding="utf-8")` | Windows 控制台默认 cp1252 会破坏中文日志 |
| `app.py:42-43` | `getattr(exc, "winerror", None) == 10054 or getattr(exc, "errno", None) == 10054` | SSE 客户端断开；非兼容代码，是良性传输层错误处理 |

### C2 遗留数据 / 字段别名（真实旧数据兼容，必须保留）

| 文件:行 | 逻辑 | 说明 |
|---|---|---|
| `storage/layout.py:358` | `data.get("library_root") or data.get("libraryRoot")` | 对外 API camelCase 契约，集中式单点别名 |
| `storage/markush_transitions.py:185-187` | `properties.get("scaffold_id")` 回退 | 旧版把 scaffold_id 内嵌在 properties JSON |
| `pipeline/persist/markush.py:50-66` | `formula_label` / `label` 旧键回退 | SQL 单列前的旧属性键名 |
| `pipeline/activity/extraction.py:139-151` | `__post_init__` 填充 `metric`/`value_canonical`/`unit_canonical`/`operator_original` | 老调用方构建的 `ActivityRecord` |
| `services/documents/library.py:340-353` | `LibraryLayout(root).source_pdf(doc_id)` 回退 | 未注册进 LibraryStore 的迁移前专利 |
| `services/molecule/queries.py:382` | 无 bbox 产物时回退 `_molecules_by_location_db` | legacy 数据查询路径 |
| `services/molecule/recorrection.py:106-107,193` | `row_dict.get("canonical_smiles") or row_dict.get("smiles","")` | DB 旧字段别名 |
| `services/chem/chem.py:170` | `candidate.get("smiles") or candidate.get("canonical_smiles")` | 同上 |
| `core/detection/types.py:147` | `data.get("esmiles","") or data.get("smiles","")` | 旧识别结果字段别名 |
| `services/documents/activity_queries.py:233` | `record.get("activity_id") or record.get("review_id")` | 旧 ID 字段 |
| `services/pipeline/detection_cache.py:73`、`services/documents/pdf_layout.py:132` | 响应同时带 `results` 与 `detections` 键 | 对外 API 响应契约，前端可能仍按旧键读 |
| `models/*.py` 的 `AliasChoices` | `library_root`/`libraryRoot`、`doc_id`/`docId`、`coreSmiles`/`core_smiles` | Pydantic 官方的 camelCase 兼容手段，最干净 |

### C3 真·可选依赖（extras 未装时的正确降级，保留）

| 文件:行 | 依赖 | 说明 |
|---|---|---|
| `backends/device.py:27-32` | torch | `[gpu]` extra，CPU-only 安装无 torch |
| `infra/resource_manager.py:551` | torch | 同上 |
| `pipeline/detection/image_preprocessing.py:26-31` | scikit-learn | `[local-models]` extra，缺失时 `_SKLEARN_AVAILABLE=False` 退回原始 crop |
| `infra/model_downloader.py:91` | modelscope | `[local-models]` extra，缺失走直连 HTTP 下载 |
| `infra/model_downloader.py:232-235` | huggingface_hub | **见 D1**：依赖未声明，但 except 行为正确，保留 |
| `backends/ocr/chain.py:50` | — | `hasattr(ocr_config, "model_dump")` 兼容 dict / Pydantic 两种入参 |
| `backends/moldet_v2_ft.py:235` | — | `hasattr(im, "width")` 兼容 PIL.Image / numpy 两种入参 |

### C4 前端真实兼容（保留）

| 文件:行 | 内容 | 说明 |
|---|---|---|
| `frontend/vite.config.ts:43-62` + `process-shim.json` | `window.process` 注入 | `ketcher-standalone` 预打包产物含 `process.env.X`，浏览器无 `process` 会抛 ReferenceError。依赖 ketcher 就必须保留 |
| `frontend/vite.config.ts:64-73,82-97` | `global: 'globalThis'` + `optimizeDeps.rolldownOptions.transform.define` | 同上，rolldown 的 define 不作用于预打包依赖 |
| `styles/base.css:20-21` | `-webkit-font-smoothing` / `-moz-osx-font-smoothing` | Safari / 旧 Firefox 仍识别 |
| `styles/base.css:65-78` | `::-webkit-scrollbar*` | 无标准等价物 |
| `styles/pdf-toolbar.css:24-25,182-183` | `backdrop-filter` + `-webkit-backdrop-filter` | Safari 必需前缀 |
| `styles/pdf-toolbar.css:410,419,433` | `-webkit-appearance` / `::-webkit-slider-thumb` / `::-moz-range-thumb` | 跨浏览器 range 样式必需 |
| `styles/notes.css:164-166` | `-webkit-line-clamp` / `-webkit-box` | 多行截断标准支持仍不完整 |
| `styles/library.css:340,841` + `styles/settings.css:526,530` | `::-webkit-details-marker` | Safari 下 `<summary>` 三角不响应 `list-style: none`，仍必需 |
| `api/http/detection_cache.ts:89-96`、`MoleculeDetailPanel.tsx:69-70`、`PdfViewer.tsx:319-320` | `smiles \|\| esmiles` | 后端 MolParser 双字段契约（Layer1 干净 SMILES vs Layer2 E-SMILES 带 `<sep>`），RDKit 渲染需优先 `smiles` |
| `components/ui/Toast.tsx:130-137` | `useToast` 无 Provider 回退全局 store | 防御性，非历史兼容，成本低 |
| `api/query/hooks/useReview.ts:73-77` | `toQueueItems` 处理 `undefined` | 防御性 |
| `api/http/project.ts:12` | `getCommonDirs()` 返回 `[]` | `FolderPicker.tsx:28` 有实时调用，是 web 模式的接口占位，不是兼容代码 |

---

## D 类：审计发现的其他问题（非删除项）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| D1 | `huggingface_hub` 在 `pyproject.toml` 中**完全未声明** | `infra/model_downloader.py:232` | 在 `[local-models]` 或新 extra 中补 `"huggingface-hub"`，否则 HF 下载通道对默认安装不可用 |
| D2 | 前端 `tsconfig.json` 注释称 `skipLibCheck` 为兼容 ketcher/framer-motion 的 `.d.ts` | `frontend/tsconfig.json:10` | 非代码兼容，保留；若升级依赖后可尝试关闭 |
| D3 | `navigator.platform` 使用已废弃 API | `frontend/src/api/http/settings.ts:149` | 不建议改 `userAgentData`（实验性，反而引入兼容问题），保持现状 |

---

## 阴性结论（已确认**不存在**的兼容代码，避免重复排查）

前端 `src/` 中确认无：`document.execCommand` 回退、`structuredClone`/`crypto.randomUUID`/`Array.prototype.at`/`Object.fromEntries`/`String.replaceAll` 手写替代、`??=`/`?.` 规避、`requestIdleCallback` polyfill、`IntersectionObserver`/`ResizeObserver` 缺失检测、`AbortController` 兜底、`Blob`/`createObjectURL` 分支、`EventSource` 兜底、`navigator.userAgent` 解析、`Buffer` polyfill、`@supports` 分支、legacy build target、browserslist 配置。

后端确认无：`sys.version_info` 分支、`from __future__ import annotations` 之外的版本判断、`ntpath`/`posixpath` 双写、`asyncio.set_event_loop_policy`、版本化 migration（`user_version`/`PRAGMA user_version`）。

---

## 汇总

- **B 类迁移后删除**：7 项
- **C 类保留**：约 40 项（跨平台 10、遗留数据 16、可选依赖 7、前端 7）
- **D 类其他问题**：3 项

## 验证注意事项

在本仓库跑全量 `pytest tests/` 会受到沙箱 safe-delete guard 干扰：测试用 `tmp_path` 清理时累计删除超过阈值会抛 `SystemExit: 1`，表现为大量 `ERROR at setup` / `previous item was not torn down properly` 的级联误报（本次曾出现 142 failed / 348 errors 的假象）。**应分批按子目录/单文件跑**，每批结果与全量跑差异极大。
