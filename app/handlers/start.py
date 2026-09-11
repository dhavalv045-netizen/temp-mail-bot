from telegram import Update
from telegram.ext import ContextTypes

from app import database
from app.utils import keyboards

WELCOME_TEXT = (
    "👋 <b>Welcome to Temporary Mail</b>\n\n"
    "📧 Generate a temporary email instantly.\n"
    "📥 Receive emails directly inside Telegram.\n"
    "🔢 Automatically extract OTP codes.\n"
    "🗑 Delete emails whenever you want.\n"
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await database.ensure_user(user.id, user.username)
    await update.message.reply_html(WELCOME_TEXT, reply_markup=keyboards.main_menu())


async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        WELCOME_TEXT, parse_mode="HTML", reply_markup=keyboards.main_menu()
    )
