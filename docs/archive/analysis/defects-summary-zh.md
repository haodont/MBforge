# MBForge 项目缺陷总结（精简版）

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

> **分析日期**: 2026-07-09  
> **缺陷总数**: 33 项 (P0: 3 | P1: 7 | P2: 15 | P3: 8)

---

## 一、核心问题速览

### 🔴 P0 - 阻塞生产（3 项）

| # | 问题 | 影响 | 修复成本 |
|---|------|------|----------|
| 1 | **测试覆盖率极低**：19 个路由零测试，核心模块无单元测试 | 回归风险高，无法安全重构 | 24 人时 |
| 2 | **模型首次加载 30s 无预热**：`server.py:_prewarm()` 是空函数 | 用户首次上传 PDF 卡死 30s | 2 人时 |
| 3 | **tsconfig.json 配置错误**：`noCheck: true` 不是有效选项 | ESLint 报警，配置意图不明 | 5 分钟 |

### 🟡 P1 - 高优先级（7 项）

| # | 问题 | 位置 |
|---|------|------|
| 4 | **Ruff lint 254 个问题**：未使用导入、命名不规范、导入排序混乱 | 44 个文件 |
| 5 | **SSE 无重连逻辑**：网络抖动导致 Agent 对话截断 | `frontend/src/api/sse.ts` |
| 6 | **阻塞式 subprocess**：`nvidia-smi` 调用阻塞事件循环 | `core/resource_manager.py:245` |
| 7 | **密钥明文存储**：API keys 通过 GET `/api/v1/settings` 暴露 | `utils/config.py` |
| 8 | **错误处理不完整**：Pydantic 422 与 MBForgeError 422 混淆 | `frontend/src/api/http/_utils.ts` |
| 9 | **Agent 异常吞噬**：所有异常只记日志，不向用户反馈 | `agent/graph.py:88` |
| 10 | **依赖版本过宽**：`langchain>=0.3.0` 可能拉到 breaking 版本 | `pyproject.toml` |

### 🟢 P2 - 中优先级（15 项）

**文档-代码不一致（6 项）**：
- Pipeline 阶段数：README 说 6 阶段，实际 9 阶段
- Router 数量：CLAUDE.md 说 18 个，实际 19 个
- 数据库文件：文档只提 `knowledge_base.db`，实际还有 `molecules.db`
- OCR 配置：代码已实现 4 个后端（MinerU/PaddleOCR/GLMOCR/RapidOCR），文档未更新
- 存储路径：多处引用 `project_root`，已改为 `library_root`
- 技术栈：README 仍提及 Tauri v2（已删除）

**技术债务（5 项）**：
- 全局状态管理混乱（3 个独立 cache，无统一失效）
- 模块职责不清（`helpers.py` 既有工具函数又有异常定义）
- 类型提示不完整（部分函数缺少返回类型）
- 日志级别不一致（部分模块用 `print`，未走统一 logger）
- 测试隔离困难（`@lru_cache` 跨测试污染）

**性能（4 项）**：
- OpenKB PageIndex 可扩展性未验证（100+ 文档查询延迟未知）
- 前端打包体积未优化（KaTeX 字体 150KB，未分析 JS bundle）
- 语义缓存命中率未监控（`semantic_cache` 表有字段但无仪表盘）
- 数据库索引覆盖不全（`coref_predictions` 表缺少联合索引）

### ⚪ P3 - 低优先级（8 项）

- 代码风格不统一（部分文件中英文注释混杂）
- 常量重复定义（`STAGE_PCT` 在 runner.py，前端也硬编码一份）
- 死代码未清理（`gui/utils/__init__.py` 24 个未使用导入）
- 环境变量命名不一致（`MBFORGE_*` vs `HF_HOME`）
- Git commit message 不规范（部分提交未遵循 conventional commits）
- 错误信息不够用户友好（技术术语过多，缺少解决建议）
- 缺少 API 版本管理（`/api/v1/` 是唯一版本，无迁移计划）
- 缺少国际化（前端硬编码中文字符串）

---

## 二、按模块分组

### 后端 (Python)

**测试 & 质量**：
- ❌ 19 个路由无集成测试
- ❌ 9 阶段 pipeline 无单元测试
- ❌ Core 模块（database/knowledge_base/semantic_cache）无测试
- ❌ Agent 模块（graph/tools/sessions）无测试
- ⚠️ 254 个 Ruff lint 问题

**性能 & 架构**：
- ❌ 模型预热未实现（首次加载 30s）
- ⚠️ 阻塞式 subprocess 调用
- ⚠️ 全局状态管理混乱
- ⚠️ 异步 I/O 不完整

**安全**：
- ⚠️ API keys 明文存储 + GET 暴露
- ✅ SQL 注入防护到位（参数化查询）

### 前端 (TypeScript)

**配置 & 工具**：
- ❌ `tsconfig.json:noCheck` 配置错误
- ⚠️ ESLint 规则不够严格（允许 `any` 类型）

**功能 & 体验**：
- ⚠️ SSE 无重连逻辑
- ⚠️ 错误处理不完整（422 误判）
- ⚠️ 打包体积未优化

**测试**：
- 15 个 `.test.tsx` 文件，但未统计覆盖率
- 缺少 E2E 测试（Playwright / Cypress）

### 文档

**准确性**：
- 6 处与代码不一致（阶段数、路由数、文件名、技术栈）
- 部分 API 示例代码过时

