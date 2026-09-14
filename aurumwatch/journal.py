# -*- coding: utf-8 -*-
"""事件记录（内存近况）与日志（落盘档案）：一条事件两处同文。

`record` 一处写两处：当天的日志文件与主窗口的事件记录区出现的是同一条内容，只是
近况只留最近 `RECENT_LIMIT` 条、重启即失（见 ticket 05）。记的是事件——触发、故障
警告、故障出现与恢复、启停、设置保存、配置回退、弹窗失败——逐轮行情一个字不记。

日志按天分文件（`logs/aurumwatch-YYYY-MM-DD.log`），启动时清掉超过 30 天的旧文件
（见 ADR-0003）。轮询线程（触发、故障与警告）与主线程（启停、设置、弹窗失败）都会
写它，故内部加锁；写不进去（只读目录等）也不打断监视——档案宁可缺，监视不能停，
只在事件记录里说一声。
"""

import os
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

from aurumwatch.alerts import Alert
from aurumwatch.config import base_dir
from aurumwatch.failures import FailureChange, FailureWarning, duration_text

LOG_DIR_NAME = "logs"
LOG_PREFIX = "aurumwatch-"
LOG_SUFFIX = ".log"
DAY_FORMAT = "%Y-%m-%d"
STAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

KEEP_DAYS = 30  # 日志留几天（见 ADR-0003）：更旧的按天文件在启动时清掉
RECENT_LIMIT = 50  # 事件记录摆几条（见 ticket 05）：更早的只在日志里

STARTUP_TEXT = "AurumWatch 启动"
SHUTDOWN_TEXT = "AurumWatch 退出"
SETTINGS_SAVED_TEXT = "设置已保存"


def log_dir():
    """日志目录：与配置文件同位（打包在 exe 旁、源码在仓库根，见 ADR-0002）。"""
    return base_dir() / LOG_DIR_NAME


def line_text(text, at):
    """一条日志／事件记录的整行：发生时刻 + 事由（事件记录与日志因此逐字相同）。"""
    return f"{at:{STAMP_FORMAT}} {text}"


def alert_text(alert):
    """一次触发：方向、市场，以及现价、阈值与行情数据时间。"""
    return (
        f"触发：{alert.market} {alert.direction}——现价 {alert.price:.2f} {alert.unit}，"
        f"阈值 {alert.threshold:.2f} {alert.unit}，"
        f"行情时间 {alert.data_time:{STAMP_FORMAT}}"
    )


def warning_text(warning):
    """一次故障警告：哪个市场、连续失败多久、从什么时候起、最近错在哪。"""
    return (
        f"故障警告：{warning.market} 已连续 {duration_text(warning.elapsed)}取数失败"
        f"（自 {warning.since:{STAMP_FORMAT}} 起，最近错误：{warning.error}）"
    )


def failure_text(change):
    """一次故障出现或恢复：出现时报错误，恢复时报这次故障持续了多久。"""
    if change.recovered:
        return (
            f"数据源恢复：{change.market} 又能取到行情了"
            f"（此前连续失败 {duration_text(change.elapsed)}）"
        )
    return f"数据源故障：{change.market} 取数失败（{change.error}）"


def round_texts(changes, alerts, warnings):
    """一轮里发生的全部事件 → 要记的文字（纯函数，顺序即讲故事的顺序）。

    先说数据源状况（为什么有的市场没有读数），再说行情事件，最后是被升级出来的警告。
    没有事件（多数轮次）时是空元组——逐轮行情不进任何一处。
    """
    return (
        *(failure_text(change) for change in changes),
        *(alert_text(alert) for alert in alerts),
        *(warning_text(warning) for warning in warnings),
    )


def file_name(day):
    """某一天的日志文件名：一天一份。"""
    return f"{LOG_PREFIX}{day:{DAY_FORMAT}}{LOG_SUFFIX}"


