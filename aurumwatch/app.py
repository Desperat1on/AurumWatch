# -*- coding: utf-8 -*-
"""编排：轮询取数、判定与记账、弹窗提醒、控制台上屏。

副作用都在这一层：每轮取数后把纯函数的判定结果交给弹窗与控制台。
"""

import sys
import time
import traceback
from datetime import datetime, timedelta

from aurumwatch.alerts import INITIAL_STATE, evaluate_markets
from aurumwatch.console import (
    NEWLINE,
    alert_log_line,
    render_frame,
    terminal_width,
    warning_log_line,
    wrap_lines,
)
from aurumwatch.failures import INITIAL_FAILURE, update_failures
from aurumwatch.popup import drain_ui_errors, notifier_error, notify, start_notifier
from aurumwatch.quotes import fetch_rounds, next_refresh_delay
from aurumwatch.settings import (
    FAILURE_WARN_AFTER,
    MARKETS,
    REARM_RATIO,
    REFRESH_INTERVAL,
)


def run():
    """主循环：每 REFRESH_INTERVAL 秒逐市场取数、上屏并判定；越线即弹窗提醒，
    长时间取数失败弹一次故障警告，随后继续监视。"""
    if not start_notifier():
        sys.stdout.write(
            f"弹窗不可用（{notifier_error()}），提醒将只出现在控制台。{NEWLINE}"
        )
    states = {market["code"]: INITIAL_STATE for market in MARKETS}
    failures = {market["code"]: INITIAL_FAILURE for market in MARKETS}
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
        rounds = fetch_rounds(MARKETS)
        alerts, states = evaluate_markets(rounds, states, REARM_RATIO)
        failures, warnings = update_failures(rounds, failures, now, FAILURE_WARN_AFTER)
        lines.extend(
            render_frame(rounds, states, failures, now, REARM_RATIO, FAILURE_WARN_AFTER)
        )
        delay = next_refresh_delay(now, REFRESH_INTERVAL)
        next_fire = now.replace(microsecond=0) + timedelta(seconds=delay)
        lines.append(
            f"下次刷新：{next_fire:%H:%M:%S}（约 {delay} 秒后，第 {cycle} 轮）"
        )
        for event in (*alerts, *warnings):
            notify(event)
        at = datetime.now()
        log_lines = [alert_log_line(alert, at) for alert in alerts]
        log_lines.extend(warning_log_line(warning, at) for warning in warnings)
        # 弹窗线程的报错也做成日志行，避免它直接写屏打断原地刷新
        log_lines.extend(
            f"[{at:%Y-%m-%d %H:%M:%S}] 弹窗显示失败：{message}"
            for message in drain_ui_errors()
        )
        # 自己折行：屏幕上的物理行数与这里的计数必须一致，上移量才算得准
        width = terminal_width()
        if width:
            log_rows = wrap_lines(log_lines, width - 1)  # 留 1 列余量防边界差异
            frame_rows = wrap_lines(lines, width - 1)
        else:
            log_rows, frame_rows = log_lines, lines  # 重定向输出：无光标可回，不折行
        # 回到本帧起点并清掉旧内容，原地刷新；有提醒时让日志行落在旧帧的位置上
        if frame_lines:
            sys.stdout.write(f"\x1b[{frame_lines}A")
            frame_lines = 0
        if log_rows:
            sys.stdout.write("\x1b[J" + NEWLINE.join(log_rows) + NEWLINE)
        sys.stdout.write("\x1b[J" + NEWLINE.join(frame_rows) + NEWLINE)
        sys.stdout.flush()
        frame_lines = len(frame_rows)
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
