# -*- coding: utf-8 -*-
"""金价监视——国内（沪金99，元/克）与国际（伦敦金，美元/盎司）实时行情上屏。

双击「启动金价监视.bat」运行；关闭窗口或 Ctrl+C 停止。
"""

import re
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import requests

# ============================ 配置区 ============================
# 轮询间隔（秒）。刷新时刻与系统时钟的整分钟对齐（如 60 → 每分 0 秒，
# 120 → 每分 0、2 分 0 秒），保证行情数据时间与刷新时刻一致、可对照。
REFRESH_INTERVAL = 60
# 单次请求超时（秒）
REQUEST_TIMEOUT = 10

MARKETS = (
    {
        "name": "国内金价",
        "detail": "沪金99（上海黄金交易所 Au99.99）",
        "unit": "元/克",
        "code": "gds_AU9999",
    },
    {
        "name": "国际金价",
        "detail": "伦敦金（XAU/USD 现货黄金）",
        "unit": "美元/盎司",
        "code": "hf_XAU",
    },
)
# ===============================================================

API_URL = "https://hq.sinajs.cn/list={codes}"
HEADERS = {"Referer": "https://finance.sina.com.cn"}
NEWLINE = "\r\n"

_LINE_RE = re.compile(r'var hq_str_([A-Za-z0-9_]+)="([^"]*)"')


class QuoteError(Exception):
    """一次行情取数或解析失败。"""


@dataclass(frozen=True)
class Quote:
    """一次行情读数：价格（已在展示单位）与行情数据时间。"""

    price: Decimal
    time: datetime


def next_refresh_delay(now, interval):
    """返回距离下一个整分对齐刷新的秒数（下限 1 秒）；整分即 interval 的整数倍。"""
    current = now.minute * 60 + now.second
    next_aligned = (current // interval + 1) * interval
    return max(1, next_aligned - current)


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


def fetch_raw(codes):
    """向数据源请求若干行情代码的原始响应文本（GBK 解码）。"""
    response = requests.get(
        API_URL.format(codes=",".join(codes)), headers=HEADERS, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    return response.content.decode("gbk")


def render(market, quote, error):
    """渲染单个市场的显示段落。"""
    lines = [f"【{market['name']}】{market['detail']}"]
    if error is not None:
        lines.append(f"  数据源故障：{error}")
    else:
        lines.append(f"  现价：{quote.price:.2f} {market['unit']}")
        lines.append(f"  行情数据时间：{quote.time:%Y-%m-%d %H:%M:%S}")
    return lines


def run():
    """主循环：每 REFRESH_INTERVAL 秒取一次两个市场的行情并刷新上屏。"""
    codes = [market["code"] for market in MARKETS]
    frame_lines = 0
    cycle = 0
    while True:
        cycle += 1
        now = datetime.now()
        lines = [
            f"金价监视中——每 {REFRESH_INTERVAL} 秒刷新，Ctrl+C 或关闭窗口停止",
            f"本次刷新：{now:%Y-%m-%d %H:%M:%S}",
            "",
        ]
        try:
            raw = fetch_raw(codes)
            fetch_error = None
        except Exception as exc:  # 单轮取数失败不退出，下一轮自动重试
            raw = ""
            fetch_error = f"{type(exc).__name__}: {exc}"
        for market in MARKETS:
            quote = None
            error = fetch_error
            if error is None:
                line = next(
                    (l for l in raw.splitlines() if market["code"] in l), ""
                )
                try:
                    quote = parse_quote(line, market["code"])
                except QuoteError as exc:
                    error = str(exc)
            lines.extend(render(market, quote, error))
            lines.append("")
        delay = next_refresh_delay(now, REFRESH_INTERVAL)
        next_fire = now.replace(microsecond=0) + timedelta(seconds=delay)
        lines.append(
            f"下次刷新：{next_fire:%H:%M:%S}（约 {delay} 秒后，第 {cycle} 轮）"
        )
        # 回到本帧起点并清掉旧内容，原地刷新
        if frame_lines:
            sys.stdout.write(f"\x1b[{frame_lines}A")
        sys.stdout.write("\x1b[J" + NEWLINE.join(lines) + NEWLINE)
        sys.stdout.flush()
        frame_lines = len(lines)
        time.sleep(delay)


def main():
    try:
        run()
    except KeyboardInterrupt:
        print("\r\n监视已停止。")
    except Exception:
        traceback.print_exc()
        input("脚本出错，按回车键关闭窗口……")
        sys.exit(1)


if __name__ == "__main__":
    main()
