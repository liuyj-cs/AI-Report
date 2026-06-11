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
   - 周报：`python skills/ai-daily-report/scripts/report_runner.py init-weekly --iso-week {YYYY-Wnn} --now {ISO8601} --env .env`
   - 作用：提前校验 `.env`、创建 `cache/.../run.log`。日报入口只负责生成 `discovery_manifest.json` 与窗口；周报入口会写 `input_days.json`。若邮件环境变量缺失，此步即失败并停止。
1. **读取 sources/whitelist.yaml**：按类别枚举所有信源和搜索 query
1b. **读取 sources/profile.yaml**：读者画像（四个角色、在途决策、实践关注点）。它是编辑判断的输入：相关性、决策雷达分组、生态板块取舍都要回答"这条信息服务哪个角色/哪个在途决策"。
2. **读取 .env**：确保 `GMAIL_USER`、`GMAIL_APP_PASSWORD`、`REPORT_RECIPIENTS`（或回退 `RECIPIENT_EMAIL`）三项都已配置；任何一项缺失 → **立刻停止并提示用户**补齐。`report_runner.py` 与 `send_mail.py` 都会校验，runner 的职责是让错误尽早暴露。
3. **CN 厂商官方源验证**：whitelist 中标记 `verify_before_use: true` 的中国厂商源，在首次抓取前用一次浏览打开测试。若失败或返回无效页面，记录到 run.log 但仍尝试抓取相关信息（可通过 search query 兜底）。
4. **检查 cache 是否已有当日产出**：
   - 日报：`cache/{YYYY-MM-DD}/report.json` 存在 → 询问用户是否覆盖
   - 周报：`cache/weekly/{YYYY-W{nn}}/report.json` 存在 → 询问用户是否覆盖
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
     - `websearch_scoped` → AI 代理使用自身搜索能力执行 query，对每个 query 替换 `{date}` / `{yesterday}` / `{iso_week}` 占位符
     - `websearch_broad` → 同 scoped，但检索范围更宽

   - **「成功」判定**（这一步至关重要，否则会掉进伪成功陷阱）
     - HTTP 200 + 页面体感为真实内容（含可读文本，非纯 CSS / 空骨架 / 登录墙）
     - 窗口内 0 条目（empty_in_window）属于**合法成功**，**不**继续下层
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
   - **整链成功但窗口内 0 条目** → 同时进 `fetch_status.succeeded` 和 `fetch_status.empty`

   - **对 `general_agent_search_queries`** 仍然由 AI 代理单独执行搜索，命中的条目按 `via_broad_search: true` 处理。

   - **HN / GitHub Trending 扩大提取范围**
     - Hacker News：提取 **top 50**（而非 top 30）中的 AI/agent/LLM 相关故事
     - GitHub Trending：除 `since=daily` 外，额外抓取 `since=weekly` 作为兜底源，捕捉持续上升但单日增长不突出的项目
     - 高信号媒体发现面：除白名单媒体逐源首轮外，还应单独维护一组 `high_signal_media_queries`，用于把弱信号候选抬进 `candidate_ledger`，后续再由 AI 决定是进正文、进观察区/`unverified`，还是丢弃
     - **召回探针必须执行**：除逐源白名单、`general_agent_search_queries`、`high_signal_media_queries` 外，日报还必须执行 `recall_probe_queries`，并把结果写入 `fetch_status.source_details["High-Recall Product/Adoption Probes"].attempts[]`。
     - `recall_probe_queries` 不是固定正文规则，只是独立召回面。命中的候选仍由 AI 基于窗口、证据路径、产品相关性和团队可行动性决定进入正文、观察区、`unverified` 或拒绝。
     - 对 Cursor / Zed / IDE 平台化类信号，不要只看 changelog；官方 blog、release post、SDK 公告和 Agent Client Protocol 一类入口都属于 coding/general agent 候选面。
     - 对 DeepSeek / Qwen / Kimi 等中文头部模型，若官方 API update 为空但主流媒体给出明确日期和产品事实，应进入 `candidate_ledger`，再按 `media_plus_official_one_hop` 或 `media_only` 降级，不要直接在首层空结果后判定“无内容”。
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

