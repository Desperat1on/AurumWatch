# -*- coding: utf-8 -*-
"""设置窗口（Tk）：把可调项摆成控件，只做摆放与交互，判断交回 config 的纯函数。

非模态——与主窗口并排，边看行情边调；[保存] 写回 config.json 并立即生效（见 ticket 03）。
外观组里内嵌 1:1 预览卡片，它调的是弹窗那套绘制函数，改一项立刻重画（见 ticket 04）。
[开机自启] 由 ticket 06 接。
"""

import tkinter as tk
import tkinter.font as tkfont
from tkinter import colorchooser, filedialog, messagebox, ttk

from aurumwatch import popup
from aurumwatch.alerts import DIRECTIONS
from aurumwatch.config import (
    ADVANCED_FIELDS,
    COLOR_FIELDS,
    CUSTOM_SOUND,
    MARKET_CATALOG,
    MAX_BASE_SIZE,
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
from aurumwatch.theme import Theme, contrast_text

WINDOW_TITLE = "设置"
ENTRY_WIDTH = 14
FILE_ENTRY_WIDTH = 26  # 音效文件的路径不短，输入框给宽一点
ERROR_WRAP_AT_BASE = 240  # 红字与提示的折行宽度（像素，按基准字号 10 标定）
PREVIEW_HINT = "以上与真实弹窗是同一套绘制：改任一项，这里立刻变"

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
        self._colors = {}  # 颜色键（bg/fg/rise/fall）→ 色块按钮上的色号
        self._swatches = {}  # 颜色键 → 色块按钮

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
        self._hint(section, row, "留空即停用该方向")

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
        entry = self._entry(row, self._sound_file, width=FILE_ENTRY_WIDTH)
        entry.pack(side="left")
        self._text[SOUND_FILE] = entry
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
        """高级项：刷新节奏、重新武装带、故障警告与启动时的提醒。"""
        section = self._section(parent, "高级")
        for row, field in enumerate(ADVANCED_FIELDS):
            label = f"{field.label}（{field.unit}）" if field.unit else field.label
            self._field_row(section, row, label, field_id("advanced", field.key))
        self._flag_row(
            section, len(ADVANCED_FIELDS), "启动时若已越线立即提醒", STARTUP_FLAG
        )

    def _build_exits(self, parent):
        """三个出口：保存、取消、恢复默认；左边一行留给「保存不成」这类整窗提示。"""
        bottom = tk.Frame(parent, bg=self._theme.bg)
        bottom.pack(fill="x", pady=(12, 0))
        self._notice = tk.Label(
            bottom, text="", bg=self._theme.bg, fg=self._theme.rise,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.wrap(ERROR_WRAP_AT_BASE),
        )
        self._notice.pack(side="left")
        for text, command, pad in (
            ("恢复默认", self.restore_defaults, 0),
            ("取消", self.close, 8),
            ("保存", self.save, 8),
        ):
            self._theme.button(bottom, text, command).pack(side="right", padx=(0, pad))
        return bottom

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
            bg=self._theme.bg, fg=self._theme.fg,
            activebackground=self._theme.bg, activeforeground=self._theme.fg,
            selectcolor=self._theme.field_bg, highlightthickness=0,
            font=self._theme.font(), anchor="w",
        )

    def _flag_row(self, section, row, label, field):
        """一个开关项：勾选框 + 与它同行的红字位（开关本身不会出错，占位对齐而已）。"""
        flag = tk.BooleanVar()
        tk.Checkbutton(
            section, text=label, variable=flag, bg=self._theme.bg,
            fg=self._theme.fg, font=self._theme.font(),
            activebackground=self._theme.bg, activeforeground=self._theme.fg,
            selectcolor=self._theme.field_bg, highlightthickness=0, anchor="w",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self._flags[field] = flag

    def _error_label(self, section, row, field):
        """一个字段的红字位：照着字段标识挂起来，`_show_errors` 知道该把话说在哪。"""
        label = tk.Label(
            section, text="", bg=self._theme.bg, fg=self._theme.rise,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.wrap(ERROR_WRAP_AT_BASE),
        )
        label.grid(row=row, column=2, sticky="w")
        self._errors[field] = label
        return label

    def _hint(self, section, row, text):
        """一组设置下的口头说明。"""
        tk.Label(
            section, text=text, bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.wrap(ERROR_WRAP_AT_BASE),
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))

    def _preview_row(self, parent):
        """1:1 预览：与真实弹窗同一个绘制函数，另配[试弹一次]。"""
        tk.Label(
            parent, text="预览（1:1）", bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(bold=True), anchor="w",
        ).pack(anchor="w")
        self._preview = tk.Frame(parent, bg=self._theme.bg)
        self._preview.pack(anchor="w", pady=(4, 0))
        self._preview_hint = tk.Label(
            parent, text=PREVIEW_HINT, bg=self._theme.bg, fg=self._theme.dim,
            font=self._theme.font(-1), anchor="w", justify="left",
            wraplength=self._theme.wrap(ERROR_WRAP_AT_BASE),
        )
        self._preview_hint.pack(anchor="w", pady=(6, 0))
        self._theme.button(parent, "试弹一次", self.test_popup).pack(
            anchor="w", pady=(6, 0)
        )

    def _style_dropdown(self):
        """下拉框（字体选择）：ttk 默认用系统配色，涂上这套外观才不至于突兀。"""
        style = ttk.Style(self._window)
        if "clam" in style.theme_names():
            style.theme_use("clam")  # vista 主题由系统绘制，颜色配置一概不认
        style.configure(
            "Aurum.TCombobox",
            fieldbackground=self._theme.field_bg,
            background=self._theme.field_bg,
            foreground=self._theme.fg,
            arrowcolor=self._theme.fg,
            selectbackground=self._theme.field_bg,
            selectforeground=self._theme.fg,
            padding=2,
        )
        style.map(
            "Aurum.TCombobox",
            fieldbackground=[("readonly", self._theme.field_bg)],
            foreground=[("readonly", self._theme.fg)],
            background=[("active", self._theme.button_active_bg)],
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
        for field, entry in self._text.items():
            entry.delete(0, "end")
            entry.insert(0, as_text(_field_value(values, field)))
        for field, flag in self._flags.items():
            flag.set(bool(_field_value(values, field)))
        for key, variable in self._colors.items():
            variable.set(values["appearance"][key])
        self._font.set(values["appearance"]["font"])
        self._corner.set(values["appearance"]["popup_corner"])
        self._sound_choice.set(values["sound"]["choice"])
        self._sound_file.set(values["sound"]["file"])
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
            "appearance": {
                **{key: variable.get() for key, variable in self._colors.items()},
                "font": self._font.get(),
                "base_size": self._numbers[BASE_SIZE_FIELD].get(),
                "popup_seconds": self._numbers[POPUP_SECONDS_FIELD].get(),
                "popup_corner": self._corner.get(),
                "topmost": self._flags[TOPMOST_FLAG].get(),
            },
            "advanced": {
                **{
                    field.key: self._text[field_id("advanced", field.key)].get()
                    for field in ADVANCED_FIELDS
                },
                "alert_on_start": self._flags[STARTUP_FLAG].get(),
            },
        }

    def _sound_draft(self):
        """控件上的音效设置：与配置同形的那一份（还没保存）。"""
        return {
            "enabled": self._flags[SOUND_FLAG].get(),
            "choice": self._sound_choice.get(),
            "file": self._sound_file.get().strip(),
        }

    def _draft_theme(self, draft=None):
        """草稿 → 一份可用主题：还没填对的项按默认值算，预览不因此消失。"""
        return Theme.from_appearance(normalize(draft or self._draft())[0]["appearance"])

    def _appearance_errors(self, draft):
        """外观项里还没填对的那些：预览按默认值画，得说明一句。"""
        return {
            field: text
            for field, text in validate(draft).items()
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
            variable.trace_add("write", lambda *_args, key=key: self._paint_swatch(key))
        for variable in self._numbers.values():
            variable.trace_add("write", lambda *_args: self._refresh_preview())
        self._font.trace_add("write", lambda *_args: self._refresh_preview())

    def _refresh_preview(self):
        """按当前（可能还没保存的）外观重画预览卡片——用的就是弹窗那套绘制函数。"""
        draft = self._draft()
        errors = self._appearance_errors(draft)
        for child in self._preview.winfo_children():
            child.destroy()
        self._preview_hint.configure(
            text="；".join(errors.values()) + "（预览暂按默认值画）" if errors else PREVIEW_HINT
        )
        theme = self._draft_theme(draft)
        popup.build_card(
            self._preview, popup.sample_alert(), theme, theme.popup_seconds
        ).pack()

    def _paint_swatch(self, key):
        """把色块涂成当前颜色（色号写在色块上），并顺带重画预览。"""
        code = self._colors[key].get()
        # 手改配置留下的怪值：色块按底色画，红字会说清楚哪儿不对
        color = code if is_color(code) else self._theme.bg
        text = contrast_text(color)
        self._swatches[key].configure(
            text=code, bg=color, fg=text, activebackground=color, activeforeground=text,
        )
        self._refresh_preview()

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
        self._text[SOUND_FILE].configure(state=state)

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
        notice = popup.test_pop(self._draft_theme(), self._sound_draft())
        self._notice.configure(text=notice or "")

    def save(self):
        """[保存]：校验 → 原子落盘 → 立即生效（主窗口与后续弹窗都换新外观）。"""
        values, errors = read_draft(self._draft())
        if errors:
            self._show_errors(errors)
            self._notice.configure(text="有项目还没填对，改好再保存")
            return
        try:
            self._store.save(values)
        except (ConfigError, OSError) as exc:
            self._notice.configure(text=f"保存失败：{exc}")
            return
        self.close()
        if self._on_saved is not None:
            self._on_saved(values)

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
