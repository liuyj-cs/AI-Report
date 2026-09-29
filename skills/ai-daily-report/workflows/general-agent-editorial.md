# 通用与办公 Agent：发现、证据与编辑

本工作流用于每份新日报 1.2（候选台账 1.1）及周报 1.1。旧日报 1.0/1.1、旧周报 1.0 只按其原结构读取；不迁移历史归档。初始化 manifest 锁定版本，不能降版本绕过检查。

## 读者问题与栏目边界

通用与办公 Agent（内部键 `general_agents`）回答：谁能借助什么产品，完成什么非编码任务，本窗口变化了什么，何时何地能用，是否改变试点或部署选择。允许办公辅助功能，但用 `usage_mode` 区分辅助生成、固定工作流和自主执行。

政策与风险观察（`policy_risk`）承载政策程序、已公布规则、研究安全披露与行业风险。它可以影响导读、决策雷达和行动，但不使用产品发布卡。证据充分的风险并不低于产品新闻；可信程度和栏目归属是两个判断。

按以下顺序编辑：识别对象/事件 → 核对窗口与证据 → 判断读者价值和栏目 → core/watch/unverified → 行动资格。`source.category`、厂商知名度、官网链接和新闻稀缺都不能替代归属理由。

边界例子：

- 议会邀请厂商负责人出席调查：policy_risk / policy_process；邀请不是法规，不填 ANNOUNCED。
- 训练或评测系统访问外部站点的披露：policy_risk / research_safety；没有生产产品归因，不能写成 ChatGPT/Codex 的已确认漏洞。
- 某个实际办公产品的连接器正式开放：general_agents，说明任务、读写权限、套餐与地区。
- 已确认某产品特定版本漏洞、停服或区域限制：可留该产品栏目，具体受影响对象和条件比“安全/监管”关键词更重要。
- 一个机构即使误写成产品名也不是产品；程序只能拦截声明为 institution/research_system 却进入产品栏的矛盾，AI 必须对照原文识别错误声明。
- 同一事件原则上只有一个正文归属；其他消费者引用它。拆分必须确有不同对象、事实增量和读者问题，并解释关系。
- 无合格新增时写“本窗口未确认新增通用与办公 Agent 产品变化”。有覆盖缺口时同时说明具体来源和原因，不宣称行业静默。

## 发现与提供证据

读取 profile 的 `workplace_task_coverage`，按研究、文档/数据、浏览器/桌面、跨系统工作流、组织管理与开放发现检查覆盖。复用 whitelist 中共享源；矩阵是补漏提醒，不是厂商排名。所有日期查询覆盖 `{yesterday}` 到 `{date}`，随后按 manifest 的准确时间窗口逐项核对。

每次实际工具返回必须完整保存到本批次 `cache/{date}/evidence/`。保存已得到的响应，不代表拿到了来源全部内容；工具截断、分页未取完、登录墙等必须保留。不能把 `String(result).slice(0,230)` 当作完成阅读；不能在正文无入选后反推搜索为空。

使用仓库 `scripts/evidence.py` 的确定性辅助工具，保存与阅读分两步进行。`save_response` 仅保存实际完整响应，不能生成完成回执。

每次外层工具调用只提供一个证据块（上限2000字符），不要在一次 functions.exec 中循环、并行、拼接全部块，或同时打印其他输出。为内层命令与外层调用各预留至少6000输出token；这个预算只是防截断余量，不是完成证明。

```sh
.venv/bin/python skills/ai-daily-report/scripts/evidence.py read cache/{date}/evidence/{sha256}.txt --start 0 --end 2000
```

末块使用实际长度；空响应读0..0。返回JSON包含 content、start、end 和 response_sha256，**不包含完成receipt**。观察实际工具返回：JSON是否完整，首尾范围是否一致，是否出现任一层truncated提示；如果有截断，这次输出不确认，缩小范围重新提供。不得仅看磁盘已保存的全部块。

确认实际输出完整后，在下一次调用将工具真正返回的stdout交给 `receipt_from_output(cache_dir, artifact, returned_output=actual_stdout)`，或将它原样传入 `evidence.py ack <artifact_path>` 的stdin。工具解析实际输出并重算比对规范证据块，内容缺失、修改、混入其他输出或超范围均拒绝；返回receipt后才加入 receipts。不要把本地重新序列化的 read_response 结果当成 actual_stdout，也不要在读块的同一次调用里预先ack。无需再次展示刚确认的原文。

只有实际确认过的receipt才能用于 `review_coverage(raw_response, receipts)`。不能循环遍历所有磁盘chunk生成receipt，再从这些预生成值反推“全部已提供”。保存证据、命令实际返回、外层向编辑提供、编辑理解，是四个不同步骤；脚本不声称能自动证明最后两步。

批次无法分辨各查询归属时，各 attempt 关联同一批次 artifact，`query_ids` 保留真实批次查询集合；不要伪造逐查询映射。artifact 内含 path、SHA-256、采集时间、批次和查询标识、limitations。失败响应也保存，敏感凭据不能进入采集请求或响应留存。

attempt 保留原 `result` 作为实际检索结果，并新增：

```json
{"evidence_artifact": {"path": "evidence/<hash>.txt", "sha256": "<hash>", "collected_at": "真实采集时间", "batch_id": "实际批次", "query_ids": ["实际查询标识"], "limitations": []},
 "review": {"status": "complete", "receipts": [], "coverage": {}, "reason": "编辑的取舍或覆盖说明"}}
```

