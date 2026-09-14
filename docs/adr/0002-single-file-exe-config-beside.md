---
status: accepted
---

# 发布为单文件 exe，配置与它同目录

目标是「拷到别的电脑直接能用，不装任何环境」。用 PyInstaller 单文件模式（`--onefile --noconsole`）在 aurum 环境构建出单个 `AurumWatch.exe`；`config.json` 与 exe 同目录，首次运行自动生成默认值，设置页面的保存即写回该文件。换电脑时 exe + config.json 一起拷，设置跟着走。不做安装包：本机没有 Inno Setup / NSIS，且对个人工具来说绿色单文件比安装向导更贴合「拷了就用」。

## Considered Options

- 单目录（onedir）+ zip 分发：启动更快、杀软误报概率更低，但要求对方先解压，且总有人在压缩包预览里直接双击而失败。
- 配置放 `%APPDATA%\AurumWatch\`：升级 exe 不覆盖配置，但换电脑带不走设置，与「拷贝即用」相悖。

## Consequences

- exe 不能放在 `Program Files` 等只读目录，否则配置写不进去；需在说明里写明。
- 构建期需在 aurum 环境安装 PyInstaller（仅构建期依赖，不进产物）；该环境 pip 需带 `--no-user`。
- 「别的电脑能用」必须在**未安装 Python 的机器**上实测一次才算验证通过；若遇到杀软误报，可退回单目录模式（只是构建参数变化，不影响架构）。
