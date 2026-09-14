# -*- coding: utf-8 -*-
"""外观派生单元测试（纯函数，不建窗口）。

用户只在外观组里调六项（背景色、文字色、涨破色、跌破色、字体、基准字号），其余
颜色与所有字号都由它们派生。这里断言的就是这份承诺：设进去的颜色原样生效、派生色
跟着底色走（浅底深字也自洽）、字号档位随基准整体平移、折行宽度跟着字号走。
"""

import unittest

from aurumwatch.config import default_values
from aurumwatch.theme import BASE_SIZE, Theme


def theme_of(**changes):
    """按外观默认值起一份主题，改掉其中几项（就是设置窗口里改的那几项）。"""
    appearance = default_values()["appearance"]
    appearance.update(changes)
    return Theme.from_appearance(appearance)


def luminance(color):
    """sRGB 相对亮度（WCAG 的定义），用来独立地判断「谁比谁亮」。"""
    channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(one, other):
    """两个颜色的对比度（WCAG 的定义）：1 表示一模一样，21 表示黑白。"""
    light, dark = sorted((luminance(one), luminance(other)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class TheSixSettingsTakeEffect(unittest.TestCase):
    """用户设的六项：原样进入主题，一处改、各处跟着变。"""

    def test_the_colors_and_the_font_are_kept_as_given(self):
        theme = theme_of(
            bg="#ffffff", fg="#101010", rise="#c00000", fall="#008000",
            font="SimSun", base_size=14,
        )
        self.assertEqual(theme.bg, "#ffffff")
        self.assertEqual(theme.fg, "#101010")
        self.assertEqual(theme.rise, "#c00000")
        self.assertEqual(theme.fall, "#008000")
        self.assertEqual(theme.font_family, "SimSun")
        self.assertEqual(theme.base_size, 14)

    def test_the_popup_and_window_switches_come_along(self):
        theme = theme_of(popup_seconds=8, popup_corner="top-left", topmost=True)
        self.assertEqual(theme.popup_seconds, 8)
        self.assertEqual(theme.popup_corner, "top-left")
        self.assertTrue(theme.topmost)

    def test_each_tone_picks_its_own_color(self):
        theme = theme_of(bg="#ffffff", fg="#101010", rise="#c00000", fall="#008000")
        self.assertEqual(theme.color("rise"), "#c00000")
        self.assertEqual(theme.color("fall"), "#008000")
        self.assertEqual(theme.color("dim"), theme.dim)
        self.assertEqual(theme.color("warn"), theme.warn)
        for tone in ("normal", "price", "不认识的色调"):
            with self.subTest(tone=tone):
                self.assertEqual(theme.color(tone), "#101010", "认不出的色调按正文色")


class TheRestIsDerived(unittest.TestCase):
    """只有六项由用户调，其余颜色得从底色与文字色里算出来。"""

    def test_secondary_colors_sit_between_the_text_and_the_background(self):
        for bg, fg in (("#1e1f22", "#f0f0f0"), ("#ffffff", "#101010")):
            with self.subTest(bg=bg):
                theme = theme_of(bg=bg, fg=fg)
                low, high = sorted((luminance(bg), luminance(fg)))
                for name in ("dim", "faint"):
                    value = luminance(getattr(theme, name))
                    self.assertLess(low, value, f"{name} 该比底色显眼")
                    self.assertLess(value, high, f"{name} 该比正文收敛")

    def test_field_background_stays_close_to_the_background_but_visible(self):
        theme = theme_of(bg="#ffffff", fg="#101010")
        self.assertNotEqual(theme.field_bg, "#ffffff", "白底上的输入框不能也全白")
        self.assertLess(luminance(theme.field_bg), luminance("#ffffff"))
        self.assertGreater(
            luminance(theme.field_bg), luminance(theme.button_active_bg),
            "按下去的按钮比常态更沉一点",
        )

    def test_derived_colors_follow_a_changed_background(self):
        dark = theme_of(bg="#1e1f22", fg="#f0f0f0")
        light = theme_of(bg="#ffffff", fg="#101010")
        self.assertNotEqual(dark.dim, light.dim, "派生色不是写死的常量")
        self.assertNotEqual(dark.field_bg, light.field_bg)
        self.assertGreater(
            luminance(light.field_bg), luminance(dark.field_bg), "浅底的输入框也浅"
        )

    def test_the_warning_color_stays_readable_on_a_light_background(self):
        dark = theme_of(bg="#1e1f22", fg="#f0f0f0")
        light = theme_of(bg="#ffffff", fg="#101010")
        self.assertGreaterEqual(
            contrast(dark.warn, dark.bg), 3, "深色底上的警告色本来就够显眼"
        )
        self.assertGreaterEqual(
            contrast(light.warn, light.bg), 3,
            "浅色底上要压暗，否则琥珀色糊在白底里看不见",
        )


class FontTiersFollowTheBaseSize(unittest.TestCase):
    """字号只调一个数：各处的档位由基准字号派生（ticket 04 的「整体缩放项」）。"""

    def test_a_tier_is_the_base_size_plus_its_offset(self):
        theme = theme_of(base_size=12)
        self.assertEqual(theme.font(), ("Microsoft YaHei UI", 12))
        self.assertEqual(theme.font(2), ("Microsoft YaHei UI", 14))
        self.assertEqual(theme.font(7, bold=True), ("Microsoft YaHei UI", 19, "bold"))
        self.assertEqual(theme.font(-1), ("Microsoft YaHei UI", 11))

    def test_every_tier_moves_with_the_base_size(self):
        small, large = theme_of(base_size=9), theme_of(base_size=16)
        for offset in (-1, 0, 5, 12):
            with self.subTest(offset=offset):
                gap = large.font(offset)[1] - small.font(offset)[1]
                self.assertEqual(gap, 16 - 9, "差一档就是差一个基准字号")

    def test_the_font_family_follows_the_setting(self):
        theme = theme_of(font="SimSun", base_size=11)
        self.assertEqual(theme.font(0, bold=True), ("SimSun", 11, "bold"))

    def test_the_default_base_size_is_the_one_the_old_windows_were_built_on(self):
        self.assertEqual(theme_of().font(), ("Microsoft YaHei UI", BASE_SIZE))

    def test_wrapping_grows_with_the_base_size(self):
        self.assertEqual(theme_of(base_size=BASE_SIZE).wrap(520), 520, "默认字号下原样")
        self.assertEqual(theme_of(base_size=15).wrap(520), 780, "字大了，一行也得更宽")


if __name__ == "__main__":
    unittest.main()
