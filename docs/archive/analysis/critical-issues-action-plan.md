# MBForge 关键问题行动计划

> **ARCHIVED / HISTORICAL** — point-in-time snapshot. Numbers, paths, and stage/router counts may be **wrong today**. Do not treat as current API. Canonical: [../README.md](../README.md) · pipeline: [../architecture/pipeline-stages.md](../architecture/pipeline-stages.md).

> **发起日期**: 2026-07-09  
> **优先级**: P0 (Critical)  
> **预期完成**: 2026-07-16 (1 周内)

---

## 问题 1: 模型首次加载 30s 无预热

### 现状
- `src/mbforge/server.py:_prewarm()` 是空函数
- 用户首次调用 `/api/v1/moldet/*` 或 `/api/v1/molscribe/*` 需等待：
  - MolDet (YOLO26n): ~5-8s
  - MolScribe (Swin + Transformer): ~15-30s
- 前端无加载状态提示，用户以为请求卡死

### 影响
- **用户体验极差**：首次上传 PDF → 检测分子时，等待 30s+ 无反馈
- **竞品对比劣势**：云端 API 首次请求 < 3s

### 解决方案

#### 步骤 1: 后端实现预热 (1 小时)

```python
# src/mbforge/server.py:_prewarm()
def _prewarm() -> None:
    """后台预热核心模型 — 并发加载以节省时间."""
    import concurrent.futures
    from .backends.moldet_v2_ft import get_moldet_ft
    from .backends.molscribe import load as load_molscribe
    
    def _prewarm_moldet():
        try:
            logger.info("Prewarming MolDet...")
            detector = get_moldet_ft()
            # 空图片推理以触发 CUDA kernel 编译
            import numpy as np
            _ = detector.detect(np.zeros((960, 960, 3), dtype=np.uint8))
            logger.info("MolDet ready")
        except Exception as e:
            logger.warning("MolDet prewarm failed (non-fatal): %s", e)
    
    def _prewarm_molscribe():
        try:
            logger.info("Prewarming MolScribe...")
            load_molscribe()
            logger.info("MolScribe ready")
        except Exception as e:
            logger.warning("MolScribe prewarm failed (non-fatal): %s", e)
    
    # 并发预热（节省 ~10s）
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_prewarm_moldet),
            executor.submit(_prewarm_molscribe),
        ]
        concurrent.futures.wait(futures, timeout=60)
```

#### 步骤 2: 健康检查端点增强 (30 分钟)

```python
# src/mbforge/routers/health.py
from ..server_state import get_model_status

@router.get("/health")
async def health() -> dict:
    """健康检查 — 新增 models_ready 字段."""
    moldet_status = get_model_status("moldet")
    molscribe_status = get_model_status("molscribe")
    
    models_ready = (
        moldet_status == "ready" and
        molscribe_status == "ready"
    )
    
    return {
        "status": "ok",
        "models_ready": models_ready,  # ← 新增
        "models": {
            "moldet": moldet_status,
            "molscribe": molscribe_status,
        },
        "timestamp": time.time(),
    }
```

#### 步骤 3: 前端轮询等待 (30 分钟)

```typescript
// frontend/src/hooks/useModelsReady.ts
import { useEffect, useState } from 'react';
import { httpGet } from '@/api/http/_utils';

export function useModelsReady() {
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    const check = async () => {
      try {
        const resp = await httpGet<{models_ready: boolean}>('/api/v1/health');
        if (mounted && resp.models_ready) {
          setReady(true);
        } else if (mounted) {
          setTimeout(check, 2000);  // 每 2s 轮询一次
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Health check failed');
        }
      }
    };
    check();
    return () => { mounted = false; };
  }, []);

  return { ready, error };
}
```

```tsx
// frontend/src/components/project/DocumentUpload.tsx
import { useModelsReady } from '@/hooks/useModelsReady';

export default function DocumentUpload() {
  const { ready, error } = useModelsReady();

  if (error) {
    return <InlineAlert severity="error">模型加载失败: {error}</InlineAlert>;
  }

  if (!ready) {
    return (
      <Card>
        <Spinner />
        <BodyText>正在加载模型，请稍候...</BodyText>
        <Caption>MolDet 和 MolScribe 首次加载需要 20-30 秒</Caption>
      </Card>
    );
  }

  return (
    <Dropzone onDrop={handleUpload}>
      上传 PDF
    </Dropzone>
  );
}
```

### 验证步骤

1. **启动后端**：
   ```bash
   uv run uvicorn mbforge.app:app --host 127.0.0.1 --port 18792 --log-level debug
   ```
   观察日志：
   ```
   INFO:mbforge.server:Prewarming MolDet...
   INFO:mbforge.server:Prewarming MolScribe...
   INFO:mbforge.server:MolDet ready
   INFO:mbforge.server:MolScribe ready
   INFO:mbforge.server:Prewarm complete
   ```

