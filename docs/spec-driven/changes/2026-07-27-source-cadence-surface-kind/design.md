# 2026-07-27-source-cadence-surface-kind design

## 背景

- intake 参考:`intake.md`(需求概述、追问 1-4 已答复:三档降频 / 豁免名单 / advisory / 硬验收口径,全部采纳推荐)
- 与本设计直接相关的关键约束:
  - AGENTS.md 红线:判断逻辑归 AI,脚本只做确定性工作;whitelist 是首轮覆盖起点不是信息上限;审计面不能过窄。
  - cache 日目录仅保留 14 天(`archive.cleanup_cache`),30 天命中率必须依赖独立持久台账。
  - 现状锚点(均已读码核实):覆盖校验 `discovery.missing_fetch_status_coverage`(discovery.py:424)以 whitelist 全量为基准;召回守门 `editorial.recall_fallback_findings`(editorial.py:994)按「category ∈ (cn_labs, hard_data) 且源级 `empty_is_conclusive` 缺失」判定;`empty_is_conclusive` 在 whitelist.yaml 中只出现于注释,无任何源实际配置。

## 计划输入摘要

- **范围边界**:三项合一——①命中统计台账 + 三档 cadence 调度;②fetch_chain 逐层 `surface_kind: feed|static` 标注并精化召回守门判据;③AI HOT 源 Layer-0 换结构化 API。**不做**:不改编辑判断规则(候选取舍、降档、action 资格),不改邮件/渲染/归档链路,不动周报聚合逻辑,不扩大召回守门的阻塞范围。
- **变更落点**:`scripts/discovery.py`(manifest 增 cadence/due;覆盖校验基准)、`scripts/report_runner.py`(finalize 写台账;init 算 cadence;新调试子命令 `source-stats`)、`scripts/editorial.py`(守门判据 surface_kind 化;覆盖校验对接 manifest)、`sources/whitelist.yaml`(65 条链逐层标注 + AI HOT 链替换 + `cadence` pin 字段)、`SKILL.md` / `AGENTS.md`(empty 判定与调度口径修订)、`tests/`(新增 + 修订)。
- **契约锚点**:spec delta `specs/source-discovery/spec.md` 五条新增需求;AI HOT API 契约见下「接口变更」。
- **强约束**:豁免面恒为 daily(core_sources / tier1 / hard_data / `cadence: daily` pin / 聚合探针面);阻塞性守门范围保持 cn_labs + hard_data 不扩大;manifest 缺失时覆盖校验回退 whitelist 全量(向后兼容)。
- **验证来源**:`cd skills/ai-daily-report && python3 -m pytest tests -q`(context-sources.yaml 登记)。
- **未决项**:无——待决策点已清零(2026-07-27 G-spec 门内裁决,见关键决策 1)。

## 技术方案

数据流(全部确定性,AI 不参与计算,只消费结果):

```
finalize-daily(成功校验后)
  └─ 从 report.json.fetch_status 提取每面 {attempts 数, hit} → 写 cache/source_stats.json(按日幂等,45 天修剪)
init-daily(次日)
  └─ 读 source_stats.json → 逐面算 cadence(daily/every_2_days/weekly)与 due
      → 写入 discovery_manifest.json(required_sources[i].cadence/.due/.last_probed + 顶层 cadence_summary)
      → run.log 记 "CADENCE due=N skipped=M"
AI 执行日报
  └─ 只须跑 due=true 的面;非 due 面可因外部信号唤醒(attempts 记 wakeup_reason)
finalize-daily
  └─ 覆盖校验基准 = 当日 manifest 的 due 面(manifest 缺失回退 whitelist 全量)
  └─ 召回守门:final 层 surface_kind==feed 且空 → 合法;static/未标 且空且无搜索层 attempt → 阻塞(范围仍限 cn_labs/hard_data)
```

1. **统计台账 `cache/source_stats.json`**(cache 根,不受 14 天日目录清理影响,惯例同 `seen_repos.json`):
   - 结构:`{"version":"1.0","days":{"<date>":{"<surface_name>":{"attempts":<int>,"hit":<bool>}}}}`
   - `hit` 定义:该面 ∈ `fetch_status.succeeded` 且 ∉ `fetch_status.empty`(纯确定性,不依赖 ledger 质量;见关键决策 2)
   - 写入时点:finalize-daily 在 `validate_daily_artifacts` 通过后立即写(dry-run 也写——统计的是采集事实,与投递无关);按日期键幂等覆盖;写入时修剪 >45 天条目。
