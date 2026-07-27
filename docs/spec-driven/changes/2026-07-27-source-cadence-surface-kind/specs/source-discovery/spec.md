## 目的
信源采集面的调度与空判定纪律:用确定性的命中统计与逐层面性标注,控制日报采集成本并消除「空判定靠体感」的漂移。

## 新增需求

### 需求: 信源面命中统计台账
`finalize-daily` 在制品校验通过后必须把当日各信源面的探测结果写入 `cache/source_stats.json`(结构:按日期 → 面名 → `{attempts, hit}`);`hit` 必须按「该面 ∈ `fetch_status.succeeded` 且 ∉ `fetch_status.empty`」确定性判定;写入必须按日期键幂等,且应当在写入时修剪超过 45 天的条目。dry-run 同样必须写入(统计对象是采集事实,不是投递结果)。

#### 场景: 重跑 finalize 不重复计数
- **当** 同一日期的 `finalize-daily` 重复执行
- **则** 该日期在台账中的条目被整体覆盖,不产生重复或累加

#### 场景: 台账损坏不阻塞日报
- **当** `source_stats.json` 无法解析
- **则** 视为空台账继续运行,全部面回退每日探查,禁止因此阻塞 finalize

### 需求: 采集节奏分层调度
`init-daily` 必须依据台账近 30 天数据为每个信源面计算 `cadence`(`daily` / `every_2_days` / `weekly`)与当日 `due`,写入 `discovery_manifest.json`(`required_sources[i].cadence/.due/.last_probed` 与顶层 `cadence_summary`),并在 run.log 记录 `CADENCE due=N skipped=M`。分档规则:近 30 天命中日数 ≥3 为 `daily`,1-2 为 `every_2_days`,0 且实探日 ≥10 且台账首见 ≥14 天为 `weekly`;统计不足的面必须回退 `daily`。以下豁免面必须恒为 `daily`:`core_sources` 成员、`authority_tier == 1` 的源、`category == hard_data` 的源、whitelist 标 `cadence: daily` pin 的源、以及聚合探针/搜索/source_family/tracking 面;其中 interview 与 methodology 两个发现面应当固定为 `every_2_days`。非 due 面允许 AI 因外部信号唤醒探测,唤醒的 attempts 应当记录 `wakeup_reason`;禁止把 cadence 用于正文取舍或排序判断。

#### 场景: 长尾零命中面降为每周
- **当** 某非豁免源近 30 天命中 0 次、实探日 ≥10、台账首见 ≥14 天,且距最近一次实探不足 7 天
- **则** 该面 `cadence=weekly` 且 `due=false`,当日不要求探测

#### 场景: 新源保持每日
- **当** 某源在台账中首见不足 14 天
- **则** 该面 `cadence=daily`,不因零命中降频

### 需求: 覆盖校验以 due 面为基准
`finalize-daily` 的 fetch_status 覆盖校验必须以当日 `discovery_manifest.json` 中 `due=true` 的面为基准:due 面缺席 `source_details` 必须报错;非 due 面缺席禁止报错;非 due 面出现(唤醒)必须被接受且不产生告警。当日 manifest 缺失或不含 cadence 字段时,应当回退 whitelist 全量基准(向后兼容)。

#### 场景: 降频面缺席不报错
- **当** 某面当日 `due=false` 且未出现在 `fetch_status.source_details`
- **则** 覆盖校验通过,该缺席不进入错误清单

### 需求: fetch_chain 逐层 surface_kind 标注
whitelist 中每个 `webfetch` 层必须标注 `surface_kind: feed | static`(`github_releases` 层缺省视为 feed;websearch 层不标注);未标注的 `webfetch` 层应当按 `static` 处理。空结果语义按层判定:final 层为 `feed` 时,窗口内空必须视为合法成功,禁止据此强制下穿;final 层为 `static` 时,`cn_labs` / `hard_data` 源必须下穿搜索层后才能判空,未下穿即 finalize 阻塞(阻塞范围禁止扩大到其他类别)。`cn_labs` / `hard_data` 另需满足**链内穷尽**:停在 `feed` 层且空时,只要该链里还有未触达的抓取面(`webfetch` / `github_releases`),同样必须继续下穿,否则 finalize 阻塞——单个 feed 面只覆盖该源的一部分发布口径(API changelog 不覆盖 HF 权重发布)。判定「走到哪一层」必须依据 `attempts[]` 中真实出现过的最大 `layer_index`,禁止采信自报的 `final_layer_index`。源级 `empty_is_conclusive` 字段退役,代码禁止再读取。测试必须强制全部 `webfetch` 层标注齐全。

