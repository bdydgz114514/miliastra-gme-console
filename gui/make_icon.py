r"""生成桌面快捷方式用的 icon.ico（零第三方依赖）。

不依赖 Qt / Pillow：自己用 zlib 写 PNG，再按 ICO 容器格式打包。
图形直接按像素画：深色圆角方块 + 麦克风轮廓 + 底部几条彩色状态线，
和 gui/assets/icon.svg 的配色保持一致。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

GUI_DIR = Path(__file__).resolve().parent
ICO = GUI_DIR / "assets" / "icon.ico"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)

# 与 widgets.py 的配色对齐
BG = (23, 26, 33)
BORDER = (42, 47, 58)
WHITE = (231, 234, 240)
ACCENT = (79, 140, 255)
OK = (62, 207, 142)
WARN = (240, 180, 41)
ERR = (242, 85, 90)


def _clamp_byte(value: float) -> int:
    return max(0, min(255, int(round(value))))


def blend(dst: tuple[int, int, int, int], src: tuple[int, int, int], alpha: float):
    """把 src 以 alpha 覆盖到 dst 上（简单的 source-over）。"""

    sr, sg, sb = src
    dr, dg, db, da = dst
    a = max(0.0, min(1.0, alpha))
    da_f = da / 255.0
    out_a = a + da_f * (1 - a)
    if out_a <= 0:
        return (0, 0, 0, 0)
    return (
        _clamp_byte((sr * a + dr * da_f * (1 - a)) / out_a),
        _clamp_byte((sg * a + dg * da_f * (1 - a)) / out_a),
        _clamp_byte((sb * a + db * da_f * (1 - a)) / out_a),
        _clamp_byte(out_a * 255),
    )


def rounded_rect_coverage(x: float, y: float, w: float, h: float, radius: float) -> float:
    """点 (x,y) 落在圆角矩形内的覆盖率（用距离做 1px 软边，够用）。"""

    cx = min(max(x, radius), w - radius)
    cy = min(max(y, radius), h - radius)
    dx = x - cx
    dy = y - cy
    dist = (dx * dx + dy * dy) ** 0.5
    if x < 0 or y < 0 or x > w or y > h:
        # 矩形外：还要看是否落在圆角外
        inside = (radius - dist) if (dx or dy) else 0
        return max(0.0, min(1.0, inside + 0.5))
    return max(0.0, min(1.0, (radius - dist) + 0.5))


def in_round_rect(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> float:
    """圆角矩形覆盖率的通用实现（支持任意位置）。"""

    if x < x0 - 1 or x > x1 + 1 or y < y0 - 1 or y > y1 + 1:
        return 0.0
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    dx = x - cx
    dy = y - cy
    dist = (dx * dx + dy * dy) ** 0.5
    return max(0.0, min(1.0, (r - dist) + 0.5))


def in_circle(x: float, y: float, cx: float, cy: float, r: float) -> float:
    dist = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
    return max(0.0, min(1.0, (r - dist) + 0.5))


def in_capsule(x: float, y: float, x0: float, y0: float, x1: float, y1: float, r: float) -> float:
    """胶囊（圆头线段）覆盖率。"""

    vx, vy = x1 - x0, y1 - y0
    wx, wy = x - x0, y - y0
    length2 = vx * vx + vy * vy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, (wx * vx + wy * vy) / length2))
    px, py = x0 + t * vx, y0 + t * vy
    dist = ((x - px) ** 2 + (y - py) ** 2) ** 0.5
    return max(0.0, min(1.0, (r - dist) + 0.5))


def render(size: int) -> bytearray:
    """按 4 倍超采样渲染，得到平滑边缘。"""

    ss = 4
    high = size * ss

    s = high / 128.0  # 设计稿基于 128x128
    margin = 4 * s
    radius = 26 * s

    # 麦克风几何（对应 SVG）
    mic_x0, mic_x1 = 48 * s, 80 * s
    mic_y0, mic_y1 = 20 * s, 76 * s
    mic_r = 16 * s
    arc_r = 30 * s
    arc_cx, arc_cy = 64 * s, 58 * s
    stem_y0, stem_y1 = 88 * s, 104 * s

    pixels = bytearray(high * high * 4)
    for py in range(high):
        for px in range(high):
            x = px + 0.5
            y = py + 0.5

            pixel = (0, 0, 0, 0)

            # 底板
            cover = in_round_rect(x, y, margin, margin, high - margin, high - margin, radius)
            if cover > 0:
                pixel = blend(pixel, BG, cover)
                # 边框：用「外圈减去内圈」
                inner = in_round_rect(
                    x, y, margin + 2 * s, margin + 2 * s, high - margin - 2 * s, high - margin - 2 * s, radius - 2 * s
                )
                border_cover = max(0.0, cover - inner)
                if border_cover > 0:
                    pixel = blend(pixel, BORDER, border_cover)

            # 麦克风主体（胶囊）
            body = in_capsule(
                x, y, (mic_x0 + mic_x1) / 2, mic_y0 + mic_r, (mic_x0 + mic_x1) / 2, mic_y1 - mic_r, (mic_x1 - mic_x0) / 2
            )
            if body > 0:
                pixel = blend(pixel, WHITE, body)

            # 拾音弧（用圆环截取下半部分）
            ring = in_circle(x, y, arc_cx, arc_cy, arc_r) - in_circle(x, y, arc_cx, arc_cy, arc_r - 8 * s)
            if ring > 0 and y > arc_cy:
                pixel = blend(pixel, ACCENT, max(0.0, min(1.0, ring)))

            # 支架
            stem = in_capsule(x, y, 64 * s, stem_y0, 64 * s, stem_y1, 4 * s)
            if stem > 0:
                pixel = blend(pixel, ACCENT, stem)

            # 底座横线（绿）+ 两侧状态线（黄/红）
            base = in_capsule(x, y, 46 * s, 104 * s, 82 * s, 104 * s, 4 * s)
            if base > 0:
                pixel = blend(pixel, OK, base)
            left = in_capsule(x, y, 30 * s, 104 * s, 38 * s, 104 * s, 3 * s)
            if left > 0:
                pixel = blend(pixel, WARN, left)
            right = in_capsule(x, y, 90 * s, 104 * s, 98 * s, 104 * s, 3 * s)
            if right > 0:
                pixel = blend(pixel, ERR, right)

            offset = (py * high + px) * 4
            pixels[offset : offset + 4] = bytes(pixel)

    # 降采样
    out = bytearray(size * size * 4)
    area = ss * ss
    for oy in range(size):
        for ox in range(size):
            r = g = b = a = 0
            for dy in range(ss):
                for dx in range(ss):
                    offset = ((oy * ss + dy) * high + (ox * ss + dx)) * 4
                    r += pixels[offset]
                    g += pixels[offset + 1]
                    b += pixels[offset + 2]
                    a += pixels[offset + 3]
            offset = (oy * size + ox) * 4
            out[offset : offset + 4] = bytes((r // area, g // area, b // area, a // area))
    return out


def png_encode(rgba: bytearray, size: int) -> bytes:
    """把 RGBA 像素编码成 PNG（8 位真彩 + alpha）。"""

    raw = bytearray()
    stride = size * 4
    for row in range(size):
        raw.append(0)  # filter type 0
        raw += rgba[row * stride : (row + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    entries = b""
    payload = b""
    offset = 6 + 16 * count
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        payload += data
        offset += len(data)
    return header + entries + payload


def main() -> int:
    images: list[tuple[int, bytes]] = []
    for size in SIZES:
        png = png_encode(render(size), size)
        images.append((size, png))
        print(f"  {size:>3}x{size:<3} PNG {len(png):>6} 字节")

    ICO.parent.mkdir(parents=True, exist_ok=True)
    ICO.write_bytes(build_ico(images))
    print(f"已生成 {ICO}（{len(SIZES)} 个尺寸，{ICO.stat().st_size} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
