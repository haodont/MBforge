# PdfCanvas 文档缓存 LRU 修复设计

## 范围

修复 `frontend/src/components/PdfCanvas.tsx` 中 PDF 文档缓存的 LRU 驱逐顺序。只处理 item 12；不改 `usePdfViewer` 的 viewer snapshot 缓存、不改 PDF 渲染流程、不做无关重构。

## 现状与问题

`docCache` 使用 `Map<string, Promise<PDFDocumentProxy>>` 保存最多三个 PDF 文档。Map 的迭代顺序代表插入顺序，因此缓存命中后必须把对应 URL 移到尾部，尾部表示最近使用项，首部表示最久未使用项。若仅在命中路径调整顺序，新插入项和命中项的顺序会与实际访问顺序不一致，导致错误驱逐。

## 设计

保留现有 Map 缓存结构与容量 `DOC_CACHE_MAX = 3`：

1. 查询 URL 对应的已有 Promise。
2. 无论命中还是新增，都先删除 URL，再写回 URL 和 Promise，使其成为 MRU 项。
3. 缓存超过容量时，删除 Map 首项作为 LRU 项。
4. 对被驱逐 Promise 注册异步 `destroy()`；销毁失败不得阻塞缓存操作。
5. 返回当前 URL 对应的 Promise。

缓存必须满足：

- 首次访问四个不同 URL 时，最早 URL 被驱逐。
- 重新访问旧 URL 后，该 URL 不被下一次驱逐。
- 被驱逐文档最终调用 `destroy()`。
- 同一 URL 命中时复用原 Promise，不重复调用 `pdfjsLib.getDocument()`。

## 测试

增加针对缓存行为的测试，覆盖：

- 容量边界和首次 LRU 驱逐。
- 命中后更新 MRU 顺序。
- 驱逐时调用文档 `destroy()`。
- 命中复用 Promise。

测试应通过公开或专门的纯缓存辅助接口验证行为，避免依赖完整 PDF canvas 渲染。不得改变组件对外 Props 或 PDF.js 调用契约。

## 错误处理

`getDocument()` 返回的 Promise 继续沿用现有错误传播。缓存驱逐后的 `destroy()` 继续异步执行；销毁异常被隔离，不能影响当前文档加载或后续缓存访问。

## 验证

至少运行：

```bash
npm --prefix frontend run test -- src/components/__tests__/PdfCanvas.test.ts
npm --prefix frontend run lint
npm --prefix frontend run build
```

若测试文件实际路径不同，使用对应路径运行，并记录结果。
