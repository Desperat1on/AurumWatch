# -*- coding: utf-8 -*-
"""配置（纯函数层）：默认值、数据形状、规范化、校验、读写与原子落盘。

可调项只存在于 exe／仓库同目录的 `config.json` 与设置窗口，源码里没有配置区
（见 ticket 03）。数值一律用 Decimal 承载，950.00 就是 950.00——JSON 没有小数
类型，写文件时小数按字面量写成字符串，读文件时字符串与数字都认。
"""

import json
import locale
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aurumwatch.alerts import DIRECTIONS

CONFIG_NAME = "config.json"
BACKUP_NAME = "config.json.bak"
TEMP_SUFFIX = ".tmp"

# 刷新间隔的上下限（秒）：下限再密就是对数据源的硬碰，也会把「下次刷新」倒计时搅得
# 没法看；上限一小时——再长就不算「盯着行情」了，而「整分对齐」的算法也只在小时以内
# 自洽。上限不是审美问题：这些数会喂给 `Event.wait()` 与 `timedelta()`，天文数字会让
# 取数线程带着异常死掉（没有控制台，谁也不知道监视已经不在了）。
MIN_REFRESH_INTERVAL = 5
MAX_REFRESH_INTERVAL = 3600

# 故障警告时长的上限（分钟）：一天。再长等于「等你想起来看的时候黄花菜都凉了」
MAX_FAILURE_WARN_MINUTES = 24 * 60

# 外观的取值边界：基准字号 8 磅起（再小，派生出来的小字就没法看）、20 磅止。
# 20 磅这个上限是设置窗口定的：组里嵌着 1:1 的预览卡片，窗口宽度随字号一起长，
# 24 磅时量下来已到 1924 逻辑像素，超出常见屏幕（20 磅约 1633，1080p 屏放得下）。
# 弹窗停留 3 秒起（再短来不及看清）、600 秒止（再长等于不消失）。字号与秒数只收
# 整数——半磅字没法看，半秒也没意义。
MIN_BASE_SIZE, MAX_BASE_SIZE = 8, 20
MIN_POPUP_SECONDS, MAX_POPUP_SECONDS = 3, 600

# 弹窗位置：屏幕四角，配置里存英文键、界面上显示中文（见 CONTEXT.md「弹窗」）
POPUP_CORNERS = (
    ("bottom-right", "右下角"),
    ("bottom-left", "左下角"),
    ("top-right", "右上角"),
    ("top-left", "左上角"),
)
CORNER_NAMES = tuple(name for name, _ in POPUP_CORNERS)
CORNER_TEXT = "、".join(text for _, text in POPUP_CORNERS)

# 颜色项：用户可调的四个颜色，值一律 #RRGGBB
COLOR_FIELDS = (
    ("bg", "背景色"),
    ("fg", "文字色"),
    ("rise", "涨破色"),
    ("fall", "跌破色"),
)
COLOR_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")

# 音效：系统提示音，或一个自定义 WAV 文件（winsound 只认 WAV）
SYSTEM_SOUND = "system"
CUSTOM_SOUND = "custom"
SOUND_CHOICES = ((SYSTEM_SOUND, "系统提示音"), (CUSTOM_SOUND, "自定义 WAV 文件"))
SOUND_NAMES = tuple(name for name, _ in SOUND_CHOICES)
WAV_SUFFIX = ".wav"

# 开关项：字段名与中文说法。规范化（认不出就回退默认）与校验（不是布尔不许保存）
# 共用一份，免得两边走偏（见 _flag_errors 的说明）。
SOUND_FLAGS = (("enabled", "提示音开关"),)
APPEARANCE_FLAGS = (("topmost", "主窗口置顶"),)
ADVANCED_FLAGS = (("alert_on_start", "启动时若已越线立即提醒"),)


@dataclass(frozen=True)
class NumberField:
    """一个数值项：配置键、中文名与取值要求（高级项与外观项的数值共用）。

    规范化（越界回退默认值）与校验（越界不许保存）共用同一份要求，免得两边走偏。
    """

    key: str
    label: str
    unit: str  # 设置窗口挂在名称后的单位，如「刷新间隔（秒）」
    hint: str  # 要求的中文说法，如「不小于 5 的整数秒」
    integer_only: bool  # 是否只收整数
    allowed: Callable[[Decimal], bool]  # 取值是否在范围内


