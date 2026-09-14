# -*- coding: utf-8 -*-
"""弹窗与提示音（副作用层）。

弹窗是主窗口的 Toplevel：不抢焦点、点击即关、到点自动消失。卡片怎么画只有
`build_card` 一处——设置窗口里的预览调的就是同一个函数，所以预览与真实弹窗所见即
所得。轮询线程只往队列里投递提醒（顺带出声），Tk 那一侧的活都留在主线程。

外观（配色、字体、停留秒数、贴哪个角）由编排层经 `set_theme` 设置，保存设置后
立即对后续弹窗生效（见 ticket 04）。
"""

import ctypes
import os
import queue
import tkinter as tk
import winsound
from ctypes import wintypes
from datetime import datetime
from decimal import Decimal

from aurumwatch.alerts import UPSIDE, Alert
from aurumwatch.config import CUSTOM_SOUND, default_values
from aurumwatch.failures import FailureWarning, duration_text
from aurumwatch.theme import Theme

POPUP_MARGIN = 24  # 距屏幕工作区边缘的留白（像素）
POPUP_GAP = 10  # 同一角上多个弹窗之间的间距（像素）
ERROR_SHORT_LIMIT = 72  # 弹窗里错误文本的最大字符数，超长截断
PUMP_MS = 200  # 主线程取一次提醒队列的间隔

# 弹窗的字号档位（相对基准字号）：标题、大数字、正文、脚注
TITLE_STEP = 5
PRICE_STEP = 12
FOOT_STEP = -1

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SPI_GETWORKAREA = 0x0030

_events = queue.Queue()
_ui_errors = queue.Queue()  # 弹窗与提示音的报错，每条自带说法，由编排层取走显示在窗口底部
_root = None
_theme = Theme.from_appearance(default_values()["appearance"])  # 编排层接手前的默认外观
_open_popups = []
_reported = {}  # 说过的音效问题（同一条不每轮重复），见 _report


def attach(root):
    """把弹窗挂到主窗口上（须在主线程调用）：此后提醒经根窗的定时回调弹出。"""
    global _root
    _root = root
    _pump()


def set_theme(theme):
    """换一套外观：此后弹出的窗口照新的画（已经弹出来的不动）。"""
    global _theme
    _theme = theme


def current_theme():
    """当前外观：设置窗口拿它起预览、真实弹窗拿它绘制。"""
    return _theme


def notify(event, *, sound=None):
    """投递一次提醒（价格越线或故障警告）：一声提示音（可关、音效可换）＋一个小窗。

    sound 由编排层按当前配置的快照传入：提示音开关与音效一保存就生效，不用重启。
    """
    if sound and sound.get("enabled"):
        notice = play_sound(sound)
        if notice:
            _report(f"提示音：{notice}")
    _events.put(event)


def play_sound(sound):
    """出一声：系统提示音，或配置里指定的 WAV 文件。

    返回一句要转达给用户的中文说明（没出问题时为 None）：文件被删了、挪走了、
    根本不是 WAV，都不该让提醒哑掉，但也不该不吭声地换一种声音。
    """
    if sound.get("choice") != CUSTOM_SOUND:
        _beep()
        return None
    problem = _play_wav(str(sound.get("file") or ""))
    if problem is None:
        return None
    _beep()
    return f"{problem}，已改用系统提示音"


def test_pop(theme, sound=None):
    """[试弹一次]：按给定的（可能尚未保存的）外观弹一个真实弹窗。

    与真实触发一样顺手出声（提示音开着的话）；返回一句要转达给用户的话（音效放不
    出来时），没有则 None。弹完不改变当前外观——[取消] 后一切照旧。
    """
    notice = play_sound(sound) if sound and sound.get("enabled") else None
    _show_popup(sample_alert(), theme)
    return notice


def sample_alert():
    """样例提醒：国内金价涨破（预览与[试弹一次]共用，见 spec 的验收参考价位）。"""
    return Alert(
        market="国内金价",
        direction=UPSIDE,
        price=Decimal("951.24"),
        threshold=Decimal("950.00"),
        unit="元/克",
        data_time=datetime.now(),
    )


def build_card(parent, event, theme, seconds):
    """把一张提醒卡片摆进 parent，返回最外层（真实弹窗与设置窗口的预览共用这一套绘制）。

    卡片整个包在 2 像素的描边里：价格提醒用涨破/跌破色，故障警告用警告色。
    seconds 是卡片脚注上写的停留秒数——真实弹窗就停这么久，预览写的就是待保存的值。
    """
    accent, fill = _look(event, theme)
    border = tk.Frame(parent, bg=accent)
    card = tk.Frame(border, bg=theme.bg, padx=18, pady=14)
    card.pack(padx=2, pady=2)
    fill(card, event, theme, accent)
    tk.Label(
        card, text=f"点击关闭 · {seconds} 秒后自动消失", fg=theme.faint,
        bg=theme.bg, font=theme.font(FOOT_STEP),
    ).pack(anchor="w", pady=(8, 0))
    return border


def _look(event, theme):
    """一张卡片的描边色与填充函数：价格提醒看方向，故障警告一律警告色。"""
    if isinstance(event, FailureWarning):
        return theme.warn, _fill_failure
    accent = theme.rise if event.direction == UPSIDE else theme.fall
    return accent, _fill_alert


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
            _ui_errors.put(f"弹窗显示失败：{type(exc).__name__}: {exc}")
    _root.after(PUMP_MS, _pump)


def drain_ui_errors():
    """取走弹窗积累的报错（编排层调用，显示在窗口底部）。"""
    messages = []
    while True:
        try:
            messages.append(_ui_errors.get_nowait())
        except queue.Empty:
            return messages


