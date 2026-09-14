# -*- coding: utf-8 -*-
"""设置窗口（Tk）：把可调项摆成控件，只做摆放与交互，判断交回 config 的纯函数。

非模态——与主窗口并排，边看行情边调；[保存] 写回 config.json 并立即生效（见 ticket 03）。
外观组里内嵌 1:1 预览卡片，它调的是弹窗那套绘制函数，改一项立刻重画（见 ticket 04）。
[开机自启] 这一项不在 config.json 里，它落在当前用户的 Run 键上（见 ticket 06 与
`autostart` 模块的说明）：[保存] 时连同配置一起落地，源码运行时置灰。
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

from aurumwatch import autostart, popup
from aurumwatch.alerts import DIRECTIONS
from aurumwatch.config import (
    ADVANCED_FIELDS,
    COLOR_FIELDS,
    CUSTOM_SOUND,
    MARKET_CATALOG,
    MAX_BASE_SIZE,
    MAX_THRESHOLD,
    MAX_POPUP_SECONDS,
    MIN_BASE_SIZE,
    MIN_POPUP_SECONDS,
    POPUP_CORNERS,
    SOUND_CHOICES,
    ConfigError,
    as_text,
    default_values,
    field_id,
    is_color,
    normalize,
    read_draft,
    validate,
)
from aurumwatch.theme import Theme, contrast_text, ttk_style

WINDOW_TITLE = "设置"
ENTRY_WIDTH = 14
FILE_ENTRY_WIDTH = 26  # 音效文件的路径不短，输入框给宽一点
ERROR_WRAP_AT_BASE = 240  # 红字的折行宽度（像素，按基准字号 10 标定）：它挤在输入框右边那一列
HINT_WRAP_AT_BASE = 320  # 组下说明的折行宽度：说明独占一行，宽些才不至于折成四行、行尾只挂一个字
PREVIEW_HINT = "以上与真实弹窗是同一套绘制：改任一项，这里立刻变"
AUTOSTART_HINT = "开机后自动启动本程序（写在当前用户的启动项里）"
AUTOSTART_BLOCKED_HINT = "从源码运行时不可用（不把 Python 路径写进启动项）；打包后可用"

SOUND_FLAG = field_id("sound", "enabled")
SOUND_CHOICE = field_id("sound", "choice")
SOUND_FILE = field_id("sound", "file")
STARTUP_FLAG = field_id("advanced", "alert_on_start")
TOPMOST_FLAG = field_id("appearance", "topmost")
FONT_FIELD = field_id("appearance", "font")
CORNER_FIELD = field_id("appearance", "popup_corner")
BASE_SIZE_FIELD = field_id("appearance", "base_size")
POPUP_SECONDS_FIELD = field_id("appearance", "popup_seconds")

_opened = None  # 同一时刻只开一扇：再点[设置]就把已开的那扇带到前台


def open_settings(parent, store, on_saved=None):
    """打开设置窗口（已开着就带到前台）：非模态，可与主窗口并排。

    窗口照当前生效的外观起——保存之后这扇窗就关了，下次打开自然是新的。
    """
    global _opened
    if _opened is not None and _opened.exists():
        _opened.focus()
        return _opened
    _opened = SettingsWindow(
        parent, store, Theme.from_appearance(store.values["appearance"]), on_saved
    )
    return _opened


class SettingsWindow:
    """设置窗口：阈值、提示音、外观（含预览）、高级四组，出口是[保存][取消][恢复默认]。"""

    def __init__(self, parent, store, theme, on_saved=None):
        self._theme = theme  # 本窗口自己的外观：开着的这段时间不跟着预览变
        self._store = store
        self._on_saved = on_saved
        self._text = {}  # 字段标识 → 文本框（含数字框）
        self._numbers = {}  # 字段标识 → 数字框上的文本变量（外观项要即时反映到预览）
        self._flags = {}  # 字段标识 → 勾选框
        self._errors = {}  # 字段标识 → 红字标签
        self._filling = False  # 是否正在成批填控件（填的过程里不重画预览）
        self._sound_entry = None  # 音效文件那个输入框：不进 _text，见 _build_sound 的说明
        self._colors = {}  # 颜色键（bg/fg/rise/fall）→ 色块按钮上的色号
        self._swatches = {}  # 颜色键 → 色块按钮
        self._traces = []  # [(变量, trace 编号)]：关窗时摘掉，别把窗口扣住
        # [开机自启] 的真身在注册表里，不在 config.json（见 autostart 模块）：开窗时
        # 读一次当「本次改动的起点」，[恢复默认] 回的就是它
        self._autostart_supported = autostart.exe_path() is not None
        self._autostart_open = autostart.enabled() if self._autostart_supported else False

        self._window = tk.Toplevel(parent)
        self._window.title(WINDOW_TITLE)
        self._window.configure(bg=theme.bg)
        self._window.protocol("WM_DELETE_WINDOW", self.close)
        self._window.transient(parent)  # 跟着主窗口：不另占任务栏图标，不会被压到后面
        self._window.bind("<Return>", lambda _event: self.save())
        self._window.bind("<Escape>", lambda _event: self.close())

        self._font = tk.StringVar()
        self._corner = tk.StringVar()
        self._sound_choice = tk.StringVar()
        self._sound_file = tk.StringVar()
        self._style_dropdown()

        body = tk.Frame(self._window, bg=theme.bg, padx=14, pady=12)
        body.pack(fill="both", expand=True)
        columns = tk.Frame(body, bg=theme.bg)
        columns.pack(fill="both", expand=True)
        left = tk.Frame(columns, bg=theme.bg)
        left.pack(side="left", fill="both", expand=True, anchor="n")
        right = tk.Frame(columns, bg=theme.bg)
        right.pack(side="left", fill="both", expand=True, anchor="n", padx=(12, 0))
        self._build_thresholds(left)
        self._build_advanced(left)
        self._build_appearance(right)
        self._build_sound(right)
        self._build_exits(body)
        self._watch_appearance()  # 控件都齐了再接线：见方法上的说明
        self._fill(store.values)

    # —— 控件 ——

    def _build_thresholds(self, parent):
        """阈值：每个市场的涨破、跌破各一个输入框，留空即停用该方向。"""
        section = self._section(parent, "阈值")
        row = 0
        for market in MARKET_CATALOG:
            for direction in DIRECTIONS:
                self._field_row(
                    section, row, f"{market['name']}　{direction.name}",
                    field_id("thresholds", market["code"], direction.config_key),
                )
                row += 1
        self._hint(section, row, f"留空即停用该方向；最大 {as_text(MAX_THRESHOLD)}")

    def _build_sound(self, parent):
        """提示音：开关、系统提示音或自定义 WAV（可[选择…]与[试听]）。"""
        section = self._section(parent, "提示音")
        self._flag_row(section, 0, "触发时播放提示音", SOUND_FLAG)
        self._label(section, 1, "音效")
        holder = self._holder(section, 1)
        for name, text in SOUND_CHOICES:
            self._radio(holder, text, name, self._sound_choice, self._sync_sound_row).pack(
                side="left", padx=(0, 10)
            )
        self._error_label(section, 1, SOUND_CHOICE)

        self._label(section, 2, "文件")
        row = self._holder(section, 2)
        # 这一格不进 _text：它带 textvariable，值由变量直接设（见 _fill），
        # 而且选系统提示音时它是置灰的——Tk 在置灰的输入框上会默默吞掉 delete/insert
        self._sound_entry = self._entry(row, self._sound_file, width=FILE_ENTRY_WIDTH)
        self._sound_entry.pack(side="left")
        self._theme.button(row, "选择…", self.pick_sound_file).pack(
            side="left", padx=(6, 0)
        )
        self._theme.button(row, "试听", self.audition).pack(side="left", padx=(6, 0))
        self._error_label(section, 2, SOUND_FILE)

    def _build_appearance(self, parent):
        """外观：颜色、字体、字号、弹窗停留与位置、主窗口置顶；右边并排 1:1 预览。

        控件与预览并排而不是上下摞：预览卡片是 1:1 的，竖着摞会把窗口撑得比小屏还高。
        """
        section = self._section(parent, "外观")
        holder = tk.Frame(section, bg=self._theme.bg)
        holder.pack(fill="x")
        controls = tk.Frame(holder, bg=self._theme.bg)
        controls.pack(side="left", anchor="n")
        controls.columnconfigure(1, weight=1)
        preview_side = tk.Frame(holder, bg=self._theme.bg)
        preview_side.pack(side="left", anchor="n", padx=(18, 0))

        row = 0
        for key, label in COLOR_FIELDS:
            self._color_row(controls, row, label, key)
            row += 1
        self._font_row(controls, row)
        row += 1
        self._spin_row(
            controls, row, "基准字号（磅）", BASE_SIZE_FIELD, MIN_BASE_SIZE, MAX_BASE_SIZE
        )
        row += 1
        self._spin_row(
            controls, row, "弹窗停留（秒）", POPUP_SECONDS_FIELD,
            MIN_POPUP_SECONDS, MAX_POPUP_SECONDS,
        )
        row += 1
        self._corner_row(controls, row)
        row += 1
        self._flag_row(controls, row, "主窗口置顶", TOPMOST_FLAG)
        row += 1
        self._hint(controls, row, "基准字号定全局：各处的字号都由它派生")
        self._preview_row(preview_side)

    def _build_advanced(self, parent):
        """高级项：刷新节奏、重新武装带、故障警告，与两个启动开关。

        [开机自启] 不进 `_flags`（那儿的字段按配置路径取值）：它不来自 config.json，
        勾也勾不出错值，红字位与 `_draft` 都够不着它。
        """
        section = self._section(parent, "高级")
        for row, field in enumerate(ADVANCED_FIELDS):
            label = f"{field.label}（{field.unit}）" if field.unit else field.label
            self._field_row(section, row, label, field_id("advanced", field.key))
        row = len(ADVANCED_FIELDS)
        self._flag_row(section, row, "启动时若已越线立即提醒", STARTUP_FLAG)
        self._autostart = tk.BooleanVar(value=self._autostart_open)
        self._check_row(
            section, row + 1, "开机自启", self._autostart,
            enabled=self._autostart_supported,
        )
        self._hint(
            section, row + 2,
            AUTOSTART_HINT if self._autostart_supported else AUTOSTART_BLOCKED_HINT,
        )

    def _build_exits(self, parent):
        """三个出口：保存、取消、恢复默认；左边一行留给「保存不成」这类整窗提示。"""
        bottom = tk.Frame(parent, bg=self._theme.bg)
        bottom.pack(fill="x", pady=(12, 0))
        self._notice = tk.Label(
            bottom, text="", bg=self._theme.bg, fg=self._theme.rise,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.scaled(ERROR_WRAP_AT_BASE),
        )
        self._notice.pack(side="left")
        for text, command, pad in (
            ("恢复默认", self.restore_defaults, 0),
            ("取消", self.close, 8),
            ("保存", self.save, 8),
        ):
            self._theme.button(bottom, text, command).pack(side="right", padx=(0, pad))

    def _section(self, parent, title):
        """一组设置：标题框 + 两列网格（名称｜输入框｜红字），输入框那列可拉伸。"""
        section = tk.LabelFrame(
            parent, text=title, bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(bold=True), bd=1, relief="solid",
            labelanchor="nw", padx=12, pady=8,
        )
        section.pack(fill="x", pady=(0, 10))
        section.columnconfigure(1, weight=1)
        return section

    def _label(self, section, row, text):
        tk.Label(
            section, text=text, bg=self._theme.bg, fg=self._theme.fg,
            font=self._theme.font(), anchor="w",
        ).grid(row=row, column=0, sticky="w", pady=2)

    def _holder(self, section, row):
        """一行里放多个控件的容器（单选组、输入框带按钮那种）：仍只占「控件」那一列，
        右边的红字列留给 `_error_label`。"""
        holder = tk.Frame(section, bg=self._theme.bg)
        holder.grid(row=row, column=1, sticky="w", padx=(8, 10), pady=2)
        return holder

    def _entry(self, parent, variable=None, width=ENTRY_WIDTH):
        entry = tk.Entry(
            parent, width=width, font=self._theme.font(), relief="flat",
            **({"textvariable": variable} if variable is not None else {}),
        )
        return self._theme.style_entry(entry)

    def _field_row(self, section, row, label, field):
        """一个数值项：名称、输入框、红字。"""
        self._label(section, row, label)
        entry = self._entry(section)
        entry.grid(row=row, column=1, sticky="w", padx=(8, 10), pady=2)
        self._text[field] = entry
        self._error_label(section, row, field)

    def _spin_row(self, section, row, label, field, low, high):
        """外观组的数值项：名称、带上下箭头的数字框（改了立刻反映到预览）、红字。"""
        self._label(section, row, label)
        variable = tk.StringVar()
        box = tk.Spinbox(
            section, from_=low, to=high, textvariable=variable, width=6, relief="flat",
            font=self._theme.font(), justify="right",
            bg=self._theme.field_bg, fg=self._theme.fg,
            buttonbackground=self._theme.button_active_bg,
            insertbackground=self._theme.fg,
        )
        box.grid(row=row, column=1, sticky="w", padx=(8, 10), pady=2)
        self._text[field] = box
        self._numbers[field] = variable
        self._error_label(section, row, field)

    def _color_row(self, section, row, label, key):
        """一个颜色项：名称、色块（点开系统取色器）、红字。"""
        self._label(section, row, label)
        swatch = tk.Button(
            section, width=10, relief="flat", cursor="hand2",
            font=self._theme.font(),
            # 一圈细边：底色与窗口撞色时（黑底配黑窗），色块才不至于看不见边界
            highlightthickness=1, highlightbackground=self._theme.dim,
            highlightcolor=self._theme.dim,
            command=lambda: self._pick_color(key),
        )
        swatch.grid(row=row, column=1, sticky="w", padx=(8, 10), pady=2)
        self._swatches[key] = swatch
        self._colors[key] = tk.StringVar()
        self._error_label(section, row, field_id("appearance", key))

    def _font_row(self, section, row):
        """字体：从系统装着的字体里挑（挑中的名字 Tk 认不出时它会自动替换）。"""
        self._label(section, row, "字体")
        families = sorted(
            name for name in tkfont.families(self._window) if not name.startswith("@")
        )
        current = self._store.values["appearance"]["font"]
        if current not in families:  # 手改过的配置：名字留着，别在框里凭空消失
            families.insert(0, current)
        box = ttk.Combobox(
            section, textvariable=self._font, values=families, state="readonly",
            width=24, font=self._theme.font(), style="Aurum.TCombobox",
        )
        box.grid(row=row, column=1, sticky="w", padx=(8, 10), pady=2)
        self._error_label(section, row, FONT_FIELD)

    def _corner_row(self, section, row):
        """弹窗位置：主屏四角（默认右下角）。"""
        self._label(section, row, "弹窗位置")
        holder = self._holder(section, row)
        for name, text in POPUP_CORNERS:
            self._radio(holder, text, name, self._corner).pack(side="left", padx=(0, 8))
        self._error_label(section, row, CORNER_FIELD)

    def _radio(self, parent, text, value, variable, command=None):
        """一个单选按钮：底色随窗口，别用系统那套灰底。"""
        return tk.Radiobutton(
            parent, text=text, value=value, variable=variable, command=command,
            **self._toggle_look(),
        )

    def _flag_row(self, section, row, label, field):
        """一个开关项：勾选框 + 与它同行的红字位。

        勾选框自己给不出错值，但校验认的是字段值——别的调用方喂进非布尔时，
        红字得有地方写，否则用户只看到「有项目还没填对」而不知道是哪一行。
        """
        flag = tk.BooleanVar()
        self._check_row(section, row, label, flag)
        self._flags[field] = flag
        self._error_label(section, row, field)

    def _check_row(self, section, row, label, variable, *, enabled=True):
        """一个勾选框（开关项那一行都长这样；`enabled=False` 即置灰不可勾）。

        置灰的那一支（源码运行时的[开机自启]）没有红字位：不是「填错了」，而是
        这一项在本次运行里就不适用，原因由那组底下的说明交代。
        """
        box = tk.Checkbutton(
            section, text=label, variable=variable,
            disabledforeground=self._theme.faint,
            state="normal" if enabled else "disabled",
            **self._toggle_look(),
        )
        box.grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 2))

    def _toggle_look(self):
        """勾选框与单选按钮共用的那几项样式（两者同名同义，只差控件类）。"""
        return {
            "bg": self._theme.bg, "fg": self._theme.fg,
            "activebackground": self._theme.bg, "activeforeground": self._theme.fg,
            "selectcolor": self._theme.field_bg, "highlightthickness": 0,
            "font": self._theme.font(), "anchor": "w",
        }

    def _error_label(self, section, row, field):
        """一个字段的红字位：照着字段标识挂起来，`_show_errors` 知道该把话说在哪。"""
        label = tk.Label(
            section, text="", bg=self._theme.bg, fg=self._theme.rise,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.scaled(ERROR_WRAP_AT_BASE),
        )
        label.grid(row=row, column=2, sticky="w")
        self._errors[field] = label
        return label

    def _hint(self, section, row, text):
        """一组设置下的口头说明（比红字那一列宽：它下面没有别的控件）。"""
        tk.Label(
            section, text=text, bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.scaled(HINT_WRAP_AT_BASE),
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _preview_row(self, parent):
        """1:1 预览：与真实弹窗同一个绘制函数，另配样例切换与[试弹一次]。

        样例有三样（涨破／跌破／故障警告）：三种卡片的取色各不相同，只有一种样例时
        改[跌破色]在预览里看不出动静，而「改任一项即时反映」正是本票的承诺。
        """
        head = tk.Frame(parent, bg=self._theme.bg)
        head.pack(anchor="w")
        tk.Label(
            head, text="预览（1:1）", bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(bold=True), anchor="w",
        ).pack(side="left")
        tk.Label(
            head, text="样例", bg=self._theme.bg, fg=self._theme.fg,
            font=self._theme.font(), anchor="w",
        ).pack(side="left", padx=(12, 4))
        self._sample = tk.StringVar(value=next(iter(popup.SAMPLES)))
        for name in popup.SAMPLES:
            self._radio(head, name, name, self._sample, self._refresh_preview).pack(
                side="left", padx=(0, 6)
            )
        self._preview = tk.Frame(parent, bg=self._theme.bg)
        self._preview.pack(anchor="w", pady=(4, 0))
        self._preview_hint = tk.Label(
            parent, text=PREVIEW_HINT, bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.scaled(HINT_WRAP_AT_BASE),  # 说明那一档宽度（见 _hint）
        )
        self._preview_hint.pack(anchor="w", pady=(6, 0))
        self._theme.button(parent, "试弹一次", self.test_popup).pack(
            anchor="w", pady=(6, 0)
        )

    def _style_dropdown(self):
        """下拉框（字体选择）：ttk 默认用系统配色，涂上这套外观才不至于突兀。"""
        style = ttk_style(self._window)  # 与主窗口的滚动条同一条规矩：主题切到 clam
        # clam 自带一圈浅灰描边，深色外观下格外扎眼，一并换掉
        style.configure(
            "Aurum.TCombobox",
            fieldbackground=self._theme.field_bg,
            background=self._theme.field_bg,
            foreground=self._theme.fg,
            arrowcolor=self._theme.fg,
            bordercolor=self._theme.field_bg,
            lightcolor=self._theme.field_bg,
            darkcolor=self._theme.field_bg,
            padding=2,
        )
        # 选中底色只能走 map：它不在 configure 能落的元素选项里（挡着不改会留一抹浅灰）
        style.map(
            "Aurum.TCombobox",
            fieldbackground=[("readonly", self._theme.field_bg)],
            foreground=[("readonly", self._theme.fg)],
            background=[("active", self._theme.button_active_bg)],
            selectbackground=[("readonly", self._theme.button_active_bg)],
            selectforeground=[("readonly", self._theme.fg)],
        )
        # 展开后的候选列表是另一个窗口，颜色得单独交代
        for option, color in (
            ("background", self._theme.field_bg),
            ("foreground", self._theme.fg),
            ("selectBackground", self._theme.button_active_bg),
            ("selectForeground", self._theme.fg),
        ):
            self._window.option_add(f"*TCombobox*Listbox.{option}", color)

    # —— 数据 ——

    def _fill(self, values):
        """按一份配置填一遍控件（打开时、[恢复默认]时各来一次）。"""
        self._filling = True  # 填的过程里别一次次重画预览，填完再画（见 _appearance_changed）
        try:
            for field, entry in self._text.items():
                entry.delete(0, "end")
                entry.insert(0, as_text(_field_value(values, field)))
            for field, flag in self._flags.items():
                flag.set(bool(_field_value(values, field)))
            # [开机自启] 的「默认」就是开窗时的实际状态：它由注册表说了算，没有
            # 一个「默认该不该自启」可言——[恢复默认] 只该丢下本次未保存的改动
            self._autostart.set(self._autostart_open)
            for key, variable in self._colors.items():
                variable.set(values["appearance"][key])
            self._font.set(values["appearance"]["font"])
            self._corner.set(values["appearance"]["popup_corner"])
            self._sound_choice.set(values["sound"]["choice"])
            self._sound_file.set(values["sound"]["file"])  # 上面那圈到不了它（见 _sound_entry）
        finally:
            # 半路抛错也要把门闩放下：留着它，预览从此不再刷新，还没人知道
            self._filling = False
        self._sync_sound_row()
        self._show_errors({})
        self._notice.configure(text="")
        self._refresh_preview()

    def _draft(self):
        """控件 → 草稿：与配置文件同形，数值是输入框里的文本（留空即停用）。"""
        return {
            "thresholds": {
                market["code"]: {
                    direction.config_key: self._text[
                        field_id("thresholds", market["code"], direction.config_key)
                    ].get()
                    for direction in DIRECTIONS
                }
                for market in MARKET_CATALOG
            },
            "sound": self._sound_draft(),
            "appearance": self._appearance_draft(),
            "advanced": {
                **{
                    field.key: self._text[field_id("advanced", field.key)].get()
                    for field in ADVANCED_FIELDS
                },
                "alert_on_start": self._flags[STARTUP_FLAG].get(),
            },
        }

    def _appearance_draft(self):
        """控件上的外观段：预览与[试弹一次]只认这一段，不必把整份配置重走一遍。"""
        return {
            **{key: variable.get() for key, variable in self._colors.items()},
            "font": self._font.get(),
            "base_size": self._numbers[BASE_SIZE_FIELD].get(),
            "popup_seconds": self._numbers[POPUP_SECONDS_FIELD].get(),
            "popup_corner": self._corner.get(),
            "topmost": self._flags[TOPMOST_FLAG].get(),
        }

    def _sound_draft(self):
        """控件上的音效设置：与配置同形的那一份（还没保存）。"""
        return {
            "enabled": self._flags[SOUND_FLAG].get(),
            "choice": self._sound_choice.get(),
            "file": self._sound_file.get().strip(),
        }

    def _draft_theme(self, appearance=None):
        """外观草稿 → 一份可用主题：还没填对的项按默认值算，预览不因此消失。"""
        draft = {"appearance": appearance if appearance is not None else self._appearance_draft()}
        return Theme.from_appearance(normalize(draft)[0]["appearance"])

    def _appearance_errors(self, appearance):
        """外观项里还没填对的那些：预览按默认值画，得说明一句。"""
        return {
            field: text
            for field, text in validate({"appearance": appearance}).items()
            if field.startswith("appearance.")
        }

    def _show_errors(self, errors):
        """把校验结果挂到对应字段上：错的红字，其余清空。"""
        for field, label in self._errors.items():
            label.configure(text=errors.get(field, ""))

    # —— 外观组的即时反馈 ——

    def _watch_appearance(self):
        """线接上：外观控件一动就重画预览。

        要等全部控件建好再挂——Spinbox 一造出来就会往变量里写一次，那时预览还没建，
        挂早了就会扑空。字号/字体/颜色都是这么回事，跟用户改没改无关。
        """
        for key, variable in self._colors.items():
            self._trace(variable, lambda *_args, key=key: self._paint_swatch(key))
        for variable in self._numbers.values():
            self._trace(variable, lambda *_args: self._appearance_changed())
        self._trace(self._font, lambda *_args: self._appearance_changed())
        self._trace(self._sample, lambda *_args: self._refresh_preview())

    def _trace(self, variable, callback):
        """挂一条 trace 并记下它的编号：关窗时要挨个摘掉（见 _unwatch_appearance）。"""
        self._traces.append((variable, variable.trace_add("write", callback)))

    def _unwatch_appearance(self):
        """摘掉外观控件上的 trace。

        变量挂在根解释器上，活得比这扇窗久；trace 又握着这里的 lambda（进而握着整扇
        窗），不摘的话开一次设置就留一份控件树，谁也不回收。
        """
        for variable, identifier in self._traces:
            variable.trace_remove("write", identifier)
        self._traces.clear()

    def _refresh_preview(self):
        """按当前（可能还没保存的）外观重画预览卡片——用的就是弹窗那套绘制函数。"""
        appearance = self._appearance_draft()
        errors = self._appearance_errors(appearance)
        for child in self._preview.winfo_children():
            child.destroy()
        self._preview_hint.configure(
            text="；".join(errors.values()) + "（预览暂按默认值画）" if errors else PREVIEW_HINT
        )
        theme = self._draft_theme(appearance)
        popup.build_card(self._preview, self._sample_event(), theme).pack()

    def _sample_event(self):
        """当前选中的样例提醒（预览与[试弹一次]弹的是同一张卡）。"""
        return popup.SAMPLES[self._sample.get()]()

    def _appearance_changed(self):
        """外观控件动了：[填控件]时先不画，填完一次画好——开窗与[恢复默认]各要填十来个。"""
        if not self._filling:
            self._refresh_preview()

    def _paint_swatch(self, key):
        """把色块涂成当前颜色（色号写在色块上），并顺带重画预览。"""
        code = self._colors[key].get()
        # 手改配置留下的怪值：色块按底色画，红字会说清楚哪儿不对
        color = code if is_color(code) else self._theme.bg
        text = contrast_text(color)
        self._swatches[key].configure(
            text=code, bg=color, fg=text, activebackground=color, activeforeground=text,
        )
        self._appearance_changed()

    def _pick_color(self, key):
        """点色块开系统取色器；[取消]即不改动。"""
        _, chosen = colorchooser.askcolor(
            color=self._colors[key].get(), parent=self._window, title="选择颜色"
        )
        if chosen:
            self._colors[key].set(chosen)

    def _sync_sound_row(self):
        """选了系统提示音就把文件那行置灰：免得对着用不上的输入框发愣。"""
        state = "normal" if self._sound_choice.get() == CUSTOM_SOUND else "disabled"
        self._sound_entry.configure(state=state)

    # —— 出口 ——

    def pick_sound_file(self):
        """[选择…]：挑一个 WAV 文件（winsound 只放 WAV，所以只列 WAV）。"""
        chosen = filedialog.askopenfilename(
            parent=self._window, title="选择提示音文件",
            filetypes=(("WAV 音频", "*.wav"), ("所有文件", "*.*")),
        )
        if not chosen:
            return
        self._sound_choice.set(CUSTOM_SOUND)  # 挑了文件就是要用它
        self._sound_file.set(chosen)
        self._sync_sound_row()
        self._notice.configure(text="")

    def audition(self):
        """[试听]：按当前选择出一声；文件放不出来就说一句并退回系统提示音。"""
        self._notice.configure(text=popup.play_sound(self._sound_draft()) or "")

    def test_popup(self):
        """[试弹一次]：按当前（尚未保存的）外观弹一个真实弹窗，并照当前音效出一声。"""
        notice = popup.test_pop(
            self._draft_theme(), self._sample_event(), self._sound_draft()
        )
        self._notice.configure(text=notice or "")

    def save(self):
        """[保存]：校验 → 落开机自启 → 原子落盘 → 立即生效（主窗口与后续弹窗都换新外观）。

        开机自启先落：设不成（权限等）就整笔不保存、窗口留着把原因说清楚——配置写
        进去了、注册表没写成的话，用户得猜是哪一半生效了。反过来的一头（注册表落
        下了、配置写失败）没法回滚，那就如实写在红字里：这一勾是真的生效了。
        """
        values, errors = read_draft(self._draft())
        if errors:
            self._show_errors(errors)
            self._notice.configure(text="有项目还没填对，改好再保存")
            return
        try:
            self._apply_autostart()
        except (OSError, ValueError) as exc:
            reason = getattr(exc, "strerror", None) or exc
            self._notice.configure(text=f"开机自启没设成：{reason}；设置未保存")
            return
        try:
            self._store.save(values)
        except (ConfigError, OSError) as exc:
            note = "（开机自启已改）" if self._autostart.get() != self._autostart_open else ""
            self._notice.configure(text=f"保存失败：{exc}{note}")
            return
        self.close()
        if self._on_saved is not None:
            self._on_saved(values)

    def _apply_autostart(self):
        """把[开机自启]那一勾落到注册表（从源码运行时那一项本就是灰的，不碰）。"""
        if not self._autostart_supported:
            return
        autostart.set_enabled(self._autostart.get())

    def restore_defaults(self):
        """[恢复默认]：二次确认后把控件填回默认值（还没写盘，反悔就[取消]）。"""
        if not messagebox.askyesno(
            WINDOW_TITLE,
            "恢复默认会丢弃这次改的全部内容（尚未写进配置文件）。要继续吗？",
            parent=self._window,
        ):
            return
        self._fill(default_values())

    def close(self):
        """关窗：非模态，主窗口照常监视。"""
        global _opened
        _opened = None
        self._unwatch_appearance()
        self._window.destroy()

    # —— 窗口本身 ——

    def focus(self):
        """把已开着的这扇带到前台。"""
        self._window.deiconify()
        self._window.lift()
        self._window.focus_force()

    def exists(self):
        """还在不在（主窗口一关，整棵树都没了）。"""
        try:
            return bool(self._window.winfo_exists())
        except tk.TclError:
            return False


def _field_value(values, field):
    """按字段标识（就是配置里的路径）取出当前值。"""
    node = values
    for part in field.split("."):
        node = node[part]
    return node
