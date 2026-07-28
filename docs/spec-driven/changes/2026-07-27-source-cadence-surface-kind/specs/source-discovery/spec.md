## 目的
信源采集面的调度与空判定纪律:用确定性的命中统计与逐层面性标注,控制日报采集成本并消除「空判定靠体感」的漂移。

## 新增需求

### 需求: 信源面命中统计台账
`finalize-daily` 在制品校验通过后必须把当日各信源面的探测结果写入 `cache/source_stats.json`(结构:按日期 → 面名 → `{attempts, hit}`);台账里每条面记录必须满足 `attempts` 为非负整数且 `hit` 为布尔,不满足即整条丢弃(禁止强制转换)。`hit` 必须按「该面 ∈ `fetch_status.succeeded` 且 ∉ `fetch_status.empty`」确定性判定;写入必须按日期键幂等,且应当在写入时修剪超过 45 天的条目。整个 read→prune→update→write 必须在跨进程文件锁内完成,并以同目录临时文件 + 原子替换落盘(并发 finalize 不得丢日期,写入中断不得留下半个台账)。dry-run 同样必须写入(统计对象是采集事实,不是投递结果)。

#### 场景: 重跑 finalize 不重复计数
- **当** 同一日期的 `finalize-daily` 重复执行
- **则** 该日期在台账中的条目被整体覆盖,不产生重复或累加

#### 场景: 台账损坏不阻塞日报
- **当** `source_stats.json` 无法解析,或解析出的顶层/`days` 不是对象(如合法 JSON `[]`)
- **则** 视为空台账继续运行,全部面回退每日探查,禁止因此抛异常或阻塞 finalize

#### 场景: 局部损坏只丢损坏部分
- **当** 台账某一天的 entry 或某个面的 record 结构非法
- **则** 只丢弃该条,其余历史保留(不得为一条坏数据清空整个调度依据)

#### 场景: 跳过记录不得被当成实探日
- **当** 某面连续多日只有 `attempts: 0` 的跳过记录
- **则** 这些天不计入实探日,该面因统计不足保持 `daily` 且 `due=true`,`last_probed` 不被这些记录推进

#### 场景: 字段损坏的 record 不得被当成零命中探测
- **当** 某面记录的 `attempts` 不是非负整数、或 `hit` 不是布尔(如 `{"attempts":"corrupt","hit":null}`)
- **则** 必须整条丢弃,禁止强制转换后保留——坏数据被读成"探过、没命中"会累积成错误降频依据;
  该面因统计不足回 `daily`

### 需求: 采集节奏分层调度
`init-daily` 必须依据台账近 30 天数据为每个信源面计算 `cadence`(`daily` / `every_2_days` / `weekly`)与当日 `due`,写入 `discovery_manifest.json`(`required_sources[i].cadence/.due/.last_probed` 与顶层 `cadence_summary`),并在 run.log 记录 `CADENCE due=N skipped=M`。分档规则:近 30 天命中日数 ≥3 为 `daily`,1-2 为 `every_2_days`,0 且实探日 ≥10 且台账首见 ≥14 天为 `weekly`;统计不足的面必须回退 `daily`。分档与 `last_probed` 只依据**严格早于目标日期**的记录(当天记录不得参与,否则 `init` 与 `finalize` 的重算结果会不一致、重跑 finalize 自我否定,语义上也是用当天采集结果决定当天是否采集)。**实探日只计 `attempts > 0` 的记录**——`attempts: 0` 表示当天记了一笔但没真去探(面被跳过),它是合法审计留痕,但禁止计入实探日、禁止作为 `last_probed`、也禁止计入 `source-stats` 的 `probed_days` 汇总。以下豁免面必须恒为 `daily`:`core_sources` 成员、`authority_tier == 1` 的源、`category == hard_data` 的源、whitelist 标 `cadence: daily` pin 的源、以及聚合探针/搜索/source_family/tracking 面;其中 interview 与 methodology 两个发现面应当固定为 `every_2_days`。非 due 面允许 AI 因外部信号唤醒探测,唤醒面必须在某次 attempt 上记录非空 `wakeup_reason`,缺失即 finalize 失败(唤醒本身合法,但越过调度计划的依据必须可审计);禁止把 cadence 用于正文取舍或排序判断。

