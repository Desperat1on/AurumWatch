# -*- coding: utf-8 -*-
"""主窗口几何单元测试（纯函数，不建窗口）。

关窗时记下的位置与大小，下次开窗照着摆：认得出就用；跑到屏幕外（换过显示器、改过
分辨率）的拉回可见区，别让窗口再也找不到。真实窗口的拖动、恢复与「记进配置文件」
按 spec 的约定手验。
"""

import unittest

from aurumwatch.config import parse_geometry
from aurumwatch.main_window import GEOMETRY_KEEP, visible_geometry

WORK_AREA = (0, 0, 1920, 1040)  # 主屏工作区：左、上、宽、高（已避开任务栏）


class ReadsTheShapeWeWrite(unittest.TestCase):
    """窗口几何就是 Tk 的 `wm geometry` 那种形状：宽x高+左+上。"""

    def test_a_saved_geometry_comes_back_as_four_numbers(self):
        self.assertEqual(parse_geometry("960x640+120+80"), (960, 640, 120, 80))

    def test_negative_offsets_mean_left_of_or_above_the_screen(self):
        self.assertEqual(parse_geometry("960x640-8-8"), (960, 640, -8, -8))

    def test_surrounding_blank_space_is_not_a_different_geometry(self):
        self.assertEqual(parse_geometry(" 960x640+120+80 "), (960, 640, 120, 80))

    def test_anything_we_did_not_write_is_not_a_geometry(self):
        for text in (None, "", 42, "abc", "960x640", "800x600", "960x640+120",
                     "=960x640+120+80", "960x640+120+80+40"):
            with self.subTest(text=text):
                self.assertIsNone(parse_geometry(text))


class KeepsTheWindowWhereYouLeftIt(unittest.TestCase):
    """上次关窗摆的地方，这次照摆（见 User Story 20）。"""

    def test_a_position_that_is_still_on_screen_is_kept(self):
        self.assertEqual(
            visible_geometry("960x640+120+80", WORK_AREA), "960x640+120+80"
        )

    def test_a_window_from_a_bigger_screen_is_pulled_back_into_view(self):
        """4K 屏上摆到右下角，换回 1920x1080：拉回来，至少留 keep 像素看得见。"""
        self.assertEqual(
            visible_geometry("960x640+3000+2000", WORK_AREA),
            f"960x640+{1920 - GEOMETRY_KEEP}+{1040 - GEOMETRY_KEEP}",
        )

    def test_a_window_left_of_the_screen_keeps_a_visible_slice(self):
        """显示器搬到右边、窗口留在负坐标：留一条边，拖得回来。"""
        pulled = parse_geometry(visible_geometry("960x640-900+80", WORK_AREA))
        self.assertEqual(pulled, (960, 640, -960 + GEOMETRY_KEEP, 80))

    def test_hanging_off_the_edge_on_purpose_is_respected(self):
        """故意摆成半出屏的（贴着右缘看盘）：那是用户的意图，不动它。"""
        saved = "960x640+1500+80"
        self.assertEqual(visible_geometry(saved, WORK_AREA), saved)

    def test_the_window_never_ends_up_above_the_work_area(self):
        pulled = parse_geometry(visible_geometry("960x640+120-50", WORK_AREA))
        self.assertEqual(pulled[3], 0, "顶边拉回工作区里，标题栏才抓得住")

    def test_a_work_area_that_starts_away_from_the_origin_is_respected(self):
        """任务栏在左边时工作区不从 0 开始：拉回的是工作区的边（与弹窗一个口径）。"""
        pulled = parse_geometry(visible_geometry("960x640-5000+80", (100, 40, 1820, 1000)))
        self.assertEqual(pulled[2], 100 - 960 + GEOMETRY_KEEP)

    def test_nothing_saved_means_open_at_the_default_spot(self):
        self.assertIsNone(visible_geometry(None, WORK_AREA), "第一次运行：交给 Tk")

    def test_a_geometry_we_did_not_write_is_ignored(self):
        self.assertIsNone(visible_geometry("800x600", WORK_AREA))

    def test_without_a_work_area_the_saved_geometry_is_used_as_is(self):
        self.assertEqual(
            visible_geometry("960x640+120+80", None), "960x640+120+80", "问不到屏幕就别猜"
        )


if __name__ == "__main__":
    unittest.main()
