# 2026-07-27-source-cadence-surface-kind plan

## 目标
交付信源采集面的确定性调度与空判定纪律:命中统计台账 + 三档 cadence 调度 + 覆盖校验 due 基准 + fetch_chain 逐层 surface_kind 标注(守门判据层级化)+ AI HOT 结构化 API 面,目标正常日抓取尝试量下降 30-50% 且召回不劣化。

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
| T1 | source_stats 台账模块(写入/幂等/修剪/fail-open) | tdd | Liu | pending |
| T2 | cadence 三档计算与 due 判定 | tdd | Liu | pending |
| T3 | runner/manifest 集成:init 算 cadence、finalize 写台账、source-stats 子命令 | tdd | Liu | pending |
| T4 | 覆盖校验 due 基准 + manifest 缺失回退 | tdd | Liu | pending |
| T5 | 召回守门判据层级化(surface_kind)+ empty_is_conclusive 退役 | tdd | Liu | pending |
| T6 | whitelist 全量 surface_kind 标注 + AI HOT API 链替换 + 标注齐全性测试 | tdd | Liu | pending |
| T7 | SKILL.md / AGENTS.md 口径修订 | docs | Liu | pending |

## 任务详情

### T1:source_stats 台账模块
**需求引用**:`## 新增需求 › 信源面命中统计台账`(全部场景)

**接口块**
- Consumes: `report.json` 的 `fetch_status.succeeded / empty / source_details[name].attempts` — 来源: SKILL.md 步骤 1 契约 + discovery.py `_blank_source_detail`(discovery.py:181) (verified: 是)
- Produces: `scripts/source_stats.py`:`record_source_stats(report, project_root, target_date) -> int`(写入并返回记录面数,按日期幂等,写入时修剪 >45 天)、`load_source_stats(project_root) -> dict`(损坏 fail-open 返回空台账)— 来源: 本 change 契约产物

**type**:`tdd` —— 数据处理/状态管理

**步骤**
- [ ] 写失败测试:hit 判定(succeeded 且非 empty)、按日期幂等覆盖、45 天修剪、损坏文件返回空台账不抛异常
- [ ] 实现 `source_stats.py`(持久化惯例同 `seen_repos.json`:cache 根文件)
- [ ] 补边界用例:空 report、面名含中文/空格、首次运行无台账文件

---

### T2:cadence 三档计算与 due 判定
**需求引用**:`## 新增需求 › 采集节奏分层调度`(分档规则、豁免面、场景×2)

**接口块**
- Consumes: T1 `load_source_stats` — 来源: 本 change 契约产物 (verified: 依赖 T1);whitelist `core_sources` 名单 / `authority_tier` / `category` / 源级 `cadence` pin — 来源: sources/whitelist.yaml 现有结构 (verified: 是);聚合面名常量(`discovery.py:19-27` GENERAL_SEARCH/RECALL_PROBE/INTERVIEW/METHODOLOGY 等)— 来源: discovery.py (verified: 是)
- Produces: `compute_cadence(whitelist, stats, target_date) -> dict[name, {"cadence","due","last_probed"}]`(落 `source_stats.py` 或 `discovery.py`,dev 时按依赖方向定,避免循环 import)— 来源: 本 change 契约产物

**type**:`tdd` —— 业务规则计算

**步骤**
- [ ] 写失败测试:三档分档(hit≥3 / 1-2 / 0)、weekly 准入(实探日≥10 且首见≥14 天)、新源回退 daily、豁免面恒 daily(core/tier1/hard_data/pin/聚合面)、interview+methodology 固定 every_2_days、due 差值判定(≥2 / ≥7,无记录即 due)
- [ ] 实现 `compute_cadence`
- [ ] 边界用例:台账为空(全 daily)、last_probed 恰好等于间隔

---

### T3:runner/manifest 集成
**需求引用**:`## 新增需求 › 采集节奏分层调度`(manifest 字段、CADENCE 日志)+ `## 新增需求 › 信源面命中统计台账`(finalize 写入时点、dry-run 也写)

**接口块**
- Consumes: T1 `record_source_stats`、T2 `compute_cadence` — 来源: 本 change 契约产物 (verified: 依赖 T1/T2);`build_discovery_manifest`(discovery.py:360)、`run_daily_init`(report_runner.py:96)、`run_daily_finalize`(report_runner.py:204,写入点=validate_daily_artifacts 通过后、dry-run 分支 return 之前)— 来源: 现有代码 (verified: 是)
- Produces: manifest 新字段 `required_sources[i].cadence/.due/.last_probed` + 顶层 `cadence_summary{due,skipped}`;run.log `CADENCE due=N skipped=M` 行;`report_runner.py source-stats --date` 子命令(打印近 30 天汇总 + 当日 due 预览)— 来源: 本 change 契约产物

**type**:`tdd` —— 接口/编排逻辑

**步骤**
- [ ] 写失败测试:init-daily 后 manifest 含 cadence 字段与汇总、run.log 有 CADENCE 行;finalize(含 --dry-run)后台账已更新;source-stats 子命令输出
- [ ] 实现三处集成与子命令
- [ ] 回归:现有 test_report_runner / test_discovery 全绿(manifest 新增字段不破坏旧消费方)

