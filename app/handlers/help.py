from app.utils import keyboards

TEXT = "/gen 4 — Create 4 emails in one live list (1–10).\nEmails and codes use monospace text for copying. Auto-check runs for one hour.\n/start — Menu\n/stats — Statistics"

async def help_command(update, context):
    await update.effective_message.reply_text(TEXT, reply_markup=keyboards.back_to_menu())

async def help_callback(update, context):
    await update.callback_query.answer()
    await update.callback_query.edit_message_text(TEXT, reply_markup=keyboards.back_to_menu())
