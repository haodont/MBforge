# Plan: 拆分重构 Pipeline Runner（C901≈65）

> 目标：把 `src/mbforge/pipeline/runner.py` 中 `run_pipeline`（单函数约 650 行，C901≈65）
> 按机制拆成五个协作组件。**行为必须保持不变**；若产生接口变化，在此文档逐条记录并核对。

## 现状

`run_pipeline`（160–807 行）混在一起承担 7 类职责：

1. 运行态维护（局部变量 + `PipelineContext` 混用）
2. 事件发送（三个内嵌闭包 `_maybe_record`/`_emit`/`_emit_stage_result`）
3. 固定初始岔路 Extract ∥ Detection（约 250 行并行 + join + 分支对齐/回收）
4. 顺序阶段执行循环（resume/skip + 单阶段 checkpoint 写入）
5. 完成收尾（删临时 roughmd + complete 事件）
6. 失败/取消清理（`cleanup_staging`）
7. 生命周期副作用（`set_trace`/`reset_trace`/`release_task`）

## 目标结构

新增 `src/mbforge/pipeline/run/` 子包，`runner.py` 退化为薄门面。

```
pipeline/run/
  __init__.py
  models.py   RunContext 依赖的 DTO：PipelineEvent / PipelineResult / ProgressCallback
  events.py   PipelineEventSink        # 事件/日志/ingest_queue 统一出口
  state.py    RunContext               # 编排态（ctx/staging/run_id/timings/结果组装）
  initial_fork.py InitialForkRunner    # Extract∥Detection 并行 + join
  sequential.py SequentialStageRunner  # resume/skip + 单阶段执行循环
  finalize.py Finalizer                # 完成收尾 + 失败/取消清理
```

## 接口变化登记（逐条核对）

| # | 变化 | 位置 | 影响面 | 状态 |
|---|------|------|--------|------|
| 1 | `run_pipeline(...)` 签名不变 | runner.py | worker/router/queue 无改动 | ✅ 已核对（runner 测试 507 通过） |
| 2 | `PipelineResult` 字段不变 | run/models.py（runner re-export） | `test_runner.py` 等 | ✅ 已核对 |
| 3 | `PipelineEvent` / `ProgressCallback` 迁移到 run/models.py，runner 仍 re-export | run/models.py | 无外部直接引用 | ✅ 已核对 |
| 4 | `STAGES` / `_effective_stages` 保持在 runner.py 模块级（测试会 patch `_effective_stages`） | runner.py | `test_stages.py`/`test_runner.py` | ✅ 已核对 |
| 5 | `cancel_task / is_task_cancelled / release_task` 保持在 runner.py | runner.py | worker.py/ingest.py | ✅ 已核对 |
| 6 | 新增 `pipeline/run/` 子包（纯增量，无删除） | run/*.py | 无 | ✅ 已核对 |
| 7 | 一次调用只跑一个阶段 / 由 worker re-queue 的契约不变 | runner/sequential | worker | ✅ 已核对 |
| 8 | 事件→`ingest_queue` 状态映射（processing/done/failed/cancelled）与 `update_stage` 时机不变 | run/events.py | UI 队列状态 | ✅ 已核对 |
| 9 | resume 语义与清理规则（无中间成功才 `cleanup_staging`）不变 | runner/finalize | 断点续跑 | ✅ 已核对 |

## 实施步骤（每条实现后勾选）

### 实现（已完成）

- [x] 1. 建 `run/models.py`（PipelineEvent/PipelineResult/ProgressCallback）
- [x] 2. 建 `run/events.py`（PipelineEventSink，搬移三个闭包）
- [x] 3. 建 `run/state.py`（RunContext：编排态 + 生命周期副作用）
- [x] 4. 建 `run/initial_fork.py`（InitialForkRunner：并行岔路 + join + 分支回收）
- [x] 5. 建 `run/sequential.py`（SequentialStageRunner：resume/skip + 单阶段循环）
- [x] 6. 建 `run/finalize.py`（Finalizer：完成收尾 + 失败清理）
- [x] 7. 重写 `runner.py` 为薄门面（保留全部公共符号）

### 验证（已完成）

- [x] 8. 验证：`py_compile` 全部改动文件（通过）
- [x] 9. 验证：`ruff check` 改动文件（通过）
- [x] 10. 验证：最小相关测试集通过 —— `tests/unit/pipeline + infra + routers` **507 passed**；全量 `tests/unit` **821 passed**（仅 `test_recorrection_service.py` 6 个 error 属沙箱 `tmp_path` 清理的 `PermissionError`，与改组无关）
- [x] 11. 逐条复查「接口变化登记」表 —— 见下表核对状态

> 验证结论：并发重构收敛后，runner 拆分（含其消费方 worker/queue/router）无回归。验证过程中修正了两个搬运期引入的缺陷：
> `InitialForkRunner.__init__` 的 `self.run` 属性遮蔽方法 `run()`（已改名 `run_fork()`）、`load_stage_summary` 误从 `stage_artifacts` 导入（实际在 `stage_checkpoint`）。

## 风险与回滚

- fork/join 状态机是唯一高风险区：**先原样搬运、再提纯**，不边搬边改逻辑。
- 全程保持 `run_pipeline` 公共签名与 `PipelineResult` 字段，泄漏面为零，可整体回滚。
- 改动集中在 `pipeline/`，不影响 `worker.py`/`ingest.py`/`routers`/`stages/*.py`。