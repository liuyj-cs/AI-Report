---
name: ai-daily-report
description: 生成 AI 行业日报或周报。覆盖模型、Coding Agent、通用 Agent 动态，并给出落地建议。产物为移动端优先的单文件 HTML，通过 Gmail SMTP（应用专用密码）发送到 .env 中的收件人。Trigger when 用户说"生成今天的 AI 日报"、"跑一下 /ai-daily"、"生成本周 AI 周报"、"跑一下 /ai-weekly"。
---

# AI 日报 / 周报 Skill

## 使用场景

- 在 Codex 中直接用自然语言触发，例如"生成今天的 AI 日报"、"生成本周 AI 周报"、"dry run 跑一下今天的日报"
- 用户输入 `/ai-daily` 或类似自然语言（"生成今天的日报"、"跑日报"）→ 走**日报工作流**
- 用户输入 `/ai-weekly` 或类似自然语言（"生成本周周报"、"跑周报"）→ 走**周报工作流**
- 用户说"dry run"或"演练一下" → 走**日报/周报工作流**但**跳过邮件发送**

## 运行前检查

每次运行开始时，依次确认：

0. **初始化 runner（默认入口）**
   - 日报：`python skills/ai-daily-report/scripts/report_runner.py init-daily --date {YYYY-MM-DD} --now {ISO8601} --env .env`
   - 周报：`python skills/ai-daily-report/scripts/report_runner.py init-weekly --end-date {YYYY-MM-DD} --now {ISO8601} --env .env`
   - 作用：提前校验 `.env`、创建 `cache/.../run.log`。日报入口只负责生成 `discovery_manifest.json` 与窗口；周报入口会写 `input_days.json`。若邮件环境变量缺失，此步即失败并停止。
0a. **昨日送达自检**：`init-daily` 输出若含 `DELIVERY_ALERT`（昨日有邮件失败或仅 dry-run），优先重跑
   `python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date {昨日} --env .env`
   续发（send_state 幂等：已送达的跳过；失败点之后从未尝试的深度/访谈也会一并补发）。
   仅确需单发一封时才用 send_mail.py（单发不写 send_state，之后重跑 finalize 会重复投递）。
   补发也失败则停止并提示用户检查网络/凭据。
0b. **昨日 QA 复盘**：读 `cache/{昨日}/qa_diff.json`（若存在）。昨日 `missed_discovery` 点名的源，今天首轮必须完成下穿（搜索层留痕）；连续出现的同名告警视为流程缺陷，当天必须消化，不允许再顺延。
1. **读取 sources/whitelist.yaml**：按类别枚举所有信源和搜索 query
1b. **读取 sources/profile.yaml**：读者画像（四个角色、在途决策、实践关注点）。它是编辑判断的输入：相关性、决策雷达分组、生态板块取舍都要回答"这条信息服务哪个角色/哪个在途决策"。
2. **读取 .env**：确保 `GMAIL_USER`、`GMAIL_APP_PASSWORD`、`REPORT_RECIPIENTS`（或回退 `RECIPIENT_EMAIL`）三项都已配置；任何一项缺失 → **立刻停止并提示用户**补齐。`report_runner.py` 与 `send_mail.py` 都会校验，runner 的职责是让错误尽早暴露。
3. **CN 厂商官方源验证**：whitelist 中标记 `verify_before_use: true` 的中国厂商源，在首次抓取前用一次浏览打开测试。若失败或返回无效页面，记录到 run.log 但仍尝试抓取相关信息（可通过 search query 兜底）。
4. **检查 cache 是否已有当日产出**：
   - 日报：`cache/{YYYY-MM-DD}/report.json` 存在 → 询问用户是否覆盖
   - 周报：`cache/weekly/{end_date}/report.json` 存在 → 询问用户是否覆盖
5. **确认 SMTP 凭据可用**：本步骤已合并到 step 2 的 .env 校验。Gmail 应用专用密码无浏览器认证流程。

## 日报工作流

**目标日期**：运行当日（如今日为 2026-04-11，则 date = 2026-04-11）
**采集窗口**：`昨日 07:00:00 ~ 当前运行时刻`（北京时间 Asia/Shanghai）。例如日报在 10:30 运行，则窗口为 `昨日 07:00 ~ 今日 10:30`，覆盖约 27.5 小时。`window.end` 写入实际运行时刻（ISO 8601）。

步骤：

