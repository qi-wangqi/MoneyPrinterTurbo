"""SubtitleConfig：字幕渲染的唯一配置对象。

引擎、排版与绘制只认识 SubtitleConfig；`from_video_params()` 是全项目
唯一知道 schema 旧字段名的地方。将来 schema 改成统一的 `subtitle_*`
字段时，只需要修改这个函数，流水线与引擎无感。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.subtitles.models import (
    AlignH,
    AlignV,
    BackgroundStyle,
    Direction,
    Margin,
    ShowMode,
)


# 渲染节奏默认值（秒）：滚动 cue 的滑动时长与正文行淡入时长。
DEFAULT_SLIDE_DURATION = 0.4
DEFAULT_FADE_IN_DURATION = 0.24


@dataclass(frozen=True)
class SubtitleConfig:
    """一次渲染任务所需的全部字幕配置。"""

    direction: Direction
    show_mode: ShowMode
    align_h: AlignH
    align_v: AlignV
    margin: Margin
    font_name: str
    font_size: int
    text_color: str
    stroke_color: str
    stroke_width: float
    background_enabled: bool
    background_color: str
    background_style: BackgroundStyle
    header_line_count: int
    reading_highlight: bool
    auto_fit_font_size: bool
    fade_in_duration: float
    slide_duration: float = DEFAULT_SLIDE_DURATION
    min_font_size: int = 24

    @property
    def stroke_width_int(self) -> int:
        """描边宽度按整数像素使用（PIL 描边不支持小数）。"""
        return max(0, int(float(self.stroke_width or 0)))

    @classmethod
    def from_video_params(cls, params) -> "SubtitleConfig":
        """把 VideoParams 的字幕字段翻译成引擎配置。

        普通字幕与诗歌字幕在这里收敛成同一套字段：方向、显示模式、
        对齐与边距。引擎里没有任何“诗歌/普通”的分支。
        """
        if getattr(params, "subtitle_style", "standard") == "poetry":
            direction_map = {
                "right_to_left": Direction.VERTICAL_RTL,
                "left_to_right": Direction.VERTICAL_LTR,
                # 旧“top_to_bottom”即横排文字向下流动，统一到 HORIZONTAL。
                "top_to_bottom": Direction.HORIZONTAL,
            }
            direction = direction_map.get(
                getattr(params, "poetry_direction", "right_to_left"),
                Direction.VERTICAL_RTL,
            )
            margin = Margin(
                top=float(getattr(params, "poetry_margin_top", 6.0)),
                right=float(getattr(params, "poetry_margin_right", 6.0)),
                bottom=float(getattr(params, "poetry_margin_bottom", 6.0)),
                left=float(getattr(params, "poetry_margin_left", 6.0)),
            )
            return cls(
                direction=direction,
                show_mode=ShowMode.SCROLL,
                align_h=AlignH.CENTER,
                align_v=AlignV.MIDDLE,
                margin=margin,
                font_name=str(params.font_name or "STHeitiMedium.ttc"),
                font_size=int(params.font_size),
                text_color=str(params.text_fore_color or "#FFFFFF"),
                stroke_color=str(params.stroke_color or "#000000"),
                stroke_width=float(params.stroke_width or 0),
                background_enabled=False,
                background_color="",
                background_style=BackgroundStyle.RECTANGLE,
                header_line_count=2,
                reading_highlight=True,
                auto_fit_font_size=True,
                fade_in_duration=DEFAULT_FADE_IN_DURATION,
                slide_duration=DEFAULT_SLIDE_DURATION,
            )

        # 普通字幕：旧的 subtitle_position / custom_position 映射成
        # margin + align_v；左右各留 5% 对应旧实现的 90% 宽度上限。
        position = getattr(params, "subtitle_position", "bottom") or "bottom"
        if position == "top":
            margin, align_v = Margin(top=5, right=5, bottom=5, left=5), AlignV.TOP
        elif position == "center":
            margin, align_v = Margin(right=5, left=5), AlignV.MIDDLE
        elif position == "custom":
            custom = min(100.0, max(0.0, float(getattr(params, "custom_position", 70.0))))
            margin, align_v = Margin(top=custom, right=5, left=5), AlignV.TOP
        else:  # bottom（默认）
            margin, align_v = Margin(right=5, bottom=5, left=5), AlignV.BOTTOM

        background_color = _resolve_background_color(params)
        return cls(
            direction=Direction.HORIZONTAL,
            show_mode=ShowMode.PUNCTUATION,
            align_h=AlignH.CENTER,
            align_v=align_v,
            margin=margin,
            font_name=str(params.font_name or "STHeitiMedium.ttc"),
            font_size=int(params.font_size),
            text_color=str(params.text_fore_color or "#FFFFFF"),
            stroke_color=str(params.stroke_color or "#000000"),
            stroke_width=float(params.stroke_width or 0),
            background_enabled=bool(background_color),
            background_color=background_color,
            background_style=(
                BackgroundStyle.ROUNDED_TRANSLUCENT
                if getattr(params, "rounded_subtitle_background", False)
                else BackgroundStyle.RECTANGLE
            ),
            header_line_count=0,
            reading_highlight=False,
            auto_fit_font_size=False,
            fade_in_duration=0.0,
            slide_duration=DEFAULT_SLIDE_DURATION,
        )


def _resolve_background_color(params) -> str:
    """归一化历史背景色参数。

    API 里 `text_background_color` 既可能是布尔值也可能是颜色字符串：
    True 视为黑色底、False 视为关闭、字符串原样使用。
    """
    value = getattr(params, "text_background_color", False)
    if isinstance(value, bool):
        return "#000000" if value else ""
    return str(value or "")


def subtitle_colors_are_indistinguishable(params) -> bool:
    """判断字幕文字和背景是否同色，提醒用户可能无法看清字幕。"""
    if not params.subtitle_enabled or not params.text_background_color:
        return False

    def normalize_color(value):
        if isinstance(value, bool):
            return "#000000" if value else ""
        return str(value or "").strip().lower()

    text_color = normalize_color(params.text_fore_color)
    background_color = normalize_color(params.text_background_color)
    return bool(text_color and text_color == background_color)