3b. **重大事件深度与事件追踪（major_event）**

   - **判定**：见编辑原则。`major_event: true` 只能标在 `editorial_tier: core` 的条目上。
   - **当天深度补证（2-3 跳）**：对重大事件，证据扩展从常规 1 跳放宽到 2-3 跳，目标面优先：model card / system card / 官方 benchmark 页 / pricing 页 / developer docs / 可用区与配额说明。每次尝试照常写入 `fetch_status.source_details`。
   - **撰写 `expanded` 块**（schema `$defs/expandedBlock`，挂在条目上）：
     - `what_shipped`（50-400 字，必填）：发布要点
     - `benchmarks`（≤400 字，可选）：官方 benchmark 摘录，只写官方给出的数字
     - `pricing_availability`（≤300 字，可选）：定价、配额、可用区
     - `comparison`（≤300 字，可选）：与现役模型/版本对比
     - `third_party_reaction`（≤300 字，可选）：已抓到证据的第三方反应，禁止臆测
     - `open_questions`（1-5 条，必填）：待验证问题清单，将转入事件追踪
   - **开追踪档案**：写 `cache/tracking/{event_slug}.json`（schema `schemas/event_tracking.schema.json`）。`event_slug` 用小写连字符（如 `claude-fable-5`），`expires_on` 距 `opened_date` 不超过 5 天，`watch_items` 直接继承 `open_questions`。条目同时写 `tracking_ref: {event_slug}`；finalize 会校验 `major_event` 条目必须有 expanded + tracking_ref，且 tracking_ref 能解析到活跃档案。
   - **追踪期内的后续日报**：`discovery_manifest.json` 的 `active_tracking` 会列出活跃追踪事件。对每个活跃事件至少执行一轮定向搜索（第三方评测 / 实测反馈 / 价格与配额变化）。命中的增量条目：
     - 豁免 3-1 跨日去重（见该节例外 2），headline 必须体现增量（如「Fable 5 第三方评测首批出炉」）
     - 条目带 `tracking_ref`，并把 `{date, headline, ref}` 追加进追踪档案的 `updates[]`
     - 没有增量就不写条目，不为追踪而凑数
   - **关闭**：`expires_on` 过后档案自动失效；finalize 会清理过期超过 7 天的档案。追踪档案的 `updates[]` 是周报回顾该事件的现成素材。

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

4. **产出 coding_agents 深度观察**
   - 从 coding_agents.items 中挑最值得关注的 1 条
   - 写 150-250 字中文分析，填入 `deep_dive.body`
   - **安静日放宽**：当 frontier_models + coding_agents + general_agents 总条目 ≤ 4 时，deep_dive 字数上限放宽到 **150-400 字**，允许更深入的趋势分析和背景解读
   - 若当日无 coding_agents 进展：仍写一段观察（可围绕"本周无新动作，建议保持观察"或近期延续话题）

5. **抓取并解析硬数据（market_signals）**
   - 对 `whitelist.yaml > hard_data` 4 个源走标准 fetch_chain（LMArena / Artificial Analysis / OpenRouter / HuggingFace Trending）
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
   - 空时 `items: []` + `empty_message: "今日无明显行动项，延续近期建议。"`