1. **遍历每个信源的 fetch_chain（通用降级机制）**

   每个白名单项都带 `fetch_chain` 有序列表。对每个源按层尝试，**首次「成功且非伪成功」立即停止**：

   - **白名单的角色**
     - `whitelist.yaml` 是**首轮覆盖起点**，不是可用信息的天然上限
     - `authority_tier` / `authority_score` / `weight` 只用于**信源性质提示**与**首轮探索顺序**，不代表新闻重要性排序
     - 助手应先完整跑完白名单首轮，再决定是否扩展；不要一开始就脱离白名单四处漫游
     - 若首轮结果已经充分，直接进入后续归类；只有在首轮明显偏稀薄、或已抓到的高信号实体明显指向其他**相邻官方面**时，才进入下述扩展轮

   - **Layer 类型 → 使用方式**
     - `webfetch` → AI 代理用浏览/网页工具直连 URL
     - `github_releases` → AI 代理打开 `https://github.com/{repo}/releases` 或 GitHub API
     - `websearch_scoped` → AI 代理使用自身搜索能力执行 query，对每个 query 替换 `{date}` / `{yesterday}` / `{week_range}` 占位符
     - `websearch_broad` → 同 scoped，但检索范围更宽

   - **「成功」判定**（这一步至关重要，否则会掉进伪成功陷阱）
     - HTTP 200 + 页面体感为真实内容（含可读文本，非纯 CSS / 空骨架 / 登录墙）
     - **窗口内 0 条目（empty_in_window）按该层的 `surface_kind` 判定（whitelist 数据说了算，不靠现场体感）**：
       - **`surface_kind: feed`**——官方 news/blog 列表、changelog、release notes、GitHub releases、GitHub 组织 `?sort=updated`、HuggingFace 组织 `?sort=created`、结构化 API 等"每条都带日期的倒序列表"：empty 属于**合法成功**，**不**继续下层
       - **`surface_kind: static`**——产品首页、API/使用介绍页、聊天入口、JS 壳、看板/排行榜首屏：empty **不代表"无新闻"，只代表"这个面展示不了新闻"** → **必须继续下穿** 该源 fetch_chain 里后续的 feed 面与 websearch_scoped/broad；跑完搜索层仍空，才能判为该源空
       - 未标注的 `webfetch` 层按 `static` 处理；`github_releases` 层缺省 `feed`。标注判据与齐全性由 whitelist 头部注释与 `tests/test_whitelist_annotations.py` 机器门守恒——**不要在跑日报时临时改判某个面的类型**，该改标注就改 whitelist
     - **cn_labs 与 hard_data 是 finalize 阻塞项，且判空规则比通则更严**：这两类源除了「`static` 层空必须下穿搜索层」外，**`feed` 层空也不能立刻收工**——只要链里还有未触达的抓取面（webfetch / github_releases），就必须继续下穿；停在中途 `finalize-daily` 直接失败（不只是 qa_diff 告警）。原因是单个 feed 面只覆盖该源的一部分发布口径（API changelog ≠ 权重发布），开源权重的第一现场通常是 HF 上的新权重。**判据按 `attempts[]` 里真实出现过的最大 `layer_index` 算，不看自报的 `final_layer_index`**——留痕说了算，声明一个层号不算走过。对 `cn_labs`，走完链内全部抓取面仍空即可判空，不强制再跑 websearch；对 `hard_data`（每源只有一个 `static` 抓取面），走完它还不够，必须跑搜索层。阻塞范围仅这两类；其他类别的 `feed` 面空照旧即停，`surface_kind` 只作为你判断 empty 的输入，不阻断发送
     - 反例：Google AI Blog 经常返回纯 CSS 模板 → 视为 error，进入下一层
     - 反例：HTTP 200 但页面内容是「Please enable JavaScript」/「Cloudflare verification」→ 视为 error

   - **confidence 应用规则**（按 layer 类型决定，不按 layer 位置）
     - `webfetch` / `github_releases` 命中 → 条目 `confidence` 保持原始
     - `websearch_scoped` 命中 → 条目 `confidence` 降一档（high→medium，medium→low），写 `confidence_downgrade_reason`
     - `websearch_broad` 命中 → 条目 `confidence` 强制 `medium`，并打 `via_broad_search: true` 标记

   - **官方源优先补证**
     - `openai.com/news` 若遇到 403、JS shell、Cloudflare 或空壳页面，不得直接判空；继续查 OpenAI 官方 RSS、同域 news index 或 sitemap，再决定是否为空
     - `Google AI Blog` 若首层只命中 AI 总索引但无窗口内条目，且外部信号指向 Search / Chrome / AI Mode，一跳补证应继续查 `blog.google/products/search/` 与 `blog.google/products/chrome/`
     - `github_releases` 类源优先信任官方 release metadata；媒体稿只能补上下文，不能覆盖官方发布时间

   - **高信号官方 / 公司动作补漏**
     - 对 OpenAI、Anthropic、Google、Microsoft、Meta、DeepMind 等源，不只查模型发布，也要查 partnership / infrastructure / cloud / enterprise / pricing / compliance / benchmark 这类公司级信号。
     - 若官方入口 403 或空壳，但媒体或搜索结果指向明确官方页面、合作方公告或监管页面，应沿同一实体一跳补证，并把媒体面和补证面都写入 `source_details` 与 `candidate_ledger.source_attempt_refs`。
     - 这类候选进入正文时默认最多 `watch`，除非直接官方页面给出清楚日期与事实链。

   - **每层尝试都记录到 `fetch_status.source_details[name].attempts[]`**，包括失败的尝试。最终用的层写入 `final_layer_index` / `final_layer_type` / `via_broad_search` / `confidence_policy`。

   - **整链全部失败** → 进 `fetch_status.failed`，字段 `{name, reason, attempts: <chain 总尝试次数>}`
   - **整链首层成功** → 进 `fetch_status.succeeded`
   - **整链成功但窗口内 0 条目** → 同时进 `fetch_status.succeeded` 和 `fetch_status.empty`（仅当最终命中层 `surface_kind: feed`，或已跑完搜索层与后续 feed 面仍空时才允许；`static` 层不得停下直接判空。`cn_labs` 另需走完链内全部抓取面，见上）

   - **对 `general_agent_search_queries`** 仍然由 AI 代理单独执行搜索，命中的条目按 `via_broad_search: true` 处理。

   - **HN / GitHub Trending 扩大提取范围**
     - Hacker News：提取 **top 50**（而非 top 30）中的 AI/agent/LLM 相关故事
     - GitHub Trending：除 `since=daily` 外，额外抓取 `since=weekly` 作为兜底源，捕捉持续上升但单日增长不突出的项目
     - 高信号媒体发现面：除白名单媒体逐源首轮外，还应单独维护一组 `high_signal_media_queries`，用于把弱信号候选抬进 `candidate_ledger`，后续再由 AI 决定是进正文、进观察区/`unverified`，还是丢弃
     - **召回探针必须执行**：除逐源白名单、`general_agent_search_queries`、`high_signal_media_queries` 外，日报还必须执行 `recall_probe_queries`，并把结果写入 `fetch_status.source_details["High-Recall Product/Adoption Probes"].attempts[]`。
     - `recall_probe_queries` 不是固定正文规则，只是独立召回面。命中的候选仍由 AI 基于窗口、证据路径、产品相关性和团队可行动性决定进入正文、观察区、`unverified` 或拒绝。
     - 对 Cursor / Zed / IDE 平台化类信号，不要只看 changelog；官方 blog、release post、SDK 公告和 Agent Client Protocol 一类入口都属于 coding/general agent 候选面。
     - 对 DeepSeek / Qwen / Kimi / 智谱GLM / MiniMax / 豆包 / 混元 等中文头部模型，**任何单一面空都≠无发布**。这类源的 fetch_chain 里通常有多个抓取面（API changelog、HuggingFace 组织 `sort=created`、GitHub 组织 `sort=updated`、官方 blog），**每个面只覆盖一部分发布口径**——API changelog 记的是接口变更，开源权重的发布第一现场是 HF。所以 cn_labs 的判空规则比通则更严：**即使命中层是 `feed`，只要链里还有没走到的抓取面，就必须继续下穿**（finalize 会阻塞停在中途的链）；走完全部抓取面仍空，才可以判该源空，此时不强制再跑 websearch。若还需要更宽的确认，再走 ② websearch_scoped/broad；③ 主流媒体一跳。命中后进入 `candidate_ledger`，官方一手（HF/GitHub release）可保 high，纯媒体按 `media_plus_official_one_hop` / `media_only` 降级。
     - **AI HOT 是结构化 API 面**（`aihot.virxact.com/api/v1/items`，匿名只读、无需 Key）。**两层分工是刻意的**：Layer-0 `mode=selected` 是高门槛策展池（实测当日只放行约 8% 条目），标 `static`——它空只说明"策展没放行"，不等于中文圈无新闻，**必须下穿** Layer-1 `mode=all` 全量池（标 `feed`，空即权威）。返回 `{schemaVersion, query, items[], page}`；每条必有 `id / title / source.name / links.aihot / links.original / discoveredAt / selected`，而 `publishedAt / summary / category / score` 键恒在但**值可为 null，取用前必须判空**：`publishedAt` 为空时回退 `discoveredAt` 并按 `published_at_confidence: inferred` 处理。
       - ⚠️ **静默空集陷阱（必须防）**：非法参数会返回 **HTTP 400 但 body 是 `{"items": [], "page": null}`**——`feed` 层读到它就等于"今天中文圈无 AI 新闻"，是静默漏采。判别信号是 **`page` 为 null**：合法响应的 `page` 一定是对象。见到 `page: null` 一律按该层 error 处理并下穿，**不得**记成 empty。已实测会触发的非法值：`window` 只接受 `24h` / `7d`（`48h` 报 400）、`limit` 上限 100（`101` 报 400）、`mode` 只接受 `selected` / `all`。别自造参数。
       - `mode=all&limit=50` 实测 `page.hasMore=true`——这是**按需截断，不是全量**。50 条对召回对照够用；确需更多时用 `page.nextCursor` 原样回传翻页，不要把 `hasMore=true` 读成"就这些"。它是**中文圈召回对照面，不是证据源**——tier 2 聚合面，候选照常按 media 降档（`media_only` 不驱动 `action_items`），进正文前用条目自带的 `links.original` 做一跳官方补证。API 不可达时按该层 error 处理，继续下穿后续层
     - 对 Microsoft 365 Copilot、企业 agent 席位、ARR、weekly engagement 等商业采用率信号，优先写入 `market_signals.adoption_signals`，并通过正文 item `ref` 连接到 `general_agents` 或 `frontier_models`。引用必须指向能承载该数字的一手或电话会转录来源；普通新闻稿若不含数字，不可单独作为数字证据。
     - 媒体面不只看“新品发布”，也要覆盖工程化与组织信号，例如套餐/定价波动、agent 架构披露、企业落地案例；但这类条目若缺一跳官方补证，默认最多收口到 `watch` 或 `unverified`
     - 从这两个源提取的条目仍需通过窗口硬卡和跨日去重

1b. **证据驱动扩展轮（只在必要时触发）**

   - 当首轮覆盖偏稀薄，或某条高信号候选明显暗示还有更直接的官方/一级来源时，助手应做一轮**证据驱动扩展**
   - 扩展目的是形成**候选池**并补齐证据，不是用固定厂商表或固定分数把信息机械排队
   - 扩展优先级不是按厂商写死，而是沿着**同一实体**向外追一跳：
     - developer changelog / product changelog
     - release notes / docs / announcement page
     - partner official announcement
     - 官方 what’s new / blog / docs 页面
     - 对任何首轮只抓到弱信号或媒体转述、且明显存在更直接官方面的对象，应优先补一跳官方 changelog / 官方博客 / 官方 what’s new
   - 扩展的目标是**补齐证据**，不是扩大话题面；优先找更直接的官方面，而不是继续堆媒体二手稿
   - 一轮扩展通常控制在 1 跳；若一跳后仍无更强证据，就按现有证据收口，不要无边界追索

   - 所有阶段的状态（START / FETCH ... OK/FAIL / CLASSIFY / RENDER / ARCHIVE / EMAIL / END）写入 `cache/{date}/run.log`（纯文本，时间戳前缀）

1a. **搜索结果时间归因（必须在归类前完成）**

   搜索结果摘要经常将同一产品的**多个时间段事件**混在一起（如同时提到 2 月发布的旧模型和 4 月的新变更）。必须拆分后逐条验证：

   - **拆分**：当一次搜索结果摘要包含多个独立事件（不同发布日期、不同版本号、不同产品动作）时，将每个事件拆分为独立候选条目
   - **时间归因**：为每个候选条目独立确定 `published_at`：
     1. 摘要中有明确日期（如 "April 8, 2026"）→ 直接使用，`published_at_confidence: exact`
     2. 无明确日期但提到版本号 → 用版本号反查发布日期（额外一次搜索或检查同批抓取中的 release 信息），`published_at_confidence: approximate`
     3. 无法确定 → `published_at_confidence: inferred`，标记为待窗口硬卡判断
   - **关键反例**：搜索 "OpenAI Codex April 2026" 返回的摘要同时包含 GPT-5.3-Codex（2 月发布）和 GPT-5.4（4 月当前旗舰）→ 必须拆成两条，GPT-5.3-Codex 因 `published_at` 远早于窗口而被丢弃

2. **核心源阈值检查**
   - 核心源：`whitelist.yaml` 的 `core_sources`（共 8 个，含 2 家 CN 一级厂商 DeepSeek/Qwen）
   - 失败定义改为「**fetch_chain 全层都失败**」，被 Layer 1+ 兜底成功的源**不**算失败
   - 若 **≥4 个核心源整链失败** → 中止：打印清晰错误、写 run.log 末尾 `END daily status=aborted core_failures=N`、**不发邮件、不归档**

