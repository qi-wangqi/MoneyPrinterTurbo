"""SubtitleConfig：字幕渲染的唯一配置对象。

引擎、排版与绘制只认识 SubtitleConfig；VideoParams 已经使用统一的
`subtitle_*` 契约，`from_video_params()` 只做契约对象到渲染配置的转换。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.models.schema import (
    SubtitleAlignH,
    SubtitleAlignV,
    SubtitleBackgroundStyle,
    SubtitleDirection,
    SubtitleShowMode,
)
from app.services.subtitles.models import SubtitleCueSegmentation, SubtitleMargin

if TYPE_CHECKING:
    from app.models.schema import VideoParams


# 渲染节奏默认值（秒）：滚动 cue 的滑动时长与正文行淡入时长。
DEFAULT_SUBTITLE_SLIDE_DURATION = 0.4
DEFAULT_SUBTITLE_FADE_IN_DURATION = 0.24


@dataclass(frozen=True)
class SubtitleConfig:
    """一次渲染任务所需的全部字幕配置。"""

    subtitle_direction: SubtitleDirection
    subtitle_show_mode: SubtitleShowMode
    subtitle_align_h: SubtitleAlignH
    subtitle_align_v: SubtitleAlignV
    subtitle_margin: SubtitleMargin
    subtitle_font: str
    subtitle_font_size: int
    subtitle_text_color: str
    subtitle_stroke_color: str
    subtitle_stroke_width: float
    subtitle_background_enabled: bool
    subtitle_background_color: str
    subtitle_background_style: SubtitleBackgroundStyle
    subtitle_header_line_count: int
    subtitle_reading_highlight_enabled: bool
    subtitle_auto_fit_font_size_enabled: bool
    subtitle_fade_in_duration: float
    subtitle_slide_duration: float = DEFAULT_SUBTITLE_SLIDE_DURATION
    subtitle_min_font_size: int = 24

    @property
    def subtitle_stroke_width_int(self) -> int:
        """描边宽度按整数像素使用（PIL 描边不支持小数）。"""
        return max(0, int(float(self.subtitle_stroke_width or 0)))

    @classmethod
    def from_video_params(cls, params: "VideoParams") -> "SubtitleConfig":
        """把统一 `subtitle_*` 契约转换为渲染引擎配置。"""
        subtitle_show_mode = SubtitleShowMode(params.subtitle_show_mode)
        is_scroll = subtitle_show_mode == SubtitleShowMode.scroll
        subtitle_background_enabled = bool(params.subtitle_background_enabled)
        return cls(
            subtitle_direction=SubtitleDirection(params.subtitle_direction),
            subtitle_show_mode=subtitle_show_mode,
            subtitle_align_h=SubtitleAlignH(params.subtitle_align_h),
            subtitle_align_v=SubtitleAlignV(params.subtitle_align_v),
            subtitle_margin=SubtitleMargin(
                top=float(params.subtitle_margin_top),
                right=float(params.subtitle_margin_right),
                bottom=float(params.subtitle_margin_bottom),
                left=float(params.subtitle_margin_left),
            ),
            subtitle_font=str(params.subtitle_font or "MicrosoftYaHeiBold.ttc"),
            subtitle_font_size=int(params.subtitle_font_size),
            subtitle_text_color=str(params.subtitle_text_color or "#FFFFFF"),
            subtitle_stroke_color=str(params.subtitle_stroke_color or "#000000"),
            subtitle_stroke_width=float(params.subtitle_stroke_width or 0),
            subtitle_background_enabled=subtitle_background_enabled,
            subtitle_background_color=(
                str(params.subtitle_background_color or "#000000")
                if subtitle_background_enabled
                else ""
            ),
            subtitle_background_style=SubtitleBackgroundStyle(
                params.subtitle_background_style
            ),
            subtitle_header_line_count=int(params.subtitle_header_line_count),
            subtitle_reading_highlight_enabled=is_scroll,
            subtitle_auto_fit_font_size_enabled=is_scroll,
            subtitle_fade_in_duration=DEFAULT_SUBTITLE_FADE_IN_DURATION
            if is_scroll
            else 0.0,
            subtitle_slide_duration=DEFAULT_SUBTITLE_SLIDE_DURATION,
        )


def subtitle_colors_are_indistinguishable(params: "VideoParams") -> bool:
    """判断字幕文字和背景是否同色，提醒用户可能无法看清字幕。"""
    if not params.subtitle_enabled or not params.subtitle_background_enabled:
        return False

    def normalize_color(value):
        return str(value or "").strip().lower()

    text_color = normalize_color(params.subtitle_text_color)
    background_color = normalize_color(params.subtitle_background_color)
    return bool(text_color and text_color == background_color)


def resolve_cue_segmentation(params: "VideoParams") -> SubtitleCueSegmentation:
    """把显示模式与头部行约束转换成 SRT 生成层的切分策略。

    `scroll` 需要按物理换行建立连续滑动锚点；固定头部行也要求 SRT cue
    与脚本行一一对应。因此这两个条件都映射到 `physical_line`。
    """
    show_mode = SubtitleShowMode(params.subtitle_show_mode)
    if (
        show_mode == SubtitleShowMode.scroll
        or int(params.subtitle_header_line_count) > 0
    ):
        return SubtitleCueSegmentation.physical_line
    if show_mode == SubtitleShowMode.sentence:
        return SubtitleCueSegmentation.sentence
    return SubtitleCueSegmentation.punctuation
