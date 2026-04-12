"""Markdown → speech-friendly plaintext conversion shared by client hooks.

The daemon itself stays text-agnostic; clients strip markdown before sending
so multiple frontends (Claude Code, aider, shell scripts) can agree on what
"readable" means without the daemon importing a markdown library.
"""

from __future__ import annotations

import re


def extract_summary(text: str) -> str | None:
    """Return the inner text of the first ``<!-- TTS_SUMMARY ... TTS_SUMMARY -->``
    block if present, otherwise ``None``. Used by Claude Code Stop hooks so the
    assistant can opt into a concise spoken summary separate from the visible
    reply."""
    m = re.search(
        r"<!--\s*TTS_SUMMARY\s*(.*?)\s*TTS_SUMMARY\s*-->",
        text,
        re.DOTALL,
    )
    return m.group(1).strip() if m else None


def strip_markdown(text: str) -> str:
    """Best-effort markdown → plaintext transform tuned for speech.

    Prioritises sentence flow over fidelity: code blocks, headings, list
    markers, URLs and bare paths all disappear; bold/italic markers are
    removed but their content is preserved; links keep the anchor text.
    """
    # HTML / TTS_SUMMARY comments (strip any that survived extract_summary)
    text = re.sub(r"<!--[\s\S]*?-->", " ", text)
    # Fenced code blocks
    text = re.sub(r"```[\s\S]*?```", " ", text)
    # Inline code
    text = re.sub(r"`[^`\n]+`", " ", text)
    # Images ![alt](url) — drop entirely
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    # Links [text](url) → text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Bare URLs → "a link"
    text = re.sub(r"https?://\S+", "a link", text)
    # Heading / blockquote / list markers at line start
    text = re.sub(
        r"^\s{0,3}(#{1,6}|>|[*+\-]|\d+\.)\s+",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Horizontal rules
    text = re.sub(r"^\s*[-*_]{3,}\s*$", " ", text, flags=re.MULTILINE)
    # Bold / italic markers (keep content)
    text = re.sub(r"\*\*\*([^\*\n]+)\*\*\*", r"\1", text)
    text = re.sub(r"\*\*([^\*\n]+)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^\*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"(?<!_)_([^_\n]+)_(?!_)", r"\1", text)
    # Emoji shortcodes :thumbsup:
    text = re.sub(r":[a-z_]+:", " ", text)
    # Table pipes
    text = re.sub(r"\|", " ", text)
    # Bare POSIX paths
    text = re.sub(r"(?:^|\s)(/[\w.\-/]+)", " ", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text