3. **助手过滤、去重与归类**

   - **编辑原则**
     - 先把白名单首轮与必要扩展轮都跑完，再做编辑判断；不要因为 seed page 静默就过早宣布 quiet day
     - 若某条信息只能靠媒体或搜索摘要成立，而沿实体追过一跳后仍拿不到更直接来源，应降低置信；若该信号仍有跟进价值，可转入观察区/`unverified`，而不是直接蒸发
     - 先形成**候选池**，再做编辑判断；`核心发布 / 重要观察 / 待证实` 是编辑结论，不是数值映射结果
     - 每条候选都要能回答四个问题：最强证据是什么、为什么是今天、为何进入该章节、为什么能或不能进入 `action_items`
     - 严禁使用固定分数阈值、固定厂商排名、固定 Top N 条数决定正文入选与排序
     - 严禁因为“某厂商默认更重要”而跳过窗口硬卡、版本校验或来源闭环
     - **重大事件判定（major_event）**：当一条 `selected_core` 候选满足「会改变读者的选型决策、或值得当天安排评估」（典型：新一代前沿模型发布、头部 coding agent 重大版本或定价变化、影响选型的重大产品发布）时，标记 `major_event: true`。这是编辑结论，不是分数阈值；每天 0-2 条，宁缺毋滥。
     - **major_event 默认必标清单**：以下三类事件命中即默认 `major_event: true`——① 新一代前沿主力模型正式发布/GA（Anthropic / OpenAI / Google / Meta / DeepSeek / Qwen 等，如 GPT-5.6、Gemini 3.5 Pro、Claude 新主力）；② 头部 coding agent 重大版本或定价模式变化（Claude Code / Codex / Cursor / Copilot 量级）；③ 影响选型的重大 agent 平台 / 协议发布。命中清单但决定不标的候选，`candidate_ledger` 的 `decision_reason` 必须写明不算 major_event 的理由。

   **3-0. 窗口硬卡（最高优先级，无例外）**
   - 每条候选条目必须已填写 `published_at`（在 Step 1a 完成）
   - **硬判规则**：
     - `published_at` 早于 `window.start` → **直接丢弃，无例外，不论内容多重要**
     - `published_at` 晚于 `window.end` → 丢弃
     - `published_at_confidence: inferred` 且落在窗口内 → 保留但 `confidence` 不得高于 `medium`
   - 记录：被窗口硬卡丢弃的条目写入 `run.log`，格式 `WINDOW_REJECT {headline} published_at={date} reason=before_window|after_window`
   - **关键反例**：GitHub Copilot 4 月 10 日的 changelog 条目不得出现在 4 月 12 日日报中（窗口起点为 4 月 11 日 07:00）

   **3-1. 跨日去重**
   - 读取 `cache/{yesterday}/report.json`（若存在）
   - 将昨日所有条目的 `dedup_key` 和 `headline` 加入去重池
   - 当日候选条目的 `dedup_key` 完全匹配、或标题 n-gram Jaccard > 0.7 命中昨日条目 → **丢弃**
   - **例外 1**：当日条目相比昨日有实质性状态变更（如 `release_stage` 从 `announced` 变为 `ga`，或新增重大细节）→ 保留，但 headline 必须体现增量（如"X 正式发布"而非重复昨日标题）
   - **例外 2（事件追踪）**：当日条目带 `tracking_ref` 且对应 `cache/tracking/{slug}.json` 处于活跃期 → 不因与昨日/前日同一实体而丢弃，但 headline 与 summary 必须只写增量信息，不复述发布日内容
   - `cache/{yesterday}/report.json` 不存在 → 跳过此步

   **3-2. 基础过滤**
   - 丢弃明显非 AI、广告、软文

   - **跨源去重**（在归类前必须做）
     - URL 归一化：去掉 `utm_*` 等追踪参数、去掉末尾斜杠，作为 `dedup_key` 候选
     - 标题相似度：n-gram Jaccard > 0.7 的两条视为同一事件
     - 合并时保留 `authority_score` 最高（authority_tier 数字最小）的那条作主条目；次条目并入 `evidence` 备注

   - **交叉验证规则**
     - `authority_tier ≤ 2` 的条目可单源进入正文（前三节）
     - `authority_tier = 3` 的条目必须有另一条 tier ≤ 2 的交叉确认，否则进 `unverified`
     - 来自 `via_broad_search: true` 的条目 confidence 已经被强制为 medium，仍可进正文，但要求标题至少能在两个独立来源中出现

   - 归类到 5 个章节：
     - **frontier_models**：模型能力发布、基准测试、开源、API 定价调整
     - **coding_agents**：明确面向写代码的产品（如 `Codex / Claude Code / Gemini CLI / Jules / Cursor / Copilot / Cline / Aider / Windsurf` 等）；是否进入正文和排序由事件本身决定，不按产品名单预设主次
     - **general_agents**：通用 agent、browser agent、computer use、工作流 agent（不限厂商）。凡属此类且进入正文的条目都归入这里，不因厂商体量或对象热度预设更高优先级
     - **unverified**：观察区 / 待核实区。用于收纳“日期明确、事实链部分成立、但一级证据未闭环”或“官方痕迹存在但信息过薄”的候选，不进入正文判断与行动建议
   - 媒体内容提升规则：高质量媒体（trust: high）的确定消息 → 前三节作为补充；不确定 → 第五节
   - **安静日媒体分析提升**：当 frontier_models + coding_agents + general_agents 总条目 ≤ 4 时，允许将 `authority_tier ≤ 2` 的媒体**分析/观点文章**（非产品发布）提升进正文章节，标注 `release_stage: announced`，headline 前缀加"[分析]"以区分
   - **媒体驱动主题分层**
     - 已被官方源证实的功能更新 → 可进前三节
     - 只有媒体分析、但事实链足够清楚 → 最多作为 `watch` 级观察
     - 高关注对象名单只用于提醒 AI 做补漏和补证，不构成固定优先级顺序，也不能替代编辑判断。是否排前、是否进入正文、谁更值得写，必须由 AI 基于事件强度、影响面、版本阶段、来源质量以及对团队后续动作的意义综合判断；不要因为某个对象本身更热门，就机械地压过同窗口内其他更重要或更实质的更新
     - 对这类需要补证的高关注对象，若官方页弱、旧、或不提供干净时间戳，但媒体稿/搜索结果已给出**清楚事实链 + 明确日期 + 至少一跳可回到官方面或官方产品页**，允许进入前三节作为 `watch`；必须显式保留 `confidence=medium`、`via_broad_search=true` 或相应降档痕迹，且 `action_items` 只允许导出 `monitor / experiment` 这类轻量建议，不要直接推高强度下注
     - 观察区应比正文更宽：若候选日期明确、事实链部分成立、对后续跟进有价值，但完成必要补证后仍缺一级证据或官方信息过薄，可进入 `unverified`
     - `unverified` 不等于“纯传闻堆放区”：优先保留 0-2 条最值得继续跟进的候选，并写清楚缺的证据是什么；明显窗口外、明显重复、或价值很低的弱信号仍应丢弃
   - 字段约束：`headline ≤ 30 字`、`summary ≤ 40 字`、`impact ≤ 30 字`

   - **每条条目都必须填以下元数据字段**（schema 强制 required）
     - `release_stage`: 枚举 `announced` / `preview` / `beta` / `ga` / `rumor`
     - `published_at_confidence`: 枚举 `exact` / `approximate` / `inferred`
     - `authority_score`: 1-5 整数（直接由 source 的 `authority_tier` 反向映射：tier 1→5，tier 2→3-4，tier 3→2）
     - `editorial_tier`: `core` / `watch`，只表达编辑分层，不是自动评分
     - 可选：`evidence_quote`（原文一句直接引用，≤120 字），`dedup_key`，`via_broad_search`

   - **候选编辑判定**
     - 每条候选最终必须落到：`selected_core`、`selected_watch`、`selected_unverified`、`rejected_window`、`rejected_duplicate`、`rejected_weak_evidence`、`rejected_not_ai`
     - 助手必须为每条候选写一句 `decision_reason`，明确说明是保留、降级还是丢弃

3a. **当前状态校验（针对 frontier_models 和 coding_agents）**

   对于涉及具体**模型版本号**或**产品版本号**的条目，在写入 JSON 前必须验证该版本是否为当前最新：

   - **同批信息交叉检查**：检查本次抓取中是否已有该产品的更新版本信息。例如搜索结果同时提到 GPT-5.3-Codex 和 GPT-5.4，则 GPT-5.3-Codex 不应作为"新发布"报道
   - **快速验证**：若不确定，用一次搜索 `"{product} latest version April 2026"` 确认
   - **处理规则**：
     - 非最新版本 + `published_at` 在窗口外 → 丢弃
     - 非最新版本 + `published_at` 在窗口内（如旧版本在窗口内被正式下线/退役）→ 保留，但 headline 必须反映真实事件（"X 退役"而非"X 上线"）
     - 当前最新版本 → 正常保留
   - **关键反例**：GPT-5.3-Codex 2 月发布，4 月当前旗舰已是 GPT-5.4 → 不得以"GPT-5.3-Codex 上线"为 headline 出现在 4 月日报中

3b. **重大事件补证与事件追踪（major_event）**

   - **判定**：见编辑原则。`major_event: true` 只能标在 `editorial_tier: core` 的条目上。
   - **当天深度补证（2-3 跳）**：对重大事件，证据扩展从常规 1 跳放宽到 2-3 跳，目标面优先：model card / system card / 官方 benchmark 页 / pricing 页 / developer docs / 可用区与配额说明。每次尝试照常写入 `fetch_status.source_details`。
   - **撰写 `expanded` 块**（schema `$defs/expandedBlock`，挂在条目上）：
     - `what_shipped`（50-600 字，必填）：发布要点
     - `benchmarks`（≤600 字，可选）：官方 benchmark 摘录，只写官方给出的数字
     - `pricing_availability`（≤400 字，可选）：定价、配额、可用区
     - `comparison`（≤400 字，可选）：与现役模型/版本对比
     - `third_party_reaction`（≤400 字，可选）：已抓到证据的第三方反应，禁止臆测
     - `decision_relevance`（≤300 字，可选）：对在途选型/迁移决策的整体判断（与 decision_radar 互补：radar 按决策分组一句话，这里是事件视角）
     - `quick_start`（≤300 字，可选）：第一时间上手路径（入口 / 版本号 / 前置条件）
     - `open_questions`（1-5 条，必填）：待验证问题清单，将转入事件追踪
   - **事件重要性与专题成熟度分别判断**：重大事件继续补证、写 expanded 和开追踪；是否具备独立研究价值按 3b-3 判定。不能因为暂时缺少评测而降低重大事件等级，也不为重大事件自动配发专题。
   - **开追踪档案**：写 `cache/tracking/{event_slug}.json`（schema `schemas/event_tracking.schema.json`）。`event_slug` 用小写连字符（如 `claude-fable-5`），`expires_on` 距 `opened_date` 不超过 5 天，`watch_items` 直接继承 `open_questions`。条目同时写 `tracking_ref: {event_slug}`；finalize 会校验 `major_event` 条目必须有 expanded + tracking_ref，且 tracking_ref 能解析到活跃档案。
   - **追踪期内的后续日报**：`discovery_manifest.json` 的 `active_tracking` 会列出活跃追踪事件。对每个活跃事件至少执行一轮定向搜索（第三方评测 / 实测反馈 / 价格与配额变化）。
     - **跟进留痕（finalize 强制）**：把当天定向搜索写入 `fetch_status.source_details["Event Tracking: {event_slug}"].attempts[]`（无增量也要记一条空结果 attempt）。开档当天豁免；追踪期内缺该 surface 会导致 finalize-daily 失败。
     命中的增量条目：
     - 豁免 3-1 跨日去重（见该节例外 2），headline 必须体现增量（如「Fable 5 第三方评测首批出炉」）
     - 条目带 `tracking_ref`，并把 `{date, headline, ref}` 追加进追踪档案的 `updates[]`
     - 没有增量就不写条目，不为追踪而凑数
   - **关闭**：`expires_on` 过后档案自动失效；finalize 会清理过期超过 7 天的档案。追踪档案的 `updates[]` 是周报回顾该事件的现成素材。

