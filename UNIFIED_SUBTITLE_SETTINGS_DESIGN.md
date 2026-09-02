# 统一字幕设置设计

状态：设计稿，未实施。  
目标：重写字幕设置与渲染配置，覆盖横排、竖排、替换式、整块、累积滚动等场景。  
范围：本文只定义目标字段、语义、尺寸计算、显示规则和渲染分层；不处理历史字段迁移。

---

## 1. 命名规则

## 1.1 字段命名

所有字幕字段都以 `subtitle_` 开头。

例如：

```text
subtitle_font
subtitle_font_size
subtitle_direction
subtitle_show_mode
subtitle_align_h
subtitle_align_v
```

不允许再使用裸的：

```text
font
show
direction
align_h
align_v
```

作为顶层业务字段。

## 1.2 枚举值命名

枚举值也要能脱离上下文看懂。

因此：

```text
subtitle_show_mode = "show_scroll"
```

而不是：

```text
subtitle_show_mode = "scroll"
```

同理：

```text
subtitle_direction = "direction_vertical_right_to_left"
subtitle_background_style = "background_style_rounded_translucent"
```

对于字段名已经能明确表达含义的简单枚举，可以继续使用短值，例如：

```text
subtitle_align_h = "left" / "center" / "right"
subtitle_align_v = "top" / "middle" / "bottom"
```

---

## 2. 核心概念

| 概念 | 英文名 | 含义 |
|---|---|---|
| 字幕区域 | viewport | 视频画面减去四边 margin 后得到的字幕可用区域 |
| 显示单元 | cue | 一个时间驱动的字幕显示单元，由 `subtitle_show_mode` 切分出来 |
| 槽 | slot | 一行横排文字或一列竖排文字的排版单位 |
| 槽容量盒 | slot capacity box | 槽可以使用的最大排版空间，用于判断什么时候换行 / 换列 |
| 槽可视盒 | slot visual box | 一个槽里实际文字、描边、背景等占用的包围盒 |
| cue 内容块 | cue content block | 一个 cue 的一个或多个 slot visual box 组成的包围盒 |
| 显示内容块 | display block | 当前实际参与 viewport 定位的内容块 |
| 内容块定位 | content block placement | 把 display block 放进 viewport 的过程 |

关键关系：

```text
1 个 cue 可以包含 1 个或 N 个 slot。
N 个 slot 组成当前 cue 的 cue content block。

show_punctuation / show_sentence：
display block = 当前 cue content block

show_scroll：
display block = 已经出现的累积内容块

show_block：
display block = 全部正文组成的一个 block
```

特别注意：

```text
slot capacity box 不等于 cue content block。
viewport 不等于 cue content block。

viewport 只提供排版容量。
slot capacity box 只提供一行/一列的排版容量。
content block 使用实际渲染内容的包围盒。
```

---

## 3. 前端字段总览

字幕设置面板按以下行展示。`subtitle_enabled` 是字幕总开关，不属于新增排版字段，但保留在配置模型中。

| 行号 | 字段英文名 | 中文名 | 控件 | 选项 / 值 | 默认值 |
|---:|---|---|---|---|---|
| 0 | `subtitle_enabled` | 启用字幕 | 开关 | `true` / `false` | `true` |
| 1 | `subtitle_font` | 字幕字体 | 下拉框 | 字体注册表动态返回的字体名 | 系统默认字体 |
| 2 | `subtitle_direction` | 文字方向 | 下拉框 | `direction_horizontal` / `direction_vertical_right_to_left` / `direction_vertical_left_to_right` | `direction_horizontal` |
| 3 | `subtitle_show_mode` | 显示模式 | 下拉框 | `show_punctuation` / `show_sentence` / `show_block` / `show_scroll` | `show_punctuation` |
| 4 | `subtitle_align_h` | 水平对齐 | 下拉框 | `left` / `center` / `right` | `center` |
| 5 | `subtitle_align_v` | 垂直对齐 | 下拉框 | `top` / `middle` / `bottom` | `bottom` |
| 6 | `subtitle_margin` | 字幕区域与视频外边距 | 单输入框 | `6%,6%,6%,6%`，顺序为上、右、下、左 | `6%,6%,6%,6%` |
| 7 | `subtitle_text_color` | 字幕颜色 | 颜色选择器 | `#RRGGBB` 或 `#RRGGBBAA` | `#FFFFFF` |
| 7 | `subtitle_font_size` | 字幕大小 | 数字输入 / 滑块 | 正整数，单位为目标视频像素 | `60` |
| 8 | `subtitle_stroke_color` | 描边颜色 | 颜色选择器 | `#RRGGBB` 或 `#RRGGBBAA` | `#000000` |
| 8 | `subtitle_stroke_width` | 描边粗细 | 数字输入 / 滑块 | `0.0` 到 `10.0`，`0` 表示无描边 | `1.5` |
| 9 | `subtitle_background_enabled` | 启用字幕背景 | 开关 | `true` / `false` | `false` |
| 9 | `subtitle_background_color` | 字幕背景颜色 | 颜色选择器 | `#RRGGBB` 或 `#RRGGBBAA` | `#000000` |
| 10 | `subtitle_background_style` | 字幕背景样式 | 下拉框 | `background_style_rectangle` / `background_style_rounded_translucent` | `background_style_rectangle` |

