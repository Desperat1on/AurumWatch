# -*- coding: utf-8 -*-
"""主窗口视图模型（纯函数）：把「一轮取数结果 + 状态 + 记账」算成窗口要显示的一切。

窗口只负责摆放：每段文字与它的色调都在这里定，窗口不判断行情、不算距离。
文案语义沿用控制台版（现价、行情数据时间、距触发距离、重新武装线、市场状态）。
"""

from dataclasses import dataclass
from datetime import timedelta

from aurumwatch.alerts import UPSIDE, distance_to_line, enabled_directions, rearm_line
from aurumwatch.failures import duration_text
from aurumwatch.schedule import next_refresh_delay

# 市场状态文案（见 CONTEXT.md）
WATCHING = "监视中"
FIRED = "已触发待回落"
SOURCE_FAILURE = "数据源故障"

# 行的色调：窗口按它取颜色，不认识时按普通处理
TONE_NORMAL = "normal"
TONE_DIM = "dim"
TONE_PRICE = "price"
TONE_RISE = "rise"
TONE_FALL = "fall"
TONE_WARN = "warn"


@dataclass(frozen=True)
class Line:
    """窗口里的一行文字：内容 + 色调提示（窗口只按色调选颜色）。"""

    text: str
    tone: str = TONE_NORMAL


@dataclass(frozen=True)
class MarketView:
    """一个市场面板：标题（名称与说明）、正文行、市场状态。"""

    name: str
    detail: str
    lines: tuple[Line, ...]
    status: Line


@dataclass(frozen=True)
class WindowView:
    """主窗口一帧的全部内容：抬头、刷新时刻与下次刷新、各市场面板。"""

    headline: str
    refreshed: str
    next_refresh: str
    markets: tuple[MarketView, ...]


def market_status(market, state):
    """市场状态：任一启用方向已触发待回落，否则监视中。"""
    for direction, _ in enabled_directions(market):
        if direction.name not in state.armed:
            return FIRED
    return WATCHING


def threshold_line(direction, threshold, unit, price, fired, rearm_ratio):
    """阈值现状一行：潜伏时报距触发的距离，已触发时报重新武装线与回摆所需量。"""
    tone = TONE_RISE if direction.name == UPSIDE else TONE_FALL
    if not fired:
        return Line(
            f"{direction.name}阈值 {threshold:.2f} {unit}："
            f"距触发还差 {distance_to_line(price, direction, threshold):.2f}",
            tone,
        )
    line = rearm_line(direction, threshold, rearm_ratio)
    gap = abs(distance_to_line(price, direction, line))
    return Line(
        f"{direction.name}阈值 {threshold:.2f} {unit}：已触发；"
        f"{direction.return_word}至 {line:.2f} {direction.side_word}重新武装"
        f"（还需{direction.return_word} {gap:.2f}）",
        tone,
    )


def failure_lines(error, failure, at, warn_after):
    """取数失败市场的行：故障原因与连续失败时长。"""
    note = "已弹出警告" if failure.warned else f"满 {duration_text(warn_after)}将弹出警告"
    return (
        Line(f"!! 数据源故障：{error}", TONE_WARN),
        Line(f"已连续失败 {duration_text(at - failure.since)}（{note}）", TONE_WARN),
    )


def market_view(round_, state, failure, at, *, rearm_ratio, warn_after):
    """单个市场面板（纯函数）。

    取数失败的轮次没有读数：不显示现价与距阈值距离（不用陈旧读数冒充行情），
    状态记为「数据源故障」。failure 须为该轮记账后的失败状态（失败时起点必已置位）。
    """
    market = round_.market
    if round_.failed:
        return MarketView(
            name=market["name"],
            detail=market["detail"],
            lines=failure_lines(round_.error, failure, at, warn_after),
            status=Line(SOURCE_FAILURE, TONE_WARN),
        )
    quote = round_.quote
    lines = [
        Line(f"现价：{quote.price:.2f} {market['unit']}", TONE_PRICE),
        Line(f"行情数据时间：{quote.time:%Y-%m-%d %H:%M:%S}", TONE_DIM),
    ]
    for direction, threshold in enabled_directions(market):
        lines.append(
            threshold_line(
                direction,
                threshold,
                market["unit"],
                quote.price,
                direction.name not in state.armed,
                rearm_ratio,
            )
        )
    status = market_status(market, state)
    return MarketView(
        name=market["name"],
        detail=market["detail"],
        lines=tuple(lines),
        status=Line(status, TONE_WARN if status == FIRED else TONE_DIM),
    )


def window_view(rounds, states, failures, at, *, interval, rearm_ratio, warn_after):
    """主窗口一帧：抬头、刷新时刻、每个市场一段、下次刷新（纯函数）。

    states、failures 均按市场代码索引，由调用方在判定与记账之后传入。
    """
    delay = next_refresh_delay(at, interval)
    next_fire = at.replace(microsecond=0) + timedelta(seconds=delay)
    return WindowView(
        headline=f"金价监视中——每 {interval} 秒刷新",
        refreshed=f"本次刷新：{at:%Y-%m-%d %H:%M:%S}",
        next_refresh=f"下次刷新：{next_fire:%H:%M:%S}（约 {delay} 秒后）",
        markets=tuple(
            market_view(
                round_,
                states[round_.market["code"]],
                failures[round_.market["code"]],
                at,
                rearm_ratio=rearm_ratio,
                warn_after=warn_after,
            )
            for round_ in rounds
        ),
    )
