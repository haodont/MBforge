# 分层治理规划 — 依赖修复、infra 执行器与 services 重组

> 2026-09-06 拍板；**同日双轨实施完成**（清单二"HTTP 用例面"由本会话执行，清单一
> "工作流主干"由并行会话执行，互审通过；完成裁定见第八章同步点表"修订 2026-09-06"行）。
> 本文档是 services 布局的**唯一依据**：
> `src-naming-migration.md` P3 中 `models/chem.py`、`routers/chem.py` 两个 SPLIT 行
> 的目标路径由本文第五章拍板并已回写。与 `patent-link-spec.md`（§5.1 直接发布、
> §9 STAGE_ORDER）和 `src-naming-migration.md` KEEP 行显式兼容，不推翻任何已拍板决策。
>
> 修订 2026-09-06（ExamplesStage 接入）：§4.2/§6.5 的"条件启用不 import 该 stage 模块"
> 调整为"注册但组合根过滤"——house 模式下 stage 内部延迟 import（import 代价低），
> 条件注册改为 `pipeline/composition.py` 的 `effective_stage_names()`（runner 与
> stage_checkpoint 共同消费，单一真源）；stage 自身无感知不变。首个使用者 ExamplesStage。

## 问题陈述

三层"编排"职责混在一起：pipeline 持有工作单元却被 services 反向引用，
services 里住着进程级 worker，routers 里渗入 RDKit 算法、文件 IO 与直连 DB。
同时存在六条实测依赖违规边（第一章），其中三条源自同一个根因——检测数据类型放错层。

## 第一章 现状依赖审计

### 1.1 分层与合法主干

```
UI (frontend)
 └─ routers/{system, documents, molecule, pipeline, markush}   # HTTP 校验 + 委托
     └─ services/                      # 请求级用例（读写编排）——唯一合法"宽依赖"层
         ├─ pipeline/                  # 工作流（工作单元 + run 编排）
         ├─ core/                      # 纯领域模型
         ├─ backends/                  # 模型封装
         ├─ storage/                   # 文件 + SQLite 原语
         ├─ infra/                     # 进程治理（执行器、锁、进程注册表）
         └─ utils/
```

合法主干链路（自上而下，无环）：`routers → services → {pipeline → backends/storage, storage → core}`。

### 1.2 各层实测对外依赖

| 层 | 依赖 | 评价 |
| --- | --- | --- |
| models/ | 无 | 纯 DTO，最干净 |
| core/ | utils（+1 处违规，见 ①②） | 基本合格，纯领域 |
| storage/ | core, utils, pipeline（违规②） | layout.py→LibraryLayout 是路径真相源 |
| backends/ | infra, utils, pipeline（违规②） | 经 ResourceManager 定位权重 |
| infra/ | utils, **services（违规⑥）** | 应为纯底层 |
| pipeline/ | core, storage, backends, **services（违规③）** | 基本合格 |
| services/ | core, storage, pipeline, backends, models, utils | 合格，唯一被设计为可"横跨"的一层 |
| routers/ | services, models, storage, pipeline, utils | 部分违规（④⑤） |

### 1.3 干净边界（保持不动）

- pipeline 不 import routers/models；core 不 import storage/backends；models 零依赖。
- services 的宽依赖符合用例编排定位（如 `services/library.py` 同时用
  `core.entities.document` + `storage.document_store` + `storage.layout`）。
- 命名迁移 P0–P2 已 verified；KEEP 行（含 `pipeline/runner.py`、
  `pipeline/stage_checkpoint.py`、`pipeline/stage_result.py`，迁移清单 216–218 行）不动。

### 1.4 六条违规边（全部经 grep 复核，2026-09-06）

