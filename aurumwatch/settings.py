# -*- coding: utf-8 -*-
"""配置区：可调参数的默认值。

改配置只改这里；判定、取数、弹窗、编排各模块都从这里读取。
"""

from datetime import timedelta
from decimal import Decimal

# 轮询间隔（秒）。刷新时刻与系统时钟的整分钟对齐（如 60 → 每分 0 秒，
# 120 → 每分 0、2 分 0 秒），保证行情数据时间与刷新时刻一致、可对照。
REFRESH_INTERVAL = 60
# 单次请求超时（秒）
REQUEST_TIMEOUT = 10
# 重新武装带比例：触发后，价格须回到阈值另一侧并越过「阈值 × 该比例」才算
# 翻篇、可再次提醒；贴着阈值抖动不会反复打扰。0.001 即千分之一（0.1%）。
REARM_RATIO = Decimal("0.001")
# 弹窗停留时长（秒），期间点击即关
POPUP_DURATION = 30
# 触发时是否播放一声短提示音
SOUND_ENABLED = True
# 某市场连续取数失败多久后弹出一次故障警告（须用 datetime.timedelta 填写）
FAILURE_WARN_AFTER = timedelta(minutes=10)

# 每个市场的提醒阈值：涨破、跌破各一个；留空（None）或填 0 的方向不启用、不提醒。
# 数值照抄 Decimal("...") 的格式填写（带小数时不要直接写浮点数）。
MARKETS = (
    {
        "name": "国内金价",
        "detail": "沪金99（上海黄金交易所 Au99.99）",
        "unit": "元/克",
        "code": "gds_AU9999",
        "up_threshold": None,  # 涨破提醒价，如 Decimal("950.00")
        "down_threshold": None,  # 跌破提醒价，如 Decimal("900.00")
    },
    {
        "name": "国际金价",
        "detail": "伦敦金（XAU/USD 现货黄金）",
        "unit": "美元/盎司",
        "code": "hf_XAU",
        "up_threshold": None,  # 涨破提醒价，如 Decimal("4400.00")
        "down_threshold": None,  # 跌破提醒价，如 Decimal("4300.00")
    },
)