说明：

1. `subtitle_font` 的候选值来自字体注册表，不直接让用户输入路径。
2. `subtitle_font_size` 是目标视频坐标系下的像素值。预览界面应按预览尺寸等比缩放显示。
3. `subtitle_margin` 是 UI 输入形态；后端规范配置应拆成四个结构化 margin 字段。
4. `subtitle_background_style = "background_style_rounded_translucent"` 表示圆角半透明背景；该选项只有在 `subtitle_background_enabled = true` 时生效。
5. `subtitle_background_enabled = false` 时，背景颜色和样式仍可保存在 UI 配置里，但渲染时忽略。

---

## 4. 字段详细定义

## 4.1 `subtitle_enabled`

| 项目 | 值 |
|---|---|
| 中文名 | 启用字幕 |
| 类型 | boolean |
| 选项 | `true`, `false` |
| 默认值 | `true` |

当 `subtitle_enabled = false` 时，所有字幕字段都不生效，不渲染字幕层。

## 4.2 `subtitle_font`

| 项目 | 值 |
|---|---|
| 中文名 | 字幕字体 |
| 类型 | string |
| 取值 | 字体注册表返回的字体标识 |
| 默认值 | 系统默认字体 |

约束：

1. 不允许用户输入任意路径。
2. 候选字体由后端字体注册表提供。
3. 渲染前应检查字体是否支持当前文案中的字符。
4. 如果字体缺少字符，应提示用户；是否 fallback 到其他字体由实现阶段决定。

## 4.3 `subtitle_direction`

| 项目 | 值 |
|---|---|
| 中文名 | 文字方向 |
| 类型 | enum |
| 选项 | `direction_horizontal`, `direction_vertical_right_to_left`, `direction_vertical_left_to_right` |
| 默认值 | `direction_horizontal` |

| 值 | 中文名 | 排版语义 |
|---|---|---|
| `direction_horizontal` | 横排 | 文字从左到右，行从上到下堆叠 |
| `direction_vertical_right_to_left` | 竖排，从右到左 | 单列文字从上到下，列从右向左推进 |
| `direction_vertical_left_to_right` | 竖排，从左到右 | 单列文字从上到下，列从左向右推进 |

`subtitle_direction` 同时决定溢出方向锚点：

| 值 | 新内容进入边 | 旧内容退出 / 裁剪边 |
|---|---|---|
| `direction_horizontal` | 新行从下方进入 | 旧行向上滑动，顶部旧行被裁剪 |
| `direction_vertical_right_to_left` | 第一列贴 viewport 右侧，新列向左出现 | 旧列继续向左滑动，左侧旧列被裁剪 |
| `direction_vertical_left_to_right` | 第一列贴 viewport 左侧，新列向右出现 | 旧列继续向右滑动，右侧旧列被裁剪 |

## 4.4 `subtitle_show_mode`

| 项目 | 值 |
|---|---|
| 中文名 | 显示模式 |
| 类型 | enum |
| 选项 | `show_punctuation`, `show_sentence`, `show_block`, `show_scroll` |
| 默认值 | `show_punctuation` |

| 值 | 中文名 | 显示语义 |
|---|---|---|
| `show_punctuation` | 按标点显示 | 按标点切分 cue，逐条替换显示；标点保留在字幕中 |
| `show_sentence` | 按句子显示 | 按完整句结束符切分 cue，逐条替换显示；句内标点保留 |
| `show_block` | 整块显示 | 全部正文作为一个 cue 常驻显示；不自动拆分、不自动缩放 |
| `show_scroll` | 累积滚动 | 按物理换行切分 cue；已出现的 cue 累积保留，超出 viewport 后滑动裁剪 |

