# -*- coding: utf-8 -*-
"""取数与解析：向数据源要行情、把响应解析成读数。

本模块是唯一的出网处；判定核心（alerts、failures）与视图模型只消费这里产出的读数
（刷新节奏见 `schedule`，那里不依赖网络）。
"""

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

import requests

API_URL = "https://hq.sinajs.cn/list={code}"
HEADERS = {"Referer": "https://finance.sina.com.cn"}
REQUEST_TIMEOUT = 10  # 单次请求超时（秒）：不由用户权衡，留在模块里（设置只收用户可调的项）

_LINE_RE = re.compile(r'var hq_str_([A-Za-z0-9_]+)="([^"]*)"')


class QuoteError(Exception):
    """一次行情取数或解析失败。"""


@dataclass(frozen=True)
class Quote:
    """一次行情读数：价格（已在展示单位）与行情数据时间。"""

    price: Decimal
    time: datetime


@dataclass(frozen=True)
class MarketRound:
    """一个市场一轮刷新的取数结果：读数与故障二者必居其一。"""

    market: dict
    quote: Quote | None = None
    error: str | None = None

    def __post_init__(self):
        if (self.quote is None) == (self.error is None):
            raise ValueError("MarketRound 须有读数或故障原因，且只有其一")

    @property
    def failed(self):
        return self.error is not None


def parse_quote(line, code, scale=Decimal("1")):
    """解析新浪行情响应中的一行，定位到 `code` 并返回 Quote。

    line 为已解码文本，scale 把接口数值换算为展示单位（gds_ 与 hf_ 两个
    系列的量纲一致，均为 1；换算系数留在此处是为接口量纲变化兜底）。
    """
    match = _LINE_RE.search(line)
    if not match or match.group(1) != code:
        raise QuoteError(f"响应中没有 {code} 的数据：{line[:80]!r}")
    fields = match.group(2).split(",")
    if len(fields) < 13 or not fields[0]:
        raise QuoteError(f"{code} 返回空数据（可能代码错误或接口限制）")
    try:
        price = Decimal(fields[0]) * scale
    except InvalidOperation:
        raise QuoteError(f"{code} 价格字段无法解析：{fields[0]!r}") from None
    time_text = fields[6].split(".")[0]  # 国际行情时间带毫秒，取到秒
    try:
        data_time = datetime.strptime(
            fields[12] + " " + time_text, "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        raise QuoteError(
            f"{code} 行情时间无法解析：{fields[12]} {fields[6]}"
        ) from None
    return Quote(price=price, time=data_time)


def fetch_raw(code):
    """向数据源请求单个行情代码的原始响应文本（GBK 解码）。"""
    response = requests.get(
        API_URL.format(code=code), headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.content.decode("gbk")


def fetch_rounds(markets):
    """逐市场取数并解析（副作用层）：每个市场各发一次请求，成败互不牵连。

    单市场失败（网络异常或响应解析失败）只影响它自己，另一个市场照常取数。
    """
    rounds = []
    for market in markets:
        code = market["code"]
        try:
            raw = fetch_raw(code)
            line = next((l for l in raw.splitlines() if code in l), "")
            quote = parse_quote(line, code)
        except Exception as exc:  # 本轮失败不退出，下一轮自动重试
            rounds.append(MarketRound(market=market, error=f"{type(exc).__name__}: {exc}"))
        else:
            rounds.append(MarketRound(market=market, quote=quote))
    return rounds
