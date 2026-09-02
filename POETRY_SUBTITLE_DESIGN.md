# 唐诗字幕模式详细设计

状态：设计稿，未实施。  
目标版本：MoneyPrinterTurbo 当前工作区。

## 1. 背景

当前项目的字幕链路是：

```text
视频文案
  -> TTS 生成 audio.mp3，同时返回 word boundary / phrase cue
  -> 按标点和换行聚合成 subtitle.srt
  -> MoviePy SubtitlesClip 读取 SRT
  -> 每条字幕生成横向 TextClip
  -> 叠加到视频画面并合成 final-N.mp4
```

这个模式适合普通口播字幕，但不能表达用户想要的唐诗效果：

1. 诗名和作者从视频一开始就常驻显示。
2. 正文诗句按用户输入的物理行断句。
3. 视频朗读到某一行时，该行以竖排形式展开。
4. 已展开的诗句继续保留，不会像普通字幕一样被下一条替换。
5. 整体版式支持“从右至左”“从左至右”“从上至下”三种方向，默认从右至左，以贴近传统书籍排版。

本方案新增一个可选的 `poetry` 字幕样式。它复用现有音频、TTS、SRT、素材下载和视频合成链路，只把“字幕分段方式”和“字幕渲染方式”做成独立分支，避免影响普通字幕。

## 2. 目标

### 2.1 功能目标

1. WebUI 可以选择字幕样式：
   - `standard`：普通字幕，保持现有行为。
   - `poetry`：唐诗字幕。
2. 唐诗模式直接使用用户填写的“视频文案”，不新增诗名、作者参数。
3. 唐诗模式按用户输入的物理行断句，不按逗号、句号继续拆分。
4. 诗名、作者、正文都来自视频文案。
5. TTS 正常朗读诗名、作者和正文。
6. `subtitle.srt` 仍然基于真实音频时间轴。
7. 最终视频中的诗名和作者从 `0s` 常驻显示。
8. 每行正文从该行音频开始时间出现，并保留到视频结束。
9. 画面布局方向可配置：
   - `right_to_left`：竖排列从右向左推进。
   - `left_to_right`：竖排列从左向右推进。
   - `top_to_bottom`：横排行从上向下推进。

### 2.2 非目标

第一版不做以下内容：

1. 不新增独立数据库表。
2. 不新增 `poem_title`、`poem_author` 参数。
3. 不支持逐字动画、毛笔书写动画、粒子特效。
4. 不修改普通字幕的默认断句和显示逻辑。
5. 不保证上传音频加 Whisper 的行级对齐效果和 TTS 一样稳定；第一版只做兼容支持。
6. 不提供用户自定义列间距、分隔线颜色、背景纹理等高级样式输入；这些先由渲染器内置默认值控制。

## 3. 用户输入约定

唐诗模式的输入仍然使用现有“视频文案”输入框。

约定如下：

```text
第 1 个非空物理行：诗名
第 2 个非空物理行：作者
第 3 个及之后的非空物理行：诗句正文
空行：忽略
每行首尾空白：忽略
每个非空物理行：一条字幕 cue
```

示例：

```text
【拟古·其一】
魏晋 · 陶渊明
人生无根蒂，飘如陌上尘。
分散逐风转，此已非常身。
落地为兄弟，何必骨肉亲！
得欢当作乐，斗酒聚比邻。
盛年不重来，一日难再晨。
及时当勉励，岁月不待人。
```

解析结果：

```text
title:
【拟古·其一】

author:
魏晋 · 陶渊明

poem_lines:
1. 人生无根蒂，飘如陌上尘。
2. 分散逐风转，此已非常身。
3. 落地为兄弟，何必骨肉亲！
4. 得欢当作乐，斗酒聚比邻。
5. 盛年不重来，一日难再晨。
6. 及时当勉励，岁月不待人。
```

### 3.1 为什么不新增诗名和作者参数

诗名和作者已经属于视频文案的一部分。如果单独新增 `poem_title`、`poem_author`，会带来以下问题：

1. WebUI 需要额外输入框。
2. API 参数变多。
3. 历史任务恢复和设置导出需要兼容新字段。
4. 用户可能在视频文案和独立参数里重复填写，产生不一致。
5. 后续导出 SRT 或复现任务时，还要解释独立参数与正文的关系。

因此本方案只新增一个样式开关：

```text
subtitle_style = "poetry"
```

其余信息继续由 `video_script` 承载。

### 3.2 输入约束

除“前两个非空行是诗名和作者、至少有一句正文”外，不限制正文行数、单行字数、诗名长度和作者长度。

超长内容不是提交错误，而是渲染布局要处理的问题：

1. 行数或列数超过安全区时，使用滑动窗口显示最近出现的诗句。
2. 单列或单行在正交方向过长时，先尝试按安全区缩放；仍放不下则拆成续列或续行。
3. 头部诗名和作者同样参与正交方向的适配，但不进入正文滑动队列。

## 4. 总体流程

### 4.1 普通模式流程，保持不变

```text
video_script
  -> utils.split_string_by_punctuations()
  -> voice.create_subtitle()
  -> subtitle.srt
  -> generate_video() 普通字幕分支
  -> 横向字幕逐条替换
```

### 4.2 唐诗模式流程

```text
video_script
  -> parse_poetry_script()
      第 1 个非空行 -> title
      第 2 个非空行 -> author
      其余非空行 -> poem_lines
  -> 校验通过后继续原任务
  -> TTS 使用完整 video_script 生成 audio.mp3 和 sub_maker
  -> voice.create_subtitle(segmentation="line")
      所有物理行按行聚合成 SRT
  -> subtitle.srt
      cue 1 = 诗名
      cue 2 = 作者
      cue 3..N = 正文行
  -> generate_video()
  -> poetry_renderer.build_poetry_overlays()
      title/author 从 0s 常驻
      body cue 从自己的 start 出现并保留到结尾
      超出安全区时按 subtitle_direction 滑动，滑出的旧句隐藏
  -> CompositeVideoClip 合成最终视频
```

关键点：TTS 输入仍然是完整 `video_script`，所以诗名和作者也会被朗读。SRT 中也保留诗名和作者的 cue，用于保证正文时间轴从真实朗读位置开始。渲染器只把前两条 cue 当作固定头部，不按普通字幕替换显示。

## 5. 参数模型修改

### 5.1 修改文件

```text
app/models/schema.py
```

### 5.2 新增字段

在 `VideoParams` 中新增：

```python
subtitle_style: Literal["standard", "poetry"] = "standard"
poetry_direction: Literal[
    "right_to_left",
    "left_to_right",
    "top_to_bottom",
] = "right_to_left"
poetry_margin_top: float = Field(default=6.0, ge=0, le=25)
poetry_margin_right: float = Field(default=6.0, ge=0, le=25)
poetry_margin_bottom: float = Field(default=6.0, ge=0, le=25)
poetry_margin_left: float = Field(default=6.0, ge=0, le=25)
```

