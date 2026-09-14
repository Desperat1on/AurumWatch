# -*- coding: utf-8 -*-
"""开机自启单元测试（纯函数 + 一份内存里的假注册表，不碰真注册表、不建窗口）。

这一项的承诺是「勾选写进去、取消删干净、源码运行不给写」：写入的值要能被 Windows
当命令跑（路径带引号）、取消之后不留东西、从源码运行不许把 python.exe 写进启动项。
真注册表上的效果（写进 HKCU 的 Run 键、重启后自启）属手动验收，见 ticket 06。
"""

import contextlib
import sys
import unittest
from pathlib import Path
from unittest import mock

from aurumwatch import autostart

EXE = Path("D:/Apps/AurumWatch/AurumWatch.exe")


class FakeRegistry:
    """内存里的注册表：只认本模块用到的那几个调用（键、值的在不在都要说得清楚）。"""

    def __init__(self, values=None, key_exists=True):
        self.values = dict(values or {})
        self.key_exists = key_exists
        self.written = []  # [(值名, 类型, 值)]：断言写的是什么

    def OpenKey(self, root, path, reserved, access):
        if not self.key_exists:
            raise FileNotFoundError(2, "系统找不到指定的文件。", path)
        return _FakeKey(self)

    def CreateKeyEx(self, root, path, reserved, access):
        self.key_exists = True  # 写的时候键不在就顺手建出来
        return _FakeKey(self)

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(2, "系统找不到指定的文件。", name)
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value
        self.written.append((name, kind, value))

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(2, "系统找不到指定的文件。", name)
        del self.values[name]

    # 常量：值与 winreg 的对得上就行，测试里不拿它们做别的事
    HKEY_CURRENT_USER = "HKCU"
    KEY_QUERY_VALUE = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1


class _FakeKey:
    """注册表键的替身：只管当上下文管理器（真 winreg 的键就是这么用的）。"""

    def __init__(self, registry):
        self._registry = registry

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def with_registry(registry):
    """把模块里的 winreg 换成假的那一份。"""
    return mock.patch.object(autostart, "winreg", registry)


@contextlib.contextmanager
def frozen(exe=EXE):
    """假装这是打包运行（exe 自己就是启动目标）。"""
    with mock.patch.object(sys, "frozen", True, create=True), mock.patch.object(
        sys, "executable", str(exe)
    ):
        yield


class CommandLineIsRunnable(unittest.TestCase):
    """写进启动项的那串命令：Windows 拿它当命令行跑，路径必须在引号里。"""

    def test_path_is_quoted(self):
        self.assertEqual(
            autostart.command_line(EXE), '"D:\\Apps\\AurumWatch\\AurumWatch.exe"'
        )

    def test_a_path_with_spaces_survives(self):
        # 不加引号的话 Windows 会按空格切开去跑 C:\Program.exe（自启静默失败）
        self.assertEqual(
            autostart.command_line("C:/Program Files/AurumWatch/AurumWatch.exe"),
            '"C:\\Program Files\\AurumWatch\\AurumWatch.exe"',
        )

    def test_a_relative_path_is_made_absolute(self):
        # 启动项是在别的进程、别的工作目录里执行的：相对路径在那儿没有意义
        line = autostart.command_line("dist/AurumWatch.exe")
        self.assertTrue(line.startswith('"'))
        self.assertTrue(line.endswith('"'))
        self.assertEqual(Path(line.strip('"')).name, "AurumWatch.exe")
        self.assertEqual(Path(line.strip('"')).parent, Path.cwd() / "dist")


class TargetOnlyExistsWhenPackaged(unittest.TestCase):
    """从源码运行没有可自启的 exe：那一项在设置窗口里是灰的（见 User Story 10）。"""

    def test_source_run_has_no_target(self):
        self.assertIsNone(autostart.exe_path())

    def test_packaged_run_targets_the_exe(self):
        with frozen():
            self.assertEqual(autostart.exe_path(), EXE)


