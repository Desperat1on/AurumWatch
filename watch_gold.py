# -*- coding: utf-8 -*-
"""金价监视——国内（沪金99，元/克）与国际（伦敦金，美元/盎司）实时行情上屏；
价格越线时在屏幕右下角弹出小窗提醒，并留一行控制台日志。

双击「启动金价监视.bat」运行；关闭窗口或 Ctrl+C 停止。
"""

import ctypes
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import traceback
import winsound
from ctypes import wintypes
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests

# ============================ 配置区 ============================
# 轮询间隔（秒）。刷新时刻与系统时钟的整分钟对齐（如 60 → 每分 0 秒，
# 120 → 每分 0、2 分 0 秒），保证行情数据时间与刷新时刻一致、可对照。
REFRESH_INTERVAL = 60
# 单次请求超时（秒）
REQUEST_TIMEOUT = 10
# 重新武装带比例：触发后，价格须回到阈值另一侧并越过「阈值 × 该比例」才算
# 翻篇、可再次提醒；贴着阈值抖动不会反复打扰。0.001 即千分之一（0.1%）。
REARM_RATIO = Decimal("0.001")
# 弹窗停留时长（秒），期间点击即关
POPUP_DURATION = 30
# 触发时是否播放一声短提示音
SOUND_ENABLED = True

# 每个市场的提醒阈值：涨破、跌破各一个；留空（None）或填 0 的方向不启用、不提醒。
# 数值照抄 Decimal("...") 的格式填写（带小数时不要直接写浮点数）。
MARKETS = (
    {
        "name": "国内金价",
        "detail": "沪金99（上海黄金交易所 Au99.99）",
        "unit": "元/克",
        "code": "gds_AU9999",
        "up_threshold": None,  # 涨破提醒价，如 Decimal("950.00")
        "down_threshold": None,  # 跌破提醒价，如 Decimal("900.00")
    },
    {
        "name": "国际金价",
        "detail": "伦敦金（XAU/USD 现货黄金）",
        "unit": "美元/盎司",
        "code": "hf_XAU",
        "up_threshold": None,  # 涨破提醒价，如 Decimal("4400.00")
        "down_threshold": None,  # 跌破提醒价，如 Decimal("4300.00")
    },
)
# ===============================================================

API_URL = "https://hq.sinajs.cn/list={codes}"
HEADERS = {"Referer": "https://finance.sina.com.cn"}
NEWLINE = "\r\n"

_LINE_RE = re.compile(r'var hq_str_([A-Za-z0-9_]+)="([^"]*)"')


class QuoteError(Exception):
    """一次行情取数或解析失败。"""


@dataclass(frozen=True)
class Quote:
    """一次行情读数：价格（已在展示单位）与行情数据时间。"""

    price: Decimal
    time: datetime


