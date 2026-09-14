# 07: 打包发布——AurumWatch.exe

**What to build:** 用 PyInstaller 单文件模式构建出 `AurumWatch.exe`（带图标、无控制台窗口）：构建脚本入库、可重复执行，图标以代码生成（不引图像库）。产物拷到**未安装 Python 的电脑**上双击即用：行情上屏、越线弹窗、设置与预览、单实例、开机自启全部正常，`config.json` 与 `logs/` 在 exe 旁自动生成与读写。仓库文档同步改为 GUI 应用口径，`.bat` 定位为开发入口。

**Blocked by:** 01–06 全部

**Status:** ready-for-human（打包、产物验收与文档都做完了；剩下两步只能人来：拿第二台电脑实测「未装 Python 的机器」，以及在真机上点一次[设置]。见 Comments 末尾）

- [x] 构建脚本可重复执行，产出 `dist/AurumWatch.exe`（带图标、双击无控制台窗口）
- [ ] 在未安装 Python、未装 conda 的电脑上双击可运行：行情上屏、越线弹窗、设置窗口与预览均可用（本机用替身验齐：干净环境启动、依赖闭包核查、打包形态下的设置窗口与预览、配置写回；**只差第二台真机那一次**）
- [x] 该机器上 `config.json` 与 `logs/` 在 exe 旁自动生成、读写正常；config.json 拷走时设置跟随
- [x] 发布产物上单实例有效：重复双击不跑出两份
- [x] exe 放在只读目录（如 `Program Files`）时的表现有明确说明（写不进配置时给出提示而非崩溃）
- [x] CLAUDE.md 的运行/测试章节与 .bat 说明更新为 GUI 应用口径
- [x] `dist/`、`build/`、`logs/` 加入 .gitignore

## Comments

实现记录（2026-09-14）：