`subtitle_style` 使用 `Literal` 满足 API 校验。`poetry_direction` 和四个 `poetry_margin_*` 只在 `subtitle_style == "poetry"` 时生效；普通字幕忽略它们，因此不会影响现有行为。

`poetry_margin_*` 表示文字内容区到画布四边的距离，单位是画布短语义上的百分比：

| 字段 | 计算基准 | 默认值 |
|---|---:|---:|
| `poetry_margin_top` | 视频高度 | `6.0%` |
| `poetry_margin_bottom` | 视频高度 | `6.0%` |
| `poetry_margin_left` | 视频宽度 | `6.0%` |
| `poetry_margin_right` | 视频宽度 | `6.0%` |

它借用 CSS `margin` 的四边语义，但不采用 CSS 中上下 margin 相对宽度的特殊规则。视频渲染按对应边尺寸计算更直观：横屏和竖屏使用同一套配置时，仍能得到合理的物理边距。

### 5.3 默认值和兼容性

```python
subtitle_style = "standard"
```

老任务和历史 API 请求不会传这个字段，Pydantic 会使用默认值 `standard`。

因此：

1. 老 API 调用行为不变。
2. 老任务 `script.json` 读取时自动回到普通字幕。
3. 普通用户不会看到任何行为变化。

`poetry_direction` 的兼容性相同：

```python
poetry_direction = "right_to_left"
```

老任务没有该字段时使用默认方向和默认边距。导入预设和恢复历史任务时，非法方向或超出范围的边距由 `VideoParams` 直接拒绝。

### 5.4 为什么不再新增诗名和作者字段

不新增：

```python
poem_title
poem_author
```

原因是输入约定已经可以表达完整语义：

```text
第 1 行 = 诗名
第 2 行 = 作者
第 3 行起 = 正文
```

这样能减少：

1. WebUI 输入框。
2. API 参数。
3. 设置导出字段。
4. 历史任务恢复字段。
5. 用户重复填写造成的数据不一致。

## 6. 新增服务模块

### 6.1 新增 `app/services/poetry.py`

这个模块只负责唐诗文本的结构解析和校验，不负责渲染。

建议内容：

```python
from dataclasses import dataclass


class PoetryScriptError(ValueError):
    pass


@dataclass(frozen=True)
class PoetryScript:
    title: str
    author: str
    poem_lines: tuple[str, ...]

    @property
    def all_lines(self) -> tuple[str, ...]:
        return (self.title, self.author, *self.poem_lines)

    @property
    def metadata_line_count(self) -> int:
        return 2


def parse_poetry_script(text: str) -> PoetryScript:
    ...
```

核心逻辑：

```python
def parse_poetry_script(text: str) -> PoetryScript:
    lines = [
        line.strip()
        for line in (text or "").splitlines()
        if line.strip()
    ]

    if len(lines) < 3:
        raise PoetryScriptError(
            "poetry mode requires title, author and at least one poem line"
        )

    title = lines[0]
    author = lines[1]
    poem_lines = tuple(lines[2:])

    validate_poetry_script(title=title, author=author, poem_lines=poem_lines)

    return PoetryScript(
        title=title,
        author=author,
        poem_lines=poem_lines,
    )
```

### 6.2 为什么单独建 `poetry.py`

唐诗文本解析不是通用字幕逻辑，也不是渲染逻辑。它属于业务语义层：

```text
用户文本 -> 唐诗结构
```

单独建模块有以下好处：

1. WebUI 可以复用它做提交前校验。
2. `task.py` 可以复用它做后端校验。
3. `poetry_renderer.py` 可以复用它读取诗名、作者、正文。
4. 后续如果要支持歌词模式、文言文模式，可以继续扩展而不是污染现有服务。

### 6.3 新增 `app/services/poetry_renderer.py`

这个模块只负责视觉渲染，不负责音频、TTS 或业务校验。

对外接口建议：

```python
def build_poetry_overlays(
    subtitle_path: str,
    poetry_script: PoetryScript,
    params: VideoParams,
    video_width: int,
    video_height: int,
    audio_duration: float,
    font_path: str,
) -> list[ImageClip]:
    ...
```

输入：

| 参数 | 来源 | 说明 |
|---|---|---|
| `subtitle_path` | `storage/tasks/<task_id>/subtitle.srt` | 提供真实音频时间轴 |
| `poetry_script` | `parse_poetry_script(params.video_script)` | 提供诗名、作者、正文 |
| `params` | `VideoParams` | 复用字体、颜色、描边等现有样式 |
| `video_width` / `video_height` | `VideoAspect.to_resolution()` | 画布尺寸 |
| `audio_duration` | 当前旁白 `AudioFileClip.duration` | 常驻图层的结束时间 |
| `font_path` | 现有字体目录 + `params.font_name` | Pillow 渲染字体 |

输出：

```python
list[ImageClip]
```

返回的是可直接交给 `CompositeVideoClip` 的透明图层。

## 7. 通用按行断句能力

### 7.1 修改文件

```text
app/utils/utils.py
```

新增：

```python
def split_string_by_lines(s: str) -> list[str]:
    return [
        line.strip()
        for line in (s or "").splitlines()
        if line.strip()
    ]
```

### 7.2 为什么放在 `utils.py`

`split_string_by_punctuations()` 已经位于 `app/utils/utils.py`，它表示一种通用的脚本分段策略。

按行分段同样不是唐诗专属逻辑，未来歌词、课文朗读、多行口播都可能使用，因此放在通用工具层更合理。

### 7.3 与现有函数的关系

现有：

```python
utils.split_string_by_punctuations()
```

行为保持不变。

新增：

```python
utils.split_string_by_lines()
```

两者区别：

| 输入 | `split_string_by_punctuations()` | `split_string_by_lines()` |
|---|---|---|
| `人生无根蒂，飘如陌上尘。` | `人生无根蒂` / `飘如陌上尘` | `人生无根蒂，飘如陌上尘。` |
| `A。\nB，C。` | `A` / `B` / `C` | `A。` / `B，C。` |

## 8. TTS 与 SRT 生成修改

### 8.1 修改文件

```text
app/services/voice.py
```

### 8.2 修改 `create_subtitle()`

当前签名：

```python
def create_subtitle(sub_maker: SubMaker, text: str, subtitle_file: str):
    text = _format_text(text)
    script_lines = utils.split_string_by_punctuations(text)
    ...
```

调整为：

```python
def create_subtitle(
    sub_maker: SubMaker,
    text: str,
    subtitle_file: str,
    segmentation: Literal["punctuation", "line"] = "punctuation",
):
    text = _format_text(text)

    if segmentation == "line":
        script_lines = utils.split_string_by_lines(text)
    else:
        script_lines = utils.split_string_by_punctuations(text)

    ...
```

后面的 `_build_subtitle_items_from_edge_cues()`、`_build_subtitle_items_from_legacy_submaker()` 不需要改变核心算法。

原因：

1. 它们的职责是把 TTS 细碎 cue 聚合成目标脚本行。
2. `_match_script_line()` 比较时会去标点、归一化文本。
3. 因此目标行从“标点句”换成“物理行”后，聚合逻辑仍然成立。

