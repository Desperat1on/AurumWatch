# -*- coding: utf-8 -*-
"""编排：主窗口、设置窗口、轮询线程、提醒、事件记录与视图模型的接线。

分工：Tk 只在主线程碰，取数（阻塞的网络请求）放在后台线程；每一轮算好的视图
模型经队列交给主线程上屏——窗口不因取数卡住，提醒也不会漏。可调项每轮从配置
快照现取，所以[保存]之后无需重启（见 ticket 03）。外观同理：保存后主窗口与后续
弹窗当场换新（见 ticket 04）。

事件记录与日志都由 `Journal` 管：一条事件两处同文，只是近况只留最近 50 条
（见 ticket 05）。入口先过一道单实例（见 ticket 06）：已经有一份在跑时，这一头
把那份的主窗口带到前台就退场，不再跑出第二份监视。
"""

import queue
import sys
import threading
import traceback
from datetime import datetime, timedelta

from aurumwatch import single_instance
from aurumwatch.alerts import INITIAL_STATE, evaluate_markets
from aurumwatch.config import ConfigStore, markets
from aurumwatch.failures import INITIAL_FAILURE, update_failures
from aurumwatch.journal import (
    SETTINGS_SAVED_TEXT,
    SHUTDOWN_TEXT,
    STARTUP_TEXT,
    Journal,
    round_texts,
)
from aurumwatch.main_window import MainWindow, enable_dpi_awareness, show_error_box
from aurumwatch.popup import attach, drain_ui_errors, notify, set_theme
from aurumwatch.quotes import fetch_rounds
from aurumwatch.schedule import next_refresh_delay
from aurumwatch.settings_window import open_settings
from aurumwatch.theme import Theme
from aurumwatch.viewmodel import window_view

PUMP_MS = 200  # 主线程取一次取数结果与事件记录的间隔
ERROR_WAIT_SECONDS = 30  # 一轮出错之后隔多久再取：别空转，也别拖太久


def run(journal):
    """打开主窗口开始监视：后台线程按整分取数、判定与记账，越线即弹窗提醒。

    关闭主窗口即退出监视（见 ADR-0001：不做托盘、不藏后台进程），退出时日志留一条。
    """
    enable_dpi_awareness()
    store = ConfigStore()
    notices = store.load()
    journal.start()
    journal.record(STARTUP_TEXT)
    wake = threading.Event()  # [立即刷新] 用它提前结束等待中的取数线程
    frames = queue.Queue()
    theme = Theme.from_appearance(store.values["appearance"])
    window = MainWindow(
        on_refresh=wake.set,
        on_settings=lambda: open_settings(
            window.root, store, on_saved=lambda values: _applied(window, values, journal)
        ),
        on_logs=lambda: _open_logs(window, journal),
        on_error=journal.record,  # 窗口回调里的异常：留一条（没有控制台可打印）
        theme=theme,
    )
    attach(window.root)
    set_theme(theme)  # 弹窗与主窗口用同一份外观：只造一处，不会各拿各的
    for notice in notices:  # 配置回退这类事：提示行、事件记录与日志说的是同一句
        _tell(window, journal, f"配置：{notice}")
    threading.Thread(
        target=_poll_loop, args=(frames, wake, store, journal), name="取数", daemon=True
    ).start()
    try:
        _pump(window, frames, journal)  # 先摆一次：事件记录与开窗时的事不必等第一轮取数
        window.run()  # 进入窗口事件循环；关闭主窗口后返回
    finally:
        journal.record(SHUTDOWN_TEXT)  # 关窗与 Ctrl+C 都留一条（见 User Story 23）


def _applied(window, values, journal):
    """[保存]之后：主窗口与后续弹窗当场换用新外观（阈值与提示音由轮询线程按快照取）。"""
    theme = Theme.from_appearance(values["appearance"])
    set_theme(theme)
    window.apply(theme)
    _tell(window, journal, SETTINGS_SAVED_TEXT)  # 什么时候改过设置，日后翻得到（见 User Story 44）


def _open_logs(window, journal):
    """[打开日志]：在资源管理器里打开日志文件夹；打不开就说一句。"""
    try:
        journal.open_dir()
    except OSError as exc:
        _tell(window, journal, f"打不开日志文件夹：{exc.strerror or exc}")


def _tell(window, journal, text):
    """一条要当面告诉用户的事：底部提示行摆上，同时记进事件记录与日志。

    两处一起说，是因为提示行只停到下一帧（`MainWindow.show` 每轮清一次）——
    不留下一条记录的话，用户回过头来就再也看不到这件事。
    """
    window.show_notice(text)
    journal.record(text)


