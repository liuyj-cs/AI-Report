## 目的
信源采集面的空判定纪律:用逐层面性标注消除「空判定靠体感」的漂移,并把中文圈召回面换成结构化 API。

## 新增需求

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
AI HOT 源的 fetch_chain 必须以两个结构化 API 层开头:Layer-0 `mode=selected&window=24h&limit=50` 标 `surface_kind: static`(策展池空只说明未放行,不代表无新闻,必须下穿),Layer-1 `mode=all&window=24h&limit=50` 标 `surface_kind: feed`;并保留 websearch_scoped 兜底层。响应 `page` 为 null 时必须按该层 error 处理并继续下穿,禁止记为 empty(非法参数会返回 HTTP 400 + 空 items,静默读成 empty 即漏采)。来自该面的候选必须按既有 media 降档规则处理(tier 2 聚合面;`media_only` 禁止驱动 action_items),一跳官方补证应当优先使用条目自带的 `links.original`;条目 `publishedAt` 为空时应当回退 `discoveredAt` 并按 `published_at_confidence: inferred` 处理。

#### 场景: API 失效走兜底
- **当** aihot API 请求失败或返回不可解析内容
- **则** 该层按 error 处理,fetch_chain 继续下穿 websearch_scoped,不因单层失败判定源失败

## Technical Notes

- 现状锚点(均已读码核实,verified: 是):`editorial.recall_fallback_findings`(原按源级 `empty_is_conclusive` + category 判定)、`discovery.build_discovery_manifest`。
- AI HOT API 契约:响应 `{schemaVersion, query, items[], page}`;item 必有 `id/title/source.name/links.aihot/links.original/discoveredAt/selected`,`publishedAt/summary/category/score` 键恒在但值可 null,展示/归因前必须判空。来源: aihot skill `references/api.md` + 2026-07-27 实测 curl(verified: 是)。
- 层定位机器规则:守门时由 attempt 的 `layer_index` 回查 whitelist 对应链取 `surface_kind`;attempts 已记录 `layer_index`(discovery.py `_blank_source_detail` 与 SKILL.md 步骤 1 契约)。
- 实施细节与风险缓解见 `../../design.md`(关键决策、风险与权衡);已撤销的采集调度设计见 design「撤销记录」,不属于本 spec 的 active 需求。

## 实施与验证
- [x] surface_kind 标注 65 条链 + 标注齐全性测试 + 守门判据层级化(tdd)
- [x] AI HOT 链替换 + SKILL.md/AGENTS.md 口径修订 + 全量回归(`python3 -m pytest tests -q`)
