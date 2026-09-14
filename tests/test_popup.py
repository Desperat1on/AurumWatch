# -*- coding: utf-8 -*-
"""弹窗落位单元测试（纯函数，不建窗口）。

弹窗贴哪个角是外观设置里的一项（主屏四角，默认右下角），同一角上多个弹窗依次向内
错开。这里只断言坐标；「不抢焦点、点击即关」这些真实窗口行为按 spec 的约定手验。
"""

import unittest

from aurumwatch.popup import POPUP_GAP, POPUP_MARGIN, corner_origin

WORK_AREA = (0, 0, 1920, 1040)  # 主屏工作区：左、上、宽、高（已避开任务栏）
SIZE = (300, 160)  # 一个弹窗的宽高
RIGHT = WORK_AREA[2] - SIZE[0] - POPUP_MARGIN  # 1620 - 24：贴右缘
BOTTOM = WORK_AREA[3] - SIZE[1] - POPUP_MARGIN  # 1040 - 160 - 24：贴下缘


class PopupSitsInTheChosenCorner(unittest.TestCase):
    """选哪个角就贴哪个角，留白一致（见 ticket 04：弹窗位置在主屏四角间选择）。"""

    def test_bottom_right_is_where_it_used_to_be(self):
        self.assertEqual(
            corner_origin("bottom-right", WORK_AREA, SIZE, 0), (RIGHT, BOTTOM)
        )

    def test_the_other_three_corners_move_the_matching_edges(self):
        self.assertEqual(
            corner_origin("bottom-left", WORK_AREA, SIZE, 0), (POPUP_MARGIN, BOTTOM)
        )
        self.assertEqual(
            corner_origin("top-right", WORK_AREA, SIZE, 0), (RIGHT, POPUP_MARGIN)
        )
        self.assertEqual(
            corner_origin("top-left", WORK_AREA, SIZE, 0), (POPUP_MARGIN, POPUP_MARGIN)
        )

    def test_the_work_area_may_start_away_from_the_origin(self):
        """任务栏在左边时工作区不从 0 开始：贴的是工作区的边，不是整屏的边。"""
        area = (100, 40, 1820, 1000)
        x, y = corner_origin("bottom-left", area, SIZE, 0)
        self.assertEqual(x, 100 + POPUP_MARGIN)
        self.assertEqual(y + SIZE[1] + POPUP_MARGIN, 40 + 1000, "下缘贴齐工作区")


class SeveralPopupsStackUp(unittest.TestCase):
    """同时来两条提醒时上下叠放，不严丝合缝地盖在一起。"""

    def test_the_second_one_steps_away_from_the_corner(self):
        first = corner_origin("bottom-right", WORK_AREA, SIZE, 0)
        second = corner_origin("bottom-right", WORK_AREA, SIZE, 1)
        self.assertEqual(first[0], second[0], "只在纵向上错开，横坐标不动")
        self.assertEqual(first[1] - second[1], SIZE[1] + POPUP_GAP)

    def test_top_corners_stack_downwards(self):
        first = corner_origin("top-left", WORK_AREA, SIZE, 0)
        second = corner_origin("top-left", WORK_AREA, SIZE, 1)
        self.assertEqual(second[1] - first[1], SIZE[1] + POPUP_GAP)

    def test_a_crowd_never_pushes_a_popup_off_the_screen(self):
        """叠不下时宁可压在一起，也不能跑到工作区外面去。"""
        x, y = corner_origin("bottom-right", WORK_AREA, SIZE, 20)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, POPUP_MARGIN)

    def test_a_popup_larger_than_the_work_area_still_starts_inside(self):
        x, y = corner_origin("bottom-right", WORK_AREA, (2000, 1200), 0)
        self.assertEqual((x, y), (POPUP_MARGIN, POPUP_MARGIN))


if __name__ == "__main__":
    unittest.main()
