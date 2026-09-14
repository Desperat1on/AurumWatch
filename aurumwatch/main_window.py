# -*- coding: utf-8 -*-
"""主窗口（Tk）：把视图模型摆到窗口上，自己不判断行情、不算数。

关闭主窗口即退出监视（见 ADR-0001：不做托盘、不藏后台进程）。
配色与弹窗同调；外观成为可配置项后由「外观」设置统一驱动（见 ticket 04）。
"""

import ctypes
import tkinter as tk
import traceback

from aurumwatch.viewmodel import (
    TONE_DIM,
    TONE_FALL,
    TONE_NORMAL,
    TONE_PRICE,
    TONE_RISE,
    TONE_WARN,
)

WINDOW_TITLE = "AurumWatch 金价监视"
FONT = "Microsoft YaHei UI"
HEADLINE_FONT = (FONT, 12, "bold")
STAMP_FONT = (FONT, 9)
CARD_TITLE_FONT = (FONT, 9)
PRICE_FONT = (FONT, 17, "bold")
LINE_FONT = (FONT, 10)
STATUS_FONT = (FONT, 10, "bold")
NOTICE_FONT = (FONT, 9)
BUTTON_FONT = (FONT, 10)

BG = "#1e1f22"
FG = "#f0f0f0"
DIM = "#a8a8a8"
RISE = "#e5534b"  # 涨红跌绿，沿用国内行情习惯
FALL = "#3fb950"
WARN = "#e6b450"  # 与行情涨跌区分开：状态异常、故障

TONE_COLOR = {
    TONE_NORMAL: FG,
    TONE_DIM: DIM,
    TONE_PRICE: FG,
    TONE_RISE: RISE,
    TONE_FALL: FALL,
    TONE_WARN: WARN,
}
TONE_FONT = {TONE_PRICE: PRICE_FONT}  # 未列出的色调一律用 LINE_FONT

WINDOW_MARGIN = 12
STARTUP_NOTICE = "正在取第一轮行情……"
# 卡片正文的折行宽度（像素）：不加限制时，一行长报错会把窗口撑到几千像素宽。
# 固定值对应用户不改窗口大小的情况；字号可调之后应随基准字号换算（见 ticket 04）。
WRAP_WIDTH = 520


class MainWindow:
    """常驻行情面板：抬头、两个市场各一张卡片，底部 [立即刷新]。"""

    def __init__(self, on_refresh):
        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._root.configure(bg=BG)
        self._root.minsize(460, 320)
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._root.report_callback_exception = self._report_callback_error

        self._headline = tk.Label(
            self._root, text=WINDOW_TITLE, bg=BG, fg=FG, font=HEADLINE_FONT,
            anchor="w",
        )
        self._headline.pack(anchor="w", fill="x", padx=WINDOW_MARGIN, pady=(10, 0))
        self._stamp = tk.Label(self._root, text="", bg=BG, fg=DIM, font=STAMP_FONT, anchor="w")
        self._stamp.pack(anchor="w", fill="x", padx=WINDOW_MARGIN, pady=(2, 6))

        self._cards = tk.Frame(self._root, bg=BG)
        self._cards.pack(fill="both", expand=True, padx=WINDOW_MARGIN)

        bottom = tk.Frame(self._root, bg=BG)
        bottom.pack(fill="x", padx=WINDOW_MARGIN, pady=(0, 10))
        self._notice = tk.Label(
            bottom, text=STARTUP_NOTICE, bg=BG, fg=WARN, font=NOTICE_FONT,
            anchor="w", justify="left", wraplength=WRAP_WIDTH,
        )
        self._notice.pack(side="left")
        tk.Button(
            bottom, text="立即刷新", command=on_refresh, font=BUTTON_FONT,
            bg="#2f3237", fg=FG, activebackground="#3a3e45", activeforeground=FG,
            relief="flat", padx=14, pady=4, cursor="hand2",
        ).pack(side="right")

    @property
    def root(self):
        """Tk 根窗：弹窗挂靠它、编排层借它排定时回调。"""
        return self._root

    def show(self, view):
        """按一帧视图模型更新窗口：抬头、刷新时刻、各市场卡片。

        顺带清掉上一条提示：提示只讲最近一轮里发生的事，不留在屏幕上冒充现状。
        """
        self._headline.configure(text=view.headline)
        self._stamp.configure(text=f"{view.refreshed}　{view.next_refresh}")
        for card in self._cards.winfo_children():
            card.destroy()
        for market in view.markets:
            self._add_card(market)
        self._notice.configure(text="")

    def show_notice(self, text):
        """在底部显示一条提示（目前用于弹窗显示失败，见 ticket 05 的事件记录）。"""
        self._notice.configure(text=text)

    def run(self):
        """进入窗口事件循环；关闭窗口后返回。"""
        self._root.mainloop()

    def _add_card(self, market):
        """一张市场卡片：标题带市场说明，正文逐行按色调摆放，末尾是市场状态。"""
        card = tk.LabelFrame(
            self._cards, text=f"{market.name}　{market.detail}", bg=BG, fg=DIM,
            font=CARD_TITLE_FONT, bd=1, relief="solid", labelanchor="nw",
            padx=12, pady=8,
        )
        card.pack(fill="x", pady=(0, 8))
        for line in market.lines:
            tk.Label(
                card, text=line.text, bg=BG, fg=TONE_COLOR.get(line.tone, FG),
                font=TONE_FONT.get(line.tone, LINE_FONT),
                anchor="w", justify="left", wraplength=WRAP_WIDTH,
            ).pack(anchor="w", fill="x")
        tk.Label(
            card, text=f"状态：{market.status.text}", bg=BG,
            fg=TONE_COLOR.get(market.status.tone, FG), font=STATUS_FONT, anchor="w",
            justify="left", wraplength=WRAP_WIDTH,
        ).pack(anchor="w", pady=(4, 0))

    def _close(self):
        """关闭主窗口即退出监视：销毁根窗，mainloop 返回，进程随之结束。"""
        self._root.destroy()

    def _report_callback_error(self, exc_type, value, tb):
        """窗口回调里的异常：没有控制台可打印，用系统消息框说明，程序继续跑。"""
        show_error_box("".join(traceback.format_exception(exc_type, value, tb)))


def show_error_box(text):
    """系统消息框：无控制台后，启动与运行期的错误只能这样呈现。"""
    try:
        ctypes.windll.user32.MessageBoxW(None, text, WINDOW_TITLE, 0x10)  # MB_ICONERROR
    except Exception:
        pass  # 连消息框都弹不出来时不再纠缠：错误已经无处可报


def enable_dpi_awareness():
    """高分屏下按系统缩放渲染窗口，文字不模糊（须在创建任何窗口之前调用）。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
