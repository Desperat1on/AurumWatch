# -*- coding: utf-8 -*-
"""穿越触发判定单元测试（纯函数，不碰网络与 UI）。"""

import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from aurumwatch.alerts import DOWNSIDE, INITIAL_STATE, UPSIDE, evaluate_thresholds
from aurumwatch.console import render
from aurumwatch.failures import INITIAL_FAILURE, FailureState
from aurumwatch.quotes import MarketRound, Quote

AT = datetime(2026, 9, 12, 12, 0, 0)
RATIO = Decimal("0.001")
WARN_AFTER = timedelta(minutes=10)

# 配置与领域术语同形：国内金价，涨破 950、跌破 900，重新武装带取阈值的 0.1%
DOMESTIC = {
    "name": "国内金价",
    "detail": "沪金99（上海黄金交易所 Au99.99）",
    "unit": "元/克",
    "code": "gds_AU9999",
    "up_threshold": Decimal("950.00"),
    "down_threshold": Decimal("900.00"),
}


def reading(price):
    """一次读数：给定价格的 Quote，数据时间固定。"""
    return Quote(price=Decimal(price), time=AT)


def fired_state(price, market=DOMESTIC):
    """先喂一次越线读数，返回触发后的状态（考察已触发行为用）。"""
    _, state = evaluate_thresholds(market, reading(price), INITIAL_STATE, RATIO)
    return state


def console_text(price, state, market=DOMESTIC, error=None):
    """把一次控制台渲染拼成文本，便于断言；取数失败时失败记账自本次刷新起算。"""
    if price is None:
        round_ = MarketRound(market=market, error=error)
        failure = FailureState(since=AT)
    else:
        round_ = MarketRound(market=market, quote=reading(price))
        failure = INITIAL_FAILURE
    return "\n".join(render(round_, state, failure, AT, RATIO, WARN_AFTER))