补充规则：

1. `show_punctuation` 和 `show_sentence` 是替换式显示。
2. `show_block` 是整块常驻显示。
3. `show_scroll` 是累积式显示，不是逐条替换。
4. `show_scroll` 时，没有换行符的长文本就是一个 cue；如果放不下，再拆成续行/续列。
5. 标点是否被 TTS 读出与字幕渲染无关；字幕按原文显示标点。

## 4.5 `subtitle_align_h`

| 项目 | 值 |
|---|---|
| 中文名 | 水平对齐 |
| 类型 | enum |
| 选项 | `left`, `center`, `right` |
| 默认值 | `center` |

用户语义：

```text
left   => 当前 display block 在 viewport 内靠左
center => 当前 display block 在 viewport 内水平居中
right  => 当前 display block 在 viewport 内靠右
```

它控制的是整块内容的位置，不是单独某一行的行槽位置。

## 4.6 `subtitle_align_v`

| 项目 | 值 |
|---|---|
| 中文名 | 垂直对齐 |
| 类型 | enum |
| 选项 | `top`, `middle`, `bottom` |
| 默认值 | `bottom` |

用户语义：

```text
top    => 当前 display block 在 viewport 内贴顶
middle => 当前 display block 在 viewport 内垂直居中
bottom => 当前 display block 在 viewport 内贴底
```

它控制的是整块内容的位置，不是单独一行/一列的槽内位置。

## 4.7 字幕 margin

UI 只显示一个输入框：

| 项目 | 值 |
|---|---|
| UI 字段名 | `subtitle_margin` |
| 中文名 | 字幕区域与视频外边距 |
| 示例 | `6%,6%,6%,6%` |
| 顺序 | 上、右、下、左 |

后端规范配置使用五个字段：

```text
subtitle_margin_top
subtitle_margin_right
subtitle_margin_bottom
subtitle_margin_left
subtitle_margin_unit
```

后端保存示例：

```json
{
  "subtitle_margin_top": 6,
  "subtitle_margin_right": 6,
  "subtitle_margin_bottom": 6,
  "subtitle_margin_left": 6,
  "subtitle_margin_unit": "percent"
}
```

计算方式：

```text
top    百分比基于视频高度
bottom 百分比基于视频高度
left   百分比基于视频宽度
right  百分比基于视频宽度
```

约束：

```text
0 <= subtitle_margin_top    <= 25
0 <= subtitle_margin_right  <= 25
0 <= subtitle_margin_bottom <= 25
0 <= subtitle_margin_left   <= 25
top + bottom < 100
left + right < 100
```

viewport 计算：

```text
viewport_x      = video_width  * subtitle_margin_left   / 100
viewport_y      = video_height * subtitle_margin_top    / 100
viewport_width  = video_width  * (100 - subtitle_margin_left - subtitle_margin_right) / 100
viewport_height = video_height * (100 - subtitle_margin_top - subtitle_margin_bottom) / 100
```

`margin` 是字幕区域相对视频画面的外边距，不是文字到背景框的内边距。

## 4.8 `subtitle_text_color`

| 项目 | 值 |
|---|---|
| 中文名 | 字幕颜色 |
| 类型 | string |
| 取值 | `#RRGGBB` 或 `#RRGGBBAA` |
| 默认值 | `#FFFFFF` |

## 4.9 `subtitle_font_size`

| 项目 | 值 |
|---|---|
| 中文名 | 字幕大小 |
| 类型 | integer |
| 取值 | `> 0` |
| 默认值 | `60` |
| 单位 | 目标视频像素 |

实现时可以另外限制上下限，但必须对所有 direction 和 show mode 一致。

## 4.10 `subtitle_stroke_color`

| 项目 | 值 |
|---|---|
| 中文名 | 描边颜色 |
| 类型 | string |
| 取值 | `#RRGGBB` 或 `#RRGGBBAA` |
| 默认值 | `#000000` |

## 4.11 `subtitle_stroke_width`

| 项目 | 值 |
|---|---|
| 中文名 | 描边粗细 |
| 类型 | number |
| 取值 | `0.0` 到 `10.0` |
| 默认值 | `1.5` |
| 单位 | 目标视频像素 |

`subtitle_stroke_width = 0` 表示不渲染描边。

## 4.12 `subtitle_background_enabled`

| 项目 | 值 |
|---|---|
| 中文名 | 启用字幕背景 |
| 类型 | boolean |
| 选项 | `true`, `false` |
| 默认值 | `false` |