ADVANCED_FIELDS = (
    NumberField(
        "refresh_interval", "刷新间隔", "秒",
        f"{MIN_REFRESH_INTERVAL} 到 {MAX_REFRESH_INTERVAL} 之间的整数秒",
        True, lambda number: MIN_REFRESH_INTERVAL <= number <= MAX_REFRESH_INTERVAL,
    ),
    NumberField(
        "rearm_ratio", "重新武装带比例", "", "0 与 1 之间的小数（例：0.001）",
        False, lambda number: 0 < number < 1,
    ),
    NumberField(
        "failure_warn_minutes", "故障警告时长", "分钟",
        f"1 到 {MAX_FAILURE_WARN_MINUTES} 之间的整数分钟",
        True, lambda number: 1 <= number <= MAX_FAILURE_WARN_MINUTES,
    ),
)

# 外观组的数值项：字号与弹窗停留（配色、字体、四角、置顶另按各自的形状读）
APPEARANCE_NUMBERS = (
    NumberField(
        "base_size", "基准字号", "磅",
        f"{MIN_BASE_SIZE} 到 {MAX_BASE_SIZE} 磅之间的整数",
        True, lambda number: MIN_BASE_SIZE <= number <= MAX_BASE_SIZE,
    ),
    NumberField(
        "popup_seconds", "弹窗停留", "秒",
        f"{MIN_POPUP_SECONDS} 到 {MAX_POPUP_SECONDS} 之间的整数秒",
        True, lambda number: MIN_POPUP_SECONDS <= number <= MAX_POPUP_SECONDS,
    ),
)

# 两个市场的固定身份：名称、说明、单位与行情代码不可调，阈值来自配置
MARKET_CATALOG = (
    {
        "name": "国内金价",
        "detail": "沪金99（上海黄金交易所 Au99.99）",
        "unit": "元/克",
        "code": "gds_AU9999",
    },
    {
        "name": "国际金价",
        "detail": "伦敦金（XAU/USD 现货黄金）",
        "unit": "美元/盎司",
        "code": "hf_XAU",
    },
)


def default_values():
    """内置默认配置（新的一份，可随意改）：阈值一律留空，其余沿用控制台版的默认值。"""
    return {
        "thresholds": {
            market["code"]: {direction.config_key: None for direction in DIRECTIONS}
            for market in MARKET_CATALOG
        },
        "sound": {"enabled": True, "choice": SYSTEM_SOUND, "file": ""},
        # 外观：用户只调这几项，其余颜色由主题按它们派生（见 theme.py）
        "appearance": {
            "bg": "#1e1f22",
            "fg": "#f0f0f0",
            "rise": "#e5534b",
            "fall": "#3fb950",
            "font": "Microsoft YaHei UI",
            "base_size": 10,
            "popup_seconds": 30,
            "popup_corner": "bottom-right",
            "topmost": False,
        },
        "advanced": {
            "refresh_interval": 60,
            "rearm_ratio": Decimal("0.001"),
            "failure_warn_minutes": 10,
            "alert_on_start": True,
        },
    }


def markets(values):
    """两个市场的完整定义：身份取自固定目录、阈值取自配置（判定与视图模型都用这个）。"""
    return tuple(
        {**market, **values["thresholds"][market["code"]]} for market in MARKET_CATALOG
    )


