# AIReport Repository Notes

当用户要求生成、重跑、dry-run、渲染、归档或发送 AI 日报 / 周报时，先阅读并遵循 `skills/ai-daily-report/SKILL.md`。

保持判断逻辑由 AI 完成：
- 不要把信源优先级、去重、归类、趋势判断、落地建议改写成脚本死规则。
- `skills/ai-daily-report/scripts/` 只负责确定性工作：渲染 HTML、归档、发送邮件。
- 跑日报时，`whitelist.yaml` 是首轮覆盖起点，不是信息上限；若首轮明显偏稀薄，AI 应沿高信号实体追一跳相邻官方面补齐，但正文信息仍必须能回溯到 `fetch_status.source_details`。
- 采集节奏（`discovery_manifest.json > cadence_plan`）是对"首轮起点"的运维收窄，不改变上面这条原则：脚本按命中率把长尾面降到隔日/每周，`due=true` 的面必须全跑；非 due 面仍可被 AI 因外部信号唤醒（attempt 里写 `wakeup_reason`）。cadence 只决定"今天探不探"，不参与正文取舍与排序。审计面由 manifest 全量留痕承担，不因降频变窄。
- 面的空判定由 whitelist 逐层 `surface_kind`（`feed` / `static`）决定，不是每天现场按体感重判：`feed` 空即合法成功，`static` 空必须下穿。`cn_labs` / `hard_data` 更严——feed 面空也要走完该链剩下的抓取面（hard_data 还需跑搜索层），且判据只认 `attempts` 留痕、不认自报的 `final_layer_index`。要改判某个面的类型就改 whitelist 标注（有机器门守恒），不要在当天口头放行。
- 不要用固定厂商白名单、固定 Top N、固定分数阈值替代编辑判断；是否进正文、进 `unverified`、还是丢弃，应先形成候选池，再由 AI 结合窗口、证据强度、用户关注度与可执行性收口。
- 高关注对象名单只用于提醒 AI 做补漏和补证，不构成固定优先级顺序，也不能替代编辑判断。是否排前、是否进入正文、谁更值得写，必须由 AI 基于事件强度、影响面、版本阶段、来源质量以及对团队后续动作的意义综合判断；不要因为某个对象本身更热门，就机械地压过同窗口内其他更重要或更实质的更新。
- 对这类需要补证的高关注对象，若官方页弱、旧、或没有干净时间戳，但媒体稿或搜索结果已给出清楚事实链、明确日期，且至少一跳能回到官方面或官方产品页，允许进入正文前三节作为 `watch`；必须显式保留 `confidence=medium`、`via_broad_search=true` 或同等降档痕迹。
- 这类 `watch` 条目可以影响日报判断与后续跟进，但 `action_items` 只能导出 `monitor / experiment` 这类轻量动作；不要因为媒体热度直接推导高强度下注、迁移或大规模投入。
- `candidate_ledger.json` 和 `fetch_status.source_details` 要优先完整记录弱信号候选与补证路径，避免“HTML 里看不到就等于不存在”；正文取舍可以保守，但审计面不能过窄。
- 这是给团队看的 AI 行业日报/周报，不是论文或死板研究报告；在满足时间窗口、来源闭环和风险降档的前提下，应优先保留对行业判断有帮助、值得继续跟进的信号，而不是机械追求只剩绝对确定项。
- 当一份日报/周报暴露出问题时，首要目标不是只把当天这份修顺，而是提炼出能让后续日报/周报更稳、更完整的改进：优先补 workflow、校验点、审计字段、提示口径或 skill/AGENTS 规则；只有当天临时修补、却不能提升后续质量的做法，不应作为默认收口。
- 硬数据线：AI 抓取时把 LMArena / Artificial Analysis / OpenRouter 原始数字写 `hard_data_snapshot.json`，跨日 delta 由 `hard-data-delta` 子命令确定性计算；"是否值得写、怎么解读"仍是编辑判断。没有 delta 基线不得写"上升/下降"。
- 政策与合规是选型决策的一级输入（出口管制、备案、AI 法案），每日按 policy_compliance_sources 清账；稀薄日宁可少建议（前三节 ≤2 条时 action_items 上限 1 条，finalize 强制）。
- 两条思想/深度轨道：①「负责人访谈」复用 deep_dive 独立邮件骨架（`interview_{slug}.json` → `reports/interviews/` → 「AI 访谈 · {人物}」独立邮件，`interview_seen.json` 永久去重）；②「方法论雷达」是日报/周报新 section（`methodology_radar`，宽准入 + 30 天 cooldown，daily-only）。两者都不进 `action_items` 依据；发现、翻译、编辑判断仍由 AI 完成，脚本只做渲染/归档/发送/校验/台账。

常见触发语句包括：
- `生成今天的 AI 日报`
- `生成本周 AI 周报`
- `dry run 跑一下日报`
- `/ai-daily`
- `/ai-weekly`
