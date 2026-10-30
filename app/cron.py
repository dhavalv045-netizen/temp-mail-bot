"""
Called by GET /cron/check-otp (see main.py), which an external scheduler
like cron-job.org hits every few minutes. Two jobs at once:

  1. Keeps the Render Free service awake (any HTTP request does this).
  2. Checks every known alias for new mail and, if an OTP is found, PUSHES
     it straight to the owning Telegram user — no "open inbox" needed.

New vs already-seen messages are tracked by message id in the
`seen_messages` table — not by list position, since the logs endpoint's
ordering isn't confirmed.
"""

import asyncio
import logging

from telegram import Bot

from app import database
from app.inboxmail import client, InboxMailError, pick_field
from app.mail_lookup import find_otp_in_message

logger = logging.getLogger("tempmail.cron")

# Small pause between aliases so one cron run doesn't burst through
# InboxMail's rate limit (Free: 100 req/hour ≈ under 2/min on average).
_DELAY_BETWEEN_ALIASES = 1.0


def _msg_key(msg: dict) -> str:
    """Identify a message by id where possible, falling back to a stable
    subject+date key — either way, never by list position/order."""
    mid = pick_field(msg, "id", "message_id", "email_id")
    if mid:
        return str(mid)
    return f"{pick_field(msg, 'subject', default='')}|{pick_field(msg, 'created_at', 'received_at', 'date', default='')}"


async def check_all_aliases_for_otp(bot: Bot) -> dict:
    """Returns a small summary dict for the cron endpoint's response body."""
    conn = database._get_conn()
    rows = conn.execute(
        "SELECT telegram_user_id, alias_id, email_address FROM aliases"
    ).fetchall()

    checked, notified, skipped = 0, 0, 0

    for row in rows:
        checked += 1
        try:
            messages = await client.get_alias_logs(row["alias_id"])
        except InboxMailError:
            logger.exception("cron: get_alias_logs failed for alias %s", row["alias_id"])
            skipped += 1
            await asyncio.sleep(_DELAY_BETWEEN_ALIASES)
            continue

        all_keys = [_msg_key(m) for m in messages]
        unseen_keys = await database.get_unseen_message_ids(row["alias_id"], all_keys)
        new_messages = [m for m, key in zip(messages, all_keys) if key in unseen_keys]

        for msg in new_messages:
            code = await find_otp_in_message(msg)
            sender = pick_field(msg, "sender", "from", default="")

            try:
                if code:
                    await bot.send_message(
                        chat_id=row["telegram_user_id"],
                        text=(
                            f"🔢 <b>New OTP</b>\n\n"
                            f"📧 {row['email_address']}\n"
                            f"Code: <code>{code}</code>\n\n"
                            f"Tap the code to copy."
                        ),
                        parse_mode="HTML",
                    )
                    await database.bump_stats(row["telegram_user_id"], otps=1, emails=1)
                    notified += 1
                else:
                    from_line = f" from {sender}" if sender else ""
                    await bot.send_message(
                        chat_id=row["telegram_user_id"],
                        text=f"📩 New email{from_line} on {row['email_address']} (no OTP code found).",
                    )
                    await database.bump_stats(row["telegram_user_id"], emails=1)
            except Exception:
                logger.exception("cron: failed to notify user %s", row["telegram_user_id"])

        await database.mark_messages_seen(row["alias_id"], all_keys)
        await asyncio.sleep(_DELAY_BETWEEN_ALIASES)

    return {"checked": checked, "notified": notified, "skipped_not_ready": skipped}


