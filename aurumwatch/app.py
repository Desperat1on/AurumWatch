# -*- coding: utf-8 -*-
"""编排：主窗口、轮询线程、提醒与视图模型的接线。

分工：Tk 只在主线程碰，取数（阻塞的网络请求）放在后台线程；每一轮算好的视图
模型经队列交给主线程上屏——窗口不因取数卡住，提醒也不会漏。
"""

import queue
import sys
import threading
import traceback
from datetime import datetime

from aurumwatch.alerts import INITIAL_STATE, evaluate_markets
from aurumwatch.failures import INITIAL_FAILURE, update_failures
from aurumwatch.main_window import MainWindow, enable_dpi_awareness, show_error_box
from aurumwatch.popup import attach, drain_ui_errors, notify
from aurumwatch.quotes import fetch_rounds
from aurumwatch.schedule import next_refresh_delay
from aurumwatch.settings import (
    FAILURE_WARN_AFTER,
    MARKETS,
    REARM_RATIO,
    REFRESH_INTERVAL,
)
from aurumwatch.viewmodel import window_view

PUMP_MS = 200  # 主线程取一次取数结果的间隔


def run():
    """打开主窗口开始监视：后台线程按整分取数、判定与记账，越线即弹窗提醒。

    关闭主窗口即退出监视（见 ADR-0001：不做托盘、不藏后台进程）。
    """
    enable_dpi_awareness()
    wake = threading.Event()  # [立即刷新] 用它提前结束等待中的取数线程
    frames = queue.Queue()
    window = MainWindow(on_refresh=wake.set)
    attach(window.root)
    threading.Thread(
        target=_poll_loop, args=(frames, wake), name="取数", daemon=True
    ).start()
    _show_frames(window, frames)
    window.run()


def _poll_loop(frames, wake):
    """轮询线程：取数 → 判定与记账 → 投递提醒与视图模型 → 等到下一个整分。"""
    states = {market["code"]: INITIAL_STATE for market in MARKETS}
    failures = {market["code"]: INITIAL_FAILURE for market in MARKETS}
    while True:
        rounds = fetch_rounds(MARKETS)
        # 本轮的记账与显示时刻取在取数之后：窗口上「下次刷新」的秒数与这里真正要等的
        # 秒数出自同一个时刻，不会出现「显示还有 2 秒、实际却等了一分钟」。
        at = datetime.now()
        alerts, states = evaluate_markets(rounds, states, REARM_RATIO)
        failures, warnings = update_failures(rounds, failures, at, FAILURE_WARN_AFTER)
        for event in (*alerts, *warnings):
            notify(event)
        frames.put(
            window_view(
                rounds,
                states,
                failures,
                at,
                interval=REFRESH_INTERVAL,
                rearm_ratio=REARM_RATIO,
                warn_after=FAILURE_WARN_AFTER,
            )
        )
        # 从同一个 at 起算：取数耗时已含在内，下一轮仍落在整分上（[立即刷新] 后
        # 同样如此），窗口上显示的秒数与实际要等的秒数一致。取数期间点的那一下
        # 已由这一轮兑现，清掉标记，不再补取一轮。
        wake.clear()
        wake.wait(next_refresh_delay(at, REFRESH_INTERVAL))


def _show_frames(window, frames):
    """主线程：把取数线程算好的视图模型摆上窗口，并转达弹窗的报错。"""
    while True:
        try:
            view = frames.get_nowait()
        except queue.Empty:
            break
        window.show(view)
    messages = drain_ui_errors()
    if messages:
        window.show_notice("弹窗显示失败：" + "；".join(messages))
    window.root.after(PUMP_MS, lambda: _show_frames(window, frames))


def main():
    """入口：把启动与运行期的意外兜成系统消息框（没有控制台可打印）。"""
    try:
        run()
    except KeyboardInterrupt:
        pass  # 从终端 Ctrl+C：与关闭主窗口同义
    except Exception:
        show_error_box(f"AurumWatch 出错退出：\n\n{traceback.format_exc()}")
        sys.exit(1)
