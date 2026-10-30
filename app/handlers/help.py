from telegram import Update
from telegram.ext import ContextTypes

from app.utils import keyboards


HELP_TEXT = (
    "📖 Temporary Mail Help\n\n"
    "📧 Create Email: Generate a new email address.\n"
    "📋 My Emails: View your saved addresses.\n"
    "🔢 Get OTP: Check an address for a verification code.\n"
    "🗑 Delete Email: Remove an address.\n\n"
    "Commands: /start /help /stats"
)


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    await update.effective_message.reply_text(
        HELP_TEXT,
        reply_markup=keyboards.back_to_menu(),
    )


async def help_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        HELP_TEXT,
        reply_markup=keyboards.back_to_menu(),
    )
