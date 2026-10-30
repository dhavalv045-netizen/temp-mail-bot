"""
Shared logic for finding an OTP in an alias's recent mail. Used by both
the manual "🔢 Get OTP" button (handlers/otp.py) and the cron auto-push
(cron.py) so the two never drift apart.
"""

import logging

from app.inboxmail import client, pick_field
from app.utils.formatting import html_email_to_text
from app.utils.otp import extract_otp

logger = logging.getLogger("tempmail.mail_lookup")


async def find_otp_in_message(msg: dict) -> str | None:
    """
    Step 1 (✅ confirmed): check the subject line — the alias-logs endpoint
    only gives us that much, and plenty of services put the code right in
    the subject (e.g. "123456 is your verification code").

    Step 2 (best-effort fallback, only if step 1 finds nothing): try
    fetching the full email via GET /api/v1/emails/{id}. That endpoint's
    response shape isn't confirmed, so this defensively tries several
    likely field names and simply gives up (returns None) if none match —
    it never guesses a fake code.
    """
    subject = pick_field(msg, "subject", default="")
    code = extract_otp(subject)
    if code:
        return code

    log_id = pick_field(msg, "id")
    if not log_id:
        return None

    try:
        detail = await client.get_email(log_id)
    except Exception:
        logger.info("mail_lookup: body fallback fetch failed for message %s", log_id)
        return None

    body = pick_field(detail, "text_body", "body", "content", "message", "text", default="")
    html = pick_field(detail, "html_body", "html", default="")
    search_text = " ".join(filter(None, [body, html_email_to_text(html)]))
    return extract_otp(search_text)
