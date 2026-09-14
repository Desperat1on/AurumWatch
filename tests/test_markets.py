# -*- coding: utf-8 -*-
"""国内、国际两个市场同挂一套提醒：各自独立判定（纯函数，不碰网络与 UI）。

两个市场各自显示的断言（现价、单位、状态、重新武装线）见 `test_viewmodel`。
"""

import unittest
from datetime import datetime
from decimal import Decimal

from aurumwatch.alerts import DOWNSIDE, INITIAL_STATE, UPSIDE, evaluate_markets
from aurumwatch.failures import INITIAL_FAILURE
from aurumwatch.quotes import MarketRound, Quote

AT = datetime(2026, 9, 12, 12, 0, 0)
RATIO = Decimal("0.001")

# 配置与领域术语同形：两个市场各两个阈值；国际按美元/盎司，与国内不同量纲、数值也不同
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


def rounds(prices, markets=BOTH_MARKETS, failing=()):
    """一轮取数结果：市场名 → 价格，数据时间固定；failing 里的市场本轮取数失败。"""
    return [
        MarketRound(market=market, error="ConnectionError: 连接失败")
        if market["name"] in failing
        else MarketRound(
            market=market,
            quote=Quote(price=Decimal(prices[market["name"]]), time=AT),
        )
        for market in markets
    ]


class MarketsFireOnTheirOwnLines(unittest.TestCase):
    """同一轮里两个市场各自越线：各弹各的，互不阻塞。"""

    def test_both_markets_fire_in_the_same_cycle(self):
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "955.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(
            [(alert.market, alert.direction, alert.unit) for alert in alerts],
            [("国内金价", UPSIDE, "元/克"), ("国际金价", UPSIDE, "美元/盎司")],
            "两个市场同一轮越线，各自提醒，各自带自己的单位",
        )


class SingleMarketEnabled(unittest.TestCase):
    """只启用一个市场（另一个留空或填 0）时，行为与该市场单独启用时一致。"""

    def test_market_without_thresholds_never_fires(self):
        quiet = dict(INTERNATIONAL, up_threshold=None, down_threshold=None)
        alerts, states = evaluate_markets(
            rounds({"国内金价": "955.00", "国际金价": "4500.00"}, (DOMESTIC, quiet)),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual([a.market for a in alerts], ["国内金价"], "未设阈值的市场再极端也不提醒")
        self.assertEqual(states["hf_XAU"], INITIAL_STATE)

    def test_zero_thresholds_mean_disabled_too(self):
        quiet = dict(
            INTERNATIONAL, up_threshold=Decimal("0"), down_threshold=Decimal("0")
        )
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "940.00", "国际金价": "4500.00"}, (DOMESTIC, quiet)),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(alerts, (), "填 0 与留空同义")

    def test_only_international_enabled_domestic_stays_quiet(self):
        quiet = dict(DOMESTIC, up_threshold=None, down_threshold=None)
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "1000.00", "国际金价": "4410.00"}, (quiet, INTERNATIONAL)),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(
            [(a.market, a.direction) for a in alerts],
            [("国际金价", UPSIDE)],
            "只启用国际时，与国内单独启用时同样各判各的",
        )


