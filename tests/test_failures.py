# -*- coding: utf-8 -*-
"""取数故障处理：失败记账、长时间故障警告与控制台呈现（纯函数，不碰网络与 UI）。"""

import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from watch_gold import (
    INITIAL_FAILURE,
    INITIAL_STATE,
    UPSIDE,
    FailureState,
    FailureWarning,
    MarketRound,
    Quote,
    duration_text,
    evaluate_markets,
    render,
    render_frame,
    update_failures,
    warning_log_line,
)

AT = datetime(2026, 9, 12, 12, 0, 0)
RATIO = Decimal("0.001")
WARN_AFTER = timedelta(minutes=10)
TIMEOUT = "Timeout: 请求超时"

# 配置与领域术语同形：两个市场各两个阈值，与其余测试文件各自自洽
DOMESTIC = {
    "name": "国内金价",
    "detail": "沪金99（上海黄金交易所 Au99.99）",
    "unit": "元/克",
    "code": "gds_AU9999",
    "up_threshold": Decimal("950.00"),
    "down_threshold": Decimal("900.00"),
}
INTERNATIONAL = {
    "name": "国际金价",
    "detail": "伦敦金（XAU/USD 现货黄金）",
    "unit": "美元/盎司",
    "code": "hf_XAU",
    "up_threshold": Decimal("4400.00"),
    "down_threshold": Decimal("4300.00"),
}
BOTH_MARKETS = (DOMESTIC, INTERNATIONAL)
INITIAL_STATES = {market["code"]: INITIAL_STATE for market in BOTH_MARKETS}
INITIAL_FAILURES = {market["code"]: INITIAL_FAILURE for market in BOTH_MARKETS}


def quoted(market, price):
    """该市场本轮取数成功：给定价格的读数。"""
    return MarketRound(market=market, quote=Quote(price=Decimal(price), time=AT))


def failed(market, error=TIMEOUT):
    """该市场本轮取数失败：只有故障原因，没有读数。"""
    return MarketRound(market=market, error=error)


def console_text(round_, failure, at=AT, warn_after=WARN_AFTER):
    """把单个市场的控制台段落拼成文本，便于断言。"""
    return "\n".join(render(round_, INITIAL_STATE, failure, at, RATIO, warn_after))


class MarketRoundInvariant(unittest.TestCase):
    """取数结果要么有读数、要么有故障原因，只有其一；坏的轮次在构造时就拦下。"""

    def test_round_must_carry_a_reading_or_a_failure(self):
        with self.assertRaises(ValueError):
            MarketRound(market=DOMESTIC)
        with self.assertRaises(ValueError):
            MarketRound(
                market=DOMESTIC,
                quote=Quote(price=Decimal("940.00"), time=AT),
                error=TIMEOUT,
            )