def _report(message):
    """说一次就够的问题（例如音效文件放不出来）：别每分钟提醒一次同一件事。

    换过音效、或设置里[试听]之后再出问题，说法不一样，自然会再报一次。
    """
    if _reported.get(message):
        return
    _reported[message] = True
    _ui_errors.put(message)


def _play_wav(path):
    """放一个 WAV 文件 → 出问题时的中文说明（放成功为 None）。"""
    if not path:
        return "没有指定音效文件"
    if not os.path.isfile(path):
        return f"找不到音效文件 {path}"
    try:
        # SND_ASYNC：放音不挡住提醒；SND_NODEFAULT：放不出来就报错，而不是悄悄换成
        # 系统提示音——那样用户会以为自定义音效已经生效
        winsound.PlaySound(
            path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT
        )
    except Exception:
        return f"音效文件放不出来（{path}）"
    return None


def _beep():
    """系统提示音；无音频设备时静音退化，不影响提醒本身。"""
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        try:
            winsound.Beep(880, 180)
        except Exception:
            pass


def _short(text):
    """截断过长的文本，避免把弹窗撑得比屏幕还宽。"""
    if len(text) <= ERROR_SHORT_LIMIT:
        return text
    return text[: ERROR_SHORT_LIMIT - 1] + "…"


def _fill_alert(card, alert, theme, accent):
    """价格提醒内容：方向、市场、现价、阈值、行情数据时间。"""
    head = tk.Frame(card, bg=theme.bg)
    head.pack(anchor="w")
    tk.Label(
        head, text=alert.direction, fg=accent, bg=theme.bg,
        font=theme.font(TITLE_STEP, bold=True),
    ).pack(side="left")
    tk.Label(
        head, text=f"  {alert.market}", fg=theme.fg, bg=theme.bg,
        font=theme.font(TITLE_STEP, bold=True),
    ).pack(side="left")
    tk.Label(
        card, text=f"{alert.price:.2f} {alert.unit}", fg=theme.fg,
        bg=theme.bg, font=theme.font(PRICE_STEP, bold=True),
    ).pack(anchor="w", pady=(6, 2))
    tk.Label(
        card, text=f"阈值 {alert.threshold:.2f} {alert.unit}", fg=theme.dim,
        bg=theme.bg, font=theme.font(),
    ).pack(anchor="w")
    tk.Label(
        card, text=f"数据时间 {alert.data_time:%Y-%m-%d %H:%M:%S}", fg=theme.dim,
        bg=theme.bg, font=theme.font(),
    ).pack(anchor="w")


def _fill_failure(card, warning, theme, accent):
    """故障警告内容：市场、连续失败时长与最近错误，并说明这来自数据源、不是行情。"""
    head = tk.Frame(card, bg=theme.bg)
    head.pack(anchor="w")
    tk.Label(
        head, text="数据源故障", fg=accent, bg=theme.bg,
        font=theme.font(TITLE_STEP, bold=True),
    ).pack(side="left")
    tk.Label(
        head, text=f"  {warning.market}", fg=theme.fg, bg=theme.bg,
        font=theme.font(TITLE_STEP, bold=True),
    ).pack(side="left")
    tk.Label(
        card, text=f"已连续 {duration_text(warning.elapsed)}取数失败", fg=theme.fg,
        bg=theme.bg, font=theme.font(PRICE_STEP, bold=True),
    ).pack(anchor="w", pady=(6, 2))
    tk.Label(
        card, text=f"{warning.detail} · 自 {warning.since:%H:%M:%S} 起", fg=theme.dim,
        bg=theme.bg, font=theme.font(),
    ).pack(anchor="w")
    tk.Label(
        card, text=f"最近错误：{_short(warning.error)}", fg=theme.dim,
        bg=theme.bg, font=theme.font(),
    ).pack(anchor="w")
    tk.Label(
        card, text="不是行情变化；恢复后自动继续提醒", fg=theme.dim,
        bg=theme.bg, font=theme.font(),
    ).pack(anchor="w")


def corner_origin(corner, work_area, size, index, *, margin=POPUP_MARGIN, gap=POPUP_GAP):
    """弹窗左上角坐标（纯函数）：贴住所选的那个角。

    同一个角上已经有 index 个弹窗时，依次向内错开一个身位；多到叠不下、或弹窗比
    工作区还大时，宁可压在一起也不许跑到屏幕外面去。
    """
    left, top, width, height = work_area
    w, h = size
    x = left + margin if corner.endswith("left") else left + width - w - margin
    step = index * (h + gap)
    y = top + margin + step if corner.startswith("top") else top + height - h - margin - step
    return (
        max(left + margin, min(x, left + width - w - margin)),
        max(top + margin, min(y, top + height - h - margin)),
    )


def _show_popup(event, theme=None):
    """在设置好的那个角弹出无边框小窗：不抢焦点，点击即关，到点自动消失。

    价格提醒与故障警告共用窗口骨架，内容各自填充（描边色随内容变化）。
    """
    theme = theme or _theme
    window = tk.Toplevel(_root)
    window.withdraw()
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.configure(bg=theme.bg)
    build_card(window, event, theme, theme.popup_seconds).pack()

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
    x, y = corner_origin(
        theme.popup_corner,
        _work_area(),
        (window.winfo_reqwidth(), window.winfo_reqheight()),
        len(_open_popups),
    )
    window.geometry(f"+{x}+{y}")
    _open_popups.append(window)
    previous_foreground = ctypes.windll.user32.GetForegroundWindow()
    window.deiconify()
    _keep_foreground(previous_foreground)
    window.after(theme.popup_seconds * 1000, close)


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
