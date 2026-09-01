import re


_MARKDOWN_LINK = re.compile(r"\[([^\]]+)]\([^\)]+\)")
_MARKDOWN_DECORATION = re.compile(r"(?:\*\*|__|~~|`{1,3})")
_HEADING_OR_QUOTE = re.compile(r"(?m)^\s{0,3}(?:#{1,6}|>)\s*")
_LIST_MARKER = re.compile(r"(?m)^\s*(?:[-*+] |\d+[.)]\s+)")
_WHITESPACE = re.compile(r"[ \t]+")
_TOO_MANY_NEWLINES = re.compile(r"\n{3,}")


def speech_friendly(text: str) -> str:
    """Remove common Markdown constructs that sound bad when spoken."""
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _MARKDOWN_DECORATION.sub("", text)
    text = _HEADING_OR_QUOTE.sub("", text)
    text = _LIST_MARKER.sub("", text)
    text = _WHITESPACE.sub(" ", text)
    text = _TOO_MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def shorten_for_alice(text: str, limit: int) -> str:
    text = speech_friendly(text)
    if len(text) <= limit:
        return text

    candidate = text[: limit - 1].rstrip()
    sentence_end = max(candidate.rfind(". "), candidate.rfind("! "), candidate.rfind("? "))
    if sentence_end >= max(80, limit // 2):
        return candidate[: sentence_end + 1]

    word_end = candidate.rfind(" ")
    if word_end >= max(40, limit // 2):
        candidate = candidate[:word_end]
    return candidate.rstrip(" ,;:-") + "…"

