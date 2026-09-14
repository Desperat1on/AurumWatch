# -*- coding: utf-8 -*-
"""图标单元测试（纯函数，不建窗口、不写盘）。

图标是画出来的（见 ticket 07）：一枚金币加一条上行折线。这里只锁「交给两头的字节是
不是那个形状」——exe 要的 ICO 得是七档、每档是一张像样的 32 位位图；窗口与任务栏要的
PNG 得能被解析回来，四角透明、中间是实心的金币。画得好不好看是人的事，这两条不是。
"""

import struct
import unittest
import zlib

from aurumwatch import icon
from aurumwatch.icon import SIZES, ico_bytes, png_bytes


def decode_png(data):
    """PNG 字节 → (宽, 高, 每行像素)。只认我们自己写出来的这种（8 位 RGBA、不过滤）。"""
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "不是 PNG"
    pos, width, height, payload = 8, 0, 0, b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        tag = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        assert struct.unpack(">I", data[pos + 8 + length : pos + 12 + length])[0] == (
            zlib.crc32(tag + body) & 0xFFFFFFFF
        ), f"{tag} 的 CRC 不对"
        if tag == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            assert (depth, color) == (8, 6), "应当是 8 位 RGBA"
        elif tag == b"IDAT":
            payload += body
        pos += 12 + length
    raw = zlib.decompress(payload)
    stride = width * 4
    rows = []
    for y in range(height):
        assert raw[y * (stride + 1)] == 0, "我们写的行不带过滤字节"
        start = y * (stride + 1) + 1
        rows.append(raw[start : start + stride])
    return width, height, rows


class IcoShape(unittest.TestCase):
    """ICO：档位、表头与每档的位图头都得对，装进 exe 才认。"""

    def setUp(self):
        self.data = ico_bytes()

    def test_header_names_every_size(self):
        reserved, kind, count = struct.unpack("<HHH", self.data[:6])
        self.assertEqual((reserved, kind), (0, 1), "ICO 的表头")
        self.assertEqual(count, len(SIZES))

    def test_each_entry_points_at_a_bitmap(self):
        for index, size in enumerate(SIZES):
            start = 6 + index * 16
            width, height, _, _, planes, bits, length, offset = struct.unpack(
                "<BBBBHHII", self.data[start : start + 16]
            )
            self.assertEqual((width, height), (size % 256, size % 256), f"{size} 档的宽高")
            self.assertEqual((planes, bits), (1, 32), f"{size} 档的位深")
            bitmap = self.data[offset : offset + length]
            header = struct.unpack("<IiiHH", bitmap[:16])
            # BITMAPINFOHEADER：40 字节、高记两倍（XOR 与 AND 两张摞着）、32 位
            self.assertEqual(header[:2], (40, size))
            self.assertEqual(header[2], size * 2)
            self.assertEqual(header[4], 32)
            # 位图 + AND 掩码（1 位一像素、行按 4 字节对齐）正好是这一档的长度
            mask_stride = ((size + 31) // 32) * 4
            self.assertEqual(length, 40 + size * size * 4 + mask_stride * size)


class PngShape(unittest.TestCase):
    """PNG：窗口与任务栏认这个，四角透、中间实心。"""

    def test_size_and_alpha(self):
        for size in (16, 64):
            width, height, rows = decode_png(png_bytes(size))
            self.assertEqual((width, height), (size, size))
            corner = rows[0][:4]
            self.assertEqual(corner[3], 0, "四角应当是透明的（金币是圆的）")
            # 币面上取一点（正中那条深色折线不算）：不透明、且是暖色
            coin = rows[size // 2][(size // 4) * 4 : (size // 4) * 4 + 4]
            self.assertEqual(coin[3], 255, "币面应当是不透明的")
            red, green, blue = coin[:3]
            self.assertEqual(max(coin[:3]), red, "金币是暖色：红分量最大")
            self.assertGreater(red, blue)

    def test_writes_the_drawn_shape(self):
        # 同一个形状画两次：字节一模一样（纯函数，没有随机与时间）
        self.assertEqual(png_bytes(32), png_bytes(32))
        self.assertEqual(ico_bytes(), ico_bytes())


class DrawnFromCode(unittest.TestCase):
    """不引图像库：这个模块只许用标准库。"""

    def test_only_stdlib(self):
        import ast
        from pathlib import Path

        source = Path(icon.__file__).read_text(encoding="utf-8")
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Import)
        } | {
            (node.module or "").split(".")[0]
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom)
        }
        self.assertEqual(imported - {"math", "struct", "zlib", "pathlib"}, set())


if __name__ == "__main__":
    unittest.main()