| # | 违规边 | 证据 | 根因 |
| --- | --- | --- | --- |
| ① | utils → backends | `utils/runtime.py:94` `shutdown_backends()` 函数级 `from ..backends import moldet_v2_ft, molparser`（:96）；同文件 `get_default_device`(:18)/`is_gpu_available`(:61)/`require_gpu`(:79)/`gpu_warning`(:84) 直接探测 torch 设备 | 最底层 utils 反向引用模型层；设备探测与关停编排住错了层 |
| ② | core/storage/backends → pipeline（三处，同根同解） | `core/markush/provenance.py:22`（TYPE_CHECKING import `NormalizedMolecule`）、`storage/markush_candidates.py:38`（同）、`backends/molparser.py:24`（静态 import `ExtractionResult`）；另 `storage/sqlite/database.py:537` 函数级 import `pipeline.stage_checkpoint`（checkpoint 写入耦合进 schema）；docstring 级引用：`core/entities/molecule.py:19`、`backends/ocr/base.py:23`（TextSpan）、`backends/ocr/crop_labels.py:7` | 检测数据类（NormalizedMolecule/ExtractionResult）放错在 `pipeline/detection/types.py`，按分层应住 core；checkpoint 格式与写入逻辑耦合进 schema 文件 |
| ③ | pipeline → services | `pipeline/persist/activities.py:36`、`pipeline/stages/persist_stage.py:148` 均为 `from ...services.review_queue import insert_review_item` | 审核闭环横跨两条链路；patent-link 的 file-first 审核改造是终局 |
| ④ | routers 持有 DatabaseManager | `routers/markush/_shared.py:15,23-32` `resolve_db()` 直接 `DatabaseManager.get(...)`（缺省回退 `get(".")`，cwd 依赖）；`routers/pipeline/pipeline.py:33` import `storage.sqlite.database.INGEST_TERMINAL_STATUSES` 常量 | AGENTS.md 明令禁止的模式；markush 五个子路由经它裸操作 DB |
| ⑤ | routers 直连 storage.layout | 7 个 router 文件 import `storage.layout`（LibraryLayout/resolve_library_root 等路径工具） | 轻度越界；可收口到 `_path_utils.py` |
| ⑥ | infra → services | `infra/process/shutdown.py:33` 函数级 `from ...services import ingest_worker` | worker 住错层导致 infra 不再是纯底层 |

另记（本方案范围外）：routers 层存在大量内嵌业务逻辑（`molecule/chem.py` 439 行 RDKit、
`documents/library.py` 上传流与产物读取、`documents/notes.py` 整个持久层、
`pipeline/pipeline.py` worker_status/SSE 策略、`system/*` 模型生命周期与探测），
第五章/Phase 2 抽取；library_root 解析存在 5 种并存变体，见第六章约定。

## 第二章 目标分层与三角色模型

"编排"拆为三个角色，各归一层：

| 角色 | 层 | 职责 | 依赖规则 |
| --- | --- | --- | --- |
| **工作单元** | pipeline | stage 实现 + 注册声明（向注册表声明自己）；`run_pipeline` 编排留在 `pipeline/runner.py`（KEEP） | 不 import infra；执行器经注入 |
| **执行编排** | infra | 什么时候跑、怎么跑：队列认领、心跳、孤儿回收、并发、run 进程级外壳 | 持有 `StageProtocol` 注册表，只依赖 protocol + storage + utils；**不静态 import pipeline**；组合根（app 启动）完成注册 |
| **用例编排** | services | HTTP 请求要发生什么：校验后同步调 stage / 入队 / 纯 DB 用例 | 唯一合法宽依赖层；只被 routers（和 app lifespan）调用 |

依赖方向：`routers → services → {pipeline, infra, storage, core, backends} → utils`，
infra 与 pipeline 之间仅经 **`core/stage.py` 契约**单向关联（pipeline 实现 `@register`，
infra 消费注册表），不新建顶层 contracts 包。

### 2.1 service ↔ stage 升级判据

