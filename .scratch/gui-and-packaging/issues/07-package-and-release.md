# 07: 打包发布——AurumWatch.exe

**What to build:** 用 PyInstaller 单文件模式构建出 `AurumWatch.exe`（带图标、无控制台窗口）：构建脚本入库、可重复执行，图标以代码生成（不引图像库）。产物拷到**未安装 Python 的电脑**上双击即用：行情上屏、越线弹窗、设置与预览、单实例、开机自启全部正常，`config.json` 与 `logs/` 在 exe 旁自动生成与读写。仓库文档同步改为 GUI 应用口径，`.bat` 定位为开发入口。

**Blocked by:** 01–06 全部

**Status:** ready-for-agent

- [ ] 构建脚本可重复执行，产出 `dist/AurumWatch.exe`（带图标、双击无控制台窗口）
- [ ] 在未安装 Python、未装 conda 的电脑上双击可运行：行情上屏、越线弹窗、设置窗口与预览均可用
- [ ] 该机器上 `config.json` 与 `logs/` 在 exe 旁自动生成、读写正常；config.json 拷走时设置跟随
- [ ] 打包产物上单实例有效：重复双击不跑出两份
- [ ] exe 放在只读目录（如 `Program Files`）时的表现有明确说明（写不进配置时给出提示而非崩溃）
- [ ] CLAUDE.md 的运行/测试章节与 .bat 说明更新为 GUI 应用口径
- [ ] `dist/`、`build/`、`logs/` 加入 .gitignore
