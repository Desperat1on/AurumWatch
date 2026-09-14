# -*- coding: utf-8 -*-
"""主窗口（Tk）：把视图模型与事件记录摆到窗口上，自己不判断行情、不算数。

关闭主窗口即退出监视（见 ADR-0001：不做托盘、不藏后台进程）。
配色、字体与折行宽度都取自当前外观（见 ticket 04）：`apply` 一下当场改观，
之后每帧的卡片也照新的画。事件记录的条目文字由 journal 给出（与日志同文），
这里只负责摆（见 ticket 05）。
"""

import base64
import ctypes
import tkinter as tk
import traceback

from aurumwatch import icon
from aurumwatch.config import parse_geometry
from aurumwatch.viewmodel import TONE_PRICE

WINDOW_TITLE = "AurumWatch"  # 不单用「金价」：两个市场各有各的金价（见 CONTEXT.md）
# 窗口与任务栏图标：Tk 拿这一张去缩放，64 在 100%–200% 缩放下都够用（任务栏最大 64）
ICON_SIZE = 64
WINDOW_MARGIN = 12
STARTUP_NOTICE = "正在取第一轮行情……"
EVENTS_TITLE = "事件记录"

# 字号档位（相对基准字号）：抬头、刷新时刻、卡片标题、现价、正文、状态、提示、事件
HEADLINE_STEP = 2
STAMP_STEP = -1
CARD_TITLE_STEP = -1
PRICE_STEP = 7
LINE_STEP = 0
STATUS_STEP = 0
NOTICE_STEP = -1
EVENT_STEP = -1

# 提示行固定两行高（空着也占着）：长短不一的提示来了走了，窗口不跟着一跳一跳
NOTICE_ROWS = 2

# 事件记录区一次看得见几行：最近 50 条都摊开会把窗口撑得比屏幕还高，多的用滚动条看
EVENT_ROWS = 8
# 事件记录区的宽度（字符）：不给的话 Tk 默认按 80 字符算，窗口会被撑到 950px 宽。
# 一条触发记录约 70 字，这个宽度下折两行——近况本来就该是几眼看完的东西
EVENT_CHARS = 46

# 折行宽度（像素，按基准字号 10 标定）：不加限制时，一行长报错会把窗口撑到几千像素宽；
# 字号调大后按比例放宽，一行放得下的字数才不至于变少（见 theme.Theme.scaled）
WRAP_AT_BASE = 520
# 窗口最小尺寸（像素，同样按基准字号标定）：定得比内容的实测需求低一档（10 磅下
# 内容要 607x788），拖到这一步时先让位的是卡片区——底栏与事件记录区按 side="bottom"
# 先摆，抢在卡片前面占好地方，不会被挤没（实测 560x620 下记录区仍是 8 行、三个按钮
# 一个不少）。不做成「刚好装下内容」是因为最小尺寸按字号等比放、内边距不跟着长：
# 16 磅下等比上来 896x992，比实测的 987x1127 还小不少，再往上调会在字号大时把窗口
# 撑得比内容还高
MIN_SIZE = (560, 620)

# 记下的位置跑到屏幕外时要拉回来多少：至少留这么多像素在工作区里（与弹窗留 24px 同理，
# 这一档给得宽些——主窗口是给人拖来拖去的东西，留一条边看得出是它）
GEOMETRY_KEEP = 80