class UpsideTrigger(unittest.TestCase):
    """涨破：现价 ≥ 阈值即触发。"""

    def test_price_reaching_threshold_fires(self):
        alerts, state = evaluate_thresholds(
            DOMESTIC, reading("950.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1, "到达阈值（≥）应当触发")
        self.assertEqual(alerts[0].direction, UPSIDE)
        self.assertNotIn(UPSIDE, state.armed, "触发后该方向转入已触发")

    def test_price_above_threshold_fires(self):
        alerts, _ = evaluate_thresholds(
            DOMESTIC, reading("955.20"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1)

    def test_price_below_threshold_is_silent(self):
        alerts, state = evaluate_thresholds(
            DOMESTIC, reading("949.99"), INITIAL_STATE, RATIO
        )
        self.assertEqual(alerts, (), "差一点不触发")
        self.assertEqual(state, INITIAL_STATE)


class DownsideTrigger(unittest.TestCase):
    """跌破：现价 ≤ 阈值即触发。"""

    def test_price_reaching_threshold_fires(self):
        alerts, state = evaluate_thresholds(
            DOMESTIC, reading("900.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1, "到达阈值（≤）应当触发")
        self.assertEqual(alerts[0].direction, DOWNSIDE)
        self.assertNotIn(DOWNSIDE, state.armed, "触发后该方向转入已触发")

    def test_price_below_threshold_fires(self):
        alerts, _ = evaluate_thresholds(
            DOMESTIC, reading("895.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1)

    def test_price_above_threshold_is_silent(self):
        alerts, state = evaluate_thresholds(
            DOMESTIC, reading("900.01"), INITIAL_STATE, RATIO
        )
        self.assertEqual(alerts, (), "差一点不触发")
        self.assertEqual(state, INITIAL_STATE)


class HoverDoesNotRefire(unittest.TestCase):
    """触发后价格停留或贴着阈值抖动，不重复提醒（穿越触发）。"""

    def test_hovering_within_band_does_not_refire(self):
        state = fired_state("951.00")
        for price in ("950.00", "951.50", "949.50", "949.10"):  # 均未越过 949.05
            alerts, state = evaluate_thresholds(DOMESTIC, reading(price), state, RATIO)
            self.assertEqual(alerts, (), f"价格 {price} 不应重复提醒")
        self.assertNotIn(UPSIDE, state.armed, "未回落越带，应保持已触发")


class ReArm(unittest.TestCase):
    """回落越过重新武装带（950 × 0.1% = 0.95，线在 949.05）才重新武装。"""

    def test_pullback_just_inside_band_stays_fired(self):
        state = fired_state("951.00")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("949.06"), state, RATIO)
        self.assertEqual(alerts, (), "回到阈值另一侧但未越带，不提醒")
        self.assertNotIn(UPSIDE, state.armed)

    def test_pullback_to_rearm_line_rearms_without_alert(self):
        state = fired_state("951.00")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("949.05"), state, RATIO)
        self.assertEqual(alerts, (), "重新武装本身不是提醒")
        self.assertIn(UPSIDE, state.armed)

    def test_recross_after_rearm_fires_again(self):
        state = fired_state("951.00")
        _, state = evaluate_thresholds(DOMESTIC, reading("949.05"), state, RATIO)
        alerts, state = evaluate_thresholds(DOMESTIC, reading("952.00"), state, RATIO)
        self.assertEqual(len(alerts), 1, "重新武装后再次越线应当再提醒")
        self.assertNotIn(UPSIDE, state.armed)

    def test_trigger_cycle_repeats(self):
        state = INITIAL_STATE
        fired = 0
        for price in ("951.00", "948.00", "953.00", "947.00", "954.00"):
            alerts, state = evaluate_thresholds(DOMESTIC, reading(price), state, RATIO)
            fired += len(alerts)
        self.assertEqual(fired, 3, "三次越线、两次回落越带，应提醒三次")

    def test_downside_pullback_up_to_rearm_line_rearms(self):
        state = fired_state("899.00")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("900.89"), state, RATIO)
        self.assertEqual(alerts, ())
        self.assertNotIn(DOWNSIDE, state.armed, "未越过 900.90 不重新武装")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("900.90"), state, RATIO)
        self.assertEqual(alerts, ())
        self.assertIn(DOWNSIDE, state.armed)


class ConfigurableReArmRatio(unittest.TestCase):
    """重新武装带比例可配：1% 时重新武装线为 940.50。"""

    def test_larger_ratio_needs_bigger_pullback(self):
        ratio = Decimal("0.01")
        state = fired_state("951.00")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("941.00"), state, ratio)
        self.assertEqual(alerts, ())
        self.assertNotIn(UPSIDE, state.armed, "941.00 在带内，不重新武装")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("940.50"), state, ratio)
        self.assertEqual(alerts, ())
        self.assertIn(UPSIDE, state.armed)


class AlertPayload(unittest.TestCase):
    """提醒事件自带弹窗与日志所需的全部字段。"""

    def test_event_carries_display_fields(self):
        alerts, _ = evaluate_thresholds(
            DOMESTIC, reading("955.20"), INITIAL_STATE, RATIO
        )
        alert = alerts[0]
        self.assertEqual(alert.market, "国内金价")
        self.assertEqual(alert.direction, UPSIDE)
        self.assertEqual(alert.price, Decimal("955.20"))
        self.assertEqual(alert.threshold, Decimal("950.00"))
        self.assertEqual(alert.unit, "元/克")
        self.assertEqual(alert.data_time, AT)


class StartupAlreadyCrossed(unittest.TestCase):
    """启动即越线：第一次读数就提醒。"""

    def test_first_reading_above_threshold_fires(self):
        alerts, _ = evaluate_thresholds(
            DOMESTIC, reading("970.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1)

    def test_first_reading_below_threshold_fires(self):
        alerts, _ = evaluate_thresholds(
            DOMESTIC, reading("880.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].direction, DOWNSIDE)


class DisabledThreshold(unittest.TestCase):
    """留空（None）或填 0 的方向不启用、不提醒。"""

    def test_none_threshold_never_fires(self):
        market = dict(DOMESTIC, up_threshold=None)
        alerts, state = evaluate_thresholds(
            market, reading("1000.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(alerts, (), "未启用的方向越线也不提醒")
        self.assertEqual(state, INITIAL_STATE, "未启用的方向状态不变")

    def test_zero_threshold_never_fires(self):
        market = dict(DOMESTIC, down_threshold=Decimal("0"))
        alerts, state = evaluate_thresholds(
            market, reading("0.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(alerts, (), "填 0 与留空同义")
        self.assertEqual(state, INITIAL_STATE)

    def test_remaining_direction_still_works(self):
        market = dict(DOMESTIC, up_threshold=None)
        alerts, state = evaluate_thresholds(
            market, reading("890.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(len(alerts), 1, "关掉涨破不影响跌破")
        self.assertEqual(alerts[0].direction, DOWNSIDE)
        self.assertNotIn(DOWNSIDE, state.armed)


class DirectionsAreIndependent(unittest.TestCase):
    """涨破与跌破互不干扰。"""

    def test_firing_up_leaves_down_armed(self):
        state = fired_state("955.00")
        self.assertIn(DOWNSIDE, state.armed, "涨破触发不影响跌破方向")

    def test_waiting_in_the_middle_triggers_nothing(self):
        alerts, state = evaluate_thresholds(
            DOMESTIC, reading("920.00"), INITIAL_STATE, RATIO
        )
        self.assertEqual(alerts, ())
        self.assertEqual(state, INITIAL_STATE)

    def test_up_rearms_while_down_keeps_its_own_state(self):
        state = fired_state("955.00")
        alerts, state = evaluate_thresholds(DOMESTIC, reading("940.00"), state, RATIO)
        self.assertEqual(alerts, (), "回落越带只是重新武装，不是提醒")
        self.assertIn(UPSIDE, state.armed)
        self.assertIn(DOWNSIDE, state.armed)
        alerts, state = evaluate_thresholds(DOMESTIC, reading("890.00"), state, RATIO)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].direction, DOWNSIDE, "此时只有跌破越线")
        self.assertIn(UPSIDE, state.armed)


class Purity(unittest.TestCase):
    """纯函数：不改入参、同输入同输出。"""

    def test_input_state_is_not_mutated(self):
        state = INITIAL_STATE
        evaluate_thresholds(DOMESTIC, reading("955.00"), state, RATIO)
        self.assertEqual(state, INITIAL_STATE, "传入的状态对象不被就地修改")

    def test_same_inputs_give_same_outputs(self):
        first = evaluate_thresholds(DOMESTIC, reading("955.00"), INITIAL_STATE, RATIO)
        second = evaluate_thresholds(DOMESTIC, reading("955.00"), INITIAL_STATE, RATIO)
        self.assertEqual(first, second)


class ConsoleRendering(unittest.TestCase):
    """控制台段落：现价、数据时间、距阈值距离、市场状态。"""

    def test_armed_market_shows_distance_to_trigger(self):
        text = console_text("940.00", INITIAL_STATE)
        self.assertIn("距触发还差 10.00", text)  # 涨破 950 − 940
        self.assertIn("距触发还差 40.00", text)  # 940 − 跌破 900
        self.assertIn("状态：监视中", text)

    def test_fired_market_shows_rearm_line_and_status(self):
        state = fired_state("955.00")
        text = console_text("955.00", state)
        self.assertIn("涨破阈值 950.00 元/克：已触发", text)
        self.assertIn("回落至 949.05 以下重新武装", text)
        self.assertIn("（还需回落 5.95）", text)  # 955.00 − 949.05
        self.assertIn("状态：已触发待回落", text)

    def test_downside_fired_uses_rise_wording(self):
        state = fired_state("898.00")
        text = console_text("898.00", state)
        self.assertIn("回升至 900.90 以上重新武装", text)
        self.assertIn("（还需回升 2.90）", text)  # 900.90 − 898.00
        self.assertIn("距触发还差 52.00", text)  # 涨破方向仍显示距离

    def test_disabled_direction_shows_no_line(self):
        market = dict(DOMESTIC, up_threshold=None)
        text = console_text("940.00", INITIAL_STATE, market=market)
        self.assertNotIn("涨破", text)
        self.assertIn("跌破阈值", text)


if __name__ == "__main__":
    unittest.main()