`subtitle_background_enabled = false` 时，背景完全不渲染。

## 4.13 `subtitle_background_color`

| 项目 | 值 |
|---|---|
| 中文名 | 字幕背景颜色 |
| 类型 | string |
| 取值 | `#RRGGBB` 或 `#RRGGBBAA` |
| 默认值 | `#000000` |

## 4.14 `subtitle_background_style`

| 项目 | 值 |
|---|---|
| 中文名 | 字幕背景样式 |
| 类型 | enum |
| 选项 | `background_style_rectangle`, `background_style_rounded_translucent` |
| 默认值 | `background_style_rectangle` |

| 值 | 中文名 | 效果 |
|---|---|---|
| `background_style_rectangle` | 直角背景 | 使用背景颜色绘制直角背景 |
| `background_style_rounded_translucent` | 圆角半透明背景 | 使用背景颜色绘制圆角背景，并应用渲染器默认半透明度 |

第一阶段不新增透明度字段。如果后续用户需要自定义透明度，再增加：

```text
subtitle_background_opacity
```

## 5. 配置结构示例

```json
{
  "subtitle_enabled": true,
  "subtitle_font": "方正字迹-心海龙体.ttf",
  "subtitle_direction": "direction_vertical_right_to_left",
  "subtitle_show_mode": "show_scroll",
  "subtitle_align_h": "center",
  "subtitle_align_v": "middle",
  "subtitle_margin_top": 6,
  "subtitle_margin_right": 6,
  "subtitle_margin_bottom": 6,
  "subtitle_margin_left": 6,
  "subtitle_margin_unit": "percent",
  "subtitle_text_color": "#FFFFFF",
  "subtitle_font_size": 60,
  "subtitle_stroke_color": "#000000",
  "subtitle_stroke_width": 1.5,
  "subtitle_background_enabled": false,
  "subtitle_background_color": "#000000",
  "subtitle_background_style": "background_style_rectangle"
}
```

普通横排字幕示例：

```json
{
  "subtitle_enabled": true,
  "subtitle_font": "STHeitiMedium.ttc",
  "subtitle_direction": "direction_horizontal",
  "subtitle_show_mode": "show_sentence",
  "subtitle_align_h": "center",
  "subtitle_align_v": "bottom",
  "subtitle_margin_top": 6,
  "subtitle_margin_right": 6,
  "subtitle_margin_bottom": 6,
  "subtitle_margin_left": 6,
  "subtitle_margin_unit": "percent",
  "subtitle_text_color": "#FFFFFF",
  "subtitle_font_size": 60,
  "subtitle_stroke_color": "#000000",
  "subtitle_stroke_width": 1.5,
  "subtitle_background_enabled": true,
  "subtitle_background_color": "#000000",
  "subtitle_background_style": "background_style_rounded_translucent"
}
```

---

## 6. viewport、slot 和 content block

## 6.1 viewport

`viewport` 是字幕可用区域：

```text
viewport_width
viewport_height
viewport_x
viewport_y
```

它由视频尺寸和 margin 计算，不等于内容块尺寸。

## 6.2 slot capacity box

`slot capacity box` 是一个槽能使用的最大排版空间。

它的作用是判断：

```text
一行横排文字什么时候放不下，需要拆续行。
一列竖排文字什么时候放不下，需要拆续列。
```

| direction | slot capacity box |
|---|---|
| `direction_horizontal` | 行槽容量宽度 = viewport 宽度 |
| `direction_vertical_right_to_left` | 列槽容量高度 = viewport 高度 |
| `direction_vertical_left_to_right` | 列槽容量高度 = viewport 高度 |

注意：

```text
横排行槽的容量宽度是 viewport 宽度，但实际行宽通常小于 viewport 宽度。
竖排列槽的容量高度是 viewport 高度，但实际列高通常小于 viewport 高度。
```

## 6.3 slot visual box

`slot visual box` 是一个槽里实际渲染内容占用的包围盒。

它由渲染器测量，通常包括：

```text
文字包围盒
描边外扩
背景框，如果启用背景
背景内边距，如果后续启用
```

横排行槽：

```text
slot visual height = 字体行高 / 渲染行高
slot visual width  = 这一行文字实际测量宽度
```

竖排列槽：

```text
slot visual width  = 列宽
slot visual height = 这一列文字实际测量高度
```

同一配置下：