| 特征 | 走 service | 升级为 stage |
| --- | --- | --- |
| 作用域 | 请求级、交互式 | 文档级、批处理 |
| 耗时 | 毫秒~秒 | 秒~分钟，需要队列 |
| 产物 | DB 行 / 响应体 | artifact 文件 + DB |
| 失败恢复 | 直接报错给用户 | 可 checkpoint / 重跑 / 取消 |

升级路径：核心逻辑写成 stage 注册进注册表，原 service 变薄门面
（同步小数据量直接跑 stage，大数据量 enqueue）。现有候选：
`services/molecule_recorrection.py`（重建→纠正→写回）、
`services/markush_enumeration.py`（枚举→候选→入库）。
Patent/Link/Examples 新阶段按此判据归类（patent-link 已按 stage 设计，无需新 service）。

## 第三章 违规治理方案

| # | 解法 | 备注 |
| --- | --- | --- |
| ① | 拆解 `utils/runtime.py`：torch 设备探测（:18,61,79,84）上移为 **backends 能力查询**（`backends` 暴露 `device_capability()`，模型定位本来就在 backends）；`shutdown_backends`(:94) 上移 **infra 关停钩子**（infra 已拥有 shutdown 编排，注册式调用 backends 清理）；utils/runtime 只留纯运行时工具（`generate_uuid`/`run_sync`/`validate_path`） | Phase 0 验收：`grep -rn "backends" src/mbforge/utils/` 为空 |
| ② | 检测数据类型 `NormalizedMolecule`/`ExtractionResult` 等从 `pipeline/detection/types.py` 迁 **`core/detection/`**（pipeline.detection 反向 from-import 保持 API 兼容，命名迁移不留 shim 的政策不适用于模块内部 re-export，见风险注记）；`storage/sqlite/database.py:537` 的 stage_checkpoint 写入解耦为参数注入或回调 | 三处一次同根修；Phase 0 验收：`grep -rn "mbforge.pipeline" src/mbforge/{core,storage,backends}/` 为空 |
| ③ | `insert_review_item` 短期下沉 `storage/`（review 写入原语）；**终局**：patent-link file-first 审核改造（审核走 review/ 目录文件 + 既有 review_items 机制）落地后自然消除 | 与 patent-link §5/§7 对齐 |
| ④ | `routers/markush/_shared.py` 的 `resolve_db` + `_run_sync` 迁入 **`services/markush/_db.py`**（`DatabaseManager.get` 解析 + 经 infra 执行器线程化；`get(".")` 回退一并废除，library_root 必填）；`routers/pipeline/pipeline.py:33` 的 `INGEST_TERMINAL_STATUSES` 改由 services/ingest 门面供给 | Phase 2 验收机检：`grep -rn "storage.sqlite" src/mbforge/routers/` 为空 |
| ⑤ | 7 处 routers→storage.layout 收口：统一经 `routers/_path_utils.py` re-export，最终由 services 供给 library_root | Phase 3 |
| ⑥ | worker 迁 infra（第四章）后，`shutdown.py:33` 变成 infra 包内调用，环消除 | Phase 1 顺带完成 |

## 第四章 infra/ingest 设计

### 4.1 迁移内容

- `services/ingest_queue.py`（350 行，队列 DAO + 批量操作）→ `infra/ingest/queue.py`
- `services/ingest_worker.py`（622 行）→ `infra/ingest/worker.py`，函数级归属：
  - **整迁**（纯进程外壳）：`_worker_loop`/`_drain_loop`/`_claim_rows`/`_heartbeat_rows`/
    `_reclaim_*`/`_set_task_terminal`/`_library_lock`/`_max_concurrency`——认领、心跳、
    孤儿回收、并发上限，只碰队列表与进程注册表。
  - **拆两半**：`_run_pipeline_sync` 对 `run_pipeline` 的调用与端态映射
    （`TaskCancelledError`→cancelled、异常→failed）留 infra；run 本体不动。
  - **迁调用、不迁语义**：`_requeue_for_next_stage`（一条队列行 UPDATE）迁 infra，
    但 `next_stage` 取值来源不变——仍由 `run_pipeline` 返回的
    `StageResult.next_stage`（pipeline/runner）决定；注册表落地后 STAGE_ORDER
    派生供 runner 使用，infra 不做任何 stage 顺序判断。
  - **迁时机、不迁逻辑**：`_write_final_report` 触发时机（全部 stage 完成）归 infra，
    函数体一行不改——`stage_checkpoint.write_merged_report`（KEEP，迁移清单 217 行）
    与 `run_artifacts.promote_staging` 的报告合并/断点续跑/晋升本体留在 pipeline；
    "报告先写、再晋升 staging"的顺序与 patent-link §5.1/M2 run 收养语义咬合，保持原样。
