import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import database
from app.inboxmail import client, InboxMailError
from app.handlers.email import _pick, GENERIC_ERROR
from app.utils import keyboards, security
from app.utils.formatting import html_email_to_text, escape_html
from app.utils.otp import extract_otp

logger = logging.getLogger("tempmail.handlers.otp")


async def get_otp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    alias_id = query.data.split(":", 2)[2]
    user = update.effective_user

    if not await security.user_owns_alias(user.id, alias_id):
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    try:
        messages = await client.get_alias_logs(alias_id)
    except InboxMailError as exc:
        logger.info("get_alias_logs not ready for alias %s: %s", alias_id, exc)
        await query.edit_message_text(
            "🛠 <b>OTP lookup isn't wired up yet</b>\n\n"
            "One more InboxMail schema needs confirming before this works "
            "— see the developer note in app/inboxmail.py / the README.",
            parse_mode="HTML",
            reply_markup=keyboards.inbox_view(alias_id),
        )
        return

    if not messages:
        await query.edit_message_text(
            "❌ No OTP found in the latest emails.", reply_markup=keyboards.otp_not_found(alias_id)
        )
        return

    # Look at the most recent messages, newest first, until an OTP is found.
    for msg in messages[:5]:
        subject = _pick(msg, "subject", default="")
        preview = _pick(msg, "preview", "snippet", "body", "text_body", default="")
        raw_html = _pick(msg, "html_body", "html", default="")
        search_text = " ".join(filter(None, [subject, preview, html_email_to_text(raw_html)]))

        code = extract_otp(search_text)
        if code:
            sender = escape_html(_pick(msg, "from", "from_address", "sender", default="unknown"))
            subject_esc = escape_html(subject or "(no subject)")
            await database.bump_stats(user.id, otps=1)
            text = (
                f"🔢 <b>OTP Found</b>\n\nCode:\n<code>{code}</code>\n\n"
                f"📧 From:\n{sender}\n\n📩 Subject:\n{subject_esc}\n\n"
                f"Tap the code to copy."
            )
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboards.otp_found(alias_id))
            return

    await query.edit_message_text(
        "❌ No OTP found in the latest emails.", reply_markup=keyboards.otp_not_found(alias_id)
    )
