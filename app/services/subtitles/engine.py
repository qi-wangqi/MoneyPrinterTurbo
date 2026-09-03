"""字幕渲染引擎：把排版结果变成随时间变化的透明视频图层。

引擎按显示行为分三种，全部由 SubtitleConfig.subtitle_show_mode 驱动：
- replace：逐条 cue 替换显示（普通字幕的标点/整句模式）；
- scroll：连续滚动，已出现内容累积，cue 按方向锚点滑动，超出视窗按自身跨度淡出裁剪；
- block：整块常驻，全文作为一个内容块显示。

引擎只消费 config / layout / painter 的输出，不知道“诗歌”或“普通”
的场景概念。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from moviepy import ImageClip, VideoClip
from PIL import Image

from app.services.subtitles import fonts, layout, painter
from app.models.exception import SubtitleException
from app.models.schema import (
    SubtitleAlignH,
    SubtitleAlignV,
    SubtitleBackgroundStyle,
    SubtitleDirection,
    SubtitleShowMode,
)
from app.services.subtitles.models import SubtitleCue, SubtitleScriptInfo

if TYPE_CHECKING:
    from app.services.subtitles.config import SubtitleConfig


# 阅读高亮（逐字金色描边）的时间参数：起笔、收笔的渐变时长与标点减淡。
SUBTITLE_READING_ATTACK_DURATION = 0.08
SUBTITLE_RELEASE_DURATION = 0.10
SUBTITLE_PUNCT_HIGHLIGHT_ALPHA = 0.25
SUBTITLE_READING_STROKE_COLOR = "#F5C451"

# 滚动模式头部行的字号比例（相对正文字号）：诗名大于正文、作者小于正文。
SUBTITLE_HEADER_FONT_RATIO = 1.15
SUBTITLE_SUBHEADER_FONT_RATIO = 0.72


@dataclass(frozen=True)
class SubtitleScrollOffsetState:
    """滚动偏移状态：某 cue 开始时刻对应的连续滚动偏移（像素）。"""

    start: float
    offset: float


@dataclass(frozen=True)
class SubtitleSlotLayout:
    """正文中一个槽（列/行）的渲染结果与基准位置。"""

    image: Image.Image
    cue: SubtitleCue
    base_x: float
    base_y: float
    char_start: int
    char_count: int


def eased_progress(value: float) -> float:
    """缓动曲线：0→1 映射到余弦缓入缓出，用于淡入与滑动。"""
    value = max(0.0, min(1.0, value))
    return 0.5 * (1.0 - math.cos(math.pi * value))


def sliding_position(
    states: list[SubtitleScrollOffsetState],
    time: float,
    subtitle_slide_duration: float,
) -> float:
    """按 cue 时间轴计算当前滚动偏移（像素）。"""
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
        if previous_elapsed < subtitle_slide_duration:
            before_previous = states[state_index - 2].offset if state_index > 1 else 0.0
            progress = previous_elapsed / subtitle_slide_duration
            start_offset = before_previous + (
                previous.offset - before_previous
            ) * eased_progress(progress)

    progress = (time - current.start) / subtitle_slide_duration
    return start_offset + (current.offset - start_offset) * eased_progress(progress)


def reading_timings(text: str, cue: SubtitleCue) -> list[tuple[float, float]]:
    """按 cue 时长估算每个可见字的朗读时间区间。"""
    chars = [char for char in text if not char.isspace()]
    if not chars or cue.end <= cue.start:
        return []

    weights = [
        fonts.SUBTITLE_PUNCT_ADVANCE_RATIO
        if char in fonts.SUBTITLE_VERTICAL_COMPACT_PUNCT
        else 1.0
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


def highlight_alpha(
    time: float,
    char_start: float,
    char_end: float,
    attack: float = SUBTITLE_READING_ATTACK_DURATION,
    release: float = SUBTITLE_RELEASE_DURATION,
) -> float:
    """逐字高亮的透明度包络：attack 渐亮、保持、release 渐灭。"""
    if time < char_start or time >= char_end + release:
        return 0.0
    if time < char_start + attack:
        return (time - char_start) / attack
    if time < char_end:
        return 1.0
    return 1.0 - (time - char_end) / release


def _piece_exit_alpha(
    piece: SubtitleSlotLayout,
    offset: float,
    direction: SubtitleDirection,
    body_origin: float,
) -> float:
    """旧内容越过视窗时按自身跨度淡出，而不是瞬间整块隐藏。"""
    if direction == SubtitleDirection.vertical_rtl:
        overflow = piece.base_x + piece.image.width + offset - body_origin
        fade_span = max(1.0, piece.image.width)
    elif direction == SubtitleDirection.vertical_ltr:
        overflow = body_origin - (piece.base_x - offset + piece.image.width)
        fade_span = max(1.0, piece.image.width)
    else:
        overflow = body_origin - (piece.base_y - offset + piece.image.height)
        fade_span = max(1.0, piece.image.height)

    return max(0.0, min(1.0, 1.0 - overflow / fade_span))


def build_overlays(
    config: SubtitleConfig,
    script: SubtitleScriptInfo,
    cues: list[SubtitleCue],
    font_path: str,
    video_width: int,
    video_height: int,
    audio_duration: float,
) -> list[VideoClip]:
    """引擎入口：按显示行为分发到对应的时间轴构建器。"""
    if audio_duration <= 0:
        raise SubtitleException("audio duration must be positive")
    if config.subtitle_show_mode == SubtitleShowMode.scroll:
        return _build_scroll_overlays(
            config, script, cues, font_path, video_width, video_height, audio_duration
        )
    if config.subtitle_show_mode == SubtitleShowMode.block:
        return _build_block_overlays(
            config, script, font_path, video_width, video_height, audio_duration
        )
    return _build_replace_overlays(
        config, cues, font_path, video_width, video_height, audio_duration
    )


def _fade_alpha(time: float, cue: SubtitleCue, fade_duration: float) -> float:
    """cue 开始后的淡入透明度；未配置淡入时恒为 1（保持旧行为）。"""
    if fade_duration <= 0:
        return 1.0
    return eased_progress((time - cue.start) / fade_duration)


def _overlay_clip(
    frame_function,
    size: tuple[int, int],
    position: tuple[float, float],
    duration: float,
) -> VideoClip:
    """把帧函数包装成带透明通道、定位好的 MoviePy 图层。"""
    clip = VideoClip(
        frame_function=lambda time: frame_function(time)[:, :, :3],
        duration=duration,
    )
    mask = VideoClip(
        frame_function=lambda time: frame_function(time)[:, :, 3].astype(float) / 255.0,
        is_mask=True,
        duration=duration,
    )
    return (
        clip.with_mask(mask)
        .with_start(0.0)
        .with_end(duration)
        .with_duration(duration)
        .with_position(position)
    )


# ---------------------------------------------------------------------------
# 滚动行为（连续滚动；已出现内容累积）
# ---------------------------------------------------------------------------


def _build_scroll_overlays(
    config: SubtitleConfig,
    script: SubtitleScriptInfo,
    cues: list[SubtitleCue],
    font_path: str,
    video_width: int,
    video_height: int,
    audio_duration: float,
) -> list[VideoClip]:
    """构建连续滚动图层：固定头部层 + 正文视窗层。

    正文按 cue 累积显示：放得下时整组按方向锚点排列并整体居中；放不下
    时从方向锚点贴边，随 cue 触发滑动，旧内容在视窗边缘被裁剪并淡出。
    """
    direction = config.subtitle_direction
    viewport = layout.compute_viewport(
        config.subtitle_margin, video_width, video_height
    )
    stroke_width = config.subtitle_stroke_width_int
    text_color = config.subtitle_text_color
    stroke_color = config.subtitle_stroke_color

    if config.subtitle_auto_fit_font_size_enabled:
        body_font_size = layout.fit_font_size(
            script.all_lines,
            direction,
            config.subtitle_font_size,
            stroke_width,
            viewport,
            font_path=font_path,
            subtitle_min_font_size=config.subtitle_min_font_size,
        )
    else:
        body_font_size = max(1, int(config.subtitle_font_size))
    title_font_size = int(body_font_size * SUBTITLE_HEADER_FONT_RATIO)
    author_font_size = int(body_font_size * SUBTITLE_SUBHEADER_FONT_RATIO)
    header_gap = max(12.0, body_font_size * layout.SUBTITLE_HEADER_BODY_GAP_RATIO)
    piece_gap = max(6.0, body_font_size * layout.SUBTITLE_COLUMN_GAP_RATIO)
    body_font = fonts.load_font(font_path, body_font_size)

    def piece_size(image: Image.Image) -> float:
        """槽在主轴上的跨度：竖排（列）取宽、横排（行）取高。"""
        return image.width if direction.is_vertical else image.height

    def group_span(images: list[Image.Image]) -> float:
        """一组槽（含间距）在主轴上的总跨度。"""
        if not images:
            return 0.0
        return sum(piece_size(image) for image in images) + piece_gap * (
            len(images) - 1
        )

    def cross_base(image: Image.Image) -> float:
        """交叉轴按用户对齐放置：横排行读 align_h，竖排列读 align_v。"""
        if direction == SubtitleDirection.horizontal:
            align_h = config.subtitle_align_h
            if align_h == SubtitleAlignH.left:
                return viewport.x
            if align_h == SubtitleAlignH.right:
                return viewport.right - image.width
            return viewport.x + (viewport.width - image.width) / 2.0

        align_v = config.subtitle_align_v
        if align_v == SubtitleAlignV.top:
            return viewport.y
        if align_v == SubtitleAlignV.bottom:
            return viewport.bottom - image.height
        return viewport.y + (viewport.height - image.height) / 2.0

    def render_group(
        text: str,
        font_size: int,
        highlight_visible_index: int | None = None,
    ) -> list[Image.Image]:
        """把一行文本切成槽并渲染成位图列表。"""
        group_font = (
            body_font
            if font_size == body_font_size
            else fonts.load_font(font_path, font_size)
        )
        chunks = layout.split_slots(text, direction, group_font, font_size, viewport)
        return painter.render_slots(
            chunks,
            group_font,
            font_size,
            direction,
            text_color,
            stroke_color,
            stroke_width,
            highlight_visible_index=highlight_visible_index,
            highlight_stroke_color=SUBTITLE_READING_STROKE_COLOR,
        )

    def layout_group(
        images: list[Image.Image],
    ) -> tuple[Image.Image, tuple[float, float]]:
        """把一组槽合并成一张画布，返回 (画布, 组内第一个槽的基准坐标)。"""
        if not images:
            return painter.new_canvas(1, 1), (0.0, 0.0)

        positions: list[tuple[float, float]] = []
        if direction == SubtitleDirection.vertical_rtl:
            cursor = group_span(images)
            for image in images:
                cursor -= image.width
                positions.append((cursor, cross_base(image)))
        elif direction == SubtitleDirection.vertical_ltr:
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
        max_x = max(
            position[0] + image.width for image, position in zip(images, positions)
        )
        max_y = max(
            position[1] + image.height for image, position in zip(images, positions)
        )
        canvas = painter.new_canvas(max_x - min_x, max_y - min_y)
        for image, position in zip(images, positions):
            canvas.alpha_composite(
                image,
                (int(round(position[0] - min_x)), int(round(position[1] - min_y))),
            )
        return canvas, (min_x, min_y)

    title_images = render_group(script.title, title_font_size) if script.title else []
    author_images = (
        render_group(script.author, author_font_size) if script.author else []
    )
    title_canvas, title_origin = layout_group(title_images)
    author_canvas, author_origin = layout_group(author_images)

    # 横排的“诗名 作者”属于同一个固定头部行；竖排才按两个头部列排布。
    horizontal_header_canvas: Image.Image | None = None
    if direction == SubtitleDirection.horizontal and title_images and author_images:
        horizontal_header_canvas = painter.new_canvas(
            title_canvas.width + header_gap + author_canvas.width,
            max(title_canvas.height, author_canvas.height),
        )
        horizontal_header_canvas.alpha_composite(
            title_canvas,
            (0, int((horizontal_header_canvas.height - title_canvas.height) / 2)),
        )
        horizontal_header_canvas.alpha_composite(
            author_canvas,
            (
                int(title_canvas.width + header_gap),
                int((horizontal_header_canvas.height - author_canvas.height) / 2),
            ),
        )

    # 头部跨度 = 头部画布跨度 + 与正文的间距；没有头部行则为 0。
    if horizontal_header_canvas is not None:
        header_span = horizontal_header_canvas.height + header_gap
    elif title_images and author_images:
        header_span = (
            piece_size(title_canvas)
            + header_gap
            + piece_size(author_canvas)
            + header_gap
        )
    elif title_images:
        header_span = piece_size(title_canvas) + header_gap
    elif author_images:
        header_span = piece_size(author_canvas) + header_gap
    else:
        header_span = 0.0

    title_position: tuple[float, float] | None = None
    author_position: tuple[float, float] | None = None

    body_cues = cues[len(script.header_lines) :]
    body_lines = script.body_lines
    body_image_groups = [render_group(line, body_font_size) for line in body_lines]

    # 内容放得下时整块在视窗内居中（content_offset > 0）；放不下时从
    # 方向锚点贴边开始排，正文视窗占用剩余空间。
    body_total_span = sum(
        group_span(images) for images in body_image_groups
    ) + piece_gap * max(0, len(body_image_groups) - 1)
    content_total = header_span + body_total_span
    main_capacity = viewport.width if direction.is_vertical else viewport.height
    if content_total <= main_capacity:
        # 累积内容放得下时，按用户配置定位整个 display block；横排主轴
        # 是垂直方向，因此读 align_v；竖排主轴是水平方向，因此读 align_h。
        main_align = (
            config.subtitle_align_v
            if direction == SubtitleDirection.horizontal
            else config.subtitle_align_h
        )
        # 用户字段描述的是内容块在视窗中的位置；方向锚点只决定坐标计算
        # 起点。vertical_rtl 的坐标系从右往左，因此 left/right 必须反转，
        # 否则会出现“选左贴右、选右贴左”的方向语义错乱。
        if direction == SubtitleDirection.vertical_rtl:
            if main_align == SubtitleAlignH.right:
                content_offset = 0.0
            elif main_align == SubtitleAlignH.left:
                content_offset = main_capacity - content_total
            else:
                content_offset = (main_capacity - content_total) / 2.0
        elif main_align in (SubtitleAlignV.top, SubtitleAlignH.left):
            content_offset = 0.0
        elif main_align in (SubtitleAlignV.bottom, SubtitleAlignH.right):
            content_offset = main_capacity - content_total
        else:
            content_offset = (main_capacity - content_total) / 2.0
    else:
        content_offset = 0.0

    if direction == SubtitleDirection.vertical_rtl:
        content_right = viewport.right - content_offset
        title_position = (content_right - title_canvas.width, title_origin[1])
        if author_images:
            author_position = (
                content_right - title_canvas.width - header_gap - author_canvas.width,
                author_origin[1],
            )
        body_origin = content_right - header_span
        body_capacity = body_origin - viewport.x
        viewport_x, viewport_y = viewport.x, viewport.y
        viewport_width, viewport_height = body_capacity, viewport.height
    elif direction == SubtitleDirection.vertical_ltr:
        content_left = viewport.x + content_offset
        title_position = (content_left, title_origin[1])
        if author_images:
            author_position = (
                content_left + title_canvas.width + header_gap,
                author_origin[1],
            )
        body_origin = content_left + header_span
        body_capacity = viewport.right - body_origin
        viewport_x, viewport_y = body_origin, viewport.y
        viewport_width, viewport_height = body_capacity, viewport.height
    else:
        content_top = viewport.y + content_offset
        if horizontal_header_canvas is not None:
            title_position = (
                viewport.x + (viewport.width - horizontal_header_canvas.width) / 2.0,
                content_top,
            )
        elif title_images:
            title_position = (title_origin[0], content_top)
        elif author_images:
            author_position = (author_origin[0], content_top)
        body_origin = content_top + header_span
        body_capacity = viewport.bottom - body_origin
        viewport_x, viewport_y = viewport.x, body_origin
        viewport_width, viewport_height = viewport.width, body_capacity

    if body_capacity <= 0:
        raise SubtitleException("margins leave no room for body lines")

    body_layouts: list[list[SubtitleSlotLayout]] = []
    line_extents: list[tuple[float, float]] = []
    line_before = 0.0
    for cue, line, images in zip(body_cues, body_lines, body_image_groups):
        piece_before = 0.0
        line_pieces: list[SubtitleSlotLayout] = []
        chunks = layout.split_slots(
            line, direction, body_font, body_font_size, viewport
        )
        if len(chunks) != len(images):
            raise SubtitleException("body split/render count mismatch")

        visible_start = 0
        for image_index, image in enumerate(images):
            if direction == SubtitleDirection.vertical_rtl:
                base_x = body_origin - line_before - piece_before - image.width
                base_y = cross_base(image)
            elif direction == SubtitleDirection.vertical_ltr:
                base_x = body_origin + line_before + piece_before
                base_y = cross_base(image)
            else:
                base_x = cross_base(image)
                base_y = body_origin + line_before + piece_before

            # 高亮按可见字符（非空白）推进；竖排槽切分后每槽的字符数即
            # 槽内可见字符数，横排同样按非空白计数。
            char_start = visible_start
            char_count = sum(not ch.isspace() for ch in chunks[image_index])
            visible_start += char_count
            line_pieces.append(
                SubtitleSlotLayout(
                    image=image,
                    cue=cue,
                    base_x=base_x,
                    base_y=base_y,
                    char_start=char_start,
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

    # 每个 cue 开始时刻需要的滚动量：让该行右/下边缘恰好贴住视窗边缘。
    offset_states = [
        SubtitleScrollOffsetState(
            start=cue.start, offset=max(0.0, extent_end - body_capacity)
        )
        for cue, (_start, extent_end) in zip(body_cues, line_extents)
    ]
    body_timings = (
        [reading_timings(line, cue) for cue, line in zip(body_cues, body_lines)]
        if config.subtitle_reading_highlight_enabled
        else [[] for _ in body_lines]
    )

    viewport_width = max(1, math.ceil(viewport_width))
    viewport_height = max(1, math.ceil(viewport_height))
    piece_variant_cache: dict[tuple[int, int, int], Image.Image] = {}

    def get_body_piece(
        line_index: int,
        piece_index: int,
        highlight_visible_index: int | None,
    ) -> Image.Image:
        """取正文槽位图；带高亮索引时渲染（并缓存）金色描边变体。"""
        if highlight_visible_index is None:
            return body_layouts[line_index][piece_index].image

        cache_key = (line_index, piece_index, highlight_visible_index)
        if cache_key not in piece_variant_cache:
            variants = render_group(
                body_lines[line_index],
                body_font_size,
                highlight_visible_index=highlight_visible_index,
            )
            if piece_index >= len(variants):
                raise SubtitleException("highlight piece index out of range")
            piece_variant_cache[cache_key] = variants[piece_index]
        return piece_variant_cache[cache_key]

    def piece_local_position(
        piece: SubtitleSlotLayout, offset: float
    ) -> tuple[float, float]:
        """把槽的基准位置换算到正文视窗坐标系。"""
        if direction == SubtitleDirection.vertical_rtl:
            return piece.base_x + offset - viewport_x, piece.base_y - viewport_y
        if direction == SubtitleDirection.vertical_ltr:
            return piece.base_x - offset - viewport_x, piece.base_y - viewport_y
        return piece.base_x - viewport_x, piece.base_y - offset - viewport_y

    def render_body_frame(time: float) -> np.ndarray:
        canvas = painter.new_canvas(viewport_width, viewport_height)
        offset = sliding_position(offset_states, time, config.subtitle_slide_duration)

        for line_index, cue in enumerate(body_cues):
            if time < cue.start:
                continue
            line_alpha = _fade_alpha(time, cue, config.subtitle_fade_in_duration)
            if line_alpha <= 0.0:
                continue
            for piece_index, piece in enumerate(body_layouts[line_index]):
                left, top = piece_local_position(piece, offset)
                painter.paste_cropped(
                    canvas,
                    piece.image,
                    left,
                    top,
                    line_alpha
                    * _piece_exit_alpha(piece, offset, direction, body_origin),
                )

        if config.subtitle_reading_highlight_enabled:
            for line_index, cue in enumerate(body_cues):
                if time < cue.start or time > cue.end + SUBTITLE_RELEASE_DURATION:
                    continue
                line_alpha = _fade_alpha(time, cue, config.subtitle_fade_in_duration)
                if line_alpha <= 0.0 or not body_timings[line_index]:
                    continue

                visible_chars = [
                    char for char in body_lines[line_index] if not char.isspace()
                ]
                for piece_index, piece in enumerate(body_layouts[line_index]):
                    left, top = piece_local_position(piece, offset)
                    exit_alpha = _piece_exit_alpha(
                        piece, offset, direction, body_origin
                    )
                    if exit_alpha <= 0.0:
                        continue
                    for local_index in range(piece.char_count):
                        char_index = piece.char_start + local_index
                        if char_index >= len(
                            body_timings[line_index]
                        ) or char_index >= len(visible_chars):
                            continue
                        char_start, char_end = body_timings[line_index][char_index]
                        alpha = highlight_alpha(time, char_start, char_end)
                        if (
                            visible_chars[char_index]
                            in fonts.SUBTITLE_VERTICAL_COMPACT_PUNCT
                        ):
                            alpha *= SUBTITLE_PUNCT_HIGHLIGHT_ALPHA
                        if alpha <= 0.0:
                            continue
                        highlighted = get_body_piece(
                            line_index, piece_index, char_index
                        )
                        painter.paste_cropped(
                            canvas,
                            highlighted,
                            left,
                            top,
                            line_alpha * exit_alpha * alpha,
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

    overlays: list[VideoClip] = [
        _overlay_clip(
            cached_body_frame,
            (viewport_width, viewport_height),
            (viewport_x, viewport_y),
            audio_duration,
        )
    ]
    if title_position is not None:
        overlays.append(
            ImageClip(
                np.asarray(
                    horizontal_header_canvas if horizontal_header_canvas is not None
                    else title_canvas
                )
            )
            .with_start(0.0)
            .with_end(audio_duration)
            .with_duration(audio_duration)
            .with_position(title_position)
        )
    if author_position is not None:
        overlays.append(
            ImageClip(np.asarray(author_canvas))
            .with_start(0.0)
            .with_end(audio_duration)
            .with_duration(audio_duration)
            .with_position(author_position)
        )
    # 图层顺序：正文在底层，头部行压在上面，避免长标题被正文视窗遮挡。
    overlays.reverse()
    return overlays


# ---------------------------------------------------------------------------
# 替换行为（逐条 cue 替换）与整块常驻行为
# ---------------------------------------------------------------------------


def _render_directional_content_block(
    config: SubtitleConfig,
    lines: list[str],
    font_path: str,
    viewport,
    allow_split: bool,
) -> Image.Image:
    """把一条 cue 或整块正文渲染成方向感知的内容块。

    替换式 cue 允许自动续行/续列；整块模式尊重用户选择，不再额外拆分。
    这个函数是替换式与整块式共用的方向入口，避免出现横排 + 竖排混排。
    """
    direction = config.subtitle_direction
    font_size = max(1, int(config.subtitle_font_size))
    rounded = (
        config.subtitle_background_style == SubtitleBackgroundStyle.rounded_translucent
    )
    if config.subtitle_background_enabled:
        pad_x = int(font_size * (0.4 if rounded else 0.6))
        pad_y = int(font_size * 0.35)
    else:
        pad_x = pad_y = 0

    font = fonts.load_font(font_path, font_size)
    slot_texts: list[str] = []
    for line in lines:
        if not allow_split:
            slot_texts.append(line)
        elif direction.is_vertical:
            slot_texts.extend(
                layout.split_vertical_slots(
                    line,
                    font_size,
                    max(1.0, viewport.height - pad_y * 2),
                )
            )
        else:
            wrapped, _wrapped_width = fonts.wrap_text(
                line,
                max(1, int(viewport.width) - pad_x * 2),
                font_path,
                font_size,
            )
            slot_texts.extend(wrapped.split("\n"))

    slots = painter.render_slots(
        slot_texts,
        font,
        font_size,
        direction,
        config.subtitle_text_color,
        config.subtitle_stroke_color,
        config.subtitle_stroke_width_int,
    )
    return painter.render_slot_group(
        slots,
        direction,
        max(6.0, font_size * layout.SUBTITLE_COLUMN_GAP_RATIO),
        (
            config.subtitle_align_h
            if direction == SubtitleDirection.horizontal
            else SubtitleAlignH.center
        ),
        (
            config.subtitle_align_v
            if direction.is_vertical
            else SubtitleAlignV.middle
        ),
        background_color=(
            config.subtitle_background_color
            if config.subtitle_background_enabled
            else None
        ),
        background_style=config.subtitle_background_style,
        padding=(pad_x, pad_y),
    )


def _build_replace_overlays(
    config: SubtitleConfig,
    cues: list[SubtitleCue],
    font_path: str,
    video_width: int,
    video_height: int,
    audio_duration: float,
) -> list[VideoClip]:
    """构建替换式字幕图层：同一时刻只显示一条 cue的内容块。

    每条 cue 预渲染成“背景 + 文字”的内容块，帧循环只做查块、对齐、
    淡入与贴图；cue 之间相互替换，不做累积。
    """
    viewport = layout.compute_viewport(
        config.subtitle_margin, video_width, video_height
    )
    block_cache: dict[str, Image.Image] = {}

    def get_block(cue: SubtitleCue) -> Image.Image:
        if cue.text not in block_cache:
            block_cache[cue.text] = _render_directional_content_block(
                config,
                [cue.text],
                font_path,
                viewport,
                allow_split=True,
            )
        return block_cache[cue.text]

    def render_frame(time: float) -> np.ndarray:
        canvas = painter.new_canvas(viewport.width, viewport.height)
        active = next((cue for cue in cues if cue.start <= time < cue.end), None)
        if active is None:
            return np.asarray(canvas)

        block = get_block(active)
        x, y = layout.align_box(
            viewport,
            block.width,
            block.height,
            config.subtitle_align_h,
            config.subtitle_align_v,
        )
        alpha = _fade_alpha(time, active, config.subtitle_fade_in_duration)
        painter.paste_cropped(canvas, block, x - viewport.x, y - viewport.y, alpha)
        return np.asarray(canvas)

    return [
        _overlay_clip(
            render_frame,
            (math.ceil(viewport.width), math.ceil(viewport.height)),
            (viewport.x, viewport.y),
            audio_duration,
        )
    ]


def _build_block_overlays(
    config: SubtitleConfig,
    script: SubtitleScriptInfo,
    font_path: str,
    video_width: int,
    video_height: int,
    audio_duration: float,
) -> list[VideoClip]:
    """构建整块常驻字幕图层：全文作为一个内容块，不切分不滚动。

    用户选择该模式即接受溢出风险，引擎不做自动缩放或折行兜底之外的处理。
    """
    viewport = layout.compute_viewport(
        config.subtitle_margin, video_width, video_height
    )
    text = "\n".join(script.body_lines)
    if not text.strip():
        return []

    block = _render_directional_content_block(
        config,
        script.body_lines,
        font_path,
        viewport,
        allow_split=False,
    )
    x, y = layout.align_box(
        viewport,
        block.width,
        block.height,
        config.subtitle_align_h,
        config.subtitle_align_v,
    )

    def render_frame(_time: float) -> np.ndarray:
        canvas = painter.new_canvas(viewport.width, viewport.height)
        painter.paste_cropped(canvas, block, x - viewport.x, y - viewport.y, 1.0)
        return np.asarray(canvas)

    return [
        _overlay_clip(
            render_frame,
            (math.ceil(viewport.width), math.ceil(viewport.height)),
            (viewport.x, viewport.y),
            audio_duration,
        )
    ]
