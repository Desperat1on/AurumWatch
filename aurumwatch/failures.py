# -*- coding: utf-8 -*-
"""取数故障记账（纯函数）：每市场独立计时、满时长警告一次、恢复清零。

记账的同时产出「故障出现／恢复」与「故障警告」两类事件：谁最清楚哪一轮是转折，
就由谁来报，省得调用方拿着一前一后两份账自己去对照（对照错了不会报错，只会记错）。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class FailureState:
    """一个市场的取数失败记账：连续失败起点（成功即归零）与本次长故障是否已警告。"""

    since: datetime | None = None
    warned: bool = False


# 从未失败过的初始失败状态
INITIAL_FAILURE = FailureState()


@dataclass(frozen=True)
class FailureWarning:
    """一次故障警告：某市场连续取数失败到点，内容说明是数据源故障。"""

    market: str
    detail: str
    since: datetime
    elapsed: timedelta
    error: str


@dataclass(frozen=True)
class FailureChange:
    """一次故障出现或恢复：某市场这一轮起取不到行情，或又能取到了。"""

    market: str
    recovered: bool
    error: str = ""  # 出现：这一轮的取数错误
    elapsed: timedelta = timedelta()  # 恢复：这次故障持续了多久


def duration_text(delta):
    """时长文案：不足 1 分钟按秒、不足 1 小时按分钟，再长按小时加分钟。"""
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds} 秒"
    if seconds < 3600:
        return f"{seconds // 60} 分钟"
    hours, minutes = divmod(seconds // 60, 60)
    return f"{hours} 小时 {minutes} 分钟"


def update_failures(rounds, failures, at, warn_after):
    """一轮刷新后的取数失败记账（纯函数）→ (新记账, 警告, 出现与恢复)。

    某市场本轮失败：首轮记下起点（并把这次「故障出现」报出来），连续失败满
    warn_after 时产生一次警告并标记，此后不重复；本轮成功：计数清零、把这次
    「故障恢复」报出来，再出现长故障会重新计时、再次警告。状态表按市场分别写入，
    市场之间互不牵连。

    只在转折的那一轮产生事件：一直失败不算反复出现，逐轮行情与逐轮故障都不记。
    """
    warnings = []
    changes = []
    next_failures = dict(failures)
    for round_ in rounds:
        code = round_.market["code"]
        state = failures[code]
        if not round_.failed:
            if state.since is not None:  # 又能取到了：这次故障到此为止
                changes.append(
                    FailureChange(
                        market=round_.market["name"],
                        recovered=True,
                        elapsed=at - state.since,
                    )
                )
            next_failures[code] = INITIAL_FAILURE
            continue
        if state.since is None:  # 这一轮起取不到：这次故障开始了
            changes.append(
                FailureChange(
                    market=round_.market["name"], recovered=False, error=round_.error
                )
            )
        since = state.since or at
        warned = state.warned
        if not warned and at - since >= warn_after:
            warned = True
            warnings.append(
                FailureWarning(
                    market=round_.market["name"],
                    detail=round_.market["detail"],
                    since=since,
                    elapsed=at - since,
                    error=round_.error,
                )
            )
        next_failures[code] = FailureState(since=since, warned=warned)
    return next_failures, tuple(warnings), tuple(changes)