def parse_decimal(text):
    """数字项 → Decimal；留空（None、空串）→ None，认不出或非有限数抛 ValueError。

    读文件与读设置窗口的输入框都走这里：两种来源的容错口径一致（950.00 就是 950.00）。
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    try:
        number = Decimal(text)
    except (ArithmeticError, ValueError, TypeError):
        raise ValueError(f"不是数字：{text!r}") from None
    if not number.is_finite():  # NaN／Infinity 能通过 Decimal()，但对阈值没有意义
        raise ValueError(f"不是有限数字：{text!r}")
    return number


def normalize(raw):
    """把读到的原始配置（缺字段、坏值都可能）化成一份可用配置（纯函数）。

    → (配置值, 说明)：缺失的字段与坏值一律回退默认值；说明是给用户看的中文短句，
    坏值点名到字段，缺字段不啰嗦。整份文件都读不出来的情形由 `load` 处理。
    """
    values = default_values()
    notices = []
    raw = _as_dict(raw)
    _read_thresholds(_as_dict(raw.get("thresholds")), values["thresholds"], notices)
    _read_sound(_as_dict(raw.get("sound")), values["sound"], notices)
    _read_appearance(_as_dict(raw.get("appearance")), values["appearance"], notices)
    _read_advanced(_as_dict(raw.get("advanced")), values["advanced"], notices)
    return values, tuple(notices)


def _as_dict(value):
    """一份配置或一段配置：缺了、不是字典（写坏了），都当空的一份。"""
    return value if isinstance(value, dict) else {}


def _read_thresholds(raw, values, notices):
    """阈值段：每个市场的每个方向各读各的，坏值只停用那一项，不牵连别人。"""
    for market in MARKET_CATALOG:
        given = _as_dict(raw.get(market["code"]))
        for direction in DIRECTIONS:
            raw_value = given.get(direction.config_key)
            if raw_value is None:
                continue  # 没填：保持默认的「留空即停用」
            try:
                number = parse_decimal(raw_value)
            except ValueError:
                notices.append(
                    f"{market['name']}{direction.name}阈值不是数字，已按停用处理"
                )
                continue
            if number is None:
                continue  # 空串与留空同义
            if number <= 0:
                notices.append(
                    f"{market['name']}{direction.name}阈值须为正数，已按停用处理"
                )
                continue
            values[market["code"]][direction.config_key] = number


def _read_flags(raw, values, notices, fields):
    """开关项：只认真正的布尔，认不出的写法回退默认值并说明。"""
    for key, label in fields:
        raw_value = raw.get(key)
        if raw_value is None:
            continue
        if not isinstance(raw_value, bool):
            notices.append(f"{label}只能是 true 或 false，已按默认值处理")
            continue
        values[key] = raw_value


def _flag_errors(errors, section, given, fields):
    """开关项的校验：不是布尔的挂到对应字段上（缺这一项不算错，按默认值走）。

    与 `_read_flags` 同用一份字段表：这两边口径分叉过一次——`validate` 放行的
    非布尔开关，`normalize` 读回来会当成坏值回退，等于存了个自己都不认的配置。
    """
    for key, label in fields:
        value = given.get(key)
        if value is not None and not isinstance(value, bool):
            errors[field_id(section, key)] = f"{label}只能是 true 或 false"


def _read_numbers(raw, values, notices, fields):
    """一组数值项：读不出的、不合要求的都回退默认值并说明。"""
    for field in fields:
        raw_value = raw.get(field.key)
        if raw_value is None:
            continue
        if _number_ok(field, raw_value):
            number = parse_decimal(raw_value)
            values[field.key] = int(number) if field.integer_only else number
            continue
        notices.append(
            f"{field.label}须为{field.hint}，"
            f"已按默认值 {as_text(values[field.key])} 处理"
        )


def _read_advanced(raw, values, notices):
    """高级项：读不出的、不合要求的都回退默认值并说明。"""
    _read_numbers(raw, values, notices, ADVANCED_FIELDS)
    _read_flags(raw, values, notices, ADVANCED_FLAGS)


def _read_sound(raw, values, notices):
    """提示音段：开关、音效选择与 WAV 路径。

    自定义音效必须落在一个 .wav 路径上（winsound 只放 WAV）：路径读不出、或不是
    .wav 时，整条设定退回系统提示音。路径留着——好让人回来改，而不是对着空白框发呆。
    """
    _read_flags(raw, values, notices, SOUND_FLAGS)
    choice = raw.get("choice")
    if choice is not None:
        if choice in SOUND_NAMES:
            values["choice"] = choice
        else:
            notices.append("音效只能选系统提示音或自定义 WAV 文件，已改用系统提示音")
    path = raw.get("file")
    if isinstance(path, str):
        values["file"] = path.strip()
    elif path is not None:
        values["file"] = ""  # 不是文本就没什么可留的
    if values["choice"] == CUSTOM_SOUND and not is_wav(values["file"]):
        notices.append("自定义音效须是 .wav 文件，本次改用系统提示音")
        values["choice"] = SYSTEM_SOUND


def _read_appearance(raw, values, notices):
    """外观段：颜色认 #RRGGBB、字体认非空名称、字号与秒数认范围内的整数、
    位置认四角之一、置顶认布尔。坏值只废掉那一项，其余照用。"""
    for key, label in COLOR_FIELDS:
        given = raw.get(key)
        if given is None:
            continue
        if is_color(given):
            values[key] = given.strip()
        else:
            notices.append(
                f"{label}须是 #RRGGBB 形式的颜色（例：{values[key]}），已按默认值处理"
            )
    font = raw.get("font")
    if font is not None:
        if isinstance(font, str) and font.strip():
            values["font"] = font.strip()
        else:
            notices.append(f"字体须是字体名称（例：{values['font']}），已按默认值处理")
    _read_numbers(raw, values, notices, APPEARANCE_NUMBERS)
    corner = raw.get("popup_corner")
    if corner is not None:
        if corner in CORNER_NAMES:
            values["popup_corner"] = corner
        else:
            notices.append(
                f"弹窗位置须是{CORNER_TEXT}之一，已按{corner_text(values['popup_corner'])}处理"
            )
    _read_flags(raw, values, notices, APPEARANCE_FLAGS)


def is_color(text):
    """是不是 #RRGGBB 形式的颜色（设置窗口的取色器只出这种写法）。"""
    return isinstance(text, str) and COLOR_PATTERN.fullmatch(text.strip()) is not None


