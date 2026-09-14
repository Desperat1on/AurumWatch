# -*- coding: utf-8 -*-
"""控制台写屏辅助单元测试（纯函数）：自己折行并数行，原地刷新才不越算越偏。"""

import unittest

from aurumwatch.console import display_cells, wrap_line


class DisplayCells(unittest.TestCase):
    """控制台列数：东亚宽字符 2 列，歧义字符保守按 2 列。"""

    def test_ascii_counts_one_per_char(self):
        self.assertEqual(display_cells("abc"), 3)

    def test_cjk_counts_two_per_char(self):
        self.assertEqual(display_cells("国内金价"), 8)

    def test_ambiguous_counts_two_to_stay_conservative(self):
        self.assertEqual(display_cells("——"), 4)


class WrapLine(unittest.TestCase):
    """自行折行：每行不超宽、宽字符不拆开（终端不再有机会自行折行）。"""

    def test_short_line_stays_one_row(self):
        self.assertEqual(wrap_line("距触发还差 10.00", 40), ["距触发还差 10.00"])

    def test_line_exactly_filling_width_stays_one_row(self):
        self.assertEqual(wrap_line("abcdefghij", 10), ["abcdefghij"])

    def test_one_char_over_wraps_to_two_rows(self):
        self.assertEqual(wrap_line("abcdefghijk", 10), ["abcdefghij", "k"])

    def test_wide_char_moves_whole_to_next_row(self):
        self.assertEqual(wrap_line("123456789中国", 10), ["123456789", "中国"])

    def test_empty_line_is_one_row(self):
        self.assertEqual(wrap_line("", 40), [""])

    def test_realistic_error_line_rows_never_exceed_width(self):
        line = (
            "  !! 数据源故障：ConnectionError: HTTPSConnectionPool("
            "host='hq.sinajs.cn', port=443): Max retries exceeded with url: "
            "/list=gds_AU9999 (Caused by NewConnectionError("
            "'HTTPSConnectionPool(host=hq.sinajs.cn, port=443): Failed to "
            "establish a new connection: [WinError 10051] 网络不可达'))"
        )
        rows = wrap_line(line, 119)
        self.assertGreater(len(rows), 1, "长报错行应当折行")
        for row in rows:
            self.assertLessEqual(display_cells(row), 119)

    def test_every_row_fits_across_widths_and_mixed_content(self):
        text = "  !! 数据源故障：ConnectionError: 网络不可达（超时）"
        for width in (20, 40, 119):
            for row in wrap_line(text, width):
                self.assertLessEqual(display_cells(row), width)


if __name__ == "__main__":
    unittest.main()
