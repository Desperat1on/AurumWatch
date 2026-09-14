# AurumWatch

金价监视与阈值弹窗提醒。双击「启动金价监视.bat」运行，出现常驻主窗口，关闭主窗口即停止。

## 运行

```bash
"D:/App/Anaconda/anaconda3/envs/aurum/python.exe" -m aurumwatch
```

双击场景走「启动金价监视.bat」：用环境内 `pythonw.exe` 绝对路径起进程（无需激活 conda），不留控制台窗口。看不到报错时改用上面的命令在终端里跑。

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
