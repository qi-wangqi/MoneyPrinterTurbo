"""Parse poetry scripts for the dedicated subtitle renderer."""

from dataclasses import dataclass

from app.utils import utils


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
    """
    Parse the first two non-empty lines as metadata and the rest as poem lines.

    Markdown separator lines are removed by the subtitle normalizer because
    TTS does not speak them; keeping them here would desynchronize cues.
    """
    normalized_text = utils.normalize_script_for_subtitle_matching(text or "")
    lines = utils.split_string_by_lines(normalized_text)

    if len(lines) < 3:
        raise PoetryScriptError(
            "poetry mode requires title, author and at least one poem line"
        )

    return PoetryScript(
        title=lines[0],
        author=lines[1],
        poem_lines=tuple(lines[2:]),
    )
