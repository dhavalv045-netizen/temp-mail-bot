import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import database
from app.inboxmail import client, InboxMailError, pick_field
from app.handlers.email import GENERIC_ERROR
from app.mail_lookup import find_otp_in_message
from app.utils import keyboards, security
from app.utils.formatting import escape_html

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
    except InboxMailError:
        logger.exception("get_alias_logs failed for alias %s", alias_id)
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.otp_not_found(alias_id))
        return

    if not messages:
        await query.edit_message_text(
            "❌ No OTP found in the latest emails.", reply_markup=keyboards.otp_not_found(alias_id)
        )
        return

    # Newest-first isn't confirmed, so check all recent ones, not just the first few.
    for msg in messages[:20]:
        code = await find_otp_in_message(msg)
        if code:
            sender = escape_html(pick_field(msg, "sender", "from", default="unknown"))
            subject_esc = escape_html(pick_field(msg, "subject", default="(no subject)"))
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