#### 场景: 长尾零命中面降为每周
- **当** 某非豁免源近 30 天命中 0 次、实探日 ≥10、台账首见 ≥14 天,且距最近一次实探不足 7 天
- **则** 该面 `cadence=weekly` 且 `due=false`,当日不要求探测

#### 场景: 新源保持每日
- **当** 某源在台账中首见不足 14 天
- **则** 该面 `cadence=daily`,不因零命中降频

### 需求: 覆盖校验以 due 面为基准
`finalize-daily` 的 fetch_status 覆盖校验必须以当日 `discovery_manifest.json` 中 `due=true` 的面为基准:due 面缺席 `source_details` 必须报错;非 due 面缺席禁止报错;非 due 面出现(唤醒)必须被接受且不产生告警。`cadence_plan` 的信任判据必须是**重算比对**:以当前 whitelist 与台账重新调用 `compute_cadence`,与 manifest 中存储的 plan 逐字段全等才可采信,任何偏离一律回退 whitelist 全量基准。禁止用逐字段规则(类型、语义自洽、固定 cadence 策略一致等)替代该比对——plan 是本流程自己的纯函数输出,「是否可信」等价于「是否等于该函数的输出」,逐字段规则只是对这个等价判断的近似,必然留下绕过路径。manifest 缺失或 `date` 与目标日期不符时,同样必须回退全量基准。承载该判据的参数(whitelist、cadence plan)禁止设默认值——可省略即等于保留一条弱校验旁路,契约必须由函数签名强制;due 名单必须从 cadence plan 内部派生,不得作为独立参数传入——收窄覆盖基准的方向一律 fail-closed,残缺 plan 会让 finalize 用短名单做阻塞校验、放行漏采日报。QA diff 与阻塞校验必须共用同一份经完整性校验的 due 基准,否则合法跳过的非 due 面会被报成 `missed_discovery` 假阳性。

#### 场景: 降频面缺席不报错
- **当** 某面当日 `due=false` 且未出现在 `fetch_status.source_details`
- **则** 覆盖校验通过,该缺席不进入错误清单,且 QA diff 不产生 `missed_discovery` finding

#### 场景: 残缺 plan 回退全量
- **当** manifest 的 `cadence_plan` 未覆盖 whitelist 当前全部 required 面(如 init 之后新增了源)
- **则** 该 plan 整体不被采信,覆盖校验回退 whitelist 全量基准

#### 场景: 非布尔 due 不得被 truthiness 读成"不用探"
- **当** 任一 slot 的 `due` 是 `null` / `0` / `"false"` 等非布尔值(即使 due 面占比恰好越过兜底阈值)
- **则** 该 plan 整体不被采信,回退 whitelist 全量基准

#### 场景: 任何偏离重算结果的 plan 都被拒绝
- **当** manifest 中的 plan 与重算结果存在任何差异——字段类型非法、语义矛盾(`daily` 却不 due、
  `last_probed: null` 却不 due、due 与间隔不符)、恒 daily 豁免面被改成 `weekly`、慢轨面被改成 `daily`、
  `last_probed` 与台账实际探测记录不符、多一个面或少一个面
- **则** 该 plan 整体不被采信,回退 whitelist 全量基准

#### 场景: 省略参数不得退回弱校验
- **当** 调用方省略 whitelist 或 cadence plan
- **则** 必须报错(参数无默认值),禁止静默走弱判据或跳过唤醒审计

#### 场景: 真实产出必须能通过自己的校验
- **当** plan 由 `compute_cadence` 在当前 whitelist 与台账上真实算出(含已降频的面)
- **则** 必须被采信,且降频面不出现在 due 名单中

#### 场景: 唤醒未留理由即阻塞
- **当** 某 `due=false` 的面出现在 `source_details`,但没有任何 attempt 带非空 `wakeup_reason`
- **则** finalize-daily 校验失败并点名该面

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
