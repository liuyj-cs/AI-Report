## 目的
信源采集面的空判定纪律:用逐层面性标注消除「空判定靠体感」的漂移,并把中文圈召回面换成结构化 API。

## 新增需求

### 需求: fetch_chain 逐层 surface_kind 标注
whitelist 中每个 `webfetch` 层必须标注 `surface_kind: feed | static`(`github_releases` 层缺省视为 feed;websearch 层不标注);未标注的 `webfetch` 层应当按 `static` 处理。空结果语义按层判定:final 层为 `feed` 时,窗口内空必须视为合法成功,禁止据此强制下穿;final 层为 `static` 时,`cn_labs` / `hard_data` 源必须下穿搜索层后才能判空,未下穿即 finalize 阻塞(这项 surface_kind 守门范围不扩大到其他类别；AI HOT 的分页证据校验另见下节)。`cn_labs` / `hard_data` 另需满足**链内穷尽**:停在 `feed` 层且空时,只要该链里还有未触达的抓取面(`webfetch` / `github_releases`),同样必须继续下穿,否则 finalize 阻塞——单个 feed 面只覆盖该源的一部分发布口径(API changelog 不覆盖 HF 权重发布)。判定「走到哪一层」必须依据 `attempts[]` 中真实出现过的最大 `layer_index`,禁止采信自报的 `final_layer_index`。源级 `empty_is_conclusive` 字段退役,代码禁止再读取。测试必须强制全部 `webfetch` 层标注齐全。

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
AI HOT 源的 fetch_chain 首层必须为 `mode=all&window=7d&by=published&limit=100`，标 `surface_kind: feed`，并保留 websearch_scoped 兜底。`selected` 只参考返回字段；`all` 是上游过滤后的公开池，不是原始采集全集。每页须保留真实 HTTP 状态、响应类型、请求 URL、完整 JSON 与证据 artifact 哈希，并按原样 `nextCursor` 连续翻页，再依锁定 manifest 的窗口筛选。覆盖证明必须从实际 artifact 重算，与 `aihot_coverage` 比对，不能采信自报完成。合法耗尽或倒序时间严格越过窗口起点才为 complete；partial/error 不能声明 API success/empty。HTTP 400 Problem JSON、不可解析内容及无效分页链均不属于合法空结果。该要求校验 API 覆盖事实，不把非核心聚合源失败升级为全报中断：实际完成搜索兜底后可记 source succeeded，但不能将 API 缺口写成 source empty。来自该面的候选继续按 media 降档规则处理，`media_only` 禁止驱动 action_items；沿 `links.original` 优先一跳补证。`publishedAt` 为空时回退 `discoveredAt` 必须标 `published_at_confidence: inferred`，`confidence` 不高于 medium。

本需求于 2026-09-29 替代 2026-07-27 的 selected/24h 双层配置与旧错误体判断；具体采集步骤与字段见 [AI HOT 工作流](../../../../../../skills/ai-daily-report/workflows/aihot-discovery.md)。

#### 场景: 完整分页后按本地窗口判空
- **当** 真实响应链已合法耗尽，或倒序时间严格越过 manifest 起点，且本地窗口内没有条目
- **则** API 面可记 success_but_empty；结论仅限该公开面，不代表中文圈无新闻

#### 场景: 分页未完成
- **当** `hasMore=true` 且尚未越过窗口起点，或翻页失败、游标链不连续
- **则** 记录 partial/error，禁止记 API success/empty；缺口保留在真实证据与 coverage 中

#### 场景: API 失效走兜底
- **当** API 请求失败、返回 HTTP 400 Problem JSON 或不可解析内容
- **则** 该层按 error 处理并继续 websearch_scoped；实际搜索成功可以恢复来源 succeeded，但不得声明 API 覆盖完整或来源 empty

## Technical Notes

- 现状锚点(均已读码核实,verified: 是):`editorial.recall_fallback_findings`(原按源级 `empty_is_conclusive` + category 判定)、`discovery.build_discovery_manifest`。
- AI HOT API 契约:合法成功响应为 `{schemaVersion, query, items[], page}`，`publishedAt` 等可空字段取用前判空；错误响应须先按 HTTP 状态与类型处理。2026-09-29 的实现依据与检查器见上述工作流，7 月实测不作为当前错误响应契约。
- 层定位机器规则:守门时由 attempt 的 `layer_index` 回查 whitelist 对应链取 `surface_kind`;attempts 已记录 `layer_index`(discovery.py `_blank_source_detail` 与 SKILL.md 步骤 1 契约)。
- 实施细节与风险缓解见 `../../design.md`(关键决策、风险与权衡);已撤销的采集调度设计见 design「撤销记录」,不属于本 spec 的 active 需求。

## 实施与验证
以下勾选项记录 2026-07 的原交付；2026-09-29 的 AI HOT 契约修订以当前工作流、代码与本轮验证为准，不复用历史测试结果。
- [x] surface_kind 标注 65 条链 + 标注齐全性测试 + 守门判据层级化(tdd)
- [x] AI HOT 链替换 + SKILL.md/AGENTS.md 口径修订 + 全量回归(`python3 -m pytest tests -q`)