3b-1. **模型能力卡（正文必读，不依赖独立专题邮件）**

   - 新生成日报使用 `version: "1.1"`；历史 `1.0` 仍可重渲染。每条 `frontier_models` 必填 `model_assessment`，不以 `major_event` 为前提。新模型、能力更新、评测事件应填写 `status: assessed`；查不到分数用 `insufficient_evidence` 并列明查过哪些评测面、未取得什么；纯调价/政策事件用 `not_applicable` 并说明不涉及能力更新。不能为过校验编数字。
   - **采集目标**：打开官方发布页、model/system card、技术报告的评测表及脚注；再查至少一个独立评测面。图表在图片/PDF中时应读取图表，不能只读标题摘要。优先选能解释强项与短板的代表性项目，通常覆盖编码、推理/知识、Agent/工具、多模态或长上下文中与发布相关的维度；没有相关数据就写缺口，不强凑固定数量。
   - **结构**：`conclusion` 先给综合判断：能力处于什么位置、相对谁有何优势、成本是否划算、适合什么任务及主要边界。不能只写“值得关注/验证、尚不能全面替代”。`groups[]` 按评测来源/条件分组，每组必填 `title / source_name / source_url / evidence_type / observed_at / conditions / metrics`。`evidence_type` 为 `vendor_reported / independent / team_test`；跨页面对照的来源写 `supporting_sources[{source_name, source_url}]`，组内核验时间覆盖这些页面。全部主来源和对照来源必须在 `fetch_status.source_details.*.attempts` 中有成功的精确 URL 抓取记录，并补到候选的 `source_attempt_refs`。
   - **每项评测**：填 `benchmark`（含版本）、`what_it_tests`（用中文解释测什么）、`model_variant`（具体型号和推理档位）、数值 `score`、`unit`、`direction`、`comparators[{model_variant, score}]`、`interpretation`。优先带上一代和有决策价值的竞品/同系列对照；取不到对照则空数组并说明缺口。不得把综合指数写成百分制成绩，也不得把 Elo 当正确率。
   - **可比性**：`conditions` 写清推理档位、Agent 运行框架（harness）、工具/预算、采样与统计不确定性；未披露就明确写未披露。不同框架/档位的结果分组呈现或显式限定比较，禁止合成自创总分/总排名。已公开的反例、退步项以及 Token 消耗/延迟/每次成功成本应与优势一起交代。
   - **两个时间口径**：同一评测方公开的新旧版本对比可进入能力卡，无需本地昨日快照；同一模型的跨日榜单升降仍必须遵守 `hard-data-delta` 基线要求。百分比成绩之差用“百分点”，相对变化才用“%”；不得混用。
   - **性价比证据**：能力与成本一起判断，主动核验相关前沿模型及同价位候选，不能因用户偏好或单一排行榜给出“优秀/落后”。标清价格提供方、货币、每百万 Token 输入/输出、缓存和长输入条件；API、订阅、加速档、自部署分别讨论。有同口径评测任务成本时，和 Token 单价同时给出；不能把评测平均成本说成生产每次成功成本。没有总成本数据就明确缺口，不能仅据单价推断实际节省。比较前先核对评测版本和档位，不混用新旧综合指数；比例须复算，不自创“得分除以价格”的总排名。
   - `strengths / limitations / evidence_gaps` 分别回答已有优势与适用场景、已知短板和代价、还有哪些证据欠缺。支持的正面结论要明确写出，不让通用免责声明淹没优势；场景建议标明是由公开分项推断还是团队实测。对 Pro/Flash、API/开放权重不能互相借用评测结论；上下文上限也不等于有效召回能力。
   - `expanded` 保留发布规格、价格/可用性和事件背景；有能力卡时不再重复 `expanded.benchmarks`。独立专题深化方法和场景，正文仍须能独立回答“分数多少、和谁比、强在哪里、代价是什么”。`market_signals` 保留快照/变化审计记录与简短增量，分数详表只在能力卡展示。

3b-2. **晨报阅读主线与去重**

   - 顶层 `reading_guide` 写 0-4 条“今日核心判断”，每条 `{text, ref}` 必须回指正文，最多 160 字；安静日允许空。模型条目优先写“型号与定位 → 关键能力对照 → 成本优势或代价 → 适用任务/关键边界”，正文已有的决定性数字不要省成模糊形容词。不得只写“值得看/有进步/仍需验证”，不得只列风险、不交代已成立的价值，也不得复述新闻标题。每个价格/分数在正文可查到同口径来源；无法判断就具体说明缺哪个证据。
   - **读者验收**：只看开头应能回答“这款模型相对谁处于什么位置、为何值得用或不值得、适合什么任务”。HTML 的导读链接只显示“查看详评”，钉钉导读不追加重复标题。两端正文语义层级为 H1 报告 → H2 栏目 → H3 模型/事件 → H4 能力评测 → H5 评测分组；不得靠同级大字或空行模拟从属关系。钉钉发布必须回读真实块级标题验收，详见同步工作流。
   - 展示顺序固定为：模型 → Coding Agent → 通用 Agent → 硬数据 → 跨条目模式 → 决策雷达 → 落地建议 → 建议实验 → 生态实践 → 方法论 → 待核实。目录、正文和终端简版保持一致。
   - **各层各司其职**：正文说事实与证据；模式只写至少两条事件合起来才成立的新判断；雷达说明哪个在途决策改变、哪个门槛尚未跨过；建议写是否行动、投入与验收；实验只写执行步骤与产物。每层不能只是换句话重复“值得小范围试点”。
   - 同一事件横跨模型与 Coding 工具时，模型节讲能力，工具节只讲接入、额度与管理增量。没有新分析时压缩观察段，空板块用一句说明，不凑趋势。把内部 ref 显示成文章标题，避免读者看到数组索引。
   - 读者身份来自 `profile.yaml`，不要套泛化的“四角色”模板。具体型号的接入入口、评测配置与实验对象需逐一对应，不能因一款已接入某工具就假设另一款也已接入。

3b-3. **按需选型研究（独立专题）**

   - 晨报必须独立讲清能力、分数、强弱项、成本与适用边界。专题只在能解决一个具体选择问题、且比晨报增加实质比较或推理时生成；没有新增判断就不发，不设日更篇数。
   - 立项与写作时阅读 [专题研究工作流](workflows/deep-dive-research.md)。围绕任务选择、替代条件、成本取舍组织内容；不套背景/生态/四角色，不按总字数凑篇幅。公开可查的信息先查清；公开未披露与必须业务实测的未知分开说明。
   - 新专题使用 `deep_dive` 1.1 格式。AI 对照晨报复核新增价值、证据可比性、场景推断与反例，通过后才将 slug 写入日报顶层 `deep_dive_refs`；无专题写 `[]`。这份显式清单是 finalize 唯一的专题选择入口，事件标签和目录中已有文件均不触发投递。历史日报省略清单按空处理，历史专题 1.0 保留重渲染能力。
   - 已选专题按既有路径渲染、归档并独立邮件发送，复用 `deep_dive:{slug}` 去重。专题可在后续证据成熟时生成，也可比较多个对象，不要求当日报存在同名 major_event。专题不替代、也不改变每天晨报的钉钉全文同步。

3c. **生成 Agent 生态与实践（agent_ecosystem）**

   - 每天 0-4 条，来源：GitHub Trending（已有 surface）、`ecosystem_search_queries`、`agent_ecosystem_sources`（Anthropic Engineering / LangChain Blog / Latent Space 等）、HN 实践讨论
   - 四种 `item_type`：
     - `trending_repo`：热门 agent 仓库。必须带 `repo_slug` 与 `heat_note`（star 数 + 快照时间，沿用 community_snapshot 纪律，不写"今日登顶"）。受 `cache/seen_repos.json` 30 天冷却约束：同一仓库 30 天内不重复收录（finalize 强制）；同日重跑不受限
     - `skill_plugin`：可直接使用的 skills / 插件 / MCP server。必须带 `onboarding_cost`（ready_to_use / needs_config / needs_build）
     - `practice_case`：工程实践 / 团队落地复盘。日报只写 1-2 句导读 + 链接，深读进周报
     - `tool_release`：值得关注的工具发布
   - **准入窗口与新闻线不同**：放宽为"7 天内首次达到阈值 / 首次被收录"，但 `relevance` 必须锚定 profile.yaml 的 `practice_focus` 或某个角色——不泛收一切 AI 热门
   - 生态条目不进入 `action_items` 依据，可作为 `experiments_this_week` 的素材
   - 空则 `items: []` + `empty_message`，不凑数

