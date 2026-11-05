"""Private access and persisted, manually checked email batches."""

import hmac
import os
import secrets
import time
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ApplicationHandlerStop

from app import database
from app.config import DOMAIN, FORWARD_TO_EMAIL
from app.inboxmail import client, InboxMailError, pick_field
from app.mail_lookup import find_otp_in_message

_auth_attempts = {}
_generating = set()
_checking = set()
CHECK_COOLDOWN = 0


async def access_guard(update, context):
    user, chat = update.effective_user, update.effective_chat
    if not user or not chat or chat.type != "private":
        if update.callback_query:
            await update.callback_query.answer("Open the bot in a private chat.", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("Open the bot in a private chat.")
        raise ApplicationHandlerStop
    if await database.is_authorized(user.id):
        return
    query = update.callback_query
    if query:
        await query.answer("Send the access key in this chat first.", show_alert=True)
        raise ApplicationHandlerStop
    if not update.effective_message:
        raise ApplicationHandlerStop
    text = (update.effective_message.text or "").strip()
    if not text or text.startswith("/"):
        await update.effective_message.reply_text("🔐 Private bot. Please send your access key (first time only).")
        raise ApplicationHandlerStop
    now = time.monotonic()
    if now - _auth_attempts.get(user.id, -10) < 3:
        await update.effective_message.reply_text("Please wait a few seconds before trying again.")
        raise ApplicationHandlerStop
    _auth_attempts[user.id] = now
    configured = os.getenv("BOT_ACCESS_KEY")
    if not configured:
        await update.effective_message.reply_text("🔐 Access is not configured yet. Ask the owner to set BOT_ACCESS_KEY in the server environment.")
        raise ApplicationHandlerStop
    valid = hmac.compare_digest(text.encode(), configured.encode())
    if not valid:
        await update.effective_message.reply_text("❌ Incorrect access key. Try again.")
        raise ApplicationHandlerStop
    await database.ensure_user(user.id, user.username)
    await database.authorize_user(user.id)
    _auth_attempts.pop(user.id, None)
    await update.effective_message.reply_text("✅ Access granted. Use /gen 4 to generate emails (maximum 10), or /start for the menu.")
    raise ApplicationHandlerStop


def batch_text(rows):
    return "\n\n".join(
        f"{i}. <code>{escape(row['email_address'])}</code>\n"
        + (f"code - <code>{escape(row['otp'])}</code>" if row['otp'] else "code -")
        for i, row in enumerate(rows, 1)
    )


def batch_keyboard(batch_id):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📥 Check Mail", callback_data=f"batch:check:{batch_id}")]])


async def gen_command(update, context):
    args = context.args
    if len(args) != 1 or not args[0].isascii() or not args[0].isdigit() or len(args[0]) > 2 or not 1 <= int(args[0]) <= 10:
        await update.effective_message.reply_text("Use /gen 1 to /gen 10. Example: /gen 4")
        return
    user = update.effective_user
    if user.id in _generating:
        await update.effective_message.reply_text("Your emails are still being generated. Please wait.")
        return
    if not FORWARD_TO_EMAIL:
        await update.effective_message.reply_text("Set FORWARD_TO_EMAIL in the server environment first.")
        return
    _generating.add(user.id)
    try:
        await database.ensure_user(user.id, user.username)
        batch_id = secrets.token_hex(8)
        await database.create_batch(batch_id, user.id)
        message = await update.effective_message.reply_text("⏳ Generating emails…")
        requested = int(args[0])
        for _ in range(requested):
            try:
                result = await client.create_alias(destinations=[FORWARD_TO_EMAIL])
                alias_id, prefix = pick_field(result, "id", "alias_id"), pick_field(result, "prefix")
                if not alias_id or not prefix:
                    raise InboxMailError("Missing alias fields")
                address = f"{prefix}@{DOMAIN}"
                await database.add_alias(user.id, str(alias_id), address)
                await database.add_batch_item(batch_id, str(alias_id), address)
            except InboxMailError:
                break  # Preserve successful addresses; don't keep hitting a failing API.
        rows = await database.get_batch_items(batch_id, user.id)
        if not rows:
            await message.edit_text("❌ Could not generate emails. Please try again later.")
            return
        text = batch_text(rows)
        if len(rows) < requested:
            text += f"\n\n⚠️ Created {len(rows)} of {requested}. Provider unavailable or rate limited; try the remaining emails later."
        await message.edit_text(text, parse_mode="HTML", reply_markup=batch_keyboard(batch_id))
    finally:
        _generating.discard(user.id)


async def check_batch_callback(update, context):
    query, user = update.callback_query, update.effective_user
    batch_id = query.data.split(":", 2)[2]
    rows = await database.get_batch_items(batch_id, user.id)
    if not rows:
        await query.answer("This batch is unavailable. Use /gen again.", show_alert=True)
        return
    if user.id in _checking:
        await query.answer("Already checking. Please wait.")
        return
    if not await database.claim_mail_check(user.id, CHECK_COOLDOWN):
        await query.answer(f"Please wait {CHECK_COOLDOWN} seconds between checks.")
        return
    _checking.add(user.id)
    try:
        await query.answer("Checking mail…")
        failed = False
        for row in rows:
            # Completed/deleted addresses never consume additional API requests.
            if row['otp'] or await database.get_alias_owner(row['alias_id']) != user.id:
                continue
            try:
                messages = await client.get_alias_logs(row['alias_id'])
                for msg in sorted(messages, key=lambda m: str(m.get('created_at') or ''), reverse=True)[:20]:
                    code = await find_otp_in_message(msg)
                    if code:
                        await database.set_batch_otp(batch_id, row['alias_id'], code)
                        await database.bump_stats(user.id, otps=1)
                        break
            except InboxMailError:
                failed = True
                break
        rows = await database.get_batch_items(batch_id, user.id)
        text = batch_text(rows)
        if failed:
            text += "\n\n⚠️ Mail provider unavailable or rate limited. Please check again later."
        try:
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=batch_keyboard(batch_id))
        except BadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                raise
    finally:
        _checking.discard(user.id)
