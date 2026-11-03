"""Turn a markdown article into an ordered list of subtitle lines."""

from __future__ import annotations

import re
from typing import Iterable

# Sentence terminators kept at the end of their sentence.
SENT_END = "。！？!?；;…"

# Secondary break points used when a sentence is too long.
SOFT_BREAK = "，,、：:—；; "


def strip_markdown(md: str, keep_headings: bool = False) -> str:
    text = md.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)          # front matter
    text = re.sub(r"```.*?```", "", text, flags=re.S)                  # code blocks
    text = re.sub(r"`([^`]*)`", r"\1", text)                           # inline code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)                   # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)               # links
    text = re.sub(r"<[^>]+>", "", text)                                # html tags
    text = re.sub(r"^\s*\|.*\|\s*$", "", text, flags=re.M)             # tables
    text = re.sub(r"^\s*\|?[\s:\-|]+\|?\s*$", "", text, flags=re.M)    # table separators
    if keep_headings:
        text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    else:
        text = re.sub(r"^\s{0,3}#{1,6}\s*.*$", "", text, flags=re.M)
    text = re.sub(r"^\s{0,3}>\s?", "", text, flags=re.M)               # quotes
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)               # bullets
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.M)             # ordered lists
    text = re.sub(r"\*\*([^*]*)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]*)\*", r"\1", text)
    text = re.sub(r"__([^_]*)__", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    buf = ""
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        for ch in line:
            buf += ch
            if ch in SENT_END:
                parts.append(buf.strip())
                buf = ""
        if buf.strip():
            parts.append(buf.strip())
            buf = ""
    return [p for p in parts if p]


def _split_long(sentence: str, max_chars: int) -> list[str]:
    # a sentence barely over the limit reads better whole than as 18+2 chars
    if len(sentence) <= max_chars * 1.3:
        return [sentence]
    out: list[str] = []
    rest = sentence
    while len(rest) > max_chars * 1.3:
        window = rest[:max_chars]
        cut = -1
        for i in range(len(window) - 1, 0, -1):
            if window[i] in SOFT_BREAK:
                cut = i
                break
        if cut <= 0:
            # nothing to break on inside the limit: look a little further out
            limit = min(len(rest) - 1, int(max_chars * 1.6))
            for i in range(limit - 1, max_chars - 1, -1):
                if rest[i] in SOFT_BREAK:
                    cut = i
                    break
        if cut <= 0:
            cut = max_chars - 1
        piece = rest[: cut + 1].strip()
        if piece:
            out.append(piece)
        rest = rest[cut + 1:].strip()
    if rest:
        out.append(rest)
    return [s for s in out if s]


_NOSPOKEN = re.compile(r"^[\s\d\.\-_/|:+%()（）\[\]【】<>《》\"'“”‘’·…—]*$")


def _speakable(line: str) -> bool:
    if not line or _NOSPOKEN.match(line):
        return False
    core = re.sub(r"[\s\W_]", "", line, flags=re.UNICODE)
    return len(core) >= 2


def to_subtitles(markdown: str, max_chars: int = 18,
                 keep_headings: bool = False) -> list[str]:
    text = strip_markdown(markdown, keep_headings=keep_headings)
    lines: list[str] = []
    for sent in split_sentences(text):
        for chunk in _split_long(sent, max_chars):
            chunk = chunk.strip()
            if _speakable(chunk):
                lines.append(chunk)
    return lines


def join_for_tts(lines: Iterable[str]) -> str:
    return "".join(lines)


# --------------------------------------------------------------- line mode
_FRONT_KEYS = {
    "voice", "rate", "bgm", "bgm_name", "bgm_volume", "per_image",
    "font_size", "text_y", "pause", "keep_tail", "keep_head",
    "max_chars", "images", "title",
}


def parse_front_matter(md: str) -> tuple[dict, str]:
    """Split a leading `---` block into a params dict and the body."""
    text = md.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    block = text[4:end]
    body = text[end + 4:].lstrip("\n")
    params: dict = {}
    for line in block.split("\n"):
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        k = k.strip().lower()
        v = v.strip().strip("'\"")
        if k not in _FRONT_KEYS:
            continue
        if k in {"per_image", "pause", "keep_tail", "keep_head", "max_chars"}:
            try:
                params[k] = int(float(v))
            except ValueError:
                pass
        elif k in {"font_size", "text_y", "bgm_volume"}:
            try:
                params[k] = float(v)
            except ValueError:
                pass
        else:
            params[k] = v
    return params, body


_MD_LINE = re.compile(r"^\s{0,3}(?:#{1,6}\s+|>\s?|[-*+]\s+|\d+[.)]\s+)")
_IMG_LINE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")
_LINK_ONLY = re.compile(r"^\s*\[[^\]]*\]\([^)]*\)\s*$")


def to_subtitles_by_line(md: str, split_over: int = 0) -> tuple[list[str], list[str]]:
    """One line == one subtitle. Returns (lines, dropped) for transparency."""
    lines: list[str] = []
    dropped: list[str] = []
    for raw in md.replace("\r\n", "\n").split("\n"):
        s = raw.strip()
        if not s:
            continue
        if _IMG_LINE.match(s) or _LINK_ONLY.match(s):
            dropped.append(f"图片/链接行: {s[:40]}")
            continue
        s = _MD_LINE.sub("", s)
        s = re.sub(r"^\s*`+", "", s).strip()
        s = re.sub(r"\*\*([^*]*)\*\*", r"\1", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", s)
        if not s:
            continue
        if split_over and len(s) > split_over:
            for chunk in _split_long(s, split_over):
                if _speakable(chunk):
                    lines.append(chunk)
            continue
        if _speakable(s):
            lines.append(s)
        else:
            dropped.append(f"无内容行: {s[:30]}")
    return lines, dropped
