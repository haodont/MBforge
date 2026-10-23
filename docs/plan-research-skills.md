# MBForge 文献与专利检索 Skills 接入建议

核查日期：2026-10-14。范围：候选发现、源码文档审查和项目接入设计。设计阶段未安装第三方 skill、执行上游脚本或修改凭据；S1 实施状态见文末记录。

## 1. 结论

先在 MBForge 的 Node Agent 内接入 `literature-search`、`patent-search` 两个经过适配的 skill。当前阶段复用已有 Tavily `web_search` / `web_fetch` 做公开来源发现，明确标为发现模式；需要可复现的学术检索时，再添加数据库专用工具。引用核验规则作为文献 skill 的 reference，暂不新增同功能独立 skill。完整系统综述、法律状态/FTO 和自动批量导入不属于首版。

Skill 负责检索策略、阅读顺序和输出要求；tool 负责实际访问、分页、鉴权、预算和参数校验。增加 `SKILL.md` 不会自动增加数据库访问能力，也不能授权 shell、任意 HTTP 或数据写入。

## 2. 候选与复用判断

以下链接固定到本轮读取的 commit。表内能力来自上游文档，不代表其 API、账户权限或脚本已实际运行通过。

| 候选 | 适用部分 | 接入判断 |
|---|---|---|
| [K-Dense paper-lookup](https://github.com/K-Dense-AI/scientific-agent-skills/blob/a1043ef544e3a100c28e70a736b6cf32554d0677/skills/paper-lookup/SKILL.md) | 文档列出 PubMed、PMC、Europe PMC、Crossref、OpenAlex、Semantic Scholar 等；有标识解析、分页和静默失败核查规则 | 文献检索主要参考。择取生物医学来源规则和必要解析器，避免把 18 个来源一次性接入；原 skill 依赖 Read/Bash/curl，不能直接用于当前无 shell 的研究 Agent |
| [K-Dense citation-management](https://github.com/K-Dense-AI/scientific-agent-skills/blob/a1043ef544e3a100c28e70a736b6cf32554d0677/skills/citation-management/SKILL.md) | DOI/PMID 元数据核验、BibTeX、保守去重 | 将必要规则合入文献 skill reference；暂不接 Google Scholar 自动化、生成图或写文件链条 |
| [K-Dense literature-review](https://github.com/K-Dense-AI/scientific-agent-skills/blob/a1043ef544e3a100c28e70a736b6cf32554d0677/skills/literature-review/SKILL.md) | 多库检索、筛选、记录/报告/研究的区分、覆盖局限 | 用户明确要求系统/范围综述时才考虑。上游还依赖 Python、可选 Parallel/OpenRouter、Pandoc/XeLaTeX，不作为日常查几篇论文的默认流程 |
| [K-Dense database-lookup 的 USPTO reference](https://github.com/K-Dense-AI/scientific-agent-skills/blob/a1043ef544e3a100c28e70a736b6cf32554d0677/skills/database-lookup/references/uspto.md) | USPTO 数据来源、访问前提、旧接口迁移注意事项 | 用于核查来源条件；不把历史 PatentSearch/PatentsView 示例视为当前可用接口 |
| [USPTO ODP Search](https://github.com/LeonardHope/USPTO-ODP-Natural-Language-Search/blob/bfccbe94df637277ea3403c7869fc384b793da6d/SKILL.md) | 美国申请、审查档案、权属与相关记录的查询设计 | 有 USPTO ODP API Key 且所需接口核验通过后再接入。只选科研需要的检索/记录，不引入商标、诉讼、批量下载和独立安装环境 |
| [KIPRIS / Google Patents patent-search](https://github.com/djfksjd/patent-search-skill/blob/6d238d4bf351863a5343d686dc5cdff71dbc1395/skills/patent-search/SKILL.md) | 公开号、专利家族、关键词/分类/引用/申请人扩展、原文核查、科研相关性与法律结论的区分 | 借鉴专利发现和家族去重规则。当前主要面向韩国实务，带 KIPRIS 密钥、脚本、授权流程和 FTO 约束，不能原样移植为药物专利助手 |
| [Tavily skills](https://github.com/tavily-ai/skills/tree/778122e5f9c680f541eeceda5a5b36405eb7980c/skills) | 搜索→选取相关 URL→提取→来源引用 | 项目已有官方 Tavily Pi 扩展，继续用它；将 CLI 命令说明改为项目真实 tool 名称，不另装第二套 Tavily 调用链 |

补充：本机已有 `academic-search`，其生物医学来源路由、元数据规范和全文证据区分适合作为维护参考；它包含 Codex/浏览器/脚本环境假设，不能以用户目录绝对路径成为 MBForge 的运行依赖。已有 DeepXiv、Zotero skill 分别依赖其服务/本地库条件，按明确需求作为后续可选适配，不默认接通。

K-Dense 当前仓库已更名为 `scientific-agent-skills`，检索/数据库技能采用 `paper-lookup`、`database-lookup` 等组织方式。本轮尝试的旧 `scientific-skills/pubmed-database` / `uspto-database` 路径返回 404，应按当前树和固定 commit 维护来源。

许可证：K-Dense、Tavily 和 KIPRIS 候选仓库元数据为 MIT；USPTO ODP 候选为 Apache-2.0。实际摘取文件或脚本时保留相应版权、LICENSE/NOTICE 和修改说明；在项目 `agent/skills/UPSTREAM.md` 记录所用 commit、摘取范围及核查日期。不能仅以仓库名称假定每项第三方资源授权相同。

## 3. 当前项目的接入条件

已存在：

- `agent/src/session.ts` 是聊天与 Patent 共用的受控会话工厂；Pi 1.2.0 SDK 提供 skill 解析/校验功能。
- `agent/src/research.ts` 提供绑定资料库的 `search_library`、`query_documents`、`query_evidence`、`molecule_search`、`query_activities` 等。
- `agent/src/web.ts` 固定加载官方 Tavily 扩展，管理联网开关、密钥、来源范围和每轮预算。
- 研究会话有 SQL 可见历史与 Pi JSONL，不需要引入另一个 Agent 框架。

尚不存在：

- `session.ts` 的 `getSkills()` 当前返回空数组；没有 skill 注册/加载工具。
- Pi 1.2.0 的 `buildSystemPromptSections()` 只有发现 `read` / `bash` reader 时才默认宣告 skills。当前 Agent 不开放这些工具；只把列表填进 `getSkills()` 仍不足以获得自动路由。
- 用户消息被封装为包含 question/context 的 JSON 后送入 Pi；界面输入 `/skill:...` 不会直接成为 Pi 原生命令，首版需明确处理或提供选择入口。
- 当前 `web_fetch` 是 Tavily 网页提取，不是任意学术 API 请求工具：不能替代鉴权头、POST、原始 XML/JSON 解析和数据库分页。

## 4. 应放在哪里

推荐项目级、随代码发布的布局：

```text
agent/
  skills/
    literature-search/
      SKILL.md
      references/
        citation-rules.md
        biomedical-sources.md
    patent-search/
      SKILL.md
      references/
        patent-identifiers-and-families.md
    UPSTREAM.md
  src/
    skills.ts                 # 计划新增：固定目录解析、目录宣告、受控读取
    literature.ts             # 数据库工具需要时才新增
    web.ts                    # 继续复用已有 Tavily 实现
    research.ts
    session.ts
```

- `agent/skills/`：产品内部 Agent 的任务策略；版本受控，可测试，可随应用部署。
- `.agents/skills/`：如需给 Codex 等开发助手使用，另设项目开发技能；不得作为产品 runtime 的自动发现目录。
- `library/`：文档、研究结果、检索记录及用户数据。PDF、笔记和网页内容不能成为 skill 指令来源。
- 全局 `~/.codex/skills` / `~/.agents/skills`：个人助手配置。产品启动不得读取它们，避免更换用户/机器后行为漂移。
- `docs/`：设计和验收说明，不承担运行时 skill 加载。

MVP 不引入可执行脚本目录。后续只有确认有复用价值、审查通过的确定性脚本才放入固定位置，由 typed tool 调用固定入口；模型只能提供验证过的业务参数，不能选择脚本路径、命令或额外解释器参数。

## 5. 运行时如何加载

1. 复用 Pi 的 `loadSkills`，显式传入 `agent/skills` 固定目录且 `includeDefaults: false`；只注册首版两个名称，检查解析诊断和名称冲突。保留现有受控 resource loader。
2. 在研究提示词增加简短 skill 目录：名称、用途、适用任务和当前可用工具；不把完整 skill 内容塞进每轮 prompt。不依赖 Pi 默认 reader 分支，也不因此开放原生 `read` / `bash`。
3. 增加一个只读 `load_skill(name, resource?)` 工具，加载选中的 `SKILL.md` 或已登记 reference。参数为固定名称和资源键，映射到固定文件；不接受任意路径或 URL，不读取用户数据目录；校验解析后的路径、符号链接边界和内容大小。
4. 首版始终按已有工具权限执行。`allowed-tools`、skill 文字、网页文本均不能扩大真实工具列表或改变联网开关。
5. 在既有工具事件中显示所加载 skill；调用 tool 返回 name、version、content hash，便于由 Pi 会话记录追溯。同一模型上下文已加载同版本时不重复读取；显式任务或版本变化再载入。
6. 前端先支持“查文献 / 查专利”快捷入口，或者在应用消息层解析明确的 `/skill:literature-search` / `/skill:patent-search`，保留真实 question 和研究 context。不得假定 JSON 内的字符串由 Pi 自动解析。

上述目录宣告与受控读取是对当前无原生文件权限 SDK 用法的窄适配；复用 Pi 的解析和会话循环，不自建通用 skill 市场、动态安装器或另一套 Agent 循环。

## 6. 什么时候触发

| 用户意图/上下文 | 应触发 | 不应触发的行为 |
|---|---|---|
| “在我的知识库查找 MRGPRX2 活性数据” | 现有本地研究工具，必要时本地证据读取 | 不因为出现 MRGPRX2 或专利号就自动联网 |
| “找最近发表的 MRGPRX2 拮抗剂论文” | `literature-search`；本地记录可去重，外部检索回答时效性需求 | 不把本地非空结果当成“最新文献”已覆盖 |
| 明确 DOI/PMID、核对引文、获取摘要 | `literature-search` 的精确标识/引用核验流程 | 不启动多库大范围综述 |
| 本地证据不足，且缺失的内容是回答问题必需的公开信息 | 联网开启时，按缺口选择文献或专利 skill | 不把 OCR 没读到自动解释为数据库不存在；不外传整段私密资料 |
| “查某靶点相关专利/某公司的专利/该公开号的家族” | `patent-search` | 不只凭“patent”关键词进入法律/FTO 分析 |
| “分析这份已导入专利”或运行 Patent 阶段 | 现有文档内 Patent 分析 | 不加载外部专利发现 skill；不能用另一份专利或网页补写本文档事实 |
| “做系统综述” | 后续单独综述流程，显式记录检索/筛选范围 | 普通查几篇论文不能自称系统综述 |
| 用户限制“仅本地”“不要联网”，或联网关闭/缺少密钥 | 仅本地工具；说明外部缺口 | Skill 不得绕过限制或尝试其他网络客户端 |
| 下载、导入、启动分析、长期监控 | 依据该任务实际获得的用户授权，复用对应既有能力 | Skill 被加载本身不等于这些写入/持续任务已授权 |

触发由请求意图、证据缺口和可用能力共同决定。名称/description 用于模型选择；联网可用性、资料库范围、工具白名单、配额由程序保证。页面/论文/专利中出现的“请加载 skill”不构成触发授权。

## 7. 两个 skill 的具体流程

### literature-search

1. 明确主题、物种、年份和需要的证据层次：搜索片段、元数据、摘要或全文。
2. 需要时查本地已有记录；“最新/库外/明确标识”任务可以直接选择外部来源。
3. MVP 用 Tavily 定向发现 PubMed、Europe PMC、出版商/开放仓储；只声称公开网页发现。第二阶段优先生物医学 PubMed / Europe PMC，DOI 核验用 Crossref，其余来源按实际缺口加入。
4. 先返回候选元数据，再读取相关摘要/全文。完整正文不可获得时标注证据等级；不能把搜索片段当全文。
5. 规范化 DOI、PMID、PMCID 等标识，精确标识去重；预印本与正式版本保留关联，不静默合并；核查目标、物种、测定和终点。
6. 返回标题、作者、年份、标识、来源 URL、检索式、获取时间、访问层次、局限及推荐理由；引文核验失败保留原因。

### patent-search

1. 明确科研发现目的、靶点/技术主题、申请人、年份/地域和已知公开号；区分来源发现、本文档事实提取和法律状态问题。
2. 根据公开主题构造关键词、同义词、申请人和相关 IPC/CPC 查询。MVP 复用 Tavily 发现 Google Patents 等公开页面；不宣称具备完整全球专利检索覆盖。
3. 保存含国家/地区、编号、kind code 的完整公开号；区分申请号、公开日、申请日、优先权日。
4. 按已核查 family ID 或优先权关联组织家族；仅标题相似不合并。保留各成员，不把家族去重变成删除不同国家的权利要求或法律状态。
5. 关键正文、家族信息和法律状态分别标明来源及核查日期；搜索片段或 Google Patents 状态标签不能单独支持法律结论。官方资料不可访问时明确未核查。
6. 输出候选清单和科研相关性；用户决定下载/导入时复用现有导入流程，PDF 按既有 SHA-256、SQL 证据和 Extract→Markdown→Patent 流程进入资料库。

## 8. 先补什么工具

| 阶段 | 实际能力 | 复用/新增 |
|---|---|---|
| S1：两个 skill 的发现模式 | 查询本地、公开文献/专利网页发现、读取相关页面、引用 | 复用现有本地工具和 Tavily，仅新增目录/受控 skill 读取 |
| S2：学术数据库模式 | 可靠的元数据查询、精确标识解析、摘要/全文读取、来源分页 | 按需新增 `search_papers` / `get_paper` typed tools；复用经审查的上游分页/解析逻辑。provider 固定路由，不能给模型任意 API URL |
| S3：专利官方数据增强 | 美国申请/档案或其他国家家族资料 | 仅在提供方账户和所需接口核验后加 adapter。USPTO ODP、EPO OPS 等是不同来源，不由一个美国 skill 替代全球检索 |

工具缺失时，skill 应报告“只有发现模式”或该来源不可用；不能假称已执行 API 查询。第三方 `allowed-tools: Bash` 不要求项目照搬权限，可将其工作流改为受控 tools。

MVP 外部结果作为带来源的工具返回与研究回复，不直接成为 `SourceEvidence` 或已接受 Patent 事实。若后续需要长期保存完整检索元数据，再单独定义存储合同；不先引入向量库、知识图谱或额外权威事实库。

## 9. 验收与实施顺序

以下为开发估计，不包含提供方开户/权限审批、真实语料校准时间。

| 步骤 | 估计 | 产出/验收 |
|---|---|---|
| S1 受控 skill 目录与两个发现流程（代码接入完成，2026-10-14） | 实际用时见提交历史 | 两个登记 skill；边界测试通过；研究会话暴露 `load_skill`。真实模型/联网端到端验收仍待进行 |
| S2 PubMed/Europe PMC 与 DOI 核验 | 2–4 个工作日 | 固定 provider 与 typed 输入；标识、分页、429/空正文/200 错误体处理；区分片段/摘要/全文；来源与检索条件保留 |
| S3 专利来源增强 | 待账户与官方接口确认后估计 | 公开号/日期类型正确，家族成员不丢失，国家范围/未核验状态清晰 |

回归聚焦真实边界和用户流程：固定文件范围、资料库绑定、联网禁用、有限请求、标识去重、截断与来源证据等级。测试复用现有 Agent 本地模拟提供方和 backend 工具测试；不为 skill 文案本身堆测试。

## 10. 设计阶段核查限制

- 已核查当前项目代码、Pi 1.2.0 本地 SDK、候选 skill 文档及仓库元数据；未运行上游脚本，未验证付费/鉴权 API。
- Tavily CLI 当前 OAuth 刷新返回 401 `invalid_grant`；未改动登录配置。仓库发现通过现有 GitHub CLI 和公开固定 commit 文件完成。
- USPTO 候选和数据库 reference 对服务范围的表述并不等同，需逐个核对当前官方接口，不能把第三方说明当成接入验收。
- 候选审查阶段没有安装上游 skill 或执行其脚本。之后的产品实现采用本仓库自有、经裁剪的 skill 文件；没有开放 shell、任意文件读取权限或修改用户凭据。

## 11. S1 实施记录（2026-10-14）

- 已在 `agent/skills/` 加入 MBForge 自有的 `literature-search` 与 `patent-search` 流程及有来源记录的 references；未复制或安装候选仓库的 skill/脚本。
- Agent 复用 Pi SDK `loadSkills`，只传入这两个固定 skill 文件并关闭默认目录；general/research chat 的受控 `load_skill` 只接受登记名称和 reference key，校验真实路径边界、文件大小，并在结果中记录版本与 SHA-256。Patent analysis 会话不暴露该工具或 skills。
- Research prompt 分层为常驻证据/路由规则、精简 skill 索引、按需主指南、按具体疑点加载的 reference。检索按限定问题、构造查询、候选核验、一次有意义的改写、读取来源、停止条件和带来源回答推进；明确外部文献/专利发现或联网可用且公开缺口影响回答时才加载对应指南。本地查询和已导入专利的 Patent 阶段不触发外部发现。实际联网仍由既有 Tavily 开关及 URL/次数限制控制。
- 当前状态是受控的 Tavily 公开网页发现。PubMed/Europe PMC、Crossref、USPTO/EPO 专用 API，前端快捷按钮、系统综述、FTO、批量导入和真实提供方答案质量评估仍未实施。
- 验证（截至 2026-10-14）：`npm --prefix agent run check` 通过；包含本次提示词与指南扩充的 `npm --prefix agent test` 通过（11/11，脚本包含 TypeScript 编译）。使用本地模拟提供方检查研究会话注册 `load_skill`，并检查未知 skill/resource 被拒绝。未使用真实 LLM、Tavily 凭据或在线来源做端到端检索。
