# 2026-07-27-source-cadence-surface-kind intake

## 需求概述

日报采集管线目前每天对 62 个白名单信源(65 条 fetch_chain、约 75-79 个面)全量轮询,实测约 107-117 次抓取尝试/天,仅产出 5-13 条候选、2-7 条正文条目;07-26 当天 79 个面里 70 个 empty、正文仅 1 条。本 change 提升单位信息的获取效率并把「空判定」从提示词裁量收敛为白名单数据,三项合一:

1. **按历史命中率做产能分层调度**:`report_runner.py` 新增确定性子命令,统计各信源面近 30 天命中率(基于持久滚动台账,因 cache 日目录只保留 14 天),调度结论写入 `discovery_manifest.json`;长期零命中的长尾面降频(隔日/每周探测),官方一级源与核心源保持每日。
2. **fetch_chain 逐层 `surface_kind: feed|static` 标注**:替代「cn_labs/hard_data 按类别一刀切下穿」的规则;feed 面(带日期倒序列表/结构化 API)空即合法成功、不下穿,落地目前只存在于 whitelist 注释中的 `empty_is_conclusive` 机制。DeepSeek 的 `api-docs.deepseek.com/updates` 这类带日期 changelog 应按 feed 面处理,不再每天强制下穿 4 层。
3. **AI HOT 源升级为结构化 API**:fetch_chain Layer-0 从抓首页 HTML(JS 渲染页,易触发伪成功判定)换成 `GET https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=50`(已实测可用:结构化 JSON、双时间戳、links.original 可直接支撑一跳官方补证);feed 面、每日探查、tier 2 聚合面角色不变,候选仍按 media 降档规则走(media_only 不驱动 action)。

目标:正常日抓取尝试量下降 30-50%,召回不劣化(qa_diff missed_discovery 不因降频新增);编辑判断归 AI 的红线(AGENTS.md)不动——调度与空判定是确定性运维工作,是否进正文仍由 AI 收口。

## PRD 来源清单

- 本会话(2026-07-27)对照 aihot skill(github.com/KKKKhazix/khazix-skills/tree/main/aihot)的全仓诊断分析,含 07-22~07-27 六天 report.json / candidate_ledger.json / qa_diff.json 实测数据
- 用户裁决:同意先做 #1(命中率分层调度)与 #2(surface_kind 标注);AI HOT API 质量确认后要求换用 API 并保持每日探查
- aihot skill references/api.md:AI HOT v1 API 契约(items 端点参数、双时间戳语义、feed 语义)

## 完整度评估

- 验收标准:明确(追问 4 已答复:7 日均 attempts≤70 且无降频致漏采)
- 边界条件:明确(追问 1/2 已答复:三档降频;豁免名单=核心源+tier1+hard_data+AI HOT+召回探针)
- 异常路径:基本明确 —— aihot API 不可达时沿 fetch_chain 下层(websearch)降级;调度台账损坏按现有台账惯例(视为空、不阻塞);统计不足的新源默认每日
- 性能与合规约束:不适用(本 change 本身即效率改进;aihot API 匿名只读、无密钥)

## 追问记录

> 编号,每条附可直接转发的编号文本。

1. 降频档位怎么定(风险偏好)?— 状态:已答复:采纳推荐(三档 每日/隔日/每周;新源 14 天内一律每日)
   推荐:三档——每日(默认)/ 隔日(近 30 天命中 1-2 次)/ 每周(近 30 天 0 命中且已探测 ≥10 次);统计不足 14 天的新源一律每日。
   权衡:不采纳三档、全部只降到隔日,则节省约减半但最坏延迟仅 1 天;三档下每周档的面若突发新闻,最坏官方一手延迟 6 天,靠媒体/探针面兜底(通常 ≤1 天被交叉发现)。
   转发文本:「关于 2026-07-27-source-cadence-surface-kind,想确认:长尾信源降频采用三档(每日/隔日/每周)还是保守两档(每日/隔日)?」

2. 永不降频的豁免名单范围?— 状态:已答复:采纳推荐(核心源+tier1 官方+hard_data+AI HOT+召回探针每日;interview/methodology 允许隔日)
   推荐:core_sources 8 个 + 全部 authority_tier=1 官方面 + hard_data 4 源 + AI HOT + 召回类探针(recall_probe / high_signal_media / general_agent queries)维持每日;interview 与 methodology 面(慢信号,7 天/14 天准入窗)允许降为隔日。降频主要落在 tier 2/3 媒体面、coding_agents_secondary、agent_ecosystem_sources、policy_compliance_sources 的长期零命中面。
   权衡:豁免过宽则总节省达不到 30%;过窄则官方一手信息延迟,违背「官方面优先」纪律。
   转发文本:「同 change,想确认:哪些信源类别绝不降频?推荐名单为核心源+tier1 官方+hard_data+召回探针+AI HOT,访谈/方法论面允许隔日。」

3. 调度是 advisory 还是硬校验?— 状态:已答复:采纳推荐(advisory;finalize 覆盖校验基准改为 manifest due 列表;非 due 面可记 reason 唤醒)
   推荐:advisory——`discovery_manifest.json` 列出当日 due 面;AI 必须覆盖全部 due 面(finalize 沿用现有覆盖校验,基准从 whitelist 全量改为 manifest due 列表);非 due 面允许 AI 因外部信号临时唤醒(须在 attempts 里记 reason),不因未探而告警。
   权衡:硬校验(非 due 面禁探)更省 token 但违背 AGENTS.md「白名单是起点不是上限」红线;advisory 的风险是 AI 惯性全探导致省不下来——以追问 4 的验收口径观察一周,不达标再收紧。
   转发文本:「同 change,想确认:非探查日的面,AI 是允许自主唤醒(advisory)还是禁止探测(硬校验)?」

4. 硬验收口径?— 状态:已答复:采纳推荐(连续 7 正常日:日均 attempts≤70、无降频致 missed_discovery、AI HOT API 面每日留痕)
   推荐:改造合入后连续 7 个正常日:①日均 attempts ≤ 70(基线约 110,-35%);②qa_diff 无因降频新增的 missed_discovery(降频面事后被证实漏掉窗口内官方发布记为违约);③AI HOT API 面每日有 attempt 留痕。
   权衡:不定硬口径无法判定改造成功;口径过紧(如 ≤55)可能逼出真实漏采。
   转发文本:「同 change,想确认:验收口径采用『7 日均值 attempts≤70 且无降频致漏采』是否合适?」

## 未决项(open questions)

- 无(追问 1-4 已于 2026-07-27 答复:全部采纳推荐)

## 分级结论与信号

- 结论:中等(M)
- 命中信号(对照 intake flow ⑤ 信号表):
  - 数据模型变化:whitelist.yaml 新增逐层 `surface_kind` / 源级 cadence 覆盖字段;discovery_manifest.json 新增调度段;新增持久滚动统计台账(cache 根文件,仿 seen_repos.json 惯例)
  - 跨模块:discovery.py(manifest 生成)、report_runner.py(新子命令 + finalize 覆盖校验基准变更)、whitelist.yaml、SKILL.md/AGENTS.md 规则层同步修订
  - PRD 有需技术决策的歧义:追问 1-4
- 单 repo,无跨仓/跨端 → 不升 L

## 收尾记录

<留空;spec-close 收尾时追加>
