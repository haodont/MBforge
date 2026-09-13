# 为 PaddleOCR 增加本地入口

## 背景

当前 `mbforge.backends.ocr.paddleocr.PaddleOCRBackend` 是**纯云后端**：必须配置
`paddleocr_api_key`，走 aistudio-app 的 v2 异步 submit→poll job API。没有云端 key
时整条 OCR 链不可用（`extract_text_with_chain` 抛 `OCRUnavailableError`）。

用户希望增加一个**本地入口**：MBForge 直接调用本地部署的 PaddleOCR GenAI 服务
（官方的 /layout-parsing 同步接口，内部由 vLLM 跑视觉识别），从而在无云 key 时
也能 OCR。

## 协议（来自官方接口文档）

本地服务主操作是 `POST /layout-parsing`：

- 请求体是 JSON：`file`（图片/PDF 的 URL 或 Base64）、`fileType`（0=PDF, 1=图像）、
  `useDocOrientationClassify`、`useDocUnwarping`、`useLayoutDetection` 等可选参数。
- 成功响应：HTTP 200，`errorCode == 0`，`result.layoutParsingResults[i].markdown.text`
  为每页的 Markdown 文本；`prunedResult` 承载版面块（文本/表格/图像 bbox）。

该响应结构与云端后端已在解析的 `layoutParsingResults` **完全一致**，因此本地后端
可直接复用云端那套 `_spans_from_result` 版面→PDF-point span 解码（底稿比例约定一致）。

> 注意：沙箱环境连不到用户的 `127.0.0.1:8118`（连接被拒），协议按官方文档实现，
> 无法在本会话实测真实往返。请求体/响应解码集中在 `_build_payload_extract` /
> `_extract_text` / `_spans_from_local_result`，方便对着真实服务器微调。

## 接口变更清单

| # | 变更 | 文件 | 状态 |
|---|------|------|------|
| 1 | 新增 `LocalPaddleOCRBackend`（opt-in、失败静默降级、解析 `/layout-parsing`） | `backends/ocr/ocr_local.py` | ✅ 已实现+测试 |
| 2 | `DEFAULT_PRIORITY` 增补 `"paddleocr_local"`（cloud 优先、本地为 opt-in 候补） | `backends/ocr/chain.py` | ✅ 已实现+测试 |
| 3 | `OCRConfig` 新增 `paddleocr_local_host` / `paddleocr_local_model` / `paddleocr_local_api_key` | `utils/config.py` | ✅ 已实现 |
| 4 | 本地端点连通性探针（`POST /layout-parsing` 探活） | `backends/ocr/probe.py` | ✅ 已实现 |
| 5 | 新增路由 `POST /api/v1/ocr/test-paddleocr-local` | `routers/system/ocr.py` | ✅ 已实现 |
| 6 | 导出 `LocalPaddleOCRBackend` | `backends/ocr/__init__.py` | ✅ 已实现 |
| 7 | 文档（本文件 + 说明文档） | `docs/` | ✅ 本文件 |
| 8 | 云端 submit `optionalPayload` 改为官方三项后处理开关（可配置、默认全 `False`） | `backends/ocr/paddleocr.py`, `chain.py`, `utils/config.py` | ✅ 已实现+测试 |

## 云端后处理开关（变更 8）

按官方 PaddleOCR v2 示例 payload 透传三项：
- `useDocOrientationClassify`（方向分类）→ 配置键 `paddleocr_doc_orientation_classify`
- `useDocUnwarping`（畸变矫正）→ 配置键 `paddleocr_doc_unwarping`
- `useChartRecognition`（图表识别）→ 配置键 `paddleocr_chart_recognition`

默认全部 `False`：保持上传图像几何不变，bbox→PDF-point 映射（MoleCode 裁剪锚点）
依赖此假设。前三项一旦开启会改写图片几何，版面 span 坐标将不再可靠用于分子裁剪——
仅当扫描页严重旋转/畸变且可接受放弃该页 post-OCR 分子 ROI 对齐时启用。

## 行为变更说明

- **默认关闭**：`is_configured()` 仅当显式填 `paddleocr_local_host` 才为 True；未填时
  `build_backends` 因未配置而丢弃本地后端，云链路行为完全不变（无 cloud key 仍报错）。
- **选了 host 即自动进链**：`paddleocr_local` 进入 `DEFAULT_PRIORITY`，意味着用户只需
  配置 `paddleocr_local_host`，无需再手工改 `priority` 列表——cloud 在前，本地作为
  已配置时的候补。
- **失败不连累主链**：本地任何传输/解析错误都返回 `OCRResult(error=...)`，链会尝试
  下一后端，富化/OCR 路径绝不因此中断。
- **disabled 预处理器**：请求体固定 `useDocOrientationClassify=False`,
  `useDocUnwarping=False`，保证 bbox 停留在上传图像坐标空间，与云端渲染约定一致，
  MoleCode 裁剪映射不失真。

## 验证

- `py_compile` 全部通过。
- `ruff check`（ocr 包、路由、config）通过。
- 测试：`tests/unit/backends/test_ocr_local.py`（5 个）+ `test_ocr_chain.py` +
  `test_paddleocr.py` + `routers` = **172 passed**。
- 修改了既有 `test_ocr_chain.py::test_priority_config_reorders_and_completes_default_chain`
  的默认补全断言：云优先 + opt-in 本地名补全；`test_build_backends_has_no_cloud_backend_without_keys`
  仍保证未配置时不进链。

## 待办 / 风险

- **需用户实测校准**：真实 `paddleocr_local_host`（例 `http://127.0.0.1:8118/v1`）下
  跑一次探针，若响应结构与本文档假设不同，只需改 `ocr_local.py` 的解码函数即可。
- 前端尚未暴露本地 host 配置入口；当前用户可在 `~/MBForge/settings.json` 的
  `ocr` 段手写 `paddleocr_local_host`，或经现有设置保存接口落盘。