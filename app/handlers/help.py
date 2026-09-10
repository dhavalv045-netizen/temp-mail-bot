from telegram import Update
from telegram.ext import ContextTypes

from app.utils import keyboards

HELP_TEXT = (
    "ℹ️ <b>Help</b>\n\n"
    "📧 <b>Create Email</b> — generate a new temporary address\n"
    "📥 <b>Inbox</b> — see received messages\n"
    "🔢 <b>OTP</b> — pull the latest verification code automatically\n"
    "🗑 <b>Delete</b> — remove an email you no longer need\n"
    "🔄 <b>Refresh</b> — check an inbox again without creating a new email\n\n"
    "Use /stats anytime to see your own usage."
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_html(HELP_TEXT, reply_markup=keyboards.back_to_menu())


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(HELP_TEXT, parse_mode="HTML", reply_markup=keyboards.back_to_menu())
