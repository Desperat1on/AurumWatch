# AGENTS.md

本仓库的 agent 入口文件。

## 项目指令

运行、打包、测试、环境的说明以 [`CLAUDE.md`](CLAUDE.md) 为单一来源（Claude Code 也读它）。本文件不重复其内容。

## Git 工作流

本项目采用 Git Flow。分支职责、禁止行为、以及**每次任务开始前**必须执行的检查步骤见 [`docs/git-flow.md`](docs/git-flow.md)。除非用户明确要求，不得绕过。

## 其他 agent 文档

- Issue tracker（`.scratch/<feature>/` 下的 markdown 票）：[`docs/agents/issue-tracker.md`](docs/agents/issue-tracker.md)
- Triage labels：[`docs/agents/triage-labels.md`](docs/agents/triage-labels.md)
- Domain docs（`CONTEXT.md` 与 `docs/adr/`）：[`docs/agents/domain.md`](docs/agents/domain.md)
