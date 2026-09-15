# 方案：统一 run_id 取代对外 task_id 概念

> 状态：**已执行并验证完成** · 前后端统一 run_id 契约，内部节点状态机按 (doc_id, run_id, stage) 保留

## 背景与目标

目前 ingest_queue 队列对外暴露 task_id（= ingest_queue.id，每个 stage 节点一个）。
一个文档的一次 run 有多个 stage 节点（extract/detection 并行 → join → markdown → patent），
所以前端和 API 会看到一堆 task_id。用户诉求：任务直接使用 run_id，更好把握整体进度。

## 关键事实（已查证）

1. ingest_queue.id 是每个 stage 节点的物理主键；cq_iq_doc_run_stage 唯一约束已允许 (doc_id, run_id, stage) 定位。
2. run_id：mint_run_id() = UTC YYYYMMDDHHMMSS（pipeline/run/ids.py），同一 run 的所有 stage 节点共享；ingest_runs(doc_id, run_id) 唯一。
3. enqueue 已返回 first_node_id（run 的首个节点 id，近似 run_id），并能 return run_id。
4. ingest_logs 用 task_id 列关联日志；SSE /events/{task_id} 按它读。
5. DAG 并行正确性：extract/detection 并行，各 stage 成败独立 => 内部队列状态机必须按 (doc_id, run_id, stage) 精确定位节点，不能合并成 run 级单一状态。

## 目标形态

- 对外 API：PipelineEnqueueResponse.task_id -> run_id；/events/{run_id}；批量操作改 run_ids
- SSE/日志：ingest_logs 加 run_id 列，SSE 按 run 订阅聚合进度
- 前端：IngestTask.id 语义换成 run_id；队列按 run 分组；SSE 按 run 订阅
- 内部状态机：(doc_id, run_id, stage) 精确定位节点状态（保留，保证并发正确）

## 执行步骤（分阶段，每步验证）

### 阶段 A - 存储层（最低层，可独立验证）
1. schema.py：ingest_logs 加 run_id TEXT 列。
2. database.record_ingest_event：同时写 run_id；ingest_queue 状态更新改按 (doc_id, run_id, stage)（而非 WHERE id）。
3. infra/ingest/queue.py：fetch_logs_since 改按 (doc_id, run_id) 过滤；新增按 run 定位辅助。

### 阶段 B - services / worker / runner（状态机 + 执行键）
4. services/pipeline/ingest.py：enqueue 返回 run_id；cancel_batch/retry_batch/delete_task 改按 run_id（作用于该 run 的所有节点）。
5. infra/ingest/worker.py：执行/取消注册表键从 task_id(=row[id]) 改为 (doc_id, run_id)；set_node_status/reset_node 改按 (doc_id, run_id, stage)。
6. pipeline/runner.py + run/context.py + run/events.py：task_id 参数替换为 run_id，取消注册表用 run 键。

### 阶段 C - 路由 / 模型（对外契约）
7. models/pipeline.py：PipelineEnqueueResponse.run_id；PipelineProcessResponse.run_id；PipelineTaskBatchRequest.run_ids。
8. routers/pipeline/pipeline.py：/events/{run_id}；/queue/{run_id}/...；batch 用 run_ids。

### 阶段 D - 前端
9. frontend/src/api/http/ingest_queue.ts：IngestTask 以 run_id 聚合；subscribeIngestEvents 改 run 订阅。
10. frontend/src/api/query/useIngestSSE.ts、useIngestQueue.ts、hooks：taskId -> runId。
11. frontend/src/components/project/ProcessingQueue.tsx + TaskRow.tsx：按 run 分组；操作按 run。
12. 前端 npm run lint + tsc 验证。

## 风险与保护

- 并发正确性：内部状态机保留 (doc_id, run_id, stage) 节点定位，不合并 run 级单一状态。
- 兼容：本地 SQLite 为 disposable 开发数据，ingest_logs 加列直接改 canonical schema，无需迁移脚本（符合 AGENTS.md）。
- 级联影响：cancel_task/release_task/is_task_active 注册表从节点 id 改 run 键，需同步 worker 与 runner，避免取消失效。

## 验证

- 后端：python -m compileall -q src/mbforge + uv run ruff check src/mbforge。
- 前端：npm --prefix frontend run lint + tsc --noEmit。
- 冒烟：enqueue 返回 run_id；SSE /events/{run_id} 能聚合多 stage 进度。
