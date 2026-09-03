"""脚本文本解析：把生成文案拆成“头部行 + 正文行”。

普通文本没有头部行（header_line_count == 0），全部行都是正文；
带头部文本前 N 行固定显示，其余行为正文。引擎只依赖 SubtitleScriptInfo 结构。
"""

from app.models.exception import SubtitleException
from app.utils import utils
from app.services.subtitles.models import SubtitleScriptInfo


def parse_script(text: str, header_line_count: int = 0) -> SubtitleScriptInfo:
    """解析脚本文本，返回结构化的 SubtitleScriptInfo。

    - Markdown 分隔线已由字幕归一化移除（TTS 不朗读它们，保留会导致
      cue 与正文行错位）；
    - 前两个非空行为头部行，其余为正文行。
    """
    normalized_text = utils.normalize_script_for_subtitle_matching(text or "")
    lines = utils.split_string_by_lines(normalized_text)

    if header_line_count > 0:
        # 带头部模式要求头部行、正文至少各一行，缺任何一项都直接报错，
        # 避免渲染出残缺的固定图层。
        if len(lines) < header_line_count + 1:
            raise SubtitleException(
                "script requires header lines plus at least one body line: "
                f"header={header_line_count}, lines={len(lines)}"
            )
        info = SubtitleScriptInfo(
            title=lines[0],
            author=lines[1] if header_line_count > 1 else "",
            body_lines=tuple(lines[header_line_count:]),
        )
    else:
        info = SubtitleScriptInfo(
            title="",
            author="",
            body_lines=tuple(lines),
        )

    return info