2. **cadence 计算**(init-daily 内,输入=台账近 30 天):
   - 豁免恒 daily:源 name ∈ `core_sources`、`authority_tier == 1`、`category == hard_data`、源带 `cadence: daily` pin(AI HOT 配此 pin)、以及全部非 whitelist 具名面(聚合探针/搜索面/source_families/tracking 面)——interview 与 methodology 两个发现面除外,固定 `every_2_days`。
   - 其余具名源:近 30 天 hit 日数 ≥3 → daily;1-2 → every_2_days;0 且实探日数 ≥10 且台账首见 ≥14 天 → weekly;统计不足(首见 <14 天或实探 <10 日)→ daily。
   - due 判定:`daily` 恒 due;`every_2_days` / `weekly` 按 `target_date - last_probed >= 2 / 7`(last_probed = 台账中该面最近有 attempts 记录的日期;无记录视为 due)。差值法天然错峰,无需全局相位。
3. **覆盖校验对接 manifest**:`missing_fetch_status_coverage` 增加可选 due 名单参数;finalize 读当日 `discovery_manifest.json` 取 due 面名单传入;manifest 不存在或无 cadence 字段(历史缓存)→ 回退 whitelist 全量。非 due 面出现在 source_details(唤醒)不报错、不告警。
4. **surface_kind 逐层标注**:whitelist 每个 `webfetch` 层必须标 `surface_kind: feed | static`(`github_releases` 层缺省视为 feed;websearch 层不标,类型即语义)。标注判据:「页面是每条带日期的倒序列表(news/blog 索引、changelog、release notes、HF `?sort=created`、GitHub `?sort=updated`、结构化 API feed)」→ feed;产品首页/文档/看板/JS 壳 → static。新增测试强制 webfetch 层标注齐全(65 条链一次标完,见待决策点 1 裁决)。
5. **守门判据精化**(`recall_fallback_findings`):从「源 category ∈ 高召回类 且 源级 `empty_is_conclusive` 缺失」改为「源 category ∈ 高召回类 且 final attempt 所在层 `surface_kind != feed` 且空且无搜索层 attempt」→ 阻塞。层定位:attempt 已记录 `layer_index`,回查 whitelist 该链对应层。源级 `empty_is_conclusive` 字段退役(代码不再读取,whitelist 注释同步删除)。DeepSeek `api-docs.deepseek.com/updates` 这类带日期 changelog 标 feed 后,空即合法成功、不再强制下穿。
6. **AI HOT 链替换**(whitelist):

   ```yaml
   - name: AI HOT
     category: chinese_media
     weight: high
     authority_tier: 2
     cadence: daily
     fetch_chain:
       - type: webfetch
         url: https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=50
         surface_kind: feed
       - type: websearch_scoped
         queries:
           - "AI HOT site:aihot.virxact.com {date}"
   ```

   删除首页与 `/all` 两个 webfetch 层。候选处理不变:tier 2 聚合面,`media_only` 不驱动 action、需一跳官方补证(`links.original` 直接支撑一跳)。
7. **SKILL.md / AGENTS.md 修订**:①empty 判定三处(日报步骤 1、异常处理、时效性规则)统一改写为 surface_kind 数据口径,删除「cn_labs/hard_data 按类别默认下穿」一刀切表述(阻塞范围不变,判据改层级);②新增 cadence 小节:due 面必须全跑、非 due 面允许唤醒且 attempts 记 `wakeup_reason`、豁免名单与三档规则一句话说明;③AI HOT API 面的读取说明(JSON 字段:`title/summary/source.name/links.original/publishedAt/discoveredAt`,`publishedAt` 为空回退 `discoveredAt` 并按 inferred 处理);④AGENTS.md 补一句:cadence due 列表是「当日首轮起点」的运维收窄,不改变「白名单是起点不是上限」原则。

### 接口变更

