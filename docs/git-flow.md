# Git Flow 工作流规则

本项目采用 Git Flow 分支模型。除非用户明确要求，否则不得绕过以下规则。

## 本仓库的具体约定

- 正式发布分支叫 **`master`**（本仓库没有 `main`）。下文出现的「main / master」一律读作 `master`。
- 集成分支叫 **`develop`**。
- 分支前缀与 tag 前缀已写入 git-flow 配置：`feature/`、`release/`、`hotfix/`，发布 tag 形如 `v0.1.0`。
- 版本号在 `aurumwatch/__init__.py` 的 `__version__`，**全项目唯一一处**；在 `release/*` 分支上确认并提升。窗口标题栏、启动日志与 exe 的属性页都读它。
- **本仓库没有配置任何远程**。「push 到远程」「远程同步状态」相关的规则当前无对象可施；一旦加上远程，它们立即生效。

## 分支职责

- **main / master**：正式发布分支，只保存稳定版本。禁止日常开发直接提交。
- **develop**：日常开发集成分支。所有普通功能完成后先合并到 develop。
- **feature/***：功能开发分支，必须从 develop 拉出，完成后合并回 develop。
- **release/***：发布准备分支，必须从 develop 拉出，只允许发布前 bug 修复、配置调整、版本号调整和文档更新。发布后必须同时合并到 main/master 和 develop，并在 main/master 打 tag。
- **hotfix/***：线上紧急修复分支，必须从 main/master 拉出。修复完成后必须同时合并到 main/master 和 develop，并在 main/master 打补丁版本 tag。

## 禁止行为

- 不得直接在 main / master 上开发。
- 不得直接在 develop 上开发具体功能。
- 不得在 release/* 分支开发新功能。
- 不得执行 `git push --force`，除非用户明确确认。
- 不得执行 `git reset --hard`、`git rebase`、删除分支、删除 tag 等破坏性操作，除非用户明确确认。
- 不得在未查看 `git status`、当前分支和远程同步状态前执行合并或提交。

## 每次任务开始前必须执行

1. 查看当前分支和工作区状态。
2. 判断当前任务类型：
   - **新功能**：创建或切换到 `feature/*`
   - **发布准备**：创建或切换到 `release/*`
   - **线上紧急修复**：创建或切换到 `hotfix/*`
   - **普通问题修复**：优先走 `feature/*`，除非明确属于发布分支或 hotfix
3. 向用户说明建议使用的分支名和原因。
4. 在未得到用户确认前，不得 push 到远程。

## 提交要求

- 每次提交只包含同一主题的修改。
- 提交信息必须清楚描述修改内容。
- 修改代码后必须运行可用的测试、格式化或静态检查命令。
- 如果无法运行测试，必须说明原因。

## 本仓库的命令

git-flow（AVH Edition 1.12.3）已安装并配置完毕，可直接使用：

```bash
git flow feature start <name>     # 从 develop 拉出 feature/<name>
git flow feature finish <name>    # 合回 develop：1 个提交就快进，2 个及以上留合并点
                                  # 默认删掉该分支，要保留加 -k

git flow release start 0.1.0      # 从 develop 拉出 release/0.1.0
git flow release finish 0.1.0     # 合入 master + 打 tag v0.1.0 + 回合并 develop

git flow hotfix start 0.1.1       # 从 master 拉出 hotfix/0.1.1
git flow hotfix finish 0.1.1      # 合入 master + 打 tag v0.1.1 + 回合并 develop
```

三个 `finish` 的合并方式不一样（规则取自 git-flow 1.12.3 的脚本本身）：

| 命令 | 合并方式 |
| --- | --- |
| `feature finish` | 分支上**只有 1 个提交就快进**，**2 个及以上生成合并点** |
| `release finish` | 一律 `--no-ff`（合入 master 与 develop 都是） |
| `hotfix finish` | 一律 `--no-ff`（合入 master 与 develop 都是） |

本仓库用默认，不去动 `gitflow.feature.finish.no-ff`。想让 feature 一律留下合并点，把它设成 `true`，或者每次显式传 `--no-ff`。

测试与静态检查命令见 `CLAUDE.md` 的「测试」「静态检查」两节。