def is_wav(path):
    """是不是 .wav 文件路径（大小写不论）。文件在不在是运行期的事，这里只看名字。"""
    return isinstance(path, str) and path.strip().lower().endswith(WAV_SUFFIX)


def corner_text(name):
    """四角配置键 → 界面上的中文说法。"""
    return dict(POPUP_CORNERS).get(name, name)


def _is_whole(number):
    """是不是整数（60 与 60.0 都算，60.5 不算）。"""
    return number == number.to_integral_value()


def field_id(section, *parts):
    """字段标识：设置窗口按它把红字挂到对应的输入框上（与配置里的路径同形）。"""
    return ".".join((section, *parts))


def as_text(value):
    """配置值 → 输入框文本：留空（None）→ ""，数字按字面量（950.00 就是 950.00）。"""
    if value is None:
        return ""
    return format(value, "f") if isinstance(value, Decimal) else str(value)


def validate(values):
    """保存前的校验（纯函数）→ {字段标识: 中文说明}；空字典就是全部通过。

    规则：阈值为正数（留空即停用）；同一市场两个方向都启用时跌破必须小于涨破；
    高级项与外观项的取值范围见 `ADVANCED_FIELDS`／`APPEARANCE_NUMBERS`；颜色须是
    #RRGGBB、字体非空、弹窗位置是四角之一、选了自定义音效就得给 .wav 路径。取值可以
    是配置值，也可以是设置窗口里读到的文本草稿——数字一律经 `parse_decimal` 认，
    两种来源口径一致。
    """
    errors = {}
    values = _as_dict(values)
    thresholds = _as_dict(values.get("thresholds"))
    for market in MARKET_CATALOG:
        given = _as_dict(thresholds.get(market["code"]))
        numbers = {}
        for direction in DIRECTIONS:
            field = field_id("thresholds", market["code"], direction.config_key)
            try:
                number = parse_decimal(given.get(direction.config_key))
            except ValueError:
                errors[field] = (
                    f"{market['name']}{direction.name}阈值请填数字（例：950.00）"
                )
                continue
            if number is not None and number <= 0:
                errors[field] = (
                    f"{market['name']}{direction.name}阈值须为正数（留空即停用）"
                )
                continue
            numbers[direction.config_key] = number
        up, down = numbers.get("up_threshold"), numbers.get("down_threshold")
        if up is not None and down is not None and down >= up:
            errors[field_id("thresholds", market["code"], "down_threshold")] = (
                f"{market['name']}的跌破阈值须小于涨破阈值"
            )
    appearance = _as_dict(values.get("appearance"))
    for key, label in COLOR_FIELDS:
        if not is_color(appearance.get(key)):
            errors[field_id("appearance", key)] = f"{label}须是 #RRGGBB 形式的颜色（例：#1e1f22）"
    font = appearance.get("font")
    if not (isinstance(font, str) and font.strip()):
        errors[field_id("appearance", "font")] = "字体须填字体名称（例：Microsoft YaHei UI）"
    _number_errors(errors, "appearance", appearance, APPEARANCE_NUMBERS)
    _flag_errors(errors, "appearance", appearance, APPEARANCE_FLAGS)
    if appearance.get("popup_corner") not in CORNER_NAMES:
        errors[field_id("appearance", "popup_corner")] = f"弹窗位置须为{CORNER_TEXT}之一"
    sound = _as_dict(values.get("sound"))
    _flag_errors(errors, "sound", sound, SOUND_FLAGS)
    if sound.get("choice") not in SOUND_NAMES:
        errors[field_id("sound", "choice")] = "音效只能选系统提示音或自定义 WAV 文件"
    elif sound["choice"] == CUSTOM_SOUND and not is_wav(sound.get("file")):
        errors[field_id("sound", "file")] = "选择自定义音效时须填 .wav 文件路径"
    advanced = _as_dict(values.get("advanced"))
    _number_errors(errors, "advanced", advanced, ADVANCED_FIELDS)
    _flag_errors(errors, "advanced", advanced, ADVANCED_FLAGS)
    return errors


