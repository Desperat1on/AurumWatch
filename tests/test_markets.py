# -*- coding: utf-8 -*-
"""国内、国际两个市场同挂一套提醒：各自独立判定、各自显示（纯函数，不碰网络与 UI）。"""

import unittest
from datetime import datetime
from decimal import Decimal

from watch_gold import (
    DOWNSIDE,
    INITIAL_STATE,
    UPSIDE,
    Quote,
    evaluate_markets,
    render,
    render_frame,
)

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


def quotes(prices):
    """一轮读数：市场名 → 价格，数据时间固定。"""
    codes = {market["name"]: market["code"] for market in BOTH_MARKETS}
    return {
        codes[name]: Quote(price=Decimal(price), time=AT)
        for name, price in prices.items()
    }


def console_text(price, market, state=INITIAL_STATE, error=None):
    """把单个市场的控制台段落拼成文本，便于断言。"""
    quote = Quote(price=Decimal(price), time=AT) if price is not None else None
    return "\n".join(render(market, quote, error, state, RATIO))


class MarketsFireOnTheirOwnLines(unittest.TestCase):
    """同一轮里两个市场各自越线：各弹各的，互不阻塞。"""

    def test_both_markets_fire_in_the_same_cycle(self):
        alerts, _ = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "955.00", "国际金价": "4410.00"}),
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
            (DOMESTIC, quiet),
            quotes({"国内金价": "955.00", "国际金价": "4500.00"}),
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
            (DOMESTIC, quiet),
            quotes({"国内金价": "940.00", "国际金价": "4500.00"}),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(alerts, (), "填 0 与留空同义")

    def test_only_international_enabled_domestic_stays_quiet(self):
        quiet = dict(DOMESTIC, up_threshold=None, down_threshold=None)
        alerts, _ = evaluate_markets(
            (quiet, INTERNATIONAL),
            quotes({"国内金价": "1000.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual(
            [(a.market, a.direction) for a in alerts],
            [("国际金价", UPSIDE)],
            "只启用国际时，与国内单独启用时同样各判各的",
        )


class ConsoleShowsEachMarket(unittest.TestCase):
    """控制台两段：各显示各自的市场、单位、距阈值距离与状态。"""

    def test_frame_lists_both_sections_in_market_order(self):
        """整帧逐行比对：两段的归属、顺序、段间空行、各自的单位与状态都咬死。"""
        prices = {"国内金价": "956.00", "国际金价": "4355.00"}
        _, states = evaluate_markets(BOTH_MARKETS, quotes(prices), INITIAL_STATES, RATIO)
        self.assertEqual(
            render_frame(BOTH_MARKETS, quotes(prices), {}, states, RATIO),
            [
                "【国内金价】沪金99（上海黄金交易所 Au99.99）",
                "  现价：956.00 元/克",
                "  行情数据时间：2026-09-12 12:00:00",
                "  涨破阈值 950.00 元/克：已触发；"
                "回落至 949.05 以下重新武装（还需回落 6.95）",
                "  跌破阈值 900.00 元/克：距触发还差 56.00",
                "  状态：已触发待回落",
                "",
                "【国际金价】伦敦金（XAU/USD 现货黄金）",
                "  现价：4355.00 美元/盎司",
                "  行情数据时间：2026-09-12 12:00:00",
                "  涨破阈值 4400.00 美元/盎司：距触发还差 45.00",
                "  跌破阈值 4300.00 美元/盎司：距触发还差 55.00",
                "  状态：监视中",
                "",
            ],
        )

    def test_international_section_is_in_usd_per_ounce(self):
        text = console_text("4348.35", INTERNATIONAL)
        self.assertIn("【国际金价】伦敦金（XAU/USD 现货黄金）", text)
        self.assertIn("现价：4348.35 美元/盎司", text)
        self.assertIn("距触发还差 51.65", text)  # 4400.00 − 4348.35
        self.assertIn("距触发还差 48.35", text)  # 4348.35 − 4300.00

    def test_international_fired_shows_rearm_line(self):
        _, states = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "940.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        text = console_text("4410.00", INTERNATIONAL, states["hf_XAU"])
        self.assertIn("涨破阈值 4400.00 美元/盎司：已触发", text)
        self.assertIn("回落至 4395.60 以下重新武装", text)
        self.assertIn("（还需回落 14.40）", text)  # 4410.00 − 4395.60
        self.assertIn("状态：已触发待回落", text)

    def test_disabled_market_keeps_its_price_without_threshold_lines(self):
        quiet = dict(INTERNATIONAL, up_threshold=None, down_threshold=None)
        text = console_text("4350.00", quiet)
        self.assertIn("现价：4350.00 美元/盎司", text, "未启用的市场仍显示行情")
        self.assertNotIn("阈值", text)
        self.assertIn("状态：监视中", text)


class StatesAreNotShared(unittest.TestCase):
    """一个市场的触发与重新武装，不动另一个市场的状态。"""

    def test_one_market_crossing_leaves_the_other_armed(self):
        alerts, states = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "955.00", "国际金价": "4350.00"}),
            INITIAL_STATES,
            RATIO,
        )
        self.assertEqual([alert.market for alert in alerts], ["国内金价"])
        self.assertNotIn(UPSIDE, states["gds_AU9999"].armed, "国内越线，转入已触发")
        self.assertIn(UPSIDE, states["hf_XAU"].armed, "国际未越线，仍潜伏待发")

    def test_each_market_rearms_on_its_own_line(self):
        _, states = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "955.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        # 国内回落到 948.00（已越过重新武装线 949.05），国际停在 4405.00（未到 4395.60）
        alerts, states = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "948.00", "国际金价": "4405.00"}),
            states,
            RATIO,
        )
        self.assertEqual(alerts, (), "回落越带只是重新武装，不是提醒")
        self.assertIn(UPSIDE, states["gds_AU9999"].armed)
        self.assertNotIn(UPSIDE, states["hf_XAU"].armed, "国际未回落越带，保持已触发")
        # 国际回落到 4395.00（已越过 4395.60）后再次越线：只有它提醒
        _, states = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "948.00", "国际金价": "4395.00"}),
            states,
            RATIO,
        )
        self.assertIn(UPSIDE, states["hf_XAU"].armed)
        alerts, _ = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "948.00", "国际金价": "4402.00"}),
            states,
            RATIO,
        )
        self.assertEqual([(a.market, a.direction) for a in alerts], [("国际金价", UPSIDE)])

    def test_missing_quote_keeps_that_market_state(self):
        _, states = evaluate_markets(
            BOTH_MARKETS,
            quotes({"国内金价": "955.00", "国际金价": "4410.00"}),
            INITIAL_STATES,
            RATIO,
        )
        fired = dict(states)
        alerts, states = evaluate_markets(
            BOTH_MARKETS, quotes({"国内金价": "890.00"}), fired, RATIO
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
            BOTH_MARKETS,
            quotes({"国内金价": "955.00", "国际金价": "4410.00"}),
            states,
            RATIO,
        )
        self.assertEqual(states, INITIAL_STATES, "传入的状态表不被就地修改")


if __name__ == "__main__":
    unittest.main()
