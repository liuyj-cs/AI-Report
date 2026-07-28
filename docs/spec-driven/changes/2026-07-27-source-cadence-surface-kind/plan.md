# 2026-07-27-source-cadence-surface-kind plan

## 目标
交付信源采集面的空判定纪律:fetch_chain 逐层 surface_kind 标注(守门判据层级化)+ AI HOT 结构化 API 面。

> 原目标含「命中统计台账 + 三档 cadence 调度 + 覆盖校验 due 基准,抓取量降 30-50%」(T1-T4)。
> 2026-07-28 整体撤销:实测降幅只有 21%(74 个面里 48 个恒每日,可降频的仅 24 个),而 PR #5
> 五轮 review 的 12 条 findings 100% 落在这部分。理由详见 design「撤销记录」。
> T1-T4 的原任务详情移至文末「附录:已撤销任务」,不再是待办步骤。

## 关联 spec 引用
- spec delta: `specs/source-discovery/spec.md`
- design: `design.md`

## 全局约束引用
- 红线:`AGENTS.md`(context-sources.yaml `red_lines`;对照结论见 design「结构化影响面分析」)
- test_policy: tdd
- 验证命令:`cd skills/ai-daily-report && python3 -m pytest tests -q`

## 任务总览

| id | 标题 | type | owner | status |
|----|------|------|-------|--------|
| T1 | ~~source_stats 台账模块~~ **已撤销,交付为空**(见附录) | tdd | Liu | done |
| T2 | ~~cadence 三档计算与 due 判定~~ **已撤销,交付为空** | tdd | Liu | done |
| T3 | ~~runner/manifest 集成 cadence 与台账~~ **已撤销,交付为空** | tdd | Liu | done |
| T4 | ~~覆盖校验 due 基准~~ **已撤销,交付为空** | tdd | Liu | done |
| T5 | 召回守门判据层级化(surface_kind)+ empty_is_conclusive 退役 | tdd | Liu | done |
| T6 | whitelist 全量 surface_kind 标注 + AI HOT API 链替换 + 标注齐全性测试 | tdd | Liu | done |
| T7 | SKILL.md / AGENTS.md 口径修订 | docs | Liu | done |

> status 词汇按 plugin 契约只取 `pending | pending_review | done`;撤销任务保留 `done`(交付为空)
> 以满足 spec-close 的准入条件,撤销事实写在标题与附录里。

## 任务详情

### T5:召回守门判据层级化
**需求引用**:`## 新增需求 › fetch_chain 逐层 surface_kind 标注`(空结果语义、场景×4、empty_is_conclusive 退役)

**接口块**
- Consumes: attempts 的 `layer_index`(回查 whitelist 链层取 `surface_kind`)— 来源: discovery.py `_blank_source_detail` + SKILL.md 步骤 1 attempts 契约 (verified: 是)
- Produces: `recall_fallback_findings`(editorial.py)重写:按 `attempts[]` 实迹取最大 `layer_index`(禁止采信自报 `final_layer_index`)定位 final 层;该层 `surface_kind==feed` 且链内已无未触达抓取面且空 → 无 finding;`static`/未标 且空且无搜索层 attempt,或停在中间 feed 层(链内穷尽未达)→ 阻塞性 finding,范围仍限 `HIGH_RECALL_CATEGORIES`;删除源级 `empty_is_conclusive` 读取 — 来源: 现有函数重写,本 change 契约产物

**type**:`tdd` —— 校验逻辑

**步骤**
- [x] 写失败测试:feed 层空不阻塞、static 层空未下穿阻塞、未标注层按 static、`github_releases` 层缺省 feed、非高召回类不阻塞、layer_index 越界安全处理
- [x] 补链内穷尽与自报层号用例(中间 feed 层空仍阻塞;attempts 只到 Layer-0 而自报链尾 → 按实迹判)
- [x] 重写 `recall_fallback_findings` 并删 `empty_is_conclusive` 读取
- [x] 回归:test_editorial 现有守门用例改造后全绿

---

### T6:whitelist 全量标注 + AI HOT 链替换
**需求引用**:`## 新增需求 › fetch_chain 逐层 surface_kind 标注`(标注齐全性,关键决策 1 全量口径)+ `## 新增需求 › AI HOT 结构化 API 采集面`

**接口块**
- Consumes: 标注判据(design 技术方案 4:「每条带日期的倒序列表才算 feed」)— 来源: design.md (verified: 是);AI HOT API 契约 — 来源: aihot skill references/api.md + 2026-07-27 实测 (verified: 是)
- Produces: whitelist 全部链的 `webfetch` 层带 `surface_kind`;AI HOT 新链(Layer-0 `mode=selected` 标 static + Layer-1 `mode=all` 标 feed + websearch_scoped 兜底);新测试「webfetch 层必标 surface_kind ∈ {feed,static}」守恒 — 来源: 本 change 契约产物

**type**:`tdd` —— 齐全性测试先行(测试先红:未标注 → 逐条标注 → 转绿),数据标注有机器守恒