3d. **负责人访谈发现与文稿（interview，独立邮件，非核心源、不阻塞日报）**

   - 跑 `whitelist.yaml > leader_interviews` 面 + `interview_search_queries`；每场候选抽 `{person, org, role, interview_title, outlet, original_url, published_at}`，尝试照常写入 `fetch_status.source_details["Leader Interview Discovery"].attempts[]`。
   - **关注范围**：`profile.yaml > interview_watchlist`（Anthropic/OpenAI 高管创始人首席科学家 + 两家产品/工程负责人 + DeepMind/其他前沿实验室 + 头部 coding agent 产品负责人）；seeds 是种子，可顺名追人。
   - **新鲜度 + 去重门（两层职责，别混淆）**：
     - **AI 立项层（语义去重）**：先读 `cache/interview_seen.json`（其中每条已存 `original_url` / `person` / `title`）。`published_at`（或首次被权威源提及）≤14 天 **且** 当前候选与台账中任何一条都不构成「同一场访谈」（按归一化 `original_url`、或 person+title 近似判断）→ 立项；否则跳过并在 run.log 记命中原因。这一步的「同场」判断由 AI 完成，不是脚本规则。
     - **脚本幂等层（slug 兜底）**：finalize 的 `interview_already_sent` 只按 `slug` 判定，防止「同一个 `interview_{slug}.json` 重跑 finalize 时重发」。它**不**做 URL/person 级语义去重——那是上一层 AI 的职责。
     - 因此**永久去重的有效性依赖 AI 为同一对象复用稳定 slug**：同一场访谈即使改天被重新发现，也必须沿用首次的 `slug`（如 `fiona-fung-claude-code`），否则换 slug 会绕过脚本幂等导致重发。起 slug 前先在台账里核对该对象是否已有既有 slug。
   - **找中文整理稿**（跑 `interview_zh_transcript_queries`）：
     - 命中高质量中文稿 → `mode=linked_zh_transcript`：`chinese_transcript.{available:true,url,outlet}` + 300-500 字 `lede` 导读 + `key_points` + 可选 `notable_quotes` + `role_implications`（四角色）。
     - 未命中 → 尝试取原文逐字稿（YouTube 字幕 / show notes / 文字访谈正文）：取到 → `mode=self_translated_full`：填 `full_translation`（分段中译）+ `lede` 要点；取不到逐字稿 → `mode=deep_summary_fallback`：`lede` + `key_points` 写 800-1500 字结构化深度摘要，并在 `lede` 显式标注「无逐字稿，基于公开报道/节选」。
   - **来源闭环**：`references ≥1`，全部回溯当日 fetch 留痕；禁止臆测。
   - 落盘 `cache/{date}/interview_{slug}.json`（schema `schemas/interview_brief.schema.json`，`slug` 小写连字符）。当日无新访谈 → 不产出任何 interview JSON、不发访谈邮件。访谈不进 `action_items` 依据。
   - finalize-daily 会渲染 `reports/interviews/{date}-{slug}.html` 并以「**AI 访谈 · {person}（{org}）**」独立邮件发送；发送成功后写 `interview_seen.json`，对已发 slug 幂等跳过。

3e. **方法论雷达（methodology_radar，日报捕获，允许空）**

   - 来源：`whitelist.yaml > methodology_radar_sources` + `methodology_search_queries`，结合当日 `agent_ecosystem` / 实践信号。写入 `fetch_status.source_details["Methodology Radar Discovery"].attempts[]`。
   - **准入窗口宽口径**：与 `agent_ecosystem` 一致——「7 天内首见 / 首次被收录」，不走严格当日新闻硬卡（方法论是慢信号）；靠 `cache/methodology_seen.json` 的 30 天 cooldown 防止天天复读。cooldown 是 **advisory**：冲突只在 run.log 记 `METHODOLOGY cooldown(advisory)` 告警、**不阻断**日报投递；台账在日报正文发送成功后才写入（dry-run / 发送失败不烧冷却）。复用稳定 slug 才能让 cooldown 生效。
   - 每天 0-3 条，**允许空**（`items:[] + empty_message`）。每条字段：`slug`（小写连字符）/ `title` / `kind`（`paradigm_shift` / `framework_tool` / `practice_pattern`）/ `what_it_is` / `why_trending`（+ 证据）/ `how_team_can_use` / `depth_link` / 可选 `hook`（回指当日 `experiments_this_week[i]` 或 `action_items[i]`）/ `references`（≥1，回溯 fetch 留痕）。
   - 锚定 `profile.yaml > practice_focus` + 范式网（spec-driven / harness / loop engineering 等），不泛收一切 AI 热点。
   - **不进 `action_items` 依据**；`hook` 是单向的（radar → experiment/建议）。

4. **产出 coding_agents 深度观察**
   - 从 coding_agents.items 中挑最值得关注的 1 条
   - 写 150-250 字中文分析，填入 `deep_dive.body`
   - **安静日放宽**：当 frontier_models + coding_agents + general_agents 总条目 ≤ 4 时，deep_dive 字数上限放宽到 **150-400 字**，允许更深入的趋势分析和背景解读
   - 若当日无 coding_agents 进展：仍写一段观察（可围绕"本周无新动作，建议保持观察"或近期延续话题）

5. **抓取并解析硬数据（market_signals）**
   - 对 `whitelist.yaml > hard_data` 4 个源走标准 fetch_chain（LMArena / Artificial Analysis / OpenRouter / HuggingFace Trending）
   - **快照纪律（必做）**：抓取 hard_data 面时，把读到的原始数字写入 `cache/{date}/hard_data_snapshot.json`：
     `{"version":"1.0","date":"{date}","sources":{"lmarena":{"observed_at":...,"url":...,"models":[{"model":...,"elo":...,"rank":...}]},"artificial_analysis":{"models":[{"model":...,"index_score":...}]},"openrouter":{"models":[{"model":...,"input_price_per_mtok":...,"output_price_per_mtok":...}]}}}`。
     抓不到的源可缺省；有啥记啥，不做判断。
   - 然后跑 `python skills/ai-daily-report/scripts/report_runner.py hard-data-delta --date {date}`：
     `deltas` 里 `status=changed` 的条目是有真实基线的变化 → 据此写 `benchmark_changes` / `pricing_changes`；
     `status=new_entry`（首见/无基线）→ 只能进 `benchmark_watch`，不得写成"变化"。当天缺快照会被 qa_diff 记 `hard_data_gap` 告警。
   - LMArena / Artificial Analysis：
     - 若窗口内存在可明确归因的显著变化（如 Elo 变化 > 10 或 > 5%）→ 进入 `market_signals.benchmark_changes`
     - 若当天出现新的 benchmark / score snapshot、榜单进入、或新模型评分首曝，但缺稳定前一日基线、尚不足以写成严格 delta → 进入 `market_signals.benchmark_watch`
   - OpenRouter：与上一轮抓取（`cache/{prev_date}/report.json`）对比 → `pricing_changes`；首次运行无上一轮则 `[]`
   - 基于 benchmark 快照写 1-3 条一句话 `capability_gaps`
   - `benchmark_changes` 只写有前后基线的真实变化；没有 old/new 或 rank delta 时，不得写“上升、下降、扩大领先、超越”等变化性措辞。
   - `benchmark_watch` 写新评分、新上榜、当天快照或缺稳定基线的榜单观察，必须有 `observed_at`、source 与有效 `ref`；每个 `benchmark_watch` item 的 `ref` 都必须指向相关正文条目：`frontier_models[i]`、`coding_agents[i]` 或 `general_agents[i]`。
   - `capability_gaps` 是解释层；涉及 benchmark / leaderboard / score / pricing 时，必须引用 `benchmark_changes`、`benchmark_watch`、`pricing_changes` 或正文 item ref。
   - 任一子数组有内容即可；只有 `benchmark_changes / benchmark_watch / pricing_changes / capability_gaps` 全空时，才填 `empty_message: "今日无显著硬数据变化"`
   - 4 个 hard_data 源同样写入 `fetch_status.source_details`
   - **hard_data 不进 core_sources**：失败不阻塞日报

6. **跨条目模式识别（pattern_observations）**
   - 写完 frontier / coding / general 三节后，反思是否有 ≥2 条可归入同一主题
   - 有 → 写入 `pattern_observations.items`（日报 0-3 条，允许空）
   - 每条必须填：
     - `theme`（≤60 字）
     - `supporting_item_refs`（≥2 条，形如 `"frontier_models[0]"`，索引必须真实存在）
     - `interpretation_for_tech_lead`（100-220 字，明确回答"这组动作合在一起对技术负责人意味着什么"）
   - 无可归纳主题 → `items: []` + `empty_message: "今日无显著跨条目模式"`
   - **严禁为凑数强行合并**

7. **生成本期实验（experiments_this_week）**
   - 基于本期 coding_agents / general_agents 最值得一试的工具或能力，**0-1 条**可执行实验
   - 字段：`{title, hypothesis, steps[2..5], time_budget_hours.{min,max}, expected_output, required_skills[1..4]}`
   - **`time_budget_hours.max ≤ 8` 小时**；产出必须是单一可衡量结果
   - 每条实验必须标 `audience`：`team_pilot`（设计为 2-3 人小范围团队试点，expected_output 必须是可向上汇报的度量结果）或 `personal_workflow`（个人当天/当周可试的新用法）。按当日素材选最合适的受众，不强行轮换
   - 无可试项 → `items: []` + `empty_message` 写明原因

7a. **生成决策雷达（decision_radar）**

   - 对 `profile.yaml > decisions_in_flight` 的每个在途决策，检查当日 `core/watch` 正文条目是否影响该决策（候选变化、定价、企业功能、benchmark、可用性等）
   - 有影响 → 该决策建一个 group：`decision_name` 必须与 profile 中的 `name` 一致（finalize 校验），每条 `{ref, impact}`，`ref` 指向正文条目，`impact` 一句话说清"对这个决策意味着什么"（≤120 字）
   - 每个决策最多 4 条；无影响的决策不建 group；全空则 `decisions: []` + `empty_message: "今日无影响在途决策的信息"`
   - 雷达是 action_items 的输入参考：step 8 写建议前先看雷达
   - `unverified` 条目不得进入雷达

