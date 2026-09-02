"""统一字幕模块：独立于流水线的字幕渲染子系统。

流水线（video.py）只调用本模块的门面函数，不接触任何渲染细节：

    from app.services import subtitles

    overlays = subtitles.build_overlays(
        subtitle_path=subtitle_path,
        params=params,          # VideoParams
        video_width=video_width,
        video_height=video_height,
        audio_duration=voice_duration,
    )
    video_clip = CompositeVideoClip([source_video_clip, *overlays])

模块分层（依赖自上而下）：
    config   字幕统一配置对象；schema 旧字段只在这里被翻译
    models   枚举与纯数据结构（Direction / ShowMode / Viewport / Cue）
    script   脚本文本 → 头部行 + 正文行
    srt      SRT 生成（Whisper）、读取与脚本校正
    cues     SRT → SubtitleCue，及 cue/脚本一致性校验
    fonts    字体解析、字形探测与文本度量
    layout   纯几何：视窗、槽切分、对齐公式
    painter  PIL 绘制原语：文字、描边、背景、透明度
    engine   时间轴：replace / scroll / block 三种显示行为
"""

from __future__ import annotations

from moviepy import VideoClip

from app.services.subtitles import config as config_module
from app.services.subtitles import cues as cues_module
from app.services.subtitles import engine as engine_module
from app.services.subtitles import fonts as fonts_module
from app.services.subtitles import script as script_module


def build_overlays(
    subtitle_path: str,
    params,
    video_width: int,
    video_height: int,
    audio_duration: float,
) -> list[VideoClip]:
    """渲染字幕图层，返回可直接参与 CompositeVideoClip 的透明图层列表。

    步骤：schema 参数 → SubtitleConfig → 解析脚本 → 读取并校验 cue →
    解析字体 → 引擎按显示行为出图层。任何一步失败都会抛出异常，由
    流水线决定是否终止任务。
    """
    subtitle_config = config_module.SubtitleConfig.from_video_params(params)
    script = script_module.parse_script(
        params.video_script, subtitle_config.header_line_count
    )
    cues = cues_module.read_cues(subtitle_path)
    if subtitle_config.header_line_count > 0:
        # 带头部行的模式（如诗歌）要求 cue 与脚本行一一对应，错位会让
        # 逐字高亮和滚动节奏全部失准，必须显式失败。
        cues_module.validate_cues(cues, script)

    font_path = fonts_module.resolve_font_path(
        subtitle_config.font_name, params.video_script
    )
    return engine_module.build_overlays(
        config=subtitle_config,
        script=script,
        cues=cues,
        font_path=font_path,
        video_width=video_width,
        video_height=video_height,
        audio_duration=audio_duration,
    )


__all__ = ["build_overlays"]
