# -*- coding: utf-8 -*-
"""打包：把 AurumWatch 打成单文件 exe（见 ticket 07）。

一次运行做完三件事：把图标画出来（`tools/icon.py`，不引图像库）、交给 PyInstaller
打成 `dist/AurumWatch.exe`、核对产物在不在。构建期需要 PyInstaller，它既不是运行期
依赖也不进产物；缺了这里会给出装它的那一条命令。

中间物全落在 `build/`——PyInstaller 的 workpath，以及它顺带写出的 .spec；产物落在
`dist/`。两者都不入库（见 .gitignore）：每次构建先清掉上一次的产物，于是「可重复
执行」是干净的重复，而不是把上次的残留当成这次的结果。

    python tools/build.py
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # 直接跑这个脚本时（`python tools/build.py`）也认得出下面的包

from tools.icon import write_ico  # noqa: E402  （要在上面那行之后）

ENTRY = ROOT / "aurumwatch" / "__main__.py"  # 与 `python -m aurumwatch` 同一个入口
NAME = "AurumWatch"
DIST = ROOT / "dist"
WORK = ROOT / "build"
ICON = WORK / "aurumwatch.ico"
INSTALL_HINT = "pip install --no-user pyinstaller"


def main():
    """构建一次：图标 → PyInstaller → 核对产物；任一步不成说明原因并以非零码退出。"""
    _use_utf8_output()
    _require_pyinstaller()
    target = DIST / f"{NAME}.exe"
    target.unlink(missing_ok=True)  # 先清旧的：构建没走完时不会留一个像是成功的产物
    write_ico(ICON)
    _run_pyinstaller()
    _check(target)
    print(f"\n产物：{target}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
    print("拷到别的电脑时连同 config.json 一起拷（首次运行会自己在 exe 旁生成一份）。")


def _use_utf8_output():
    """下面这些中文别在 Git Bash 里变成乱码。

    真控制台（cmd、Windows Terminal）上 Python 走的是控制台 API，中文本来就对；输出被
    接进管道时却不是——Git Bash 的终端（mintty）就是一根管道，`> 日志.txt` 也是——那
    时它按本机 ANSI（简中 cp936）编码，接收方按 UTF-8 解，就成了乱码。只在管道里改成
    UTF-8：两头正好对上，真控制台那边一个字不动。

    stdout 与 stderr 都要改：出错那两句（没装 PyInstaller、构建失败）走的正是 stderr，
    漏掉它就等于「最该看的话恰好看不清」。
    """
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")


def _require_pyinstaller():
    """构建期依赖：没装就说清楚装哪一条，别让 PyInstaller 的报错来兜底。

    `find_spec` 只看到不到，不管装的是哪个版本；`-m PyInstaller` 起来之后，版本不合
    由它自己抱怨。
    """
    if importlib.util.find_spec("PyInstaller") is None:
        sys.exit(f"没装 PyInstaller（构建期依赖）：{INSTALL_HINT}")


def _run_pyinstaller():
    """跑 PyInstaller：单文件、无控制台、带图标，中间物都落在 build/ 下。

    入口用包自己的 `__main__.py`（与源码运行同一个），`--paths` 指到仓库根——那是
    `aurumwatch` 包所在的地方，不指的话 PyInstaller 只认入口脚本那一层目录。
    """
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",  # 重复构建是干净的一次，不弹「要覆盖吗」也不吃缓存
        "--onefile", "--noconsole",
        "--name", NAME,
        "--icon", str(ICON),
        "--paths", str(ROOT),
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),  # .spec 也是中间物，别落在仓库根
        str(ENTRY),
    ]
    print("构建中：" + " ".join(command) + "\n")
    result = subprocess.run(command, cwd=ROOT, env=_env_with_env_dlls())
    if result.returncode != 0:
        sys.exit(f"PyInstaller 构建失败（退出码 {result.returncode}）")


def _env_with_env_dlls():
    """把本环境的 DLL 目录排到 PATH 最前，交给 PyInstaller 用。

    PyInstaller 找不到某个 DLL 时会顺着 PATH 找。这个环境里 `_ssl.pyd` 依赖的 OpenSSL
    不在它自己那层目录，而在 `Library/bin`；而开发机上往往还有别的 OpenSSL（Git 自带的
    `mingw64\\bin` 在 Git Bash 的 PATH 里就排在前面）——实测第一版产物就是这么装错了
    DLL：构建一路成功，exe 在没装 Python 的机器上「取数失败：Can't connect to HTTPS URL
    because the SSL module is not available」，本机跑却看不出问题（本机的 conda 目录也
    在 PATH 里，能兜住）。所以不赌 PATH 的顺序：本环境的目录排第一，其余照旧。
    """
    dll_dir = Path(sys.prefix) / "Library" / "bin"  # conda 把 DLL 都放这儿
    env = dict(os.environ)
    if dll_dir.is_dir():
        env["PATH"] = str(dll_dir) + os.pathsep + env.get("PATH", "")
    return env


def _check(target):
    """核对产物：PyInstaller 说成功、东西却不在，是构建脚本自己的错，得当场说。"""
    if not target.exists():
        sys.exit(f"构建结束，但没找到 {target}")


if __name__ == "__main__":
    main()
