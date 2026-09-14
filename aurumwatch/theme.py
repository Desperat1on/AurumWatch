# -*- coding: utf-8 -*-
"""两个窗口共用的外观（主题）：由配置里的外观项算出配色、字号档位与控件样式。

用户只调六项（背景色、文字色、涨破色、跌破色、字体、基准字号），其余颜色由它们
派生——浅底深字也自洽。字号一律按「基准 + 档位」派生，改一个数各处一起变。主窗口、
设置窗口与弹窗都从这里取色取字，预览与真实弹窗因此长得一模一样。
"""

import tkinter as tk
from dataclasses import dataclass

BASE_SIZE = 10  # 字号档位的标定基准：配置里基准字号的默认值也是它

DIM_MIX = 0.35  # 次要文字（行情数据时间那一类）：往背景色靠这么多
FAINT_MIX = 0.55  # 更次要的文字（弹窗上「点击关闭」那行）
FIELD_MIX = 0.09  # 输入框与按钮的底色：比背景略偏文字色（默认外观下即原 #2f3237 一档）
ACTIVE_MIX = 0.14  # 按钮按下去时再深/再亮一档
LIGHT_BG_LUMA = 0.5  # 底色亮到这个程度就算浅色底
WARN_ON_DARK = "#e6b450"  # 深色底上的警告色（琥珀）
WARN_ON_LIGHT = "#8a6410"  # 浅色底上压暗到同一色相，否则糊在白底里看不见

# 视图模型给的色调 → 主题里的颜色；没列出的（normal、price）一律正文色
_TONE_FIELDS = {"dim": "dim", "rise": "rise", "fall": "fall", "warn": "warn"}


@dataclass(frozen=True)
class Theme:
    """当前外观：用户调的六项（加弹窗与窗口的三个开关）与由它们派生的配色。"""

    bg: str
    fg: str
    rise: str
    fall: str
    font_family: str
    base_size: int
    popup_seconds: int
    popup_corner: str
    topmost: bool
    # 派生色：不单独配置，改底色或文字色时自动跟着走
    dim: str
    faint: str
    field_bg: str
    button_active_bg: str
    warn: str

    @classmethod
    def from_appearance(cls, appearance):
        """配置里的外观段 → 一份外观（颜色已由配置层规范化成 #rrggbb）。"""
        bg, fg = appearance["bg"], appearance["fg"]
        return cls(
            bg=bg,
            fg=fg,
            rise=appearance["rise"],
            fall=appearance["fall"],
            font_family=appearance["font"],
            base_size=int(appearance["base_size"]),
            popup_seconds=int(appearance["popup_seconds"]),
            popup_corner=appearance["popup_corner"],
            topmost=bool(appearance["topmost"]),
            dim=_mix(fg, bg, DIM_MIX),
            faint=_mix(fg, bg, FAINT_MIX),
            field_bg=_mix(bg, fg, FIELD_MIX),
            button_active_bg=_mix(bg, fg, ACTIVE_MIX),
            warn=WARN_ON_LIGHT if _luma(bg) >= LIGHT_BG_LUMA else WARN_ON_DARK,
        )

    def color(self, tone):
        """按视图模型给的色调取色（不认识的色调按正文色）。"""
        field = _TONE_FIELDS.get(tone)
        return getattr(self, field) if field else self.fg

    def font(self, offset=0, *, bold=False):
        """一个字号档位：基准字号 + 偏移（磅），可加粗。"""
        size = self.base_size + offset
        return (self.font_family, size, "bold") if bold else (self.font_family, size)

    def wrap(self, width_at_base):
        """折行宽度：文字在大字号下占的地方也大，一行能放的字数才不至于变少。"""
        return round(width_at_base * self.base_size / BASE_SIZE)

    # —— 控件样式：两个窗口的按钮、输入框长相一致，改外观时也好整批重涂 ——

    def button(self, parent, text, command):
        """窗口底部的按钮：不抢眼、鼠标移上去有手型。"""
        return self.style_button(
            tk.Button(
                parent, text=text, command=command, relief="flat", padx=14, pady=4,
                cursor="hand2",
            )
        )

    def style_button(self, button):
        """把按钮涂成当前外观（外观看变了就再涂一遍）。"""
        button.configure(
            font=self.font(), bg=self.field_bg, fg=self.fg,
            activebackground=self.button_active_bg, activeforeground=self.fg,
        )
        return button

    def style_entry(self, entry):
        """输入框：底色比背景略偏一点，光标用正文色。"""
        entry.configure(
            bg=self.field_bg, fg=self.fg, insertbackground=self.fg,
            disabledbackground=self.bg, disabledforeground=self.dim,
        )
        return entry


def contrast_text(color):
    """在给定底色上看得清的文字色：浅底黑字、深底白字（色块上写色号用）。"""
    return "#000000" if _luma(color) >= LIGHT_BG_LUMA else "#ffffff"


def _rgb(color):
    """#rrggbb → (r, g, b)。"""
    return tuple(int(color[index : index + 2], 16) for index in (1, 3, 5))


def _hex(channels):
    return "#%02x%02x%02x" % channels


def _mix(color, toward, ratio):
    """把 color 往 toward 靠 ratio（0～1）：派生中间色用。"""
    return _hex(
        tuple(
            round(here + (there - here) * ratio)
            for here, there in zip(_rgb(color), _rgb(toward))
        )
    )


def _luma(color):
    """粗略亮度（0～1）：只用来判断底色是深是浅。"""
    red, green, blue = _rgb(color)
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255