**完整性**：
- 缺少部署文档（Docker / 生产环境配置）
- 缺少故障排查手册（常见错误码 + 解决方案）
- 缺少贡献者指南（如何提交 PR、代码审查标准）

---

##三、修复路线图

### 第 1 周：止血（P0）

**周一**：
```bash
# 1. 修复 tsconfig.json（5 分钟）
cd frontend
# 删除 "noCheck": true，确认 skipLibCheck: true

# 2. 实现模型预热（2 小时）
# 编辑 src/mbforge/server.py:_prewarm()
# 测试：uv run uvicorn mbforge.app:app --log-level debug
# 观察日志：Prewarming MolDet... Prewarming MolScribe... Prewarm complete
```

**周二-周五**：
```bash
# 3. 路由冒烟测试（8 小时）
# tests/integration/test_routers_smoke.py
# 为每个路由写 3 个测试：GET 200, POST 404, POST 422
pytest tests/integration/test_routers_smoke.py -v
```

### 第 2-4 周：系统修复（P1）

**Week 2**：
```bash
# 修复 Ruff lint（4 小时）
uv run ruff check --fix src/mbforge          # 自动修复 142 项
uv run ruff check src/mbforge > lint.log     # 人工审查 112 项

# SSE 重连（3 小时）
# 前端实现 RobustEventSource class

# 密钥脱敏（2 小时）
# 后端 GET /api/v1/settings 返回 _redact_secrets(cfg)
```

**Week 3**：
```bash
# Pipeline 单元测试（16 小时）
# tests/unit/pipeline/test_extract.py
# tests/unit/pipeline/test_density.py
# ... 每个 stage 一个测试文件
pytest tests/unit/pipeline/ --cov=src/mbforge/pipeline --cov-report=html
```

**Week 4**：
```bash
# 错误处理增强（3 小时）
# 前端区分 Pydantic 422 vs MBForgeError 422
# 后端 Agent 异常分类（recoverable vs fatal）

# 异步化 subprocess（1 小时）
# resource_manager.py 使用 run_in_executor

# 依赖版本收紧（1 小时）
# pyproject.toml 添加上界约束
```

### 第 2-3 月：长期改进（P2）

**Month 2**：
- 文档-代码一致性修复（2 天）
- 全局状态管理重构（5 天）
- 性能基准测试（3 天）

**Month 3**：
- OpenKB 可扩展性优化（1 周）
- 前端打包优化（2 天）
- E2E 测试搭建（1 周）

---

## 四、关键指标目标

| 指标 | 当前 | Q3 目标 | Q4 目标 |
|------|------|---------|---------|
| **测试覆盖率（Python）** | ~5% | 50% | 70% |
| **测试覆盖率（前端）** | 未知 | 40% | 60% |
| **Ruff lint 问题** | 254 | 0 | 0 |
| **首次模型加载时间** | 30s | <3s (预热) | <1s |
| **文档-代码不一致** | 6 处 | 0 | 0 |
| **安全漏洞（高危）** | 1 (密钥暴露) | 0 | 0 |

---

## 五、常见问题

### Q1: 为什么测试覆盖率这么低？

**A**: 项目在 2026-06 完成了 Rust→Python 大迁移（29 GB 代码删除），时间压力下优先"能跑起来"，测试被推迟。现在技术债累积到临界点，必须补齐。

### Q2: 模型预热为什么是空函数？

**A**: 历史遗留。原 Zvec 向量数据库有预热逻辑，迁移到 OpenKB 时被删除，但 MolDet/MolScribe 的预热未补上。开发者可能认为"lazy load"更节省内存，但忽略了首次用户体验。

### Q3: 为什么有这么多 lint 问题？

**A**: `parsers/molecule/molscribe_inference/` 目录来自第三方模型代码（直接复制粘贴），未经适配。需要：
1. 对第三方代码豁免 lint（pyproject.toml per-file-ignores）
2. 对自有代码严格执行

### Q4: 文档为什么跟代码不一致？

**A**: 文档更新滞后。Pipeline 从 6 阶段扩展到 9 阶段后，只更新了 `runner.py` 的 docstring，忘记同步 README/CLAUDE.md。建议：
- CI 中添加 doc linter（检查示例代码能否运行）
- 每次 PR 必须更新相关文档

### Q5: 如何避免技术债继续累积？

**A**: 
1. **Pre-commit hooks**：强制 ruff + eslint，不通过不让提交
2. **CI 门禁**：测试覆盖率 < 50% 不让合并
3. **Code review checklist**：新功能必须带测试，API 变更必须更新文档
4. **每月债务清理日**：全员暂停新功能，专注修 P2/P3 问题

---

## 六、结论

MBForge 项目的核心功能（PDF 解析 → 分子提取 → 知识库 → Agent 对话）**架构合理、实现完整**，但**工程实践短板明显**。

**如果不修复**：
- 3 个月后：用户因首次加载慢 + SSE 断线放弃使用
- 6 个月后：回归 bug 频发，每次发版都出事故
- 12 个月后：技术债累积到无法重构，只能推倒重来

**如果立即行动**：
- 1 周后：用户体验明显改善（模型预热）
- 1 月后：代码质量达到行业标准（50% 覆盖率）
- 3 月后：项目进入健康状态，可快速迭代新功能

**建议**：从 P0 问题开始，按优先级逐个击破。**测试和文档不是"额外工作"，而是代码的一部分**。

---

**下一步**：将本报告提交给团队 lead，讨论资源分配和时间表。