# AurumWatch

金价监视与阈值弹窗提醒。双击「启动金价监视.bat」运行，前台控制台窗口挂机，关闭窗口即停止。

## 运行

```bash
"D:/App/Anaconda/anaconda3/envs/aurum/python.exe" -m aurumwatch
```

双击场景走「启动金价监视.bat」（用环境内 python.exe 绝对路径，无需激活 conda）。

## 测试

```bash
"D:/App/Anaconda/anaconda3/envs/aurum/python.exe" -m unittest discover -s tests -v
```

## 环境

专用 Conda 环境 `aurum`（Python 3.13，`D:\App\Anaconda\anaconda3\envs\aurum`），第三方依赖仅 `requests`。

## Agent skills

### Issue tracker

Issues are tracked as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, with label strings equal to the role names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
