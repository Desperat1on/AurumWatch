# -*- coding: utf-8 -*-
"""配置单元测试（纯函数，不碰窗口；落盘用临时目录）。

可调项只来自 config.json 与设置窗口，因此这里断言的是配置对外的承诺：缺字段补默认、
坏值拒绝并回退、阈值按 Decimal 精确读写、校验指出具体项、写坏不伤原文件。
"""

import json
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest import mock

from aurumwatch.config import (
    ConfigError,
    ConfigStore,
    as_text,
    config_path,
    default_values,
    field_id,
    load,
    markets,
    normalize,
    save,
    validate,
)

# 两个市场的固定身份：名称、说明、单位与行情代码不可调
DOMESTIC_CODE = "gds_AU9999"
INTERNATIONAL_CODE = "hf_XAU"


def as_draft(values):
    """配置值 → 设置窗口里那样的草稿：数值都成输入框里的文本，开关仍是布尔。"""
    return {
        "thresholds": {
            code: {key: as_text(value) for key, value in section.items()}
            for code, section in values["thresholds"].items()
        },
        "sound": dict(values["sound"]),
        "advanced": {
            key: value if isinstance(value, bool) else as_text(value)
            for key, value in values["advanced"].items()
        },
    }


class DefaultsAreUsable(unittest.TestCase):
    """默认配置：阈值一律留空（不打扰），其余沿用控制台版的默认值。"""

    def test_thresholds_default_to_disabled(self):
        values = default_values()
        self.assertEqual(
            values["thresholds"],
            {
                DOMESTIC_CODE: {"up_threshold": None, "down_threshold": None},
                INTERNATIONAL_CODE: {"up_threshold": None, "down_threshold": None},
            },
            "默认不设阈值：装上就能跑，不会开口就报",
        )

    def test_advanced_items_keep_the_old_defaults(self):
        self.assertEqual(
            default_values()["advanced"],
            {
                "refresh_interval": 60,
                "rearm_ratio": Decimal("0.001"),
                "failure_warn_minutes": 10,
                "alert_on_start": True,
            },
        )

    def test_sound_defaults_to_on(self):
        self.assertEqual(default_values()["sound"], {"enabled": True})

    def test_each_call_returns_a_fresh_copy(self):
        first = default_values()
        first["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("950.00")
        self.assertIsNone(
            default_values()["thresholds"][DOMESTIC_CODE]["up_threshold"],
            "拿到手的默认值可以随便改，不影响下一次",
        )

    def test_markets_pair_the_catalog_with_configured_thresholds(self):
        values = default_values()
        values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("950.00")
        by_code = {market["code"]: market for market in markets(values)}
        self.assertEqual(
            list(by_code), [DOMESTIC_CODE, INTERNATIONAL_CODE], "市场顺序固定"
        )
        self.assertEqual(by_code[DOMESTIC_CODE]["name"], "国内金价")
        self.assertEqual(by_code[DOMESTIC_CODE]["unit"], "元/克")
        self.assertEqual(by_code[DOMESTIC_CODE]["up_threshold"], Decimal("950.00"))
        self.assertIsNone(by_code[DOMESTIC_CODE]["down_threshold"], "没配的方向留空")
        self.assertIsNone(by_code[INTERNATIONAL_CODE]["up_threshold"])


class NormalizeFillsDefaultsAndRejectsBadValues(unittest.TestCase):
    """读到的东西可能缺字段、也可能是坏值：缺的就补、坏的只废掉那一项。"""

    def test_empty_raw_gives_the_defaults(self):
        self.assertEqual(normalize({}), (default_values(), ()))

    def test_missing_keys_are_filled_from_defaults(self):
        raw = {"advanced": {"refresh_interval": 120}}
        values, notices = normalize(raw)
        self.assertEqual(values["advanced"]["refresh_interval"], 120, "给到的照用")
        self.assertEqual(
            values["advanced"]["rearm_ratio"], Decimal("0.001"), "没给到的补默认"
        )
        self.assertEqual(
            values["thresholds"], default_values()["thresholds"], "整段没给就整段默认"
        )
        self.assertEqual(notices, (), "缺字段不算错，不用啰嗦")

    def test_numbers_are_read_at_decimal_precision(self):
        raw = {
            "thresholds": {
                DOMESTIC_CODE: {"up_threshold": "950.00", "down_threshold": 900.50}
            },
            "advanced": {"rearm_ratio": "0.002", "failure_warn_minutes": 15},
        }
        values, notices = normalize(raw)
        self.assertEqual(notices, ())
        self.assertEqual(
            values["thresholds"][DOMESTIC_CODE]["up_threshold"], Decimal("950.00")
        )
        self.assertEqual(
            str(values["thresholds"][DOMESTIC_CODE]["up_threshold"]),
            "950.00",
            "连字面量都保住：950.00 就是 950.00",
        )
        self.assertEqual(
            values["thresholds"][DOMESTIC_CODE]["down_threshold"], Decimal("900.50"),
            "数字写法（json 的 parse_float=Decimal）同样精确",
        )
        self.assertEqual(values["advanced"]["rearm_ratio"], Decimal("0.002"))
        self.assertIsInstance(values["advanced"]["failure_warn_minutes"], int)

    def test_unreadable_threshold_disables_only_that_direction(self):
        raw = {
            "thresholds": {
                DOMESTIC_CODE: {"up_threshold": "九百五", "down_threshold": "900.00"}
            }
        }
        values, notices = normalize(raw)
        self.assertIsNone(
            values["thresholds"][DOMESTIC_CODE]["up_threshold"], "读不出来的阈值当没填"
        )
        self.assertEqual(
            values["thresholds"][DOMESTIC_CODE]["down_threshold"], Decimal("900.00"),
            "另一方向不受牵连",
        )
        self.assertEqual(len(notices), 1)
        self.assertIn("国内金价", notices[0])
        self.assertIn("涨破", notices[0])

    def test_non_positive_threshold_is_rejected(self):
        raw = {
            "thresholds": {
                DOMESTIC_CODE: {"up_threshold": "0", "down_threshold": "-5.00"}
            }
        }
        values, notices = normalize(raw)
        self.assertIsNone(values["thresholds"][DOMESTIC_CODE]["up_threshold"])
        self.assertIsNone(values["thresholds"][DOMESTIC_CODE]["down_threshold"])
        self.assertEqual(len(notices), 2, "每一项各说各的")

    def test_out_of_range_advanced_values_fall_back_to_defaults(self):
        raw = {
            "advanced": {
                "refresh_interval": 2,
                "rearm_ratio": "1.5",
                "failure_warn_minutes": 0,
            }
        }
        values, notices = normalize(raw)
        self.assertEqual(values["advanced"]["refresh_interval"], 60)
        self.assertEqual(values["advanced"]["rearm_ratio"], Decimal("0.001"))
        self.assertEqual(values["advanced"]["failure_warn_minutes"], 10)
        self.assertEqual(len(notices), 3, "三项越界各说各的")

    def test_non_integer_refresh_interval_is_rejected(self):
        values, notices = normalize({"advanced": {"refresh_interval": "60.5"}})
        self.assertEqual(values["advanced"]["refresh_interval"], 60)
        self.assertEqual(len(notices), 1)

    def test_switches_accept_only_booleans(self):
        values, notices = normalize(
            {"sound": {"enabled": "yes"}, "advanced": {"alert_on_start": False}}
        )
        self.assertIs(values["sound"]["enabled"], True, "认不出的开关按默认（开）处理")
        self.assertIs(values["advanced"]["alert_on_start"], False, "关掉的开关照实读")
        self.assertEqual(len(notices), 1)

    def test_unknown_keys_are_ignored(self):
        raw = {"thresholds": {"gds_AU9999": {"up_threshold": None, "odd": 1}}, "extra": 2}
        values, notices = normalize(raw)
        self.assertEqual(notices, ())
        self.assertEqual(
            values["thresholds"][DOMESTIC_CODE],
            {"up_threshold": None, "down_threshold": None},
        )

    def test_sections_of_the_wrong_shape_fall_back_to_defaults(self):
        values, notices = normalize({"thresholds": "坏了", "advanced": [1, 2], "sound": None})
        self.assertEqual(values, default_values())
        self.assertIsInstance(notices, tuple)


class ValidatePointsAtTheOffendingField(unittest.TestCase):
    """保存前的校验：每处毛病都点名到字段，窗口据此把红字挂在对应的输入框上。"""

    def setUp(self):
        self.values = default_values()
        self.up = field_id("thresholds", DOMESTIC_CODE, "up_threshold")
        self.down = field_id("thresholds", DOMESTIC_CODE, "down_threshold")

    def test_defaults_pass(self):
        self.assertEqual(validate(self.values), {}, "默认值必须能保存")

    def test_thresholds_are_optional(self):
        self.values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("950.00")
        self.assertEqual(validate(self.values), {}, "只设一个方向是常态")

    def test_non_positive_threshold_is_rejected_by_name(self):
        self.values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("0")
        errors = validate(self.values)
        self.assertEqual(list(errors), [self.up])
        self.assertIn("正数", errors[self.up])
        self.assertIn("国内金价", errors[self.up])

    def test_text_that_is_not_a_number_is_rejected(self):
        draft = as_draft(self.values)
        draft["thresholds"][DOMESTIC_CODE]["up_threshold"] = "九百五"
        errors = validate(draft)
        self.assertEqual(list(errors), [self.up])
        self.assertIn("数字", errors[self.up])

    def test_downside_must_stay_below_upside(self):
        self.values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("900.00")
        self.values["thresholds"][DOMESTIC_CODE]["down_threshold"] = Decimal("950.00")
        errors = validate(self.values)
        self.assertEqual(list(errors), [self.down], "错在跌破那一项")
        self.assertIn("小于", errors[self.down])

    def test_equal_thresholds_are_rejected_too(self):
        self.values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("950.00")
        self.values["thresholds"][DOMESTIC_CODE]["down_threshold"] = Decimal("950.00")
        self.assertEqual(list(validate(self.values)), [self.down])

    def test_each_market_is_checked_on_its_own(self):
        self.values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("900.00")
        self.values["thresholds"][DOMESTIC_CODE]["down_threshold"] = Decimal("950.00")
        self.values["thresholds"][INTERNATIONAL_CODE]["up_threshold"] = Decimal("4400.00")
        self.values["thresholds"][INTERNATIONAL_CODE]["down_threshold"] = Decimal("4300.00")
        self.assertEqual(
            list(validate(self.values)), [self.down], "国际那边顺序正确就不该被牵连"
        )

    def test_advanced_ranges_are_enforced(self):
        cases = (
            ("refresh_interval", 4, "秒"),
            ("refresh_interval", 60.5, "整数"),
            ("refresh_interval", "", "秒"),
            ("rearm_ratio", Decimal("0"), "0 与 1"),
            ("rearm_ratio", Decimal("1"), "0 与 1"),
            ("failure_warn_minutes", 0, "分钟"),
        )
        for key, bad, word in cases:
            with self.subTest(key=key, bad=bad):
                values = default_values()
                values["advanced"][key] = bad
                errors = validate(values)
                self.assertEqual(list(errors), [field_id("advanced", key)])
                self.assertIn(word, errors[field_id("advanced", key)])

    def test_malformed_sections_are_read_as_unset(self):
        errors = validate({"thresholds": "坏了", "advanced": [1, 2], "sound": None})
        self.assertIsInstance(errors, dict, "草稿形状不对也不炸：当作没填")
        self.assertEqual(
            [field for field in errors if field.startswith("thresholds.")], [],
            "读不出的阈值段算全留空，不该凭空报错",
        )

    def test_a_draft_from_the_settings_window_is_checked_the_same_way(self):
        draft = as_draft(self.values)
        draft["thresholds"][DOMESTIC_CODE]["up_threshold"] = "950.00"
        draft["advanced"]["refresh_interval"] = "120"
        self.assertEqual(validate(draft), {}, "输入框里的文本照样能校验（留空即停用）")
        draft["advanced"]["rearm_ratio"] = "1.5"
        self.assertEqual(
            list(validate(draft)), [field_id("advanced", "rearm_ratio")],
            "草稿里的坏值一样点名",
        )


class ReadsAndWritesTheFile(unittest.TestCase):
    """落盘：与 exe／仓库同目录的 config.json，精确、原子、坏了也不挡启动。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "config.json"

    def with_threshold(self):
        """一份带阈值的配置：国内涨破 950.00、跌破 900.00，其余默认。"""
        values = default_values()
        values["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("950.00")
        values["thresholds"][DOMESTIC_CODE]["down_threshold"] = Decimal("900.00")
        return values

    def test_save_then_load_keeps_the_exact_decimals(self):
        save(self.path, self.with_threshold())
        loaded, notices = load(self.path)
        self.assertEqual(notices, ())
        self.assertEqual(loaded, self.with_threshold(), "存进去什么就读出什么")
        self.assertEqual(
            str(loaded["thresholds"][DOMESTIC_CODE]["up_threshold"]),
            "950.00",
            "连字面量都保住：950.00 就是 950.00",
        )

    def test_saved_file_is_readable_json(self):
        save(self.path, self.with_threshold())
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["thresholds"][DOMESTIC_CODE]["up_threshold"], "950.00")
        self.assertEqual(raw["advanced"]["rearm_ratio"], "0.001")
        self.assertTrue(raw["sound"]["enabled"])
        self.assertEqual(raw["advanced"]["refresh_interval"], 60)

    def test_saving_leaves_no_half_written_files_around(self):
        save(self.path, self.with_threshold())
        self.assertEqual(
            [item.name for item in Path(self.folder.name).iterdir()], ["config.json"]
        )

    def test_an_interrupted_write_leaves_the_old_file_intact(self):
        save(self.path, self.with_threshold())
        before = self.path.read_text(encoding="utf-8")
        changed = default_values()
        with mock.patch("os.replace", side_effect=OSError("磁盘满了")):
            with self.assertRaises(OSError):
                save(self.path, changed)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before, "原文件分毫未动")
        self.assertEqual(
            [item.name for item in Path(self.folder.name).iterdir()],
            ["config.json"],
            "写了半截的临时文件已经撤掉",
        )

    def test_invalid_values_are_never_written(self):
        bad = default_values()
        bad["thresholds"][DOMESTIC_CODE]["up_threshold"] = Decimal("-1")
        with self.assertRaises(ConfigError):
            save(self.path, bad)
        self.assertFalse(self.path.exists(), "校验不过就一个字都不落盘")

    def test_first_run_generates_the_default_file(self):
        values, notices = load(self.path)
        self.assertEqual(values, default_values())
        self.assertTrue(self.path.exists(), "首次运行就把配置文件摆出来，用户看得见")
        self.assertEqual(len(notices), 1)
        self.assertIn("默认", notices[0])

    def test_a_read_only_folder_still_starts(self):
        # exe 落在 Program Files 这类只读目录：生成不了配置文件也得跑起来（见 ADR-0002）
        with mock.patch("os.replace", side_effect=OSError("拒绝访问")):
            values, notices = load(self.path)
        self.assertEqual(values, default_values(), "写不进去就按默认值跑，不挡启动")
        self.assertFalse(self.path.exists())
        self.assertTrue(any("默认值" in notice for notice in notices), notices)
        self.assertEqual(
            [item.name for item in Path(self.folder.name).iterdir()], [], "别留下半截临时文件"
        )

    def test_broken_file_is_backed_up_and_defaults_run(self):
        self.path.write_text("{ 这不是 json", encoding="utf-8")
        values, notices = load(self.path)
        self.assertEqual(values, default_values(), "坏文件不挡启动：按默认值跑")
        backup = self.path.with_name("config.json.bak")
        self.assertEqual(backup.read_text(encoding="utf-8"), "{ 这不是 json")
        self.assertTrue(any("备份" in notice for notice in notices))
        self.assertTrue(
            any("不是合法的 JSON" in notice for notice in notices),
            f"给人看的说法，不把 Python 异常原样贴出来：{notices}",
        )

    def test_json_that_is_not_an_object_counts_as_broken(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        values, notices = load(self.path)
        self.assertEqual(values, default_values())
        self.assertTrue(self.path.with_name("config.json.bak").exists())
        self.assertTrue(any("不是一个设置对象" in notice for notice in notices), notices)

    def test_a_hand_edited_file_keeps_what_it_says(self):
        self.path.write_text(
            json.dumps(
                {
                    "thresholds": {DOMESTIC_CODE: {"up_threshold": 950.0}},
                    "advanced": {"refresh_interval": 120},
                }
            ),
            encoding="utf-8",
        )
        values, notices = load(self.path)
        self.assertEqual(notices, (), "缺的字段补默认，不算坏文件")
        self.assertEqual(
            values["thresholds"][DOMESTIC_CODE]["up_threshold"], Decimal("950.0")
        )
        self.assertEqual(values["advanced"]["refresh_interval"], 120)
        self.assertIsNone(values["thresholds"][INTERNATIONAL_CODE]["up_threshold"])
        self.assertFalse(self.path.with_name("config.json.bak").exists(), "没坏就不备份")

    def test_conflicting_directions_are_reported_but_still_run(self):
        self.path.write_text(
            json.dumps(
                {
                    "thresholds": {
                        DOMESTIC_CODE: {
                            "up_threshold": "900.00",
                            "down_threshold": "950.00",
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        values, notices = load(self.path)
        self.assertEqual(
            values["thresholds"][DOMESTIC_CODE]["down_threshold"],
            Decimal("950.00"),
            "手改出来的顺序不擅自改，只是不给保存",
        )
        self.assertTrue(any("跌破" in notice for notice in notices))


class ConfigPathFollowsTheDelivery(unittest.TestCase):
    """配置文件与程序放在一起：打包运行在 exe 旁，源码运行在仓库根（见 ADR-0002）。"""

    def test_source_run_puts_it_at_the_repo_root(self):
        self.assertEqual(
            config_path(), Path(__file__).resolve().parent.parent / "config.json"
        )

    def test_packaged_run_puts_it_beside_the_exe(self):
        with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
            sys, "executable", str(Path("D:/Apps/AurumWatch.exe"))
        ):
            self.assertEqual(config_path(), Path("D:/Apps/config.json"))


class StoreKeepsTheLiveSnapshot(unittest.TestCase):
    """当前生效的配置：一份快照，保存时整体替换——轮询线程每轮读它一次。"""

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "config.json"
        self.store = ConfigStore(self.path)
        self.store.load()

    def test_saving_swaps_the_snapshot_and_the_file(self):
        changed = default_values()
        changed["advanced"]["refresh_interval"] = 120
        self.store.save(changed)
        self.assertEqual(self.store.values, changed, "保存即生效，不重启")
        self.assertEqual(load(self.path)[0], changed)

    def test_a_failed_write_leaves_the_snapshot_alone(self):
        changed = default_values()
        changed["advanced"]["refresh_interval"] = 120
        with mock.patch("os.replace", side_effect=OSError("只读目录")):
            with self.assertRaises(OSError):
                self.store.save(changed)
        self.assertEqual(self.store.values, default_values(), "写不进去就不算改过设置")

    def test_load_reports_what_it_did_to_the_file(self):
        broken = ConfigStore(self.path)
        self.path.write_text("坏了", encoding="utf-8")
        notices = broken.load()
        self.assertTrue(notices, "启动时读出来的问题要说给用户听")
        self.assertEqual(broken.values, default_values())


if __name__ == "__main__":
    unittest.main()
