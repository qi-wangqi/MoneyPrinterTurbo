import sys
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.models.schema import VideoAspect, VideoFitMode, VideoParams


class TestVideoAspect(unittest.TestCase):
    def test_to_resolution_known_aspects(self):
        self.assertEqual(VideoAspect.landscape.to_resolution(), (1920, 1080))
        self.assertEqual(VideoAspect.portrait.to_resolution(), (1080, 1920))
        self.assertEqual(VideoAspect.square.to_resolution(), (1080, 1080))

    def test_to_resolution_rejects_unsupported_value(self):
        with self.assertRaises(ValueError):
            VideoAspect.to_resolution("4:5")


class TestVideoParams(unittest.TestCase):
    def test_video_fit_mode_defaults_to_cover_and_validates_values(self):
        self.assertEqual(
            VideoParams(video_subject="Coffee").video_fit_mode,
            VideoFitMode.cover,
        )
        self.assertEqual(
            VideoParams(
                video_subject="Coffee", video_fit_mode="contain"
            ).video_fit_mode,
            VideoFitMode.contain,
        )
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Coffee", video_fit_mode="stretch")

    def test_rejects_non_positive_generation_counts(self):
        for field_name in ("video_clip_duration", "video_count"):
            for value in (0, -1, None):
                with self.subTest(field_name=field_name, value=value):
                    with self.assertRaises(ValidationError):
                        VideoParams(video_subject="Coffee", **{field_name: value})

    def test_accepts_positive_generation_counts(self):
        params = VideoParams(
            video_subject="Coffee", video_clip_duration=1, video_count=1
        )

        self.assertEqual(params.video_clip_duration, 1)
        self.assertEqual(params.video_count, 1)

    def test_subtitle_fields_have_safe_defaults_and_limits(self):
        params = VideoParams(video_subject="Subtitles")

        self.assertEqual(params.subtitle_direction, "horizontal")
        self.assertEqual(params.subtitle_show_mode, "punctuation")
        self.assertEqual(params.subtitle_align_h, "center")
        self.assertEqual(params.subtitle_align_v, "bottom")
        for margin_name in (
            "subtitle_margin_top",
            "subtitle_margin_right",
            "subtitle_margin_bottom",
            "subtitle_margin_left",
        ):
            self.assertEqual(getattr(params, margin_name), 6.0)

        params = VideoParams(
            video_subject="Subtitles",
            subtitle_direction="vertical_rtl",
            subtitle_show_mode="scroll",
            subtitle_align_h="right",
            subtitle_align_v="top",
            subtitle_margin_top=0,
            subtitle_margin_right=25,
            subtitle_margin_bottom=12.5,
            subtitle_margin_left=8,
        )
        self.assertEqual(params.subtitle_margin_top, 0.0)
        self.assertEqual(params.subtitle_margin_right, 25.0)

        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Subtitles", subtitle_direction="diagonal")
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Subtitles", subtitle_show_mode="line")
        with self.assertRaises(ValidationError):
            VideoParams(video_subject="Subtitles", subtitle_margin_top=30)


if __name__ == "__main__":
    unittest.main()
