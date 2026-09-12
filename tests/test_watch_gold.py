# -*- coding: utf-8 -*-
"""watch_gold 解析器单元测试（纯函数，不碰网络与 UI）。"""

import unittest
from datetime import datetime
from decimal import Decimal

from watch_gold import QuoteError, next_refresh_delay, parse_quote

# 2026-09-12 本机实测的新浪响应（网络层按 GBK 解码后的文本）
DOMESTIC_LINE = (
    'var hq_str_gds_AU9999="940.00,0,940.00,946.00,950.00,935.00,02:30:00,'
    "939.54,938.88,8240,3.00,1.00,2026-09-12,沪金99\";"
)

INTERNATIONAL_LINE = (
    'var hq_str_hf_XAU="4348.35,4316.600,4348.35,4348.74,4402.19,4292.65,'
    "04:54:00,4316.60,4316.95,0,0,0,2026-09-12,伦敦金（现货黄金）\";"
)


class ParseQuoteDomestic(unittest.TestCase):
    def test_price_is_yuan_per_gram(self):
        quote = parse_quote(DOMESTIC_LINE, "gds_AU9999")
        self.assertEqual(quote.price, Decimal("940.00"))

    def test_data_time_is_datetime(self):
        quote = parse_quote(DOMESTIC_LINE, "gds_AU9999")
        self.assertEqual(quote.time, datetime(2026, 9, 12, 2, 30, 0))


class ParseQuoteInternational(unittest.TestCase):
    def test_price_is_usd_per_ounce(self):
        quote = parse_quote(INTERNATIONAL_LINE, "hf_XAU")
        self.assertEqual(quote.price, Decimal("4348.35"))

    def test_data_time_is_datetime(self):
        quote = parse_quote(INTERNATIONAL_LINE, "hf_XAU")
        self.assertEqual(quote.time, datetime(2026, 9, 12, 4, 54, 0))

    def test_time_with_milliseconds_is_truncated_to_seconds(self):
        line = (
            'var hq_str_hf_XAU="4348.35,0,0,0,0,0,04:54:00.123,0,0,0,0,0,'
            '2026-09-12,x";'
        )
        quote = parse_quote(line, "hf_XAU")
        self.assertEqual(quote.time, datetime(2026, 9, 12, 4, 54, 0))


class ParseQuoteScale(unittest.TestCase):
    def test_scale_converts_interface_units(self):
        quote = parse_quote(DOMESTIC_LINE, "gds_AU9999", scale=Decimal("0.01"))
        self.assertEqual(quote.price, Decimal("9.4000"))


class ParseQuoteErrors(unittest.TestCase):
    def test_empty_quote_raises(self):
        line = 'var hq_str_gds_AU9999="";'
        with self.assertRaises(QuoteError):
            parse_quote(line, "gds_AU9999")

    def test_missing_variable_raises(self):
        with self.assertRaises(QuoteError):
            parse_quote("<html>404</html>", "gds_AU9999")

    def test_wrong_code_raises(self):
        with self.assertRaises(QuoteError):
            parse_quote(DOMESTIC_LINE, "hf_XAU")

    def test_non_numeric_price_raises(self):
        line = (
            'var hq_str_gds_AU9999="abc,0,0,0,0,0,02:30:00,0,0,0,0,0,'
            '2026-09-12,沪金99";'
        )
        with self.assertRaises(QuoteError):
            parse_quote(line, "gds_AU9999")


class NextRefreshDelay(unittest.TestCase):
    def test_aligns_to_next_whole_minute(self):
        now = datetime(2026, 9, 12, 12, 34, 25)
        self.assertEqual(next_refresh_delay(now, 60), 35)

    def test_exact_minute_waits_full_interval(self):
        now = datetime(2026, 9, 12, 12, 34, 0)
        self.assertEqual(next_refresh_delay(now, 60), 60)

    def test_two_minute_interval_aligns_to_even_minutes(self):
        now = datetime(2026, 9, 12, 12, 33, 10)
        self.assertEqual(next_refresh_delay(now, 120), 50)


if __name__ == "__main__":
    unittest.main()
