import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from app.services import subtitle
from app.services import voice


def make_cue(start: float, end: float, content: str):
    return SimpleNamespace(
        start=timedelta(seconds=start),
        end=timedelta(seconds=end),
        content=content,
    )


class TestPoetrySrt(unittest.TestCase):
    def test_create_subtitle_groups_edge_cues_by_physical_line(self):
        script = (
            "【塞下曲】\n唐 · 卢纶\n林暗草惊风\n平明寻白羽\n没在石棱中"
        )
        sub_maker = SimpleNamespace(
            cues=[
                make_cue(0.0, 0.8, "【塞下曲】"),
                make_cue(0.8, 1.2, "唐卢纶"),
                make_cue(1.2, 1.8, "林暗草惊风"),
                make_cue(1.8, 2.2, "平明寻白羽"),
                make_cue(2.2, 2.6, "没在石棱中"),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            subtitle_file = Path(tmp_dir) / "subtitle.srt"
            voice.create_subtitle(
                sub_maker=sub_maker,
                text=script,
                subtitle_file=str(subtitle_file),
                segmentation="line",
            )

            items = subtitle.file_to_subtitles(str(subtitle_file))

        self.assertEqual([item[2] for item in items], script.splitlines())
        self.assertEqual(items[0][1], "00:00:00,000 --> 00:00:00,800")
        self.assertEqual(items[-1][1], "00:00:02,200 --> 00:00:02,600")


if __name__ == "__main__":
    unittest.main()