```text
横排每行高度通常相同，但每行宽度可以不同。
竖排每列宽度通常相同，但每列高度可以不同。
```

## 6.4 cue content block

一个 cue 的一个或多个 slot visual box 组成 `cue content block`。

横排多行：

```text
cue_content_block_width  = max(所有行的 visual width)
cue_content_block_height = 所有行的 visual height + 行间距
```

竖排多列：

```text
cue_content_block_width  = 所有列的 visual width + 列间距
cue_content_block_height = max(所有列的 visual height)
```

如果只有一个行槽或一个列槽：

```text
cue content block size = 这个槽的 visual box size
```

## 6.5 display block

`display block` 是实际参与 viewport 定位的内容块。

| subtitle_show_mode | display block |
|---|---|
| `show_punctuation` | 当前 cue content block |
| `show_sentence` | 当前 cue content block |
| `show_block` | 全部正文组成的一个 content block |
| `show_scroll` | 已经出现的累积内容块 |

所以，滚动模式下的定位对象不是“当前 cue”，而是“累积显示内容块”。

例如竖排滚动：

```text
display_block_width  = 已出现列的 visual width + 列间距
display_block_height = 已出现列中最高的 visual height
```

横排滚动：

```text
display_block_width  = 已出现行中最宽的 visual width
display_block_height = 已出现行的 visual height + 行间距
```

---

## 7. slot 尺寸计算

## 7.1 横排行槽

横排时，每个显示行有一个行槽。

```text
行槽容量宽度 = viewport_width
```

这个值只用于判断一行最多能容纳多少文字。

行槽实际尺寸：

```text
row_layout_height = font_size * line_height_ratio
row_visual_width  = 当前一行文字测量宽度 + 描边 / 背景外扩
```

其中：

1. `line_height_ratio` 可以来自字体 metrics，也可以作为渲染器默认值。
2. `row_visual_width` 必须实际测量，不能假设等于 viewport 宽度。

例如：

```text
viewport_width = 300
font_size = 60
line_height_ratio = 1.2
一行文字实际宽度 = 120

行槽容量宽 = 300
行槽 layout 高 = 72
行槽 visual 宽 = 120
```

## 7.2 竖排列槽

竖排时，每个显示列有一个列槽。

```text
列槽容量高度 = viewport_height
```

这个值只用于判断一列最多能容纳多少文字。

列槽实际尺寸：

```text
column_layout_width = font_size * column_width_ratio
column_visual_height = 当前一列文字测量高度 + 描边 / 背景外扩
```

其中：

1. `column_width_ratio` 可以来自字体 metrics，也可以作为渲染器默认值。
2. `column_visual_height` 必须实际测量，不能假设等于 viewport 高度。

例如：

```text
viewport_height = 400
font_size = 60
column_width_ratio = 1.2
一列文字实际高度 = 240

列槽容量高 = 400
列槽 layout 宽 = 72
列槽 visual 高 = 240
```

## 7.3 slot 数量

槽的数量按实际排版结果决定。

粗略公式：

```text
横排行槽数量 = ceil(当前 cue 总宽度 / viewport_width)
竖排列槽数量 = ceil(当前 cue 总高度 / viewport_height)
```

但真实实现不能只按字符数除，必须按字体度量、标点规则和断行规则测量。

例如：

```text
内容总宽度是 viewport 宽度的 1.2 倍
=> 2 个行槽

内容总宽度是 viewport 宽度的 2.4 倍
=> 3 个行槽
```

---

## 8. 对齐语义

## 8.1 用户对齐与槽内对齐是两层

用户配置：

```text
subtitle_align_h / subtitle_align_v
```

控制当前 display block 在 viewport 内的位置。

内部推导：

```text
slot_align_h / slot_align_v
```

控制每个行槽/列槽里的文字在自己槽内的位置。

两者不是同一个概念。

## 8.2 slot align 推导规则

| direction | slot_align_h | slot_align_v |
|---|---|---|
| `direction_horizontal` | 等于 `subtitle_align_h` | 固定 `middle` |
| `direction_vertical_right_to_left` | 固定 `center` | 等于 `subtitle_align_v` |
| `direction_vertical_left_to_right` | 固定 `center` | 等于 `subtitle_align_v` |

说明：

1. 横排时，`subtitle_align_h` 同时影响：
   - 当前 display block 在 viewport 内的水平位置；
   - 多行内容在内容块内部的水平对齐方式。
