import unittest

from app.services import poetry


class TestPoetryScript(unittest.TestCase):
    def test_parses_title_author_and_physical_lines(self):
        script = poetry.parse_poetry_script(
            "\n【塞下曲】\n唐 · 卢纶\n林暗草惊风，将军夜引弓。\n平明寻白羽，没在石棱中。\n"
        )

        self.assertEqual(script.title, "【塞下曲】")
        self.assertEqual(script.author, "唐 · 卢纶")
        self.assertEqual(
            script.poem_lines,
            ("林暗草惊风，将军夜引弓。", "平明寻白羽，没在石棱中。"),
        )
        self.assertEqual(script.metadata_line_count, 2)

    def test_removes_markdown_separators_before_parsing(self):
        script = poetry.parse_poetry_script(
            "【塞下曲】\n---\n唐 · 卢纶\n林暗草惊风\n平明寻白羽"
        )

        self.assertEqual(script.title, "【塞下曲】")
        self.assertEqual(script.author, "唐 · 卢纶")
        self.assertEqual(script.poem_lines, ("林暗草惊风", "平明寻白羽"))

    def test_rejects_scripts_without_three_lines(self):
        with self.assertRaises(poetry.PoetryScriptError):
            poetry.parse_poetry_script("【塞下曲】\n唐 · 卢纶")


if __name__ == "__main__":
    unittest.main()