### 8.3 为什么 TTS 输入仍然使用完整视频文案

唐诗模式不应该只把正文送给 TTS。

因为诗名和作者也要朗读：

```text
【拟古·其一】
魏晋 · 陶渊明
人生无根蒂，飘如陌上尘。
...
```

如果只送正文，音频会缺少诗名和作者。

所以：

```text
TTS 输入 = title + author + poem_lines
SRT 输入 = title + author + poem_lines
渲染器使用 = title / author 固定头部 + poem_lines 正文 cue
```

### 8.4 SRT 结构

以上一首诗为例，`subtitle.srt` 逻辑上类似：

```srt
1
00:00:00,000 --> 00:00:02,800
【拟古·其一】

2
00:00:02,800 --> 00:00:04,600
魏晋 · 陶渊明

3
00:00:04,600 --> 00:00:07,900
人生无根蒂，飘如陌上尘。

4
00:00:07,900 --> 00:00:11,200
分散逐风转，此已非常身。
```

注意：时间值为示例，实际时间来自 TTS cue。

渲染器使用规则：

| SRT cue | 渲染行为 |
|---|---|
| cue 1：诗名 | 不按 cue start 显示，从 `0s` 常驻 |
| cue 2：作者 | 不按 cue start 显示，从 `0s` 常驻 |
| cue 3：正文第 1 行 | 从 cue start 显示到视频结束 |
| cue 4：正文第 2 行 | 从 cue start 显示到视频结束 |

## 9. Whisper / 上传音频兼容设计

当前上传音频不会产生 `sub_maker`，只能依赖 Whisper。

### 9.1 第一版策略

如果：

```text
subtitle_style == "poetry"
custom_audio_file 不为空
sub_maker 为空
```

则只有 `subtitle_provider == "whisper"` 时继续处理。

Whisper 生成原始字幕后，调用 `subtitle.correct()` 时也使用按行目标：

```python
subtitle.correct(
    subtitle_file=subtitle_path,
    video_script=video_script,
    segmentation="line",
)
```

### 9.2 修改 `subtitle.correct()`

修改文件：

```text
app/services/subtitle.py
```

签名调整为：

```python
def correct(
    subtitle_file: str,
    video_script: str,
    segmentation: Literal["punctuation", "line"] = "punctuation",
):
```

内部从：

```python
script_lines = utils.split_string_by_punctuations(normalized_script)
```

改为：

```python
if segmentation == "line":
    script_lines = utils.split_string_by_lines(normalized_script)
else:
    script_lines = utils.split_string_by_punctuations(normalized_script)
```

### 9.3 稳定性说明

TTS 模式下，Edge TTS 返回 word boundary，按行聚合较稳定。

Whisper 模式下，识别分段和用户输入行不一定一致，所以唐诗模式的上传音频体验可能不如 TTS 稳定。第一版允许使用，但 UI 应说明推荐使用自动 TTS。

## 10. 任务流水线修改

### 10.1 修改文件

```text
app/services/task.py
```

### 10.2 提前校验唐诗结构

在 `_run_pipeline()` 里，进入昂贵阶段前校验。

建议放在生成脚本之后、TTS 之前：

```python
poetry_script = None

if (
    params.subtitle_enabled
    and params.subtitle_style == "poetry"
):
    try:
        poetry_script = parse_poetry_script(video_script)
    except PoetryScriptError as exc:
        return _mark_task_failed(
            task_id,
            "subtitle",
            str(exc),
        )
```

提前校验的原因：

1. 避免格式错误的唐诗先消耗 TTS、素材下载、FFmpeg 等资源。
2. 用户能更快看到明确错误。
3. 渲染阶段不需要再次猜文本结构。

### 10.3 修改 `generate_subtitle()`

当前调用：

```python
voice.create_subtitle(
    text=video_script,
    sub_maker=sub_maker,
    subtitle_file=subtitle_path,
)
```

改为：

```python
segmentation = (
    "line"
    if params.subtitle_style == "poetry"
    else "punctuation"
)

voice.create_subtitle(
    text=video_script,
    sub_maker=sub_maker,
    subtitle_file=subtitle_path,
    segmentation=segmentation,
)
```

Whisper 分支同样传入：

```python
subtitle.correct(
    subtitle_file=subtitle_path,
    video_script=video_script,
    segmentation=segmentation,
)
```

### 10.4 唐诗模式字幕生成失败时的行为

普通模式当前允许字幕生成失败后继续生成无字幕视频。

唐诗模式不同。如果没有 `subtitle.srt`，渲染器就没有正文时间轴，最终视频不完整。

建议行为：

```python
if (
    params.subtitle_enabled
    and params.subtitle_style == "poetry"
    and not subtitle_path
):
    return _mark_task_failed(
        task_id,
        "subtitle",
        "failed to generate poetry subtitles",
    )
```

理由：

1. 用户选择唐诗模式的核心诉求就是按音频展开诗句。
2. 静默生成无字幕视频会让用户误以为成功。
3. 明确失败更容易排查 TTS 分段问题。

## 11. 唐诗渲染器设计

### 11.1 渲染原则

渲染器只做三件事：

1. 读取 SRT 时间轴。
2. 用 Pillow 把诗名、作者、正文渲染成透明位图。
3. 用 MoviePy `ImageClip` 设置出现时间和持续时间。

不修改音频，不下载素材，不处理视频拼接。

### 11.2 图层结构

最终视频图层：

```text
底层：素材视频画面
上层：唐诗透明图层
音频：旁白 + 可选 BGM
```

唐诗透明图层包括：

```text
诗名图层
作者图层
正文第 1 行图层
正文第 2 行图层
...
正文第 N 行图层
```

### 11.3 时间规则

伪代码：

```python
overlays = []

overlays.append(
    make_static_clip(
        image=render_title(title),
        start=0,
        end=audio_duration,
    )
)

overlays.append(
    make_static_clip(
        image=render_author(author),
        start=0,
        end=audio_duration,
    )
)

body_cues = cues[poetry.metadata_line_count:]

for line, cue in zip(poetry_script.poem_lines, body_cues):
    overlays.append(
        make_static_clip(
            image=render_vertical_line(line),
            start=cue.start,
            end=line_exit_time(line_index, cue, audio_duration),
        )
    )

return overlays
```

关键差异：

| 模式 | 每条字幕结束时间 |
|---|---|
| 普通字幕 | SRT cue end |
| 唐诗正文，未触发滑动 | 视频旁白结束时间 |
| 唐诗正文，触发滑动 | 被新句推出正文滑动区的时刻 |

因此正文行不会因为下一句出现而立刻替换；只有画面装不下时，才会按滑动窗口离场。

### 11.4 文字渲染

使用 Pillow 生成透明 RGBA 图片。

对一行：

```text
人生无根蒂，飘如陌上尘。
```

`right_to_left` 和 `left_to_right` 方向下渲染成一个竖排列：

```text
人
生
无
根
蒂
飘
如
陌
上
尘
```

`top_to_bottom` 方向下渲染成一行横排文字；后续扩展如果要支持横排标点，再单独调整标点规则。

