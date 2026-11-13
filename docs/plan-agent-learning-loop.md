# MBForge Agent 学习闭环系统计划

> 目标：把现有的 TODO / goal_review / self_improvement / memory / work_state / eval
> 从"相似的孤岛"整合成**一条闭合的学习链**，复用全部现有组件，**不新建子系统**。
> 本文梳理三件事：正常使用产生什么输入 → 输入如何被分析并路由到哪个末端 →
> 各末端如何反馈回实际框架。

## 0. 原则

1. **复用优先**：所有存储与引擎已存在；缺的只是*路由契约*与*闭环接线*，不是新模块。
2. **单一蒸馏引擎**：`review`（goal 完成后的只读 reviewer）是唯一的"经验→教训"蒸馏点；
   其它组件是*不同归属的存储*或*应用/校验环节*，不再各自蒸馏。
3. **归属清晰**：每个末端有明确的受众（agent 私有 / 项目共享）、寿命（会话 / 跨会话 / 永久）、
   动作性（注入上下文 / 触发改动 / 成为下一个 goal）。路由按这三维判定。
4. **信任靠证据**：程序性知识（skill）的置信由*跨轨迹压缩/转移收益*自动累积，不靠人工策展。
5. **隐私红线**：任何末端都不得存凭据、token、证据原文、瞬态工具输出（沿用 memory 现有规则）。

## 1. 现有组件盘点（角色定位）

| 组件 | 文件 | 角色 | 归属/寿命 |
|---|---|---|---|
| goal | `agent/src/goal.ts` | 会话活计划 + 捕获（begin/progress/complete/tool 条目） | 会话/branch |
| trajectory / evalFixtures | `agent/src/trajectory.ts`, `evalFixtures.ts` | 原始经验沉淀（每完成 goal 自动导出）+ 行为回归 | agent 私有/跨会话 |
| goal artifacts | `agent/src/goalArtifacts.ts` | 完整工具输出存档（有界） | agent 私有/跨会话 |
| review（goal_review） | `agent/src/review.ts`, `reviewQueue.ts` | **蒸馏引擎**：读轨迹产出 typed 教训 | 引擎（非存储） |
| memory | `agent/src/memory.ts` | 陈述性知识存储（hot/cold/persona/ephemeral） | agent 私有/跨会话 |
| work_state | `agent/src/workState.ts` | 活跃研究状态（hypothesis/follow_up/decision + links） | agent 私有/跨会话 |
| improvements（self_improvement） | `agent/src/improvements.ts` | 对代码库的改动提案，审批门控 | agent 私有/跟踪到完成 |
| TODO | `TODO/INDEX.md` | 项目共享 backlog + 机构记忆 + 度量协议 | 项目共享(git)/永久 |
| skills | `agent/skills/` | 可复用程序/方法（pi skill 机制） | 项目共享/永久 |
| eval | `agent/src/behaviorEval.ts`, `evalFixtures.ts` | 校验环节：行为回归门禁 | 校验（非存储） |

**现状缺口**：review 已自动把 `lessons` 写进 memory；但 `improvements` 只作为建议展示
（需手动 propose）、TODO/work_state 靠手写、**没有程序性类型**、**没有统一路由**、
**应用后无回灌校验**。本计划补的就是这些胶水。

## 2. 输入清单：正常使用产生什么

| # | 输入 | 产生时机 | 现有载体/形状 |
|---|---|---|---|
| I1 | 会话 transcript | 每轮 | branch：user/assistant 消息、tool call+result、error |
| I2 | goal 条目 | begin/progress/update/complete | `{action, goal_id, goal{objective,requirements[]}, requirements[{id,status,evidence,note}], unmet[]}` |
| I3 | 工具轨迹 | 每次工具调用 | goal `tool` 条目 `{tool,input,input_digest,status,artifact}`；完成时导出 fixture `{goalId,title,steps[],mode}` |
| I4 | 完整工具输出 | 活跃 goal 内 | `GOAL_ARTIFACTS/{session}/{goal}/*.txt`（有界） |
| I5 | review 产物 | goal 完成后异步 | `{summary, lessons[{type,content}], improvements[{title,area,problem,change,rationale,risk,files}], warnings[]}` |
| I6 | 会话内 memory 写入 | 模型主动 add | ephemeral 条目 `{type:user/feedback/project/reference, content}` |
| I7 | work_state 线程 | 模型主动 add/update | `{kind:hypothesis/follow_up/decision, title, detail, links[run/review/document]}` |
| I8 | improvements 记录 | propose/complete | `IMPROVEMENTS.json` `{…,status:approved/rejected/implemented}` |
| I9 | TODO 编辑 | 里程碑/人工 | `TODO/INDEX.md` 叙述 + 度量协议 + commit 引用 |
| I10 | 用户决策 | ask / dev-mode / improvement 审批 | 选择值、批准/拒绝 |
| I11 | 后端事件 | run 结束/worker 状态 | run completion、queue/worker health、error |
| I12 | eval 结果 | npm test sweep | fixture 违规列表（forbidden_tool/no_progress/step_budget） |