class FailureAccounting(unittest.TestCase):
    """每市场独立记账：连续失败起点、到点警告一次、恢复清零。"""

    def test_first_failed_round_starts_the_clock_without_warning(self):
        failures, warnings = update_failures(
            [failed(DOMESTIC)], INITIAL_FAILURES, AT, WARN_AFTER
        )
        self.assertEqual(warnings, (), "刚开始失败不警告")
        self.assertEqual(failures["gds_AU9999"], FailureState(since=AT))

    def test_no_warning_before_the_duration_is_reached(self):
        failures = {"gds_AU9999": FailureState(since=AT)}
        failures, warnings = update_failures(
            [failed(DOMESTIC)],
            failures,
            AT + timedelta(minutes=9, seconds=59),
            WARN_AFTER,
        )
        self.assertEqual(warnings, (), "差一秒不警告")
        self.assertFalse(failures["gds_AU9999"].warned)

    def test_warning_at_exactly_the_configured_duration(self):
        failures = {"gds_AU9999": FailureState(since=AT)}
        failures, warnings = update_failures(
            [failed(DOMESTIC, "HTTPError: 503")],
            failures,
            AT + WARN_AFTER,
            WARN_AFTER,
        )
        self.assertEqual(len(warnings), 1, "连续失败满 10 分钟警告一次")
        warning = warnings[0]
        self.assertEqual(warning.market, "国内金价")
        self.assertEqual(warning.detail, DOMESTIC["detail"])
        self.assertEqual(warning.since, AT)
        self.assertEqual(warning.elapsed, WARN_AFTER)
        self.assertEqual(warning.error, "HTTPError: 503")
        self.assertTrue(failures["gds_AU9999"].warned)

    def test_warning_does_not_repeat_while_still_failing(self):
        failures = {"gds_AU9999": FailureState(since=AT, warned=True)}
        for minutes in (11, 20, 60):
            failures, warnings = update_failures(
                [failed(DOMESTIC)], failures, AT + timedelta(minutes=minutes), WARN_AFTER
            )
            self.assertEqual(warnings, (), "警告只弹一次")

    def test_brief_failure_that_recovers_never_warns(self):
        failures, _ = update_failures(
            [failed(DOMESTIC)], INITIAL_FAILURES, AT, WARN_AFTER
        )
        failures, warnings = update_failures(
            [quoted(DOMESTIC, "940.00")],
            failures,
            AT + timedelta(minutes=5),
            WARN_AFTER,
        )
        self.assertEqual(warnings, (), "短暂故障恢复后不补警告")
        self.assertEqual(failures["gds_AU9999"], INITIAL_FAILURE)

    def test_success_resets_the_clock(self):
        failures = {"gds_AU9999": FailureState(since=AT, warned=True)}
        failures, warnings = update_failures(
            [quoted(DOMESTIC, "940.00")],
            failures,
            AT + timedelta(minutes=12),
            WARN_AFTER,
        )
        self.assertEqual(warnings, ())
        self.assertEqual(failures["gds_AU9999"], INITIAL_FAILURE, "恢复成功即清零")

    def test_long_failure_after_recovery_warns_again(self):
        """恢复成功后重新计时，再次长时间故障会再次警告。"""
        failures = {"gds_AU9999": FailureState(since=AT, warned=True)}
        recovered = AT + timedelta(minutes=12)
        failures, _ = update_failures(
            [quoted(DOMESTIC, "940.00")], failures, recovered, WARN_AFTER
        )
        restarted = recovered + timedelta(minutes=1)
        failures, warnings = update_failures(
            [failed(DOMESTIC)], failures, restarted, WARN_AFTER
        )
        self.assertEqual(warnings, (), "重新计时后不满时长不警告")
        self.assertEqual(failures["gds_AU9999"].since, restarted)
        failures, warnings = update_failures(
            [failed(DOMESTIC)], failures, restarted + timedelta(minutes=10), WARN_AFTER
        )
        self.assertEqual(len(warnings), 1, "再次满时长，再次警告")
        self.assertEqual(warnings[0].since, restarted)

    def test_warn_after_is_configurable(self):
        failures = {"gds_AU9999": FailureState(since=AT)}
        _, warnings = update_failures(
            [failed(DOMESTIC)],
            failures,
            AT + timedelta(minutes=5),
            timedelta(minutes=5),
        )
        self.assertEqual(len(warnings), 1, "警告时长可配置：5 分钟即触发")

    def test_markets_track_failures_independently(self):
        """一个市场故障期间，另一个市场照常：各自计时、互不牵连。"""
        failures = dict(INITIAL_FAILURES)
        fired = []
        for minutes in range(11):  # 国内一直失败，国际一直成功
            failures, warnings = update_failures(
                [failed(DOMESTIC), quoted(INTERNATIONAL, "4350.00")],
                failures,
                AT + timedelta(minutes=minutes),
                WARN_AFTER,
            )
            fired.extend(warning.market for warning in warnings)
        self.assertEqual(fired, ["国内金价"], "10 分钟后只有失败的那个市场警告")
        self.assertEqual(
            failures["hf_XAU"], INITIAL_FAILURE, "一直成功的市场从未计入失败"
        )

    def test_input_failure_states_are_not_mutated(self):
        failures = dict(INITIAL_FAILURES)
        update_failures(
            [failed(DOMESTIC), failed(INTERNATIONAL)], failures, AT, WARN_AFTER
        )
        self.assertEqual(failures, INITIAL_FAILURES, "传入的失败状态表不被就地修改")


