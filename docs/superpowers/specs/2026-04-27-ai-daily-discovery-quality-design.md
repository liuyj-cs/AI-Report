# AI 日报 Discovery Quality 改进设计

## 背景

2026-04-27 的 CodexTool 日报与 ClaudeCode 日报对比暴露出两类相反的问题：

- CodexTool 侧结构更可靠，`candidate_ledger.json`、`qa_diff.json`、`source_details` 和 schema 校验完整，但召回偏窄，漏掉了 OpenAI-Microsoft 官方合作更新这类当天高信号事件。
- ClaudeCode 侧覆盖更广，行业叙事更像日报，但日期归因、hard-data 分层、action reference 和 schema 闭环不够稳。

本设计采用“方案 B”：补强 discovery 面、候选台账、日期归因和 hard-data 语义校验，同时保持项目既有边界：AI 代理负责搜索与编辑判断，仓库脚本只做确定性 manifest、校验、渲染、归档和发送。

## 目标

1. 让 OpenAI-Microsoft 合作、Meta-Manus/NDRC、Dirac benchmark、GitHub Trending Skills 这类高信号候选进入审计面，即使最终不进正文。
2. 防止“页面更新时间”被误当成“事件发布时间”，尤其是 Help Center、release notes、changelog、动态文档页。
3. 区分 hard-data 的真实变化、当天快照和解释性判断，避免把静态榜单快照写成“今天发生变化”。
4. 保持正文取舍由 AI 判断，但让 finalize 能挡住结构性证据缺口、悬空引用和明显错误分层。
5. 让后续日报问题复盘优先看 `candidate_ledger.json`、`fetch_status.source_details`、`qa_diff.json` 和 `run.log`，而不是只看 HTML。

## 非目标

- 不引入搜索 provider、Tavily、专用 API key、本地搜索后端或自动新闻抓取服务。
- 不让脚本自动生成日报正文、排序新闻、给候选打固定分数或固定 Top N。
- 不放松北京时间窗口硬卡。
- 不让 `unverified` 或纯媒体单源传闻驱动高强度 action。
- 不重写现有 runner；本轮只在既有 skill、schema、校验和测试结构上加固。

## 设计原则

### 1. 宽召回，严收口

首轮仍以 `whitelist.yaml` 为起点，但当日报显著偏窄，或出现高信号媒体/社区提示时，AI 必须沿同一实体做一跳补证。补证目标优先为官方公告、官方博客、changelog、release metadata、监管/合作方官方页面、一级媒体原文。

宽召回只影响候选池，不自动影响正文排序。正文仍由 AI 基于窗口、证据强度、事件影响面、用户关注度和可执行性收口。

### 2. 候选台账是审计面，不是正文草稿

`candidate_ledger.json` 必须记录高信号候选的最终命运。一个候选可以是 `selected_core`、`selected_watch`、`selected_unverified`、`rejected_window`、`rejected_duplicate`、`rejected_weak_evidence` 或 `rejected_not_ai`。HTML 没出现不等于候选不存在。

### 3. 日期归因先于章节归类

每条候选必须先回答“为什么是今天”，再决定是否进正文。动态页面的 `updated_at` 只能说明页面被编辑过，不能单独证明页面内所有条目都发生在当天。

### 4. Hard data 分三层

`benchmark_changes` 记录有前后基线的真实变化；`benchmark_watch` 记录新评分、新上榜、当天快照或缺基线观察；`capability_gaps` 只做解释，必须引用正文或 hard-data 证据。

## Discovery 改进

### 高信号官方与公司动作覆盖

`whitelist.yaml` 和 `SKILL.md` 需要明确：OpenAI、Anthropic、Google、Microsoft、Meta、DeepMind 等源不只关注模型发布，也要覆盖：

- partnership / alliance / acquisition / investment
- cloud / infrastructure / distribution / data residency
- enterprise / business / workspace / admin
- pricing / billing / API availability
- compliance / regulation / policy
- benchmark / leaderboard / evaluation

OpenAI 类源尤其要避免只查 `news/product/model`。当 `openai.com/news` 或类似入口出现 403、JS shell、Cloudflare 或空壳时，AI 应继续查同域 `index`、RSS、sitemap、产品页、合作方公告或一级媒体原文，并在 `source_details` 中记录每次尝试。

