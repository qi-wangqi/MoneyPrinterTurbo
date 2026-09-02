"""纯几何排版：viewport、字号适配、槽切分与对齐公式。

本模块不做任何像素绘制，只返回坐标与切分结果，可以脱离渲染单独测试。
所有“放得下怎么摆、放不下从哪边裁”的规则都定义在这里。
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from app.services.subtitles import fonts
from app.services.subtitles.models import (
    AlignH,
    AlignV,
    Direction,
    Margin,
    Viewport,
)


# 滚动内容之间的间距系数（相对正文字号），保证列/行之间有呼吸空间。
COLUMN_GAP_RATIO = 0.85
HEADER_BODY_GAP_RATIO = 1.0
# 自动字号下限：低于该字号的可读性很差，宁可换列/换行也不再缩小。
MIN_AUTO_FONT_SIZE = 24


def compute_viewport(margin: Margin, video_width: int, video_height: int) -> Viewport:
    """按百分比边距计算字幕视窗。

    top/bottom 相对视频高度，left/right 相对视频宽度；视窗是所有模式
    （替换、滚动、整块）共同的可用区域。
    """
    x = video_width * margin.left / 100.0
    y = video_height * margin.top / 100.0
    width = max(1.0, video_width - video_width * margin.left / 100.0 - video_width * margin.right / 100.0)
    height = max(1.0, video_height - video_height * margin.top / 100.0 - video_height * margin.bottom / 100.0)
    return Viewport(x=x, y=y, width=width, height=height)


def fit_font_size(
    lines: tuple[str, ...] | list[str],
    direction: Direction,
    base_font_size: int,
    stroke_width: int,
    viewport: Viewport,
    min_font_size: int = MIN_AUTO_FONT_SIZE,
) -> int:
    """在不小于下限的前提下缩小字号，让最长行放进视窗。

    竖排按最大纵向推进（em 合计）对高度约束；横排按最长行字符数对宽度
    约束。每轮按 0.92 收缩，直到放得下或到达下限。
    """
    font_size = max(min_font_size, int(base_font_size))
    padding = stroke_width * 2 + 4

    def fits(size: int) -> bool:
        if direction.is_vertical:
            max_advance = max(
                (fonts.vertical_advance_em(line) for line in lines),
                default=0.0,
            )
            return max_advance * size + padding <= viewport.height
        max_chars = max((len(line) for line in lines), default=0)
        return max_chars * size + padding <= viewport.width

    while font_size > min_font_size and not fits(font_size):
        font_size = max(min_font_size, int(font_size * 0.92))
    return font_size


def split_vertical_slots(text: str, font_size: int, available_height: float) -> list[str]:
    """把过长的文本按竖排推进预算切成多列（续列仍属于同一个 cue）。"""
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return []
    stroke_padding = 8
    budget = available_height - stroke_padding
    chunks: list[str] = []
    current = ""
    used = 0.0
    for char in chars:
        advance = fonts.char_advance_em(char) * font_size
        if current and used + advance > budget:
            chunks.append(current)
            current = char
            used = advance
        else:
            current += char
            used += advance
    if current:
        chunks.append(current)
    return chunks


def split_horizontal_slots(text: str, font: ImageFont.FreeTypeFont, available_width: float) -> list[str]:
    """把过长文本按字符宽度切成多行（滚动模式的续行切分）。

    与 fonts.wrap_text 不同：这里面向滚动模式，按字符逐个推进即可，
    不做词级换行和标点回拉。
    """
    if not text:
        return []
    measure = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    if measure.textlength(text, font=font) <= available_width:
        return [text]

    chunks = []
    current = ""
    for char in text:
        candidate = current + char
        if current and measure.textlength(candidate, font=font) > available_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def split_slots(
    text: str,
    direction: Direction,
    font: ImageFont.FreeTypeFont,
    font_size: int,
    viewport: Viewport,
) -> list[str]:
    """按方向把一个 cue 切成槽（竖排=列，横排=行）的文本序列。"""
    if direction.is_vertical:
        return split_vertical_slots(text, font_size, viewport.height)
    return split_horizontal_slots(text, font, viewport.width)


def align_box(
    viewport: Viewport,
    box_width: float,
    box_height: float,
    align_h: AlignH,
    align_v: AlignV,
) -> tuple[float, float]:
    """把内容块按用户对齐配置摆进视窗，返回块左上角坐标。

    对齐公式以块的实测视觉盒为准（不是假想的整块画布）；结果会 clamp
    回视窗内部，避免超大内容块摆到画面外。
    """
    if align_h == AlignH.LEFT:
        x = viewport.x
    elif align_h == AlignH.RIGHT:
        x = viewport.right - box_width
    else:
        x = viewport.x + (viewport.width - box_width) / 2.0

    if align_v == AlignV.TOP:
        y = viewport.y
    elif align_v == AlignV.BOTTOM:
        y = viewport.bottom - box_height
    else:
        y = viewport.y + (viewport.height - box_height) / 2.0

    x = max(viewport.x, min(x, viewport.right - box_width))
    y = max(viewport.y, min(y, viewport.bottom - box_height))
    return x, y
