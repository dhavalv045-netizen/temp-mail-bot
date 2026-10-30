"""
Security helpers.

The core rule enforced everywhere in the handlers: a Telegram user may only
ever act on an alias_id that OUR database says belongs to them. alias_id
values arriving from a callback_data string are never trusted on their own.
"""

from app import database
from app.config import ADMIN_TELEGRAM_IDS


def is_admin(telegram_user_id: int) -> bool:
    return telegram_user_id in ADMIN_TELEGRAM_IDS


async def user_owns_alias(telegram_user_id: int, alias_id: str) -> bool:
    owner = await database.get_alias_owner(alias_id)
    return owner is not None and owner == telegram_user_id