- `report_runner.py source-stats --date <date>`(新增调试/验收子命令,打印近 N 天各面 attempts/hit 汇总与当日 due 预览)— 来源: 本 change 契约产物
- `discovery_manifest.json` 新增字段:`required_sources[i].cadence` / `.due` / `.last_probed`、顶层 `cadence_summary{due,skipped}` — 来源: 本 change 契约产物;现有字段不变(discovery.py:360 `build_discovery_manifest`,verified: 是)
- `cache/source_stats.json`(新文件)结构见技术方案 1 — 来源: 本 change 契约产物
- `whitelist.yaml` 新字段:源级 `cadence: daily`(pin)、层级 `surface_kind: feed|static`;退役:源级 `empty_is_conclusive` — 来源: 本 change 契约产物(现状 verified: 是,该字段仅存在于注释)
- AI HOT v1 API `GET /api/v1/items?mode=selected&window=24h&limit=50`:响应 `{schemaVersion, query, items[], page}`,item 必有 `id/title/source.name/links.aihot/links.original/discoveredAt/selected`,`publishedAt/summary/category/score` 可为 null — 来源: aihot skill `references/api.md`(github.com/KKKKhazix/khazix-skills)+ 2026-07-27 实测 curl 返回一致 (verified: 是)
- `editorial.validate_fetch_status_integrity` / `discovery.missing_fetch_status_coverage` 签名增加可选 due 名单参数(默认 None=whitelist 全量,向后兼容)— 来源: 本 change 契约产物(现状 discovery.py:424 / editorial.py:169,verified: 是)

### 结构化影响面分析

- 来源:`AGENTS.md`(context-sources.yaml `red_lines`)

| 红线条目 | 触发 / 不触发 | 理由 | 人的确认证据 |
|---|---|---|---|
| 判断逻辑归 AI,脚本只做确定性工作 | 不触发 | cadence/统计/守门全是确定性运维计算;是否进正文、候选取舍、降档均不动 | 不适用 |
| 不用固定名单/阈值替代编辑判断 | 不触发 | 三档阈值决定「今天探不探」,不决定「内容进不进正文」;唤醒机制保留 AI 裁量 | 不适用 |
| whitelist 是首轮覆盖起点,不是信息上限 | 触发(收窄首轮) | due 列表把「首轮起点」按命中率运维收窄;经 intake 追问 3 用户裁决为 advisory(可唤醒),AGENTS.md 同步补充说明 | intake 追问 3 已答复:采纳推荐 |
| 审计面不能过窄 | 触发(需补痕) | 非 due 面不再出现在 source_details;补偿:manifest 留 cadence/due/last_probed 全量痕迹 + run.log CADENCE 行,审计面从 report 移到 manifest | intake 追问 3 已答复(finalize 基准改 manifest due 列表) |
| 暴露问题优先修流程而非当日修补 | 不触发 | 本 change 即流程级改进,含验收观察期 | 不适用 |

- 影响的构建产物:无(纯本仓脚本/配置/文档)

### 配置 / 灰度 / 回滚条件

| 配置 key | 用途 / 变更 | 灰度策略 | 回滚方案 | 是否已验证 |
|---|---|---|---|---|
| whitelist 源级 `cadence: daily` | 钉住恒每日探查(AI HOT 首个使用者) | 全量(仅 pin 语义) | 删除该键,回到命中率分档 | 否(dev 阶段测试覆盖) |
| whitelist 层级 `surface_kind` | feed 空即成功 / static 空须下穿 | 全量一次标注(关键决策 1) | 未标注层缺省 static=现状行为;整体回滚删字段即可 | 否(dev 阶段测试强制齐全) |
| `cache/source_stats.json` | 命中统计台账 | 自然积累;统计不足自动回退 daily | 删除文件→全部面回 daily(fail-open) | 否(dev 阶段测试) |
| manifest `cadence/due` 字段 | 当日探查计划 | manifest 缺字段→覆盖校验回退 whitelist 全量 | 同左,天然回滚 | 否(dev 阶段测试) |

## 待决策点

无——1 个决策点已全部裁决,见关键决策 1。

## 关键决策