- **pipeline 侧原有能力全部保留且被 infra 消费，不做替代**：`pipeline/runner.py`
  （单 stage 执行+事件+取消，KEEP 216 行）、`pipeline/stage_checkpoint.py`
  （断点续跑+合并报告，KEEP 217 行）、`pipeline/stage_result.py`
  （`StageResult.next_stage` 是 worker 决定 requeue 还是 finalize 的契约，KEEP 218 行）、
  `pipeline/cancellation.py`（取消在 run 内传播；队列行的 cancel 意图由 worker 转成终态）。
- **不迁**：stage 编排本身。`run_pipeline` 留在 `pipeline/runner.py`（KEEP 行，迁移清单 216 行），
  worker 经注册表调用。**不触碰** patent-link §5.1 已拍板的
  "PatentStage 成功末尾直接发布，不借道 .staging promote"。
- `routers` 不直接触 infra：`services/pipeline/ingest.py` 作为薄用例门面
  （enqueue/cancel/status 本质是用例：校验 + DB + worker 唤醒）。

### 4.2 Stage 注册表

- **Stage 基类、注册钩子、`next_after()` 查询全部定义在 `core/stage.py`**
  （core 是纯领域与共享词汇之家，契约只依赖 typing/纯 DTO——若钩子由 infra 提供，
  stage 就得 import infra，违反分层；放 core 免去新建顶层 contracts 包）。形态：

  ```python
  # core/stage.py —— 契约与注册表（纯内存，无 I/O）
  REGISTRY: dict[str, Stage] = {}
  ORDER: list[str] = []

  def register(stage_cls, *, after: str | None = None): ...  # 注册钩子，stage 自声明
  def next_after(name: str) -> Stage | None: ...             # 自动解析下一个 stage

  # pipeline/stages/extract.py —— stage 实现自包含、自注册（编排壳，重逻辑在 core）
  @register
  class ExtractStage:
      name = "extract"
      def execute(self, ctx) -> StageResult: ...
  ```

- **`StageResult`/`PipelineErrorCode` 随契约上移 core**（纯 DTO）。KEEP 行 218
  针对"纯外观改名"的命名批次，本迁移为分层修复；`pipeline/stage_result.py`
  可保留薄 re-export 至 P3 收尾。
- **stage 实现本体不进 core**：detection 调 backends、persist 写 storage，
  搬入 core 将制造 core→backends/storage 倒置边（违反 1.3 干净边界）。
  pipeline/ 最终定位收窄为"stage 编排壳 + runner + checkpoint"，
  重逻辑继续沿现有形态沉在 core（core/markush/enumeration、core/activity 等）。

- 组合根（app 启动装配）import 各 stage 模块触发注册；**条件启用**
  （patent-link 的 `examples_enabled` 等开关）在组合根注册时过滤，stage 本身无感知。
- **下一个 stage 由注册表解析**（`next_after`/ORDER），替代 runner 硬编码顺序；
  `StageResult.next_stage` 契约不变，infra 只执行队列行更新，不做顺序判断。
