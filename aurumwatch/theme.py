# -*- coding: utf-8 -*-
"""两个窗口共用的外观（主题）：由配置里的外观项算出配色、字号档位与控件样式。

用户只调六项（背景色、文字色、涨破色、跌破色、字体、基准字号），其余颜色由它们
派生——浅底深字也自洽。字号一律按「基准 + 档位」派生，改一个数各处一起变。主窗口、
设置窗口与弹窗都从这里取色取字，预览与真实弹窗因此长得一模一样。
"""

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from aurumwatch.viewmodel import TONE_DIM, TONE_FALL, TONE_RISE, TONE_WARN

BASE_SIZE = 10  # 字号档位的标定基准：配置里基准字号的默认值也是它

# 滚动条的 ttk 样式名：`scrollbar` 造控件与 `paint_scrollbar` 上色都按它取名
SCROLLBAR_STYLE = "Aurum.Vertical.TScrollbar"

DIM_MIX = 0.35  # 次要文字（行情数据时间那一类）：往背景色靠这么多
FAINT_MIX = 0.55  # 更次要的文字（弹窗上「点击关闭」那行）
FIELD_MIX = 0.09  # 输入框与按钮的底色：比背景略偏文字色（默认外观下即原 #2f3237 一档）
ACTIVE_MIX = 0.14  # 按钮按下去时再深/再亮一档
LIGHT_BG_LUMA = 0.5  # 底色亮到这个程度就算浅色底
WARN_ON_DARK = "#e6b450"  # 深色底上的警告色（琥珀）
WARN_ON_LIGHT = "#8a6410"  # 浅色底上压暗到同一色相，否则糊在白底里看不见
WARN_CONTRAST = 3  # 警告色与底色的对比度下限（WCAG 的 ≥3:1，见 ticket 04）

# 视图模型给的色调 → 主题里的颜色；没列出的（normal、price）一律正文色。
# 键取自 viewmodel 的常量：哪天改了色调名，这里跟着变，不会悄悄退成正文色。
_TONE_FIELDS = {TONE_DIM: "dim", TONE_RISE: "rise", TONE_FALL: "fall", TONE_WARN: "warn"}


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
            warn=warn_color(bg),
        )

    def color(self, tone):
        """按视图模型给的色调取色（不认识的色调按正文色）。"""
        field = _TONE_FIELDS.get(tone)
        return getattr(self, field) if field else self.fg

    def font(self, offset=0, *, bold=False):
        """一个字号档位：基准字号 + 偏移（磅），可加粗。"""
        size = self.base_size + offset
        return (self.font_family, size, "bold") if bold else (self.font_family, size)

    def scaled(self, pixels_at_base):
        """一个按基准字号标定的像素量（折行宽度、窗口最小尺寸）：字号大了等比放大。

        文字在大字号下占的地方也大，折行宽度跟着放，一行能放的字数才不至于变少；
        窗口的最小尺寸同理，不然字号一调大，最小尺寸就形同虚设。
        """
        return round(pixels_at_base * self.base_size / BASE_SIZE)

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

    def style_text(self, widget):
        """只读文本区（事件记录）：底色同背景、无边框，选中的一片用按钮按下色。

        字号不在这里定：文本区按哪一档由窗口说了算（见 main_window.EVENT_STEP）。
        """
        widget.configure(
            bg=self.bg, fg=self.fg, insertbackground=self.fg,
            selectbackground=self.button_active_bg, selectforeground=self.fg,
            relief="flat", borderwidth=0, highlightthickness=0,
        )
        return widget

    def scrollbar(self, parent, command):
        """一条竖滚动条：造出来就是当前外观的样子（与 `button` 一样，造与涂一处办）。

        `tk.Scrollbar` 在 Windows 上画的是系统那一支，配色一个都不认——深色窗口里
        横着一条浅灰的槽，改外观时它也纹丝不动，所以这里用的是 ttk 那支。
        """
        self.paint_scrollbar()
        return ttk.Scrollbar(
            parent, command=command, orient="vertical", style=SCROLLBAR_STYLE
        )

    def paint_scrollbar(self):
        """按这套外观配置滚动条样式：改外观时再调一次，已经造出来的滚动条跟着变。

        ttk 的样式是解释器级的，与具体哪个控件无关——所以这里不收控件参数。
        """
        style = ttk_style()
        style.configure(
            SCROLLBAR_STYLE,
            background=self.field_bg,
            troughcolor=self.bg,
            bordercolor=self.bg,
            arrowcolor=self.fg,
            lightcolor=self.field_bg,
            darkcolor=self.field_bg,
            relief="flat",
        )
        style.map(SCROLLBAR_STYLE, background=[("active", self.button_active_bg)])


def ttk_style(widget=None):
    """取一份 ttk 样式表，顺便确保主题是认颜色的那一支（clam）。

    ttk 的默认主题（vista）由系统绘制，颜色配置一概不认——设置窗口的字体下拉与
    主窗口的滚动条都要改色，两处从这里取同一条规矩。主题是解释器级的，切一次全局
    生效，已经造出来的控件跟着变；已经是 clam 就不重复切，免得每次保存都重来一遍。
    """
    style = ttk.Style(widget)
    if "clam" in style.theme_names() and style.theme_use() != "clam":
        style.theme_use("clam")
    return style


def warn_color(bg):
    """在给定底色上看得见的警告色（纯函数）。

    深底用琥珀、浅底用压暗的那支，但中灰底（`#808080` 这类）两支都不够看——所以
    这里真去量对比度：挑对比度高的一支，还不够就把它往远离底色的方向推，直到够
    `WARN_CONTRAST`（WCAG 的 3:1）。中灰底上「浅色底那一支」的对比度只有 1.36:1，
    而窗口上那几行故障提示、底部提示行与故障弹窗都靠这个颜色。
    """
    best = max((WARN_ON_DARK, WARN_ON_LIGHT), key=lambda color: _contrast(color, bg))
    if _contrast(best, bg) >= WARN_CONTRAST:
        return best
    away = "#000000" if _luma(bg) >= LIGHT_BG_LUMA else "#ffffff"
    for step in range(1, 21):
        mixed = _mix(best, away, step / 20)
        if _contrast(mixed, bg) >= WARN_CONTRAST:
            return mixed
    return away  # 推到头（墨黑／纯白）也只到这个份上：那就是最好的了


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
    """粗略亮度（0～1）：只用来判断底色是深是浅、该往哪边推。"""
    red, green, blue = _rgb(color)
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


def _relative_luminance(color):
    """WCAG 的相对亮度（每个通道先做 sRGB 反伽马）：对比度得按它算，肉眼估的不够。"""
    linear = [_linear(channel) for channel in _rgb(color)]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _linear(channel):
    """一个 0～255 通道的线性值（WCAG 的 sRGB 反伽马）。"""
    value = channel / 255
    return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4


def _contrast(one, other):
    """两个颜色的对比度（WCAG 的定义）：1 表示一模一样，21 表示黑白。"""
    lighter, darker = sorted(
        (_relative_luminance(one), _relative_luminance(other)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)
