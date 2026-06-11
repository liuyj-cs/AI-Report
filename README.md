# AI Report

一个给 Codex 用的本地 skill。它通过自然语言请求或 `/ai-daily`、`/ai-weekly` 这类触发词生成 AI 行业日报 / 周报，并通过 Gmail SMTP 发送到邮箱。

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

- `skills/ai-daily-report/SKILL.md`：工作流与判断规则
- `skills/ai-daily-report/sources/whitelist.yaml`：信源白名单
- `skills/ai-daily-report/scripts/`：渲染、归档、发信脚本
- `skills/ai-daily-report/tests/`：render/archive 回归测试
- `cache/tracking/`：重大事件追踪档案（最长 5 天有效期，驱动跨日追踪报道，运行时生成）
- `skills/ai-daily-report/sources/profile.yaml`：读者画像（角色、在途决策、实践关注点）
- `cache/seen_repos.json`：生态板块已收录仓库台账（30 天冷却，运行时生成）
