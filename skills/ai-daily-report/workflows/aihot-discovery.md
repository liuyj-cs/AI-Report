# AI HOT 发现面与分页留痕

AI HOT 是媒体聚合发现面。`mode=all` 仍经过上游公开资格过滤；`selected` 只参考返回字段，不替代本地选稿。合法空响应只能表示这个公开面本次没有返回窗口内条目，不能说明中文圈无新闻或上游处理已经完成。候选沿 `links.original` 补证，媒体证据与行动资格规则不变。

从 whitelist 的 `mode=all&window=7d&by=published&limit=100` 开始。`by=published` 实际按 `publishedAt ?? discoveredAt` 倒序；保存两个原始字段，前者为 null 时只把后者视为推定时间，补证前不得当成确定发布日期。API 每页使用当时服务器的滚动 7 天窗口；旧日报超出这个范围时应明确覆盖不足。

逐页保留完整 HTTP 响应，不能只保存选中的条目或重写成摘要。用现有 `evidence-save` 保存以下 JSON 对象作为该 API attempt 的 `evidence_artifact`；请求开始时间为 `requested_at`，响应收集完成时间由 artifact 的 `collected_at` 承载，二者均使用带时区的 ISO 8601 实际时间：

```json
{
  "request_url": "实际请求的完整 URL，含原样 cursor 的 URL 编码",
  "requested_at": "实际请求开始时间",
  "status_code": 200,
  "content_type": "application/json; charset=utf-8",
  "body": {"完整响应": "这里是结构示意，实际须保存原始 API JSON 对象"}
}
```

`request_url` 必须与 attempt 的 `target` 相同。每页仍属于 whitelist 首层，`layer_index=0`、`layer_type=webfetch`；不同页各有独立 attempt 和原始 artifact。网络失败同样留痕，`status_code=null`，`body` 保留工具报错。HTTP 400 当前使用 `application/problem+json`，旧错误体 `items:[]/page:null`、304 无实体、错误 HTML、缺字段都不能当空成功。

后续请求原样传递 `page.nextCursor`，保持 mode/window/by 与来源一致，不增加 category/q 过滤。正常停止依据只能是：

- 合法响应的 `hasMore=false`，游标为 null；或
- 已连续读取合法倒序页，最后一条排序时间**严格早于** manifest 的窗口起点。等于起点还可能有同时间条目，继续翻页。提前停止时保留原始 `hasMore=true` 和 nextCursor。

达到预算、请求失败、游标失效或未翻完时，记录 partial；不能写成 empty、不能声称 API 发现已成功。HTTP 200 只代表单次请求成功，此时 API attempts 的 `result=error`、`reason` 写明“分页未完成”，真实 HTTP 状态仍保留在 artifact 中，再走 whitelist 搜索降级层。搜索完成可记来源 `succeeded`，但不得把 API 缺口抹成来源 `empty`。失败尝试也必须保留；重试仍使用该失败请求的同一个 cursor，失败本身不推进游标。不能用重新抓第一页填补缺失的后续页，也不能拼接两个不同起点。

用确定性检查器读取实际 artifact、校验哈希和 HTTP/响应/query/cursor/时间顺序，并计算本地覆盖结果：

```bash
python skills/ai-daily-report/scripts/aihot.py \
  --report cache/{date}/report.json \
  --manifest cache/{date}/discovery_manifest.json \
  --cache-dir cache/{date}
```

将输出原样写入 `fetch_status.source_details["AI HOT"].aihot_coverage`。finalize 从相同原始材料重算比对，不接受自报 complete。检查器在首次充分的完成证据处停止；`pages_fetched` 统计参与覆盖判断的有效响应页，失败尝试与额外页仍保留在 attempts 中。`status=complete` 表示本次目标窗口遍历完成；不表示不可变快照，也不表示上游没有尚未处理、被过滤或以后才发现的材料。`in_window_count` 包含按发现时间推定的条目，`inferred_time_count` 单独标出它们；是否入选、归类、补证和行动仍由 AI 决定。

合同依据：AIHOT [`v1.ts`](https://github.com/KKKKhazix/AIHOT/blob/589f79eff09470b31ba8a7f1d9eb62d36ff2be6c/packages/backend/src/publication/v1.ts)、[API 路由](https://github.com/KKKKhazix/AIHOT/blob/589f79eff09470b31ba8a7f1d9eb62d36ff2be6c/apps/api/src/routes/v1.ts)。上游默认 window 是 7d；本地旧 URL 显式使用 24h。新批次由 manifest 锁定新首层 URL，历史 selected/24h manifest 只按历史契约读取。
