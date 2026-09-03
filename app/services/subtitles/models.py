"""字幕内部领域模型。

这里存放字幕渲染过程中使用的纯数据结构，不包含渲染行为，也不对外
暴露成任务参数。用户可配置的字段和枚举仍由 app/models/schema.py 定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SubtitleCueSegmentation(str, Enum):
    """SRT 生成层的 cue 切分策略；不是用户可见的显示模式。"""

    punctuation = "punctuation"  # 按所有标点切分，用于逐条弹出
    sentence = "sentence"  # 按句末标点切分，用于逐条弹出
    physical_line = "physical_line"  # 按物理换行切分，用于连续滚动/固定头部


@dataclass(frozen=True)
class SubtitleMargin:
    """字幕边距（百分比）。"""

    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0


@dataclass(frozen=True)
class SubtitleViewport:
    """字幕可用区域（视频坐标系，单位像素）。"""

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
class SubtitleScriptInfo:
    """解析后的脚本文本结构。"""

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
