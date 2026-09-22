# 每日晨报同步到钉钉在线文档

此工作流用于用户已授权的“AI日报晨报”定时任务。独立的手动生成、dry-run、历史补齐和周报不会因此自动获得钉钉发布授权。

## 目标与标题

- 目标目录：`https://alidocs.dingtalk.com/i/nodes/qnYMoO1rWxD46rbMH9zlryOvW47Z3je9`
- 已核验名称：`AI信息晨报`
- 目录 nodeId：`qnYMoO1rWxD46rbMH9zlryOvW47Z3je9`
- workspaceId：`O2RXDJLqWMYjNGZj`
- 文档标题：`AI 晨报 · {YYYY-MM-DD}`，日期按 Asia/Shanghai。
- 每日一篇可编辑的在线文档。权限继承目标目录，不新加成员，不另发群消息。

## 前置与内容

1. 阅读 `/Users/liuyingjie/.agents/skills/dws/SKILL.md` 及 doc URL 分流、创建和回读说明。只用 `dws` 操作钉钉；每条命令加 `--format json`，实际参数以当前 leaf schema 和 help 为准。不要打印认证信息。
2. 正常执行日报生成、完整校验、渲染和原有邮件流程。只有最终日报内容通过校验，才能同步；校验失败不能发布草稿。邮件成功和钉钉成功分别报告：若仅邮件发送失败而最终正文已通过校验，仍可同步钉钉，保留邮件失败信息。
3. 新建本地目录 `reports/dingtalk/{date}/`。用仓库已有转换器从同一份最终 HTML 生成在线版：

   `.venv/bin/python skills/ai-daily-report/scripts/render_markdown.py cache/{date}/report.html --output reports/dingtalk/{date}/report.md`

   内容继承最终 HTML，保留全部栏目、模型评测、测试条件、分数、对照、缺口和外部来源链接，不重新摘要。导航和抓取诊断不进在线正文。需要人工补充说明时只修正发布状态措辞，不更改事实。
4. 核对 Markdown 全部栏目、末段和所有模型指标存在，检查 UTF-8 大小。阅读开头的“今日核心判断”，确认模型的能力定位、相关对照、成本和适用任务足够明确，数字能在正文找到来源；不能只留模糊评价和免责声明。标题必须为 H1 报告 → H2 栏目 → H3 模型/事件 → H4 能力评测 → H5 评测分组，不能同级平铺；导读不重复完整新闻标题。内置创建命令支持 `--content-file`，优先一次完整写入；超过 dws 文档工作流所规定的大小边界时，按其要求处理，不自行截断。旧 `doc_create_and_write.py` 无持久化去重/回读台账且会先建空文档再追加，本流程使用 doc 原生命令并保存每步回执。

## 目标确认与同日去重

5. 先执行 `dws doc info --node <目标目录URL> --format json`，确认 nodeType=folder，目录 nodeId 和 workspaceId 符合目标；不匹配则停止，不能改投“我的文档”。
6. 读取 `reports/dingtalk/{date}/publication.json`（存在时）并回读其中 nodeId，核对标题、父目录和内容。没有完整台账或上次创建结果不确定时，使用：

   `dws drive list --workspace O2RXDJLqWMYjNGZj --folder qnYMoO1rWxD46rbMH9zlryOvW47Z3je9 --limit 30 --format json`

   按 `hasMore / nextCursor` 翻页到结束，查找完整同名标题；不要仅因本地缺台账就再次创建。
7. 已存在唯一同日且内容完整的文档：复用链接，补齐台账后结束同步。多篇同名、人工改动、源内容与已发布版本不同或部分写入时，不自动整篇覆盖、不盲目重建；保留现场并明确报告需要处理的差异。对本流程未完成的文档，仅在回读确定缺失片段后补写该片段并再次核对。

## 创建与验收

8. 确定不存在同日文档后：先落 `publication.json`，状态 `creating`，记录日期、目标目录、标题和本地 Markdown 的 SHA-256。执行一次：

   `dws doc create --name "AI 晨报 · {date}" --folder qnYMoO1rWxD46rbMH9zlryOvW47Z3je9 --workspace O2RXDJLqWMYjNGZj --content-file reports/dingtalk/{date}/report.md --format json`

   保存创建回执，立即把真实返回的 nodeId/链接写入台账，状态 `created_unverified`。创建超时/结果不明先查目录，不直接重试创建。
9. 执行 `dws doc info --node <返回nodeId> --format json`：必须是 `ALIDOC / adoc`，父目录必须是上述目标。再执行 `dws doc read --node <返回nodeId> --format json` 并保存回读结果。
10. 将回读内容与本地正文比对：全部栏目顺序、正文段落、来源链接、每项分数/对照/单位以及末尾内容完整；允许 Markdown 空格和表格格式归一化，不允许内容截断。同时执行 `dws doc block list --node <nodeId> --format json`，完整保存为 `blocks_after.json`，不能只看 Markdown 中有标题文字便通过。执行：

    `.venv/bin/python skills/ai-daily-report/scripts/validate_dingtalk.py <本次最终HTML路径> reports/dingtalk/{date}/blocks_after.json`

    它从最终 HTML 重算完整标题大纲，与钉钉原生块的标题文字、顺序和级别逐一比对；分页未读完不能通过。内容比对和大纲校验都成功，才写台账状态 `verified`，保存 nodeId、链接、标题、目录、源文件 SHA-256、回读时间和校验结果。失败保留 `created_unverified`，不得自报成功。确认是本次导入造成的标题降级或字面 Markdown 标记时，按 DWS 工作流局部修正后重新回读，不重建同日文档；已有人工改动则保留并报告差异。
11. 终端分别报告邮件结果、钉钉结果与可点击文档链接。钉钉失败不撤销已经成功的邮件，也不重新发送它。

台账放在 `reports/dingtalk/`，不放会定期清理的 cache；不使用 email send_state 代替钉钉发布状态。本工作流不修改定时频率。