- **构建脚本** `tools/build.py`：一次运行做完「画图标 → 交给 PyInstaller → 核对产物」；`--onefile --noconsole --icon build/aurumwatch.ico --paths <仓库根>`，入口是包自己的 `aurumwatch/__main__.py`（与源码运行同一个），中间物（workpath 与 .spec）全落在 `build/`，产物在 `dist/`。构建前先删掉上一次的 `dist/AurumWatch.exe`——构建没走完时不会留一个「看起来像成功」的旧产物。缺 PyInstaller 时给出一条安装命令就退，不让 PyInstaller 的报错来兜底。
- **图标** `tools/icon.py`（纯标准库）：金币 + 上行折线。形状全按**有向距离场**算——距离直接换覆盖率，边缘天然抗锯齿，不必按几倍超采样铺像素（256 那一档省下的时间最明显，全部 7 档跑完 1 秒）。交付多尺寸 ICO（16/24/32/48/64/128/256，32 位 DIB + AND 掩码），Explorer 每种视图各取所需。
- **踩到并修掉的一个真坑：装错了 OpenSSL**。第一版产物构建一路成功，**在没装 Python 的机器上却是「取数失败：Can't connect to HTTPS URL because the SSL module is not available」**——PyInstaller 找不到 DLL 时顺着 PATH 找，而 Git Bash 的 PATH 里 `Git\mingw64\bin` 排在本环境 `Library\bin` 前面，于是 conda 的 `_ssl.pyd` 配上了一份 Git 自带的 OpenSSL。本机跑还看不出问题（本机 PATH 里的 conda 目录能兜住）。修法：构建脚本把 `sys.prefix\Library\bin` 排到 PATH 最前，交给 PyInstaller 的那个子进程；修完 `Analysis-00.toc` 里 74 个二进制的来源全在本环境或 System32（Git 一条都没有）。
- **依赖闭包核查**（静态）：产物里每个二进制/扩展的导入表都过了一遍，除 `api-ms-win-core-path-l1-1-0.dll`（Windows 8+ 的 API set，不是实体文件）外，没有「既不在产物里、System32 里也没有」的依赖；`VCRUNTIME140.dll`／`ucrtbase.dll`／`libssl`／`libcrypto`／`tcl86t.dll`／`tk86t.dll`／`_tk_data\ttk\*.tcl` 都在归档里。exe 子系统是 2（GUI）——「双击无控制台」由此定死。
- **产物验收**（`D:\App\Temp\aurum-exe-test\` 下的临时脚本与截图，不入库；行情上屏、两个越线弹窗、配置跟随这三条在**最后那一版产物**上又整跑了一遍，见 `final-*.png`）：
  - **在「没有 Python」的环境里跑**：把 PATH 收成 `C:\Windows\System32;C:\Windows`、去掉全部 `PYTHON*`／`CONDA*`，把 exe 拷到一个新目录再启动——行情上屏（国内 932.80 元/克、国际 4313.70 美元/盎司）、状态「监视中」、`config.json` 与 `logs/` 在 exe 旁生成、日志有「启动」与「配置：未找到配置文件，已按默认值生成」两条。
  - **越线弹窗**：给一份「拷来的」config.json（两个市场的涨破阈值都压在现价下方、底色换成紫的），第一轮就触发——两个弹窗落在工作区右下角（右、下各留 24px）上下叠放，弹窗上是紫底、涨破色标题、现价/阈值/行情时间/「点击关闭 · 30 秒后自动消失」，与源码运行逐项一致。
  - **配置跟随**：上面那份 config 的颜色与阈值都生效了（截图里主窗口是紫底、卡片上写着「涨破阈值 900.00…已触发」），且程序没有把它改回默认——「exe + config.json 一起拷」这条成立。
  - **单实例**：同一份产物连开三次，后两次退出码 0、进程表里始终只有一份监视、窗口不多、日志一行不加（连日志都不开）。
  - **只读目录**：给目录加一条拒绝写入的 ACE（跑完撤掉），exe 照常启动、照常监视，事件记录里两条说明——「配置：未找到配置文件，也写不进去（Permission denied），本次按默认值运行」「日志写不进去（Access denied），本次运行的事件只留在窗口里」；目录里没留下任何东西，也没崩。这条行为已写进 CLAUDE.md。
  - **图标**：`pefile` 把 exe 的 `RT_ICON` 1–7 逐个抠出来，与 `build/aurumwatch.ico` 的七档**逐字节比对，全一样**（`probe_archive.py` 里那次只比了 256 一档、且是容差 8 的像素比对，不算数——口径以这条为准）。子系统 2（GUI）另证一次「无控制台」。
  - **打包形态下的设置窗口与预览**：本机锁屏、点不动（见下），于是用**一次性入口**再打一个 exe——同一套 PyInstaller 参数，只把入口换成「开机就开设置窗口、量一遍再自己关掉」（`settings_probe_entry.py`，不入库）。同一份 config 下，打包形态与源码形态的取证**逐项相同**：ttk 主题 7 个（当前 clam）、字体 507 个（有 Microsoft YaHei UI）、Tcl 8.6.13、设置窗口 2188x1125、**预览卡片 502x330**、三个样例齐。截图（`probe-设置.png`）里阈值/高级/外观/提示音四组、四个取色块、字体下拉、四角单选、1:1 预览卡片与[保存][取消][恢复默认]都在。
  - **打包形态下的配置写回**（同一探针，`PROBE_ACTION=save`）：改一个阈值为 `950.00` → 按[保存] → 窗口自己关了（保存成功的表现），`config.json` 里出现 `950.00`、654 字节；再开一扇设置窗口，阈值框里还是 `950.00`——**写入与回读在产物上都成立**。
  - **打包形态下的自启谓词**（同一探针）：`packaged()` 为真、`exe_path()` 就是本次运行的 exe（不是 python.exe）、`command_line()` 是**带引号的绝对路径**、[开机自启]开关**可用（没置灰）**、初值未勾。注册表那一步**没写真表**——换了内存替身，记下这一笔「本来会写什么」（`set_enabled(False)`，即未勾选＝删掉那一项）。
- **文档**：CLAUDE.md 改成 GUI 应用口径——运行章节先说「开发：从源码跑」，双击 .bat 明确为开发期快捷方式（用户手上那份是**发布产物**）；新增「打包（发布）」章节与只读目录的注意事项；测试章节注明只盖纯函数层、其余靠手动验收；环境章节区分运行期（`requests`）与构建期（`pyinstaller`）。`.gitignore` 补 `dist/`、`build/`（`logs/`、`config.json` 本来就在）。
- **设置窗口那一下点击没验成（环境所限，不是打包问题）**：本轮开发机全程锁屏（前台是 LockApp），真鼠标进不去。合成点击（PostMessage 到顶层框与 TkChild、带不带 WM_MOUSEMOVE）实测**源码运行与产物都一样没反应**——顺带说明这不是产物的毛病：给窗口发 `WM_CLOSE` 能正常退出并落日志，说明消息进得去，只是 Tk 在窗口未激活时不接这类合成鼠标事件。**更正**：先前几轮探针按 `"AurumWatch 设置"` 找窗口，而设置窗口的标题就是「设置」（`settings_window.WINDOW_TITLE`），判据本身是错的；改对判据重做后结论不变（弹窗点不关、[设置] 点不开），两次都在场。
- **评审（Standards / Spec 两条轴各一遍）**：
  - **Standards** 提的都落地了：① 术语漂移——CLAUDE.md 与 .gitignore 里我写成「打包产物」，CONTEXT.md 定的是**发布产物**（并明写避免「打包版」），已改；② `_speak_utf8` 只管 stdout，而出错那两句（没装 PyInstaller、构建失败）走的是 stderr——改成两个都管，名字也改成说得清的 `_use_utf8_output`；③ 产物路径打两遍——合并成一句；④ `ico_bytes`／`write_ico` 的 `sizes` 参数没有调用方传值（Speculative Generality）→ 去掉，直接用 `SIZES`；⑤ 三处 `min(1.0, max(0.0, …))` 收敛成 `_clamp`；⑥ 图标里那两个颜色与 `config.py` 的默认外观同色却没写明 → 注释点了名。**不改的**：`_render` 里那组几何系数（0.46／0.05／0.09／0.08）留在函数内——它们从 `size` 派生、就地起名并带注释，提到文件顶部反而把一处设计摊成两处；`_dib(pixels, size)` 同时收两个是省一次开方。
  - **Spec** 指出的缺口逐个补了：① **打包形态下的开机自启**此前一字未验——补了上面的自启谓词取证（真注册表那一笔仍没跑，见下）；② **CLAUDE.md 测试章节**只改了一半——补上「只盖纯函数层、其余手验」；③ **产物上的配置写回**没有证据——补了 `PROBE_ACTION=save` 那一条；④ Status 措辞曾读起来像硬门槛已过——改成 `ready-for-human` 并写明剩哪两步；⑤ 探针的判据错误（标题找错）——已更正并重做；⑥ 评审保留的脚本与截图在临时目录、不入库（与 ticket 06 的先例一致），所以结论里都附了**怎么复现**：干净环境启动＝把 PATH 收成 `C:\Windows\System32;C:\Windows` 并清掉 `PYTHON*`／`CONDA*` 后从新目录启动 exe；依赖闭包＝读 `build/AurumWatch/Analysis-00.toc` 的 binaries，对每个文件跑 `pefile` 取导入表，逐个减去产物内文件名与 `C:\Windows\System32` 的 DLL 名单；图标＝`pefile` 读 `RT_ICON` 与 ICO 逐档比对。
- **剩下两步（只能人来）**：
  1. **第二台真机的实测**：本机没有别的 Windows 环境（Windows Sandbox 未安装，本机的 Python/conda 又到处都是），所以「未装 Python 的机器」这条用的是替身（干净环境 + 静态核查 + 上面的逐项验收）。真机那一次：把 `dist/AurumWatch.exe`（连同 `config.json`，要的话）拷过去双击，看行情上屏、越线弹窗、设置与预览。
  2. **真机上的[设置]那一下**（可选）：机器解锁后点一次就知道，或由用户口头确认。
  3. 另有一件**没做**、要用户点头才做的事：**在打包产物上真写一次开机自启**（往当前用户 Run 键写一条指向 exe 的启动项，验完删掉）。本轮验到「谓词与命令都对、开关可用」为止——替用户改自启动这件事，等一句明确授权。
- **已知风险（不在本票范围，留个话）**：主窗口与任务栏图标仍是 Tk 自带的羽毛——票面的「带图标」只要求 exe（资源管理器里那个），运行时窗口图标没动。要一并换成金币的话说一声，`tools/icon.py` 现成，加一段 `iconphoto` 即可。
- **顺带说明**：构建期在 aurum 环境装了 PyInstaller（`pip install --no-user pyinstaller`，6.22.3）——仅构建期依赖，不进产物、不进运行期。构建产物不是逐字节可复现的（PyInstaller 每次会写进时间戳一类的东西），「可重复执行」指每次都从干净状态跑通、产出同一份可运行的东西。