上例只是字段说明，不可照抄空 receipts/coverage 作为完成记录。`coverage` 必须与函数重算完全相等。完整保存的空字符串也要调用一次 0..0 阅读，留下可重算记录。

`review.status` 为 complete / access_gap / incomplete。complete 仅表示全部已返回内容已提供并经编辑取舍；有分页/截断仍须在 reason 写清覆盖限制。access_gap 表示真实访问失败；incomplete 表示尚未提供完整响应，必须明确缺口。未完整审查不能将 result 写 empty/success_but_empty。失败不自动阻断全报，沿既有核心源阈值处置；缺文件、哈希不符、伪造完整阅读是确定性错误。

逐项查看搜索结果的标题、日期、来源与链接，明显无关可以排除；决定收录和行动的主张必须阅读正文或注明访问缺口。辅助函数只证明传入的实际输出与规范块一致；外层是否完整提供仍需核对工具结果，模型是否理解仍需编辑复核。不能把receipt当作端到端阅读或语义正确证明。

## 候选与成稿

日报填写 `coverage_summary`：把有实际影响的来源缺口合并为简短说明（上限1200字符），回答“哪些判断受限、还缺什么”。不能逐attempt复制reason或将通用“工具返回选段”铺满正文；原始limitations完整留存。空栏目保留真实empty_message，缺口不能被“本节无内容”覆盖。

工具响应完整提供不等于来源正文已取得，更不等于行业覆盖充分。只返回标题、元信息、JS壳或登录墙时，review可以如实记录已提供的内容，但抓取result不能因此标成正文成功；应记录error/access_gap并沿原fallback规则继续。共享批次中应逐请求判断，不能因另一查询有正文把整批所有请求都标success。

每条候选填写 `subject_kind`、`section_reason`、`claim_support`。后者仅覆盖决定收录、对象归因和行动的主张，包含 claim、direct_attempt_refs、background_attempt_refs、unresolved_questions。直接和背景引用互斥且属于 source_attempt_refs；直接证据必须是成功检索并完整提供的结果。只有背景不能把关键主张升为一手确认。

例如 9/28，Reuters 支持“发出出席请求”；对应参议院调查页只支持“调查存在”。相同官网的另一项调查不能证明该请求。9/27，官方通报支持研究环境的行为类型，不自动支持媒体所写具体机构及生产型号。事实可靠但无读者价值用 rejected_low_relevance，不伪装成证据弱。

产品条目必须填 use_case、what_changed、usage_mode、availability、impact、evidence_limits。release_stage 只代表实际能力的可用阶段。旧格式的 heat_signal 不用于新条目。真实采用数字进入已有 market_signals 并引用具体产品。

风险条目必须填 subject、risk_kind、event_status、affected_scope、decision_relevance、evidence_limits 和来源/时间/置信等共同字段，不填 product、product_tier、release_stage、heat_signal 或产品 expanded。tracking_ref 可选，不自动建立追踪、重大事件或专题。

正文与 selected 台账双向一致；拒绝条目保留在台账。导读、雷达、模式、行动可以引用风险；硬数据引用仍限定产品；新工具实验必须非空引用 coding_agents/general_agents。风险假设实验放行动项 experiment，不借产品实验栏包装。

## 行动增量

每条行动填写 `action_delta`：对照前日报/周报，此次新增的对象、范围、失败机制或有效期是什么，为何值得新增投入。仅程序进展而权限核查未变时，延续原判断、不重配人日；允许 action_items 为空。

每条实质依据分别服从 action_eligibility：none 无行动，monitor 仅 monitor，experiment 仅 monitor/experiment，full_action 可使用既有所有行动类型。多条依据不能取最高权限整体放行。正式规则确实改变本团队产品可用性，且证据闭环时可以支持 adopt/migrate/patch，不把所有风险永久限制为 monitor。产品前三栏合计 ≤2 条仍最多一项行动，风险不参与产品计数。

## 周报与交付

周报 1.1 按任务使用 `general_agents.items`，每项含 product、use_case、weekly_changes、implication、references；保留 trend_judgment、implication、empty_message。旧版的 newcomers/big_lab_moves 仅供历史读取。新 policy_risk.items 有独立状态、范围、增量、证据边界与原日报 references。没有独立事实就不凑模式或实验。

混合版本输入必须重新审查归属；旧 general 中的监管消息可转新周报 risk，但引用必须保留真实原日期、原 section、原 headline，并填写 origin_classification_note。旧消息不因聚合升级置信或行动资格。引用旧台账的行动必须先形成经过原始证据复核的新格式证据包；补审包存入 `cache/weekly/{week_end}/evidence_reviews/cache/{原日报日期}/`，包含新格式 report.json、candidate_ledger.json 和 evidence/。保留原 headline/source_url，按新栏目审查；weekly references 仍指原报告。程序验证补审包完整证据、唯一关联和行动资格。不能补审时不新增行动。不得为此覆盖已交付历史数据。

导读给判断、正文给事实、雷达给决策影响、行动给新增工作，避免四处重复扩写同一提醒。模板生成编号与稳定锚点。普通产品和风险导读显示“查看详情”，有模型能力卡才显示“查看详评”。全文 Markdown 从同一最终 HTML 转换；交付和发布仍按当前会话授权及已有去重/回读流程执行。

收尾读取 delivery_result.json 与原send_state。skipped_existing 表示跳过本次发送；sent_html_sha256为空意味着旧投递版本未知，不能从当前HTML推断。钉钉只认对应HTML哈希的发布回读，不将旧verified套到修订稿。
