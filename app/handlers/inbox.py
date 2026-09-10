import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import database
from app.inboxmail import client, InboxMailError
from app.handlers.email import _pick, GENERIC_ERROR
from app.utils import keyboards, security, sessions
from app.utils.formatting import html_email_to_text, escape_html, split_message, truncate_preview

logger = logging.getLogger("tempmail.handlers.inbox")


async def _render_inbox(query, user_id: int, alias_id: str, *, note_new: bool = False) -> None:
    aliases = await database.list_aliases(user_id)
    match = next((a for a in aliases if a["alias_id"] == alias_id), None)
    email_address = match["email_address"] if match else alias_id

    try:
        messages = await client.get_alias_logs(alias_id)
    except InboxMailError:
        logger.exception("get_alias_logs failed for alias %s", alias_id)
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.inbox_view(alias_id))
        return

    previous_count = await database.update_message_count(user_id, alias_id, len(messages))

    lines = [f"📥 <b>Inbox</b>\n\n📧 {email_address}", "━━━━━━━━━━━━━━"]
    if note_new and len(messages) > previous_count:
        lines.insert(1, "🆕 <b>New email received!</b>\n")

    if not messages:
        lines.append("No messages yet.")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="HTML", reply_markup=keyboards.inbox_view(alias_id)
        )
        return

    message_buttons = []
    for i, msg in enumerate(messages[:10], start=1):
        sender = escape_html(_pick(msg, "from", "from_address", "sender", default="unknown"))
        subject = escape_html(_pick(msg, "subject", default="(no subject)"))
        received = _pick(msg, "received_at", "date", "created_at", default="")
        msg_id = _pick(msg, "id", "message_id", "email_id", default=str(i))

        lines.append(f"\n📩 {i}. {truncate_preview(subject, 50)}")
        lines.append(f"👤 From: {sender}")
        if received:
            lines.append(f"🕐 {received}")

        token = sessions.make_token(user_id, alias_id, str(msg_id))
        message_buttons.append((f"📖 Read #{i}", f"msg:read:{token}"))

    lines.append("━━━━━━━━━━━━━━")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=keyboards.inbox_with_messages(alias_id, message_buttons),
    )


async def inbox_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    alias_id = query.data.split(":", 2)[2]
    user = update.effective_user

    if not await security.user_owns_alias(user.id, alias_id):
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    await _render_inbox(query, user.id, alias_id)


async def refresh_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer("⏳ Checking inbox...")
    alias_id = query.data.split(":", 2)[2]
    user = update.effective_user

    if not await security.user_owns_alias(user.id, alias_id):
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    await _render_inbox(query, user.id, alias_id, note_new=True)


async def read_email_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    token = query.data.split(":", 2)[2]
    user = update.effective_user

    resolved = sessions.resolve_token(token)
    if not resolved or resolved[0] != user.id:
        await query.edit_message_text(
            "❌ This message link expired. Please open the inbox again.",
            reply_markup=keyboards.back_to_menu(),
        )
        return
    _, alias_id, email_id = resolved

    if not await security.user_owns_alias(user.id, alias_id):
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.back_to_menu())
        return

    try:
        detail = await client.get_email(email_id)
    except InboxMailError:
        logger.exception("get_email failed for email %s", email_id)
        await query.edit_message_text(GENERIC_ERROR, reply_markup=keyboards.inbox_view(alias_id))
        return

    sender = escape_html(_pick(detail, "from", "from_address", "sender", default="unknown"))
    subject = escape_html(_pick(detail, "subject", default="(no subject)"))
    date = _pick(detail, "received_at", "date", "created_at", default="")
    raw_html = _pick(detail, "html_body", "html", default="")
    text_body = _pick(detail, "text_body", "text", default="") or html_email_to_text(raw_html)
    body = escape_html(text_body) or "(empty body)"

    header = (
        f"📩 <b>Email Details</b>\n\nFrom: {sender}\nSubject: {subject}\nDate: {date}\n"
        f"━━━━━━━━━━━━━━\n\nBody:\n\n"
    )
    full_text = header + body + "\n\n━━━━━━━━━━━━━━"

    chunks = split_message(full_text)
    await query.edit_message_text(chunks[0], parse_mode="HTML", reply_markup=keyboards.inbox_view(alias_id))
    for chunk in chunks[1:]:
        await query.message.reply_html(chunk)