8. **推导当日落地建议（action_items）**
   - **严格依赖当日前四节**（frontier / coding / general / market_signals）
   - 先列出可引用的 `core/watch` 正文事实，再从这些事实倒推出建议；不要先写建议再反向找依据
   - `unverified` 或仅媒体单源传闻**不得**进入 `action_items`
   - 0-4 条；每条必须携带：
     - `recommendation`（≤120 字）
     - `rationale`（≤240 字）
     - `recommendation_type`（patch / experiment / adopt / migrate / monitor / hire）
     - `effort_person_days{min,max}`
     - `time_horizon`（this_week / this_month / this_quarter）
     - `team_size_applicability[]`（small_lt_10 / medium_10_50 / large_gt_50）
     - `priority`（P0 / P1 / P2）
     - `references[]`：每条引用都必须指向 `frontier_models / coding_agents / general_agents` 中的 `core/watch` 条目
   - **多样性硬约束**：items ≥ 3 时 `recommendation_type` 必须出现 ≥3 种不同值；不允许全 patch / 全 monitor
   - **范围约束**：`effort_person_days.max ≤ effort_person_days.min × 3`
   - 写作语气必须回答"是否下注 / 何时下注 / 下注多少人日"，不是"怎么打补丁"
   - **稀薄日纪律（finalize 强制）**：前三节合计 ≤2 条时，action_items 最多 1 条；decision_radar 允许空。宁可写"今日信号不足，延续近期建议"，不允许把单条更新放大成成套建议
   - 空时 `items: []` + `empty_message: "今日无明显行动项，延续近期建议。"`

9. **产出结构化 JSON**
   - 严格遵循 `schemas/daily_report.schema.json`
   - 字段约束：新日报 `version: "1.1"`、`type: "daily"`、`date`、`window`（带时区）、`generated_at`、`reading_guide`、**十一个 `sections`**（frontier_models / coding_agents / general_agents / market_signals / pattern_observations / decision_radar / action_items / experiments_this_week / agent_ecosystem / methodology_radar / unverified）、`fetch_status`。历史 `1.0` 兼容读取；不要用旧版本跳过新日报能力卡要求。
   - **章节标题契约**：`sections.*.title` 只写纯语义标题（如 `模型动态`、`方法论雷达`），不得写 `一、`、`三a、`、`6.` 等展示编号；日报/周报模板是章节编号的唯一真源，schema 会在渲染前拒绝带编号标题。
   - **每条正文章目必须填 `release_stage` / `published_at_confidence` / `authority_score` / `editorial_tier`**（schema required，缺失会被 render 阶段拒绝）
   - **`fetch_status.source_details`** 必须记录所有走过 fetch_chain 的源（含降级路径），渲染层会展示降级路径供巡检
   - **来源闭环要求**：进入正文（前三节 + market_signals）的每条信息，都必须能回溯到某次具体抓取尝试；若无法在 `fetch_status.source_details` 中解释它是怎么来的，要么补记该尝试，要么降到 `unverified`，不要保留“正文比日志更聪明”的状态
   - **候选台账要求**：除 `report.json` 外，还要落一份 `cache/{date}/candidate_ledger.json`
     - 每条候选至少记录：`candidate_id` / `headline` / `proposed_section` / `published_at` / `source_attempt_refs` / `verification_state` / `editorial_tier` / `decision` / `decision_reason` / `novelty_vs_yesterday`
     - 每条候选还必须记录 `event_type`、`date_basis`、`evidence_path`、`why_today`、`action_eligibility`。
     - `page_updated_at` 不能单独作为 `selected_core` 或 `selected_watch` 的日期依据；Help Center / release notes / changelog / docs 页面必须优先取小节日期、release metadata 或正文明确事件日期。
     - `media_only`、`community_snapshot`、`search_only` 与 `selected_unverified` 不能驱动 action；`media_plus_official_one_hop` 只能驱动 monitor / experiment。
     - `candidate_ledger.json` 只用于审计与复盘，不参与 HTML 正文渲染
   - **落盘前编辑自检**：至少再问自己 5 个问题
     1. 今天是否有高信号官方更新被首轮静默掩盖？
     2. 是否把榜单快照或静态排名误写成“变化”？
     3. 每条 action item 是否都能回指正文中的事实，而不是只来自感觉？
     4. 新模型是否给出可直接阅读的评测分项、对照、测试条件和短板，而非只有参数量、排名或“值得测试”？
     5. 每个结论层是否提供新的信息？型号、实验入口、基线、投入与验收是否前后一致？
   - 落盘：`cache/{date}/report.json`
   - 助手必须自检 JSON 结构，字段不完整时自行补齐后再写入

9a. **Runner 收尾（默认入口）**
    - Run: `python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date {date} --env .env`
    - dry-run: `python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date {date} --env .env --dry-run`
    - 作用：再次校验邮件环境变量，检查 `fetch_status` 覆盖、`candidate_ledger.json` 与正文对齐、`action_items.references[]` 只能引用 `core/watch` 正文条目；通过后再顺序执行渲染、归档、发送邮件。
    - 若发送失败：必须保留 `cache/{date}/report.json`、`cache/{date}/candidate_ledger.json`、`cache/{date}/report.html` 与 `cache/{date}/run.log`，并返回明确错误。

9b. **每日定时任务的钉钉同步**
    - 已获用户授权的“AI日报晨报”定时任务，在最终内容通过校验后执行 [钉钉在线文档工作流](workflows/dingtalk-daily.md)，把同一份完整晨报新建到指定的“AI信息晨报”目录。
    - 保留模型评分表、测试条件与来源链接；按北京时间日期去重，保存真实文档链接并回读核对全文。邮件与钉钉的结果分别报告。
    - 普通手动运行、dry-run、历史补齐和周报不因这一规则自动发布到钉钉；是否发布以当前请求或任务明确授权为准。

10. **渲染 HTML（调试/单步重跑）**
    - Run: `python skills/ai-daily-report/scripts/render_html.py cache/{date}/report.json`
    - 期望：退出码 0，stdout 是生成的 HTML 绝对路径
    - 若退出码 1（schema 校验失败）：修正 JSON 后重试；若退出码 2（IO 错误）：检查权限并报告

11. **归档（调试/单步重跑）**
    - Run: `python skills/ai-daily-report/scripts/archive.py cache/{date}/report.html --type daily --date {date}`
    - 期望：退出码 0，stdout 是归档后的绝对路径
    - 该步骤顺带清理 cache 中超过 14 天的子目录

12. **发送邮件（调试/单步重跑）**
    - Run: `python skills/ai-daily-report/scripts/send_mail.py reports/daily/{date}.html --subject "AI 日报 · {date}"`
    - 脚本会自动从 `./.env` 读 `GMAIL_USER` / `GMAIL_APP_PASSWORD` / `REPORT_RECIPIENTS`，通过 `smtp.gmail.com:465 (SSL)` 直接发送 HTML 正文（含 plain text fallback）
    - 期望：退出码 0，stdout `sent to=... subject=...`
    - 退出码 1 = 参数/配置问题，2 = SMTP 认证失败（多半是应用专用密码失效），3 = SMTP 网络/服务错误
    - 若 dry-run 模式：**跳过此步**，在 run.log 写 `EMAIL skipped (dry-run)`

13. **终端输出中等详细度简版**
    - 固定格式：
      ```
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      AI 日报 · {date}

      今日核心判断：{reading_guide 全部显示}

      一、模型动态
        · {item 1 headline}
        · {item 2 headline}
        ...（最多显示 2 条，其余用「还有 N 条」表示）

      二、Coding Agent 专项
        · {item 1 headline}
        · {item 2 headline}
        深度观察：{deep_dive.title}（详见 HTML）

      三、通用 Agent 动态
        · {item 1 headline}
        ...

      四、硬数据信号
        {增量与观察摘要；模型分数详表见对应正文能力卡}

      五、跨条目模式
        {若有 pattern observation 显示 theme；空显示 empty_message}

      六、决策雷达
        {每个有内容的决策一行；空显示 empty_message}

      七、今日落地建议
        {全部逐条打印；空显示 empty_message}

      八、本期建议实验
        {若有显示 title；空显示 empty_message}

      九、Agent 生态与实践
        · {item title}（{item_type 中文标签}）

      十、方法论雷达
        · {item title}（{kind 中文标签}）

      十一、观察区 / 待核实
        {逐条打印待核实候选；空则显示本节无内容}

      负责人访谈：{有/无}{若有：· {person}（{org}）· 已独立邮件发送/Dry-run 未发送}

      抓取状态：{succeeded 数} 成功 / {failed 数} 失败 / {empty 数} 无内容

      HTML 已归档：
         {绝对路径}
      {邮件已发送/Dry-run 未发送}：{RECIPIENT_EMAIL}
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ```

14. **运行日志收尾**
    - `END daily status=ok` / `status=email_failed` 由 `finalize-daily` 写入，**AI 不要手写 END 行**。
    - finalize 返回非零且 run.log 有 `END daily status=email_failed` 时：邮件未送达。用 `send_mail.py` 单步补发（脚本自带 3 次重试），补发成功后终端简版如实报告"邮件经补发成功"。

## 周报工作流

**目标窗口**：最近 7 天——`end_date` 往前数 7 个自然日（含 `end_date` 当天）；`end_date` 默认为运行当日
**采集窗口**：`{end_date-6} 00:00 ~ {end_date} 23:59:59`（北京时间）
**运行节奏**：任意一天可跑（建议每周固定一天）。`cache/tracking/` 中窗口内活跃过的追踪档案（含 `updates[]`）是周报回顾重大事件的现成素材，读入后随日报 JSON 一起聚合。

