"""Regression tests for user-facing project documentation."""

from pathlib import Path


CLAUDE_MD = Path(__file__).resolve().parents[1] / "CLAUDE.md"
JOB_ROOM_AUTOLINK = "<https://www.job-room.ch>"


def _what_this_is_section() -> str:
    """Return the introductory project-description section from CLAUDE.md."""
    document = CLAUDE_MD.read_text(encoding="utf-8")
    heading = "## What this is\n"
    assert heading in document, "CLAUDE.md must retain its project-description section"
    return document.split(heading, maxsplit=1)[1].split("\n## ", maxsplit=1)[0]


def test_job_room_url_is_a_markdown_autolink():
    """The project URL renders as a clickable Markdown autolink."""
    section = _what_this_is_section()

    assert section.count(JOB_ROOM_AUTOLINK) == 1


def test_job_room_url_is_not_duplicated_as_bare_text():
    """Guard against reintroducing the unformatted URL in the same section."""
    section_without_autolink = _what_this_is_section().replace(JOB_ROOM_AUTOLINK, "")

    assert "https://www.job-room.ch" not in section_without_autolink