**核心输入是 I1–I4（原始经验）**；I5 是已蒸馏的中间产物；I6–I12 是各末端的当前状态与反馈信号。

## 3. 处理与路由：输入如何分析、到哪个末端

### 3.1 蒸馏（单一引擎）
- 触发：goal `complete` → 现有 reviewQueue 异步跑 reviewer（输入 = I1+I2+I3 的 transcript）。
- 增强：reviewer 的输出 schema 增加**程序性类型**与**路由标签**（见 3.2），其余沿用。
- 可选第二蒸馏点：周期性 maintenance 对*多条* fixture 做"切分→串联→剪枝→压缩验证"，
  产出候选 micro-skill（复用 I3，不新建存储）。

### 3.2 路由契约（review 输出 → 末端）
给每条教训加 `kind` + `audience`，router 按规则分发：

| kind | 判定标准 | 末端 | 现有写入路径 |
|---|---|---|---|
| `fact`/`preference`/`correction` | 陈述性、跨会话有用、agent 私有 | memory（type=user/feedback/project/reference） | 已有：review→memory |
| `procedure` | 可复用方法/工具序列骨架+槽，跨实例可转移 | skills / memory procedural 层 | **新增类型**，复用 skills 存储 |
| `code_change` | 具体代码缺陷/改动、agent 可实施 | improvements（审批门控） | 已有 propose；改为 review 自动 propose |
| `backlog` | 项目级、需人工/度量、跨 agent 共享 | TODO/INDEX.md | **新增**：里程碑追加（含度量护栏） |
| `research_state` | 活跃假设/待办/决策、需 resume | work_state | 已有 add；改为 review 自动路由 |
| `regression` | 行为退化信号 | eval baselines/fixtures | 已有 sweep；回灌为基线 |

路由判定三维：**受众**（私有→memory/work_state/improvements；共享→TODO/skills）、
**寿命**（当下注入→memory；resume→work_state；永久→TODO/skills）、
**动作性**（上下文→memory/skills；改动→improvements；下一个 goal→TODO）。

### 3.3 程序性知识的归纳（skill，复用而非新建）
- 切分：用 goal requirements 边界 / 工作对象切换把 I3 轨迹切成语义小点。
- 串联+剪枝：连成候选骨架，删重复（loop-guard 信号）、死路、实例专属步。
- 压缩验证：骨架去其他 fixture 匹配+替换，统计压缩收益；达阈值才沉淀为 `procedure`。
- 存储：结构化 micro-skill `{trigger, slots, steps[tool+purpose+precondition], pitfalls}`
  存进 skills（或 memory procedural 层）；置信阶梯 candidate→probation→active 靠使用成功累积。

## 4. 末端与反馈：如何回到实际框架

| 末端 | 反馈路径（回到实际行为） | 现有接线 |
|---|---|---|
| memory | `memorySystemPrompt()` 在 `before_agent_start` 每轮注入 hot/cold/persona | 已有 |
| skills/procedure | goal `begin`/任务开始时按 trigger 匹配注入适用 micro-skill | **新增匹配注入**（复用 pi skill 机制） |
| work_state | `workStateSystemPrompt()` 会话启动注入 active_goal+open threads；`check` 核对 links；resume 重建 | 已有 |
| improvements | propose→用户审批 dialog→approved→agent 用 edit/write 实施→complete 标记→eval 校验 | 已有审批/实施；**补 eval 回灌** |
| TODO | 会话启动读（AGENTS.md 约定）→成为下一个 goal 的 objective；人工+agent 共读 | 已有约定；**补 review 自动追加** |
| eval | `npm test` sweep 门禁挡行为回归；违规回灌 review 下一轮蒸馏 | 已有 sweep；**补回灌** |

**闭环**：应用（注入/实施/resume）之后产生的新会话，又成为 I1–I4 输入 → 再蒸馏 → 再路由。
eval 在"应用→再捕获"之间做校验，防止学到的东西引入退化。

## 5. 闭环总览

