# -*- coding: utf-8 -*-
"""设置窗口（Tk）：把可调项摆成控件，只做摆放与交互，判断交回 config 的纯函数。

非模态——与主窗口并排，边看行情边调；[保存] 写回 config.json 并立即生效（见 ticket 03）。
外观、试弹与音效选择由 ticket 04 接进同一扇窗，[开机自启] 由 ticket 06 接。
"""

import tkinter as tk
from tkinter import messagebox

from aurumwatch import theme
from aurumwatch.alerts import DIRECTIONS
from aurumwatch.config import (
    ADVANCED_FIELDS,
    MARKET_CATALOG,
    ConfigError,
    as_text,
    default_values,
    field_id,
    read_draft,
)
from aurumwatch.theme import BG, DIM, FG, FIELD_BG, RISE as ERROR

WINDOW_TITLE = "设置"
FONT = theme.FONT
SECTION_FONT = (FONT, 10, "bold")
FIELD_FONT = (FONT, 10)
HINT_FONT = (FONT, 9)
ENTRY_WIDTH = 14
ERROR_WRAP = 240  # 红字与提示的折行宽度（像素）：长了换行，不把窗口撑宽

SOUND_FLAG = field_id("sound", "enabled")
STARTUP_FLAG = field_id("advanced", "alert_on_start")

_opened = None  # 同一时刻只开一扇：再点[设置]就把已开的那扇带到前台


def open_settings(parent, store, on_saved=None):
    """打开设置窗口（已开着就带到前台）：非模态，可与主窗口并排。"""
    global _opened
    if _opened is not None and _opened.exists():
        _opened.focus()
        return _opened
    _opened = SettingsWindow(parent, store, on_saved)
    return _opened


class SettingsWindow:
    """设置窗口：阈值、提示音、高级项三组，出口是[保存][取消][恢复默认]。"""

    def __init__(self, parent, store, on_saved=None):
        self._store = store
        self._on_saved = on_saved
        self._text = {}  # 字段标识 → 文本框
        self._flags = {}  # 字段标识 → 勾选框
        self._errors = {}  # 字段标识 → 红字标签

        self._window = tk.Toplevel(parent)
        self._window.title(WINDOW_TITLE)
        self._window.configure(bg=BG)
        self._window.protocol("WM_DELETE_WINDOW", self.close)
        self._window.transient(parent)  # 跟着主窗口：不另占任务栏图标，不会被压到后面
        self._window.bind("<Return>", lambda _event: self.save())
        self._window.bind("<Escape>", lambda _event: self.close())

        body = tk.Frame(self._window, bg=BG, padx=14, pady=12)
        body.pack(fill="both", expand=True)
        self._build_thresholds(body)
        self._build_sound(body)
        self._build_advanced(body)
        self._build_exits(body)
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
        """提示音：触发时是否出一声（关掉只留弹窗）。"""
        section = self._section(parent, "提示音")
        self._flag_row(section, 0, "触发时播放提示音", SOUND_FLAG)

    def _build_advanced(self, parent):
        """高级项：刷新节奏、重新武装带、故障警告与启动时的提醒。"""
        section = self._section(parent, "高级")
        for row, field in enumerate(ADVANCED_FIELDS):
            label = f"{field.label}（{field.unit}）" if field.unit else field.label
            self._field_row(section, row, label, field_id("advanced", field.key))
        self._flag_row(
            section,
            len(ADVANCED_FIELDS),
            "启动时若已越线立即提醒",
            STARTUP_FLAG,
        )

    def _build_exits(self, parent):
        """三个出口：保存、取消、恢复默认；左边一行留给「保存不成」这类整窗提示。"""
        bottom = tk.Frame(parent, bg=BG)
        bottom.pack(fill="x", pady=(12, 0))
        self._notice = tk.Label(
            bottom, text="", bg=BG, fg=ERROR, font=HINT_FONT, anchor="w",
            justify="left", wraplength=ERROR_WRAP,
        )
        self._notice.pack(side="left")
        theme.button(bottom, "恢复默认", self.restore_defaults).pack(side="right")
        theme.button(bottom, "取消", self.close).pack(side="right", padx=(0, 8))
        theme.button(bottom, "保存", self.save).pack(side="right", padx=(0, 8))

    def _section(self, parent, title):
        """一组设置：标题框 + 两列网格（名称｜输入框｜红字），输入框那列可拉伸。"""
        section = tk.LabelFrame(
            parent, text=title, bg=BG, fg=DIM, font=SECTION_FONT, bd=1,
            relief="solid", labelanchor="nw", padx=12, pady=8,
        )
        section.pack(fill="x", pady=(0, 10))
        section.columnconfigure(1, weight=1)
        return section

    def _field_row(self, section, row, label, field):
        """一个数值项：名称、输入框、红字。"""
        tk.Label(section, text=label, bg=BG, fg=FG, font=FIELD_FONT, anchor="w").grid(
            row=row, column=0, sticky="w", pady=2
        )
        entry = tk.Entry(
            section, width=ENTRY_WIDTH, bg=FIELD_BG, fg=FG, insertbackground=FG,
            font=FIELD_FONT, relief="flat",
        )
        entry.grid(row=row, column=1, sticky="w", padx=(8, 10), pady=2)
        self._text[field] = entry
        self._errors[field] = self._error_label(section, row)

    def _flag_row(self, section, row, label, field):
        """一个开关项：勾选框 + 与它同行的红字位（开关本身不会出错，占位对齐而已）。"""
        flag = tk.BooleanVar()
        tk.Checkbutton(
            section, text=label, variable=flag, bg=BG, fg=FG, font=FIELD_FONT,
            activebackground=BG, activeforeground=FG, selectcolor=FIELD_BG,
            highlightthickness=0, anchor="w",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(4, 2))
        self._flags[field] = flag

    def _error_label(self, section, row):
        label = tk.Label(
            section, text="", bg=BG, fg=ERROR, font=HINT_FONT, anchor="w",
            justify="left", wraplength=ERROR_WRAP,
        )
        label.grid(row=row, column=2, sticky="w")
        return label

    def _hint(self, section, row, text):
        """一组设置下的口头说明。"""
        tk.Label(
            section, text=text, bg=BG, fg=DIM, font=HINT_FONT, anchor="w",
            justify="left", wraplength=ERROR_WRAP,
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 0))

    # —— 数据 ——

    def _fill(self, values):
        """按一份配置填一遍控件（打开时、[恢复默认]时各来一次）。"""
        for field, entry in self._text.items():
            entry.delete(0, "end")
            entry.insert(0, as_text(_field_value(values, field)))
        for field, flag in self._flags.items():
            flag.set(bool(_field_value(values, field)))
        self._show_errors({})
        self._notice.configure(text="")

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
            "sound": {"enabled": self._flags[SOUND_FLAG].get()},
            "advanced": {
                **{
                    field.key: self._text[field_id("advanced", field.key)].get()
                    for field in ADVANCED_FIELDS
                },
                "alert_on_start": self._flags[STARTUP_FLAG].get(),
            },
        }

    def _show_errors(self, errors):
        """把校验结果挂到对应字段上：错的红字，其余清空。"""
        for field, label in self._errors.items():
            label.configure(text=errors.get(field, ""))

    # —— 出口 ——

    def save(self):
        """[保存]：校验 → 原子落盘 → 立即生效（轮询线程下一轮就用新配置）。"""
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
