"""字体解析、字形探测与文本度量。

这里集中所有“字体能不能用、文本有多宽、一行有多高”的计算。渲染层
（painter/layout/engine）一律通过本模块获取字体与度量结果，禁止各自
直接 ImageFont.truetype，避免度量口径不一致。
"""

from __future__ import annotations

import os
import unicodedata
from functools import lru_cache

from loguru import logger
from PIL import ImageDraw, ImageFont

from app.utils import utils


# 用户选择了缺字形的字体（例如只覆盖西文的字体渲染中文文案）时，按这个
# 确定性顺序回退，避免 Pillow 把缺字形字符画成透明像素导致“字幕消失”。
SUBTITLE_FONT_FALLBACKS = (
    "MicrosoftYaHeiBold.ttc",
    "STHeitiMedium.ttc",
    "MicrosoftYaHeiNormal.ttc",
    "STHeitiLight.ttc",
)


@lru_cache(maxsize=64)
def _font_supports_sample(font_path: str, sample: str) -> bool:
    """检查字体是否包含样本文字需要的字形，并缓存重复检查结果。

    探测方法：先用 U+10FFFF（保证缺字形）生成“缺字形签名”，再逐字比对。
    字体探测失败不应阻止用户生成，保留日志供环境兼容问题排查。
    """
    try:
        font = ImageFont.truetype(font_path, 30)
        missing_mask = font.getmask("\U0010ffff")
        missing_signature = (
            missing_mask.size,
            missing_mask.getbbox(),
            bytes(missing_mask),
        )
        for char in sample:
            char_mask = font.getmask(char)
            char_signature = (
                char_mask.size,
                char_mask.getbbox(),
                bytes(char_mask),
            )
            if char_mask.getbbox() is None or char_signature == missing_signature:
                return False
        return True
    except Exception as exc:
        logger.warning(f"failed to inspect subtitle font glyphs: {font_path}, {exc}")
        return True


def font_supports_text(font_path: str, text: str) -> bool:
    """检查字体能否绘制文本中的字母和数字，忽略空白及标点符号。"""
    sample = "".join(
        dict.fromkeys(
            char
            for char in str(text or "")
            if unicodedata.category(char)[0] in {"L", "N"}
        )
    )[:64]
    if not sample:
        return True
    return _font_supports_sample(font_path, sample)


def resolve_font_path(font: str, text: str) -> str:
    """根据字幕文案解析可用字体；缺字形时按确定性顺序回退。

    用户可能保存了仅覆盖西文的字体（例如 BeVietnamPro），却用来渲染中文
    文案。这里在合成前检测字形覆盖，自动回退到内置中文字体并记录日志，
    避免静默输出看不见的字幕。
    """
    base_path = os.path.join(utils.font_dir(), font)
    resolved = base_path
    if not font_supports_text(base_path, text):
        for candidate in dict.fromkeys([*SUBTITLE_FONT_FALLBACKS, font]):
            if candidate == font:
                continue
            candidate_path = os.path.join(utils.font_dir(), candidate)
            if not os.path.isfile(candidate_path):
                continue
            if font_supports_text(candidate_path, text):
                logger.warning(
                    "subtitle font cannot render the script text; "
                    f"fallback from {font} to {candidate}"
                )
                resolved = candidate_path
                break
        else:
            # 没有任何候选字体覆盖全部字形时保留原选择，由上层继续渲染；
            # 宁可缺字形也不中断任务。
            logger.warning(
                f"no built-in fallback font can render the script text; keep {font}"
            )

    if os.name == "nt":
        # MoviePy/PIL 在 Windows 上要求正斜杠路径。
        resolved = resolved.replace("\\", "/")
    return resolved


def load_font(font_path: str, font_size: int) -> ImageFont.FreeTypeFont:
    """加载指定字号字体；路径非法时抛出排版错误而不是静默降级。"""
    if not font_path or not os.path.isfile(font_path):
        raise ValueError(f"subtitle font does not exist: {font_path}")
    return ImageFont.truetype(font_path, max(1, int(font_size)))


def line_height(font: ImageFont.FreeTypeFont, font_size: int) -> int:
    """字体的稳定行高（ascent + descent），单位像素。

    getbbox() 返回的是“当前字形的可见墨迹高度”，并不是字体行高。只含
    a、m、n 等无下伸部字符的英文会缺少 descent，多行时误差逐行累积。
    ascent + descent 来自字体自身，不受具体语种和字符组合影响。
    """
    ascent, descent = font.getmetrics()
    height = int(ascent + descent)
    if height <= 0:
        # 正常 TrueType/OpenType 字体不会进入这里；保留日志与字号兜底，
        # 避免损坏字体返回异常 metrics 后生成零高度字幕。
        logger.warning(
            "invalid subtitle font metrics, fallback to font size: "
            f"ascent={ascent}, descent={descent}, fontsize={font_size}"
        )
        height = max(1, int(font_size))
    return height


