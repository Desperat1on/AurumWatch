# -*- coding: utf-8 -*-
"""刷新节奏（纯函数）：整分对齐的下一轮时刻。

独立成模块是为了让视图模型也能算「下次刷新」而不牵进网络依赖
（`quotes` 是唯一的出网模块）。
"""


def next_refresh_delay(now, interval):
    """返回距离下一个整分对齐刷新的秒数（下限 1 秒）；整分即 interval 的整数倍。"""
    current = now.minute * 60 + now.second
    next_aligned = (current // interval + 1) * interval
    return max(1, next_aligned - current)