### 高信号媒体与社区发现面

`High-Signal Media Discovery` 不应只收新品发布，还要覆盖工程化、组织、商业与监管信号。命中后处理规则：

- 有官方/一级一跳补证：可进入正文前三节作为 `watch`，保持 `confidence=medium` 或相应降级痕迹。
- 只有媒体原文且事实链清楚：进入 `unverified` 或 `selected_watch` 的轻量观察，但 action 只能是 `monitor / experiment`。
- 只有趋势页、HN、GitHub Trending 等易变页面：必须保留快照证据或在 ledger 中标明 `community_snapshot`，否则不能写具体 star delta 或“今天登顶”。

### Discovery surface 完整性

`fetch_status.source_details` 仍需覆盖 required discovery names。新增或强化的 surface 缺失时，finalize 应报 `missed_discovery` 或 validation error，而不是静默生成窄日报。

## Candidate Ledger 契约

在现有字段基础上，候选台账增加这些审计字段：

- `event_type`: `model_release` / `coding_release` / `partnership` / `pricing` / `benchmark` / `compliance` / `community_signal` / `enterprise_update` / `research_update`
- `date_basis`: `official_event_date` / `release_metadata` / `section_date` / `article_published_at` / `page_updated_at` / `community_snapshot_time` / `inferred_from_search`
- `evidence_path`: `primary` / `media_plus_official_one_hop` / `media_only` / `community_snapshot` / `search_only`
- `why_today`: 一句话解释窗口归因。
- `action_eligibility`: `none` / `monitor` / `experiment` / `full_action`

约束：

- `source_attempt_refs` 必须能解析回 `fetch_status.source_details[source].attempts[index]`。
- `selected_core` 通常要求 `evidence_path=primary`，且 `date_basis` 不能只依赖 `page_updated_at`。
- `selected_watch` 可接受 `media_plus_official_one_hop` 或 `community_snapshot`，但必须降级 confidence 或保留 `via_broad_search`。
- `selected_unverified` 可接受 `media_only` 或 `search_only`，但不能驱动 action。
- `rejected_window` 必须说明被拒绝的具体 `published_at` 和窗口边界关系。

## 日期归因校验

### 规则

1. `official_event_date`、`release_metadata`、`section_date`、`article_published_at` 可作为窗口判断依据。
2. `page_updated_at` 不能单独支撑 `selected_core` 或 `selected_watch`。
3. Help Center、release notes、changelog、docs 类页面必须优先取页面内小节日期或 release metadata。
4. 如果页面小节日期在窗口外，即使页面整体在窗口内更新，也应 `rejected_window`，除非正文明确说明该小节当天有状态变化。
5. `published_at_confidence=inferred` 的候选最多进入 `watch` 或 `unverified`，不得作为核心发布。

### 2026-04-27 回归样例

- ChatGPT Business 日本数据本地化：若页面小节日期是 2026-04-22，应在 2026-04-27 日报中被窗口拒绝。
- OpenAI-Microsoft 合作更新：若官方页面日期是 2026-04-27，应进入候选池，并允许作为 `frontier_models` 或 business/infrastructure 相关 `watch/core` 正文项。

## Hard Data 契约

### `benchmark_changes`

用于真实变化，必须具备前后基线：

- old value / new value
- change pct 或 rank delta
- observed_at
- source
- 可选 ref

没有前后基线时不能写“上升、下降、扩大领先、超越、降价”等变化性措辞。

### `benchmark_watch`

用于当天观察信号：

- 新评分
- 新上榜
- 当前快照
- 缺少稳定前一日基线的榜单观察

必须保留 `vendor`、`model`、`source`、`signal`、`observed_at`，可选 `ref` 指向正文条目。

### `capability_gaps`

只做解释层，不能承载孤立事实。每条 capability gap 若涉及 benchmark、leaderboard、score、pricing，应满足至少一个条件：

- 引用 `benchmark_changes` / `benchmark_watch` / `pricing_changes`
- 引用正文 `frontier_models[i]`、`coding_agents[i]`、`general_agents[i]`
- 在正文条目上有显式 `hard_data_note` 说明为什么不进入 hard-data bucket

