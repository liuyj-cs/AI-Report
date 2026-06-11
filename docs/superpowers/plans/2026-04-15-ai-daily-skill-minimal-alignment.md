# AI Daily Skill Minimal Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不增加脚本硬规则的前提下，补齐 Codex 版 AI 日报 skill 的执行姿态，使其更接近 Claude 版的实际召回与收口方式。

**Architecture:** 只修改 prompt/说明层，不改脚本、schema 或白名单结构。核心是把白名单明确为首轮覆盖起点，并补上证据驱动扩展与来源闭环要求。

**Tech Stack:** Markdown 文档、仓库级操作说明

---

### Task 1: 调整日报 skill 执行姿态

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md`

- [ ] **Step 1: 补充“白名单是起点不是上限”的说明**

在日报工作流的 fetch 阶段增加一段说明，明确 whitelist 只负责首轮覆盖，安静日或高信号实体出现时允许 AI 做一跳相邻官方面扩展。

- [ ] **Step 2: 补充“证据驱动扩展轮”说明**

在不引入 vendor-specific fallback 列表的前提下，增加 evidence-led expansion 描述，优先追 developer changelog、release notes、官方 docs、partner official announcement。

- [ ] **Step 3: 补充 provenance closure 与编辑自检**

增加正文条目必须能回溯到 `fetch_status.source_details` 的要求，并在 JSON 落盘前加入一段简短的编辑自检说明。

### Task 2: 调整仓库级提醒

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 1: 增加仓库级原则**

补一句仓库级提示，强调白名单是首轮覆盖起点，不是信息上限；当首轮稀薄时，AI 应沿高信号实体追一跳相邻官方面，但仍需保持来源可回溯。

### Task 3: 复核最小改动

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md`
- Modify: `AGENTS.md`

- [ ] **Step 1: 查看 diff**

Run: `git diff -- skills/ai-daily-report/SKILL.md AGENTS.md`
Expected: 仅出现 prompt/说明层修改，无脚本、schema、白名单结构变动

- [ ] **Step 2: 人工检查是否引入硬规则**

确认新增内容没有变成 vendor-specific 列表、固定 if/else 规则或脚本职责扩张。
