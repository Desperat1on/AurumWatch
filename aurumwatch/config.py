# -*- coding: utf-8 -*-
"""配置（纯函数层）：默认值、数据形状、规范化、校验、读写与原子落盘。

可调项只存在于 exe／仓库同目录的 `config.json` 与设置窗口，源码里没有配置区
（见 ticket 03）。数值一律用 Decimal 承载，950.00 就是 950.00——JSON 没有小数
类型，写文件时小数按字面量写成字符串，读文件时字符串与数字都认。
"""

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aurumwatch.alerts import DIRECTIONS

CONFIG_NAME = "config.json"
BACKUP_NAME = "config.json.bak"
TEMP_SUFFIX = ".tmp"

# 刷新间隔的下限（秒）：再密就是对数据源的硬碰，也会把「下次刷新」倒计时搅得没法看
MIN_REFRESH_INTERVAL = 5


@dataclass(frozen=True)
class AdvancedField:
    """高级项的一项：配置键、中文名与取值要求。

    规范化（越界回退默认值）与校验（越界不许保存）共用同一份要求，免得两边走偏。
    """

    key: str
    label: str
    unit: str  # 设置窗口挂在名称后的单位，如「刷新间隔（秒）」
    hint: str  # 要求的中文说法，如「不小于 5 的整数秒」
    integer_only: bool  # 是否只收整数
    allowed: Callable[[Decimal], bool]  # 取值是否在范围内


ADVANCED_FIELDS = (
    AdvancedField(
        "refresh_interval", "刷新间隔", "秒", f"不小于 {MIN_REFRESH_INTERVAL} 的整数秒",
        True, lambda number: number >= MIN_REFRESH_INTERVAL,
    ),
    AdvancedField(
        "rearm_ratio", "重新武装带比例", "", "0 与 1 之间的小数（例：0.001）",
        False, lambda number: 0 < number < 1,
    ),
    AdvancedField(
        "failure_warn_minutes", "故障警告时长", "分钟", "正整数分钟",
        True, lambda number: number >= 1,
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
        "sound": {"enabled": True},
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
    _read_flags(
        _as_dict(raw.get("sound")), values["sound"], notices, (("enabled", "提示音开关"),)
    )
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


def _read_advanced(raw, values, notices):
    """高级项：读不出的、不合要求的都回退默认值并说明。"""
    for field in ADVANCED_FIELDS:
        raw_value = raw.get(field.key)
        if raw_value is None:
            continue
        if _advanced_ok(field, raw_value):
            number = parse_decimal(raw_value)
            values[field.key] = int(number) if field.integer_only else number
            continue
        notices.append(
            f"{field.label}须为{field.hint}，"
            f"已按默认值 {as_text(values[field.key])} 处理"
        )
    _read_flags(
        raw, values, notices, (("alert_on_start", "启动时若已越线立即提醒"),)
    )


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
    高级项的取值范围见 `ADVANCED_FIELDS`。取值可以是配置值，也可以是设置窗口里
    读到的文本草稿——数字一律经 `parse_decimal` 认，两种来源口径一致。
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
    advanced = _as_dict(values.get("advanced"))
    for field in ADVANCED_FIELDS:
        if not _advanced_ok(field, advanced.get(field.key)):
            errors[field_id("advanced", field.key)] = f"{field.label}须为{field.hint}"
    return errors


def _advanced_ok(field, raw_value):
    """高级项读出来的数是否合要求（读不出、不是整数、越界都算不合）。"""
    try:
        number = parse_decimal(raw_value)
    except ValueError:
        return False
    if number is None:  # 高级项不设「留空即停用」，空着就是没填
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


def config_path():
    """配置文件的位置：打包运行取 exe 同目录，源码运行取仓库根（见 ADR-0002）。"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
    else:
        base = Path(__file__).resolve().parent.parent
    return base / CONFIG_NAME


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
        raw = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
    except OSError as exc:
        return _recover(path, f"读文件失败（{exc.strerror or exc}）")
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
