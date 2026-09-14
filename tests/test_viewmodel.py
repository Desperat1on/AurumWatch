# -*- coding: utf-8 -*-
"""主窗口视图模型单元测试（纯函数，不碰网络与 UI）。

主窗口上要显示的每个数字与每句文案都由视图模型算出，因此断言只认文字：喂入
一轮取数结果、状态与故障记账，断言现价、行情数据时间、距触发距离、重新武装线
与市场状态。取数失败的轮次不得出现任何陈旧读数（现价、数据时间、阈值距离）。
"""

import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from aurumwatch.alerts import INITIAL_STATE, UPSIDE, TriggerState, evaluate_markets
from aurumwatch.failures import INITIAL_FAILURE, FailureState
from aurumwatch.quotes import MarketRound, Quote
from aurumwatch.viewmodel import market_view, window_view

AT = datetime(2026, 9, 12, 12, 0, 0)
RATIO = Decimal("0.001")
WARN_AFTER = timedelta(minutes=10)
INTERVAL = 60

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
BOTH = (DOMESTIC, INTERNATIONAL)
INITIAL_STATES = {market["code"]: INITIAL_STATE for market in BOTH}
INITIAL_FAILURES = {market["code"]: INITIAL_FAILURE for market in BOTH}


def round_of(market, price, data_time=AT, error="ConnectionError: 连接失败"):
    """一个市场一轮的取数结果：给价格即取数成功，price=None 即本轮失败。"""
    if price is None:
        return MarketRound(market=market, error=error)
    return MarketRound(market=market, quote=Quote(price=Decimal(price), time=data_time))


def panel(
    price,
    market=DOMESTIC,
    state=INITIAL_STATE,
    failure=INITIAL_FAILURE,
    at=AT,
    data_time=AT,
):
    """单个市场的面板视图。"""
    return market_view(
        round_of(market, price, data_time),
        state,
        failure,
        at,
        rearm_ratio=RATIO,
        warn_after=WARN_AFTER,
    )


def panel_text(price, **kwargs):
    """把单个市场面板的正文拼成文本，便于断言。"""
    return "\n".join(line.text for line in panel(price, **kwargs).lines)


class ShowsPriceAndDataTime(unittest.TestCase):
    """现价与行情数据时间：按市场各自的单位显示，数据时间取读数自带的时刻。"""

    def test_domestic_price_is_in_yuan_per_gram(self):
        self.assertEqual(panel("936.30").lines[0].text, "现价：936.30 元/克")

    def test_international_price_is_in_usd_per_ounce(self):
        self.assertEqual(
            panel("4348.35", INTERNATIONAL).lines[0].text, "现价：4348.35 美元/盎司"
        )

    def test_data_time_is_the_quote_time_not_the_refresh_time(self):
        text = panel_text("936.30", at=datetime(2026, 9, 12, 12, 3, 0))
        self.assertIn(
            "行情数据时间：2026-09-12 12:00:00", text, "显示的是读数自带的行情时刻"
        )


class ShowsDistanceToEachEnabledThreshold(unittest.TestCase):
    """每个启用方向一行：报距触发的距离；未启用（留空）的方向没有行。"""

    def test_both_directions_report_their_distance(self):
        self.assertEqual(
            panel_text("936.30").splitlines()[2:],
            [
                "涨破阈值 950.00 元/克：距触发还差 13.70",
                "跌破阈值 900.00 元/克：距触发还差 36.30",
            ],
        )

    def test_disabled_direction_has_no_line(self):
        text = panel_text("936.30", market=dict(DOMESTIC, up_threshold=None))
        self.assertIn("跌破阈值 900.00 元/克：距触发还差 36.30", text)
        self.assertNotIn("涨破", text, "留空的方向不显示")

    def test_market_without_any_threshold_keeps_its_price(self):
        quiet = dict(INTERNATIONAL, up_threshold=None, down_threshold=None)
        text = panel_text("4350.00", market=quiet)
        self.assertIn("现价：4350.00 美元/盎司", text, "未设阈值的市场仍显示行情")
        self.assertNotIn("阈值", text)
        self.assertEqual(panel("4350.00", market=quiet).status.text, "监视中")


class FiredDirectionShowsRearmDistance(unittest.TestCase):
    """已触发待回落的方向：显示重新武装线与回摆所需量（沿用控制台版文案）。"""

    def test_fired_upside_shows_rearm_line_and_gap(self):
        _, states = evaluate_markets(
            [round_of(DOMESTIC, "956.00"), round_of(INTERNATIONAL, "4355.00")],
            INITIAL_STATES,
            RATIO,
        )
        text = panel_text("956.00", state=states["gds_AU9999"])
        self.assertIn(
            "涨破阈值 950.00 元/克：已触发；回落至 949.05 以下重新武装（还需回落 6.95）",
            text,
        )

    def test_fired_downside_uses_rise_wording(self):
        state = TriggerState(armed=frozenset({UPSIDE}))  # 跌破已触发，涨破仍潜伏
        self.assertEqual(
            panel_text("898.00", state=state).splitlines()[2:],
            [
                "涨破阈值 950.00 元/克：距触发还差 52.00",
                "跌破阈值 900.00 元/克：已触发；回升至 900.90 以上重新武装（还需回升 2.90）",
            ],
        )

    def test_fired_direction_reports_market_status(self):
        state = TriggerState(armed=frozenset({UPSIDE}))
        self.assertEqual(panel("956.00", state=state).status.text, "已触发待回落")

    def test_armed_market_status_is_watching(self):
        self.assertEqual(panel("940.00").status.text, "监视中")


