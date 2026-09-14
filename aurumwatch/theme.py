# -*- coding: utf-8 -*-
"""两个窗口共用的外观：配色、字体族与底部按钮的样式。

两个窗口各有一套字号层级（抬头、正文、红字……），但底色、文字色与按钮必须一致，
所以收在这里一份。ticket 04 做外观设置时，这里换成「按当前外观取值」即可。
"""

import tkinter as tk

FONT = "Microsoft YaHei UI"
BUTTON_FONT = (FONT, 10)

BG = "#1e1f22"
FG = "#f0f0f0"
DIM = "#a8a8a8"
RISE = "#e5534b"  # 涨红跌绿，沿用国内行情习惯；也用作「填得不对」「保存失败」的红
FALL = "#3fb950"
WARN = "#e6b450"  # 与行情涨跌区分开：状态异常、故障、没填对
FIELD_BG = "#2f3237"  # 输入框与按钮的底色
BUTTON_ACTIVE_BG = "#3a3e45"


def button(parent, text, command):
    """窗口底部的按钮：不抢眼、鼠标移上去有手型。"""
    return tk.Button(
        parent, text=text, command=command, font=BUTTON_FONT, bg=FIELD_BG, fg=FG,
        activebackground=BUTTON_ACTIVE_BG, activeforeground=FG, relief="flat",
        padx=14, pady=4, cursor="hand2",
    )
