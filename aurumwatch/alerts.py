# -*- coding: utf-8 -*-
"""触发判定核心（纯函数）：不碰网络、界面与写屏，只做「读数 + 配置 + 状态 → 提醒 + 新状态」。"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

# 方向词汇（见 CONTEXT.md）：涨破 = 现价 ≥ 阈值；跌破 = 现价 ≤ 阈值。
UPSIDE = "涨破"
DOWNSIDE = "跌破"


@dataclass(frozen=True)
class Direction:
    """一个提醒方向：名称、配置键，与回到阈值另一侧时的文案。"""

    name: str
    config_key: str
    return_word: str  # 涨破等「回落」，跌破等「回升」
    side_word: str  # 重新武装线的方位：以下 / 以上


DIRECTIONS = (
    Direction(UPSIDE, "up_threshold", "回落", "以下"),
    Direction(DOWNSIDE, "down_threshold", "回升", "以上"),
)


@dataclass(frozen=True)
class Alert:
    """一次触发的提醒事件：弹窗与日志所需的全部信息。"""

    market: str
    direction: str
    price: Decimal
    threshold: Decimal
    unit: str
    data_time: datetime


@dataclass(frozen=True)
class TriggerState:
    """一个市场的触发状态：armed 内的方向潜伏待发，其余已触发待回落。"""

    armed: frozenset


# 全新市场的初始状态：两个方向均潜伏待发
INITIAL_STATE = TriggerState(armed=frozenset({UPSIDE, DOWNSIDE}))


def enabled_directions(market):
    """该市场启用的方向及其阈值；留空（None）或 0 的方向不参与。"""
    for direction in DIRECTIONS:
        threshold = market[direction.config_key]
        if threshold:
            yield direction, threshold


def distance_to_line(price, direction, price_line):
    """现价相对一条价格线的距离：未越线为正，越线为负。

    price_line 可为方向阈值或重新武装线；涨破的线在现价上方、跌破的在下方。
    """
    return price_line - price if direction.name == UPSIDE else price - price_line


def rearm_line(direction, threshold, rearm_ratio):
    """重新武装线：触发后价格须回到并越过此线，该方向才重回潜伏。"""
    band = threshold * rearm_ratio
    return threshold - band if direction.name == UPSIDE else threshold + band


def evaluate_thresholds(market, quote, state, rearm_ratio):
    """穿越触发判定（纯函数）：一次读数 + 配置 + 当前状态 → 提醒事件 + 新状态。

    涨破 = 现价 ≥ 阈值，跌破 = 现价 ≤ 阈值（到达即算）。触发后该方向转入
    已触发，不再重复提醒，直到价格回到阈值另一侧并越过重新武装线
    （阈值 ∓ 阈值 × rearm_ratio）才重回潜伏。留空（None）或 0 的阈值不参与判定。
    """
    alerts = []
    armed = set(state.armed)
    for direction, threshold in enabled_directions(market):
        if direction.name in armed:
            if distance_to_line(quote.price, direction, threshold) <= 0:
                armed.discard(direction.name)
                alerts.append(
                    Alert(
                        market=market["name"],
                        direction=direction.name,
                        price=quote.price,
                        threshold=threshold,
                        unit=market["unit"],
                        data_time=quote.time,
                    )
                )
        elif distance_to_line(
            quote.price, direction, rearm_line(direction, threshold, rearm_ratio)
        ) >= 0:
            armed.add(direction.name)
    return tuple(alerts), TriggerState(armed=frozenset(armed))


def evaluate_markets(rounds, states, rearm_ratio):
    """一轮刷新：对每个取到读数的市场独立判定（纯函数）。

    取数失败的市场（round 只有故障、没有读数）保持原状态、不产生提醒——
    故障不会被当成行情。新状态表按市场分别写入，市场之间互不覆盖、互不阻塞。
    """
    alerts = []
    next_states = dict(states)
    for round_ in rounds:
        if round_.failed:
            continue
        code = round_.market["code"]
        new_alerts, next_states[code] = evaluate_thresholds(
            round_.market, round_.quote, states[code], rearm_ratio
        )
        alerts.extend(new_alerts)
    return tuple(alerts), next_states
