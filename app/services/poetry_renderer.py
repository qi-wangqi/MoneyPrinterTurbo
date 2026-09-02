"""Render cumulative poetry subtitles without changing normal subtitle behavior."""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from moviepy import ImageClip, VideoClip
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.models.schema import VideoParams
from app.services import subtitle
from app.services.poetry import PoetryScript


class PoetryLayoutError(ValueError):
    pass


MIN_POETRY_FONT_SIZE = 24
CHAR_HEIGHT_RATIO = 1.32
COLUMN_WIDTH_RATIO = 1.4
COLUMN_GAP_RATIO = 0.85
HEADER_BODY_GAP_RATIO = 1.0
SLIDE_DURATION = 0.4
PUNCT_ADVANCE_RATIO = 0.55
VERTICAL_COMPACT_PUNCT = set("，。！？；：、,.!?;:")
LINE_FADE_IN_DURATION = 0.24
READING_ATTACK_DURATION = 0.08
READING_RELEASE_DURATION = 0.10
READING_PUNCT_HIGHLIGHT_ALPHA = 0.25
READING_STROKE_COLOR = "#F5C451"


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class BodyPieceLayout:
    image: Image.Image
    cue: SubtitleCue
    base_x: float
    base_y: float
    char_start: int
    char_count: int


@dataclass(frozen=True)
class OffsetState:
    start: float
    offset: float


