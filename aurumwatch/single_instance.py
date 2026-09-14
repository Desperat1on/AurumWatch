# -*- coding: utf-8 -*-
"""单实例：同一时刻只跑一份监视（见 ticket 06）。

重复双击不该跑出第二份监视——两份监视就是两个提醒源，同一件事弹两遍。第二个实例
拿到同一个命名互斥体就知道「已经有人在跑」：把已有主窗口带到前台，然后静默退出。

窗口靠**标题**去找（两个进程之间没有别的共同身份），但只按标题取第一个不够：Tk 的
Toplevel 默认继承应用标题，弹窗与主窗口同名，而且弹窗是置顶的——真取第一个，取到的
往往正是那个贴在屏幕角上、半秒后自己会消失的小窗。所以这里枚举全部同名窗口，再按
**有没有标题栏**认出主窗口（弹窗用 overrideredirect，没有标题栏）。

找不到窗口也照样退出——第一份可能还在起窗（双击得急了就会这样），它的窗口随后自己
会出现；这一头再补点什么，反而可能造出第二份监视。

造不出互斥体（系统调用失败）时按「我是第一份」跑：单实例是防重复的附加保护，
不该反过来挡住启动。
"""

import ctypes
from ctypes import wintypes

from aurumwatch.main_window import WINDOW_TITLE

# 「Local\」前缀：每个登录会话各一份——多用户各自开各自的，互不打架
MUTEX_NAME = "Local\\AurumWatch.SingleInstance"
ERROR_ALREADY_EXISTS = 183
SW_RESTORE = 9
GWL_STYLE = -16
WS_CAPTION = 0x00C00000  # 带标题栏的普通窗口：弹窗（overrideredirect）没有这一位
FLASHW_ALL = 0x00000003  # 闪任务栏按钮与窗口边框
FLASHW_TIMERNOFG = 0x0000000C  # 一直闪，直到用户把它点到前台

# 窗口标题取这么长：`GetWindowTextW` 取不下就**截断**，按标题长度开缓冲区会把
# 「AurumWatch 设置」这种长标题截成「AurumWatch」，看着像同名——开得比标题长、
# 再整串比对，才是「正好同名」
TITLE_LIMIT = 256

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = (wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR)
_kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class _FlashInfo(ctypes.Structure):
    """FlashWindowEx 的参数：要闪哪个窗口、闪什么、闪多久。"""

    _fields_ = (
        ("size", wintypes.UINT),
        ("hwnd", wintypes.HWND),
        ("flags", wintypes.DWORD),
        ("count", wintypes.UINT),
        ("timeout", wintypes.DWORD),
    )


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.EnumWindows.argtypes = (ctypes.c_void_p, wintypes.LPARAM)
_user32.FlashWindowEx.argtypes = (ctypes.POINTER(_FlashInfo),)
_user32.GetWindowLongW.restype = ctypes.c_long
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.SetForegroundWindow.argtypes = (wintypes.HWND,)

_held = []  # 申请到的互斥体句柄：留着不放——句柄一关，这个名额就等于让出去了


def claim():
    """申请独占名额 → 本进程是不是第一份监视。

    `ERROR_ALREADY_EXISTS` 就是「已经有一份在跑」：那时刚拿到手的这个句柄没有用，
    关掉它（名额仍是别人的）。拿到的那个留着，直到进程退出由系统收走。
    """
    handle = _kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:  # 造不出来：宁可多跑一份，也不能打不开
        return True
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _held.append(handle)
    return True


def focus_existing():
    """把已在运行的那份主窗口带到前台。

    先 `SW_RESTORE`（最小化着的先还原回来）再要前台：一个最小化的窗口就算被设成
    前台，也还是最小化的。

    前台不是想拿就能拿的：Windows 只把它让给前台进程，或由前台进程拉起的进程——
    双击 exe 的正是资源管理器（前台进程），所以「重复双击」这一路走得通；从终端
    再起一次这种情形要不到，那就闪任务栏（一直闪到用户点开为止）——总比什么都不
    发生强，用户至少知道「那扇窗在哪儿」。

    找不到窗口就什么都不做——另一份可能还在起窗，它的窗口随后自己会出现。
    """
    hwnd = _main_window()
    if not hwnd:
        return
    _user32.ShowWindow(hwnd, SW_RESTORE)
    if not _user32.SetForegroundWindow(hwnd):
        _flash(hwnd)


def _flash(hwnd):
    """闪窗口与它的任务栏按钮，直到用户把它点到前台（前台权限要不到时的退路）。"""
    info = _FlashInfo(
        ctypes.sizeof(_FlashInfo), hwnd, FLASHW_ALL | FLASHW_TIMERNOFG, 0, 0
    )
    _user32.FlashWindowEx(ctypes.byref(info))


def _main_window():
    """主窗口的句柄（找不到返回 0）：枚举同名窗口里那个带标题栏的。

    出错消息框与主窗口同名也同框（都是带标题栏的窗口），真赶上它开着时被带到前台的
    就是那个框——它本来就压在主窗口前面，这么做出不了格。
    """
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _param):
        caption = _user32.GetWindowLongW(hwnd, GWL_STYLE) & WS_CAPTION
        if caption and _title(hwnd) == WINDOW_TITLE:
            found.append(hwnd)
        return True

    _user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def _title(hwnd):
    """窗口标题（整串取回来，长标题不会被截成短的看着像同名，见 TITLE_LIMIT）。"""
    buffer = ctypes.create_unicode_buffer(TITLE_LIMIT)
    _user32.GetWindowTextW(hwnd, buffer, TITLE_LIMIT)
    return buffer.value