9. **产出结构化 JSON**
   - 严格遵循 `schemas/daily_report.schema.json`
   - 字段约束：`version: "1.0"`、`type: "daily"`、`date`、`window`（带时区）、`generated_at`、**十个 `sections`**（frontier_models / coding_agents / general_agents / agent_ecosystem / market_signals / pattern_observations / experiments_this_week / decision_radar / action_items / unverified）、`fetch_status`
   - **每条正文章目必须填 `release_stage` / `published_at_confidence` / `authority_score` / `editorial_tier`**（schema required，缺失会被 render 阶段拒绝）
   - **`fetch_status.source_details`** 必须记录所有走过 fetch_chain 的源（含降级路径），渲染层会展示降级路径供巡检
   - **来源闭环要求**：进入正文（前三节 + market_signals）的每条信息，都必须能回溯到某次具体抓取尝试；若无法在 `fetch_status.source_details` 中解释它是怎么来的，要么补记该尝试，要么降到 `unverified`，不要保留“正文比日志更聪明”的状态
   - **候选台账要求**：除 `report.json` 外，还要落一份 `cache/{date}/candidate_ledger.json`
     - 每条候选至少记录：`candidate_id` / `headline` / `proposed_section` / `published_at` / `source_attempt_refs` / `verification_state` / `editorial_tier` / `decision` / `decision_reason` / `novelty_vs_yesterday`
     - 每条候选还必须记录 `event_type`、`date_basis`、`evidence_path`、`why_today`、`action_eligibility`。
     - `page_updated_at` 不能单独作为 `selected_core` 或 `selected_watch` 的日期依据；Help Center / release notes / changelog / docs 页面必须优先取小节日期、release metadata 或正文明确事件日期。
     - `media_only`、`community_snapshot`、`search_only` 与 `selected_unverified` 不能驱动 action；`media_plus_official_one_hop` 只能驱动 monitor / experiment。
     - `candidate_ledger.json` 只用于审计与复盘，不参与 HTML 正文渲染
   - **落盘前编辑自检**：至少再问自己 3 个问题
     1. 今天是否有高信号官方更新被首轮静默掩盖？
     2. 是否把榜单快照或静态排名误写成“变化”？
     3. 每条 action item 是否都能回指正文中的事实，而不是只来自感觉？
   - 落盘：`cache/{date}/report.json`
   - 助手必须自检 JSON 结构，字段不完整时自行补齐后再写入