2. 横排时，`subtitle_align_v` 只影响 display block 在 viewport 内的垂直位置；行槽内垂直对齐固定为 `middle`。
3. 竖排时，`subtitle_align_v` 同时影响：
   - 当前 display block 在 viewport 内的垂直位置；
   - 多列内容在内容块内部的垂直对齐方式。
4. 竖排时，`subtitle_align_h` 只影响 display block 在 viewport 内的水平位置；列槽内水平对齐固定为 `center`。

示例：

```text
subtitle_direction = "direction_horizontal"
subtitle_align_h        = "center"
subtitle_align_v        = "bottom"

推导：
slot_align_h = center
slot_align_v = middle
```

```text
subtitle_direction = "direction_vertical_right_to_left"
subtitle_align_h        = "center"
subtitle_align_v        = "middle"

推导：
slot_align_h = center
slot_align_v = middle
```

## 8.3 横排对齐效果

假设当前 cue 拆成两行：

```text
君不见，黄河之水天上来，
奔流到海不复回。
```

如果：

```text
subtitle_align_h = "center"
subtitle_align_v = "bottom"
slot_align_h = "center"
```

效果：

```text
┌ viewport ─────────────────────┐
│                               │
│                               │
│                               │
│   君不见，黄河之水天上来，        │
│       奔流到海不复回。           │
└────────────────────────────────┘
```

如果：

```text
subtitle_align_h = "center"
subtitle_align_v = "bottom"
slot_align_h = "left"
```

效果：

```text
┌ viewport ─────────────────────┐
│                               │
│                               │
│                               │
│ 君不见，黄河之水天上来，           │
│ 奔流到海不复回。                  │
└────────────────────────────────┘
```

第一阶段不暴露 `slot_align_h`，因此实际显示由推导规则决定。

## 8.4 竖排对齐效果

假设当前 cue 拆成两列：

```text
列1：黄河之水天上来
列2：奔流到海
```

`subtitle_direction = "direction_vertical_right_to_left"` 时，列 1 在右，列 2 在左。

如果：

```text
subtitle_align_h = "center"
subtitle_align_v = "middle"
```

则列组水平居中，列内部垂直居中：

```text
┌ viewport ─────────────────────┐
│                               │
│       奔      黄              │
│       流      河              │
│       到      之              │
│       海      水              │
│               天              │
│               上              │
│               来              │
│                               │
└────────────────────────────────┘
```

如果：

```text
subtitle_align_h = "center"
subtitle_align_v = "top"
```

则列组在 viewport 内贴顶，列内容也贴顶：

```text
┌ viewport ─────────────────────┐
│       奔      黄              │
│       流      河              │
│       到      之              │
│       海      水              │
│               天              │
│               上              │
│               来              │
│                               │
│                               │
└────────────────────────────────┘
```

如果：

```text
subtitle_align_h = "center"
subtitle_align_v = "bottom"
```

则列组贴底，列内容也贴底：

```text
┌ viewport ─────────────────────┐
│                               │
│                               │
│               黄              │
│               河              │
│               之              │
│               水              │
│               天              │
│               上              │
│               来              │
│       奔      流              │
│       到      到              │
│       海      海              │
└────────────────────────────────┘
```

---

## 9. 放得下与溢出的处理

## 9.1 内容放得下

当当前 display block 能放进 viewport 时：

```text
subtitle_align_h / subtitle_align_v 生效
```

放置公式：

```text
subtitle_align_h = "left"
=> content_x = viewport_x

subtitle_align_h = "center"
=> content_x = viewport_x + (viewport_width - display_block_width) / 2

subtitle_align_h = "right"
=> content_x = viewport_x + viewport_width - display_block_width

subtitle_align_v = "top"
=> content_y = viewport_y

subtitle_align_v = "middle"
=> content_y = viewport_y + (viewport_height - display_block_height) / 2

subtitle_align_v = "bottom"
=> content_y = viewport_y + viewport_height - display_block_height
```

这里的 `display_block_width / display_block_height` 是当前显示内容块的实际尺寸，不是 viewport 尺寸。

## 9.2 内容溢出

当当前 display block 超过 viewport 时：

```text
subtitle_align_h / subtitle_align_v 不再决定溢出方向
subtitle_direction 方向锚点接管
viewport 负责裁剪
```

规则：

| direction | 溢出行为 |
|---|---|
| `direction_horizontal` | 新行从下方进入，旧内容整体向上滑动，顶部旧行被裁剪 |
| `direction_vertical_right_to_left` | 新列向左出现，旧内容向左滑动，左侧旧列被裁剪 |
| `direction_vertical_left_to_right` | 新列向右出现，旧内容向右滑动，右侧旧列被裁剪 |