2. **测试健康检查**：
   ```bash
   curl http://127.0.0.1:18792/api/v1/health
   # 应返回: {"status": "ok", "models_ready": true, ...}
   ```

3. **前端测试**：
   - 刷新页面，应看到"正在加载模型"转圈动画
   - 20-30s 后自动消失，显示"上传 PDF"按钮

### 预期结果
- ✅ 后端启动时自动预热模型（并发加载，总耗时 ~20s）
- ✅ 首次 API 请求响应时间 < 500ms（模型已加载）
- ✅ 前端显示加载状态，用户知道正在等什么

---

## 问题 2: 测试覆盖率极低

### 现状
- 133 个 Python 文件，仅 28 个测试文件
- **19 个路由零测试** → 任何 API 变更都可能破坏客户端
- **9 阶段 pipeline 零测试** → 重构风险极高

### 影响
- 回归 bug 频发（无测试安全网）
- 重构信心不足（不敢动代码）
- 新人 onboarding 困难（看不到预期行为）

### 解决方案（分阶段）

#### 阶段 1: 路由冒烟测试 (8 小时)

为每个路由写 **3 个最小测试**：
1. Happy path (200)
2. Not found (404)
3. Validation error (422)

```python
# tests/integration/test_routers_smoke.py
import pytest
from fastapi.testclient import TestClient
from mbforge.app import create_app

@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)

class TestLibraryRouter:
    def test_list_libraries_success(self, client):
        """GET /api/v1/library 返回 200."""
        resp = client.get("/api/v1/library")
        assert resp.status_code == 200
        data = resp.json()
        assert "libraries" in data

    def test_get_library_not_found(self, client):
        """GET /api/v1/library/{invalid} 返回 404."""
        resp = client.get("/api/v1/library/nonexistent-id")
        assert resp.status_code == 404

    def test_create_library_invalid_body(self, client):
        """POST /api/v1/library 空 body 返回 422."""
        resp = client.post("/api/v1/library", json={})
        assert resp.status_code == 422

# ... 重复 19 个路由
```

**清单**（按 `app.py` 顺序）：
- [ ] `library.router` (3 tests)
- [ ] `documents.router` (3 tests)
- [ ] `pipeline.router` (3 tests)
- [ ] `knowledge_base.router` (3 tests)
- [ ] `molecule.router` (3 tests)
- [ ] `agent.router` (3 tests)
- [ ] `chem.router` (3 tests)
- [ ] `coref.router` (3 tests)
- [ ] `detection_cache.router` (3 tests)
- [ ] `notes.router` (3 tests)
- [ ] `settings.router` (3 tests)
- [ ] `health.router` (3 tests)
- [ ] `resource.router` (3 tests)
- [ ] `events.router` (3 tests)
- [ ] `pdf.router` (3 tests)
- [ ] `sar.router` (3 tests)
- [ ] `ocr.router` (3 tests)
- [ ] `diagnostics.router` (3 tests)
- [ ] `moldet_api.router` (3 tests)

**时间分配**：
- 每个路由 3 tests × 15 分钟 = 45 分钟
- 19 个路由 × 45 分钟 = 14.25 小时
- 考虑 fixture 复用和熟练度提升，实际 ~8 小时

#### 阶段 2: Pipeline 单元测试 (16 小时)

为每个 stage 写 **输入→输出断言**：

```python
# tests/unit/pipeline/test_extract.py
from mbforge.pipeline.extract_text import extract_text_from_pdf

def test_extract_text_simple_pdf(tmp_path):
    """提取纯文本 PDF."""
    pdf_path = tmp_path / "test.pdf"
    # ... 创建简单 PDF
    result = extract_text_from_pdf(str(pdf_path))
    assert result["page_count"] > 0
    assert len(result["pages"]) == result["page_count"]
    assert result["pages"][0]["text"].strip() != ""

def test_extract_text_ocr_fallback(tmp_path):
    """图片 PDF 触发 OCR."""
    # ... 创建纯图片 PDF
    result = extract_text_from_pdf(str(pdf_path), ocr_config={...})
    assert result["ocr_used"] is True
```

**清单**：
- [ ] `extract_text` (4 tests)
- [ ] `density` (3 tests)
- [ ] `rough_md` (2 tests)
- [ ] `detect` (4 tests)
- [ ] `insert_molecode` (3 tests)
- [ ] `reorganize` (2 tests)
- [ ] `pageindex` (3 tests)
- [ ] `wiki` (2 tests)
- [ ] `persist_mols` (3 tests)