class FailedRoundHidesTheStaleReading(unittest.TestCase):
    """取数失败的轮次：显示故障原因与连续失败时长，不拿陈旧读数冒充行情。"""

    def test_failure_lines_carry_error_and_elapsed(self):
        failure = FailureState(since=AT - timedelta(minutes=3))
        text = panel_text(None, failure=failure)
        self.assertIn("!! 数据源故障：ConnectionError: 连接失败", text)
        self.assertIn("已连续失败 3 分钟（满 10 分钟将弹出警告）", text)

    def test_warn_hint_follows_the_configured_duration(self):
        view = market_view(
            round_of(DOMESTIC, None),
            INITIAL_STATE,
            FailureState(since=AT),
            AT,
            rearm_ratio=RATIO,
            warn_after=timedelta(minutes=5),
        )
        self.assertIn(
            "满 5 分钟将弹出警告", "\n".join(line.text for line in view.lines)
        )

    def test_warned_failure_says_so(self):
        failure = FailureState(since=AT - timedelta(minutes=12), warned=True)
        self.assertIn(
            "已连续失败 12 分钟（已弹出警告）", panel_text(None, failure=failure)
        )

    def test_no_stale_price_or_threshold_lines(self):
        text = panel_text(None, failure=FailureState(since=AT - timedelta(minutes=3)))
        self.assertNotIn("现价", text, "故障轮没有读数，不显示现价")
        self.assertNotIn("行情数据时间", text)
        self.assertNotIn("阈值", text, "故障轮不判阈值，也不显示距触发的距离")

    def test_status_is_source_failure(self):
        view = panel(None, failure=FailureState(since=AT - timedelta(minutes=3)))
        self.assertEqual(view.status.text, "数据源故障")


class WindowFrame(unittest.TestCase):
    """整帧：抬头、两个市场各一段、下次刷新提示，逐行咬死。"""

    def test_frame_lists_both_markets_in_configured_order(self):
        prices = {"国内金价": "956.00", "国际金价": "4355.00"}
        rounds = [round_of(market, prices[market["name"]]) for market in BOTH]
        _, states = evaluate_markets(rounds, INITIAL_STATES, RATIO)
        view = window_view(
            rounds,
            states,
            INITIAL_FAILURES,
            AT,
            interval=INTERVAL,
            rearm_ratio=RATIO,
            warn_after=WARN_AFTER,
        )
        self.assertEqual(view.headline, "监视中——每 60 秒刷新")
        self.assertEqual(view.refreshed, "本次刷新：2026-09-12 12:00:00")
        self.assertEqual(view.next_refresh, "下次刷新：12:01:00（约 60 秒后）")
        self.assertEqual(
            [market.name for market in view.markets], ["国内金价", "国际金价"]
        )
        self.assertEqual(
            [line.text for line in view.markets[0].lines],
            [
                "现价：956.00 元/克",
                "行情数据时间：2026-09-12 12:00:00",
                "涨破阈值 950.00 元/克：已触发；"
                "回落至 949.05 以下重新武装（还需回落 6.95）",
                "跌破阈值 900.00 元/克：距触发还差 56.00",
            ],
        )
        self.assertEqual(
            [line.text for line in view.markets[1].lines],
            [
                "现价：4355.00 美元/盎司",
                "行情数据时间：2026-09-12 12:00:00",
                "涨破阈值 4400.00 美元/盎司：距触发还差 45.00",
                "跌破阈值 4300.00 美元/盎司：距触发还差 55.00",
            ],
        )
        self.assertEqual(
            [market.status.text for market in view.markets], ["已触发待回落", "监视中"]
        )

    def test_next_refresh_aligns_to_the_whole_minute(self):
        rounds = [round_of(market, "940.00") for market in BOTH]
        view = window_view(
            rounds,
            INITIAL_STATES,
            INITIAL_FAILURES,
            datetime(2026, 9, 12, 12, 34, 25),
            interval=INTERVAL,
            rearm_ratio=RATIO,
            warn_after=WARN_AFTER,
        )
        self.assertEqual(view.next_refresh, "下次刷新：12:35:00（约 35 秒后）")

    def test_one_market_failing_leaves_the_other_showing_its_quote(self):
        rounds = [
            round_of(DOMESTIC, "936.30"),
            round_of(INTERNATIONAL, None),
        ]
        failures = {
            "gds_AU9999": INITIAL_FAILURE,
            "hf_XAU": FailureState(since=AT - timedelta(minutes=2)),
        }
        view = window_view(
            rounds,
            INITIAL_STATES,
            failures,
            AT,
            interval=INTERVAL,
            rearm_ratio=RATIO,
            warn_after=WARN_AFTER,
        )
        self.assertEqual(view.markets[0].lines[0].text, "现价：936.30 元/克")
        self.assertEqual(view.markets[0].status.text, "监视中")
        self.assertEqual(view.markets[1].status.text, "数据源故障")
        self.assertIn(
            "已连续失败 2 分钟（满 10 分钟将弹出警告）",
            "\n".join(line.text for line in view.markets[1].lines),
        )


if __name__ == "__main__":
    unittest.main()