溢出时不自动缩小字体、不自动隐藏后续内容、不自动改换显示模式。

## 9.3 `show_block` 的溢出

`show_block` 不自动拆分、不自动缩放。

如果用户选择整块显示但内容放不下，属于用户选择结果，渲染器只按 viewport 裁剪。

这一点需要在前端帮助文案中说明：

```text
整块显示模式不会自动缩小文字或拆分内容；如果内容超出字幕区域，将被裁剪。
```

---

## 10. 渲染流程

目标渲染流程：

```text
字幕配置
↓
配置校验
↓
CueBuilder
根据 subtitle_show_mode 切分 cue
↓
LayoutStrategy
根据 subtitle_direction 选择横排 / 竖排布局
↓
SlotBuilder
把每个 cue 拆成一行或多行、一列或多列
↓
SlotMeasurer
计算 slot capacity box 和 slot visual box
↓
SlotAligner
按内部 slot_align_h / slot_align_v 排列行槽 / 列槽
↓
ContentBlockBuilder
把一个或多个 slot 组成 cue content block
↓
DisplayBlockBuilder
根据 show mode 得到 display block
替换式：当前 cue block
滚动式：累积 block
↓
PlacementStrategy
放得下：按 subtitle_align_h / subtitle_align_v 放置
溢出：按 direction 锚点和滚动偏移处理
↓
ViewportRenderer
裁剪 viewport 外内容，处理替换式 / 累积式 / 整块式生命周期
↓
StyleRenderer
渲染字体、颜色、描边、背景、圆角
↓
视频合成
```

对应策略：

| 变化点 | 策略 |
|---|---|
| cue 切分 | `PunctuationCueBuilder`, `SentenceCueBuilder`, `BlockCueBuilder`, `ScrollCueBuilder` |
| 布局方向 | `HorizontalLayoutStrategy`, `VerticalRightToLeftLayoutStrategy`, `VerticalLeftToRightLayoutStrategy` |
| 显示生命周期 | `ReplaceRenderer`, `BlockRenderer`, `ScrollRenderer` |
| 溢出策略 | `ClipOverflowPolicy`，后续可扩展 |

---

## 11. 使用示例

## 11.1 普通横排字幕

配置：

```text
subtitle_direction = direction_horizontal
subtitle_show_mode      = show_sentence
subtitle_align_h        = center
subtitle_align_v        = bottom
margin                  = 6%,6%,6%,6%
```

效果：

1. 文案按完整句切分。
2. 每次只显示一句。
3. 一句能放下时，水平居中、贴字幕区域底部。
4. 一句太长时，拆成多个行槽，但这些行槽仍属于同一句。
5. 下一句出现时，上一句整组替换。

## 11.2 竖排唐诗

配置：

```text
subtitle_direction = direction_vertical_right_to_left
subtitle_show_mode      = show_scroll
subtitle_align_h        = center
subtitle_align_v        = middle
margin                  = 6%,6%,6%,6%
```

效果：

1. 按物理换行切分 cue。
2. 每读一句，出现一列。
3. 已出现的列累积保留。
4. 列数超出 viewport 时，内容按 direction 滑动，旧列被裁剪。
5. 列组在 viewport 内水平居中，列内容垂直居中。

## 11.3 横排现代诗

配置：

```text
subtitle_direction = direction_horizontal
subtitle_show_mode      = show_scroll
subtitle_align_h        = center
subtitle_align_v        = middle
margin                  = 6%,6%,6%,6%
```

效果：

1. 按物理换行切分 cue。
2. 每读一行，出现一行。
3. 已出现的行累积保留。
4. 行数超出 viewport 时，新行从下方进入，旧内容整体向上滑动。
5. 最上方旧行被 viewport 上边缘裁剪。

## 11.4 整块显示

配置：

```text
subtitle_direction = direction_horizontal
subtitle_show_mode      = show_block
subtitle_align_h        = center
subtitle_align_v        = middle
```

效果：

1. 全部正文作为一个整块常驻显示。
2. 不按标点、句子或换行拆 cue。
3. 内容放不下时不自动缩放、不自动拆分。
4. 超出 viewport 的部分被裁剪。

---

## 12. 校验规则

必须校验：