步骤：

1. **检查日报齐全**
   - 以 `cache/{date}/report.json` 为准检查窗口内 7 个日期是否齐全（含运行当日；当日日报未生成同样按缺失补齐）；`reports/daily/*.html` 只作为成品展示，不作为周报聚合的 source of truth
   - 对每个缺失日期：**独立走一次"日报工作流步骤 1-6"** 补齐（包括抓取、归类、产出 JSON 与 HTML），并把该日期加入 `source_days.backfilled`

2. **读入 7 份日报 JSON**
   - 从 `cache/{date}/report.json` 读入每天的结构化数据
   - 合并为内存中的"本周事件集合"
   - `source_days.daily_reports_used` 必须恰好等于 `week_end` 往前的 7 个自然日；`backfilled` 只能是其中子集

3. **聚合 & 去重 & 归纳**
   - 按模型提供方聚合 frontier_models 条目 → `vendor_groups`
   - 按产品聚合 coding agent 条目 → `product_groups`
   - 通用 agent 按现有 schema 划分 `newcomers` 和 `big_lab_moves`；这只用于周报归纳与排版，不代表对象天然更重要
   - 每个 vendor_group / product_group 必须填 `weekly_changes / trend_judgment / implication / references`（三段式观察深度**二/三/四节保持一致**）

3a. **聚合本周硬数据（market_signals）**
   - 新版日报的 `model_assessment` 是模型能力证据输入：归纳时保留具体型号、来源与可比条件，不能只提取总分；不得把不同框架或指数版本合成周级排名。
   - 从 7 份日报的 `market_signals` 合并；按 `change_pct` 绝对值取 top 5-8 条
   - `capability_gaps` 改写为周级（2-4 条）
   - 任一子数组有内容即可；全空时填 `empty_message: "本周无显著硬数据变化"`

3b. **识别跨日模式（pattern_observations）**
   - 在 7 份日报条目 + 本周硬数据上识别 ≥1 条主题
   - **`pattern_observations.items` 必须 ≥1 条**（schema 强制）
   - 字段同日报：`theme` / `supporting_item_refs` / `interpretation_for_tech_lead`（100-220 字）

3c. **生成本周实验（experiments_this_week）**
   - 1-3 条；**`experiments_this_week.items` 必须 ≥1 条**（schema 强制）
   - 每条 `time_budget_hours.max ≤ 16`（周报上限），可在 1 周内完成
   - 字段：`{title, hypothesis, steps[2..5], time_budget_hours.{min,max}, expected_output, required_skills[1..4]}`
   - 每条实验必须标 `audience`（team_pilot / personal_workflow）。若本周日报素材足够，1-3 条实验应覆盖两种受众各至少一次；素材不足时不强凑，但要在 hypothesis 里说明为何只面向单一受众

3d. **生成本周实践精选（practice_digest）**

   - 从本周 7 份日报的 `agent_ecosystem` 条目（优先 `practice_case`，也可选特别值得深读的 `skill_plugin` / `trending_repo`）中挑 0-2 篇做深读
   - 每篇：`summary`（200-400 字深读摘要：它解决什么问题、怎么做的、有什么数据或代价）+ `applicability`（adopt_now 适合现在引入 / wait_mature 等工具成熟 / reference_only 仅参考思路）+ `applicability_note`（一句话判断依据）
   - 每篇必须带 `origin: {date, title}`，date 在本周 `source_days` 内，title 与该日日报 `agent_ecosystem` 条目的 title 完全一致（finalize 校验，校验不过会阻塞发送）
   - 当周日报生态板块没有值得深读的内容 → `items: []` + `empty_message`，不硬凑

3e. **方法论雷达聚合（methodology_radar）**

   - 聚合本周 7 份日报的 `methodology_radar` 条目 + 周级 `methodology_search_queries` 补充 + 跨日范式归纳。
   - 1-3 条/周，**允许空**（`items:[] + empty_message`）；字段同日报。周报版可写更深的「为何是趋势」与团队落地路径。
   - 周报**不做 cooldown 去重**（它是日报的聚合，cooldown 由日报捕获时已执行）；只做 `hook` 越界校验与 `references` 闭环。

4. **补充搜索（兜底）**
   - 3-5 条搜索，query 形如 "AI industry week summary {week_range}"（以窗口日期区间替换，如 2026-06-07..2026-06-13）、"top AI agent news this week" 等
   - 对比日报聚合结果，补齐遗漏内容

5. **产出周报 JSON**
   - 严格遵循 `schemas/weekly_report.schema.json`
   - **十一章节**：`tldr / frontier_models / coding_agents / general_agents / market_signals / pattern_observations / experiments_this_week / practice_digest / methodology_radar / action_items / next_week_signals`
   - **章节标题契约**：`sections.*.title` 只写纯语义标题，不携带 `一、`、`1.` 等展示编号；周报模板统一负责 `一、` 至 `十一、` 的展示编号。
   - 顶层必填 `week_end`（YYYY-MM-DD，窗口结束日）
   - TL;DR 3-5 条
   - **落地建议**：3-5 条体系化建议，每条字段与日报 `actionItem` 完全一致：
     - `recommendation` / `rationale` / `recommendation_type` / `effort_person_days{min,max}` / `time_horizon` / `team_size_applicability[]` / `success_metric` / `priority` / `references`
   - `references` 引用本周具体日期的日报条目
   - **多样性硬约束**：items ≥ 3 时 `recommendation_type` 必须出现 ≥3 种
   - 落盘：`cache/weekly/{end_date}/report.json`

5a. **Runner 收尾（默认入口）**
   - Run: `python skills/ai-daily-report/scripts/report_runner.py finalize-weekly --end-date {end_date} --env .env`
   - dry-run: `python skills/ai-daily-report/scripts/report_runner.py finalize-weekly --end-date {end_date} --env .env --dry-run`
   - 作用：校验周报 JSON 已落盘，并检查 CLI 传入的 `end_date` 是否与 payload 的 `week_end` 一致、`source_days` 是否完整覆盖该周、`cache/{date}/report.json` 是否齐全、weekly `references` 是否能回指日报条目、以及 `itemRef` 是否越界；通过后再顺序执行渲染、归档、发送邮件。若发送失败，保留 `cache/weekly/{end_date}` 下所有产物与 `run.log`。

6. **渲染 HTML（调试/单步重跑）**
   - Run: `python skills/ai-daily-report/scripts/render_html.py cache/weekly/{end_date}/report.json`

7. **归档（调试/单步重跑）**
   - Run: `python skills/ai-daily-report/scripts/archive.py cache/weekly/{end_date}/report.html --type weekly --date {end_date}`
   - 清理 cache 时只删除过期的叶子目录；周报会按 `cache/weekly/{end_date}` 粒度清理，不会误删 `cache/weekly/` 根目录

8. **发送邮件（调试/单步重跑）**
   - Run: `python skills/ai-daily-report/scripts/send_mail.py reports/weekly/{end_date}.html --subject "AI 周报 · {start_date} ~ {end_date}"`
   - 退出码与异常处理同日报步骤 12
   - 若 dry-run 模式：**跳过此步**，在 run.log 写 `EMAIL skipped (dry-run)`

9. **终端简版**
   - 结构同日报简版，章节名改为周报十一章节（含方法论雷达），TL;DR 全部显示，落地建议全部显示

10. **运行日志**：`cache/weekly/{end_date}/run.log` 追加 `END weekly status=ok`

## 时效性判断规则

- 日报：仅保留 `published_at` 严格落在 `window.start`（昨日 07:00）到 `window.end`（当前运行时刻）之间的条目（由 Step 3-0 窗口硬卡强制执行）
- 无法确定发布时间的条目：若"首次被权威源提及"在窗口内，则保留（`published_at_confidence: inferred`，`confidence` 不得高于 `medium`）
- 明显窗口外的内容：直接丢弃，**即使内容看起来重要或"接近"窗口也不例外**
- 已被前一天日报覆盖的条目：由 Step 3-1 跨日去重处理，除非有实质性状态变更
- 涉及版本号的条目：由 Step 3a 当前状态校验确认是否为最新版本
- 周报：同理，窗口为 `end_date` 往前 7 个自然日（`{end_date-6} 00:00 ~ {end_date} 23:59:59`）

## 归类规则

- **frontier_models**：纯模型能力（新模型发布、benchmark、开源权重、API 定价等）。不含产品化的 coding agent、通用 agent。
- **coding_agents**：明确面向写代码的产品。**不包括**只是"某 AI 助手支持写代码"的通用产品（那些进 general_agents）。
- **general_agents**：通用 agent、browser agent、computer use、工作流 agent、企业 agent 等。不限厂商。
- **unverified**：观察区 / 待核实区。可包含非权威源消息、单一媒体信息、早期爆料，也可包含“官方痕迹存在但信息过薄”的信号；共同点是它们都不应直接驱动正文强结论与行动建议。
- **落地建议**：仅从 frontier_models / coding_agents / general_agents 推导。`unverified` 里的内容**不作为**建议依据。
- **agent_ecosystem**：生态与实践信号（热门仓库、skills/插件、实践案例、工具发布）。不是新闻，准入窗口放宽到 7 天首见；不作为 action_items 依据。
- **decision_radar**：编辑结论层，只引用当日 core/watch 正文条目，按 profile.yaml 在途决策分组。
- **methodology_radar**：方法论/范式/工具思潮（spec-driven / harness / loop engineering 等）。日报捕获 + 周报聚合，宽准入窗口（7 天首见）+ 30 天 cooldown（advisory，不阻断投递）；不作为 action_items 依据，hook 单向连到 experiments/建议。
- **interview（负责人访谈）**：独立邮件产物（非 section），复用 deep_dive 发送骨架；不进日报正文、不进 action_items 依据。
- **政策与合规信号**（policy_compliance_sources）：按影响对象归类——模型/算力可用性（出口管制、备案通过/下架）→ frontier_models；企业部署合规、行业准入 → general_agents；事实链不完整 → unverified。窗口硬卡与来源闭环同标准；对在途决策有影响时必须进 decision_radar。

