# 按需专题研究

专题的验收标准是替读者完成公开资料整理、比较与推理，使其只需验证与自身业务有关的差异。AI 决定是否立项和发布，脚本只检查结构、引用与投递清单，不用固定厂商、分数、来源数量或篇幅代替编辑判断。

## 立项与补证

- 先提出具体选择问题，例如“Pro 与 Flash 在哪些任务上的质量差异值得额外成本”。再写一句相对本期晨报新增的判断或分析；如果只能重复发布参数或建议测试，合并回晨报，不选入专题。
- 重大事件照常补证和追踪；允许等待后续证据成熟，也允许一篇比较多个对象。没有专题不影响重大事件标记、正文能力卡或每日钉钉同步。
- 先处理可公开查清的分项成绩、测试脚注、价格、许可证、硬件要求与产品可用性。已打开的页面、表格/PDF 和失败尝试均在本次日报 `fetch_status.source_details` 留痕。可引用较早的技术资料，标清其适用版本和本次核验时间，不把旧资料写成当天新闻。
- 比较项由问题决定：解释指标测什么、具体型号/档位、对照成绩、差距、预算和运行框架。不同口径分开写；不省略反例、退步项或更有利的替代方案。综合分不能直接推出所有任务能力。
- 把场景写成“任务特点 → 需要的能力 → 证据 → 适用边界”，区分直接测量和推断。产品功能专题可比较流程与约束，不强凑模型榜单。成本优先讨论完整任务的消耗、等待和返工；缺少数据时写缺口，不从单价推导总成本。

## 产物与发布选择

写 `cache/{date}/deep_dive_{slug}.json`，遵循 `schemas/deep_dive.schema.json` 的 `version: "1.1"`：

- `decision_question`：读者要解决的具体问题；`incremental_value`：相比晨报增加了什么。
- `sections.verdict`：先给带条件的结论。
- `comparisons[]`：`dimension / finding / conditions / interpretation / reference_ids`。finding 写明各对象的结果与对照，conditions 保留可比性限制；不只罗列一个模型的分数。
- `scenarios[]`：`task / recommendation / reason / evidence_boundary / reference_ids`。recommendation 使用 `recommended / conditional / not_recommended / insufficient_evidence`；evidence_boundary 使用 `measured / inferred`。
- `costs_and_constraints`：`analysis / reference_ids`；没有公开价格或硬件数据时，在有证据的部分说明边界，不虚构估计。
- `remaining_unknowns[]`：`question / kind / checked / decision_impact`。kind 为 `public_evidence_gap` 或 `business_validation`；写清查过什么、缺口是否会改变结论。已公开可查的问题应继续研究，不转交给读者。
- `next_action`：根据结论行动、维持现状或继续观察；确需实验时，只验证剩余业务差异，给出相应对象与判据，不把“小样本试用”说成稳定选型结论。
- `references[]`：`id / source / url / evidence_type / observed_at`。每个 URL 必须有本次日报中的成功精确 URL 抓取记录，observed_at 带时区且不晚于专题生成时间。evidence_type 为 `vendor_reported / independent / team_test`；团队实测只用于真实完成且可回溯的测试。

完成后由 AI 按以下问题复核，并在 `run.log` 留一句立项/延期理由（沿用现有日志，不加新台账）：

1. 相比晨报新增了哪一步比较或推理，是否真的支持开头结论？
2. 每条重要结论是否能沿引用回到原始证据，分数/单位/配置是否抄录正确？
3. “适用”是否有证据支撑或明确标为推断，反例是否可能推翻判断？
4. 剩下的是必须业务验证的差异，还是尚未完成的公开资料研究？

通过后才将 slug 加入日报 `deep_dive_refs`，无成熟专题写 `[]`。清单内文件无效会阻止 finalize，修复或明确延期后再重跑；磁盘上的草稿、旧文件和 major_event 本身都不会触发发送。历史 1.0 专题可重渲染，进入新投递清单前需按新研究标准重做。继续使用原有渲染、归档、邮件幂等链路，不直接单封发信。

每日晨报仍执行 `dingtalk-daily.md` 的全文复制、同日去重与回读；本工作流不自动增加专题的钉钉发布范围。
