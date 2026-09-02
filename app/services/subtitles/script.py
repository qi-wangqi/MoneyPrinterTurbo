"""脚本文本解析：把生成文案拆成“头部行 + 正文行”。

普通模式没有头部行（header_line_count == 0），全部行都是正文；诗歌模式
（header_line_count == 2）前两行是诗名和作者，作为固定图层渲染。引擎
只依赖 ScriptInfo 结构，不知道“诗歌”这个概念。
"""

from app.utils import utils
from app.services.subtitles.models import ScriptInfo


class ScriptParseError(ValueError):
    """脚本行数不足以支撑指定数量的头部行时抛出。"""


def parse_script(text: str, header_line_count: int = 0) -> ScriptInfo:
    """解析脚本文本，返回结构化的 ScriptInfo。

    - Markdown 分隔线已由字幕归一化移除（TTS 不朗读它们，保留会导致
      cue 与正文行错位）；
    - 前两个非空行为头部行，其余为正文行。
    """
    normalized_text = utils.normalize_script_for_subtitle_matching(text or "")
    lines = utils.split_string_by_lines(normalized_text)

    if header_line_count > 0:
        # 诗歌模式要求诗名、作者、正文至少各一行，缺任何一项都直接报错，
        # 避免渲染出残缺的固定图层。
        if len(lines) < header_line_count + 1:
            raise ScriptParseError(
                "script requires header lines plus at least one body line: "
                f"header={header_line_count}, lines={len(lines)}"
            )
        info = ScriptInfo(
            title=lines[0],
            author=lines[1] if header_line_count > 1 else "",
            body_lines=tuple(lines[header_line_count:]),
        )
    else:
        info = ScriptInfo(
            title="",
            author="",
            body_lines=tuple(lines),
        )

    return info