def text_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> float:
    """用给定字体测量单行文本宽度（换行与居中都要用它，口径必须统一）。"""
    return draw.textlength(text, font=font)


def wrap_text(
    text: str,
    max_width: int,
    font_path: str,
    font_size: int,
) -> tuple[str, int]:
    """把一段 cue 文本按可用宽度折成多行，返回 (折行文本, 总高度)。

    高度 = 行数 × 稳定行高。折行必须在真正绘制前完成；显式 \\n 会被保留。
    """
    font = ImageFont.truetype(font_path, font_size)
    max_width = int(max_width)
    row_height = line_height(font, font_size)

    def get_text_size(inner_text: str) -> tuple[int, int]:
        inner_text = inner_text.strip()
        if not inner_text:
            return 0, row_height
        left, _top, right, _bottom = font.getbbox(inner_text)
        # bbox 适合测量换行所需的实际宽度；高度必须始终使用稳定行高。
        return right - left, row_height

    width, _ = get_text_size(text)
    if width <= max_width:
        # SRT 条目允许作者手工换行。即使整段文本在宽度上不需要再次折行，
        # 画布高度仍必须按现有行数计算，否则第二行及后续行会被裁掉。
        return text, (text.count("\n") + 1) * row_height

    def split_long_token(token: str) -> list[str]:
        # 当一个 token 本身就超宽时（常见于中文无空格长句，或英文超长单词），
        # 退化为字符级拆分。关键点：检测到 candidate 超宽时，先提交上一个
        # 仍然合法的 current，再把当前字符放入下一行，不能把超宽字符塞回上一行。
        lines = []
        current = ""
        for char in token:
            candidate = f"{current}{char}"
            candidate_width, _ = get_text_size(candidate)
            if candidate_width <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = char
        if current:
            lines.append(current)
        return lines

    lines = []
    current = ""
    words = text.split(" ")
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)

        word_width, _ = get_text_size(word)
        if word_width <= max_width:
            current = word
        else:
            lines.extend(split_long_token(word))
            current = ""

    if current:
        lines.append(current)

    line_start_punctuation = "，。！？；：、,.!?;:)]}）】》」』”’"
    for index in range(1, len(lines)):
        # 中文长句按字符拆分时，句号、逗号等闭合标点可能被单独放到下一行，
        # 视觉上像一个小点掉在正文下方。把上一行最后一个字移到标点行前面，
        # 让标点跟随文字显示。
        if not lines[index] or lines[index][0] not in line_start_punctuation:
            continue
        if len(lines[index - 1]) <= 1:
            continue

        candidate = f"{lines[index - 1][-1]}{lines[index]}"
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            lines[index] = candidate
            lines[index - 1] = lines[index - 1][:-1]

    result = "\n".join(line.strip() for line in lines if line.strip()).strip()
    # 高度以最终结果为准。原文本中的显式换行可能保留在某个 token 内，
    # 此时临时 lines 列表的长度不等于实际渲染的行数。
    height = (result.count("\n") + 1) * row_height
    return result, height


# ---- 竖排度量 -----------------------------------------------------------
# 竖排以“字高 em”为推进单位；标点压缩到半格并靠上偏右，紧贴前一个字。
SUBTITLE_CHAR_HEIGHT_RATIO = 1.32  # 每个汉字占用的字高（含行间呼吸空间），以字号为单位
SUBTITLE_PUNCT_ADVANCE_RATIO = 0.55  # 竖排中标点占用的字高比例
SUBTITLE_VERTICAL_COMPACT_PUNCT = set("，。！？；：、,.!?;:")


def char_advance_em(char: str) -> float:
    """竖排里单个字符占用的字高（以字号为单位）。"""
    if char in SUBTITLE_VERTICAL_COMPACT_PUNCT:
        return SUBTITLE_PUNCT_ADVANCE_RATIO
    return SUBTITLE_CHAR_HEIGHT_RATIO


def vertical_advance_em(text: str) -> float:
    """竖排文本占用的总字高（以字号为单位），空白字符不推进。"""
    return sum(char_advance_em(char) for char in text if not char.isspace())