### 2026-04-27 回归样例

- Dirac 65.2% Terminal-Bench-2：没有当天 leaderboard 变化证据时，不能写成“今日登顶”；可作为 `benchmark_watch` 或 coding watch，并在 ledger 写清日期依据。
- LMArena 前 4 都是 Claude：如果只有当天快照，进入 `benchmark_watch`；`capability_gaps` 只能引用该 watch 做解释。
- DeepSeek V4 Pro 价格折扣：有旧价、新价和观察时间，可进入 `pricing_changes`。

## Action Items 约束

Action item 必须回指 `frontier_models`、`coding_agents`、`general_agents` 中的 `core/watch` 条目，并带 `section` 与 `editorial_tier`。

允许关系：

- `primary + core`: 可驱动 `monitor`、`experiment`、`adopt`、`migrate` 等完整 action，仍需控制人日和风险。
- `media_plus_official_one_hop + watch`: 只能驱动 `monitor` 或 `experiment`。
- `media_only`、`community_snapshot`、`search_only`、`unverified`: 不驱动 action。

## 数据流

1. `init-daily` 生成 `discovery_manifest.json`，列出必做 discovery surface、source family 和 fallback targets。
2. AI 根据 manifest 完成抓取、补证、窗口硬卡和候选池整理。
3. AI 写入 `report.json` 和 `candidate_ledger.json`。
4. `finalize-daily --dry-run` 生成 `qa_diff.json`，执行 schema、ledger alignment、source closure、date attribution、hard-data consistency 和 action reference 校验。
5. dry-run 通过后再正式 finalize 和发送。

## 错误处理

- 缺失 required discovery surface：阻塞或在 QA 中标为高严重度，避免静默窄报。
- `source_attempt_refs` 无法解析：阻塞 finalize。
- `page_updated_at` 作为核心日期依据：阻塞或要求降级为 unverified。
- hard-data 事实直接进入 capability gap 且无 ref：阻塞或要求补 `benchmark_watch` / `pricing_changes`。
- action reference 缺 `section` / `editorial_tier` 或引用 unverified：阻塞 finalize。

## 受影响文件

- `skills/ai-daily-report/SKILL.md`: 更新日报 workflow、日期归因、hard-data 和 action 口径。
- `skills/ai-daily-report/sources/whitelist.yaml`: 补高信号官方/公司动作与媒体发现 query。
- `skills/ai-daily-report/scripts/discovery.py`: discovery manifest 与 required surface 扩展。
- `skills/ai-daily-report/scripts/editorial.py`: 日期归因、hard-data、ledger/action 语义校验。
- `skills/ai-daily-report/schemas/daily_report.schema.json`: 必要时补 hard-data 或可选审计字段。
- `skills/ai-daily-report/schemas/candidate_ledger.schema.json`: 增加 ledger 审计字段。
- `skills/ai-daily-report/templates/daily.html.j2`: 只在新增字段需要展示时小改。
- `skills/ai-daily-report/tests/*`: 增加回归 fixture 和 validator 测试。

## 验收标准

1. `python -m pytest skills/ai-daily-report/tests -q` 通过。
2. 2026-04-27 的 fixture 能证明 OpenAI-Microsoft 合作不会被漏掉。
3. Help Center 小节日期在窗口外时会被窗口拒绝。
4. Dirac benchmark 缺当天变化证据时不会被写成“今日登顶”。
5. hard-data 快照进入 `benchmark_watch`，解释进入 `capability_gaps` 且有 ref。
6. `candidate_ledger.json` 中所有 selected/rejected 高信号候选都有 `why_today`、`date_basis` 和 resolvable `source_attempt_refs`。
7. `finalize-daily --dry-run` 能在错误引用、悬空 source、缺 hard-data ref、错误 page update 日期依据时失败。

## 推进顺序

1. 先更新 spec 对应的测试 fixture，覆盖 2026-04-27 暴露的问题。
2. 再更新 schema 和 deterministic validators。
3. 然后同步 `SKILL.md` 与 `whitelist.yaml`，保证 AI 执行口径和校验口径一致。
4. 最后用 dry-run 验证一份代表性日报，不直接跳到发送。
