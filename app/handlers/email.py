import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import database
from app.config import DOMAIN
from app.inboxmail import client, InboxMailError
from app.utils import keyboards, security

logger = logging.getLogger("tempmail.handlers.email")

GENERIC_ERROR = "❌ Something went wrong.\nPlease try again."


def _pick(data: dict, *keys: str, default=None):
    """Try several possible field names — see the ⚠️ notes in inboxmail.py
    for why this is defensive rather than a single confirmed key."""
    for key in keys:
        if key in data and data[key]:
            return data[key]
    return default


async def create_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    await database.ensure_user(user.id, user.username)

    try:
        result = await client.create_alias(DOMAIN)
    except InboxMailError:
        logger.exception("create_alias failed for user %s", user.id)
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    alias_id = _pick(result, "id", "alias_id")
    email_address = _pick(result, "email", "email_address", "address", "full_address")

    if not alias_id or not email_address:
        # This is exactly the "response field missing" case flagged in
        # inboxmail.py — surfacing it clearly instead of pretending it worked.
        logger.error("create_alias response missing expected fields for user %s: keys=%s",
                      user.id, list(result.keys()))
        await query.edit_message_text(
            "❌ Email was created but the response format wasn't recognised.\n"
            "Please confirm the real field names from your InboxMail docs "
            "(see the ⚠️ note in app/inboxmail.py).",
            reply_markup=keyboards.back_to_menu(),
        )
        return

    await database.add_alias(user.id, alias_id, email_address)

    text = f"✅ <b>Email Created</b>\n\n📧 Email:\n<code>{email_address}</code>"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboards.email_created(alias_id))


async def list_emails_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    aliases = await database.list_aliases(user.id)

    if not aliases:
        await query.edit_message_text(
            "❌ You don't have any active emails.", reply_markup=keyboards.empty_state()
        )
        return

    lines = ["📋 <b>Your Emails</b>", ""]
    numerals = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, row in enumerate(aliases):
        prefix = numerals[i] if i < len(numerals) else f"{i + 1}."
        lines.append(f"{prefix} {row['email_address']}")

    await query.edit_message_text(
        "\n".join(lines), parse_mode="HTML", reply_markup=keyboards.my_emails_list(aliases)
    )


async def delete_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    alias_id = query.data.split(":", 2)[2]
    user = update.effective_user

    if not await security.user_owns_alias(user.id, alias_id):
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    aliases = await database.list_aliases(user.id)
    match = next((a for a in aliases if a["alias_id"] == alias_id), None)
    email_address = match["email_address"] if match else "this email"

    text = f"⚠️ <b>Delete Email?</b>\n\n📧 {email_address}\n\nThis cannot be undone."
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboards.confirm_delete(alias_id))


async def delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    alias_id = query.data.split(":", 2)[2]
    user = update.effective_user

    if not await security.user_owns_alias(user.id, alias_id):
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    try:
        await client.delete_alias(alias_id)
    except InboxMailError:
        logger.exception("delete_alias failed for user %s alias %s", user.id, alias_id)
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    await database.delete_alias(user.id, alias_id)
    await query.edit_message_text("🗑 Email deleted successfully.", reply_markup=keyboards.back_to_menu())


async def delete_all_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    aliases = await database.list_aliases(user.id)

    if not aliases:
        await query.edit_message_text("❌ You don't have any active emails.", reply_markup=keyboards.back_to_menu())
        return

    text = f"⚠️ <b>Delete ALL Emails?</b>\n\nThis will remove:\n\n📧 {len(aliases)} active emails\n\nAre you sure?"
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=keyboards.confirm_delete_all())


async def delete_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    aliases = await database.list_aliases(user.id)

    failures = 0
    for row in aliases:
        try:
            await client.delete_alias(row["alias_id"])
        except InboxMailError:
            logger.warning("delete_alias failed during delete-all for user %s alias %s",
                            user.id, row["alias_id"])
            failures += 1

    await database.delete_all_aliases(user.id)

    if failures:
        text = (
            f"🗑 Deleted {len(aliases) - failures} of {len(aliases)} emails.\n"
            f"{failures} couldn't be removed on InboxMail's side but have been cleared from your list."
        )
    else:
        text = "🗑 All emails deleted successfully."
    await query.edit_message_text(text, reply_markup=keyboards.back_to_menu())
