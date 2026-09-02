import math
import os
import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image

from app.models.schema import VideoParams
from app.services import poetry
from app.services import poetry_renderer
from app.services.poetry_renderer import OffsetState
from app.utils import utils


def write_srt(text: str, timings):
    blocks = []
    for index, ((start, end), line) in enumerate(zip(timings, text.splitlines()), 1):
        blocks.append(f"{index}\n{start} --> {end}\n{line}")
    return "\n\n".join(blocks) + "\n\n"


class TestPoetryRenderer(unittest.TestCase):
    def setUp(self):
        self.font_path = os.path.join(utils.font_dir(), "STHeitiMedium.ttc")
        self.script = poetry.parse_poetry_script(
            "【塞下曲】\n唐 · 卢纶\n林暗草惊风\n平明寻白羽"
        )
        self.params = VideoParams(
            video_subject="poetry",
            font_size=24,
            stroke_width=0,
            subtitle_style="poetry",
        )

    def test_rejects_subtitle_count_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_path = Path(tmp_dir) / "subtitle.srt"
            subtitle_path.write_text(
                write_srt(
                    "【塞下曲】\n唐 · 卢纶\n林暗草惊风",
                    [
                        ("00:00:00,000", "00:00:01,000"),
                        ("00:00:01,000", "00:00:02,000"),
                    ],
                ),
                encoding="utf-8",
            )

            with self.assertRaises(poetry_renderer.PoetryLayoutError):
                poetry_renderer.build_poetry_overlays(
                    str(subtitle_path),
                    self.script,
                    self.params,
                    720,
                    1280,
                    4.0,
                    self.font_path,
                )

    def test_builds_overlays_for_all_directions(self):
        srt_text = write_srt(
            "【塞下曲】\n唐 · 卢纶\n林暗草惊风\n平明寻白羽",
            [
                ("00:00:00,000", "00:00:01,000"),
                ("00:00:01,000", "00:00:02,000"),
                ("00:00:02,000", "00:00:03,000"),
                ("00:00:03,000", "00:00:04,000"),
            ],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_path = Path(tmp_dir) / "subtitle.srt"
            subtitle_path.write_text(srt_text, encoding="utf-8")

            for direction in (
                "right_to_left",
                "left_to_right",
                "top_to_bottom",
            ):
                self.params.poetry_direction = direction
                clips = poetry_renderer.build_poetry_overlays(
                    str(subtitle_path),
                    self.script,
                    self.params,
                    720,
                    1280,
                    4.0,
                    self.font_path,
                )

                self.assertEqual(len(clips), 3)
                self.assertEqual(clips[0].start, 0)
                self.assertEqual(clips[1].start, 0)
                self.assertTrue(math.isclose(clips[0].end, 4.0))
                self.assertTrue(math.isclose(clips[1].end, 4.0))
                self.assertTrue(
                    all(clip.start < clip.end for clip in clips)
                )

    def test_slides_early_lines_out_when_body_is_full(self):
        lines = ["塞下秋来风景异", "衡阳雁去无留意", "四面边声连角起", "千嶂里", "长烟落日孤城闭"]
        script = poetry.parse_poetry_script("【渔家傲】\n宋 · 范仲淹\n" + "\n".join(lines))
        timings = []
        cue_start = 0.0
        for line in script.all_lines:
            timings.append((f"00:00:{int(cue_start):02d},000", f"00:00:{int(cue_start + 0.5):02d},000"))
            cue_start += 0.5
        srt_text = write_srt("\n".join(script.all_lines), timings)

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_path = Path(tmp_dir) / "subtitle.srt"
            subtitle_path.write_text(srt_text, encoding="utf-8")
            clips = poetry_renderer.build_poetry_overlays(
                str(subtitle_path),
                script,
                self.params,
                240,
                360,
                4.0,
                self.font_path,
            )

        body_clip = clips[2]
        early_alpha = body_clip.mask.get_frame(1.5)
        later_alpha = body_clip.mask.get_frame(3.5)
        self.assertGreater(float(early_alpha.max()), 0.0)
        self.assertGreater(float(later_alpha.max()), 0.0)

    def test_sliding_position_uses_absolute_timeline(self):
        # The body viewport is a full-timeline layer, so offset states use
        # absolute subtitle time directly.
        offset = poetry_renderer._sliding_position(
            states=[
                OffsetState(start=0.0, offset=0.0),
                OffsetState(start=2.0, offset=40.0),
            ],
            time=2.2,
        )

        self.assertTrue(math.isclose(offset, 20.0))

    def test_right_to_left_piece_exits_at_its_right_edge(self):
        timings = poetry_renderer._reading_timings(
            "君不见，",
            poetry_renderer.SubtitleCue(start=2.0, end=4.0, text="君不见，"),
        )

        self.assertEqual(len(timings), 4)
        self.assertEqual(timings[0][0], 2.0)
        self.assertTrue(math.isclose(timings[-1][1], 4.0))
        self.assertTrue(
            all(
                timings[index][1] <= timings[index + 1][0] + 1e-9
                for index in range(len(timings) - 1)
            )
        )

    def test_highlight_alpha_softens_entry_and_exit(self):
        self.assertEqual(poetry_renderer._highlight_alpha(1.0, 1.0, 2.0), 0.0)
        self.assertLess(poetry_renderer._highlight_alpha(1.02, 1.0, 2.0), 1.0)
        self.assertEqual(poetry_renderer._highlight_alpha(1.5, 1.0, 2.0), 1.0)
        self.assertLess(poetry_renderer._highlight_alpha(2.05, 1.0, 2.0), 1.0)
        self.assertEqual(poetry_renderer._highlight_alpha(2.2, 1.0, 2.0), 0.0)

    def test_highlight_variant_keeps_layout_and_changes_pixels(self):
        font = poetry_renderer._load_font(self.font_path, 24)
        normal = poetry_renderer._render_vertical_text("君不见", font, 24, "#FFFFFF", "#000000", 1)
        highlighted = poetry_renderer._render_vertical_text(
            "君不见", font, 24, "#FFFFFF", "#000000", 1,
            highlight_visible_index=1,
            highlight_stroke_color="#F5C451",
        )

        self.assertEqual(normal.size, highlighted.size)
        self.assertNotEqual(
            normal.tobytes(),
            highlighted.tobytes(),
        )

    def test_horizontal_highlight_does_not_relayout_text(self):
        text = "与君歌一曲，请君为我倾耳听。"
        font = poetry_renderer._load_font(self.font_path, 24)
        normal = poetry_renderer._render_horizontal_text(
            text, font, 24, "#FFFFFF", "#000000", 1
        )
        highlighted = poetry_renderer._render_horizontal_text(
            text,
            font,
            24,
            "#FFFFFF",
            "#000000",
            1,
            highlight_visible_index=1,
            highlight_stroke_color="#F5C451",
        )

        self.assertEqual(normal.size, highlighted.size)
        normal_rgb = np.asarray(normal)[:, :, :3].astype(int)
        highlighted_rgb = np.asarray(highlighted)[:, :, :3].astype(int)
        # 金色描边只叠加在原本黑色描边上；整串字形坐标不变时，RGB 不应变暗。
        self.assertGreaterEqual(int((highlighted_rgb - normal_rgb).min()), 0)
        self.assertFalse(np.array_equal(normal_rgb, highlighted_rgb))


if __name__ == "__main__":
    unittest.main()