```
[捕获] goal+trajectory+artifacts (I1–I4)
   ↓
[蒸馏] review（单一引擎；+周期 maintenance 做切分/剪枝/压缩）
   ↓  typed lessons (fact/procedure/code_change/backlog/research_state/regression)
[路由] router 按 受众/寿命/动作性 分发
   ├─ fact/preference → memory
   ├─ procedure       → skills / memory-procedural（压缩验证+置信阶梯）
   ├─ code_change     → improvements（审批）
   ├─ backlog         → TODO（共享+度量护栏）
   ├─ research_state  → work_state
   └─ regression      → eval baselines
   ↓
[应用] memory注入 / skills匹配 / improvements实施 / TODO→next goal / work_state resume
   ↓
[校验] eval sweep（行为回归+压缩收益）→ 回灌蒸馏
   ↓
回到 [捕获]
```

## 6. 最小集成改动（胶水，分阶段；不新建子系统）

- **P1 路由契约**：review 输出 schema 加 `kind`/`audience`；新增一个小 router
  （放 review.ts 或 extension.ts），把 lessons 分发到 memory/skills/improvements/TODO/work_state。
  复用各存储现有写入函数。
- **P2 程序性类型**：review/maintenance 产出 `procedure`；micro-skill 结构化 schema 存 skills；
  切分/剪枝/压缩验证复用 fixtures+loop-guard+eval。
- **P3 闭环反馈**：skills 匹配注入（begin 时）；improvements 实施后跑 eval；eval 违规回灌 review；
  TODO 自动追加（里程碑，含度量护栏）。
- 每阶段独立可验证、可回滚；不推翻任何现有组件。

## 7. 风险与权衡

- **路由误分类**：教训进错末端（如把 code_change 当 fact 存进 memory）。缓解：kind 由 reviewer
  显式标注 + router 规则兜底 + 人工可改（memory update / improvements reject）。
- **冷启动**：早期轨迹少，procedure 沉淀慢。接受"宁缺毋滥"，压缩阈值客观把关。
- **共享污染**：TODO/skills 是 git 共享；自动追加需克制（里程碑才写、带度量护栏），避免噪声。
- **隐私**：所有末端沿用"不存凭据/证据原文/瞬态输出"；procedure 只存骨架+槽，不存实例值。
- **复杂度**：路由+闭环是真实但小的集成工作；相比新建 skill 子系统省一个数量级。

## 8. 验证计划（遵循 AGENTS.md 测试准入门）

- 路由契约：一个 usage 测试——review 输出含各 kind，断言分发到正确末端（复用现有 review/memory/improvements 测试夹具）。
- procedure 压缩：一个测试——骨架在另一 fixture 上匹配+压缩达阈值才沉淀。
- 闭环反馈：一个测试——improvements 实施后 eval 被触发；eval 违规进入下一轮 review 输入。
- 不新增 pass-through/常量测试；优先扩展现有最近测试文件。

## 9. 模块间传输契约（boundary contracts）

每条边界的载荷、触发、阻塞模式、生效方式、KV 影响。schema 均为现有或最小扩展。

| 边界 | 载荷 | 触发 | 模式 | 生效 | KV 影响 |
|---|---|---|---|---|---|
| goal→review | `GoalReviewJob{goalId,cwd,transcript}` | complete | 后台静默(enqueue) | 异步 | 无 |
| review→router | `ReviewReport{summary,lessons[kind],improvements,warnings}` | review 完成 | 后台静默 | 异步 | 无 |
| router→memory | `{type,content}` | 路由 fact | 后台写 | 下一轮注入 | 间接(变则 bust) |
| router→skills | micro-skill`{trigger,slots,steps,pitfalls,confidence}` | 路由 procedure | 后台写 | begin 匹配注入 | 间接 |
| router→improvements | `ImprovementInput` | 路由 code_change | **阻塞前台**(审批) | 实施+reload | 无 |
| router→TODO | markdown 追加+度量护栏 | 路由 backlog(里程碑) | 后台写 | 下一 session/goal | 无 |
| router→work_state | thread`{kind,title,detail,links}` | 路由 research_state | 后台写 | 下一轮注入 | 间接 |
| memory→prompt | `memorySystemPrompt()` string | 每轮 before_agent_start | 前台拉取 | 即时 | **直接** |
| work_state→prompt | `workStateSystemPrompt()` | 每轮 | 前台拉取 | 即时 | **直接** |
| goal→prompt | `goalContractPrompt(goal)` | 每轮 | 前台拉取 | 即时 | **直接** |
| skills→prompt | 匹配的 micro-skill | goal begin | 前台拉取 | 即时 | 间接 |
| eval→review | violations[] | npm test/下一轮 | 离线 | 下一蒸馏 | 无 |
| improvements→code | edit/write | approved 后 | 前台 | **reload** | 无 |