| 字段 | 规则 |
|---|---|
| `subtitle_enabled` | 必须是 boolean |
| `subtitle_font` | 必须存在于字体注册表 |
| `subtitle_direction` | 必须是三个 `direction_` 枚举值之一 |
| `subtitle_show_mode` | 必须是四个 `show_` 枚举值之一 |
| `subtitle_align_h` | 必须是 `left` / `center` / `right` |
| `subtitle_align_v` | 必须是 `top` / `middle` / `bottom` |
| `subtitle_margin_*` | 四个数字必须是百分比数字，范围 `0-25`，且相对边之和小于 `100` |
| `subtitle_margin_unit` | 第一阶段固定为 `percent` |
| `subtitle_font_size` | 必须大于 `0` |
| `subtitle_text_color` | 必须是合法颜色值 |
| `subtitle_stroke_color` | 必须是合法颜色值 |
| `subtitle_stroke_width` | 必须在 `0.0-10.0` |
| `subtitle_background_enabled` | 必须是 boolean |
| `subtitle_background_color` | 必须是合法颜色值 |
| `subtitle_background_style` | 必须是 `background_style_rectangle` / `background_style_rounded_translucent` |

建议提示但不阻断：

1. 字体缺少当前文案所需字符。
2. `show_block` 且内容可能超出 viewport。
3. 字幕颜色和描边颜色过于接近。
4. 字幕颜色和背景颜色过于接近。

---

## 13. UI 分组建议

字幕设置面板可以分成三组。

## 13.1 排版

```text
文字方向
显示模式
水平对齐
垂直对齐
字幕区域与视频外边距
```

## 13.2 字体样式

```text
字幕字体
字幕大小
字幕颜色
描边颜色
描边粗细
```

## 13.3 背景

```text
启用字幕背景
字幕背景样式
字幕背景颜色
```

这样用户理解成本最低，后续也方便扩展。

---

## 14. 后续可扩展字段

以下字段不在第一阶段，但配置结构应预留扩展空间。

| 英文字段 | 中文名 | 说明 |
|---|---|---|
| `subtitle_line_gap` | 行间距 | 横排行槽之间的额外间距 |
| `subtitle_column_gap` | 列间距 | 竖排列槽之间的额外间距 |
| `subtitle_char_gap` | 字符间距 | 文字之间的额外间距 |
| `subtitle_background_padding` | 背景内边距 | 文字到背景框的距离 |
| `subtitle_background_opacity` | 背景透明度 | 自定义背景透明度 |
| `subtitle_background_corner_radius` | 背景圆角半径 | 自定义圆角大小 |
| `subtitle_overflow_policy` | 溢出策略 | `overflow_policy_clip` / `overflow_policy_shrink` / `overflow_policy_paginate` / `overflow_policy_scroll` |
| `subtitle_reading_highlight` | 朗读高亮 | 是否启用逐字或逐词高亮 |

---

## 15. 历史字段迁移

本文定义的是目标命名和目标语义。

历史字段命名与本文可能不一致，例如现有工程中可能存在旧的字体字段、旧的位置字段、旧的诗歌方向字段等。

这些问题不在本文解决。

进入实施阶段前，需要另建迁移设计，明确：

1. 旧字段如何映射到新字段。
2. 旧任务记录如何兼容读取。
3. API 是否保留旧字段别名。
4. WebUI 是否需要灰度切换。
5. 默认值是否需要按旧任务类型区分。
6. 是否需要一次性迁移或双写过渡。

---

## 16. 第一阶段验收标准

第一阶段完成后，应能通过配置完成以下场景：

1. 横排 + `show_punctuation` 替换显示。
2. 横排 + `show_sentence` 替换显示。
3. 横排 + `show_scroll` 累积滚动。
4. 横排 + `show_block` 整块显示。
5. 竖排从右到左 + `show_scroll` 累积滚动。
6. 竖排从左到右 + `show_scroll` 累积滚动。
7. 自定义字幕字体、字号、颜色、描边。
8. 自定义字幕背景开关、颜色、样式。
9. 自定义四边 margin，并正确得到 viewport。
10. 内容放得下时，`subtitle_align_h / subtitle_align_v` 表现正确。
11. 内容溢出时，direction 锚点和 viewport 裁剪表现正确。
12. 一条 cue 拆成多个 slot 后，仍能作为同一组内容替换或滚动。
13. 横排行槽的容量宽度和可视宽度能正确区分。
14. 竖排列槽的容量高度和可视高度能正确区分。
15. 滚动模式使用累积 display block 定位，而不是只定位当前 cue。
