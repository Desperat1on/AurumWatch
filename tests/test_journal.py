# -*- coding: utf-8 -*-
"""事件记录与日志：一条事件两处同文、按天分文件、清理 30 天前的旧文件。

窗口怎么摆事件记录、日志文件夹怎么打开属于手动验收；这里断言的是对外承诺：
事件 → 文字（触发、故障警告、故障出现与恢复）、文件 → 该清哪些、写进去的是什么
（见 ADR-0003，落盘一律用临时目录）。
"""

import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest import mock

from aurumwatch.alerts import Alert
from aurumwatch.failures import FailureChange, FailureWarning
from aurumwatch.journal import (
    KEEP_DAYS,
    RECENT_LIMIT,
    Journal,
    alert_text,
    failure_text,
    file_date,
    file_name,
    line_text,
    log_dir,
    round_texts,
    stale_logs,
    warning_text,
)

AT = datetime(2026, 9, 14, 12, 0, 0)
STAMP = "2026-09-14 12:00:00"
TODAY = date(2026, 9, 14)


def alert():
    """一次触发：国内金价刚越过 950.00 涨破阈值。"""
    return Alert(
        market="国内金价",
        direction="涨破",
        price=Decimal("951.24"),
        threshold=Decimal("950.00"),
        unit="元/克",
        data_time=datetime(2026, 9, 14, 11, 59, 30),
    )


def warning():
    """一次故障警告：国际金价连续取数失败满 10 分钟。"""
    return FailureWarning(
        market="国际金价",
        detail="伦敦金（XAU/USD 现货黄金）",
        since=datetime(2026, 9, 14, 11, 50, 0),
        elapsed=timedelta(minutes=10),
        error="ConnectionError: 连接失败",
    )


def appeared():
    """故障出现：国内金价这一轮开始取不到行情。"""
    return FailureChange(market="国内金价", recovered=False, error="Timeout: 请求超时")


def recovered():
    """故障恢复：国际金价连续失败 3 分钟后又能取到了。"""
    return FailureChange(
        market="国际金价", recovered=True, elapsed=timedelta(minutes=3)
    )


class EventTexts(unittest.TestCase):
    """事件 → 文字：一眼看得出是什么、哪个市场、数字多少（日志与事件记录共用）。"""

    def test_an_alert_carries_direction_price_threshold_and_market_time(self):
        self.assertEqual(
            alert_text(alert()),
            "触发：国内金价 涨破——现价 951.24 元/克，"
            "阈值 950.00 元/克，行情时间 2026-09-14 11:59:30",
        )

    def test_a_failure_warning_says_how_long_and_why(self):
        self.assertEqual(
            warning_text(warning()),
            "故障警告：国际金价 已连续 10 分钟取数失败"
            "（自 2026-09-14 11:50:00 起，最近错误：ConnectionError: 连接失败）",
        )

    def test_a_failure_appearing_says_which_market_and_why(self):
        self.assertEqual(
            failure_text(appeared()),
            "数据源故障：国内金价 取数失败（Timeout: 请求超时）",
        )

    def test_a_failure_recovering_says_how_long_it_lasted(self):
        self.assertEqual(
            failure_text(recovered()),
            "数据源恢复：国际金价 又能取到行情了（此前连续失败 3 分钟）",
        )

    def test_a_line_starts_with_the_moment_it_happened(self):
        self.assertEqual(
            line_text("触发：国内金价 涨破", AT), f"{STAMP} 触发：国内金价 涨破"
        )

    def test_a_round_is_told_in_the_order_it_happened(self):
        """同一轮：先讲数据源的状况（为什么有的市场没读数），再行情事件，最后警告。"""
        self.assertEqual(
            round_texts([appeared(), recovered()], [alert()], [warning()]),
            (
                failure_text(appeared()),
                failure_text(recovered()),
                alert_text(alert()),
                warning_text(warning()),
            ),
        )

    def test_a_quiet_round_produces_nothing(self):
        self.assertEqual(round_texts([], [], []), (), "逐轮行情不进任何一处")

    def test_a_round_with_only_failures_still_says_what_happened(self):
        self.assertEqual(round_texts([appeared()], [], []), (failure_text(appeared()),))


