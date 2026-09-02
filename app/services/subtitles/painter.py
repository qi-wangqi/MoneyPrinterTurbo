"""PIL 绘制原语：文字、描边、背景与透明度合成。

本模块只负责“把文字画成位图”，不知道时间和 cue；所有渲染（竖排、横排、
普通字幕块、背景板）共用这里，保证描边、留白和居中的口径一致。
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.services.subtitles import fonts
from app.services.subtitles.models import BackgroundStyle, Direction


# 竖排单列的宽度系数：列宽 = 字号 × 该系数 + 描边留白。系数里包含左右
# 呼吸空间，让相邻列互不粘连。
COLUMN_WIDTH_RATIO = 1.4


def new_canvas(width: float, height: float) -> Image.Image:
    """创建透明 RGBA 画布，尺寸向上取整且至少 1px。"""
    return Image.new(
        "RGBA",
        (max(1, math.ceil(width)), max(1, math.ceil(height))),
        (0, 0, 0, 0),
    )


def _stroke_padding(stroke_width: int) -> int:
    """描边向字形四周扩张需要的额外留白。"""
    return int(stroke_width * 2) + 4


def _draw_char(
    draw: ImageDraw.ImageDraw,
    position: tuple[float, float],
    char: str,
    font: ImageFont.FreeTypeFont,
    color: str,
    stroke_color: str,
    stroke_width: int,
) -> None:
    """在指定位置绘制单字（anchor=mm：以墨迹中心定位）。"""
    draw.text(
        position,
        char,
        font=font,
        fill=color,
        anchor="mm",
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
    )


def render_vertical_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    font_size: int,
    color: str,
    stroke_color: str,
    stroke_width: int,
    highlight_visible_index: int | None = None,
    highlight_stroke_color: str | None = None,
) -> Image.Image:
    """把一行文本渲染成一列竖排文字，返回贴合内容的透明位图。"""
    chars = [char for char in text if not char.isspace()]
    pad = _stroke_padding(stroke_width)
    width = int(font_size * COLUMN_WIDTH_RATIO + pad)
    height = fonts.vertical_advance_em(text) * font_size + pad
    canvas = new_canvas(width, height)
    draw = ImageDraw.Draw(canvas)
    y = pad / 2
    for visible_index, char in enumerate(chars):
        cell_height = fonts.char_advance_em(char) * font_size
        # 全角标点的墨迹偏向 em 框左下角，直接用锚点定位会被字体度量带偏。
        # 这里先测墨迹包围盒，再把墨迹中心精确放到目标位置。
        ink_left, ink_top, ink_right, ink_bottom = draw.textbbox(
            (0, 0), char, font=font, anchor="mm"
        )
        ink_offset = ((ink_left + ink_right) / 2, (ink_top + ink_bottom) / 2)
        if char in fonts.VERTICAL_COMPACT_PUNCT:
            # 标点压缩到半格、墨迹靠上偏右，紧贴前一个字。
            desired = (width * 0.64, y + cell_height * 0.32)
        else:
            desired = (width / 2, y + cell_height / 2)
        position = (desired[0] - ink_offset[0], desired[1] - ink_offset[1])
        current_stroke_color = (
            highlight_stroke_color or stroke_color
            if visible_index == highlight_visible_index
            else stroke_color
        )
        _draw_char(draw, position, char, font, color, current_stroke_color, stroke_width)
        y += cell_height
    return canvas


def render_horizontal_text(
    text: str,
    font: ImageFont.FreeTypeFont,
    font_size: int,
    color: str,
    stroke_color: str,
    stroke_width: int,
    highlight_visible_index: int | None = None,
    highlight_stroke_color: str | None = None,
) -> Image.Image:
    """把一行文本渲染成横排位图，返回贴合内容的透明位图。"""
    measure = ImageDraw.Draw(new_canvas(1, 1))
    text_width = measure.textlength(text, font=font)
    pad = _stroke_padding(stroke_width)
    width = text_width + pad
    height = font_size * fonts.CHAR_HEIGHT_RATIO + pad
    canvas = new_canvas(width, height)
    draw = ImageDraw.Draw(canvas)
    if highlight_visible_index is None:
        draw.text(
            (width / 2, height / 2),
            text,
            font=font,
            fill=color,
            anchor="mm",
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
        return canvas

    # 先按普通模式整串绘制，保证高亮图层与正常图层像素坐标完全一致；
    # 再把目标字按整串排版位置单独叠一次金色描边。不能逐字重绘整行，
    # 否则整串 advance 和逐字 advance 可能不一致，当前句会出现重影。
    draw.text(
        (width / 2, height / 2),
        text,
        font=font,
        fill=color,
        anchor="mm",
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
    )
    visible_index = 0
    for char_index, char in enumerate(text):
        char_width = draw.textlength(char, font=font)
        if not char.isspace():
            if visible_index == highlight_visible_index:
                prefix_width = draw.textlength(text[:char_index], font=font)
                left = (width - text_width) / 2.0
                char_center_x = left + prefix_width + char_width / 2.0
                draw.text(
                    (char_center_x, height / 2.0),
                    char,
                    font=font,
                    fill=color,
                    anchor="mm",
                    stroke_width=stroke_width,
                    stroke_fill=highlight_stroke_color or stroke_color,
                )
            visible_index += 1
    return canvas


def render_slots(
    chunks: list[str],
    font: ImageFont.FreeTypeFont,
    font_size: int,
    direction: Direction,
    color: str,
    stroke_color: str,
    stroke_width: int,
    highlight_visible_index: int | None = None,
    highlight_stroke_color: str | None = None,
) -> list[Image.Image]:
    """把一个 cue 拆分后的槽文本逐个渲染成位图。

    竖排方向渲染为列，横排方向渲染为行；槽的切分（layout.split_slots）
    与绘制分离，保证几何计算可以被单独测试。
    """
    if direction.is_vertical:
        return [
            render_vertical_text(
                chunk,
                font,
                font_size,
                color,
                stroke_color,
                stroke_width,
                highlight_visible_index=highlight_visible_index,
                highlight_stroke_color=highlight_stroke_color,
            )
            for chunk in chunks
        ]
    return [
        render_horizontal_text(
            chunk,
            font,
            font_size,
            color,
            stroke_color,
            stroke_width,
            highlight_visible_index=highlight_visible_index,
            highlight_stroke_color=highlight_stroke_color,
        )
        for chunk in chunks
    ]


def _draw_background(
    canvas: Image.Image,
    color: str,
    style: BackgroundStyle,
) -> None:
    """在画布上铺满字幕背景：实心矩形或圆角半透明。"""
    rgb = _hex_to_rgb(color)
    if style == BackgroundStyle.ROUNDED_TRANSLUCENT:
        alpha = 140
        radius = max(8, int(canvas.width * 0.06))
    else:
        alpha = 255
        radius = 0
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        [0, 0, max(0, canvas.width - 1), max(0, canvas.height - 1)],
        radius=radius,
        fill=(rgb[0], rgb[1], rgb[2], alpha),
    )


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    """字幕背景色来自 API/WebUI 参数，可能为空或格式不规范。

    统一只接受 #RRGGBB 形式，非法值回退为黑色，避免 PIL 渲染阶段抛出
    异常中断任务。
    """
    if isinstance(color, str) and color.startswith("#") and len(color) == 7:
        try:
            return (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        except ValueError:
            pass
    return (0, 0, 0)


def render_text_block(
    text: str,
    font_path: str,
    font_size: int,
    color: str,
    stroke_color: str,
    stroke_width: int,
    max_width: float,
    background_color: str | None = None,
    background_style: BackgroundStyle = BackgroundStyle.RECTANGLE,
) -> Image.Image:
    """渲染替换式字幕的一个内容块：折行 + 居中 + 可选背景。

    返回的位图就是内容块的视觉盒（visual box）：有背景时背景贴满整块，
    无背景时文字居中留出呼吸空间。调用方只需对齐这个盒，不再需要
    MoviePy TextClip 的度量修正。
    """
    font = fonts.load_font(font_path, font_size)
    has_background = bool(background_color)
    rounded = background_style == BackgroundStyle.ROUNDED_TRANSLUCENT
    # 圆角背景按文字真实宽度生成，左右留白更克制；矩形背景铺满可用宽度，
    # 保留较大安全边距，避免长字幕贴边。
    pad_ratio = 0.4 if rounded else 0.6
    pad_x = int(font_size * pad_ratio) if has_background else 0
    text_max_width = max(1, int(max_width) - 2 * pad_x)
    wrapped, _ = fonts.wrap_text(text, text_max_width, font_path, font_size)
    lines = wrapped.split("\n")

    row_height = fonts.line_height(font, font_size)
    interline = int(font_size * 0.25)
    stroke_pad = int(stroke_width * 2)
    # 行距 = 行高 + 行间距 + 双侧描边：Pillow 把描边计入墨迹范围，粗描边
    # 多行文本若不加双侧描边空间会互相粘连。
    pitch = row_height + interline + stroke_pad
    measure = ImageDraw.Draw(new_canvas(1, 1))
    text_w = max(
        (fonts.text_width(measure, line, font) for line in lines), default=0.0
    )
    text_h = (len(lines) - 1) * pitch + row_height + stroke_pad

    if has_background and rounded:
        box_w = max(1, min(int(max_width), int(text_w) + 2 * pad_x))
    else:
        box_w = max(1, int(max_width))
    # 无背景时用较小的垂直呼吸空间；有背景时保留较大内边距，避免文字
    # 看起来顶到底板边缘。
    vert_pad = int(font_size * (0.35 if has_background else 0.2))
    box_h = int(text_h + 2 * vert_pad)

    canvas = new_canvas(box_w, box_h)
    if has_background:
        _draw_background(canvas, background_color, background_style)

    draw = ImageDraw.Draw(canvas)
    ascent, _descent = font.getmetrics()
    first_baseline = vert_pad + stroke_width + ascent
    for index, line in enumerate(lines):
        baseline_y = first_baseline + index * pitch
        # anchor=ms：水平居中、垂直按 baseline 对齐。与 Pillow multiline
        # 的排版模型一致，避免含下伸部字符的行在墨迹居中时上下漂移。
        draw.text(
            (box_w / 2, baseline_y),
            line,
            font=font,
            fill=color,
            anchor="ms",
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
        )
    return canvas


def image_with_alpha(image: Image.Image, alpha: float) -> Image.Image:
    """按系数缩放位图透明度；alpha≈1 时直接返回原图避免拷贝。"""
    if alpha >= 0.999:
        return image
    frame = np.asarray(image).copy()
    frame[:, :, 3] = np.rint(frame[:, :, 3] * alpha).astype(np.uint8)
    return Image.fromarray(frame)


def paste_cropped(
    canvas: Image.Image,
    image: Image.Image,
    left: float,
    top: float,
    alpha: float,
) -> None:
    """把位图贴到画布上，超出画布的部分被裁掉（viewport 裁剪语义）。"""
    if alpha <= 0.0:
        return
    left_int = int(round(left))
    top_int = int(round(top))
    visible_left = max(0, left_int)
    visible_top = max(0, top_int)
    visible_right = min(canvas.width, left_int + image.width)
    visible_bottom = min(canvas.height, top_int + image.height)
    if visible_right <= visible_left or visible_bottom <= visible_top:
        return
    cropped = image.crop(
        (
            visible_left - left_int,
            visible_top - top_int,
            visible_right - left_int,
            visible_bottom - top_int,
        )
    )
    canvas.alpha_composite(image_with_alpha(cropped, alpha), (visible_left, visible_top))