#### 阶段 3: Core 模块测试 (20 小时)

```python
# tests/unit/core/test_knowledge_base.py
def test_rrf_fusion_ranking():
    """测试 RRF 融合算法."""
    results_a = [("doc1", 0.9), ("doc2", 0.7)]
    results_b = [("doc2", 0.8), ("doc3", 0.6)]
    fused = rrf_fusion([results_a, results_b], k=60)
    # doc2 在两个列表中都出现，应该排第一
    assert fused[0][0] == "doc2"
```

### 验证步骤

```bash
# 运行所有测试
uv run pytest tests/ -v

# 查看覆盖率
uv run pytest tests/ --cov=src/mbforge --cov-report=html
open htmlcov/index.html  # macOS/Linux
start htmlcov/index.html  # Windows
```

**目标覆盖率**：
- 路由冒烟测试后：~30%
- Pipeline 测试后：~45%
- Core 测试后：~55%

---

## 问题 3: tsconfig.json 配置错误

### 现状
```json
{
  "compilerOptions": {
    "noEmit": true,
    "noCheck": true,  // ← 不是有效的 TS 选项
    "jsx": "react-jsx"
  }
}
```

### 影响
- ESLint 报警：`Unknown compiler option 'noCheck'`
- 配置意图不明确（想跳过什么检查？）

### 解决方案 (5 分钟)

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,        // ← 跳过 node_modules 类型检查
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "isolatedModules": true,
    "moduleDetection": "force",
    "noEmit": true,              // Vite 负责打包，TS 只做类型检查
    // 删除 "noCheck": true
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "types": ["vitest/globals", "vite/client"],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src"]
}
```

### 验证步骤

```bash
cd frontend
npx tsc --noEmit  # 应无报错
npm run build     # 应成功打包
```

---

## 执行时间表

| 日期 | 任务 | 负责人 | 状态 |
|------|------|--------|------|
| **7/9 (周二)** | 修复 tsconfig.json | 前端 | ⏳ 待开始 |
| **7/9-7/10** | 实现模型预热（后端 + 前端） | 后端 + 前端 | ⏳ 待开始 |
| **7/10** | 测试模型预热功能 | QA | ⏳ 待开始 |
| **7/11-7/12** | 路由冒烟测试（前 10 个） | 后端 | ⏳ 待开始 |
| **7/13-7/14** | 路由冒烟测试（后 9 个） | 后端 | ⏳ 待开始 |
| **7/15** | 运行覆盖率报告，验收 | Tech Lead | ⏳ 待开始 |
| **7/16** | 发布 v0.4.1（包含上述修复） | DevOps | ⏳ 待开始 |

---

## 风险与缓解

### 风险 1: 模型预热失败导致启动卡死
**缓解**：
- 预热函数设置 60s 超时
- 所有异常捕获后记录 warning，不阻塞启动
- 健康检查返回 `models_ready: false`，前端仍可使用（但首次请求慢）

### 风险 2: 测试编写时间超出预期
**缓解**：
- 优先完成路由冒烟测试（覆盖面最广）
- Pipeline 测试可推迟到第 2 周
- 使用 fixture 复用，减少重复代码

### 风险 3: 前端轮询导致后端负载增加
**缓解**：
- 轮询间隔 2s（不是 500ms）
- 模型就绪后停止轮询
- 健康检查端点无数据库查询，响应 < 10ms

---

## 验收标准

### ✅ 模型预热
- [ ] 后端启动时，日志显示 "Prewarming MolDet..." 和 "MolScribe ready"
- [ ] `GET /api/v1/health` 返回 `models_ready: true`（启动 30s 后）
- [ ] 首次调用 `/api/v1/moldet/extract-pdf-page` 响应时间 < 1s

### ✅ 测试覆盖率
- [ ] `pytest tests/integration/test_routers_smoke.py` 全部通过（57 tests）
- [ ] 覆盖率报告显示 `src/mbforge/routers/` ≥ 80%
- [ ] CI pipeline 新增测试步骤

### ✅ 配置修复
- [ ] `npx tsc --noEmit` 无报错
- [ ] `npm run build` 成功
- [ ] ESLint 不再报 `Unknown compiler option`

---

## 后续步骤（Week 2）

完成 P0 问题后，立即启动 P1 修复：
1. Ruff lint 254 问题（自动修复 + 人工审查）
2. SSE 重连逻辑
3. 密钥脱敏
4. 异步化 subprocess

**最终目标**：2026-08-09（1 个月内）达到：
- 测试覆盖率 ≥ 50%
- Ruff lint = 0
- 所有 P0/P1 问题已修复
- 文档与代码一致

---

**批准人**: ___________  
**批准日期**: ___________