class LogFileNames(unittest.TestCase):
    """按天分文件：一天一个 aurumwatch-YYYY-MM-DD.log。"""

    def test_a_date_maps_to_its_file(self):
        self.assertEqual(file_name(TODAY), "aurumwatch-2026-09-14.log")

    def test_a_log_name_maps_back_to_its_date(self):
        self.assertEqual(file_date("aurumwatch-2026-09-14.log"), TODAY)

    def test_other_files_are_not_ours(self):
        for name in (
            "config.json",
            "aurumwatch.log",
            "备注.txt",
            "aurumwatch-坏.log",
            "aurumwatch-2026-13-45.log",
            "aurumwatch-2026-1-1.log",
            "aurumwatch-2026-09-14.log.bak",
        ):
            self.assertIsNone(file_date(name), name)

    def test_only_our_logs_older_than_the_kept_days_are_stale(self):
        names = [
            "aurumwatch-2026-08-14.log",
            "aurumwatch-2026-08-15.log",
            "aurumwatch-2026-09-14.log",
            "备注.txt",
        ]
        self.assertEqual(
            stale_logs(names, TODAY),
            ("aurumwatch-2026-08-14.log",),
            "31 天前的那份该清；整 30 天的那份留着（宁可多留一天，不可早删）",
        )

    def test_the_kept_days_can_be_changed(self):
        names = ["aurumwatch-2026-09-13.log", "aurumwatch-2026-09-14.log"]
        self.assertEqual(
            stale_logs(names, TODAY, keep_days=0), ("aurumwatch-2026-09-13.log",)
        )


class LogDirFollowsTheDelivery(unittest.TestCase):
    """日志与配置同位：打包运行在 exe 旁的 logs/，源码运行在仓库根的 logs/（见 ADR-0002）。"""

    def test_source_run_puts_it_at_the_repo_root(self):
        self.assertEqual(log_dir(), Path(__file__).resolve().parent.parent / "logs")

    def test_packaged_run_puts_it_beside_the_exe(self):
        with (
            mock.patch.object(sys, "frozen", True, create=True),
            mock.patch.object(sys, "executable", str(Path("D:/Apps/AurumWatch.exe"))),
        ):
            self.assertEqual(log_dir(), Path("D:/Apps/logs"))


class JournalWritesBothPlaces(unittest.TestCase):
    """一条事件两处同文：事件记录（内存近况）与当天的日志文件（落盘档案）。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name) / "logs"
        self.journal = Journal(self.directory)
        self.journal.start()

    def logged(self, day=TODAY):
        path = self.directory / file_name(day)
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def test_an_alert_lands_in_the_file_and_in_the_record_as_one_line(self):
        written = (
            f"{STAMP} 触发：国内金价 涨破——现价 951.24 元/克，"
            "阈值 950.00 元/克，行情时间 2026-09-14 11:59:30"
        )
        self.journal.record(alert_text(alert()), AT)
        self.assertEqual(self.journal.recent(), (written,), "事件记录里摆的就是这一条")
        self.assertEqual(
            self.logged(), written + "\n", "日志里是同一句话，前面挂着发生时刻"
        )

    def test_lifecycle_events_take_the_same_road(self):
        """启停、设置保存这类事与触发同一条路：窗口上看得到，日后也翻得到。"""
        self.journal.record("AurumWatch 启动", AT)
        self.assertEqual(self.journal.recent(), (f"{STAMP} AurumWatch 启动",))
        self.assertEqual(self.logged(), f"{STAMP} AurumWatch 启动\n")

    def test_events_append_in_the_order_they_happened(self):
        self.journal.record(alert_text(alert()), AT)
        self.journal.record(warning_text(warning()), AT + timedelta(minutes=1))
        self.assertEqual(
            self.journal.recent(),
            (
                f"{STAMP} {alert_text(alert())}",
                f"2026-09-14 12:01:00 {warning_text(warning())}",
            ),
        )
        self.assertEqual(len(self.logged().splitlines()), 2, "一天一个文件，接着往后写")

    def test_the_record_keeps_only_the_latest_events(self):
        for index in range(RECENT_LIMIT + 5):
            self.journal.record(f"触发：第 {index} 条", AT)
        entries = self.journal.recent()
        self.assertEqual(len(entries), RECENT_LIMIT, "事件记录只留最近 50 条")
        self.assertEqual(entries[0], f"{STAMP} 触发：第 5 条")
        self.assertEqual(entries[-1], f"{STAMP} 触发：第 54 条")
        self.assertEqual(
            len(self.logged().splitlines()), RECENT_LIMIT + 5, "更早的只在日志里"
        )

    def test_a_new_run_starts_with_an_empty_record(self):
        # 记在**今天**：紧跟着的 start() 会按真实日期清旧账，写死的那天过了 30 天
        # 就会被它当旧文件清掉，这条用例也就跟着过期了
        today = date.today()
        self.journal.record(alert_text(alert()), datetime.now())
        self.journal.start()
        self.assertEqual(self.journal.recent(), (), "重启即清空（近况不留档）")
        self.assertEqual(len(self.logged(today).splitlines()), 1, "已经写下的日志不动")

    def test_nothing_is_written_before_the_first_event(self):
        self.assertEqual(
            list(self.directory.iterdir()), [], "一轮行情不写一行：没事件就没文件"
        )

    def test_the_directory_is_created_on_demand(self):
        self.journal.record(alert_text(alert()), AT)
        self.assertTrue(self.directory.is_dir())

    def test_the_file_follows_the_day_of_the_event(self):
        self.journal.record(alert_text(alert()), AT)
        self.journal.record(alert_text(alert()), AT + timedelta(days=1))
        self.assertEqual(len(self.logged(TODAY).splitlines()), 1)
        self.assertEqual(
            len(self.logged(date(2026, 9, 15)).splitlines()), 1, "跨天另起一份"
        )


class JournalCleansUp(unittest.TestCase):
    """启动时清掉超过 30 天的旧日志，别人的文件一个不碰。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.directory = Path(self.folder.name) / "logs"
        self.directory.mkdir()

    def put(self, name, text="旧的\n"):
        path = self.directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def today(self):
        return date.today()

    def test_old_logs_are_removed_and_recent_ones_stay(self):
        old = self.put(file_name(self.today() - timedelta(days=KEEP_DAYS + 1)))
        edge = self.put(file_name(self.today() - timedelta(days=KEEP_DAYS)))
        fresh = self.put(file_name(self.today()))
        Journal(self.directory).start()
        self.assertFalse(old.exists(), "超过 30 天的清掉")
        self.assertTrue(edge.exists(), "整 30 天的留着")
        self.assertTrue(fresh.exists())

    def test_one_unremovable_file_does_not_stop_the_rest(self):
        """某一份清不掉（同名目录、被占着）不能把整轮清理撂下——撂下就永远清不掉了。"""
        stubborn = self.directory / file_name(
            self.today() - timedelta(days=KEEP_DAYS + 5)
        )
        stubborn.mkdir()  # 同名目录：unlink 清不掉
        first = self.put(file_name(self.today() - timedelta(days=KEEP_DAYS + 6)))
        last = self.put(file_name(self.today() - timedelta(days=KEEP_DAYS + 1)))
        with mock.patch.object(
            Path, "iterdir", return_value=iter([first, stubborn, last])
        ):
            Journal(self.directory).start()  # 顺序固定：清不动的那个夹在中间
        self.assertTrue(stubborn.is_dir(), "清不动的那份留着，不挡启动")
        self.assertFalse(first.exists(), "排在它前面的照清")
        self.assertFalse(last.exists(), "排在它后面的也照清")

    def test_files_that_are_not_ours_are_left_alone(self):
        mine = self.put("备注.txt")
        same_name_dir = self.directory / "aurumwatch-2026-01-01.log"
        same_name_dir.mkdir()
        Journal(self.directory).start()
        self.assertTrue(mine.exists(), "不是本程序的日志，不碰")
        self.assertTrue(same_name_dir.is_dir(), "同名的目录也不碰")

    def test_a_missing_directory_is_created(self):
        Journal(self.directory / "更深一层").start()
        self.assertTrue((self.directory / "更深一层").is_dir())


