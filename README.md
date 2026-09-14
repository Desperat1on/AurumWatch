# AurumWatch

Windows 桌面上的金价监视器。盯着国内、国际两个市场的金价，越过你设的阈值就在屏幕角落弹窗提醒。

交付形态是**免安装的单文件 exe**：拷到任意 Windows 电脑双击即用，不需要 Python，也不需要 conda。`config.json` 与 `logs/` 在 exe 旁自动生成。

## 功能

- **两个市场** —— 国内金价（上海黄金交易所 Au99.99）与国际金价（伦敦现货黄金 XAU/USD），各自独立判定、互不干扰
- **四个阈值** —— 每个市场各设「涨破」与「跌破」两个价位，可以只设其中一个
- **穿越触发** —— 同一阈值触发后，价格须回到另一侧并越过一小段缓冲（默认阈值的 0.1%）才重新具备触发资格。价格在阈值附近来回蹭时不会反复弹窗
- **弹窗提醒** —— 屏幕角落弹出、不抢焦点、点击关闭、到点自动消失（默认 30 秒），可带提示音
- **故障不误报** —— 某个市场取不到数只影响它自己，出故障的轮次不参与判定，不会拿旧价格去比；连续故障满 10 分钟弹一次窗告知「监视已失效」，恢复后重新计时
- **事件记录与日志** —— 主窗口显示近期事件；另有按天分文件的日志保留 30 天，供事后回查
- **设置窗口** —— 改阈值、外观、音效，带 1:1 的弹窗预览：预览长什么样，真弹窗就长什么样
- **单实例与开机自启** —— 重复启动只唤起已有窗口；开机自启可在设置里开关
- **记住窗口位置** —— 下次打开回到上次关闭的位置；显示器换了或分辨率变了会把窗口拉回屏幕内

## 从源码运行

需要一个 Python 3 环境（开发所用为 3.13），运行期只依赖 `requests`：

```bash
pip install requests
python -m aurumwatch
```

## 打包成单文件 exe

```bash
pip install pyinstaller
python tools/build.py
```

产出 `dist/AurumWatch.exe`：单文件、带图标、无控制台窗口；中间物落在 `build/`。构建期需要 PyInstaller，运行期不需要。

图标由 `aurumwatch/icon.py` 用代码画出来（不引图像库）：形状按有向距离场算，构建时出多尺寸 ICO 交给 PyInstaller，运行时现画一张 PNG 交给 Tk，不落盘——exe 放在写不进去的目录里也照样有图标。

> **别把 exe 放进 `Program Files` 这类写不进去的目录。** `config.json` 与 `logs/` 就写在它旁边。写不进去时程序照常启动与监视，只是主窗口的事件记录里会说明「配置/日志写不进去」，保存设置时也会报「保存失败」——不崩，但那台机器上改不了设置、也留不下日志。

## 配置

首次运行在 exe 旁生成 `config.json`。除了在设置窗口里改，也可以直接编辑它（保存时整个文件会被重写，窗口位置也在其中）。

| 项 | 默认 | 说明 |
| --- | --- | --- |
| `advanced.refresh_interval` | `60` | 取数间隔（秒），允许 5–3600 |
| `advanced.rearm_ratio` | `0.001` | 重新武装带的宽度，按阈值的比例 |
| `advanced.failure_warn_minutes` | `10` | 连续故障多久后弹窗告知监视失效 |
| `advanced.alert_on_start` | `true` | 启动时若价格已越线，是否立即提醒 |
| `appearance.popup_seconds` | `30` | 弹窗停留秒数 |
| `appearance.popup_corner` | `bottom-right` | 弹窗出现在屏幕哪个角 |
| `appearance.bg` / `fg` | `#1e1f22` / `#f0f0f0` | 背景色与文字色（`#rrggbb`） |
| `appearance.rise` / `fall` | `#e5534b` / `#3fb950` | 涨破色与跌破色 |
| `appearance.font` / `base_size` | `Microsoft YaHei UI` / `10` | 字体与基准字号，其余字号由基准派生 |
| `sound.enabled` / `choice` | `true` / `system` | 提示音开关；系统提示音或自定义 WAV |
| `thresholds.*.up_threshold` / `down_threshold` | `null` | 各市场的涨破／跌破阈值，未设即不判定 |

## 项目结构

```
aurumwatch/          应用本体
  quotes.py          取数与解析（唯一发网络请求的地方）
  alerts.py          穿越触发判定（纯函数）
  failures.py        取数故障记账与故障警告（纯函数）
  viewmodel.py       一轮取数结果 → 窗口要显示的一切（纯函数）
  schedule.py        刷新与提醒的时序对齐（纯函数）
  config.py          配置读写、规范化与校验
  app.py             编排：主窗口 + 取数线程 + 队列
  main_window.py     主窗口
  settings_window.py 设置窗口与 1:1 预览
  popup.py           角落弹窗
  theme.py           外观：由六个可调项派生配色与字号
  journal.py         事件记录与按天日志
  icon.py            图标（代码绘制）
  autostart.py       开机自启（注册表 Run 项）
  single_instance.py 单实例
tools/build.py       打包脚本
tests/               纯函数层单元测试
docs/                分支模型与架构决策（ADR）
.scratch/            开发期的 spec 与工单
CONTEXT.md           领域术语表
```

## 开发

```bash
python -m unittest discover -s tests    # 单元测试
python -m ruff check .                  # 静态检查
python -m ruff format .                 # 排版
```

测试只盖**纯函数层**（触发判定与故障记账、配置规范化与校验、解析与刷新对齐、视图模型）。窗口的观感与交互、预览与真实弹窗是否一致、取数、单实例、开机自启、打包产物都在缝外，靠手动验收。

分支模型见 [`docs/git-flow.md`](docs/git-flow.md)：`master` 是发布线，`develop` 是集成线，功能走 `feature/*`，发布走 `release/*`，线上修复走 `hotfix/*`。

版本号在 `aurumwatch/__init__.py` 的 `__version__`，全项目唯一一处，在 `release/*` 分支上提升。窗口标题栏、启动那行日志与 exe 的属性页都读它——三处不会各说各话。

## 数据来源

行情取自新浪财经的公开行情接口（`hq.sinajs.cn`）。程序不做任何上报、不连第三方服务，除该接口外不发起任何网络请求。

## 许可

[MIT](LICENSE) © 2026 Desperat1on