#### 场景: 链尾 feed 面空即合法
- **当** cn_labs 某源走完链内全部抓取面、最后停在 `surface_kind: feed` 的层且窗口内 0 条目、无搜索层 attempt
- **则** 召回守门不产生阻塞性 finding,该源同时进入 `succeeded` 与 `empty`

#### 场景: 链内还有抓取面时 feed 空不算数
- **当** cn_labs 某源停在中间的 `feed` 层且空,链里仍有未触达的 `webfetch` / `github_releases` 面
- **则** 召回守门产生阻塞性 finding;走完全部抓取面后再判空才通过

#### 场景: 自报层号不能替代留痕
- **当** 某源 `attempts[]` 只记录了 Layer-0,却把 `final_layer_index` 写成链尾层号
- **则** 判定按 attempts 实迹取 Layer-0,该源仍被判为未穷尽并阻塞

#### 场景: static 面空未下穿仍阻塞
- **当** cn_labs 某源 final attempt 停在 `surface_kind: static`(或未标注)的层且空、无搜索层 attempt
- **则** 召回守门产生阻塞性 finding,finalize-daily 失败并点名该源

### 需求: AI HOT 结构化 API 采集面
AI HOT 源的 fetch_chain 必须以两个结构化 API 层开头:Layer-0 `mode=selected&window=24h&limit=50` 标 `surface_kind: static`(策展池空只说明未放行,不代表无新闻,必须下穿),Layer-1 `mode=all&window=24h&limit=50` 标 `surface_kind: feed`;并保留 websearch_scoped 兜底层。响应 `page` 为 null 时必须按该层 error 处理并继续下穿,禁止记为 empty(非法参数会返回 HTTP 400 + 空 items,静默读成 empty 即漏采);该源必须标 `cadence: daily` pin 保持每日探查。来自该面的候选必须按既有 media 降档规则处理(tier 2 聚合面;`media_only` 禁止驱动 action_items),一跳官方补证应当优先使用条目自带的 `links.original`;条目 `publishedAt` 为空时应当回退 `discoveredAt` 并按 `published_at_confidence: inferred` 处理。

#### 场景: API 失效走兜底
- **当** aihot API 请求失败或返回不可解析内容
- **则** 该层按 error 处理,fetch_chain 继续下穿 websearch_scoped,不因单层失败判定源失败

## Technical Notes

- 现状锚点(均已读码核实,verified: 是):`discovery.missing_fetch_status_coverage`(discovery.py:424,现以 whitelist 全量为基准)、`editorial.validate_fetch_status_integrity`(editorial.py:169)、`editorial.recall_fallback_findings`(editorial.py:994,现按源级 `empty_is_conclusive` + category 判定)、`report_runner.run_daily_init` / `run_daily_finalize`(report_runner.py:96/204)、`discovery.build_discovery_manifest`(discovery.py:360)。
- `cache/source_stats.json` 持久化惯例同 `cache/seen_repos.json`(cache 根文件,不受 `archive.cleanup_cache` 14 天日目录清理影响)。
- 与 seen-ledger 语义区分:seen-ledger 发送成功才写(管读者可见性冷却);source_stats 校验通过即写、dry-run 也写(管采集调度)。
- AI HOT API 契约:响应 `{schemaVersion, query, items[], page}`;item 必有 `id/title/source.name/links.aihot/links.original/discoveredAt/selected`,`publishedAt/summary/category/score` 键恒在但值可 null,展示/归因前必须判空。来源: aihot skill `references/api.md` + 2026-07-27 实测 curl(verified: 是)。
- 层定位机器规则:守门时由 attempt 的 `layer_index` 回查 whitelist 对应链取 `surface_kind`;attempts 已记录 `layer_index`(discovery.py `_blank_source_detail` 与 SKILL.md 步骤 1 契约)。
- 实施细节、分档参数来历与风险缓解见 `../../design.md`(关键决策 1-9、风险与权衡)。

## 实施与验证
- [x] 台账与 source-stats 子命令:finalize 写入/幂等/修剪/损坏 fail-open(tdd)
- [x] cadence 计算与 manifest 字段:三档/豁免/新源保护/due 差值判定(tdd)
- [x] 覆盖校验 due 基准 + manifest 缺失回退(tdd)
- [x] surface_kind 标注 65 条链 + 标注齐全性测试 + 守门判据层级化(tdd)
- [x] AI HOT 链替换 + SKILL.md/AGENTS.md 口径修订 + 全量回归(`python3 -m pytest tests -q`)
