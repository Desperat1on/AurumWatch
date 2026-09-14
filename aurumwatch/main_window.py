# -*- coding: utf-8 -*-
"""主窗口（Tk）：把视图模型摆到窗口上，自己不判断行情、不算数。

关闭主窗口即退出监视（见 ADR-0001：不做托盘、不藏后台进程）。
配色、字体与折行宽度都取自当前外观（见 ticket 04）：`apply` 一下当场改观，
之后每帧的卡片也照新的画。
"""

import ctypes
import tkinter as tk
import traceback

from aurumwatch.viewmodel import TONE_PRICE

WINDOW_TITLE = "AurumWatch"  # 不单用「金价」：两个市场各有各的金价（见 CONTEXT.md）
WINDOW_MARGIN = 12
STARTUP_NOTICE = "正在取第一轮行情……"

# 字号档位（相对基准字号）：抬头、刷新时刻、卡片标题、现价、正文、状态、提示
HEADLINE_STEP = 2
STAMP_STEP = -1
CARD_TITLE_STEP = -1
PRICE_STEP = 7
LINE_STEP = 0
STATUS_STEP = 0
NOTICE_STEP = -1

# 折行宽度（像素，按基准字号 10 标定）：不加限制时，一行长报错会把窗口撑到几千像素宽；
# 字号调大后按比例放宽，一行放得下的字数才不至于变少（见 theme.Theme.wrap）
WRAP_AT_BASE = 520
MIN_SIZE = (460, 320)


class MainWindow:
    """常驻行情面板：抬头、两个市场各一张卡片，底部 [设置][立即刷新]。"""

    def __init__(self, on_refresh, on_settings, theme):
        self._view = None  # 最近一帧：换外观时照它重画一次，不必等下一轮刷新
        # self._theme 由末尾的 apply() 统一维护：构造与改外观走同一条路，不会两处各写一份
        self._error_reported = False
        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._root.minsize(*(theme.scaled(side) for side in MIN_SIZE))
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._root.report_callback_exception = self._report_callback_error

        self._headline = tk.Label(self._root, text=WINDOW_TITLE, anchor="w")
        self._headline.pack(anchor="w", fill="x", padx=WINDOW_MARGIN, pady=(10, 0))
        self._stamp = tk.Label(self._root, text="", anchor="w")
        self._stamp.pack(anchor="w", fill="x", padx=WINDOW_MARGIN, pady=(2, 6))

        self._cards = tk.Frame(self._root)
        self._cards.pack(fill="both", expand=True, padx=WINDOW_MARGIN)

        self._bottom = tk.Frame(self._root)
        self._bottom.pack(fill="x", padx=WINDOW_MARGIN, pady=(0, 10))
        self._notice = tk.Label(
            self._bottom, text=STARTUP_NOTICE, anchor="w", justify="left"
        )
        self._notice.pack(side="left")
        self._refresh_button = theme.button(self._bottom, "立即刷新", on_refresh)
        self._refresh_button.pack(side="right")
        self._settings_button = theme.button(self._bottom, "设置", on_settings)
        self._settings_button.pack(side="right", padx=(0, 8))

        self.apply(theme)

    @property
    def root(self):
        """Tk 根窗：弹窗挂靠它、编排层借它排定时回调。"""
        return self._root

    def apply(self, theme):
        """换一套外观：主窗口当场改观，之后每帧的卡片也照新的画（见 ticket 04）。

        构造时也走这里，省得把样式写两遍。保存设置后由编排层调用。
        """
        self._theme = theme
        self._root.configure(bg=theme.bg)
        self._root.attributes("-topmost", theme.topmost)
        self._headline.configure(
            bg=theme.bg, fg=theme.fg,
            font=theme.font(HEADLINE_STEP, bold=True),
        )
        self._stamp.configure(
            bg=theme.bg, fg=theme.dim, font=theme.font(STAMP_STEP)
        )
        for frame in (self._cards, self._bottom):
            frame.configure(bg=theme.bg)
        self._notice.configure(
            bg=theme.bg, fg=theme.warn, font=theme.font(NOTICE_STEP),
            wraplength=theme.scaled(WRAP_AT_BASE),
        )
        for button in (self._refresh_button, self._settings_button):
            theme.style_button(button)
        if self._view is not None:
            self.show(self._view)  # 卡片照新外观重画，不用等下一轮刷新

    def show(self, view):
        """按一帧视图模型更新窗口：抬头、刷新时刻、各市场卡片。

        顺带清掉上一条提示：提示只讲最近一轮里发生的事，不留在屏幕上冒充现状。
        """
        self._view = view
        self._headline.configure(text=view.headline)
        self._stamp.configure(text=f"{view.refreshed}　{view.next_refresh}")
        for card in self._cards.winfo_children():
            card.destroy()
        for market in view.markets:
            self._add_card(market)
        self._notice.configure(text="")

    def show_notice(self, text):
        """在底部显示一条提示（配置回退、弹窗失败这类事，见 ticket 05 的事件记录）。"""
        self._notice.configure(text=text)

    def run(self):
        """进入窗口事件循环；关闭窗口后返回。"""
        self._root.mainloop()

    def _add_card(self, market):
        """一张市场卡片：标题带市场说明，正文逐行按色调摆放，末尾是市场状态。"""
        theme = self._theme
        card = tk.LabelFrame(
            self._cards, text=f"{market.name}　{market.detail}", bg=theme.bg,
            fg=theme.dim, font=theme.font(CARD_TITLE_STEP), bd=1,
            relief="solid", labelanchor="nw", padx=12, pady=8,
        )
        card.pack(fill="x", pady=(0, 8))
        for line in market.lines:
            tk.Label(
                card, text=line.text, bg=theme.bg, fg=theme.color(line.tone),
                font=theme.font(
                    PRICE_STEP if line.tone == TONE_PRICE else LINE_STEP,
                    bold=line.tone == TONE_PRICE,
                ),
                anchor="w", justify="left", wraplength=theme.scaled(WRAP_AT_BASE),
            ).pack(anchor="w", fill="x")
        tk.Label(
            card, text=f"状态：{market.status.text}", bg=theme.bg,
            fg=theme.color(market.status.tone),
            font=theme.font(STATUS_STEP, bold=True), anchor="w", justify="left",
            wraplength=theme.scaled(WRAP_AT_BASE),
        ).pack(anchor="w", pady=(4, 0))

    def _close(self):
        """关闭主窗口即退出监视：销毁根窗，mainloop 返回，进程随之结束。"""
        self._root.destroy()

    def _report_callback_error(self, exc_type, value, tb):
        """窗口回调里的异常：没有控制台可打印，用系统消息框说明，程序继续跑。

        只弹第一次：上屏回调 200ms 跑一次，每次出错都弹模态框会把人淹在对话框里。
        之后的异常不再出声，留给落盘日志去记（见 ticket 05）；程序继续跑。
        """
        if self._error_reported:
            return
        self._error_reported = True
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
