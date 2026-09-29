# 晨报真实重跑问题修复与验证

本轮针对 [独立验收](../../reports/reviews/2026-09-28-live-rerun/independent-review.md) 暴露的问题修复。使用9月28日已采集的同一批证据与同一新闻窗口验证；没有重采扩窗、重发邮件或覆盖钉钉文档。原有未提交改动保留。

## 修改结果

- 日报1.2新增必填 `coverage_summary`，由编辑合并影响本期判断的来源限制，模板不再遍历每次抓取reason生成正文。详细limitations、失败和阅读记录仍留在审计数据。模型、编码和待核实空栏目保留各自empty_message；历史格式缺字段时仍有回退显示。
- `evidence.py read`每次只返回一个有大小限制的块，不生成完成回执。编辑核对真实工具输出后，通过独立ack调用重算比对；截断、内容修改或范围异常不能确认。完整性仍必须检查外层工具结果，不能将本地预生成值当作实际输出；程序不声称证明AI理解或禁止恶意伪造。
- 真实批次此前遗漏的导航片段，已在本会话用两个独立read调用补读17000..21000，并在后续调用确认。原运行记录保留在before及独立验收目录；修订稿使用已核对的历史区间与本次新回执重算。补读前模拟真实缺口能触发unread阻断，补读后通过。
- 经人工核对，六次只返回元信息的尝试改记error/access_gap，同批汇总同步修正；没有把完整收到元信息写成正文成功。飞书、悟空等真实外部来源缺口仍明确保留，不将其描述为已补齐。
- SKILL与专门工作流统一政策风险、行动依据和导读链接规则。原“AI日报晨报”自动任务已同步仓库版本契约、证据逐块确认、读者验收及投递版本边界；回读确认仅prompt及更新时间改变，原运行时间、状态、模型及项目保持不变。
- 日报/周报新增 `delivery_result.json`，区分dry_run、sent、skipped_existing、failed，并记录当前HTML哈希。今后发送成功时send_state保存实际HTML哈希；历史记录缺少哈希就保留未知，不用当前文件倒填。失败可能存在提交结果未知，不据此断言未送达。去重仍沿用原记录，不因哈希变化强制重发。

## 验证

最终测试数量、运行时间、真实稿校验、HTML/Markdown比较、保护文件和任务配置回读，以 [最终机器验证](../../reports/reviews/2026-09-28-rerun-fixes/final-verification.json) 为准；[全量测试日志](../../reports/reviews/2026-09-28-rerun-fixes/full-tests.txt) 保留完整结果。

回归覆盖大量审计记录不铺入正文、空栏原因保留、缺覆盖摘要拒绝、超大批次读取拒绝、实际截断或修改输出无法ack、中间块缺失不能complete，以及已发送后本地重生成不会改写历史投递哈希或触发重发。

同一份真实report和ledger通过完整校验，并执行finalize-daily --dry-run。新HTML归档与cache哈希相同；从该HTML再转出的Markdown逐字一致。手机390px宽度下已检查覆盖摘要与模型空态，无横向溢出。截图见 [覆盖摘要](../../reports/reviews/2026-09-28-rerun-fixes/mobile-coverage.png) 和 [空栏目](../../reports/reviews/2026-09-28-rerun-fixes/mobile-empty-state.png)。

对旧契约执行了含docs的全仓grep；命中保留为历史输出、历史补丁、旧方案或测试夹具，活跃实施记录的过度保证已修正。扫描与逐项分类见 [检查清单](../../reports/reviews/2026-09-28-rerun-fixes/retired-contract-inventory.json)。

## 使用与边界

- [修订后的本地晨报](../../reports/daily/2026-09-28.html)
- [同源全文Markdown](../../reports/reviews/2026-09-28-rerun-fixes/report.md)
- [本次投递状态](../../cache/2026-09-28/delivery_result.json)
- [原稿与自动任务配置备份](../../reports/reviews/2026-09-28-rerun-fixes/before/)

本轮没有发送邮件或调用钉钉发布。期间用户在另一thread明确要求替换钉钉文档，该任务已完成发布回读；本轮保留其发布台账并合并该线程的覆盖摘要，未恢复旧记录或重复发布。完整HTML哈希仍因本轮更新审计数据/生成时间而不同，不能把该发布哈希改写为当前值；正文一致性另行用保存的回读验证。详见 [并行发布记录](../../reports/reviews/2026-09-28-rerun-fixes/concurrent-publication.json)。证据文件可以重算，不代表来源已穷尽或模型必然理解；逐块输出的完整性仍需执行者核对。新的完整自动采集流程耗时尚未经下一次日常任务检验。本轮未提交或推送代码。
