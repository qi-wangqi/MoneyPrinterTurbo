import pytest

from app.models.schema import (
    SubtitleAlignH,
    SubtitleAlignV,
    SubtitleBackgroundStyle,
    SubtitleDirection,
    SubtitleShowMode,
)
from app.services.subtitles import engine, fonts
from app.services.subtitles.config import SubtitleConfig
from app.services.subtitles.models import (
    SubtitleCue,
    SubtitleMargin,
    SubtitleScriptInfo,
)


@pytest.mark.parametrize(
    ("align_h", "expected_x"),
    [
        (SubtitleAlignH.left, 213),
        (SubtitleAlignH.center, 564),
        (SubtitleAlignH.right, 915),
    ],
)
def test_vertical_rtl_scroll_aligns_content_block_in_viewport(align_h, expected_x):
    """vertical_rtl 的用户水平对齐必须按视窗语义，而不是按坐标锚点反转。"""
    config = SubtitleConfig(
        subtitle_direction=SubtitleDirection.vertical_rtl,
        subtitle_show_mode=SubtitleShowMode.scroll,
        subtitle_align_h=align_h,
        subtitle_align_v=SubtitleAlignV.middle,
        subtitle_margin=SubtitleMargin(top=6, right=6, bottom=6, left=6),
        subtitle_font="MicrosoftYaHeiBold.ttc",
        subtitle_font_size=60,
        subtitle_text_color="#FFFFFF",
        subtitle_stroke_color="#000000",
        subtitle_stroke_width=0,
        subtitle_background_enabled=False,
        subtitle_background_color="",
        subtitle_background_style=SubtitleBackgroundStyle.rectangle,
        subtitle_header_line_count=1,
        subtitle_reading_highlight_enabled=True,
        subtitle_auto_fit_font_size_enabled=True,
        subtitle_fade_in_duration=0.24,
        subtitle_slide_duration=0.4,
    )
    script = SubtitleScriptInfo("静夜思", "", ("床前明月光，",))
    font_path = fonts.resolve_font_path(config.subtitle_font, script.title)
    cues = [
        SubtitleCue(start=0, end=0.5, text=script.title),
        SubtitleCue(start=0.5, end=1.0, text=script.body_lines[0]),
    ]

    title_clip = engine._build_scroll_overlays(
        config,
        script,
        cues,
        font_path,
        video_width=1080,
        video_height=1080,
        audio_duration=1.0,
    )[0]

    assert round(title_clip.pos(0)[0]) == expected_x