## 10. 触发/时机模型

- **后台静默**：review drain、memory 压缩、trajectory 导出、artifact/目录 prune、router 写存储。
  不占前台、不阻塞回答。review 特意在 `agent_settled`(空闲) drain，绝不打断进行中的回合。
- **阻塞前台**：仅*需要人决策*的点——improvements 审批、ask、request_dev_mode。其余一律不阻塞。
- **前台拉取**：每轮 before_agent_start 读 memory/work_state/goal/skills 注入；session start 读
  library_briefing/TODO。这是"知识即时生效"的通道。
- **空闲**：review drain、run completion 投递（idle 才送）、eval sweep（npm test，离线）。

原则：**蒸馏与写存储全后台；只有人决策阻塞；知识读取走每轮前台拉取**。

## 11. 生效模型（免重启）

- **知识=热生效**：memory/skills/work_state/goal 都在每轮 before_agent_start 现读现注入，
  学到后*下一轮*即生效，**无需重启**。现状已满足（extension.ts:525-541 每轮读）。
- **代码=冷生效**：improvements 实施改的是 TS/Python 源码，需 rebuild/reload——这是改代码的
  固有成本，不是学习系统缺陷。区分"知识热/代码冷"，不承诺代码热生效。
- **TODO=粗生效**：backlog 在下一 session/下一个 goal 被读取，粒度粗但合理（它是 backlog）。
- 保证：注入函数每轮读*最新*存储（不缓存陈旧内容），配合 §12 的 dirty-flag 只缓存"组装结果"。

## 12. KV 缓存影响与对策

**现状问题**：before_agent_start 每轮把 memory+work_state+goalContract 拼进 systemPrompt
（extension.ts:525-541）。任一存储变化 → systemPrompt 变 → provider prompt-cache 前缀失效 →
每轮重算前缀（延迟+token 成本）。这正是要避免的。

**对策（不依赖 pi 内部缓存细节，稳健优先）**：
1. **dirty-flag / memoize 组装**：缓存上次注入的 sections；仅当底层存储*真的变化*（memory add、
   work_state update、goal progress/complete）才重建 systemPrompt，否则返回*字节相同*的串 →
   前缀缓存命中。多数回合存储不变 → 命中。这是最关键、最稳健的一条。
2. **稳定在前、易变在后**：systemPrompt 顺序 = base+capabilities+cold/persona(极少变) →
   hot/work_state/goal(易变)。若 pi 设缓存断点，稳定前缀最大化复用，只有小尾部重算。
3. **易变注入保持小**：只注入紧凑契约/进度，不灌全文；per-turn 易变量（TPS/时间戳）绝不进 prompt。
4. **实证校验**：pi 的缓存断点位置需实测确认；上线后对比 cache-read token 占比验证命中。

目标：学习闭环的注入*不*成为每轮 KV bust 源；存储不变时零额外前缀成本。

## 13. 简化/裁剪（keep / merge / drop / defer）

越复杂越难维护。按"是否真被消费/是否重复"裁剪：

| 模块 | 决定 | 理由 |
|---|---|---|
| GOAL_ARTIFACTS | **DROP** | 只写不读（review 读 branch transcript，不读 artifact 文件）；死存储+磁盘+代码 |
| memory.persona 层 | **MERGE** 进 hot/cold | 与 hot 同步、职责重复；少一层少一处压缩逻辑 |
| work_state.active_goal 镜像 | **DROP** | goal 已是 source of truth；镜像冗余。保留 follow_up/decision/hypothesis |
| improvements vs TODO | **UNIFY 归属** | 两存储保留但路由*不相交*：code_change→improvements、backlog→TODO，杜绝双记 |
| procedural/skill 归纳 | **DEFER**(P3) | 复杂度热点（切分/剪枝/压缩）；先证明基础闭环，再上 |
| memory.ephemeral | KEEP | 压缩 staging，有"不注入瞬态"价值；体量小 |
| goal/review/memory(hot/cold)/work_state(followups)/improvements/TODO/eval/loop-guard/citations | KEEP | 各有不可替代职责 |

**修订阶段**：P0 裁剪（drop artifacts、merge persona、drop active_goal 镜像）→
P1 路由契约 → P2 闭环反馈+KV dirty-flag → P3(defer) procedural 归纳。
先做减法再做加法，系统更小更稳。