class FailureNeverAlerts(unittest.TestCase):
    """取数失败的轮次不产生价格提醒，故障不会被当成行情。"""

    def test_failed_round_produces_no_alert(self):
        alerts, states = evaluate_markets(
            [failed(DOMESTIC), quoted(INTERNATIONAL, "4350.00")],
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(alerts, (), "没有读数就没有提醒")
        self.assertEqual(states["gds_AU9999"], INITIAL_STATE, "故障不改写触发状态")

    def test_failed_round_leaves_a_fired_market_fired(self):
        """已触发的市场在故障期间保持已触发，恢复后价格仍在线上不会重复提醒。"""
        _, states = evaluate_markets(
            [quoted(DOMESTIC, "955.00"), quoted(INTERNATIONAL, "4350.00")],
            INITIAL_STATES,
            RATIO,
        )
        alerts, states = evaluate_markets(
            [failed(DOMESTIC), quoted(INTERNATIONAL, "4350.00")], states, RATIO
        )
        self.assertEqual(alerts, ())
        alerts, _ = evaluate_markets(
            [quoted(DOMESTIC, "956.00"), quoted(INTERNATIONAL, "4350.00")],
            states,
            RATIO,
        )
        self.assertEqual(alerts, (), "故障期间没有回落，恢复后不重复提醒")

    def test_healthy_market_keeps_alerts_while_the_other_fails(self):
        alerts, _ = evaluate_markets(
            [failed(DOMESTIC), quoted(INTERNATIONAL, "4410.00")],
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(
            [(alert.market, alert.direction) for alert in alerts],
            [("国际金价", UPSIDE)],
            "国内故障不影响国际照常判定与提醒",
        )


class FailureConsole(unittest.TestCase):
    """故障轮次的控制台：醒目的错误行、连续失败时长与「数据源故障」状态。"""

    def test_error_line_is_prominent_and_shows_reason(self):
        text = console_text(
            failed(DOMESTIC), FailureState(since=AT - timedelta(minutes=3))
        )
        self.assertIn("!! 数据源故障：Timeout: 请求超时", text)
        self.assertIn("已连续失败 3 分钟（满 10 分钟将弹出警告）", text)
        self.assertIn("状态：数据源故障", text)
        self.assertNotIn("现价", text, "没有读数就不显示现价与距阈值距离，不用陈旧读数冒充行情")

    def test_warned_market_says_warning_was_shown(self):
        text = console_text(
            failed(DOMESTIC), FailureState(since=AT - timedelta(minutes=12), warned=True)
        )
        self.assertIn("已连续失败 12 分钟（已弹出警告）", text)

    def test_warn_hint_follows_the_configured_duration(self):
        text = console_text(
            failed(DOMESTIC),
            FailureState(since=AT),
            warn_after=timedelta(minutes=5),
        )
        self.assertIn("满 5 分钟将弹出警告", text)

    def test_frame_shows_the_healthy_market_as_usual(self):
        failures = {
            "gds_AU9999": FailureState(since=AT - timedelta(minutes=2)),
            "hf_XAU": INITIAL_FAILURE,
        }
        lines = render_frame(
            [failed(DOMESTIC), quoted(INTERNATIONAL, "4350.00")],
            INITIAL_STATES,
            failures,
            AT,
            RATIO,
            WARN_AFTER,
        )
        self.assertEqual(
            lines,
            [
                "【国内金价】沪金99（上海黄金交易所 Au99.99）",
                "  !! 数据源故障：Timeout: 请求超时",
                "  已连续失败 2 分钟（满 10 分钟将弹出警告）",
                "  状态：数据源故障",
                "",
                "【国际金价】伦敦金（XAU/USD 现货黄金）",
                "  现价：4350.00 美元/盎司",
                "  行情数据时间：2026-09-12 12:00:00",
                "  涨破阈值 4400.00 美元/盎司：距触发还差 50.00",
                "  跌破阈值 4300.00 美元/盎司：距触发还差 50.00",
                "  状态：监视中",
                "",
            ],
        )


class WarningLogLine(unittest.TestCase):
    """故障警告在控制台留一行带时间戳的日志，说明是数据源故障。"""

    def test_log_line_carries_timestamp_duration_and_reason(self):
        warning = FailureWarning(
            market="国内金价",
            detail=DOMESTIC["detail"],
            since=AT - WARN_AFTER,
            elapsed=WARN_AFTER,
            error=TIMEOUT,
        )
        self.assertEqual(
            warning_log_line(warning, AT),
            "[2026-09-12 12:00:00] 数据源故障警告：国内金价已连续取数失败 10 分钟"
            "（自 11:50:00 起；最近错误 Timeout: 请求超时）",
        )


class DurationText(unittest.TestCase):
    """时长文案：不足 1 分钟按秒，不足 1 小时按分钟，再长按小时加分钟。"""

    def test_seconds(self):
        self.assertEqual(duration_text(timedelta(seconds=45)), "45 秒")

    def test_minutes(self):
        self.assertEqual(duration_text(timedelta(minutes=10)), "10 分钟")

    def test_hours_and_minutes(self):
        self.assertEqual(duration_text(timedelta(hours=1, minutes=5)), "1 小时 5 分钟")


if __name__ == "__main__":
    unittest.main()
