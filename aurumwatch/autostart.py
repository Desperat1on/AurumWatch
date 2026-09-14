# -*- coding: utf-8 -*-
"""开机自启：当前用户的 Run 注册表项（见 ticket 06）。

只有打包后的 exe 才谈得上自启：从源码运行的目标是 python.exe，把它写进启动项等于
埋一个「换了环境就只剩一个报错框」的坑（见 User Story 10）。所以这种形态下
`exe_path()` 返回 None，设置窗口据此把这一项置灰。

**注册表就是这一项的唯一真相**（config.json 里不存它）：配置文件是要跟着 exe 换
电脑的，可那台机器的启动项里并没有我们——存两份，开关显示的和实际会不会自启就会
分叉。判断只看值名在不在：同一个名字下只能有一条启动命令，谁写的都是写给
AurumWatch 的；勾选时总是重写成本次运行的 exe，所以搬了家、重新打包之后保存一次
即可修正路径。
"""

import sys
import winreg
from pathlib import Path

from aurumwatch.config import packaged

# 当前用户的启动项：登录后由资源管理器执行，不需要管理员权限（也不该动 HKLM）
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AurumWatch"


def exe_path():
    """自启要运行的程序：打包后是 exe 自己；从源码运行没有（None）。

    「是不是打包运行」用的是 `config.packaged()` 那一个谓词（与配置放哪儿同一个），
    绝对化交给 `command_line`：写进启动项的东西必须是绝对路径，那一处保证。
    """
    if not packaged():
        return None
    return Path(sys.executable)


def command_line(path):
    r"""启动项里那串命令：**一律加引号**的绝对路径（纯函数）。

    路径里有空格而不加引号时，Windows 会把它按空格切开——`C:\Program Files\…`
    会被当成 `C:\Program.exe`：自启静默失败，还可能被同名的程序顶替。所以不给
    「什么时候要加」留条件：一律加，解析出来永远是这个路径。
    """
    return f'"{Path(path).resolve()}"'


def enabled():
    """当前用户的开机自启里有没有本程序这一项。

    读不出来（没这个键、没这个值、权限不对）都算没有：这是「有就写、没有就当没有」
    的开关——读失败时显示未勾选，用户勾一下仍然能把它建起来（[保存]按同一份判断落地，
    没勾就删；真删不动会当场说明，不会悄悄当成改好了）。
    """
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return True


def set_enabled(on, path=None):
    """把开机自启设成 on：往当前用户的 Run 键里写一项，或把它删掉。

    path 是勾选时要启动的程序（缺省取 `exe_path()`）；取消时用不上它。从源码运行
    勾不了——那会把 Python 解释器写进启动项（抛 `ValueError`，见模块说明）。写不
    进去（权限等）时抛 OSError，由设置窗口说给用户听。
    """
    if not on:
        _remove()
        return
    path = exe_path() if path is None else path
    if path is None:
        raise ValueError("从源码运行时没有可写进启动项的 exe")
    _write(command_line(path))


def _write(command):
    """写／覆盖那一项：值名固定，一台机器上只留一条。"""
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)


def _remove():
    """删掉那一项：本来就没有也算删干净（[取消自启] 之后注册表不留东西）。"""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, VALUE_NAME)
    except FileNotFoundError:
        pass  # 键或值本来就不在：要的就是这个结果