---

### T4:覆盖校验 due 基准
**需求引用**:`## 新增需求 › 覆盖校验以 due 面为基准`(全部场景)

**接口块**
- Consumes: 当日 `cache/{date}/discovery_manifest.json`(T3 产出的 cadence 字段)— 来源: 本 change 契约产物 (verified: 依赖 T3)
- Produces: `missing_fetch_status_coverage(report, whitelist, due_names=None)`(discovery.py:424 签名扩展,None=whitelist 全量)、`validate_fetch_status_integrity(report, whitelist, due_names=None)`(editorial.py:169 同步)、finalize 读 manifest 传入 due 名单 — 来源: 现有函数签名扩展,本 change 契约产物 (现状 verified: 是)

**type**:`tdd` —— 校验逻辑

**步骤**
- [ ] 写失败测试:due 面缺席报错、非 due 面缺席通过、非 due 面出现(唤醒)通过且无告警、manifest 缺失/无 cadence 字段回退全量基准
- [ ] 实现签名扩展与 finalize 接线
- [ ] 回归:test_editorial 现有覆盖用例全绿

---

### T5:召回守门判据层级化
**需求引用**:`## 新增需求 › fetch_chain 逐层 surface_kind 标注`(空结果语义、场景×2、empty_is_conclusive 退役)

**接口块**
- Consumes: attempts 的 `layer_index`(回查 whitelist 链层取 `surface_kind`)— 来源: discovery.py `_blank_source_detail` + SKILL.md 步骤 1 attempts 契约 (verified: 是)
- Produces: `recall_fallback_findings`(editorial.py:994)重写:final 层 `surface_kind==feed` 且空 → 无 finding;`static`/未标 且空且无搜索层 attempt → 阻塞性 finding,范围仍限 `HIGH_RECALL_CATEGORIES`;删除源级 `empty_is_conclusive` 读取 — 来源: 现有函数重写,本 change 契约产物 (现状 verified: 是)

**type**:`tdd` —— 校验逻辑

**步骤**
- [ ] 写失败测试:feed 层空不阻塞、static 层空未下穿阻塞、未标注层按 static、`github_releases` 层缺省 feed、非高召回类不阻塞、layer_index 越界安全处理
- [ ] 重写 `recall_fallback_findings` 并删 `empty_is_conclusive` 读取
- [ ] 回归:test_editorial 现有守门用例改造后全绿

---

### T6:whitelist 全量标注 + AI HOT 链替换
**需求引用**:`## 新增需求 › fetch_chain 逐层 surface_kind 标注`(标注齐全性,关键决策 1 全量口径)+ `## 新增需求 › AI HOT 结构化 API 采集面`

**接口块**
- Consumes: 标注判据(design 技术方案 4:「每条带日期的倒序列表才算 feed」)— 来源: design.md (verified: 是);AI HOT API 契约 — 来源: aihot skill references/api.md + 2026-07-27 实测 (verified: 是)
- Produces: whitelist 全部 65 条链 webfetch 层带 `surface_kind`;AI HOT 新链(API Layer-0 feed + websearch 兜底 + `cadence: daily` pin);新测试「webfetch 层必标 surface_kind ∈ {feed,static}」守恒 — 来源: 本 change 契约产物

**type**:`tdd` —— 齐全性测试先行(测试先红:未标注 → 逐条标注 → 转绿),数据标注有机器守恒

**步骤**
- [ ] 写失败测试:遍历 whitelist 全部 fetch_chain,webfetch 层缺 surface_kind 或值非法即失败;AI HOT 链结构断言(Layer-0 为 API url + feed + pin)
- [ ] 按判据逐条标注 65 条链(cn_labs/hard_data 优先核对;拿不准的层一律标 static 保守处理)
- [ ] 替换 AI HOT 链;whitelist 注释清理(empty_is_conclusive 段改为 surface_kind 说明)
- [ ] 全量回归绿

---

### T7:SKILL.md / AGENTS.md 口径修订
**需求引用**:`## 新增需求 › 采集节奏分层调度`(唤醒纪律)+ `## 新增需求 › fetch_chain 逐层 surface_kind 标注`(empty 判定三处统一)+ `## 新增需求 › AI HOT 结构化 API 采集面`(读取说明)

**接口块**
- Consumes: T1-T6 落定的机制与字段名 — 来源: 本 change 契约产物 (verified: 依赖 T1-T6)
- Produces: SKILL.md 修订(步骤 1 empty 判定、异常处理节、时效性规则三处统一为 surface_kind 口径;新增 cadence 小节;AI HOT API 字段读取说明);AGENTS.md 补 cadence 一句(due 列表是首轮起点的运维收窄,不改「起点不是上限」原则)— 来源: 本 change 契约产物

**type**:`docs` —— 纯流程文本,无可测运行时行为;完成条件 = 全量 pytest 绿(登记检查命令)+ 逐条人工核对三处口径无残留矛盾

**步骤**
- [ ] 修订 SKILL.md 三处 empty 判定 + 新增 cadence 节 + AI HOT 说明
- [ ] 修订 AGENTS.md(一句话)
- [ ] 全文 grep `empty_is_conclusive` / 「静态/必须下穿」确认无残留旧口径;全量回归绿
