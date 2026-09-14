# -*- coding: utf-8 -*-
"""弹窗与提示音（副作用层）。

弹窗是主窗口的 Toplevel：不抢焦点、点击即关、到点自动消失。轮询线程只往队列里
投递提醒（顺带出声），Tk 那一侧的活都留在主线程，由根窗的定时回调取队列弹出。
"""

import ctypes
import os
import queue
import tkinter as tk
import winsound
from ctypes import wintypes

from aurumwatch.alerts import DOWNSIDE, UPSIDE
from aurumwatch.failures import FailureWarning, duration_text
from aurumwatch.settings import POPUP_DURATION, SOUND_ENABLED

POPUP_MARGIN = 24  # 距屏幕工作区右下角的留白（像素）
POPUP_GAP = 10  # 多个弹窗上下叠放时的间距（像素）
POPUP_BG = "#1e1f22"
POPUP_FG = "#f0f0f0"
POPUP_DIM = "#a8a8a8"
POPUP_FAINT = "#787878"
POPUP_FONT = "Microsoft YaHei UI"
# 涨红跌绿，沿用国内行情习惯；琥珀色给故障警告，与行情涨跌区分开
DIRECTION_COLOR = {UPSIDE: "#e5534b", DOWNSIDE: "#3fb950"}
FAILURE_ACCENT = "#e6b450"
ERROR_SHORT_LIMIT = 72  # 弹窗里错误文本的最大字符数，超长截断
PUMP_MS = 200  # 主线程取一次提醒队列的间隔

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SPI_GETWORKAREA = 0x0030

_events = queue.Queue()
_ui_errors = queue.Queue()  # 弹窗的报错，由编排层取走显示在窗口底部（见 app._show_frames）
_root = None
_open_popups = []


def attach(root):
    """把弹窗挂到主窗口上（须在主线程调用）：此后提醒经根窗的定时回调弹出。"""
    global _root
    _root = root
    _pump()


def notify(event):
    """投递一次提醒（价格越线或故障警告）：一声短提示音（可关）＋ 右下角小窗。"""
    if SOUND_ENABLED:
        _play_chime()
    _events.put(event)


def _play_chime():
    """一声短提示音；无音频设备时静音退化，不影响提醒本身。"""
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        try:
            winsound.Beep(880, 180)
        except Exception:
            pass


def _pump():
    """主线程内的定时泵：把队列中的提醒逐个弹出。"""
    while True:
        try:
            event = _events.get_nowait()
        except queue.Empty:
            break
        try:
            _show_popup(event)
        except Exception as exc:  # 单个弹窗失败不拖垮窗口
            _ui_errors.put(f"{type(exc).__name__}: {exc}")
    _root.after(PUMP_MS, _pump)


def drain_ui_errors():
    """取走弹窗积累的报错（编排层调用，显示在窗口底部）。"""
    messages = []
    while True:
        try:
            messages.append(_ui_errors.get_nowait())
        except queue.Empty:
            return messages


def _short(text):
    """截断过长的文本，避免把弹窗撑得比屏幕还宽。"""
    if len(text) <= ERROR_SHORT_LIMIT:
        return text
    return text[: ERROR_SHORT_LIMIT - 1] + "…"


def _fill_alert(card, alert, accent):
    """价格提醒内容：方向、市场、现价、阈值、数据时间。"""
    head = tk.Frame(card, bg=POPUP_BG)
    head.pack(anchor="w")
    tk.Label(
        head, text=alert.direction, fg=accent, bg=POPUP_BG,
        font=(POPUP_FONT, 15, "bold"),
    ).pack(side="left")
    tk.Label(
        head, text=f"  {alert.market}", fg=POPUP_FG, bg=POPUP_BG,
        font=(POPUP_FONT, 15, "bold"),
    ).pack(side="left")
    tk.Label(
        card, text=f"{alert.price:.2f} {alert.unit}", fg=POPUP_FG, bg=POPUP_BG,
        font=(POPUP_FONT, 22, "bold"),
    ).pack(anchor="w", pady=(6, 2))
    tk.Label(
        card, text=f"阈值 {alert.threshold:.2f} {alert.unit}", fg=POPUP_DIM,
        bg=POPUP_BG, font=(POPUP_FONT, 10),
    ).pack(anchor="w")
    tk.Label(
        card, text=f"数据时间 {alert.data_time:%Y-%m-%d %H:%M:%S}", fg=POPUP_DIM,
        bg=POPUP_BG, font=(POPUP_FONT, 10),
    ).pack(anchor="w")