def _poll_loop(frames, wake, store, journal):
    """轮询线程：取数 → 判定与记账 → 投递提醒与视图模型 → 等到下一个整分。

    每一轮开头读一次配置快照：阈值、节奏与提示音都照最新的一份来——设置一保存
    下一轮就用上，不用重启。

    每一轮都包在一层网里：没有控制台，线程默默死掉就是一个再也不提醒的监视——
    谁也不知道。出错就记一条（同一条只说一次）再接着跑，不空转也不停摆。
    """
    codes = [market["code"] for market in markets(store.values)]
    states = {code: INITIAL_STATE for code in codes}
    failures = {code: INITIAL_FAILURE for code in codes}
    unseen = frozenset(codes)  # 还没取到过读数的市场（见下面的「启动时若已越线」）
    reported = set()  # 说过的出错：同一句话不每轮刷一条
    while True:
        try:
            cfg = store.values
            advanced = cfg["advanced"]
            rounds = fetch_rounds(markets(cfg))
            # 本轮的记账与显示时刻取在取数之后：窗口上「下次刷新」的秒数与这里真正要等的
            # 秒数出自同一个时刻，不会出现「显示还有 2 秒、实际却等了一分钟」。
            at = datetime.now()
            read_codes = frozenset(
                round_.market["code"] for round_ in rounds if not round_.failed
            )
            # 「启动时若已越线立即提醒」关掉时：某市场第一次取到读数的那一轮，越线只记账
            # 不出声——否则这一轮过后价格还压在阈值外面，下一轮照样提醒，等于没关。
            silent = frozenset() if advanced["alert_on_start"] else unseen & read_codes
            unseen -= read_codes
            alerts, states = evaluate_markets(
                rounds, states, advanced["rearm_ratio"], silent=silent
            )
            warn_after = timedelta(minutes=advanced["failure_warn_minutes"])
            failures, warnings, changes = update_failures(
                rounds, failures, at, warn_after
            )
            for event in (*alerts, *warnings):
                notify(event, sound=cfg["sound"])
            # 这一轮发生的事记进事件记录与日志（窗口上看到的与日后翻到的是同一句话）；
            # 没有事件的轮次一个字都不写——逐轮行情不进任何一处（见 ADR-0003）。
            for text in round_texts(changes, alerts, warnings):
                journal.record(text, at)
            frames.put(
                window_view(
                    rounds,
                    states,
                    failures,
                    at,
                    interval=advanced["refresh_interval"],
                    rearm_ratio=advanced["rearm_ratio"],
                    warn_after=warn_after,
                )
            )
            # 从同一个 at 起算：取数耗时已含在内，下一轮仍落在整分上（[立即刷新] 后
            # 同样如此），窗口上显示的秒数与实际要等的秒数一致。取数期间点的那一下
            # 已由这一轮兑现，清掉标记，不再补取一轮。
            wake.clear()
            delay = next_refresh_delay(at, advanced["refresh_interval"])
        except Exception as exc:  # 一轮的意外不该让监视停摆（见方法开头的说明）
            note = f"{type(exc).__name__}: {exc}"
            if note not in reported:
                reported.add(note)
                journal.record(f"取数线程出错：{note}")
            delay = ERROR_WAIT_SECONDS  # 出错也按节奏来，别空转
        wake.wait(delay)  # 出错时这一轮点过的[立即刷新]仍然算数（不清标记，立刻再试）


def _pump(window, frames, journal):
    """主线程：把取数线程算好的视图模型与最新的事件记录摆上窗口，并转达弹窗与提示音的报错。

    每条报错自带说法（「弹窗显示失败：…」「提示音：…」），这里只负责原样转达——
    提示行摆最新的一条，事件记录与日志里攒着这一轮的每一条（见 ticket 05）。
    """
    while True:
        try:
            view = frames.get_nowait()
        except queue.Empty:
            break
        window.show(view)
    for message in drain_ui_errors():
        _tell(window, journal, message)
    window.show_events(journal.recent())
    window.root.after(PUMP_MS, lambda: _pump(window, frames, journal))


def main():
    """入口：单实例把关，再把启动与运行期的意外兜成系统消息框，并在日志里留一条。

    已经有一份在跑时，第二次启动不留痕迹地退场（见 ticket 06）：把那一份的主窗口
    带到前台就够了，这里连日志都不开——「重复双击」不是一次启动。
    """
    if not single_instance.claim():
        single_instance.focus_existing()
        return
    journal = Journal()
    try:
        run(journal)
    except KeyboardInterrupt:
        pass  # 从终端 Ctrl+C：与关闭主窗口同义
    except Exception:
        # 出错退出的调用栈整段写进日志（续行缩进四格，一眼看出属于哪一条）：
        # 这种时候没有别处可看——消息框一闪而过，没有控制台可打印
        report = traceback.format_exc().strip()
        journal.record("AurumWatch 出错退出：" + report.replace("\n", "\n    "))
        show_error_box(f"AurumWatch 出错退出：\n\n{report}")
        sys.exit(1)
