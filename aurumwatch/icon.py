# -*- coding: utf-8 -*-
"""图标：用代码画出来，只依赖标准库（见 ticket 07）。

发布产物 `AurumWatch.exe` 在资源管理器里要一眼认得出来，所以图标得自己画；又不想
为一个图标引一个图像库，于是形状全部按**有向距离场**（SDF）算：距离直接换覆盖率，
边缘天然抗锯齿，也不必按几倍超采样去铺像素——256×256 那一档省下的时间最明显。

画的是「一枚金币 + 一条上行的行情折线」：金币是暖金（应用默认外观的取色），折线是
主窗口底色（深灰），末端那个点是涨破色。两个出口：构建脚本要的多尺寸 **ICO**（Explorer
的每种视图各取一档，不至于拿 16×16 去撑 256×256 的缩略图），以及窗口与任务栏要的
**PNG**——主窗口开窗时现画一张交给 Tk（`iconphoto` 直接吃 base64 的 PNG），不落盘，
exe 放在写不进去的目录里也照样有图标。
"""

import math
import struct
import zlib
from pathlib import Path

# 每一档都要：小的是列表与任务栏，大的是缩略图（256 是 Explorer 的大图标档）
SIZES = (16, 24, 32, 48, 64, 128, 256)

# 金币底色（斜向渐变的两端）、边缘那一圈暗金、折线（主窗口底色）、末端的点（涨破色）。
# 后两个与 `config.py` 的默认外观同色（`appearance.bg`／`appearance.rise`）：图标照默认
# 外观取色，用户把外观改花了也不动它——改了这两处的话，那两处也跟着看一眼
COIN_LIGHT = (0xF6, 0xD6, 0x7A)
COIN_DARK = (0xD1, 0x9A, 0x1F)
COIN_RIM = (0xA9, 0x76, 0x1A)
LINE = (0x1E, 0x1F, 0x22)
TIP = (0xE5, 0x53, 0x4B)

# 折线的控制点，画布坐标取 [-0.5, 0.5]（正 y 向下）：一段上行、一个小回摆、再上行，
# 末点即 TIP 那个点。回摆是留着的——一条直线上行看起来像斜杠，不像行情
CHART = ((-0.28, 0.14), (-0.10, -0.04), (0.00, 0.05), (0.25, -0.24))


def ico_bytes():
    """多尺寸 ICO 的字节（纯函数）：每个尺寸一张 32 位位图，Explorer 各取所需。"""
    images = [(size, _dib(_render(size), size)) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))  # reserved、type=图标、张数
    offset = len(header) + 16 * len(images)  # 目录之后紧接着就是各张位图
    entries = bytearray()
    for size, data in images:
        # 宽高写成 256 的余数：这一栏只有一字节，256 记作 0（ICO 格式的老规矩）
        entries += struct.pack(
            "<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    return header + bytes(entries) + b"".join(data for _, data in images)


def write_ico(path):
    """把图标写到文件（构建脚本调它；目录不存在就建）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ico_bytes())
    return path


def png_bytes(size):
    """一张 size×size 的 PNG（纯函数）：窗口与任务栏图标用，交给 Tk 的 `iconphoto`。

    走 PNG 而不是 ICO：Tk 只认位图与 PNG 数据，认不出 ICO；而 PNG 一趟 zlib 就能拼出来，
    仍是标准库。像素来自同一个 `_render`，窗口上那颗金币与 exe 上那颗是同一幅画。
    """
    pixels = _render(size)
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # 每行前面那个 filter 字节：0 = 不过滤
        for x in range(size):
            raw += bytes(pixels[y * size + x])
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + _chunk(b"IEND", b"")
    )


def _chunk(tag, data):
    """PNG 的一个数据块：长度 + 标签 + 数据 + CRC。"""
    return (
        struct.pack(">I", len(data)) + tag + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def _render(size):
    """画一张 size×size 的 RGBA 位图 → 自左到右、自上而下的像素序列。

    每个像素只取一个采样点：形状都是距离场，覆盖率由「离边缘还有多远」直接得出，
    比按几倍超采样再缩下来省一个数量级的时间，边缘一样是渐变的。
    """
    half = size / 2
    coin = size * 0.46  # 金币半径：留一圈透明，缩到 16 时也看得出是枚圆币
    rim = max(1.0, size * 0.05)  # 边缘那一圈暗金的宽度（小尺寸下至少一像素）
    stroke = max(1.0, size * 0.09)  # 折线的粗细
    tip = max(1.2, size * 0.08)  # 末端那个点（比折线略粗一点，看着像标在末梢上）
    points = [(x * size, y * size) for x, y in CHART]
    *_, last = points
    pixels = []
    for y in range(size):
        for x in range(size):
            px, py = x + 0.5 - half, y + 0.5 - half  # 像素中心，原点在画布正中
            radius = math.hypot(px, py)
            cover = _cover(radius - coin)
            if cover <= 0.0:
                pixels.append((0, 0, 0, 0))
                continue
            # 斜向渐变：左上亮、右下暗，币面才不是一块死板的黄
            color = _mix(COIN_LIGHT, COIN_DARK, _clamp((px + py) / (2 * coin) + 0.5))
            # 边缘压暗：靠边一像素内线性收到暗金，币的外圈看得出来
            edge = _clamp((radius - (coin - rim)) / rim)
            color = _mix(color, COIN_RIM, edge * 0.85)
            # 折线：到底边那段距离里取最近的一条
            distance = min(
                _segment_distance(px, py, start, end)
                for start, end in zip(points, points[1:], strict=False)
            )
            color = _mix(color, LINE, _cover(distance - stroke / 2))
            # 末端那个点（涨破色）：先折线后它，末梢才不被折线盖回去
            color = _mix(color, TIP, _cover(math.hypot(px - last[0], py - last[1]) - tip))
            pixels.append((*color, round(cover * 255)))
    return pixels


def _clamp(value):
    """把值收进 0–1（覆盖率、渐变量、压暗量都按这个口径）。"""
    return min(1.0, max(0.0, value))


def _cover(distance):
    """有向距离 → 覆盖率：负数在形状内，边缘那一像素里按距离过渡。"""
    return _clamp(0.5 - distance)


def _mix(base, top, amount):
    """把 top 按 amount（0–1）盖到 base 上，逐通道插值。"""
    if amount <= 0.0:
        return base
    return tuple(
        round(low + (high - low) * amount) for low, high in zip(base, top, strict=True)
    )


def _segment_distance(px, py, start, end):
    """点到线段的距离（折线的粗细就按它算）。"""
    ax, ay = start
    bx, by = end
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    # 投影落在段内则取垂距，落在两头则取到端点的距离（这样拐角是圆的）
    t = 0.0 if length_squared == 0 else ((px - ax) * dx + (py - ay) * dy) / length_squared
    t = min(1.0, max(0.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _dib(pixels, size):
    """一张位图在 ICO 里的形状：BITMAPINFOHEADER + 自下而上的 BGRA + AND 掩码。

    ICO 里的「位图」是 BITMAPINFOHEADER 打头、高度记作两倍（XOR 与 AND 两张摞着）、
    行序自下而上的 DIB。透明度交给 alpha 通道，AND 掩码全 0（老渲染器按它认透明，
    全 0 的意思是「一块都别丢」——真有透明的地方由 alpha 说了算）。
    """
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    body = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            red, green, blue, alpha = pixels[y * size + x]
            body += bytes((blue, green, red, alpha))
    mask_stride = ((size + 31) // 32) * 4  # 1 位一像素、行按 4 字节对齐
    return header + bytes(body) + bytes(mask_stride * size)