竖排模式标点默认不渲染。

原因：

1. 竖排中文标点容易占据不自然空隙。
2. 唐诗画面通常省略标点更干净。
3. 可以减少列高，降低溢出概率。

建议跳过的标点集合：

```python
POETRY_VERTICAL_SKIP_CHARS = set("，。！？；：、,.!?;:")
```

竖排和横排模式都跳过空格。

### 11.5 布局方向

方向参数由渲染器从 `params.poetry_direction` 读取。三种方向的含义如下：

| 方向 | 正文形态 | 固定头部位置 | 正文推进方式 |
|---|---|---|---|
| `right_to_left` | 竖排列 | 右侧 | 第 1 句靠近头部，后续句向左推进 |
| `left_to_right` | 竖排列 | 左侧 | 第 1 句靠近头部，后续句向右推进 |
| `top_to_bottom` | 横排行 | 顶部 | 第 1 句靠近头部，后续句向下推进 |

默认：

```text
poetry_direction = "right_to_left"
```

`right_to_left` 的初始静态布局：

```text
左侧正文滑动区                     右侧固定头部
[正文最新句] ... [正文第 1 句] [作者] [诗名]
```

`left_to_right` 则镜像为：

```text
左侧固定头部                       右侧正文滑动区
[诗名] [作者] [正文第 1 句] ... [正文最新句]
```

`top_to_bottom` 为：

```text
顶部固定头部
[诗名] [作者]
正文第 1 句
正文第 2 句
...
正文最新句
```

诗名和作者始终常驻，不参与正文滑动窗口。正文区从固定头部旁边的内层边界开始计算，避免滑动后的旧句压到头部。

内容区由四个用户可调边距决定。渲染器从 `VideoParams` 读取：

```python
margin_top = video_height * params.poetry_margin_top / 100
margin_bottom = video_height * params.poetry_margin_bottom / 100
margin_left = video_width * params.poetry_margin_left / 100
margin_right = video_width * params.poetry_margin_right / 100

safe_x = margin_left
safe_y = margin_top
safe_width = video_width - margin_left - margin_right
safe_height = video_height - margin_top - margin_bottom
```

默认 `6%` 时，1080x1920 的结果：

```text
safe_x = 64.8
safe_y = 115.2
safe_width = 1080 - 64.8 * 2 = 950.4
safe_height = 1920 - 115.2 * 2 = 1689.6
```

四个边距都在 `0% - 25%` 范围内校验，因此最大情况下仍会保留一半画面给内容。用户设置的是最终内容边距，渲染器不再额外叠加隐藏的 optical inset。

#### 内容构图与起点

渲染器不能把第一句直接贴到屏幕边界，也不能按“四句”“六句”写死固定坐标。实际做法是先建立内容框，再根据测量结果放置内容：

```text
1. 按用户配置的四个 `poetry_margin_*` 计算内容 safe area。
2. 放置固定的诗名和作者头部。
3. 用 header_body_gap 在头部旁边划出正文滑动区。
4. 测量整首诗的真实 bounding box。
5. 所有正文都在滑动区内时，使用静态构图；放不下时启用滑动窗口。
```

建议初始比例：

```python
HEADER_BODY_GAP_RATIO = 0.60
```

默认边距已经提供呼吸空间；如果用户把某一边设为 `0%`，则尊重用户设置，允许内容贴近该边。这样边距的含义和 CSS `margin` 一样直观。

`right_to_left` 的正文区：

```text
屏幕左边距
  -> 正文左边界
  -> 正文内容
  -> header_body_gap
  -> 作者列
  -> 诗名列
  -> 屏幕右边距
```

`left_to_right` 镜像处理；`top_to_bottom` 则在顶部头部下方留出 `header_body_gap`，再开始正文行。方向只决定正文推进方式；四个边距始终按同一套内容框逻辑生效。

对四句、六句、长短句混合的词牌或散文式长句，排版规则保持一致：

1. 最长物理句决定正交方向需要的最小空间。
2. 句数决定推进方向需要的空间。
3. 短诗使用静态构图，第一句靠近固定头部，尾部自然留白；不为了“填满画面”放大到突兀的字号。
4. 长短句混合时不强行左右/上下两端对齐；竖排列保持顶部基线一致，横排行保持左侧基线一致。
5. 句数超过正文区时，不缩小整首诗硬塞，而是进入滑动窗口。

这样《洛神赋》这类长文、《沁园春》这类长短句、普通四句或六句诗，都会使用同一套“安全区 -> 内容框 -> 头部 -> 正文框 -> 滑动窗口”的计算流程，而不是依赖每首诗手工调整坐标。

### 11.6 尺寸计算

对每一列：

```text
column_height = max(1, len(chars) * font_size * CHAR_HEIGHT_RATIO)
column_width = font_size * COLUMN_WIDTH_RATIO
```

初始值建议：

```python
CHAR_HEIGHT_RATIO = 1.18
COLUMN_WIDTH_RATIO = 1.25
COLUMN_GAP_RATIO = 0.18
```

诗名和作者字号：

```python
title_font_size = body_font_size * 1.15
author_font_size = body_font_size * 0.72
```

### 11.7 溢出与滑动窗口

渲染器仍然必须先测量布局，再渲染图层；但整首诗的行数或列数不再通过持续缩小字号来硬塞进画面，也不因为行数多而失败。

测量分两层：

```text
1. 正交方向：竖排列的高度，或横排行的宽度。
2. 推进方向：正文列/行加上间距后的累计跨度。
```

正交方向过长时，先按安全区缩小字号：

```text
1. 使用 params.font_size 作为初始字号。
2. 测量最高正文列或最宽正文行。
3. 如果超过正交方向安全区，按比例缩小字号、列宽、行高、间距。
4. 设置最小字号，例如 24。
5. 到达最小字号仍放不下时，把该物理句拆成续列或续行。
```

这一步只解决“一句太长”，不解决“整首诗太多”。推进方向的容量交给滑动窗口。

滑动窗口规则：

```text
1. 先按当前字号计算每个正文项的推进方向尺寸。
2. 计算正文滑动区容量：安全区跨度 - 固定头部跨度 - 头部间距。
3. 所有正文项能放下时，使用静态布局。
4. 放不下时，每出现一句新正文，重新计算窗口偏移，让最新句留在正文滑动区内。
5. 被推出正文滑动区的旧句不再显示。
6. 头部诗名和作者不受滑动影响。
```

偏移是确定性的，按 SRT cue 时间计算，不依赖逐帧音频检测：

```python
def window_offset(cumulative_extent: float, window_length: float) -> float:
    overflow = max(0.0, cumulative_extent - window_length)
    return -overflow
```

`cumulative_extent` 是“从正文区起点到最新句结束”的累计长度。`window_length` 是正文滑动区容量。偏移方向与推进方向相反，相当于把队列往头部反方向收拢；旧句越过正文区边界时结束显示。

渲染伪代码：

