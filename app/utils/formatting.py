"""
Formatting helpers:
  - safely turn an email's HTML body into plain, readable text
  - escape text for Telegram's HTML parse_mode (so a stray "<" in an email
    can never break the message or inject formatting)
  - split long messages into chunks under Telegram's 4096-char limit
"""

import html
import re
from bs4 import BeautifulSoup

TELEGRAM_MAX_LEN = 4096
# leave headroom for any wrapping tags/buttons text we add around a chunk
SAFE_CHUNK_LEN = 3800


def html_email_to_text(raw_html: str) -> str:
    """Strip an email's HTML down to readable plain text. Never trust the
    input — this only extracts visible text, no scripts/styles/tags survive."""
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text("\n")
    # collapse excess blank lines
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def escape_html(text: str) -> str:
    """Escape text for safe use inside a Telegram HTML parse_mode message."""
    if not text:
        return ""
    return html.escape(text, quote=False)


def split_message(text: str, limit: int = SAFE_CHUNK_LEN) -> list[str]:
    """Split text into chunks under `limit`, breaking on newlines/spaces
    where possible so words/lines aren't cut mid-way."""
    if len(text) <= limit:
        return [text]

    chunks = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


def truncate_preview(text: str, length: int = 40) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= length else text[: length - 1] + "…"