class StartupSilenceSwitch(unittest.TestCase):
    """「启动时若已越线立即提醒」关掉时：首轮已越线的方向只记账、不出声。

    静默不是「当作没越线」——状态照记已触发，等价格回落越过重新武装带、再次越线
    才提醒，否则下一轮又会立刻提醒一次，开关等于没关。
    """

    def test_silenced_market_marks_the_direction_fired_without_alerting(self):
        alerts, states = evaluate_markets(
            rounds({"国内金价": "970.00", "国际金价": "4350.00"}),
            INITIAL_STATES,
            RATIO,
            silent={"gds_AU9999"},
        )
        self.assertEqual(alerts, (), "首轮已越线，但这一轮不出声")
        self.assertNotIn(UPSIDE, states["gds_AU9999"].armed, "已经越线：算作触发过了")
        self.assertEqual(states["hf_XAU"], INITIAL_STATE, "没越线的市场照旧潜伏")

    def test_silenced_market_alerts_again_after_pullback_and_recross(self):
        _, states = evaluate_markets(
            rounds({"国内金价": "970.00", "国际金价": "4350.00"}),
            INITIAL_STATES,
            RATIO,
            silent={"gds_AU9999"},
        )
        _, states = evaluate_markets(
            rounds({"国内金价": "940.00", "国际金价": "4350.00"}), states, RATIO
        )  # 回落越过重新武装线：重新武装，本身不提醒
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "960.00", "国际金价": "4350.00"}), states, RATIO
        )
        self.assertEqual(
            [(alert.market, alert.direction) for alert in alerts], [("国内金价", UPSIDE)]
        )

    def test_silence_does_not_leak_to_the_other_market(self):
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "970.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
            silent={"gds_AU9999"},
        )
        self.assertEqual(
            [(alert.market, alert.direction) for alert in alerts], [("国际金价", UPSIDE)]
        )

    def test_no_silence_means_the_first_reading_alerts(self):
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "970.00", "国际金价": "4350.00"}), INITIAL_STATES, RATIO
        )
        self.assertEqual([alert.market for alert in alerts], ["国内金价"], "默认立即提醒")


class StatesAreNotShared(unittest.TestCase):
    """一个市场的触发与重新武装，不动另一个市场的状态。"""

    def test_one_market_crossing_leaves_the_other_armed(self):
        alerts, states = evaluate_markets(
            rounds({"国内金价": "955.00", "国际金价": "4350.00"}),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual([alert.market for alert in alerts], ["国内金价"])
        self.assertNotIn(UPSIDE, states["gds_AU9999"].armed, "国内越线，转入已触发")
        self.assertIn(UPSIDE, states["hf_XAU"].armed, "国际未越线，仍潜伏待发")

    def test_each_market_rearms_on_its_own_line(self):
        _, states = evaluate_markets(
            rounds({"国内金价": "955.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        # 国内回落到 948.00（已越过重新武装线 949.05），国际停在 4405.00（未到 4395.60）
        alerts, states = evaluate_markets(
            rounds({"国内金价": "948.00", "国际金价": "4405.00"}),
            states,
            RATIO,
        )
        self.assertEqual(alerts, (), "回落越带只是重新武装，不是提醒")
        self.assertIn(UPSIDE, states["gds_AU9999"].armed)
        self.assertNotIn(UPSIDE, states["hf_XAU"].armed, "国际未回落越带，保持已触发")
        # 国际回落到 4395.00（已越过 4395.60）后再次越线：只有它提醒
        _, states = evaluate_markets(
            rounds({"国内金价": "948.00", "国际金价": "4395.00"}),
            states,
            RATIO,
        )
        self.assertIn(UPSIDE, states["hf_XAU"].armed)
        alerts, _ = evaluate_markets(
            rounds({"国内金价": "948.00", "国际金价": "4402.00"}),
            states,
            RATIO,
        )
        self.assertEqual([(a.market, a.direction) for a in alerts], [("国际金价", UPSIDE)])

    def test_missing_quote_keeps_that_market_state(self):
        _, states = evaluate_markets(
            rounds({"国内金价": "955.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        fired = dict(states)
        alerts, states = evaluate_markets(
            rounds({"国内金价": "890.00"}, failing=("国际金价",)), fired, RATIO
        )
        self.assertEqual(
            [(a.market, a.direction) for a in alerts],
            [("国内金价", DOWNSIDE)],
            "缺失读数的市场不参与判定，也不误报",
        )
        self.assertEqual(states["hf_XAU"], fired["hf_XAU"], "国际状态不被这一轮改写")

    def test_input_states_are_not_mutated(self):
        states = dict(INITIAL_STATES)
        evaluate_markets(
            rounds({"国内金价": "955.00", "国际金价": "4410.00"}),
            states,
            RATIO,
        )
        self.assertEqual(states, INITIAL_STATES, "传入的状态表不被就地修改")


if __name__ == "__main__":
    unittest.main()
