"""Render incoming MIME mail for Telegram and preserve the original as an attachment."""
import re
from email import policy
from email.parser import BytesParser
from html import escape

from bs4 import BeautifulSoup


def display_body(mail):
    part = mail.get_body(preferencelist=("html", "plain"))
    if part is None:
        return ""
    body = part.get_content()
    if part.get_content_type() == "text/plain":
        return body
    soup = BeautifulSoup(body, "html.parser")
    for hidden in soup(["style", "script", "head"]):
        hidden.decompose()
    for link in soup.select("a[href]"):
        href = link["href"].strip()
        if href.startswith(("http://", "https://")) and href != link.get_text(strip=True):
            link.append(f" ({href})")
    return soup.get_text("\n", strip=True)


TOKEN = re.compile(r"https?://[^\s<>]+|(?<![\w-])\d{4,8}(?![\w-])", re.I)


def chunks(text):
    # Keep links and copyable codes intact when crossing a message boundary.
    pieces = re.split(f"({TOKEN.pattern})", text, flags=re.I)
    current = ""
    size = 0
    for piece in pieces:
        for pos in range(0, len(piece), 1900):
            fragment = piece[pos:pos + 1900]
            if size + len(fragment) > 1900:
                yield current
                current, size = "", 0
            value = escape(fragment)
            current += f"<code>{value}</code>" if piece.isascii() and piece.isdigit() and 4 <= len(piece) <= 8 else value
            size += len(fragment)
    if current:
        yield current


async def deliver(bot, owner, recipient, raw):
    mail = BytesParser(policy=policy.default).parsebytes(raw)
    text = f"Receiver: {recipient}\nFrom: {mail.get('From', '')}\nSubject: {mail.get('Subject', '')}\n\n{display_body(mail)}"
    for chunk in chunks(text):
        await bot.send_message(chat_id=owner, text=chunk, parse_mode="HTML", disable_web_page_preview=True)
    await bot.send_document(chat_id=owner, document=raw, filename="original-email.eml")