- **STAGE_ORDER 从注册表派生**，不在 `stage_checkpoint.py` 手工双维护
  （兼容 patent-link §9：现状五段 `extract, markdown, detection, activity, persist`，
  目标七段 +Index；加 Patent/Link/Examples 阶段 = 写 stage 类 + 一个 `@register` 装饰器）。
- checkpoint 文件名、`document_report.json` 等产物契约不变；阶段百分比统计不属于现行契约。
- **不解散 pipeline 文件夹（已拍板）**：独立 stage 化吸收的只有编排循环；
  ~50 个文件是 stage 实现本体（extract/detection/activity/persist）加共享运行时
  词汇表（PipelineContext、artifact 约定、checkpoint、取消语义），需要共同的家；
  并入 services 违反三角色、并入 core 破坏纯领域、按领域拆散则重对齐成本大于收益。
  演进路径：自注册使 stage 物理位置无关，未来按领域搬实现可增量进行。

### 4.3 配套归位

- 模型生命周期（已加载清单/卸载/冒烟测试，现 `routers/system/models.py` 内嵌后端单例
  私有状态操作）→ `infra/models.py`（2026-09-07 转正为 `infra/models/` 子包：
  状态存储 `state.py` + 生命周期 `lifecycle.py`，公共入口在 `infra/models/__init__.py`，
  旧 `model_state.py` 并入其中）；`/api/v1/models/mol/render` 的 PNG 渲染逻辑抽到
  services/chem（第五章），**HTTP 路径与前缀（app.py 注入）不变**，
  `tests/unit/routers/test_models_router.py` 为稳定契约。
- OCR 厂商连通性探测（`routers/system/ocr.py` 三份重复 probe）→ `backends/ocr/probe.py`
  （与三个云后端封装同层，共享 api_key fallback 与状态码策略）。
- 诊断导出（`routers/system/diagnostics.py:114-161`）→ 并入 `services/system/readiness.py`。

## 第五章 services 按领域子包目标地图

镜像 routers 子包结构（molecule/documents/pipeline/markush/system）。

| 子包 | 文件 | 来源 |
| --- | --- | --- |
| `services/molecule/` | `queries.py`、`recorrection.py`、`detection.py` | 现有三文件平移；queries 吸收 chem 搜索的"内存 vs DB 分支选择"决策 |
| `services/chem/` | `chem.py` | 从 `routers/molecule/chem.py` 抽出 RDKit 验证/描述符/指纹/Tanimoto/SVG 渲染；合并 `system/models.py` 的 PNG 渲染（去重） |
| `services/documents/` | `library.py`（LibraryStore 扩展：上传流式接收、markdown/page/report 产物读取，page 读统一走 `load_page_json`）、`notes.py`（新建，现整个持久层在 router）、`activity_queries.py`、`pdf_render.py` | 迁移 + 抽取 |
| `services/pipeline/` | `detection_cache.py`、`ingest.py`（对 infra.ingest 的薄门面） | 迁移 |
| `services/markush/` | `enumeration.py`、`review.py`、`sites.py`、`_db.py` | 迁移；DB 自解析（第三章④） |
| `services/system/` | `readiness.py`（+diagnostics 导出） | 迁移 + 合并 |
| `services/review_queue.py` | 审核中心统一队列（routers/review.py 的后端） | 实施补记（2026-09-06）：留在平铺根——单一文件不成子包，且其 markush 决策已委托 `services/markush/review.py`；若未来 review 域再增长再升格 `services/review/` |

配套下沉：`insert_review_item` → storage（第三章③）。
P3 回写：`models/chem.py` SPLIT 目标按 `/api/v1/chem` 端点群拆入 `services/chem/` + `models/chem/`；
`routers/chem.py` SPLIT 目标为薄路由壳（19 端点路径不变，逻辑在 `services/chem/`）。

## 第六章 统一约定