def file_date(name):
    """日志文件名 → 它属于哪一天；不是本程序按天写的日志则为 None。

    认名字要认到分毫不差（`file_name` 得能原样写回来）：这里的结论会用来删文件，
    「差不多像我们的」不够——`2026-1-1` 这种手写的名字不算。
    """
    if not (name.startswith(LOG_PREFIX) and name.endswith(LOG_SUFFIX)):
        return None
    try:
        day = datetime.strptime(
            name[len(LOG_PREFIX) : -len(LOG_SUFFIX)], DAY_FORMAT
        ).date()
    except ValueError:
        return None
    return day if file_name(day) == name else None


def stale_logs(names, today, keep_days=KEEP_DAYS):
    """一批文件名里该清理的日志：本程序按天写的，且超过 keep_days 天。

    边界上宁可多留一天：整 keep_days 天前的那份留着，第 keep_days + 1 天才清。
    认不出的名字一个不碰——这里的删除要落在用户的文件夹里，只认自己写的格式。
    """
    return tuple(
        name
        for name in names
        if (day := file_date(name)) is not None and (today - day).days > keep_days
    )


class Journal:
    """一次运行的记录器：当天的日志文件 + 内存里的事件记录。

    两处写的是同一条内容，差别只在留多久：事件记录是本次运行的近况（重启即清空、
    只留最近 RECENT_LIMIT 条，见 ticket 05），日志是长期档案。
    """

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory is not None else log_dir()
        self._lock = threading.Lock()  # 两个线程都会写它（见模块开头的说明）
        self._entries = []  # 事件记录：旧→新，最新的在末尾
        self._problem = None  # 上一次报过的写失败（写成功即清，见 _append）

    def start(self):
        """开张：建日志目录、清掉超过 KEEP_DAYS 天的旧日志、清空事件记录。

        清不掉（被占着、是目录、没权限）也不挡启动：那一份留着，其余照清。一份清不动
        就撂下整轮的话，清得掉的也跟着留下——挡路的那份不会自己消失，等于再也清不动。
        """
        with self._lock:
            self._entries.clear()
            self._problem = None
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                names = [item.name for item in self.directory.iterdir()]
            except OSError:
                return
            for name in stale_logs(names, date.today()):
                try:
                    (self.directory / name).unlink(missing_ok=True)
                except OSError:
                    pass

    def record(self, text, at=None):
        """记一条事件：写进当天的日志，同时摆进主窗口的事件记录（两处同一条内容）。"""
        self._write(text, at)

    def recent(self):
        """事件记录的当前内容（旧→新）：窗口照它摆，最新的那条在场尾。"""
        with self._lock:
            return tuple(self._entries)

    def open_dir(self):
        """在资源管理器中打开日志目录（[打开日志]按钮）；打不开时抛 OSError。"""
        self.directory.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.directory))

    def _write(self, text, at):
        at = at or datetime.now()
        line = line_text(text, at)
        with self._lock:
            self._remember(line)
            self._append(line, at)

    def _remember(self, line):
        """事件记录只留最近 RECENT_LIMIT 条：更早的只在日志里（近况 vs 档案）。"""
        self._entries.append(line)
        del self._entries[: -RECENT_LIMIT]

    def _append(self, line, at):
        """把整行追加到当天的日志文件。

        写不进去**只说一次**，但每一条都还会再试：写不进去往往是「这会儿写不进去」
        （文件被同步软件占着、logs/ 被顺手删掉），不是永久的判决——把它当永久的，
        等于一次抖动就把这一天的档案丢了。写成功了就把这句话忘掉，日后再坏还会说。
        """
        try:
            # 每写一次带上建目录：运行期被人把 logs/ 删了，下一件事照样落得下盘
            self.directory.mkdir(parents=True, exist_ok=True)
            path = self.directory / file_name(at.date())
            with open(path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
        except OSError as exc:
            if self._problem is None:
                # 说给用户听的话摆在事件记录里（日志自己写不进去，只能摆在这儿）。
                # 也走 line_text：记录里每一条都是「时刻 + 事由」，这一条不是例外
                self._problem = f"日志写不进去（{exc.strerror or exc}）"
                self._remember(
                    line_text(f"{self._problem}，本次运行的事件只留在窗口里", at)
                )
        else:
            self._problem = None
