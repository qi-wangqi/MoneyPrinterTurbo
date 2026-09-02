"""字幕渲染的数据模型：枚举、配置值对象与纯数据结构。

本模块只存放“是什么”，不存放“怎么画”。渲染引擎（engine）、排版
（layout）、绘制（painter）共享这里的数据结构，保证各阶段之间的接口
是数据而不是散落的参数。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SubtitleLayoutError(ValueError):
    """字幕内容无法在给定视窗内排版时抛出。"""


class Direction(str, Enum):
    """文字流动方向，决定 cue 的排列与滚动轴。"""

    HORIZONTAL = "horizontal"  # 横排：正文行自上而下排列，溢出时向上滚动
    VERTICAL_RTL = "vertical_rtl"  # 竖排：新列自右向左进入，旧列从左侧裁掉
    VERTICAL_LTR = "vertical_ltr"  # 竖排：新列自左向右进入，旧列从右侧裁掉

    @property
    def is_vertical(self) -> bool:
        """竖排方向返回 True；横排返回 False。"""
        return self in (Direction.VERTICAL_RTL, Direction.VERTICAL_LTR)


class ShowMode(str, Enum):
    """字幕显示模式，同时决定 cue 切分方式（生成侧）与显示行为（渲染侧）。"""

    PUNCTUATION = "punctuation"  # 按标点切分 cue，逐条替换显示
    SENTENCE = "sentence"  # 按完整句切分 cue，逐条替换显示
    LINE = "line"  # 按换行切分 cue（与诗歌正文行对齐）
    SCROLL = "scroll"  # 累积式：cue 按方向锚点滑动，超出视窗裁剪
    BLOCK = "block"  # 整块常驻：全文作为一个块显示，不切分不滚动

    @property
    def is_replace_style(self) -> bool:
        """替换式模式（标点/整句）在渲染侧共用同一套逐条替换行为。"""
        return self in (ShowMode.PUNCTUATION, ShowMode.SENTENCE)


class AlignH(str, Enum):
    """整块内容在视窗内的水平对齐。"""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class AlignV(str, Enum):
    """整块内容在视窗内的垂直对齐。"""

    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


class BackgroundStyle(str, Enum):
    """字幕背景样式。"""

    RECTANGLE = "rectangle"  # 实心矩形
    ROUNDED_TRANSLUCENT = "rounded_translucent"  # 圆角半透明


@dataclass(frozen=True)
class Margin:
    """字幕边距（百分比）。

    top/bottom 相对视频高度，left/right 相对视频宽度。边距把整幅视频
    收缩成字幕视窗（viewport），所有模式（包括滚动）都在视窗内排版。
    """

    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0


@dataclass(frozen=True)
class Viewport:
    """字幕可用区域（视频坐标系，单位像素）。

    由视频尺寸扣除 margin 得到；slot 与内容块的对齐、溢出锚点都在
    这个矩形内计算。
    """

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        """视窗右边界。"""
        return self.x + self.width

    @property
    def bottom(self) -> float:
        """视窗下边界。"""
        return self.y + self.height


@dataclass(frozen=True)
class SubtitleCue:
    """一条带时间的字幕 cue（来自 SRT）。"""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class ScriptInfo:
    """解析后的脚本文本结构。

    header_line_count > 0 时（诗歌模式），前两行是诗名/作者并作为固定
    图层渲染，其余行为正文；header_line_count == 0 时（普通模式）全部
    行都是正文，引擎对“诗歌”没有任何概念。
    """

    title: str
    author: str
    body_lines: tuple[str, ...]

    @property
    def header_lines(self) -> tuple[str, ...]:
        """固定不参与滚动的头部行。"""
        return tuple(line for line in (self.title, self.author) if line)

    @property
    def all_lines(self) -> tuple[str, ...]:
        """头部行 + 正文行，顺序与 SRT cue 一一对应。"""
        return (*self.header_lines, *self.body_lines)
