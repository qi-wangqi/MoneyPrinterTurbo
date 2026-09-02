"""cue 读取与校验：SRT 时间轴 → 结构化 SubtitleCue。

cue 是渲染引擎的时间单元：替换式逐条替换、滚动式按 cue 滑动。这里
负责把 SRT 文本解析成 SubtitleCue，并在诗歌模式下校验 cue 与脚本行
一一对应（错位会导致逐字高亮和滚动节奏全部失准）。
"""

from __future__ import annotations

import re

from app.services.subtitles.models import ScriptInfo, SubtitleCue
from app.services.subtitles.models import SubtitleLayoutError
from app.services.subtitles import srt


def _parse_srt_time(value: str) -> float:
    """把 SRT 时间戳 `HH:MM:SS,mmm` 转成秒。"""
    try:
        hour_text, minute_text, second_text = value.strip().split(":")
        return (
            int(hour_text) * 3600
            + int(minute_text) * 60
            + float(second_text.replace(",", "."))
        )
    except (TypeError, ValueError) as exc:
        raise SubtitleLayoutError(
            f"invalid subtitle timestamp: {value}"
        ) from exc


def read_cues(subtitle_path: str) -> list[SubtitleCue]:
    """读取 SRT 文件并解析为带时间的 cue 列表。"""
    cues: list[SubtitleCue] = []
    for _index, timing, text in srt.file_to_subtitles(subtitle_path):
        if " --> " not in timing:
            raise SubtitleLayoutError(f"invalid subtitle timing: {timing}")
        start_text, end_text = timing.split(" --> ", 1)
        start = _parse_srt_time(start_text)
        end = _parse_srt_time(end_text)
        if end < start:
            raise SubtitleLayoutError(f"subtitle end precedes start: {timing}")
        cues.append(SubtitleCue(start=start, end=end, text=text.strip()))
    return cues


def _normalize_for_match(value: str) -> str:
    """校验用归一化：去掉全部符号与空白并转小写，只比内容本身。"""
    return re.sub(r"[\W_]+", "", value or "", flags=re.UNICODE).lower()


def validate_cues(cues: list[SubtitleCue], script: ScriptInfo) -> None:
    """校验 cue 与脚本行一一对应。

    SRT cue 由 TTS 时间轴生成，脚本行是渲染内容。两者数量或文本不一致
    时（生成管线被跳改、文案中途被编辑）必须显式失败，不能静默渲染。
    """
    expected_lines = script.all_lines
    if len(cues) != len(expected_lines):
        raise SubtitleLayoutError(
            "subtitle cue count mismatch: "
            f"expected {len(expected_lines)}, got {len(cues)}"
        )

    for cue, expected_text in zip(cues, expected_lines):
        if _normalize_for_match(cue.text) != _normalize_for_match(expected_text):
            raise SubtitleLayoutError(
                f"subtitle cue mismatch at {cue.start:.3f}s: expected "
                f"{expected_text!r}, got {cue.text!r}"
            )
