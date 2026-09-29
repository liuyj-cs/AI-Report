# AI Report

一个给 Codex 用的本地 skill。它通过自然语言请求或 `/ai-daily`、`/ai-weekly` 这类触发词生成 AI 行业日报 / 周报，并通过 Gmail SMTP 发送到邮箱。

此 skill 仅在本仓库安装：`.agents/skills/ai-daily-report` 通过相对软链接指向 `skills/ai-daily-report`，由 Codex 按仓库作用域发现；工作流和脚本仍维护在原目录。不要把它安装或链接到用户级 skill 目录。

自动任务应绑定 AIReport 项目，在仓库根目录运行，并显式读取 `skills/ai-daily-report/SKILL.md`。这样日报和周报都不依赖全局 skill 安装；现有脚本、`.env`、缓存和归档路径保持有效。

每日“AI日报晨报”任务生成并校验最终正文后，保留原有邮件投递，同时将完整晨报新建为“AI信息晨报”目录下的钉钉在线文档。按日期去重、回读确认正文完整，独立记录两处投递结果。详见 [钉钉同步工作流](skills/ai-daily-report/workflows/dingtalk-daily.md)。

## 快速开始

1. 复制 `.env.example` 为 `.env`，填写收件邮箱：

        cp .env.example .env

2. 安装 Python 依赖：

        cd skills/ai-daily-report
        python3 -m venv .venv
        source .venv/bin/activate
        pip install -r requirements.txt

3. 在仓库根目录准备 `.env`，填写 Gmail SMTP 发信账号和收件人。

4. 在 Codex 中直接提需求：
   - `生成今天的 AI 日报`
   - `生成本周 AI 周报`
   - `dry run 跑一下今天的日报`
   - `生成上周的 AI 周报`（建议每周一上午跑，聚合上一 ISO 周 7 天日报）

## 目录

- `.agents/skills/ai-daily-report`：仓库级 skill 发现入口（指向下述目录的相对软链接）
- `skills/ai-daily-report/SKILL.md`：工作流与判断规则
- `skills/ai-daily-report/sources/whitelist.yaml`：信源白名单
- `skills/ai-daily-report/scripts/`：渲染、归档、发信脚本
- `skills/ai-daily-report/tests/`：render/archive 回归测试
- `cache/tracking/`：重大事件追踪档案（最长 5 天有效期，驱动跨日追踪报道，运行时生成）
- `skills/ai-daily-report/sources/profile.yaml`：读者画像（角色、在途决策、实践关注点）
- `cache/seen_repos.json`：生态板块已收录仓库台账（30 天冷却，运行时生成）
- `cache/{date}/hard_data_snapshot.json`：硬数据当日快照（运行时生成，`hard-data-delta` 用它算跨日变化）
- `cache/{date}/send_state.json`：逐收件人投递台账（运行时生成；已接收者跳过，部分接收只补未接收者，结果未知阻断重发）
- `cache/delivery_state/interviews/send_state.json`：访谈跨日投递台账（key 为 `interview:{slug}`）
- `reports/dingtalk/{date}/`：在线版 Markdown、钉钉创建与回读回执、持久化发布台账

## 晨报阅读质量

新日报使用 1.2 格式：模型正文包含分项评测、对照模型、测试条件、成本和能力边界，开头的“今日核心判断”直接说明能力位置、性价比和适用任务。HTML 与钉钉按栏目、模型、评测逐级展示，在线发布需回读验证原生标题层级。历史日报 1.0/1.1 仍可读取；新候选台账 1.1、新周报 1.1。新增“政策与风险观察”，通用与办公 Agent 按任务变化呈现，完整留存采集结果并校验行动依据。详见 [编辑质量契约](docs/report-editorial-quality.md)。

独立专题按需生成：重大事件继续补证和追踪，有成熟的选择问题与新增判断才进入日报 `deep_dive_refs` 投递清单。新专题采用 1.1 研究格式，旧专题保留重渲染；具体标准见 [专题研究工作流](skills/ai-daily-report/workflows/deep-dive-research.md)。专题取舍不影响每天晨报的钉钉全文同步。

## 采集与发送校验

AI HOT 使用 `all + 7d + published` 发现候选，按日报锁定窗口筛选，并由保存的真实响应重算分页覆盖。它仍是经过上游过滤的公开池；未翻完、请求失败与空结果分别记录，不能据此断言行业没有新闻。详见 [AI HOT 采集工作流](skills/ai-daily-report/workflows/aihot-discovery.md)。

日报 finalize 必须读取初始化生成的 manifest，重算北京时间窗口并核对正文与候选台账的时间；核心源状态从实际抓取尝试重算，整链失败达到 4 个即停止归档和发送。新闻取舍、分类与行动判断仍由 AI 完成。

邮件通过统一台账入口发送，记录稳定 Message-ID、内容哈希及逐收件人结果。已确认接收后关闭连接超时不会重发；部分接收只续发未接收者，提交结果未知或台账损坏则停止，先核实后恢复。投递回执保留，不随 14 天普通缓存清理删除。`sent` 表示 SMTP 已接收，不是最终收件箱送达证明；不得删除台账或改投递 key 绕过阻断。单封恢复也必须指定原 `--state-dir` 和 `--state-key`，具体命令见 [Skill](skills/ai-daily-report/SKILL.md)。
