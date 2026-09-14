# AurumWatch

金价监视与阈值弹窗提醒（Windows 桌面应用）。交付形态是免安装的单文件 `AurumWatch.exe`——拷到任意 Windows 电脑（不需要 Python、不需要 conda）双击即用，`config.json` 与 `logs/` 在 exe 旁自动生成。运行后出现常驻主窗口，关闭主窗口即停止。

## 运行（开发：从源码跑）

```bash
"D:/App/Anaconda/anaconda3/envs/aurum/python.exe" -m aurumwatch
```

「启动金价监视.bat」是开发期的无控制台快捷方式（双击后不留黑窗，用环境内 `pythonw.exe` 绝对路径起进程，无需激活 conda）；看不到报错时改用上面的命令在终端里跑。用户手上那份是发布产物（见 CONTEXT.md），不是这个 .bat。

## 打包（发布）

```bash
"D:/App/Anaconda/anaconda3/envs/aurum/python.exe" tools/build.py
```

产出 `dist/AurumWatch.exe`（单文件、带图标、无控制台窗口），中间物落在 `build/`；两者都不入库。构建期需要 PyInstaller（`pip install --no-user pyinstaller`），运行期不需要。

图标由 `aurumwatch/icon.py` 以代码画出（不引图像库）：构建时出多尺寸 ICO 交给 PyInstaller（资源管理器里那个），运行时现画一张 PNG 交给 Tk（主窗口与任务栏、设置窗口共用一个类图标），不落盘——exe 放在写不进去的目录里也照样有图标。

**exe 别放在 `Program Files` 这类写不进去的目录**：`config.json` 与 `logs/` 就写在它旁边。写不进去时程序照常启动与监视，只是主窗口的事件记录里会说明「配置/日志写不进去」，设置窗口保存时也会报「保存失败」——不崩，但那台机器上改不了设置、也留不下日志。

## 测试

```bash
"D:/App/Anaconda/anaconda3/envs/aurum/python.exe" -m unittest discover -s tests -v
```

测试只盖**纯函数层**（触发判定与故障记账、配置规范化与校验、解析与刷新对齐、视图模型）。窗口的观感与交互、预览与真实弹窗是否一致、取数、单实例、开机自启、打包产物都在缝外，靠手动验收（见 spec 的 Testing Decisions）。

## 环境

专用 Conda 环境 `aurum`（Python 3.13，`D:\App\Anaconda\anaconda3\envs\aurum`）：运行期第三方依赖仅 `requests`，构建期另装 `pyinstaller`。

## Agent skills

### Issue tracker

Issues are tracked as markdown files under `.scratch/<feature>/` in this repo. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, with label strings equal to the role names. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