```python
font_size = fit_orthogonal_font_size(
    poetry_script=poetry_script,
    params=params,
    safe_width=video_width,
    safe_height=video_height,
)

layout = measure_body_layout(
    poetry_script=poetry_script,
    direction=params.poetry_direction,
    font_size=font_size,
)

overlays = []

for index, item in enumerate(layout.body_items):
    start = item.cue.start
    end = audio_duration

    if item.is_pushed_out_at(start):
        end = start + SLIDE_DURATION
    elif item.will_be_pushed_out_later:
        end = item.exit_time

    position = sliding_position(
        item=item,
        layout=layout,
        time=start,
        slide_duration=SLIDE_DURATION,
    )

    overlay = (
        ImageClip(item.image)
        .with_start(start)
        .with_end(end)
        .with_position(position)
    )
    overlays.append(overlay)
```

滑动建议使用 `0.3s` 缓动，并且只在某条新 cue 的开始时刻触发一次。位置函数仍由已知 SRT 时间驱动，输出确定，不引入逐帧随机或音频检测。

例如选择 `right_to_left`：

```text
前几句放得下：新列向左展开，旧列不动。
累计跨度溢出：整组向右收拢，最新列保持在正文滑动区内。
旧列被完全推过正文区右边界：该列 end 到达，不再显示。
```

`left_to_right` 与 `top_to_bottom` 使用同一算法，只是推进向量和滑动区边界不同。

这个策略保证：

1. 不限制输入行数。
2. 不把大量文字缩小到不可读。
3. 最新诗句始终可见。
4. 已经读过的诗句在画面装不下时自然离场。

### 11.8 样式来源

第一版复用现有字幕参数：

| 现有参数 | 唐诗模式用途 |
|---|---|
| `font_name` | 竖排文字字体 |
| `font_size` | 正文字号初始值 |
| `text_fore_color` | 正文和头部文字颜色 |
| `stroke_color` | 文字描边颜色 |
| `stroke_width` | 文字描边宽度 |

不使用：

| 参数 | 原因 |
|---|---|
| `subtitle_position` | 唐诗模式有固定版式 |
| `custom_position` | 同上 |
| `text_background_color` | 第一版不做横向字幕背景 |
| `rounded_subtitle_background` | 第一版不做圆角背景 |

WebUI 中这些不适用的控件在唐诗模式下应禁用。

### 11.9 内置装饰样式

为了接近参考效果，渲染器可以内置以下默认值：

```python
POETRY_DEFAULT_TEXT_COLOR = "#E8C877"
POETRY_DEFAULT_STROKE_COLOR = "#7A5A2A"
POETRY_DEFAULT_DIVIDER_COLOR = "#D8BB80"
POETRY_DEFAULT_DIVIDER_ALPHA = 170
```

但第一版建议不新增 UI 输入。

实现策略：

1. 如果用户显式改过字体颜色和描边颜色，则使用用户值。
2. 如果仍然是默认白色和黑色，则唐诗模式可以使用内置金色样式。
3. 后续版本再考虑暴露“使用唐诗默认配色”的开关。

### 11.10 分隔线

参考图里每列之间有竖线。

渲染器可以在每列左侧绘制一条细竖线：

```text
颜色：POETRY_DEFAULT_DIVIDER_COLOR
透明度：约 67%
宽度：max(1, font_size / 36)
高度：该列文字高度
与文字间距：font_size * 0.22
```

分隔线属于列图片的一部分，不单独作为 MoviePy 图层，减少合成对象数量。

### 11.11 淡入动画

第一版可以做简单淡入：

```python
clip = clip.with_effects([vfx.FadeIn(0.35)])
```

诗名和作者可以不淡入，直接从 `0s` 显示。

正文行淡入：

```text
时长：0.3 - 0.4 秒
触发时间：该行 SRT start
```

如果性能测试发现低配设备合成变慢，可以把淡入做成常量开关并默认关闭。

## 12. 视频合成入口修改

### 12.1 修改文件

```text
app/services/video.py
```

### 12.2 修改位置

`generate_video()` 中现有普通字幕逻辑保持在原分支内。

在进入 `ExitStack()` 后判断：

```python
use_poetry_overlays = (
    params.subtitle_enabled
    and params.subtitle_style == "poetry"
    and bool(subtitle_path)
)
```

如果为真：

```python
poetry_script = parse_poetry_script(params.video_script)

poetry_overlays = poetry_renderer.build_poetry_overlays(
    subtitle_path=subtitle_path,
    poetry_script=poetry_script,
    params=params,
    video_width=video_width,
    video_height=video_height,
    audio_duration=voice_source_clip.duration,
    font_path=font_path,
)

video_clip = CompositeVideoClip(
    [source_video_clip, *poetry_overlays]
)
```

否则进入现有逻辑：

```python
if subtitle_path and os.path.exists(subtitle_path):
    sub = SubtitlesClip(...)
    text_clips = [...]
    video_clip = CompositeVideoClip([video_clip, *text_clips])
```

### 12.3 为什么不改现有 `create_text_clip()`

`create_text_clip()` 包含大量普通字幕兼容逻辑：

1. 自动换行。
2. 背景。
3. 圆角背景。
4. 描边。
5. 顶部、底部、居中、自定义位置。

这些逻辑对唐诗模式没有意义。

如果在里面继续加 `if poetry`，会导致：

1. 函数职责混乱。
2. 普通字幕回归测试范围扩大。
3. 后续新增竖排样式时继续堆分支。

因此新建 `poetry_renderer.py` 是更合理的解耦点。

## 13. WebUI 修改

### 13.1 修改文件

```text
webui/Main.py
webui/i18n/zh.json
webui/i18n/en.json
```

### 13.2 字幕设置面板

在现有字幕设置中新增：

```text
字幕样式：普通字幕 / 唐诗字幕
```

在字幕样式下方新增：

```text
字幕方向：从右至左 / 从左至右 / 从上至下
```

该控件只在 `唐诗字幕` 下启用。

字幕方向下方新增四组数字输入：

```text
上边距（%）：6
右边距（%）：6
下边距（%）：6
左边距（%）：6
```

这组控件也只在 `唐诗字幕` 下启用。可以把它们放在同一个 `st.columns(4)` 行里，避免字幕面板过长。`right_to_left` 时可以在 UI 中高亮“右边距”，因为它是该方向的视觉起点；`left_to_right` 高亮“左边距”；`top_to_bottom` 高亮“上边距”。但四个输入框始终都可修改，保持 CSS margin 的四边语义。

用户选择 `唐诗字幕` 后：

1. “视频文案”输入框显示格式提示。
2. 禁用普通字幕位置选择。
3. 禁用字幕背景和圆角背景。
4. 保留字体、字号、字体颜色、描边设置。
5. 显示当前文案解析结果或错误提示。

### 13.3 输入提示

提示文案示例：

```text
唐诗字幕模式按物理行解析：
第 1 行为诗名；
第 2 行为作者；
第 3 行起每行一句，朗读到该行时展开并保留。
画面放不下时按所选方向滑动，最早滑出的旧句不再显示。
```

示例文案可以直接展示：