def _number_errors(errors, section, given, fields):
    """一组数值项：不合要求的把说明挂到对应字段上。"""
    for field in fields:
        if not _number_ok(field, given.get(field.key)):
            errors[field_id(section, field.key)] = f"{field.label}须为{field.hint}"


def _number_ok(field, raw_value):
    """一组数值项里的某个数是否合要求（读不出、不是整数、越界都算不合）。"""
    try:
        number = parse_decimal(raw_value)
    except ValueError:
        return False
    if number is None:  # 数值项不设「留空即停用」，空着就是没填
        return False
    if field.integer_only and not _is_whole(number):
        return False
    return bool(field.allowed(number))


def read_draft(draft):
    """设置窗口的草稿 → (配置值, 错误)：有错时配置值不可用（None），不许保存。

    草稿与配置文件同形，差别只在数值是输入框里的文本（留空即停用）。
    """
    errors = validate(draft)
    if errors:
        return None, errors
    values, _ = normalize(draft)  # 校验已过，这里只做文本 → Decimal／整数／布尔的转换
    return values, {}


def base_dir():
    """程序所在目录：打包运行取 exe 同目录，源码运行取仓库根（见 ADR-0002）。

    `config.json` 与 `logs/` 都摆在这里，两者不许有两种定位规则——否则会出现
    「配置跟着 exe 走、日志落在别处」这种事。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path():
    """配置文件的位置：与程序放在一起，换电脑时拷走它设置跟着走（见 ADR-0002）。"""
    return base_dir() / CONFIG_NAME


def read_text(path):
    """把配置文件读成文本：UTF-8（可带 BOM）优先，读不出来再按本机 ANSI 编码试一次。

    配置文件是给人改的：记事本存成「ANSI」（简中即 GBK），PowerShell 5.1 的
    `Set-Content -Encoding UTF8` 与老记事本会加 BOM——那些都仍是**我们那份**配置，
    不该被判成坏文件：一旦判坏就是备份走人、四个阈值静默丢回默认值，用户还以为
    监视开着（见 ticket 05 的事件记录，那里至少留得下一条说明）。
    """
    raw = Path(path).read_bytes()
    fallback = locale.getpreferredencoding(False) or "utf-8"  # 本机 ANSI：简中是 cp936
    failure = None
    for encoding in ("utf-8-sig", fallback):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            failure = exc
    raise failure


def dumps(values):
    """配置 → 文件文本：缩进两格、中文不转义，小数写成字符串。

    JSON 没有小数类型：写成数字要经二进制浮点，950.00 会变成 950.0 甚至
    949.9999…；写成字符串则字面量原样往返（读的时候数字与字符串都认）。
    """
    return json.dumps(_jsonable(values), ensure_ascii=False, indent=2) + "\n"


def _jsonable(value):
    """能交给 json 的形状：Decimal 换成字面量字符串，其余照原样（递归）。"""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def save(path, values):
    """把配置写到文件：先写临时文件、再原子替换，写一半中断也不留半截文件。

    「非法值不许保存」在数据层也拦一道：校验不过抛 `ConfigError`，不只是靠设置
    窗口自觉。写不进去（只读目录等）时抛 OSError，由调用方提示——快照不受影响。
    """
    errors = validate(values)
    if errors:
        raise ConfigError(errors)
    path = Path(path)
    temp = path.with_name(path.name + TEMP_SUFFIX)
    try:
        with open(temp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(dumps(values))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)  # 收摊：原文件分毫未动，半截子也不留下
        raise


def load(path):
    """读配置 → (配置值, 说明)：任何配置问题都不阻断启动（副作用：可能写盘）。

    文件不在就生成默认文件；读不出来就备份为 `config.json.bak` 并按默认值跑；
    缺字段补默认、坏值只废掉那一项。说明是给用户看的中文短句，主窗口先顶着显示，
    落盘日志见 ticket 05。
    """
    path = Path(path)
    if not path.exists():
        values = default_values()
        try:
            save(path, values)
        except OSError as exc:  # 只读目录（exe 落在 Program Files 等）：跑起来比生成文件要紧
            return values, (
                f"未找到配置文件，也写不进去（{exc.strerror or exc}），本次按默认值运行",
            )
        return values, (f"未找到配置文件，已按默认值生成 {path.name}",)
    try:
        text = read_text(path)
    except OSError as exc:
        return _recover(path, f"读文件失败（{exc.strerror or exc}）")
    except UnicodeDecodeError:
        return _recover(path, "不是文本文件（UTF-8 与 ANSI 都读不出来）")
    try:
        raw = json.loads(text, parse_float=Decimal)
    except ValueError:
        return _recover(path, "不是合法的 JSON")
    if not isinstance(raw, dict):
        return _recover(path, "顶层不是一个设置对象")
    values, notices = normalize(raw)
    # 手改出来的自相矛盾（如跌破 ≥ 涨破）不擅自改动，只说明一句：拦保存是设置窗口的事
    return values, notices + tuple(validate(values).values())


def _recover(path, reason):
    """坏文件：备份到 config.json.bak，按默认值继续跑，顺带把默认文件补回来。"""
    values = default_values()
    notices = [f"配置文件读不出来（{reason}），已按默认值运行"]
    try:
        os.replace(path, path.with_name(BACKUP_NAME))
        notices.append(f"原文件已备份为 {BACKUP_NAME}")
    except OSError as backup_error:
        notices.append(f"原文件备份失败（{backup_error.strerror or backup_error}）")
    try:
        save(path, values)
    except OSError:
        pass  # 只读目录：程序照样跑，下次有写权限时再生成
    return values, tuple(notices)


class ConfigError(Exception):
    """配置不合法：带着「哪一项不对」的说明，设置窗口据此把红字挂到输入框上。"""

    def __init__(self, errors):
        self.errors = dict(errors)
        super().__init__("；".join(self.errors.values()))


class ConfigStore:
    """当前生效的配置：一份内存快照 + 它的落盘位置。

    轮询线程每轮开头读一次 `values`，保存时整体换掉引用——不加锁，也不允许就地
    改快照（要改就照抄一份、改完交给 `save`）。这样「保存即生效」不用打断取数。
    """

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else config_path()
        self.values = default_values()

    def load(self):
        """启动时读一次 → 说明：文件不在就生成、坏了就备份（任何情况都不挡启动）。"""
        self.values, notices = load(self.path)
        return notices

    def save(self, values):
        """保存并立即生效：先原子落盘，成功了才换快照（写不进去就当没改过）。"""
        save(self.path, values)
        self.values = values
