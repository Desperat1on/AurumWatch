# -*- coding: utf-8 -*-
"""控制台渲染与写屏辅助。

渲染函数都是纯函数：给定取数结果、状态与配置，拼出要上屏的行。
写屏辅助（折行、终端宽度）只为「自己折行并数行、原地刷新」服务——
终端折行后的物理行数推不出来，上移量会因此错位。
"""

import os
import unicodedata

from aurumwatch.alerts import distance_to_line, enabled_directions, rearm_line
from aurumwatch.failures import duration_text

NEWLINE = "\r\n"


def market_status(market, state):
    """市场状态文案：任一启用方向已触发待回落，否则监视中。"""
    for direction, _ in enabled_directions(market):
        if direction.name not in state.armed:
            return "已触发待回落"
    return "监视中"


def threshold_line(direction, threshold, unit, price, fired, rearm_ratio):
    """阈值现状一行：潜伏时报距触发的距离，已触发时报重新武装线与回摆所需量。"""
    if not fired:
        return (
            f"  {direction.name}阈值 {threshold:.2f} {unit}："
            f"距触发还差 {distance_to_line(price, direction, threshold):.2f}"
        )
    line = rearm_line(direction, threshold, rearm_ratio)
    gap = abs(distance_to_line(price, direction, line))
    return (
        f"  {direction.name}阈值 {threshold:.2f} {unit}：已触发；"
        f"{direction.return_word}至 {line:.2f} {direction.side_word}重新武装"
        f"（还需{direction.return_word} {gap:.2f}）"
    )


def failure_lines(error, failure, at, warn_after):
    """取数失败市场的控制台行：醒目的错误行与连续失败时长行。"""
    note = "已弹出警告" if failure.warned else f"满 {duration_text(warn_after)}将弹出警告"
    return [
        f"  !! 数据源故障：{error}",
        f"  已连续失败 {duration_text(at - failure.since)}（{note}）",
    ]


def render(round_, state, failure, at, rearm_ratio, warn_after):
    """渲染单个市场的显示段落（纯函数）。

    取数失败的轮次没有读数：不显示现价与距阈值距离（不用陈旧读数冒充行情），
    状态记为「数据源故障」。failure 须为该轮记账后的失败状态（失败时起点必已置位）。
    """
    market = round_.market
    lines = [f"【{market['name']}】{market['detail']}"]
    if round_.failed:
        lines.extend(failure_lines(round_.error, failure, at, warn_after))
        lines.append("  状态：数据源故障")
        return lines
    quote = round_.quote
    lines.append(f"  现价：{quote.price:.2f} {market['unit']}")
    lines.append(f"  行情数据时间：{quote.time:%Y-%m-%d %H:%M:%S}")
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
    lines.append(f"  状态：{market_status(market, state)}")
    return lines


def render_frame(rounds, states, failures, at, rearm_ratio, warn_after):
    """渲染整帧控制台内容：每个市场一段，段间空行分隔（纯函数）。

    states、failures 均按市场代码索引，由调用方在判定与记账之后传入。
    """
    lines = []
    for round_ in rounds:
        code = round_.market["code"]
        lines.extend(
            render(round_, states[code], failures[code], at, rearm_ratio, warn_after)
        )
        lines.append("")
    return lines


def alert_log_line(alert, at):
    """触发日志行：带触发时刻的时间戳，留在控制台滚动区。"""
    return (
        f"[{at:%Y-%m-%d %H:%M:%S}] 触发：{alert.market} {alert.direction} "
        f"{alert.threshold:.2f} {alert.unit}（现价 {alert.price:.2f}，"
        f"数据时间 {alert.data_time:%Y-%m-%d %H:%M:%S}）"
    )


def warning_log_line(warning, at):
    """故障警告日志行：说明是数据源故障而非行情，留在控制台滚动区。"""
    return (
        f"[{at:%Y-%m-%d %H:%M:%S}] 数据源故障警告：{warning.market}"
        f"已连续取数失败 {duration_text(warning.elapsed)}"
        f"（自 {warning.since:%H:%M:%S} 起；最近错误 {warning.error}）"
    )


# ---- 控制台写屏辅助：自己折行并数行，原地刷新的上移量才与屏幕一致 ----
def _char_cells(ch):
    """单个字符在控制台占用的列数：东亚宽字符与歧义字符按 2 列计。

    歧义字符（如「—」）按 2 列是保守估计：多算只会让折行稍早一点；
    少算才会让终端自行折行，行数失准、原地刷新错位。
    """
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1


def display_cells(text):
    """文本在控制台占用的列数（东亚宽字符按 2 列计）。"""
    return sum(_char_cells(ch) for ch in text)


def wrap_line(text, width):
    """把一行折成不超过 width 列的多行；宽字符不拆开，空行占 1 行。

    自己折行而不是交给终端：终端折行后的物理行数无法从逻辑行数推得，
    原地刷新的上移量会因此错位（长报错行折行时实测残留旧帧碎片）。
    """
    rows = []
    current = []
    cells = 0
    for ch in text:
        ch_cells = _char_cells(ch)
        if current and cells + ch_cells > width:
            rows.append("".join(current))
            current = []
            cells = 0
        current.append(ch)
        cells += ch_cells
    rows.append("".join(current))
    return rows


def wrap_lines(lines, width):
    """逐行折行并拉平为实际写屏的行列表。"""
    return [row for line in lines for row in wrap_line(line, width)]


def terminal_width():
    """控制台可视宽度（列）；非控制台（重定向、管道）时返回 None。"""
    try:
        return os.get_terminal_size().columns
    except OSError:
        return None