```text
【拟古·其一】
魏晋 · 陶渊明
人生无根蒂，飘如陌上尘。
分散逐风转，此已非常身。
...
```

### 13.4 提交前校验

在 `_render_generation_controls()` 或字幕设置面板中调用：

```python
try:
    poetry_script = parse_poetry_script(params.video_script)
except PoetryScriptError as exc:
    st.error(str(exc))
    st.stop()
```

后端仍要再次校验，原因是：

1. WebUI 校验只是体验优化。
2. API 和 CLI 可以绕过前端。
3. 历史任务恢复后仍可能被用户修改。

### 13.5 默认设置

`DEFAULT_SUBTITLE_SETTINGS` 新增：

```python
"subtitle_style": "standard",
```

```python
"poetry_direction": "right_to_left",
```

```python
"poetry_margin_top": 6.0,
"poetry_margin_right": 6.0,
"poetry_margin_bottom": 6.0,
"poetry_margin_left": 6.0,
```

选择后调用：

```python
_set_runtime_config("ui", "subtitle_style", params.subtitle_style)
_set_runtime_config("ui", "poetry_direction", params.poetry_direction)
_set_runtime_config("ui", "poetry_margin_top", params.poetry_margin_top)
_set_runtime_config("ui", "poetry_margin_right", params.poetry_margin_right)
_set_runtime_config("ui", "poetry_margin_bottom", params.poetry_margin_bottom)
_set_runtime_config("ui", "poetry_margin_left", params.poetry_margin_left)
```

这样用户下次打开页面时保留上次选择。

### 13.6 历史任务恢复

`_apply_restored_params()` 需要新增：

```python
subtitle_style = params.get("subtitle_style") or "standard"
_set_stable_widget_value(
    "subtitle_style_select",
    subtitle_style,
)

poetry_direction = params.get("poetry_direction") or "right_to_left"
_set_stable_widget_value(
    "poetry_direction_select",
    poetry_direction,
)

for side in ("top", "right", "bottom", "left"):
    margin = params.get(f"poetry_margin_{side}")
    if margin is None:
        margin = 6.0
    _set_stable_widget_value(
        f"poetry_margin_{side}_number",
        margin,
    )
```

老任务没有该字段时，恢复为 `standard`。

### 13.7 设置预设导入导出

设置预设 payload 使用 `VideoParams` 序列化结果。

新增字段会自动进入导出文件：

```json
{
  "subtitle_style": "poetry",
  "poetry_direction": "right_to_left",
  "poetry_margin_top": 6.0,
  "poetry_margin_right": 6.0,
  "poetry_margin_bottom": 6.0,
  "poetry_margin_left": 6.0
}
```

导入时：

1. Pydantic 校验字段。
2. `standard` 或 `poetry` 之外非法值直接拒绝。
3. 三个方向之外的 `poetry_direction` 也直接拒绝。
4. 边距必须满足 `0 <= value <= 25`。
5. `_apply_restored_params()` 恢复控件状态。

## 14. i18n

新增 key 建议：

```json
{
  "Subtitle Style": "字幕样式",
  "Standard Subtitles": "普通字幕",
  "Poetry Subtitles": "唐诗字幕",
  "Poetry Direction": "字幕方向",
  "Right To Left": "从右至左",
  "Left To Right": "从左至右",
  "Top To Bottom": "从上至下",
  "Poetry Margin": "内容边距",
  "Top Margin Percentage": "上边距（%）",
  "Right Margin Percentage": "右边距（%）",
  "Bottom Margin Percentage": "下边距（%）",
  "Left Margin Percentage": "左边距（%）",
  "Poetry Script Format Help": "唐诗字幕按物理行解析：第 1 行诗名，第 2 行作者，第 3 行起每行一句。",
  "Poetry Script Too Short": "唐诗模式至少需要诗名、作者和一句正文。",
  "Poetry Script Line Help": "每个非空物理行会作为一条诗句 cue。"
}
```

英文同步补充对应翻译。

## 15. 存储与任务快照

### 15.1 `script.json`

现有任务快照由：

```text
app/services/task_artifacts.py
```

写入：

```text
storage/tasks/<task_id>/script.json
```

`VideoParams` 新增字段后会自然序列化：

```json
{
  "subtitle_style": "poetry",
  "poetry_direction": "right_to_left",
  "poetry_margin_top": 6.0,
  "poetry_margin_right": 6.0,
  "poetry_margin_bottom": 6.0,
  "poetry_margin_left": 6.0,
  "video_script": "【拟古·其一】\n魏晋 · 陶渊明\n人生无根蒂，飘如陌上尘。\n..."
}
```

不需要单独存储诗名和作者，因为它们可以由 `video_script` 解析得到。

### 15.2 `subtitle.srt`

仍然使用现有路径：

```text
storage/tasks/<task_id>/subtitle.srt
```

唐诗模式中它包含：

```text
诗名 cue
作者 cue
正文 cue 1
正文 cue 2
...
```

保留诗名和作者 cue 的原因：

1. SRT 时间轴来自完整 TTS 音频。
2. 正文 cue 的 start 必须跳过诗名和作者朗读时间。
3. 用户可以直接检查 SRT 来排查时间轴问题。

### 15.3 不新增渲染缓存文件

第一版不把竖排 PNG 写入磁盘。

原因：

1. Pillow 可以直接生成内存图像。
2. 每个任务只渲染几十个图层，性能压力可控。
3. 减少临时文件清理逻辑。
4. 避免污染 `storage/tasks/<task_id>/`。

如果后续发现特别长的诗导致内存或性能问题，再考虑缓存 PNG。

## 16. API 兼容性

### 16.1 完整视频生成接口

完整生成接口使用 `VideoParams`，新增字段自动可用：

```json
{
  "video_subject": "拟古",
  "video_script": "【拟古·其一】\n魏晋 · 陶渊明\n人生无根蒂，飘如陌上尘。\n分散逐风转，此已非常身。",
  "video_source": "local",
  "subtitle_enabled": true,
  "subtitle_style": "poetry",
  "poetry_direction": "right_to_left",
  "poetry_margin_top": 6.0,
  "poetry_margin_right": 6.0,
  "poetry_margin_bottom": 6.0,
  "poetry_margin_left": 6.0
}
```

老请求不传 `subtitle_style`，默认：

```json
{
  "subtitle_style": "standard",
  "poetry_direction": "right_to_left",
  "poetry_margin_top": 6.0,
  "poetry_margin_right": 6.0,
  "poetry_margin_bottom": 6.0,
  "poetry_margin_left": 6.0
}
```

### 16.2 独立字幕接口

第一版不扩展独立 `/subtitle` 预览接口。

原因：

1. 该接口当前主要服务普通字幕预览。
2. 唐诗效果依赖最终画面布局，不只是 SRT。
3. 单独做预览会增加第一版范围。

后续如需支持，再给 `SubtitleRequest` 添加 `subtitle_style`。

## 17. 修改文件清单

### 17.1 新增

```text
app/services/poetry.py
app/services/poetry_renderer.py
```

### 17.2 修改

