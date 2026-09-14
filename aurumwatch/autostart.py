# -*- coding: utf-8 -*-
"""开机自启：当前用户的 Run 注册表项（见 ticket 06）。

只有打包后的 exe 才谈得上自启：从源码运行的目标是 python.exe，把它写进启动项等于
埋一个「换了环境就只剩一个报错框」的坑（见 User Story 10）。所以这种形态下
`exe_path()` 返回 None，设置窗口据此把这一项置灰。

**注册表就是这一项的唯一真相**（config.json 里不存它）：配置文件是要跟着 exe 换
电脑的，可那台机器的启动项里并没有我们——存两份，开关显示的和实际会不会自启就会
分叉。

开关说的是「**这一份**程序会不会在开机时自己起来」，所以看的是那一条命令**指向哪儿**：
值名在、却指着别处（exe 搬了家、重新打包换了位置），那这一份开机时并不会起来——
就如实显示未勾选（搬完家勾一下即可改写到现在的位置）。[保存]按同一份判断落地：
勾了就写成本次运行的 exe，没勾就把这个名字下的那一项删掉（[取消自启] 之后注册表
不留东西）。名字不带路径，一台机器上只会有一条 AurumWatch 启动项——这与单实例
（同一个会话只跑一份监视）是一个口径。
"""

import os
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
    """这一份程序会不会在开机时自己起来（值在，且指向的就是本次运行的 exe）。

    读不出来（没这个键、没这个值、权限不对）算没有；从源码运行没有可自启的 exe，
    也算没有。读失败时显示未勾选，用户勾一下仍然能把它建起来（[保存]按同一份判断
    落地，没勾就删；真删不动会当场说明，不会悄悄当成改好了）。
    """
    path = exe_path()
    if path is None:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE
        ) as key:
            command, _kind = winreg.QueryValueEx(key, VALUE_NAME)
    except OSError:
        return False
    return points_at(command, path)


def points_at(command, path):
    """那一条启动命令是不是就跑这个程序（纯函数）。

    带不带引号、大小写与斜杠的写法不同都算同一个——手改过注册表、或早先的版本写的
    是另一种写法时，开关不该因此说「没开」。认不出的写法（不是文本、空串）一律不算。
    """
    text = command.strip() if isinstance(command, str) else ""
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    if not text:
        return False
    return _canonical(text) == _canonical(path)


def _canonical(path):
    """比路径用的规范形：绝对化（引号里那条也该是绝对的），大小写与斜杠不分。"""
    return os.path.normcase(os.path.normpath(os.path.abspath(str(path))))


def set_enabled(on):
    """把开机自启设成 on：往当前用户的 Run 键里写本次运行的 exe，或把那一项删掉。

    从源码运行勾不了——那会把 Python 解释器写进启动项（抛 `ValueError`，见模块说明）。
    写不进去（权限等）时抛 OSError，由设置窗口说给用户听。
    """
    if not on:
        _remove()
        return
    path = exe_path()
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