1. **surface_kind 标注范围:全量 65 条链一次标完(待决策点 1,2026-07-27 用户裁决选 a)**。候选 (a) 全量标注 + 测试强制「webfetch 层必标」守恒;候选 (b) 只标 cn_labs/hard_data/AI HOT,其余缺省 static。用户选 (a):效率收益主要来自 feed 面免下穿,所有类别的 empty 判断都从「体感规则」变为「读数据」;误标风险由「判据成文 + dev 逐条核对 + 验收期 7 天 qa 观察」缓解。(b) 的代价是规则双轨,正是本 change 要消除的状态。
2. **hit 定义 = `succeeded 且非 empty`**(候选:按 candidate_ledger `source_attempt_refs` 判「产生过候选」)。选前者:完全确定性、不依赖 AI 写 ledger 的忠实度;代价是「抓到内容但全被窗口硬卡拒」的面会被记为 hit 而保持 daily——方向性保守(宁多探不漏探),可接受。
3. **weekly 档准入 = 实探日 ≥10 且台账首见 ≥14 天**:调和追问 1 推荐中「已探 ≥10 次」与「新源 14 天内一律每日」两个条件(前者被后者收紧);every_2_days 无需此保护(最坏延迟 1 天)。
4. **覆盖校验基准 = 当日 manifest due 名单,manifest 缺失回退 whitelist 全量**(候选:让 AI 为非 due 面手写 skipped 记录保持 report 全覆盖)。选 manifest 基准:30 个手写 skip 记录是纯噪音且易错;审计痕迹由 manifest 承载。
5. **阻塞性守门范围不扩大**:surface_kind 只精化 cn_labs/hard_data 守门判据,不把阻塞扩展到全部类别(媒体面误报会频繁阻塞发送);其他类别的 surface_kind 是 AI 判断的输入数据,非守门项。
6. **台账写入时点 = finalize 校验通过后、含 dry-run**(候选:独立子命令手跑)。自动写入避免台账断档;dry-run 也写因为统计对象是采集事实而非投递结果;与 seen-ledger「发送成功才写」的语义不同,后者管读者可见性冷却,前者管采集调度。
7. **`empty_is_conclusive` 退役**:surface_kind 是其层级化替代,双轨并存 = 两个真相源(违 AGENTS.md 流程改进精神);代码删读取、注释同步清理。
8. **AI HOT 窗口缺口接受**:API `window=24h` 从运行时刻倒推,对 27.5h 日报窗口存在约 3.5h 边缘缺口;相邻两日查询 + 跨日去重接续覆盖,不为此拉 `window=7d` 引入 7 天噪音(它是召回面,不是唯一面)。
9. **interview/methodology 固定 every_2_days**(不参与命中率分档):慢信号轨道(准入窗 7/14 天),隔日探查零实质损失;固定档比按命中率浮动更可预期(intake 追问 2 用户已裁决允许隔日)。

## 终审后追加的关键决策（2026-07-27，两轮 pre-close review 收敛）

10. **feed 标注必须以实抓为准，不能按 URL 语义推**：首轮标注按 URL 语义判定，终审实抓发现 19 个标 feed 的面在无 JS 环境下渲染不出带日期的列表（MiniMax news / 机器之心 / InfoQ CN / TLDR / 2×YouTube / latent.space / therundown / no-priors / bigtechnology / dwarkesh / importai / microsoft source / deepmind blog / blog.google / github.blog changelog + 2 个 404 死链），复验又追加 Claude Code release-notes（core_source，实为 GitHub JS 壳）。全部改判 static。判据保持不变，变的是取证方式——**后续新增源必须实抓验证再标注**。403/429 的官方面不据此改判（curl 被拦不等于 AI 的 WebFetch 拿不到）。
11. **cn_labs / hard_data 增加「链内穷尽」要求**（相对首版是收紧）：停在中间的 feed 层且空同样阻塞，必须走完链内全部抓取面。理由：单个 feed 面只覆盖该源的一部分发布口径——DeepSeek/智谱的 Layer-0 是 API changelog（覆盖接口变更，不覆盖权重发布），Kimi 的 Layer-0 是 HF 组织页（安静日常空，会让 kimi.com/blog 与 GitHub 面永不可达）。cn_labs 走完抓取面即可判空、不强制搜索层；hard_data 每源只有一个 static 抓取面，实际仍必须跑搜索层。
12. **守门判据只认 attempts 留痕，不认自报 `final_layer_index`**：首版用自报字段判「是否走到链尾」，实测只抓 Layer-0 却自报 2 即可绕过全部保护（attempts 全空同样绕过）。改为取 attempts 中真实出现过的最大 `layer_index`，为空则 fail-closed。这条同时消除了镜像误报（实走到 L2 但字段未更新被误判阻塞）。
13. **due 基准需要下限守卫**：`due` 为空回退全量还不够——同日重跑 `init-daily` 会让绝大多数面变成「今天已探过」，due 塌到个位数，覆盖校验就会对「只抓了两个源」的日报放行。双重修复：`last_probed` 只取严格早于 target 的日期（同日重跑不改变 due），且 due 占比低于 `DUE_BASELINE_MIN_RATIO`(0.25) 时回退全量。
14. **AI HOT 分两层而不是一层**：`mode=selected` 实测只放行约 8% 条目（4 条 vs all 的 50 条），作为「召回对照面」过窄。改为 Layer-0 selected(static，空必须下穿) → Layer-1 all(feed)。另发现**静默空集陷阱**：非法参数（`limit>100`、`window=48h`、未知 `mode`）返回 HTTP 400 但 body 是 `{"items":[],"page":null}`，被 feed 层读成「空即权威」即静默漏采——判别信号是 `page` 为 null，已写入 SKILL.md 纪律。
15. **weekly 档稳定性需要「探测新鲜度」条件**：只放宽样本量会让管线停摆期（本仓有过周报停摆 3 周的记录）的稀疏探测被误读成「按 weekly 节奏在探」。追加「窗口内最后一次探测距今 ≤7 天」才允许走稀疏判据。

