import logging

from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from app.config import TELEGRAM_BOT_TOKEN
from app.handlers import start, help as help_handler, email, otp, admin

logger = logging.getLogger("tempmail.bot")


def build_application() -> Application:
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Commands
    application.add_handler(CommandHandler("start", start.start_command))
    application.add_handler(CommandHandler("help", help_handler.help_command))
    application.add_handler(CommandHandler("stats", admin.stats_command))
    application.add_handler(CommandHandler("admin", admin.admin_command))
    application.add_handler(CommandHandler("users", admin.users_command))
    application.add_handler(CommandHandler("broadcast", admin.broadcast_command))
    application.add_handler(CommandHandler("health", admin.health_command))

    # Callback queries — routed by callback_data prefix.
    application.add_handler(CallbackQueryHandler(start.main_menu_callback, pattern=r"^menu:main$"))
    application.add_handler(CallbackQueryHandler(help_handler.help_callback, pattern=r"^menu:help$"))

    application.add_handler(CallbackQueryHandler(email.create_email_callback, pattern=r"^email:create$"))
    application.add_handler(CallbackQueryHandler(email.list_emails_callback, pattern=r"^email:list$"))
    application.add_handler(
        CallbackQueryHandler(email.delete_confirm_callback, pattern=r"^email:delete_confirm:")
    )
    application.add_handler(CallbackQueryHandler(email.delete_callback, pattern=r"^email:delete:"))
    application.add_handler(
        CallbackQueryHandler(email.delete_all_confirm_callback, pattern=r"^email:delete_all_confirm$")
    )
    application.add_handler(CallbackQueryHandler(email.delete_all_callback, pattern=r"^email:delete_all$"))

    application.add_handler(CallbackQueryHandler(otp.get_otp_callback, pattern=r"^email:otp:"))

    return application