```text
app/models/schema.py
app/utils/utils.py
app/services/voice.py
app/services/subtitle.py
app/services/task.py
app/services/video.py
webui/Main.py
webui/i18n/zh.json
webui/i18n/en.json
```

### 17.3 新增测试

如果项目当前测试结构允许，建议新增：

```text
test/services/test_poetry_script.py
test/services/test_poetry_srt.py
test/services/test_poetry_renderer.py
```

最小测试范围：

1. `parse_poetry_script()`。
2. `split_string_by_lines()`。
3. `create_subtitle(segmentation="line")`。
4. `correct(segmentation="line")`。
5. 渲染器时间规则。
6. 渲染器方向选择。
7. 渲染器滑动窗口。
8. 普通字幕回归。

## 18. 具体实现顺序

### Phase 1：后端最小闭环

1. `schema.py` 增加 `subtitle_style`、`poetry_direction` 和四边 `poetry_margin_*`。
2. `utils.py` 增加 `split_string_by_lines()`。
3. 新增 `poetry.py` 解析器。
4. `voice.py` 支持按行 SRT。
5. `task.py` 增加唐诗校验和 segmentation 传递。
6. 新增 `poetry_renderer.py`。
7. `video.py` 接入渲染分支。

完成后可以用 API 或测试脚本生成一个完整唐诗视频。

### Phase 2：WebUI

1. 增加字幕样式选择。
2. 增加格式提示和解析错误提示。
3. 增加四边内容边距输入，默认 `6%`。
4. 禁用不适用的普通字幕控件。
5. 更新历史任务恢复。
6. 更新设置预设导入导出。
7. 更新中英文 i18n。

### Phase 3：样式打磨

1. 金色默认配色。
2. 列间分隔线。
3. 当前句淡入。
4. 可选当前句高亮。
5. 不同画幅下的布局微调。
6. 性能测试和滑动动画打磨。

## 19. 测试计划

### 19.1 单元测试

#### `parse_poetry_script()`

覆盖：

1. 正常解析。
2. CRLF 换行。
3. 空行忽略。
4. 首尾空白清理。
5. 少于 3 行报错。
6. 超长行不作为提交错误。
7. 只保留前两个非空行作为头部。

#### `split_string_by_lines()`

覆盖：

1. 单行。
2. 多行。
3. 空行。
4. Windows CRLF。
5. 行内标点不切分。

#### `create_subtitle(segmentation="line")`

准备 fake `sub_maker.cues`，验证：

1. 每个物理行生成一条 SRT。
2. 行内逗号不拆分。
3. SRT start 使用该行第一个 cue。
4. SRT end 使用该行最后一个 cue。
5. cue 数量与物理行数量一致。

### 19.2 渲染器测试

验证：

1. 诗名图层 start 为 0。
2. 作者图层 start 为 0。
3. 正文图层 start 等于 SRT cue start。
4. 未触发滑动时，正文图层 end 等于 `audio_duration`。
5. 静态布局下可见图层在安全区域内。
6. 三种方向分别生成正确的推进方向。
7. 默认四边 `6%` 时，内容框位置和尺寸计算正确。
8. 自定义四边边距时，safe area 按对应宽高百分比计算。
9. 整首诗溢出时触发滑动窗口。
10. 最新正文句在滑动后仍在正文滑动区内。
11. 被完全滑出的旧句 end 时间早于视频结束。

### 19.3 回归测试

必须确认普通模式无变化：

1. 普通文案仍然按标点和换行断句。
2. 普通 SRT 内容与旧逻辑一致。
3. 普通字幕位置、背景、圆角背景仍可用。
4. 不开启唐诗模式时，不调用 poetry renderer。
5. 老 `script.json` 缺少 `subtitle_style` 时任务正常。
6. 老 `script.json` 缺少 `poetry_margin_*` 时渲染器使用默认 `6%`。

### 19.4 手工验收用例

用例 1：标准六行诗

```text
【拟古·其一】
魏晋 · 陶渊明
人生无根蒂，飘如陌上尘。
分散逐风转，此已非常身。
落地为兄弟，何必骨肉亲！
得欢当作乐，斗酒聚比邻。
盛年不重来，一日难再晨。
及时当勉励，岁月不待人。
```

预期：

1. TTS 朗读诗名、作者和六行正文。
2. 视频开始时诗名和作者可见。
3. 六句正文按音频依次展开。
4. 已展开正文保留到最后，或仅在画面装不下时按滑动窗口离场。

用例 2：横屏视频

```text
video_aspect = landscape
```

预期：

1. 竖排文字完整显示。
2. 不与视频安全区外边缘重叠。
3. 超长句的正交方向缩放和续列/续行处理合理。

用例 3：长诗和滑动窗口

构造远超画面可容纳行数的多行文案，分别测试 `right_to_left`、`left_to_right` 和 `top_to_bottom`。

预期：

1. 任务不因为行数多而失败。
2. 新句出现时队列按所选方向滑动。
3. 最新句始终可见。
4. 已被完全滑出正文滑动区的旧句不再显示。

用例 4：自定义边距

使用默认文案，修改：

```text
poetry_margin_top = 8
poetry_margin_right = 10
poetry_margin_bottom = 6
poetry_margin_left = 4
```

预期：

1. 内容框按对应宽高百分比重新计算。
2. 文字和头部不会越过自定义边距。
3. 剩余正文区放不下时，滑动窗口仍然以新的内容框为边界。

用例 5：上传音频

使用自定义音频并开启 Whisper。

预期：

1. 任务可以完成。
2. SRT 会尝试按物理行校正。
3. UI 已说明推荐使用自动 TTS。

## 20. 影响面评估

### 20.1 低风险

| 模块 | 原因 |
|---|---|
| `app/utils/utils.py` | 只新增函数，不修改现有函数 |
| `app/models/schema.py` | 只新增带默认值的字段 |
| `app/services/poetry.py` | 全新模块 |
| `app/services/poetry_renderer.py` | 全新模块 |

### 20.2 中风险

| 模块 | 风险 | 控制方式 |
|---|---|---|
| `app/services/voice.py` | `create_subtitle()` 增加参数 | 默认值保持旧行为 |
| `app/services/task.py` | 任务流水线加入分支 | 只在 `poetry` 模式生效 |
| `app/services/video.py` | 视频合成加入分支 | 普通分支保持不动 |
| `webui/Main.py` | 字幕面板和历史任务恢复 | 使用默认值兼容老任务 |

### 20.3 需要重点回归的区域

1. 普通字幕生成。
2. Whisper 字幕校正。
3. 本地素材模式。
4. Pexels / Pixabay / Coverr 在线素材模式。
5. 历史任务恢复。
6. 设置预设导出导入。
7. 横屏、竖屏、方形视频合成。

## 21. 失败策略

| 场景 | 行为 |
|---|---|
| 非空行少于 3 行 | 任务进入 `subtitle` 阶段前失败 |
| TTS 按行聚失败，没有 SRT | 任务在 `subtitle` 阶段失败 |
| SRT cue 数量与诗行数量不一致 | 渲染前失败，避免错位显示 |
| 上传音频且未启用 Whisper | 提示唐诗模式需要 Whisper 或改用自动 TTS |
| 字体无法渲染字符 | 尽量自动替换字体或记录警告；第一版可复用现有字体能力检查 |