def visible_geometry(saved, work_area, keep=GEOMETRY_KEEP):
    """上次记下的窗口几何 → 这次可用的（纯函数）：跑到屏幕外的拉回可见区。

    换过显示器、改过分辨率之后，上次的位置可能整个落在工作区外——照搬的话窗口就再也
    找不到了。这里只保证「横向至少 keep 像素留在工作区里、顶边不跑到上边之外」：故意
    摆成半出屏的（贴边看盘）仍然尊重，完全在外的才拉回来。

    saved 认不出（从没记过、或形状不对）时返回 None——调用方照默认位置开窗；
    work_area 拿不到时原样返回，不做判断。返回的形状与 `config.parse_geometry` 认的
    一致，正是 Tk 的 `wm geometry` 能吃的那种。
    """
    parsed = parse_geometry(saved)
    if parsed is None:
        return None
    if not work_area:
        return saved
    width, height, x, y = parsed
    left, top, area_width, area_height = work_area
    x = min(max(x, left - width + keep), left + area_width - keep)
    y = min(max(y, top), top + area_height - keep)
    # 符号由数字自带（`+120`／`-880`）：写成 `+-880` 的话 Tk 不认这串几何
    return f"{width}x{height}{x:+d}{y:+d}"


class MainWindow:
    """常驻行情面板：抬头、两个市场各一张卡片、事件记录区，底部 [打开日志][设置][立即刷新]。

    on_error 是窗口回调里出错时的去处（记进日志）：没有控制台可打印，异常只能这样留底。
    geometry 是上次关窗时记下的位置与大小（编排层已经算好可用的一份，见 visible_geometry）；
    不给就按 Tk 的默认位置开窗。关窗那一刻的位置由 `geometry()` 交回给编排层去记。
    """

    def __init__(
        self, on_refresh, on_settings, on_logs, theme, on_error=None, geometry=None
    ):
        self._view = None  # 最近一帧：换外观时照它重画一次，不必等下一轮刷新
        self._events = None  # 已摆上屏的事件记录：没变就不重画（上屏回调 200ms 跑一次）
        self._closed_at = None  # 关窗那一刻的几何：销毁之后才问就来不及了
        # self._theme 由末尾的 apply() 统一维护：构造与改外观走同一条路，不会两处各写一份
        self._error_reported = False  # 消息框只弹一次（见 _report_callback_error）
        self._reported_errors = set()  # 记过的那几条异常：同一条不重复记
        self._on_error = on_error
        self._root = tk.Tk()
        self._root.title(WINDOW_TITLE)
        self._icon = _window_icon(self._root)  # 留着这个引用：Tk 图像没人引用就没了
        self._root.protocol("WM_DELETE_WINDOW", self._close)
        self._root.report_callback_exception = self._report_callback_error

        self._headline = tk.Label(self._root, text=WINDOW_TITLE, anchor="w")
        self._headline.pack(anchor="w", fill="x", padx=WINDOW_MARGIN, pady=(10, 0))
        self._stamp = tk.Label(self._root, text="", anchor="w")
        self._stamp.pack(anchor="w", fill="x", padx=WINDOW_MARGIN, pady=(2, 6))

        # 从下往上摆底栏与事件记录区（side="bottom"，先摆的先占地方）：pack 里先摆的
        # 先拿到自己要的高度，后摆的（卡片区）在窗口被拖小时先让位——拖小了丢掉几张
        # 行情卡片可以忍，事件记录与那排按钮不能没（见 MIN_SIZE 的说明）
        self._bottom = tk.Frame(self._root)
        self._bottom.pack(side="bottom", fill="x", padx=WINDOW_MARGIN, pady=(0, 10))
        # 提示独占一行（两行高、按窗口宽折行）：与按钮挤一行的话，提示一长就要么被
        # 横着切掉半截、要么把按钮压扁；行高固定，提示来了走了窗口也不跳
        self._notice = tk.Label(
            self._bottom,
            text=STARTUP_NOTICE,
            anchor="w",
            justify="left",
            height=NOTICE_ROWS,
        )
        self._notice.pack(fill="x")
        self._button_row = tk.Frame(self._bottom)
        self._button_row.pack(fill="x")
        self._refresh_button = theme.button(self._button_row, "立即刷新", on_refresh)
        self._refresh_button.pack(side="right")
        self._settings_button = theme.button(self._button_row, "设置", on_settings)
        self._settings_button.pack(side="right", padx=(0, 8))
        self._logs_button = theme.button(self._button_row, "打开日志", on_logs)
        self._logs_button.pack(side="right", padx=(0, 8))

        self._events_frame, self._events_text = self._build_events(theme)

        self._cards = tk.Frame(self._root)
        self._cards.pack(fill="both", expand=True, padx=WINDOW_MARGIN)

        self.apply(theme)
        if geometry:
            # 摆完再给几何：最小尺寸与内容宽度都定下来了，Tk 会把这份几何按它裁一遍
            self._root.geometry(geometry)

    def _build_events(self, theme):
        """事件记录区：只读文本 + 滚动条，摆在卡片与底栏之间。

        用文本区而不是列表：一条故障警告能很长（错误原文照录），列表不折行，
        只会被截掉半截。右下的滚动条管多出来的那些（配色在 `apply` 里整批重涂）。
        """
        frame = tk.LabelFrame(
            self._root,
            text=EVENTS_TITLE,
            bd=1,
            relief="solid",
            labelanchor="nw",
            padx=8,
            pady=6,
        )
        frame.pack(side="bottom", fill="x", padx=WINDOW_MARGIN, pady=(0, 8))
        text = tk.Text(
            frame, width=EVENT_CHARS, height=EVENT_ROWS, wrap="word", state="disabled"
        )
        bar = theme.scrollbar(frame, text.yview)
        text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        return frame, text

    @property
    def root(self):
        """Tk 根窗：弹窗挂靠它、编排层借它排定时回调。"""
        return self._root

    def geometry(self):
        """关窗那一刻的窗口几何（编排层拿去记进配置）；还没关过则是 None。"""
        return self._closed_at

    def apply(self, theme):
        """换一套外观：主窗口当场改观，之后每帧的卡片也照新的画（见 ticket 04）。

        构造时也走这里，省得把样式写两遍。保存设置后由编排层调用。
        """
        self._theme = theme
        self._root.configure(bg=theme.bg)
        # 最小尺寸也跟着字号走（否则保存了更大的字号之后，窗口还能被拖到装不下内容）
        self._root.minsize(*(theme.scaled(side) for side in MIN_SIZE))
        self._root.attributes("-topmost", theme.topmost)
        self._headline.configure(
            bg=theme.bg,
            fg=theme.fg,
            font=theme.font(HEADLINE_STEP, bold=True),
        )
        self._stamp.configure(bg=theme.bg, fg=theme.dim, font=theme.font(STAMP_STEP))
        for frame in (self._cards, self._bottom, self._button_row):
            frame.configure(bg=theme.bg)
        self._notice.configure(
            bg=theme.bg,
            fg=theme.warn,
            font=theme.font(NOTICE_STEP),
            wraplength=theme.scaled(WRAP_AT_BASE),
        )
        self._events_frame.configure(
            bg=theme.bg, fg=theme.dim, font=theme.font(EVENT_STEP, bold=True)
        )
        theme.style_text(self._events_text)
        self._events_text.configure(font=theme.font(EVENT_STEP))
        theme.paint_scrollbar()
        for button in (self._refresh_button, self._settings_button, self._logs_button):
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
        """在底部显示一条提示（配置回退、弹窗失败这类事；它只停到下一帧，见 ticket 05）。"""
        self._notice.configure(text=text)

    def show_events(self, entries):
        """事件记录区：本次运行的近几次触发与故障警告，最新的一条摆在最上面。

        条目文字由 journal 给出——与写进日志的是同一条，这里只负责摆；最新的摆在
        最上面，是因为要看的正是「刚才那声响是什么」（见 User Story 16），不该让人
        先往下滚。没有事件时这里是空的，窗口本来也没什么可看。

        重排之前先看读者停在哪儿：本来就在最上面（或空着）的，跟着新事件走；正在
        往下翻旧账的，把视线留在原处——每来一条就把人拽回顶上，旧的那些就没法看了。
        """
        if entries == self._events:
            return
        self._events = entries
        top = self._events_text.yview()[0]
        self._events_text.configure(state="normal")
        self._events_text.delete("1.0", "end")
        self._events_text.insert("1.0", "\n".join(reversed(entries)))
        self._events_text.configure(state="disabled")
        if top <= 0.0:
            self._events_text.see("1.0")  # 本来就在看最新的：跟着新的走
        else:
            self._events_text.yview_moveto(top)  # 正在往下翻旧账：视线留在原处

    def run(self):
        """进入窗口事件循环；关闭窗口后返回。"""
        self._root.mainloop()

    def _add_card(self, market):
        """一张市场卡片：标题带市场说明，正文逐行按色调摆放，末尾是市场状态。"""
        theme = self._theme
        card = tk.LabelFrame(
            self._cards,
            text=f"{market.name}　{market.detail}",
            bg=theme.bg,
            fg=theme.dim,
            font=theme.font(CARD_TITLE_STEP),
            bd=1,
            relief="solid",
            labelanchor="nw",
            padx=12,
            pady=8,
        )
        card.pack(fill="x", pady=(0, 8))
        for line in market.lines:
            tk.Label(
                card,
                text=line.text,
                bg=theme.bg,
                fg=theme.color(line.tone),
                font=theme.font(
                    PRICE_STEP if line.tone == TONE_PRICE else LINE_STEP,
                    bold=line.tone == TONE_PRICE,
                ),
                anchor="w",
                justify="left",
                wraplength=theme.scaled(WRAP_AT_BASE),
            ).pack(anchor="w", fill="x")
        tk.Label(
            card,
            text=f"状态：{market.status.text}",
            bg=theme.bg,
            fg=theme.color(market.status.tone),
            font=theme.font(STATUS_STEP, bold=True),
            anchor="w",
            justify="left",
            wraplength=theme.scaled(WRAP_AT_BASE),
        ).pack(anchor="w", pady=(4, 0))

    def _close(self):
        """关闭主窗口即退出监视：先记下窗口几何，再销毁根窗（销毁后就问不出来了）。

        最大化时这一趟不更新：那时 `wm geometry` 给的是铺满屏的那一份大小，位置却还是
        最大化之前的——照记下来，下次开窗就是一个比屏幕还大的窗口挂在屏外。留着上次
        正常状态下记的那份（最小化不受影响：Tk 那时给的仍是正常几何，实测过）。
        """
        if self._root.state() == "normal":
            self._closed_at = self._root.geometry()
        self._root.destroy()

    def _report_callback_error(self, exc_type, value, tb):
        """窗口回调里的异常：没有控制台可打印，用系统消息框说明，并记进日志。

        消息框只弹第一次：上屏回调 200ms 跑一次，每次都弹模态框会把人淹在对话框里。
        日志按「哪一条异常」记账——同一条只说一次，换了一条（哪怕前一条还在刷）仍然
        记得下：只留第一次的话，真正不停出错的那条反而没人知道。日志里记的是异常那
        一行（不带调用栈），够看出是哪类错；程序继续跑。
        """
        summary = "".join(traceback.format_exception_only(exc_type, value)).strip()
        if summary not in self._reported_errors:
            self._reported_errors.add(summary)
            if self._on_error is not None:
                self._on_error(f"窗口出错：{summary}")
        if not self._error_reported:
            self._error_reported = True
            show_error_box("".join(traceback.format_exception(exc_type, value, tb)))


def _window_icon(root):
    """把窗口与任务栏的图标换成自己那颗金币（Tk 默认是它自带的羽毛）。

    图是现画的（见 `icon` 模块），不落盘：exe 放在写不进去的目录里也照样有图标。
    换不上就当没这回事——一个图标不该拦住整个窗口。返回值要留着：Tk 图像一旦没人
    引用就被回收，窗口会退回默认图标。

    `iconphoto` 的第一个参数给 True：设置窗口是之后才开的 Toplevel，也要跟着用这个。
    """
    try:
        image = tk.PhotoImage(data=base64.b64encode(icon.png_bytes(ICON_SIZE)))
        root.iconphoto(True, image)
        return image
    except Exception:
        return None


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