class EnabledFollowsTheRegistry(unittest.TestCase):
    """开关说的是「这一份会不会开机自启」：值在、且指向本次运行的 exe 才算开。"""

    def test_missing_key_counts_as_off(self):
        with with_registry(FakeRegistry(key_exists=False)), frozen():
            self.assertFalse(autostart.enabled())

    def test_missing_value_counts_as_off(self):
        with with_registry(FakeRegistry({"别的程序": "x"})), frozen():
            self.assertFalse(autostart.enabled())

    def test_our_value_counts_as_on(self):
        with with_registry(FakeRegistry({autostart.VALUE_NAME: f'"{EXE}"'})), frozen():
            self.assertTrue(autostart.enabled())

    def test_an_unquoted_value_still_counts_as_ours(self):
        # 手改过注册表（或早先的版本）写法不同，不该因此说「没开」
        with with_registry(FakeRegistry({autostart.VALUE_NAME: str(EXE)})), frozen():
            self.assertTrue(autostart.enabled())

    def test_another_copy_of_the_app_counts_as_off(self):
        # exe 搬了家、重新打包换了位置：这一份开机时并不会起来，如实显示未勾选
        with with_registry(
            FakeRegistry({autostart.VALUE_NAME: '"D:\\旧位置\\AurumWatch.exe"'})
        ), frozen():
            self.assertFalse(autostart.enabled())

    def test_source_run_is_off_whatever_the_registry_says(self):
        with with_registry(FakeRegistry({autostart.VALUE_NAME: f'"{EXE}"'})):
            self.assertFalse(autostart.enabled(), "源码运行没有可自启的 exe")

    def test_a_read_failure_counts_as_off(self):
        # 读不出来就当没有：这是「有就写、没有就当没有」的开关，不该因此挡住窗口
        with with_registry(FakeRegistry()), frozen(), mock.patch.object(
            FakeRegistry, "OpenKey", side_effect=PermissionError("拒绝访问")
        ):
            self.assertFalse(autostart.enabled())


class PointsAtComparesCommandLines(unittest.TestCase):
    """那一条启动命令是不是就跑这个程序（纯函数）：引号、大小写、斜杠都不论。"""

    def test_quoted_and_bare_both_match(self):
        self.assertTrue(autostart.points_at(f'"{EXE}"', EXE))
        self.assertTrue(autostart.points_at(str(EXE), EXE))

    def test_case_and_slashes_do_not_matter(self):
        self.assertTrue(autostart.points_at("d:/apps/aurumwatch/AURUMWATCH.EXE", EXE))

    def test_a_different_program_does_not_match(self):
        self.assertFalse(autostart.points_at('"D:\\别的\\AurumWatch.exe"', EXE))
        self.assertFalse(autostart.points_at("", EXE))
        self.assertFalse(autostart.points_at(None, EXE), "不是文本就当没开")


class TogglingWritesAndRemoves(unittest.TestCase):
    """勾选写进 Run 键（值为本次运行的 exe），取消删干净。"""

    def test_checking_writes_the_quoted_exe_path(self):
        registry = FakeRegistry()
        with with_registry(registry), frozen():
            autostart.set_enabled(True)
        self.assertEqual(
            registry.written,
            [(autostart.VALUE_NAME, registry.REG_SZ, f'"{EXE}"')],
        )
        self.assertEqual(registry.values, {autostart.VALUE_NAME: f'"{EXE}"'})

    def test_unchecking_removes_it(self):
        registry = FakeRegistry({autostart.VALUE_NAME: f'"{EXE}"'})
        with with_registry(registry):
            autostart.set_enabled(False)
        self.assertEqual(registry.values, {}, "取消之后注册表里不留东西")

    def test_unchecking_clears_a_stale_entry_too(self):
        # 旧位置留下的那一项：没勾（这一份确实不会自启）时保存，就该把它清掉
        registry = FakeRegistry({autostart.VALUE_NAME: '"D:\\旧位置\\AurumWatch.exe"'})
        with with_registry(registry):
            autostart.set_enabled(False)
        self.assertEqual(registry.values, {})

    def test_unchecking_an_absent_entry_is_fine(self):
        registry = FakeRegistry({}, key_exists=False)
        with with_registry(registry):
            autostart.set_enabled(False)  # 本来就没有：要的就是这个结果
        self.assertEqual(registry.values, {})

    def test_source_run_cannot_be_checked(self):
        # 打包之前勾上，写进去的会是 python.exe：换台电脑就只剩一个报错框
        registry = FakeRegistry()
        with with_registry(registry):
            with self.assertRaises(ValueError):
                autostart.set_enabled(True)
        self.assertEqual(registry.written, [], "一个字都不许写进注册表")

    def test_a_write_failure_reaches_the_caller(self):
        # 写不进去（权限等）时得让设置窗口说得出原因，不能悄悄当成设好了
        with with_registry(FakeRegistry()), frozen(), mock.patch.object(
            FakeRegistry, "SetValueEx", side_effect=PermissionError("拒绝访问")
        ):
            with self.assertRaises(OSError):
                autostart.set_enabled(True)


if __name__ == "__main__":
    unittest.main()
