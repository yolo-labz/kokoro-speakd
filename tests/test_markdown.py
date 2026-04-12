"""Smoke tests for the markdown → speech-friendly plaintext converter."""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure repo root is importable (no package install needed for tests)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from markdown import extract_summary, strip_markdown


class TestExtractSummary:
    def test_extracts_summary_block(self) -> None:
        text = "Some text <!-- TTS_SUMMARY Hello world TTS_SUMMARY --> more text"
        assert extract_summary(text) == "Hello world"

    def test_returns_none_when_no_summary(self) -> None:
        assert extract_summary("Just plain text") is None

    def test_multiline_summary(self) -> None:
        text = "<!-- TTS_SUMMARY\nLine one\nLine two\nTTS_SUMMARY -->"
        result = extract_summary(text)
        assert result is not None
        assert "Line one" in result
        assert "Line two" in result


class TestStripMarkdown:
    def test_strips_bold(self) -> None:
        assert "hello" in strip_markdown("**hello**")

    def test_strips_italic(self) -> None:
        assert "world" in strip_markdown("*world*")

    def test_strips_headings(self) -> None:
        result = strip_markdown("## My Heading")
        assert "My Heading" in result
        assert "#" not in result

    def test_strips_links_keeps_text(self) -> None:
        result = strip_markdown("[click here](https://example.com)")
        assert "click here" in result
        assert "https" not in result

    def test_strips_code_blocks(self) -> None:
        text = "before ```python\nprint('hi')\n``` after"
        result = strip_markdown(text)
        assert "print" not in result
        assert "before" in result
        assert "after" in result

    def test_strips_inline_code(self) -> None:
        result = strip_markdown("use `foo` here")
        assert "foo" not in result
        assert "use" in result

    def test_strips_images(self) -> None:
        result = strip_markdown("![alt text](image.png)")
        assert "alt text" not in result
        assert "image.png" not in result

    def test_bare_urls_become_a_link(self) -> None:
        result = strip_markdown("visit https://example.com today")
        assert "a link" in result
        assert "https" not in result

    def test_collapses_whitespace(self) -> None:
        result = strip_markdown("hello    world")
        assert result == "hello world"

    def test_empty_string(self) -> None:
        assert strip_markdown("") == ""

    def test_plain_text_unchanged(self) -> None:
        assert strip_markdown("Hello world") == "Hello world"