9a. **Runner 收尾（默认入口）**
    - Run: `python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date {date} --env .env`
    - dry-run: `python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date {date} --env .env --dry-run`
    - 作用：再次校验邮件环境变量，检查 `fetch_status` 覆盖、`candidate_ledger.json` 与正文对齐、`action_items.references[]` 只能引用 `core/watch` 正文条目；通过后再顺序执行渲染、归档、发送邮件。
    - 若发送失败：必须保留 `cache/{date}/report.json`、`cache/{date}/candidate_ledger.json`、`cache/{date}/report.html` 与 `cache/{date}/run.log`，并返回明确错误。

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

      三a、Agent 生态与实践
        · {item 1 title}（{item_type 中文标签}）
        ...（最多 2 条）

      四、硬数据信号
        {若有 benchmark/pricing/gap 各取 1 条；空则显示 empty_message}

      五、跨条目模式
        {若有 pattern observation 显示 theme；空则显示 empty_message}

      六、本期建议实验
        {若有显示 title；空则显示 empty_message}

      六a、决策雷达
        {每个有内容的决策一行：decision_name: N 条影响；空则显示 empty_message}

      七、今日落地建议
        {全部逐条打印}（若为空则显示 empty_message）

      抓取状态：{succeeded 数} 成功 / {failed 数} 失败 / {empty 数} 无内容

      HTML 已归档：
         {绝对路径}
      {邮件已发送/Dry-run 未发送}：{RECIPIENT_EMAIL}
      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
      ```

14. **运行日志收尾**
    - 在 `cache/{date}/run.log` 追加 `END daily status=ok`

## 周报工作流

**目标周**：运行当日所在的 ISO 周（`2026-W15` 格式）
**采集窗口**：本周一 00:00 ~ 本周日 23:59:59（北京时间）
**运行节奏**：每周一上午运行上一 ISO 周的周报（例如周一为 2026-06-15 时，iso_week = 2026-W24）。`cache/tracking/` 中本周活跃过的追踪档案（含 `updates[]`）是周报回顾重大事件的现成素材，读入后随日报 JSON 一起聚合。

步骤：

1. **检查日报齐全**
   - 以 `cache/{date}/report.json` 为准检查本周 7 个日期是否齐全；`reports/daily/*.html` 只作为成品展示，不作为周报聚合的 source of truth
   - 对每个缺失日期：**独立走一次"日报工作流步骤 1-6"** 补齐（包括抓取、归类、产出 JSON 与 HTML），并把该日期加入 `source_days.backfilled`

2. **读入 7 份日报 JSON**
   - 从 `cache/{date}/report.json` 读入每天的结构化数据
   - 合并为内存中的"本周事件集合"
   - `source_days.daily_reports_used` 必须完整覆盖该 `iso_week` 的 7 个自然日；`backfilled` 只能是其中子集

3. **聚合 & 去重 & 归纳**
   - 按模型提供方聚合 frontier_models 条目 → `vendor_groups`
   - 按产品聚合 coding agent 条目 → `product_groups`
   - 通用 agent 按现有 schema 划分 `newcomers` 和 `big_lab_moves`；这只用于周报归纳与排版，不代表对象天然更重要
   - 每个 vendor_group / product_group 必须填 `weekly_changes / trend_judgment / implication / references`（三段式观察深度**二/三/四节保持一致**）

3a. **聚合本周硬数据（market_signals）**
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

4. **补充搜索（兜底）**
   - 3-5 条搜索，query 形如 "AI industry week summary 2026-W15"、"top AI agent news this week" 等
   - 对比日报聚合结果，补齐遗漏内容

5. **产出周报 JSON**
   - 严格遵循 `schemas/weekly_report.schema.json`
   - **十章节**：`tldr / frontier_models / coding_agents / general_agents / market_signals / pattern_observations / experiments_this_week / practice_digest / action_items / next_week_signals`
   - TL;DR 3-5 条
   - **落地建议**：3-5 条体系化建议，每条字段与日报 `actionItem` 完全一致：
     - `recommendation` / `rationale` / `recommendation_type` / `effort_person_days{min,max}` / `time_horizon` / `team_size_applicability[]` / `success_metric` / `priority` / `references`
   - `references` 引用本周具体日期的日报条目
   - **多样性硬约束**：items ≥ 3 时 `recommendation_type` 必须出现 ≥3 种
   - 落盘：`cache/weekly/{iso_week}/report.json`

5a. **Runner 收尾（默认入口）**
   - Run: `python skills/ai-daily-report/scripts/report_runner.py finalize-weekly --iso-week {iso_week} --env .env`
   - dry-run: `python skills/ai-daily-report/scripts/report_runner.py finalize-weekly --iso-week {iso_week} --env .env --dry-run`
   - 作用：校验周报 JSON 已落盘，并检查 CLI 传入的 `iso_week` 是否与 payload 一致、`source_days` 是否完整覆盖该周、`cache/{date}/report.json` 是否齐全、weekly `references` 是否能回指日报条目、以及 `itemRef` 是否越界；通过后再顺序执行渲染、归档、发送邮件。若发送失败，保留 `cache/weekly/{iso_week}` 下所有产物与 `run.log`。

6. **渲染 HTML（调试/单步重跑）**
   - Run: `python skills/ai-daily-report/scripts/render_html.py cache/weekly/{iso_week}/report.json`

7. **归档（调试/单步重跑）**
   - Run: `python skills/ai-daily-report/scripts/archive.py cache/weekly/{iso_week}/report.html --type weekly --date {iso_week}`
   - 清理 cache 时只删除过期的叶子目录；周报会按 `cache/weekly/{iso_week}` 粒度清理，不会误删 `cache/weekly/` 根目录

8. **发送邮件（调试/单步重跑）**
   - Run: `python skills/ai-daily-report/scripts/send_mail.py reports/weekly/{iso_week}.html --subject "AI 周报 · {iso_week}"`
   - 退出码与异常处理同日报步骤 12
   - 若 dry-run 模式：**跳过此步**，在 run.log 写 `EMAIL skipped (dry-run)`

9. **终端简版**
   - 结构同日报简版，章节名改为周报十章节，TL;DR 全部显示，落地建议全部显示

10. **运行日志**：`cache/weekly/{iso_week}/run.log` 追加 `END weekly status=ok`

## 时效性判断规则

- 日报：仅保留 `published_at` 严格落在 `window.start`（昨日 07:00）到 `window.end`（当前运行时刻）之间的条目（由 Step 3-0 窗口硬卡强制执行）
- 无法确定发布时间的条目：若"首次被权威源提及"在窗口内，则保留（`published_at_confidence: inferred`，`confidence` 不得高于 `medium`）
- 明显窗口外的内容：直接丢弃，**即使内容看起来重要或"接近"窗口也不例外**
- 已被前一天日报覆盖的条目：由 Step 3-1 跨日去重处理，除非有实质性状态变更
- 涉及版本号的条目：由 Step 3a 当前状态校验确认是否为最新版本
- 周报：同理，窗口为本周一 00:00 ~ 本周日 23:59:59

## 归类规则

- **frontier_models**：纯模型能力（新模型发布、benchmark、开源权重、API 定价等）。不含产品化的 coding agent、通用 agent。
- **coding_agents**：明确面向写代码的产品。**不包括**只是"某 AI 助手支持写代码"的通用产品（那些进 general_agents）。
- **general_agents**：通用 agent、browser agent、computer use、工作流 agent、企业 agent 等。不限厂商。
- **unverified**：观察区 / 待核实区。可包含非权威源消息、单一媒体信息、早期爆料，也可包含“官方痕迹存在但信息过薄”的信号；共同点是它们都不应直接驱动正文强结论与行动建议。
- **落地建议**：仅从 frontier_models / coding_agents / general_agents 推导。`unverified` 里的内容**不作为**建议依据。
- **agent_ecosystem**：生态与实践信号（热门仓库、skills/插件、实践案例、工具发布）。不是新闻，准入窗口放宽到 7 天首见；不作为 action_items 依据。
- **decision_radar**：编辑结论层，只引用当日 core/watch 正文条目，按 profile.yaml 在途决策分组。

## 异常处理

- **单源 fetch_chain 整链失败**：所有层都失败 → 记入 `fetch_status.failed`，继续。被任一层兜底成功不算失败。
- **核心源阈值**：`core_sources`（8 个，含 2 家 CN）整链失败数 ≥4 → 中止任务、不发邮件、不归档（仅保留 cache 里的 run.log 供排查）
- **空结果**：某源 fetch_chain 成功但窗口内无 AI 相关条目 → 同时进 `succeeded` 与 `empty`，**不**穿透下层
- **伪成功（CSS only / 登录墙 / JS shell）**：视为该层 error，立即进入下一层
- **render_html.py 失败**：若退出码 1 → Claude 自检 JSON 格式（特别是新增 required 字段 `release_stage` / `published_at_confidence` / `authority_score` / `editorial_tier`，以及 `action_items.references[]` 的 `section` / `editorial_tier`）补齐后重试一次；仍失败则中止并报错
- **archive.py 失败**：停止流程，但保留 cache HTML 供用户手动取用
- **finalize-weekly 校验失败**：若缺日报 JSON、`source_days` 不完整、引用无法回指或 `itemRef` 越界 → 停止流程，不归档不发信，先修正 JSON / 日报缓存
- **send_mail.py 失败**：HTML 已归档 → 报告失败但不回滚归档。退出码 2（认证失败）→ 提示用户重新生成 Gmail 应用专用密码并更新 `.env`；退出码 3（网络/SMTP 错误）→ 建议稍后重跑 `send_mail.py` 单步重试
- **追踪档案损坏**：`cache/tracking/` 下存在无法解析或不符合 schema 的档案 → finalize 校验失败（错误信息会点名该文件）。修复或删除该档案后重跑；过期超过 7 天的档案由 finalize 自动清理。

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
| `expanded.what_shipped` | 50-400 字（仅 major_event 条目） |
| `expanded.open_questions` | 1-5 条，每条 ≤ 120 字 |
| `major_event` 条目 | 仅 core；每日 0-2 条；必须同时有 `expanded` 与 `tracking_ref` |
| `decision_radar` impact | ≤ 120 字，每决策 ≤ 4 条 |
| `agent_ecosystem` items | 0-4 条/天；trending_repo 30 天冷却；relevance ≤ 80 字 |
| `experiments_this_week.items[].audience` | team_pilot / personal_workflow；周报尽量两种各 ≥1 |
| `practice_digest.items[].summary` | 200-400 字（schema 兜底 120-600） |
| `practice_digest.items[]` | 0-2 篇/周；origin 必须回指本周某日日报 agent_ecosystem 条目 |

## 终端输出格式

见日报步骤 10、周报步骤 9。
