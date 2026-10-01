import html
import re

MAX_DESCRIPTION_CHARS = 4000


def strip_html(raw: str | None, max_chars: int = MAX_DESCRIPTION_CHARS) -> str | None:
    """Convert an (possibly double-escaped) HTML string into clean, truncated plain text."""
    if not raw:
        return None
    text = html.unescape(html.unescape(raw))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "..."
    return text or None