1. **library_root 唯一解析入口**：`storage.layout.resolve_library_root`。
   废除 4 个并存变体（`routers/documents/library.py:62` 自建优先链、
   `services/molecule_queries.resolve_library_db`、`routers/markush/_shared.get(".")` 回退、
   notes 直用 `resolve_root`）。
2. **routers 只做**：Pydantic 校验、HTTP 语义（状态码/流式响应）、调 service。
   禁止 `body: dict` 裸请求体（现存：`routers/markush/sites.py:21`、
   `routers/pipeline/pipeline.py:318-338`、`routers/molecule/molparser.py:53`）；禁止 import
   `DatabaseManager`/`storage.sqlite`（机检项）。
3. **services 签名规范**：收 `library_root: str` + 领域参数或 `models.*` 类型；
   返回 `models.*` 或 dict；DB 句柄由 service 内部 `DatabaseManager.get` 解析。
4. **分页 clamp 统一 helper**——双轨实施后复查：4 处已是 Pydantic `Query` 约束
   （`ge/le`），唯一手工 clamp（原 `pipeline.py:349`）随 A7 的 SSE/limit 重构消失。
   helper 不再需要，本条关闭。
5. **STAGE_ORDER 由注册表派生**（第四章 4.2），禁止手工双维护。
6. `run_db_sync` 类线程化统一经 infra 执行器（`infra/process/executors.py`），
   services 可直接 import infra（合法宽依赖的一部分）。

## 第七章 四阶段实施顺序与验收

**总验收标准**：HTTP 契约不变（路径/字段/错误码/产物文件名）；
测试基线保持 **0 failed 且 skip 集合不变（966 passed, 29 skipped, 0 failed，2026-09-06）**；
触碰 skip 集合中的测试需逐个说明理由；每个 Phase 独立可提交、可回滚。

| Phase | 内容 | 消除 | 验收机检 | 状态 |
| --- | --- | --- | --- | --- |
| **P0 依赖治理** | ①runtime 拆解、②检测类型迁 `core/detection/` + checkpoint 解耦 + `StageResult`/`PipelineErrorCode` 上移 core、③insert_review_item 下沉 storage | ①②③ | `grep -rn "mbforge.pipeline" src/mbforge/{core,storage,backends}/` 与 `grep -rn "backends" src/mbforge/utils/` 为空 | ✅ verified |
| **P1 infra 化 + stage 注册** | queue/worker 迁 `infra/ingest/`、`core/stage.py` 契约 + 注册表、STAGE_ORDER 派生、services/pipeline/ingest 门面 | ⑥ | infra 不静态 import `mbforge.pipeline`；`infra/ingest/worker.py` 允许**仅 3 处函数级调用点**（`run_pipeline`、`promote_staging`、`write_merged_report`，见下方修订 2026-09-06）；`infra/process/shutdown.py` 无 services import | ✅ verified |
| **P2 services 子包化 + 抽取** | 第五章子包平移、chem/notes/library/pdf_render/worker_status 抽取、④markush DB 收口 | ④ | `grep -rn "storage.sqlite\|DatabaseManager" src/mbforge/routers/` 为空；`tests/unit/services/` 建立并从 `tests/unit/core/` 平移服务测试 | ✅ verified（pipeline.py 的 LibraryLayout 直连由 A7 消除） |
| **P3 system 域 + 收尾** | model lifecycle → infra、ocr probes → backends、diagnostics 合并、⑤layout 收口、第六章约定清零（dict body、分页 helper）、AGENTS.md 与 `docs/wiki/architecture.md` 更新（含五段流水线描述对齐 patent-link 7+Index） | ⑤ | 约定 1–6 全部机检通过 | ✅ verified（含 M2 汇合项：render 去重、pipeline→infra 债务清零） |