## 撤销记录（2026-07-28）

**采集调度（cadence）整体撤销，本 change 只保留 `surface_kind` 与 AI HOT。** 决策依据是两个实测数字：

1. **收益被豁免名单锁死**：74 个发现面里 48 个（65%）属恒 daily 豁免（core_sources / tier1 / hard_data / 聚合探针面），真正有资格降频的只有 24 个（32%）。实测基线 148 attempts/天 → 稳态 118，**降幅 21%**，远低于 intake 承诺的 30-50%。这个上限在 intake 定豁免名单时就已经确定，而当时没有把这笔账算出来（关键决策 3/9 只做了定性权衡）。
2. **返工成本全部集中在这一部分**：PR #5 五轮 review 共 12 条 findings，**100% 落在 cadence 调度上**；`surface_kind` 与 AI HOT 在终审修完 feed 误标后再无 finding。即一套约 333 行、收益 21% 的机制消耗了全部 review 预算。

撤销范围：`scripts/source_stats.py`（整个文件）、`discovery.py` 的 cadence 计算与 manifest 字段、`editorial.py` 的 due 基准与唤醒审计、`report_runner.py` 的台账写入与 `source-stats` 子命令、whitelist 的 `cadence` pin、schema 的 `wakeup_reason`、以及 11 个纯 cadence 测试文件。保留：`surface_kind` 全量标注与召回守门层级化、AI HOT 结构化 API 双层、死链清理、CI。

如果将来重做采集调度，前置条件是**先算清楚豁免名单锁定的收益上限**，再决定值不值得做——那正是这次跳过的一步。

## 风险与权衡

- **误标 feed → 静默漏采**(最高风险):static 面被误标 feed 后空结果不再下穿。缓解:①标注判据单一明确(「每条带日期的倒序列表」);②dev 任务中逐条核对并抽查实页;③验收期 7 天盯 qa_diff `missed_discovery`(intake 追问 4 口径);④AI 在编辑自检中发现外部信号指向某 feed-空面时仍可唤醒下穿(advisory 自由保留)。
- **advisory 模式省不下来**(AI 惯性全探):验收口径(7 日均 attempts ≤70)专门盯此;不达标再议收紧,不在本 change 预设硬禁。
- **aihot 第三方依赖**:API 失效/改契约 → websearch_scoped 兜底层接管,fetch_chain 降级机制天然覆盖;它是召回对照面而非唯一信源,失效不损官方一手覆盖。
- **台账单点**:source_stats.json 损坏 → 按台账惯例视为空台账,全部面回 daily(fail-open,行为=现状),不阻塞日报。
- **每周档最坏延迟 6 天**:仅发生在「近 30 天零命中的长尾面突然发新闻且无任何媒体/探针面交叉覆盖」的组合;探针面与媒体面全部恒 daily,实际兜底延迟通常 ≤1 天(intake 追问 1 用户已接受该权衡)。
