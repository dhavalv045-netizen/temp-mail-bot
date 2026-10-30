import logging

from telegram import Update
from telegram.ext import ContextTypes

from app import database
from app.utils.security import is_admin

logger = logging.getLogger("tempmail.handlers.admin")

ADMIN_ONLY_TEXT = "❌ This command is for admins only."


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Personal stats — available to any user, matches item 17 of the spec."""
    user = update.effective_user
    row = await database.get_stats(user.id)
    aliases = await database.list_aliases(user.id)

    emails_received = row["emails_received"] if row else 0
    otps_found = row["otps_found"] if row else 0

    text = (
        "📊 <b>Your Statistics</b>\n\n"
        f"📧 Active Emails: {len(aliases)}\n"
        f"📩 Emails Received: {emails_received}\n"
        f"🔢 OTPs Found: {otps_found}"
    )
    await update.message.reply_html(text)


async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return

    totals = await database.admin_totals()
    text = (
        "🛠 <b>Admin Dashboard</b>\n\n"
        f"👥 Total users: {totals['users']}\n"
        f"📧 Total aliases: {totals['aliases']}\n"
        f"📩 API status: use /health\n"
        f"⚡ Recent errors: check server logs\n\n"
        "Commands: /stats /users /broadcast /health"
    )
    await update.message.reply_html(text)


async def users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return
    totals = await database.admin_totals()
    await update.message.reply_text(f"👥 Total users: {totals['users']}")


async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return

    message_text = " ".join(context.args) if context.args else ""
    if not message_text:
        await update.message.reply_text("Usage: /broadcast <message>")
        return

    conn = database._get_conn()
    rows = conn.execute("SELECT telegram_user_id FROM users").fetchall()

    sent, failed = 0, 0
    for row in rows:
        try:
            await context.bot.send_message(chat_id=row["telegram_user_id"], text=f"📢 {message_text}")
            sent += 1
        except Exception:
            failed += 1
    await update.message.reply_text(f"📢 Broadcast sent to {sent} users ({failed} failed).")


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_admin(user.id):
        await update.message.reply_text(ADMIN_ONLY_TEXT)
        return

    from app.inboxmail import client, InboxMailError

    try:
        await client.list_domains()
        api_status = "✅ reachable"
    except InboxMailError:
        api_status = "❌ unreachable"

    await update.message.reply_text(f"📩 InboxMail API: {api_status}")