class JournalNeverBreaksTheWatch(unittest.TestCase):
    """日志写不进去（只读目录等）不该打断监视：说一句，接着跑。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.blocker = Path(self.folder.name) / "blocked"
        self.blocker.write_text("我是个文件，不是目录", encoding="utf-8")
        self.journal = Journal(self.blocker / "logs")  # 目录建不出来，写文件必然失败

    def test_a_write_failure_is_reported_once_and_never_raised(self):
        self.journal.start()
        self.journal.record(alert_text(alert()), AT)
        self.journal.record(alert_text(alert()), AT + timedelta(minutes=1))
        entries = self.journal.recent()
        self.assertEqual(len(entries), 3, "两条事件都在，外加一句说明")
        self.assertEqual(entries[0], f"{STAMP} {alert_text(alert())}")
        self.assertTrue(
            entries[1].startswith(f"{STAMP} 日志写不进去"),
            f"说明也是「时刻 + 事由」的一条，不是例外：{entries[1]}",
        )
        self.assertEqual(
            entries[2],
            f"2026-09-14 12:01:00 {alert_text(alert())}",
            "日志哑了，事件记录照常",
        )
        self.assertEqual(
            sum("日志写不进去" in entry for entry in entries), 1, "同一件事只说一次"
        )

    def test_a_write_that_failed_can_go_through_later(self):
        """写不进去是「这会儿写不进去」：挡路的没了，后面的事件照样落盘。"""
        self.journal.start()
        self.journal.record(alert_text(alert()), AT)
        self.blocker.unlink()  # 挡路的文件删掉，日志目录建得出来了
        self.journal.record(alert_text(alert()), AT + timedelta(minutes=1))
        self.assertEqual(
            (self.journal.directory / file_name(TODAY))
            .read_text(encoding="utf-8")
            .splitlines(),
            [f"2026-09-14 12:01:00 {alert_text(alert())}"],
            "恢复之后那一条写下去了（此前那条只在窗口里）",
        )


if __name__ == "__main__":
    unittest.main()