顺序依赖：P0 的类型归位是 P1 注册表的前置（protocol 需要引用 StageResult/ctx 类型）；
P1 是 P2 中 ingest 门面的前置；P2 中 `documents/library.py` 的产物读取改造
需先对照归档交接 `assets/docs/archive/todo/2026-09-04-handover-preview-render-error.md`
（旧格式 `page_0001.txt` 数据兼容问题在该任务中未验证完成）。
Patent/Link 未跟踪文件（`pipeline/artifacts.py` 等）按 `src-naming-migration.md` 风险注记
先行收敛，再执行 P1 的注册表改造。

## 第八章 双轨并行执行清单

按文件归属域切分为两条可并行推进的清单（而非按 Phase 串行）。
每条清单内部保持顺序；跨清单仅三处弱冲突，已通过归属划分消除。

### 清单一「工作流主干」：pipeline / infra / core / storage / backends

| # | 任务 | 对应 | 完成判据 |
| --- | --- | --- | --- |
| A1 | 检测类型归位：`NormalizedMolecule`/`ExtractionResult` → `core/detection/`；`StageResult`/`PipelineErrorCode` 上移 core（pipeline 留薄 re-export） | ② | core/storage/backends 无 `mbforge.pipeline` import |
| A2 | checkpoint 写入与 `storage/sqlite/schema.py` 解耦（参数注入/回调） | ② | 同上，且断点续跑测试不变 |
| A3 | `insert_review_item` 下沉 `storage/review_audit.py`，pipeline 与 services 改调 | ③ | pipeline 无 services import |
| A4 | `utils/runtime.py` 拆解：torch 探测→backends 能力查询、`shutdown_backends`→infra 关停钩子 | ① | utils 无 backends import |
| A5 | `core/stage.py`：Stage 基类 + `@register` + `ORDER`/`REGISTRY` + `next_after()`；`STAGE_ORDER` 改派生；组合根注册 | 4.2 | 加临时测试 stage 仅需一个装饰器 |
| A6 | `services/ingest_queue.py`+`ingest_worker.py` → `infra/ingest/`；`shutdown.py` 改包内调用；建 `services/pipeline/`（`ingest.py` 门面 + `detection_cache.py` 迁入） | 4.1, ⑥ | infra 无 services import；worker/queue 测试全绿 |
| A7 | `routers/pipeline.py` 整体归本清单：worker_status/SSE 策略抽到 `services/pipeline/`、`INGEST_TERMINAL_STATUSES` 改由门面供给、logs 端点 dict body 清零 | ④⑥ | routers/pipeline 无 storage.sqlite import |
| A8 | 模型生命周期 → `infra/models.py`，`routers/system/models.py` 生命周期端点瘦身（**render 端点不动**，留给汇合点 M2） | 4.3 | `test_models_router.py` 全绿 |
| A9 | 本清单测试迁移：`test_queue_worker.py` 等移至 `tests/unit/infra/`；每步后全量验证 | — | 0 failed 且 skip 集合不变 |

### 清单二「HTTP 用例面」：routers / services 域重组

| # | 任务 | 对应 | 完成判据 |
| --- | --- | --- | --- |
| B1 | markush DB 收口：建 `services/markush/_db.py`（`resolve_db`+`_run_sync`，废除 `get(".")` 回退），`routers/markush/_shared.py` 只留路由 helper | ④ | routers/markush 无 DatabaseManager import |
| B2 | services 子包化：molecule/、documents/、markush/、system/（**pipeline/ 归清单一 A6，本清单不动**）；全库 import 更新 | 五章 | 旧平铺路径零残留 |
| B3 | chem 抽取：建 `services/chem/`（RDKit 验证/描述符/指纹/Tanimoto/SVG），`routers/molecule/chem.py` 缩为薄壳 | 五章 | 19 端点契约 `test_chem.py` 不变 |
| B4 | notes 服务化 + library 扩展（上传流、markdown/产物读取、page 统一走 `load_page_json`；先对照归档交接确认旧格式兼容） | 五章 | 无 router 内文件持久化 |
| B5 | pdf_render 服务化（PyMuPDF 渲染与 `services/molecule/detection` 渲染合并） | 五章 | 渲染端点响应不变 |
| B6 | OCR 探测 → `backends/ocr/probe.py`（三份合一）+ router 瘦身；diagnostics 导出并入 `services/system/readiness` | 4.3 | probe 逻辑仅存一处 |
| B7 | 收口杂项：⑤ layout 经 `_path_utils` 收口、剩余 dict body 清零、分页 clamp helper | ⑥ | 第六章约定 1–4 机检通过 |
| B8 | 建 `tests/unit/services/`，迁移 `tests/unit/core/` 中的服务测试（queue/worker 类除外，归 A9） | — | 移动不改断言 |
| B9 | AGENTS.md 与 `docs/wiki/architecture.md` 更新（分层图、三角色、约定；含五段流水线描述对齐 patent-link 7+Index） | — | 文档与代码互检一致 |

