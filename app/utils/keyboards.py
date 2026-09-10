"""Inline keyboard builders, kept in one place so button layout stays consistent."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📧 Create Email", callback_data="email:create"),
                InlineKeyboardButton("📋 My Emails", callback_data="email:list"),
            ],
            [
                InlineKeyboardButton("🗑 Delete All", callback_data="email:delete_all_confirm"),
                InlineKeyboardButton("ℹ️ Help", callback_data="menu:help"),
            ],
        ]
    )


def back_to_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="menu:main")]])


def email_created(alias_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📥 Open Inbox", callback_data=f"email:inbox:{alias_id}"),
                InlineKeyboardButton("🔄 Create Another", callback_data="email:create"),
            ],
            [InlineKeyboardButton("🗑 Delete", callback_data=f"email:delete_confirm:{alias_id}")],
            [InlineKeyboardButton("⬅️ Back", callback_data="menu:main")],
        ]
    )


def empty_state() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📧 Create Email", callback_data="email:create")]])


def my_emails_list(aliases) -> InlineKeyboardMarkup:
    rows = []
    for row in aliases:
        rows.append(
            [
                InlineKeyboardButton(f"📥 {row['email_address']}", callback_data=f"email:inbox:{row['alias_id']}"),
                InlineKeyboardButton("🔢", callback_data=f"email:otp:{row['alias_id']}"),
                InlineKeyboardButton("🗑", callback_data=f"email:delete_confirm:{row['alias_id']}"),
            ]
        )
    rows.append([InlineKeyboardButton("📧 Create Email", callback_data="email:create")])
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="menu:main")])
    return InlineKeyboardMarkup(rows)


def inbox_view(alias_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data=f"email:refresh:{alias_id}"),
                InlineKeyboardButton("🔢 Get OTP", callback_data=f"email:otp:{alias_id}"),
            ],
            [InlineKeyboardButton("⬅️ Back", callback_data="email:list")],
        ]
    )


def inbox_with_messages(alias_id: str, message_buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """message_buttons: list of (label, callback_data) for '📖 Read' per message."""
    rows = [[InlineKeyboardButton(label, callback_data=cb)] for label, cb in message_buttons]
    rows.append(
        [
            InlineKeyboardButton("🔄 Refresh", callback_data=f"email:refresh:{alias_id}"),
            InlineKeyboardButton("🔢 Get OTP", callback_data=f"email:otp:{alias_id}"),
        ]
    )
    rows.append([InlineKeyboardButton("⬅️ Back", callback_data="email:list")])
    return InlineKeyboardMarkup(rows)


def confirm_delete(alias_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=f"email:delete:{alias_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data="email:list"),
            ]
        ]
    )


def confirm_delete_all() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Delete All", callback_data="email:delete_all"),
                InlineKeyboardButton("❌ Cancel", callback_data="menu:main"),
            ]
        ]
    )


def otp_found(email_addr: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to Inbox", callback_data="email:list")]])


def otp_not_found(alias_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Refresh", callback_data=f"email:refresh:{alias_id}")]]
    )