def _fill_failure(card, warning, accent):
    """故障警告内容：市场、连续失败时长与最近错误，并说明这来自数据源、不是行情。"""
    head = tk.Frame(card, bg=POPUP_BG)
    head.pack(anchor="w")
    tk.Label(
        head, text="数据源故障", fg=accent, bg=POPUP_BG,
        font=(POPUP_FONT, 15, "bold"),
    ).pack(side="left")
    tk.Label(
        head, text=f"  {warning.market}", fg=POPUP_FG, bg=POPUP_BG,
        font=(POPUP_FONT, 15, "bold"),
    ).pack(side="left")
    tk.Label(
        card, text=f"已连续 {duration_text(warning.elapsed)}取数失败", fg=POPUP_FG,
        bg=POPUP_BG, font=(POPUP_FONT, 22, "bold"),
    ).pack(anchor="w", pady=(6, 2))
    tk.Label(
        card, text=f"{warning.detail} · 自 {warning.since:%H:%M:%S} 起", fg=POPUP_DIM,
        bg=POPUP_BG, font=(POPUP_FONT, 10),
    ).pack(anchor="w")
    tk.Label(
        card, text=f"最近错误：{_short(warning.error)}", fg=POPUP_DIM,
        bg=POPUP_BG, font=(POPUP_FONT, 10),
    ).pack(anchor="w")
    tk.Label(
        card, text="不是行情变化；恢复后自动继续提醒", fg=POPUP_DIM,
        bg=POPUP_BG, font=(POPUP_FONT, 10),
    ).pack(anchor="w")


def _show_popup(event):
    """右下角弹出一个无边框小窗：不抢焦点，点击即关，POPUP_DURATION 秒后自动消失。

    价格提醒与故障警告共用窗口骨架，内容各自填充（描边色随内容变化）。
    """
    if isinstance(event, FailureWarning):
        accent, fill = FAILURE_ACCENT, _fill_failure
    else:
        accent, fill = DIRECTION_COLOR.get(event.direction, FAILURE_ACCENT), _fill_alert
    window = tk.Toplevel(_root)
    window.withdraw()
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.configure(bg=accent)

    card = tk.Frame(window, bg=POPUP_BG, padx=18, pady=14)
    card.pack(padx=2, pady=2)  # 2 像素的描边
    fill(card, event, accent)
    tk.Label(
        card, text=f"点击关闭 · {POPUP_DURATION} 秒后自动消失", fg=POPUP_FAINT,
        bg=POPUP_BG, font=(POPUP_FONT, 9),
    ).pack(anchor="w", pady=(8, 0))

    def close(event=None):
        if window.winfo_exists():
            window.destroy()
        if window in _open_popups:
            _open_popups.remove(window)

    def bind_close(widget):
        # 在鼠标松开（完整点击）时才关闭：按下即销毁会让松开事件落到弹窗底下的窗口上
        widget.bind("<ButtonRelease-1>", close)
        for child in widget.winfo_children():
            bind_close(child)

    bind_close(window)
    window.update_idletasks()  # 先把窗口建出来，顶层包装句柄此时才存在
    _no_activate(window)  # 抢在首次映射前设好「不抢焦点」样式
    left, top, width, height = _work_area()
    w, h = window.winfo_reqwidth(), window.winfo_reqheight()
    x = left + width - w - POPUP_MARGIN
    y = top + height - h - POPUP_MARGIN - len(_open_popups) * (h + POPUP_GAP)
    window.geometry(f"+{x}+{max(y, top + POPUP_MARGIN)}")
    _open_popups.append(window)
    previous_foreground = ctypes.windll.user32.GetForegroundWindow()
    window.deiconify()
    _keep_foreground(previous_foreground)
    window.after(POPUP_DURATION * 1000, close)


def _work_area():
    """屏幕工作区 (左, 上, 宽, 高)：避开任务栏；查询失败时退回整屏。"""
    try:
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
        ):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
    except Exception:
        pass
    return 0, 0, _root.winfo_screenwidth(), _root.winfo_screenheight()


def _no_activate(window):
    """让窗口显示时不抢焦点、不进任务栏与 Alt+Tab（Windows 扩展样式）。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        )
    except Exception:
        pass  # 拿不到窗口句柄时退化为普通置顶窗，不影响提醒本身


def _keep_foreground(previous):
    """兜底：若前台被本进程的 Tk 窗口抢走，把它还给原窗口。"""
    try:
        user32 = ctypes.windll.user32
        current = user32.GetForegroundWindow()
        if not previous or current == previous:
            return
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(current, ctypes.byref(pid))
        if pid.value == os.getpid():
            user32.SetForegroundWindow(previous)
    except Exception:
        pass