### 同步点与弱冲突（两清单唯一需要协调的地方）

| 项 | 规则 |
| --- | --- |
| 前置（共同） | Patent/Link 未跟踪文件（`pipeline/artifacts.py` 等）先行收敛，两清单都不得基于其上重构 |
| `app.py` | 归清单一（worker 启动/stage 注册 import）；清单二不改（router 挂载路径不变） |
| `services/pipeline/` 子包 | 整体归清单一（A6 创建）；清单二 B2 跳过 |
| `routers/system/models.py` | A8 只改生命周期端点；**render 端点的 chem 去重留给汇合点 M2** |
| 汇合点 M1 | ~~清单一 A5–A7 落地后，清单二 B2 需 rebase 一次~~ 实际执行顺序为清单二先完成，未触发；注记关闭 |
| 汇合点 M2 | 两清单完成后：PNG/SVG 渲染去重进 `services/chem/`、第六章约定全量机检、AGENTS.md 终稿 |
| 修订 2026-09-06（双轨完成后的审核裁定） | ① `infra/ingest/worker.py` 对 pipeline 的 3 个函数级调用点（`run_pipeline`/`promote_staging`/`write_merged_report`）**豁免**：checkpoint/晋升语义是 KEEP（在 pipeline），回调反转需把该语义拖进契约层，成本大于收益；机检相应放宽为"无静态 import + 仅此 3 处函数级"。② `pipeline/detection/extraction.py` 的 `ResourceManager.ensure("moldet")` 已上移 `backends/moldet_v2_ft.get_moldet_ft()`（幂等，单例创建前执行），pipeline→infra 边清零。③ render 去重完成：`/models/mol/render` 的 PNG 渲染落 `services/chem/chem.py::render_molecule_png_sync`，SVG 渲染本就在该模块，同层去重达成；`test_models_router.py` 以别名引用保持断言不变。④ `infra/process/discovery.py` 子进程补 `encoding="utf-8", errors="replace"`，3 个 Windows 环境性测试失败归零，基线恢复 **0 failed**。⑤ 分页 helper 关闭（见第六章 4）。 |
| 提交纪律 | 各自小 commit 直推 main；每步全量 `pytest` 保持 0 failed 且 skip 集合不变 |



## 附录 A 前端观察（范围外，留专项）

63 个组件文件直接 import `@/api/http`，仅 11 个走 `@/api/query`（React Query）——
http 与 query 两层的分工未被普遍遵守，建议后端治理完成后另立前端专项。

## 附录 B 关联文档

- `src-naming-migration.md`：KEEP/迁移清单与批次隔离规则；P3 两行目标路径已由本文拍板回写
- `patent-link-spec.md`：§5.1 直接发布、§9 STAGE_ORDER 五段→七段；file-first 审核是违规③终局
- `patent-examples-stage-plan.md`：ExamplesStage 按 4.2 注册表接入，两个阻塞项拍板后动工
- `INDEX.md` 测试基线备注（2026-09-06）：13 个存量失败已 skip，解除时按原失败清单对照