## 22. 性能评估

唐诗渲染新增开销主要来自：

1. Pillow 渲染透明文字。
2. MoviePy 管理更多 `ImageClip`。
3. `CompositeVideoClip` 合成更多图层。

对典型 6 到 8 行诗：

```text
图层总数 = 2 个头部 + 6 到 8 个正文行 = 8 到 10 个
```

普通字幕本来也会创建类似数量的 `TextClip`，所以性能影响可控。

优化策略：

1. 每行只渲染一次静态 RGBA 图像。
2. 分隔线画进行图片，不新增独立图层。
3. 不使用逐帧动画。
4. 淡入时长固定，不生成中间 PNG 序列。

## 23. 后续扩展方向

第一版稳定后，可以扩展：

1. 当前朗读句高亮。
2. 当前句放大或变色。
3. 诗名、作者字体独立配置。
4. 背景纹理或纸张质感。
5. 自动根据唐诗 API 补全诗名、作者。
6. 逐字书写动画。
7. 滑动窗口分页、收藏句或回看控制。
8. 独立唐诗视频模板。

这些能力都应继续放在 `poetry_renderer.py` 或独立 style 模块中，不侵入普通字幕。

## 24. 最终设计取舍

本方案的核心取舍是：

```text
不新增诗名/作者参数，用视频文案的前两个非空行表达头部信息。
普通字幕按标点和换行断句，唐诗字幕按物理行断句。
SRT 继续作为唯一时间轴来源。
渲染层独立，不改造普通字幕 TextClip。
布局方向可选，溢出时使用确定性滑动窗口，不限制输入行数。
```

这样可以在不破坏现有链路的情况下，实现“视频一开始显示诗名和作者，朗读时逐行展开唐诗”的效果。

## 25. 最新代码集成复核

按当前分支真实代码复核后，方案继续成立，但落地细节做以下修正：

1. `voice.create_subtitle()` 增加一个 `segmentation` 参数，默认仍是 `"punctuation"`；唐诗模式传入 `"line"`，内部继续复用现有 Edge cues 和 legacy `subs/offset` 两条聚合路径。
2. `subtitle.correct()` 同步增加 `segmentation` 参数，Whisper 上传音频的唐诗模式按物理行校正。
3. `custom_audio_file` 且 `sub_maker is None` 时，只有显式选择 Whisper 才能生成唐诗字幕；否则必须在 `subtitle` 阶段明确失败，不能静默输出无字幕视频。
4. 渲染层的常驻结束时间使用 `voice_source_clip.duration`，而不是任务层向上取整后的 `audio_duration`，避免最后一行字幕比真实音频提前消失。
5. 渲染前必须校验 SRT cue 数量和目标物理行数量一致，并尽量校验文本顺序；不一致时任务失败，避免诗行错位。
6. 最新 main 新增的 `video_fit_mode`、CORS 保护和 Windows 文件名修复与唐诗渲染不冲突；渲染器仍只在最终视频叠加图层，不进入素材裁剪逻辑。
7. WebUI 历史任务、设置预设导出导入、运行时 UI 配置都通过现有 `_apply_restored_params()`、`VideoParams.model_dump()` 和 `_set_runtime_config()` 补充新字段。
8. MoviePy 的 `with_position(callable)` 回调时间从图层自身开始计算。滑动位置函数必须绑定图层 `start`，先换算成视频绝对时间，再匹配 SRT/滑动状态时间。
9. 每个正文图层的退出时间需要遍历其后续滑动状态，并按该图层方向判断完全离开内容区的时间；单行拆出的多个续列/续行可以独立提前离场。

## 26. 当前实现架构复核：三层 viewport

最新实现已不再为每句正文创建一个 `ImageClip`，避免长诗产生大量重叠 MoviePy 图层，也让滑动和视窗裁剪在同一个坐标系内完成。

### 26.1 图层结构

```text
底层：素材视频
第 1 层：诗名 title_clip（ImageClip，0s 常驻）
第 2 层：作者 author_clip（ImageClip，0s 常驻）
第 3 层：正文 viewport body_clip（VideoClip + mask，0s 常驻）
```

`build_poetry_overlays()` 返回固定长度 3。诗名和作者是合并后的静态透明位图；正文层尺寸等于正文 viewport，不等于整幅视频。

### 26.2 正文层机制

`body_clip` 使用 `frame_function` 每帧渲染一次：

1. 所有正文列/行仍只渲染一次位图，并保存为 `BodyPieceLayout`。
2. 每帧根据 SRT 时间和 `OffsetState` 计算一次平滑滑动 offset。
3. 已经出现过的正文持续合成，属于累积式显示。
4. 超出 viewport 的部分通过物理裁剪合成，不通过缩短 MoviePy 图层时间来隐藏。
5. 旧正文进入 viewport 起始边界后按自身跨度淡出，避免突然整块消失。
6. 新正文按 `cue.start` 淡入，时长 `LINE_FADE_IN_DURATION = 0.24s`。
7. 滑动时长为 `SLIDE_DURATION = 0.4s`，两次 cue 间隔过近时从上一次动画的当前位置继续滑，避免跳变。

### 26.3 交叉轴与呼吸空间

竖排方向的主轴是横向推进，交叉轴是垂直居中；横排方向的主轴是纵向推进，交叉轴是水平居中。长句拆出的续列/续行同样按交叉轴居中。

列/行间距和头部与正文间距由字号派生：

```text
COLUMN_GAP_RATIO = 0.85
HEADER_BODY_GAP_RATIO = 1.0
```

竖排标点使用紧凑宽度 `PUNCT_ADVANCE_RATIO = 0.55`，减少中文逗号、句号在竖排中的异常空隙。

### 26.4 当前朗读高亮

逐字打字机方案已经改为更平滑的描边高亮：

1. `_reading_timings()` 把每条 cue 的时长按字符权重拆分；普通汉字权重 1.0，紧凑标点权重 0.55。
2. 高亮进入时间 `0.08s`，释放时间 `0.10s`，避免硬切换。
3. 当前字符用金色描边 `READING_STROKE_COLOR = "#F5C451"` 叠加；标点高亮透明度乘以 0.25，避免视觉跳动。
4. 高亮变体按 `(行, 拆片段, 字符索引)` 缓存，图片尺寸和正常位图保持一致，因此不会改变布局。

### 26.5 测试与验收

当前覆盖：

1. 三层返回结构和固定头部时间。
2. 三种方向都能构建。
3. 正文溢出后 viewport 仍有可见 alpha。
4. 滑动 offset 使用 SRT 绝对时间。
5. 逐字时间切分、淡入淡出 alpha、高亮变体尺寸与像素差异。

验收样图已使用真实任务素材渲染，确认旧列保留、整体滑动、边缘淡出、新列淡入和当前字金色高亮正常。