def next_refresh_delay(now, interval):
    """返回距离下一个整分对齐刷新的秒数（下限 1 秒）；整分即 interval 的整数倍。"""
    current = now.minute * 60 + now.second
    next_aligned = (current // interval + 1) * interval
    return max(1, next_aligned - current)


def parse_quote(line, code, scale=Decimal("1")):
    """解析新浪行情响应中的一行，定位到 `code` 并返回 Quote。

    line 为已解码文本，scale 把接口数值换算为展示单位（gds_ 与 hf_ 两个
    系列的量纲一致，均为 1；换算系数留在此处是为接口量纲变化兜底）。
    """
    match = _LINE_RE.search(line)
    if not match or match.group(1) != code:
        raise QuoteError(f"响应中没有 {code} 的数据：{line[:80]!r}")
    fields = match.group(2).split(",")
    if len(fields) < 13 or not fields[0]:
        raise QuoteError(f"{code} 返回空数据（可能代码错误或接口限制）")
    try:
        price = Decimal(fields[0]) * scale
    except InvalidOperation:
        raise QuoteError(f"{code} 价格字段无法解析：{fields[0]!r}") from None
    time_text = fields[6].split(".")[0]  # 国际行情时间带毫秒，取到秒
    try:
        data_time = datetime.strptime(
            fields[12] + " " + time_text, "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        raise QuoteError(
            f"{code} 行情时间无法解析：{fields[12]} {fields[6]}"
        ) from None
    return Quote(price=price, time=data_time)


def fetch_raw(codes):
    """向数据源请求若干行情代码的原始响应文本（GBK 解码）。"""
    response = requests.get(
        API_URL.format(codes=",".join(codes)), headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.content.decode("gbk")


# ======================= 触发判定核心（纯函数） =======================
# 方向词汇（见 CONTEXT.md）：涨破 = 现价 ≥ 阈值；跌破 = 现价 ≤ 阈值。
UPSIDE = "涨破"
DOWNSIDE = "跌破"


@dataclass(frozen=True)
class Direction:
    """一个提醒方向：名称、配置键，与回到阈值另一侧时的文案。"""

    name: str
    config_key: str
    return_word: str  # 涨破等「回落」，跌破等「回升」
    side_word: str  # 重新武装线的方位：以下 / 以上


DIRECTIONS = (
    Direction(UPSIDE, "up_threshold", "回落", "以下"),
    Direction(DOWNSIDE, "down_threshold", "回升", "以上"),
)


@dataclass(frozen=True)
class Alert:
    """一次触发的提醒事件：弹窗与日志所需的全部信息。"""

    market: str
    direction: str
    price: Decimal
    threshold: Decimal
    unit: str
    data_time: datetime


@dataclass(frozen=True)
class TriggerState:
    """一个市场的触发状态：armed 内的方向潜伏待发，其余已触发待回落。"""

    armed: frozenset


# 全新市场的初始状态：两个方向均潜伏待发
INITIAL_STATE = TriggerState(armed=frozenset({UPSIDE, DOWNSIDE}))


def enabled_directions(market):
    """该市场启用的方向及其阈值；留空（None）或 0 的方向不参与。"""
    for direction in DIRECTIONS:
        threshold = market[direction.config_key]
        if threshold:
            yield direction, threshold


def distance_to_line(price, direction, price_line):
    """现价相对一条价格线的距离：未越线为正，越线为负。

    price_line 可为方向阈值或重新武装线；涨破的线在现价上方、跌破的在下方。
    """
    return price_line - price if direction.name == UPSIDE else price - price_line


def rearm_line(direction, threshold, rearm_ratio):
    """重新武装线：触发后价格须回到并越过此线，该方向才重回潜伏。"""
    band = threshold * rearm_ratio
    return threshold - band if direction.name == UPSIDE else threshold + band


def evaluate_thresholds(market, quote, state, rearm_ratio):
    """穿越触发判定（纯函数）：一次读数 + 配置 + 当前状态 → 提醒事件 + 新状态。

    涨破 = 现价 ≥ 阈值，跌破 = 现价 ≤ 阈值（到达即算）。触发后该方向转入
    已触发，不再重复提醒，直到价格回到阈值另一侧并越过重新武装线
    （阈值 ∓ 阈值 × rearm_ratio）才重回潜伏。留空（None）或 0 的阈值不参与判定。
    """
    alerts = []
    armed = set(state.armed)
    for direction, threshold in enabled_directions(market):
        if direction.name in armed:
            if distance_to_line(quote.price, direction, threshold) <= 0:
                armed.discard(direction.name)
                alerts.append(
                    Alert(
                        market=market["name"],
                        direction=direction.name,
                        price=quote.price,
                        threshold=threshold,
                        unit=market["unit"],
                        data_time=quote.time,
                    )
                )
        elif distance_to_line(
            quote.price, direction, rearm_line(direction, threshold, rearm_ratio)
        ) >= 0:
            armed.add(direction.name)
    return tuple(alerts), TriggerState(armed=frozenset(armed))


def evaluate_markets(markets, quotes, states, rearm_ratio):
    """一轮刷新：对每个取到读数的市场独立判定（纯函数）。

    quotes 为 代码 → Quote 的映射；没有读数的市场（取数失败）保持原状态、
    不产生提醒。新状态表按市场分别写入，市场之间互不覆盖、互不阻塞。
    """
    alerts = []
    next_states = dict(states)
    for market in markets:
        quote = quotes.get(market["code"])
        if quote is None:
            continue
        new_alerts, next_states[market["code"]] = evaluate_thresholds(
            market, quote, states[market["code"]], rearm_ratio
        )
        alerts.extend(new_alerts)
    return tuple(alerts), next_states


def market_status(market, state):
    """市场状态文案：任一启用方向已触发待回落，否则监视中。"""
    for direction, _ in enabled_directions(market):
        if direction.name not in state.armed:
            return "已触发待回落"
    return "监视中"


def threshold_line(direction, threshold, unit, price, fired, rearm_ratio):
    """阈值现状一行：潜伏时报距触发的距离，已触发时报重新武装线与回摆所需量。"""
    if not fired:
        return (
            f"  {direction.name}阈值 {threshold:.2f} {unit}："
            f"距触发还差 {distance_to_line(price, direction, threshold):.2f}"
        )
    line = rearm_line(direction, threshold, rearm_ratio)
    gap = abs(distance_to_line(price, direction, line))
    return (
        f"  {direction.name}阈值 {threshold:.2f} {unit}：已触发；"
        f"{direction.return_word}至 {line:.2f} {direction.side_word}重新武装"
        f"（还需{direction.return_word} {gap:.2f}）"
    )


def render(market, quote, error, state, rearm_ratio):
    """渲染单个市场的显示段落。"""
    lines = [f"【{market['name']}】{market['detail']}"]
    if error is not None:
        lines.append(f"  数据源故障：{error}")
        return lines
    lines.append(f"  现价：{quote.price:.2f} {market['unit']}")
    lines.append(f"  行情数据时间：{quote.time:%Y-%m-%d %H:%M:%S}")
    for direction, threshold in enabled_directions(market):
        lines.append(
            threshold_line(
                direction,
                threshold,
                market["unit"],
                quote.price,
                direction.name not in state.armed,
                rearm_ratio,
            )
        )
    lines.append(f"  状态：{market_status(market, state)}")
    return lines


def render_frame(markets, quotes, errors, states, rearm_ratio):
    """渲染整帧控制台内容：每个市场一段，段间空行分隔（纯函数）。

    quotes、errors 均按市场代码索引；缺读数的市场由 errors 给出原因（数据源故障）。
    """
    lines = []
    for market in markets:
        code = market["code"]
        lines.extend(
            render(market, quotes.get(code), errors.get(code), states[code], rearm_ratio)
        )
        lines.append("")
    return lines


def alert_log_line(alert, at):
    """触发日志行：带触发时刻的时间戳，留在控制台滚动区。"""
    return (
        f"[{at:%Y-%m-%d %H:%M:%S}] 触发：{alert.market} {alert.direction} "
        f"{alert.threshold:.2f} {alert.unit}（现价 {alert.price:.2f}，"
        f"数据时间 {alert.data_time:%Y-%m-%d %H:%M:%S}）"
    )


# ======================= 弹窗与提示音（副作用层） =======================
# 弹窗用一个常驻后台线程持有 Tk 根窗；主循环只往队列里投递提醒，
# 因此弹窗既不阻塞轮询，也不与行情取数抢线程。
POPUP_MARGIN = 24  # 距屏幕工作区右下角的留白（像素）
POPUP_GAP = 10  # 多个弹窗上下叠放时的间距（像素）
POPUP_BG = "#1e1f22"
POPUP_FG = "#f0f0f0"
POPUP_DIM = "#a8a8a8"
POPUP_FAINT = "#787878"
POPUP_FONT = "Microsoft YaHei UI"
# 涨红跌绿，沿用国内行情习惯
DIRECTION_COLOR = {UPSIDE: "#e5534b", DOWNSIDE: "#3fb950"}

GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
SPI_GETWORKAREA = 0x0030

_alerts = queue.Queue()
_ui_ready = threading.Event()
_ui_error = None
_ui_root = None
_open_popups = []


def start_notifier():
    """启动弹窗线程（进程内一次）；返回弹窗是否可用。"""
    threading.Thread(target=_ui_main, name="弹窗", daemon=True).start()
    ready = _ui_ready.wait(timeout=5)
    return ready and _ui_error is None


def notify(alert):
    """投递一次提醒：一声短提示音（可关）＋ 弹窗线程显示右下角小窗。"""
    if SOUND_ENABLED:
        _play_chime()
    _alerts.put(alert)


def _play_chime():
    """一声短提示音；无音频设备时静音退化，不影响提醒本身。"""
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        try:
            winsound.Beep(880, 180)
        except Exception:
            pass


def _ui_main():
    """弹窗线程主函数：建 Tk 根窗后进入事件循环；所有 Tk 调用都留在本线程。"""
    global _ui_root, _ui_error
    try:
        _enable_dpi_awareness()
        previous_foreground = ctypes.windll.user32.GetForegroundWindow()
        _ui_root = tk.Tk()
        _ui_root.withdraw()
        # 根窗创建后 Windows 会稍迟送来一次激活（此时窗口已隐藏），过一小会儿再确认还给原窗口
        _keep_foreground(previous_foreground)
        _ui_root.after(250, lambda: _keep_foreground(previous_foreground))
        _pump_alerts()
    except Exception as exc:
        _ui_error = f"{type(exc).__name__}: {exc}"
        _ui_ready.set()
        return
    _ui_ready.set()
    _ui_root.mainloop()


def _pump_alerts():
    """弹窗线程内的定时泵：把队列中的提醒逐个弹出。"""
    while True:
        try:
            alert = _alerts.get_nowait()
        except queue.Empty:
            break
        try:
            _show_popup(alert)
        except Exception as exc:  # 单个弹窗失败不拖垮弹窗线程
            print(f"弹窗显示失败：{type(exc).__name__}: {exc}", flush=True)
    _ui_root.after(200, _pump_alerts)


def _show_popup(alert):
    """右下角弹出一个无边框小窗：不抢焦点，点击即关，POPUP_DURATION 秒后自动消失。"""
    accent = DIRECTION_COLOR.get(alert.direction, "#e6b450")
    window = tk.Toplevel(_ui_root)
    window.withdraw()
    window.overrideredirect(True)
    window.attributes("-topmost", True)
    window.configure(bg=accent)

    card = tk.Frame(window, bg=POPUP_BG, padx=18, pady=14)
    card.pack(padx=2, pady=2)  # 2 像素的方向色描边
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
    return 0, 0, _ui_root.winfo_screenwidth(), _ui_root.winfo_screenheight()


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


def _enable_dpi_awareness():
    """高分屏下按系统缩放渲染窗口，文字不模糊（尽力而为）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def run():
    """主循环：每 REFRESH_INTERVAL 秒取数、上屏并判定；越线即弹窗提醒，随后继续监视。"""
    if not start_notifier():
        sys.stdout.write(
            f"弹窗不可用（{_ui_error or '启动超时'}），提醒将只出现在控制台。{NEWLINE}"
        )
    codes = [market["code"] for market in MARKETS]
    states = {market["code"]: INITIAL_STATE for market in MARKETS}
    frame_lines = 0
    cycle = 0
    while True:
        cycle += 1
        now = datetime.now()
        lines = [
            f"金价监视中——每 {REFRESH_INTERVAL} 秒刷新，Ctrl+C 或关闭窗口停止",
            f"本次刷新：{now:%Y-%m-%d %H:%M:%S}",
            "",
        ]
        try:
            raw = fetch_raw(codes)
            fetch_error = None
        except Exception as exc:  # 单轮取数失败不退出，下一轮自动重试
            raw = ""
            fetch_error = f"{type(exc).__name__}: {exc}"
        quotes = {}
        errors = {}
        for market in MARKETS:
            code = market["code"]
            errors[code] = fetch_error
            if fetch_error is None:
                line = next((l for l in raw.splitlines() if code in l), "")
                try:
                    quotes[code] = parse_quote(line, code)
                except QuoteError as exc:
                    errors[code] = str(exc)
        alerts, states = evaluate_markets(MARKETS, quotes, states, REARM_RATIO)
        lines.extend(render_frame(MARKETS, quotes, errors, states, REARM_RATIO))
        delay = next_refresh_delay(now, REFRESH_INTERVAL)
        next_fire = now.replace(microsecond=0) + timedelta(seconds=delay)
        lines.append(
            f"下次刷新：{next_fire:%H:%M:%S}（约 {delay} 秒后，第 {cycle} 轮）"
        )
        for alert in alerts:
            notify(alert)
        at = datetime.now()
        # 回到本帧起点并清掉旧内容，原地刷新；有提醒时让日志行落在旧帧的位置上
        if frame_lines:
            sys.stdout.write(f"\x1b[{frame_lines}A")
            frame_lines = 0
        if alerts:
            sys.stdout.write(
                "\x1b[J"
                + NEWLINE.join(alert_log_line(alert, at) for alert in alerts)
                + NEWLINE
            )
        sys.stdout.write("\x1b[J" + NEWLINE.join(lines) + NEWLINE)
        sys.stdout.flush()
        frame_lines = len(lines)
        time.sleep(delay)


def main():
    try:
        run()
    except KeyboardInterrupt:
        print("\r\n监视已停止。")
    except Exception:
        traceback.print_exc()
        input("脚本出错，按回车键关闭窗口……")
        sys.exit(1)


if __name__ == "__main__":
    main()