## 异常处理

- **单源 fetch_chain 整链失败**：所有层都失败 → 记入 `fetch_status.failed`，继续。被任一层兜底成功不算失败。
- **核心源阈值**：`core_sources`（8 个，含 2 家 CN）整链失败数 ≥4 → 中止任务、不发邮件、不归档（仅保留 cache 里的 run.log 供排查）
- **空结果**：一般类别下，最终命中层 `surface_kind: feed` 时窗口内无条目算合法空，同时进 `succeeded` 与 `empty` 且不穿透下层；**`static` 层命中空必须继续下穿**后续 feed 面与 websearch 后才能判空。**`cn_labs` 更严**：feed 层空也只有在它是该链最后一个抓取面时才算数，否则必须继续下穿。未标注 `webfetch` 层按 `static`，`github_releases` 缺省 `feed`。详见日报步骤 1「成功」判定。
- **伪成功（CSS only / 登录墙 / JS shell）**：视为该层 error，立即进入下一层
- **召回守门（finalize 自动校验，会阻断发送）**：① 日报 `cn_labs` / `hard_data` 源判空时，两种情形都会让 **finalize-daily 校验失败（阻断发送）**，错误信息点名源——(a) 最终停在 `static` 层且空、未跑搜索层；(b) 停在 `feed` 层且空，但该链里还有没走到的抓取面（`webfetch` / `github_releases`）。判据按 `attempts[]` 里真实出现过的最大 `layer_index` 算，**不看自报的 `final_layer_index`**——留痕说了算。所以 `hard_data`（每源只有一个 `static` 抓取面）实际必须跑搜索层才能判空；`cn_labs` 走完链内全部抓取面即可，不强制搜索层。确属带日期的倒序发布面、空即权威的，去 whitelist 给该层标 `surface_kind: feed`（改数据，不要在当天口头放行）；② 周报若 frontier_models 在 7 天里 ≥3 天为空或日报缺失（缺失=盲天，不算通过；分母固定为窗口 7 天）、或全部 CN 一级厂商整周零产出 → finalize 校验失败、不渲染不发信。确为安静周时，在周报 `source_days.recall_ack` 留证后可放行：`true` 放行全部，或按信号分别放行 `{"frontier": true}` / `{"cn_labs": true}`（也接受列表 `["frontier"]`）——放行 frontier 不会连带掩盖真实的 CN 漏采。⚠️ `recall_ack` 只接受 **布尔 / 对象 / 列表**；裸字符串 `recall_ack: frontier`（YAML 标量）**不生效、会继续阻断**（属刻意 fail-closed；weekly schema 的 `recall_ack` 已加 `oneOf`，非法形态在渲染时即报错）。
- **render_html.py 失败**：若退出码 1 → Claude 自检 JSON 格式（特别是新增 required 字段 `release_stage` / `published_at_confidence` / `authority_score` / `editorial_tier`，以及 `action_items.references[]` 的 `section` / `editorial_tier`）补齐后重试一次；仍失败则中止并报错
- **archive.py 失败**：停止流程，但保留 cache HTML 供用户手动取用
- **finalize-weekly 校验失败**：若缺日报 JSON、`source_days` 不完整、引用无法回指或 `itemRef` 越界 → 停止流程，不归档不发信，先修正 JSON / 日报缓存
- **send_mail.py 失败**：HTML 已归档 → 报告失败但不回滚归档。退出码 2（认证失败）→ 提示用户重新生成 Gmail 应用专用密码并更新 `.env`；退出码 3（网络/SMTP 错误）→ 建议稍后重跑 `send_mail.py` 单步重试
- **追踪档案损坏**：`cache/tracking/` 下存在无法解析或不符合 schema 的档案 → finalize 校验失败（错误信息会点名该文件）。修复或删除该档案后重跑；过期超过 7 天的档案由 finalize 自动清理。
- **已选专题缺失或损坏**：仅对 `deep_dive_refs` 中的专题检查文件、1.1 结构、日期/slug、证据引用与成功抓取记录。失败时修复，或由 AI 确认尚未成熟后从清单移出并说明延期；不得编造材料过关。未选专题不阻塞晨报，也不会自动发送；重大事件的 expanded 与追踪校验仍然执行。
- **发送幂等（send_state.json）**：`finalize-daily` / `finalize-weekly` 通过 `cache/{date}/send_state.json`（周报为 `cache/weekly/{end}/send_state.json`）记录已发送的日报正文 / 每份 deep_dive / 周报。发送中途失败后**直接重跑 finalize 即可**：已发的封不会重发（run.log 记 `EMAIL skip already-sent ...`），只补发失败的。访谈仍由全局 `interview_seen.json` 幂等。dry-run 不写 send_state。
- **send_mail 自动重试**：瞬时 SMTP/网络错误自动重试 2 次（5s/20s 退避）；认证错误（code=2）不重试，提示更新应用专用密码。
- **DELIVERY_ALERT**：init-daily 检测到昨日有邮件失败（按 kind 区分日报/深度/访谈）或仅 dry-run 时输出告警并写 run.log。注意发送链首个失败即中断，失败点之后的邮件从未尝试、日志里不会出现——所以恢复必须以「重跑 finalize-daily」为主，见「运行前检查 0a」。
- **逐字稿取不到（访谈）**：降级 `mode=deep_summary_fallback`，`lede` 标注来源限制，不报错、不阻塞日报。
- **访谈面整链失败**：记 `fetch_status.failed`，日报照常（`leader_interviews` 非 core_source）。
- **访谈 JSON 损坏 / schema 不合 / mode 与字段不一致**：`validate_interviews` 报错点名文件 → finalize-daily 失败、不归档不发信；修复或删除该 `cache/{date}/interview_{slug}.json` 后重跑。
- **单封补发（可选）**：send_state 幂等已使整体重跑安全；若只想补发单独一封，也可用 `send_mail.py reports/interviews/{date}-{slug}.html` 或 `reports/deep_dives/{date}-{slug}.html` 单步发送（注意单步发送不会写 send_state，之后重跑 finalize 会再发一次该封——优先用整体重跑）。
- **方法论 cooldown 台账损坏**：`methodology_seen.json` 无法解析 → 视为空台账（不阻塞）；如需重置删除该文件即可（删除会让历史范式可能重新进入冷却计算）。

## 产出字段约束

| 字段 | 规则 |
|---|---|
| `headline` | ≤ 30 字 |
| `summary` | ≤ 40 字 |
| `impact` | ≤ 30 字 |
| 深度观察 `body` | 150-250 字（安静日 ≤4 条时放宽到 150-400 字） |
| 日报落地建议 `recommendation` | 一句话，≤ 50 字 |
| 周报 `weekly_changes` | 3-5 句 |
| 周报 `trend_judgment` / `implication` | 各一句话 |
| `pattern_observations.items[].interpretation_for_tech_lead` | 100-220 字 |
| `experiments_this_week.items[].time_budget_hours.max` | 日报 ≤ 8、周报 ≤ 16 |
| `action_items.items[].recommendation_type` | 一期 items ≥ 3 时必须出现 ≥3 种 |
| `action_items.items[].effort_person_days.max` | ≤ `min × 3` |
| `expanded.what_shipped` | 50-600 字（仅 major_event 条目） |
| `expanded.benchmarks` | ≤600 字；`pricing_availability` / `comparison` / `third_party_reaction` 各 ≤400 字 |
| `expanded.decision_relevance` / `expanded.quick_start` | 各 ≤300 字，可选 |
| `expanded.open_questions` | 1-5 条，每条 ≤ 120 字 |
| `major_event` 条目 | 仅 core；每日 0-2 条；必须同时有 `expanded` 与 `tracking_ref` |
| `decision_radar` impact | ≤ 120 字，每决策 ≤ 4 条 |
| `agent_ecosystem` items | 0-4 条/天；trending_repo 30 天冷却；relevance ≤ 80 字 |
| `experiments_this_week.items[].audience` | team_pilot / personal_workflow；周报尽量两种各 ≥1 |
| `practice_digest.items[].summary` | 200-400 字（schema 兜底 120-600） |
| `practice_digest.items[]` | 0-2 篇/周；origin 必须回指本周某日日报 agent_ecosystem 条目 |
| 深度专题 | 按研究增量选择；`deep_dive_refs` 显式选中才投递；1.1 包含选择问题、结论、证据对照、场景、成本约束与剩余未知，引用闭环 |
| 访谈 `lede` | 300-500 字（schema 兜底 200-700） |
| 访谈 `key_points` | 2-8 条；`role_implications` 恰好 4 条 |
| 访谈 `mode` | `self_translated_full` 必须有 `full_translation`；`linked_zh_transcript` 必须有 `chinese_transcript.url` |
| 访谈新鲜度 | 发布 ≤14 天且首次发现；台账 `interview_seen.json` 按 slug 防重发，URL/person 级语义去重由 AI 立项时完成（须为同一对象复用稳定 slug） |
| `methodology_radar` items | 日报 0-3 条 / 周报 1-3 条，均允许空；每条必须 `references ≥1`；`slug` 30 天 cooldown 为 **advisory**（daily-only，冲突写 run.log 告警、不阻断投递；同一范式须复用稳定 slug 才有效） |
| `methodology_radar.hook` | 可选；只能指向 `experiments_this_week[i]` / `action_items[i]`，i 不得越界 |

## 终端输出格式

见日报步骤 10、周报步骤 9。