def _parse_srt_time(value: str) -> float:
    try:
        hour_text, minute_text, second_text = value.strip().split(":")
        return int(hour_text) * 3600 + int(minute_text) * 60 + float(second_text.replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise PoetryLayoutError(f"invalid subtitle timestamp: {value}") from exc


def _read_subtitle_cues(subtitle_path: str) -> list[SubtitleCue]:
    raw_items = subtitle.file_to_subtitles(subtitle_path)
    cues = []
    for _, timing, text in raw_items:
        if " --> " not in timing:
            raise PoetryLayoutError(f"invalid subtitle timing: {timing}")
        start_text, end_text = timing.split(" --> ", 1)
        start = _parse_srt_time(start_text)
        end = _parse_srt_time(end_text)
        if end < start:
            raise PoetryLayoutError(f"subtitle end precedes start: {timing}")
        cues.append(SubtitleCue(start=start, end=end, text=text.strip()))
    return cues


def _normalize_for_match(value: str) -> str:
    return re.sub(r"[\W_]+", "", value or "", flags=re.UNICODE).lower()


def _validate_cues(cues: list[SubtitleCue], poetry_script: PoetryScript):
    expected_lines = poetry_script.all_lines
    if len(cues) != len(expected_lines):
        raise PoetryLayoutError(
            f"poetry subtitle cue count mismatch: expected {len(expected_lines)}, got {len(cues)}"
        )

    for cue, expected_text in zip(cues, expected_lines):
        if _normalize_for_match(cue.text) != _normalize_for_match(expected_text):
            raise PoetryLayoutError(
                f"poetry subtitle cue mismatch at {cue.start:.3f}s: expected "
                f"{expected_text!r}, got {cue.text!r}"
            )


def _load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    if not font_path or not os.path.isfile(font_path):
        raise PoetryLayoutError(f"subtitle font does not exist: {font_path}")
    return ImageFont.truetype(font_path, max(1, int(font_size)))


def _new_canvas(width: float, height: float) -> Image.Image:
    return Image.new(
        "RGBA",
        (max(1, math.ceil(width)), max(1, math.ceil(height))),
        (0, 0, 0, 0),
    )


def _draw_char(draw: ImageDraw.ImageDraw, position: tuple[float, float], char: str, font, color, stroke_color, stroke_width: int):
    draw.text(
        position,
        char,
        font=font,
        fill=color,
        anchor="mm",
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
    )


def _char_advance_em(char: str) -> float:
    """竖排里单个字符占用的字高（以字号为单位）。"""
    if char in VERTICAL_COMPACT_PUNCT:
        return PUNCT_ADVANCE_RATIO
    return CHAR_HEIGHT_RATIO


def _vertical_advance_em(text: str) -> float:
    return sum(_char_advance_em(char) for char in text if not char.isspace())


def _render_vertical_text(
    text: str,
    font,
    font_size: int,
    color: str,
    stroke_color: str,
    stroke_width: int,
    highlight_visible_index: int | None = None,
    highlight_stroke_color: str | None = None,
) -> Image.Image:
    chars = [char for char in text if not char.isspace()]
    stroke_padding = int(stroke_width * 2) + 4
    width = int(font_size * COLUMN_WIDTH_RATIO + stroke_padding)
    height = _vertical_advance_em(text) * font_size + stroke_padding
    canvas = _new_canvas(width, height)
    draw = ImageDraw.Draw(canvas)
    y = stroke_padding / 2
    for visible_index, char in enumerate(chars):
        cell_height = _char_advance_em(char) * font_size
        # 全角标点的墨迹偏向 em 框左下角，直接用锚点定位会被字体度量
        # 带偏。这里先测墨迹包围盒，再把墨迹中心精确放到目标位置。
        ink_left, ink_top, ink_right, ink_bottom = draw.textbbox(
            (0, 0), char, font=font, anchor="mm"
        )
        ink_offset = ((ink_left + ink_right) / 2, (ink_top + ink_bottom) / 2)
        if char in VERTICAL_COMPACT_PUNCT:
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


def _render_horizontal_text(
    text: str,
    font,
    font_size: int,
    color: str,
    stroke_color: str,
    stroke_width: int,
    highlight_visible_index: int | None = None,
    highlight_stroke_color: str | None = None,
) -> Image.Image:
    canvas = _new_canvas(1, 1)
    draw = ImageDraw.Draw(canvas)
    text_width = draw.textlength(text, font=font)
    stroke_padding = int(stroke_width * 2) + 4
    width = text_width + stroke_padding
    height = font_size * CHAR_HEIGHT_RATIO + stroke_padding
    canvas = _new_canvas(width, height)
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
    else:
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


def _fit_orthogonal_font_size(
    poetry_script: PoetryScript,
    params: VideoParams,
    safe_width: float,
    safe_height: float,
    direction: str,
) -> int:
    font_size = max(MIN_POETRY_FONT_SIZE, int(params.font_size))
    stroke_width = max(0, int(float(params.stroke_width or 0)))
    padding = stroke_width * 2 + 4

    def fits(size: int) -> bool:
        if direction in {"right_to_left", "left_to_right"}:
            max_advance = max(_vertical_advance_em(line) for line in poetry_script.all_lines)
            return max_advance * size + padding <= safe_height
        max_chars = max(len(line) for line in poetry_script.all_lines)
        return max_chars * size + padding <= safe_width

    while font_size > MIN_POETRY_FONT_SIZE and not fits(font_size):
        font_size = max(MIN_POETRY_FONT_SIZE, int(font_size * 0.92))
    return font_size


def _split_vertical_text(text: str, font_size: int, available_height: float) -> list[str]:
    chars = [char for char in text if not char.isspace()]
    if not chars:
        return []
    stroke_padding = 8
    budget = available_height - stroke_padding
    chunks: list[str] = []
    current = ""
    used = 0.0
    for char in chars:
        advance = _char_advance_em(char) * font_size
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


def _split_horizontal_text(text: str, font, available_width: float) -> list[str]:
    if not text:
        return []
    measure_canvas = Image.new("RGBA", (1, 1))
    measure_draw = ImageDraw.Draw(measure_canvas)
    if measure_draw.textlength(text, font=font) <= available_width:
        return [text]

    chunks = []
    current = ""
    for char in text:
        candidate = current + char
        if current and measure_draw.textlength(candidate, font=font) > available_width:
            chunks.append(current)
            current = char
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _render_text_group(
    text: str,
    font_size: int,
    direction: str,
    safe_width: float,
    safe_height: float,
    font_path: str,
    color: str,
    stroke_color: str,
    stroke_width: int,
    highlight_visible_index: int | None = None,
    highlight_stroke_color: str | None = None,
) -> list[Image.Image]:
    font = _load_font(font_path, font_size)
    if direction in {"right_to_left", "left_to_right"}:
        chunks = _split_vertical_text(text, font_size, safe_height)
        return [
            _render_vertical_text(
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

    chunks = _split_horizontal_text(text, font, safe_width)
    return [
        _render_horizontal_text(
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


def _margins(params: VideoParams, video_width: int, video_height: int) -> tuple[float, float, float, float]:
    return (
        video_height * float(params.poetry_margin_top) / 100.0,
        video_height * float(params.poetry_margin_bottom) / 100.0,
        video_width * float(params.poetry_margin_left) / 100.0,
        video_width * float(params.poetry_margin_right) / 100.0,
    )


def _eased_progress(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return 0.5 * (1.0 - math.cos(math.pi * value))


def _sliding_position(
    states: list[OffsetState],
    time: float,
    slide_duration: float = SLIDE_DURATION,
) -> float:
    if not states:
        return 0.0

    state_index = 0
    for index, state in enumerate(states):
        if state.start <= time:
            state_index = index
        else:
            break

    current = states[state_index]
    start_offset = states[state_index - 1].offset if state_index > 0 else 0.0

    # 如果两个 cue 靠得很近，上一次滑动还没结束，就从上一次动画
    # 在当前 cue.start 时的实际位置继续滑，避免位置跳变。
    if state_index > 0:
        previous = states[state_index - 1]
        previous_elapsed = current.start - previous.start
        if previous_elapsed < slide_duration:
            before_previous = states[state_index - 2].offset if state_index > 1 else 0.0
            progress = previous_elapsed / slide_duration
            start_offset = before_previous + (previous.offset - before_previous) * _eased_progress(progress)

    progress = (time - current.start) / slide_duration
    return start_offset + (current.offset - start_offset) * _eased_progress(progress)


def _reading_timings(text: str, cue: SubtitleCue) -> list[tuple[float, float]]:
    """按 cue 时长估算每个可见字的朗读时间。"""
    chars = [char for char in text if not char.isspace()]
    if not chars or cue.end <= cue.start:
        return []

    weights = [
        PUNCT_ADVANCE_RATIO if char in VERTICAL_COMPACT_PUNCT else 1.0
        for char in chars
    ]
    total_weight = sum(weights)
    duration = cue.end - cue.start
    timings: list[tuple[float, float]] = []
    elapsed = 0.0
    for char, weight in zip(chars, weights):
        char_duration = duration * weight / total_weight
        timings.append((cue.start + elapsed, cue.start + elapsed + char_duration))
        elapsed += char_duration
    return timings


def _highlight_alpha(
    time: float,
    char_start: float,
    char_end: float,
    attack: float = READING_ATTACK_DURATION,
    release: float = READING_RELEASE_DURATION,
) -> float:
    if time < char_start or time >= char_end + release:
        return 0.0
    if time < char_start + attack:
        return (time - char_start) / attack
    if time < char_end:
        return 1.0
    return 1.0 - (time - char_end) / release


def _piece_exit_alpha(
    piece: BodyPieceLayout,
    offset: float,
    direction: str,
    body_origin: float,
) -> float:
    """旧内容越过视窗时按自身跨度淡出，而不是瞬间整块隐藏。"""
    if direction == "right_to_left":
        overflow = piece.base_x + piece.image.width + offset - body_origin
        fade_span = max(1.0, piece.image.width)
    elif direction == "left_to_right":
        overflow = body_origin - (piece.base_x - offset + piece.image.width)
        fade_span = max(1.0, piece.image.width)
    else:
        overflow = body_origin - (piece.base_y - offset + piece.image.height)
        fade_span = max(1.0, piece.image.height)

    return max(0.0, min(1.0, 1.0 - overflow / fade_span))


def build_poetry_overlays(
    subtitle_path: str,
    poetry_script: PoetryScript,
    params: VideoParams,
    video_width: int,
    video_height: int,
    audio_duration: float,
    font_path: str,
) -> list[VideoClip]:
    if audio_duration <= 0:
        raise PoetryLayoutError("audio duration must be positive")

    cues = _read_subtitle_cues(subtitle_path)
    _validate_cues(cues, poetry_script)

    direction = params.poetry_direction
    margin_top, margin_bottom, margin_left, margin_right = _margins(params, video_width, video_height)
    safe_x = margin_left
    safe_y = margin_top
    safe_width = max(1.0, video_width - margin_left - margin_right)
    safe_height = max(1.0, video_height - margin_top - margin_bottom)
    safe_right = safe_x + safe_width

    color = str(params.text_fore_color or "#FFFFFF")
    stroke_color = str(params.stroke_color or "#000000")
    stroke_width = max(0, int(float(params.stroke_width or 0)))
    body_font_size = _fit_orthogonal_font_size(poetry_script, params, safe_width, safe_height, direction)
    title_font_size = int(body_font_size * 1.15)
    author_font_size = int(body_font_size * 0.72)
    header_gap = max(12.0, body_font_size * HEADER_BODY_GAP_RATIO)
    piece_gap = max(6.0, body_font_size * COLUMN_GAP_RATIO)

    def piece_size(image: Image.Image) -> float:
        return image.width if direction != "top_to_bottom" else image.height

    def group_span(images: list[Image.Image]) -> float:
        if not images:
            return 0.0
        return sum(piece_size(image) for image in images) + piece_gap * (len(images) - 1)

    def cross_base(image: Image.Image) -> float:
        """交叉轴居中：竖排列垂直居中，横排行水平居中。"""
        if direction == "top_to_bottom":
            return safe_x + (safe_width - image.width) / 2.0
        return safe_y + (safe_height - image.height) / 2.0

    title_images = _render_text_group(
        poetry_script.title,
        title_font_size,
        direction,
        safe_width,
        safe_height,
        font_path,
        color,
        stroke_color,
        stroke_width,
    )
    author_images = _render_text_group(
        poetry_script.author,
        author_font_size,
        direction,
        safe_width,
        safe_height,
        font_path,
        color,
        stroke_color,
        stroke_width,
    )

    def layout_group(images: list[Image.Image]) -> tuple[Image.Image, tuple[float, float]]:
        positions: list[tuple[float, float]] = []
        if direction == "right_to_left":
            cursor = group_span(images)
            for image in images:
                cursor -= image.width
                positions.append((cursor, cross_base(image)))
        elif direction == "left_to_right":
            cursor = 0.0
            for image in images:
                positions.append((cursor, cross_base(image)))
                cursor += image.width + piece_gap
        else:
            cursor = 0.0
            for image in images:
                positions.append((cross_base(image), cursor))
                cursor += image.height + piece_gap

        min_x = min(position[0] for position in positions)
        min_y = min(position[1] for position in positions)
        max_x = max(position[0] + image.width for image, position in zip(images, positions))
        max_y = max(position[1] + image.height for image, position in zip(images, positions))
        canvas = _new_canvas(max_x - min_x, max_y - min_y)
        for image, position in zip(images, positions):
            canvas.alpha_composite(
                image,
                (int(round(position[0] - min_x)), int(round(position[1] - min_y))),
            )
        return canvas, (min_x, min_y)

    title_canvas, title_origin = layout_group(title_images)
    author_canvas, author_origin = layout_group(author_images)

    body_cues = cues[poetry_script.metadata_line_count :]
    body_image_groups = [
        _render_text_group(
            line,
            body_font_size,
            direction,
            safe_width,
            safe_height,
            font_path,
            color,
            stroke_color,
            stroke_width,
        )
        for line in poetry_script.poem_lines
    ]

    header_span = piece_size(title_canvas) + header_gap + piece_size(author_canvas) + header_gap
    body_total_span = (
        sum(group_span(images) for images in body_image_groups)
        + piece_gap * max(0, len(body_image_groups) - 1)
    )
    content_total = header_span + body_total_span
    main_capacity = safe_width if direction != "top_to_bottom" else safe_height
    if content_total <= main_capacity:
        content_offset = (main_capacity - content_total) / 2.0
    else:
        content_offset = 0.0

    if direction == "right_to_left":
        content_right = safe_right - content_offset
        title_position = (
            content_right - title_canvas.width,
            title_origin[1],
        )
        author_right = content_right - title_canvas.width - header_gap
        author_position = (
            author_right - author_canvas.width,
            author_origin[1],
        )
        body_origin = content_right - header_span
        body_capacity = body_origin - safe_x
        viewport_x = safe_x
        viewport_y = safe_y
        viewport_width = body_capacity
        viewport_height = safe_height
    elif direction == "left_to_right":
        content_left = safe_x + content_offset
        title_position = (
            content_left,
            title_origin[1],
        )
        author_position = (
            content_left + title_canvas.width + header_gap,
            author_origin[1],
        )
        body_origin = content_left + header_span
        body_capacity = safe_right - body_origin
        viewport_x = body_origin
        viewport_y = safe_y
        viewport_width = body_capacity
        viewport_height = safe_height
    else:
        content_top = safe_y + content_offset
        title_position = (
            title_origin[0],
            content_top,
        )
        author_position = (
            author_origin[0],
            content_top + title_canvas.height + header_gap,
        )
        body_origin = content_top + header_span
        body_capacity = (safe_y + safe_height) - body_origin
        viewport_x = safe_x
        viewport_y = body_origin
        viewport_width = safe_width
        viewport_height = body_capacity

    if body_capacity <= 0:
        raise PoetryLayoutError("poetry margins leave no room for poem lines")

    body_layouts: list[list[BodyPieceLayout]] = []
    line_extents: list[tuple[float, float]] = []
    line_before = 0.0
    body_font = _load_font(font_path, body_font_size)
    for line_index, (cue, line, images) in enumerate(
        zip(body_cues, poetry_script.poem_lines, body_image_groups)
    ):
        piece_before = 0.0
        line_pieces: list[BodyPieceLayout] = []
        if direction in {"right_to_left", "left_to_right"}:
            chunks = _split_vertical_text(line, body_font_size, safe_height)
            char_starts = []
            visible_start = 0
            for chunk in chunks:
                char_starts.append(visible_start)
                visible_start += len(chunk)
        else:
            chunks = _split_horizontal_text(line, body_font, safe_width)
            char_starts = []
            visible_start = 0
            for chunk in chunks:
                char_starts.append(visible_start)
                visible_start += sum(not char.isspace() for char in chunk)

        if len(chunks) != len(images):
            raise PoetryLayoutError("poetry body split/render count mismatch")

        for image_index, image in enumerate(images):
            if direction == "right_to_left":
                base_x = body_origin - line_before - piece_before - image.width
                base_y = cross_base(image)
            elif direction == "left_to_right":
                base_x = body_origin + line_before + piece_before
                base_y = cross_base(image)
            else:
                base_x = cross_base(image)
                base_y = body_origin + line_before + piece_before

            if direction in {"right_to_left", "left_to_right"}:
                char_count = len(chunks[image_index])
            else:
                char_count = sum(not char.isspace() for char in chunks[image_index])
            line_pieces.append(
                BodyPieceLayout(
                    image=image,
                    cue=cue,
                    base_x=base_x,
                    base_y=base_y,
                    char_start=char_starts[image_index],
                    char_count=char_count,
                )
            )
            piece_before += piece_size(image)
            if image_index < len(images) - 1:
                piece_before += piece_gap

        item_span = group_span(images)
        line_extents.append((line_before, line_before + item_span))
        body_layouts.append(line_pieces)
        line_before += item_span + piece_gap

    offset_states = [
        OffsetState(start=cue.start, offset=max(0.0, extent_end - body_capacity))
        for cue, (_, extent_end) in zip(body_cues, line_extents)
    ]
    body_timings = [
        _reading_timings(line, cue)
        for cue, line in zip(body_cues, poetry_script.poem_lines)
    ]

    viewport_width = max(1, int(math.ceil(viewport_width)))
    viewport_height = max(1, int(math.ceil(viewport_height)))
    viewport_position = (
        viewport_x if direction != "left_to_right" else body_origin,
        safe_y if direction != "top_to_bottom" else body_origin,
    )
    piece_variant_cache: dict[tuple[int, int, int], Image.Image] = {}

    def get_body_piece(
        line_index: int,
        piece_index: int,
        highlight_visible_index: int | None,
    ) -> Image.Image:
        if highlight_visible_index is None:
            return body_layouts[line_index][piece_index].image

        cache_key = (line_index, piece_index, highlight_visible_index)
        if cache_key not in piece_variant_cache:
            variants = _render_text_group(
                poetry_script.poem_lines[line_index],
                body_font_size,
                direction,
                safe_width,
                safe_height,
                font_path,
                color,
                stroke_color,
                stroke_width,
                highlight_visible_index=highlight_visible_index,
                highlight_stroke_color=READING_STROKE_COLOR,
            )
            if piece_index >= len(variants):
                raise PoetryLayoutError("poetry highlight piece index out of range")
            piece_variant_cache[cache_key] = variants[piece_index]
        return piece_variant_cache[cache_key]

    def image_with_alpha(image: Image.Image, alpha: float) -> Image.Image:
        if alpha >= 0.999:
            return image
        frame = np.asarray(image).copy()
        frame[:, :, 3] = np.rint(frame[:, :, 3] * alpha).astype(np.uint8)
        return Image.fromarray(frame)

    def paste_piece(
        canvas: Image.Image,
        image: Image.Image,
        left: float,
        top: float,
        alpha: float,
    ) -> None:
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

    def piece_local_position(piece: BodyPieceLayout, offset: float) -> tuple[float, float]:
        if direction == "right_to_left":
            return piece.base_x + offset - viewport_x, piece.base_y - viewport_y
        if direction == "left_to_right":
            return piece.base_x - offset - viewport_x, piece.base_y - viewport_y
        return piece.base_x - viewport_x, piece.base_y - offset - viewport_y

    def render_body_frame(time: float) -> np.ndarray:
        canvas = _new_canvas(viewport_width, viewport_height)
        offset = _sliding_position(offset_states, time, SLIDE_DURATION)

        for line_index, cue in enumerate(body_cues):
            if time < cue.start:
                continue
            line_alpha = _eased_progress((time - cue.start) / LINE_FADE_IN_DURATION)
            if line_alpha <= 0.0:
                continue
            for piece_index, piece in enumerate(body_layouts[line_index]):
                left, top = piece_local_position(piece, offset)
                paste_piece(
                    canvas,
                    piece.image,
                    left,
                    top,
                    line_alpha * _piece_exit_alpha(piece, offset, direction, body_origin),
                )

        attack = READING_ATTACK_DURATION
        release = READING_RELEASE_DURATION
        for line_index, cue in enumerate(body_cues):
            if time < cue.start or time > cue.end + release:
                continue
            line_alpha = _eased_progress((time - cue.start) / LINE_FADE_IN_DURATION)
            if line_alpha <= 0.0 or not body_timings[line_index]:
                continue

            visible_chars = [
                char for char in poetry_script.poem_lines[line_index] if not char.isspace()
            ]
            for piece_index, piece in enumerate(body_layouts[line_index]):
                left, top = piece_local_position(piece, offset)
                exit_alpha = _piece_exit_alpha(piece, offset, direction, body_origin)
                if exit_alpha <= 0.0:
                    continue
                for local_index in range(piece.char_count):
                    char_index = piece.char_start + local_index
                    if char_index >= len(body_timings[line_index]) or char_index >= len(visible_chars):
                        continue
                    char_start, char_end = body_timings[line_index][char_index]
                    highlight_alpha = _highlight_alpha(time, char_start, char_end)
                    if visible_chars[char_index] in VERTICAL_COMPACT_PUNCT:
                        highlight_alpha *= READING_PUNCT_HIGHLIGHT_ALPHA
                    if highlight_alpha <= 0.0:
                        continue
                    highlighted = get_body_piece(line_index, piece_index, char_index)
                    paste_piece(
                        canvas,
                        highlighted,
                        left,
                        top,
                        line_alpha * exit_alpha * highlight_alpha,
                    )

        return np.asarray(canvas)

    body_frame_cache: dict[float, np.ndarray] = {}

    def cached_body_frame(time: float) -> np.ndarray:
        key = round(float(time), 6)
        if key not in body_frame_cache:
            if len(body_frame_cache) >= 4:
                body_frame_cache.clear()
            body_frame_cache[key] = render_body_frame(key)
        return body_frame_cache[key]

    body_clip = VideoClip(
        frame_function=lambda time: cached_body_frame(time)[:, :, :3],
        duration=audio_duration,
    )
    body_mask = VideoClip(
        frame_function=lambda time: cached_body_frame(time)[:, :, 3].astype(float) / 255.0,
        is_mask=True,
        duration=audio_duration,
    )
    body_clip = (
        body_clip.with_mask(body_mask)
        .with_start(0.0)
        .with_end(audio_duration)
        .with_duration(audio_duration)
        .with_position(viewport_position)
    )

    title_clip = (
        ImageClip(np.asarray(title_canvas))
        .with_start(0.0)
        .with_end(audio_duration)
        .with_duration(audio_duration)
        .with_position(title_position)
    )
    author_clip = (
        ImageClip(np.asarray(author_canvas))
        .with_start(0.0)
        .with_end(audio_duration)
        .with_duration(audio_duration)
        .with_position(author_position)
    )
    return [title_clip, author_clip, body_clip]