**步骤**
- [x] 写失败测试:遍历 whitelist 全部 fetch_chain,webfetch 层缺 surface_kind 或值非法即失败;AI HOT 链结构断言(Layer-0 selected/static、Layer-1 all/feed)
- [x] 按判据逐条标注(cn_labs/hard_data 优先核对;拿不准的层一律标 static 保守处理)
- [x] 终审用浏览器 UA 实抓复核,修正 20 个 feed 误标(含 core_source Claude Code release-notes)
- [x] 替换 AI HOT 链;whitelist 注释清理(empty_is_conclusive 段改为 surface_kind 说明)
- [x] 清理死链信源面(The Register 换 `/ai_ml/`;Semafor Technology 全路径 404 删除)
- [x] 全量回归绿

---

### T7:SKILL.md / AGENTS.md 口径修订
**需求引用**:`## 新增需求 › fetch_chain 逐层 surface_kind 标注`(empty 判定三处统一)+ `## 新增需求 › AI HOT 结构化 API 采集面`(读取说明)

**接口块**
- Consumes: T5-T6 落定的机制与字段名 — 来源: 本 change 契约产物 (verified: 依赖 T5/T6)
- Produces: SKILL.md 修订(步骤 1 empty 判定、异常处理节、时效性规则三处统一为 surface_kind 口径;AI HOT API 字段读取说明与 `page` 为 null 的静默空集纪律);AGENTS.md 追加红线(校验函数禁止可选参数降级、纯函数产物判据必须重算比对、加机制前先算覆盖比例与稳定成本)— 来源: 本 change 契约产物

**type**:`docs` —— 纯流程文本,无可测运行时行为;完成条件 = 全量 pytest 绿(登记检查命令)+ 逐条人工核对三处口径无残留矛盾

**步骤**
- [x] 修订 SKILL.md 三处 empty 判定 + AI HOT 说明
- [x] 修订 AGENTS.md 红线
- [x] 全文 grep `empty_is_conclusive` / 「静态/必须下穿」确认无残留旧口径;全量回归绿

---

## 附录:已撤销任务(历史记录)

以下 T1-T4 是 cadence 采集调度的原计划,2026-07-28 整体撤销,**交付物已全部删除,不属于本 change 的 active 契约**。保留原文仅供将来重做时参考(重做的前置条件见 design「撤销记录」:先算清豁免名单锁定的收益上限)。

<details>
<summary>T1-T4 原任务详情(已撤销)</summary>

### T1:source_stats 台账模块
**需求引用**:`## 新增需求 › 信源面命中统计台账`(全部场景)— **该需求已从 spec delta 删除**

**接口块**
- Consumes: `report.json` 的 `fetch_status.succeeded / empty / source_details[name].attempts`
- Produces: `scripts/source_stats.py`:`record_source_stats(report, project_root, target_date) -> int`(写入并返回记录面数,按日期幂等,写入时修剪 >45 天)、`load_source_stats(project_root) -> dict`(损坏 fail-open 返回空台账)

**原步骤**:hit 判定与幂等/修剪/fail-open 测试 → 实现 `source_stats.py` → 边界用例

---

### T2:cadence 三档计算与 due 判定
**需求引用**:`## 新增需求 › 采集节奏分层调度`— **该需求已从 spec delta 删除**

**接口块**
- Consumes: T1 `load_source_stats`;whitelist `core_sources` / `authority_tier` / `category` / 源级 `cadence` pin;聚合面名常量
- Produces: `compute_cadence(whitelist, stats, target_date) -> dict[name, {"cadence","due","last_probed"}]`

**原步骤**:三档分档与豁免/新源保护/due 差值判定测试 → 实现 `compute_cadence` → 边界用例

---

### T3:runner/manifest 集成
**需求引用**:`## 新增需求 › 采集节奏分层调度`+`## 新增需求 › 信源面命中统计台账`— **均已删除**

**接口块**
- Consumes: T1 `record_source_stats`、T2 `compute_cadence`;`build_discovery_manifest` / `run_daily_init` / `run_daily_finalize`
- Produces: manifest `required_sources[i].cadence/.due/.last_probed` + 顶层 `cadence_summary{due,skipped}`;run.log `CADENCE` 行;`report_runner.py source-stats --date` 子命令

**原步骤**:manifest/日志/台账写入/子命令测试 → 实现三处集成 → 回归

---

### T4:覆盖校验 due 基准
**需求引用**:`## 新增需求 › 覆盖校验以 due 面为基准`— **该需求已从 spec delta 删除**

**接口块**
- Consumes: 当日 `discovery_manifest.json` 的 cadence 字段
- Produces: `missing_fetch_status_coverage(report, whitelist, due_names=None)`、`validate_fetch_status_integrity(report, whitelist, due_names=None)`、finalize 读 manifest 传入 due 名单

**原步骤**:due 面缺席报错/非 due 面豁免/manifest 缺失回退测试 → 实现签名扩展与接线 → 回归

> 注:这里的「可选参数 = 省略即回退全量」正是 review round 5 判定的降级旁路,后续 AGENTS.md
> 已把「校验函数禁止用可选参数表达降级」立为红线。

</details>
