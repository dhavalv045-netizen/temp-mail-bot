"""
Telegram limits callback_data to 64 bytes. An alias_id (UUID, 36 chars) fits
fine on its own, but "read this specific message inside this specific alias"
needs two IDs together, which doesn't fit. So for that one case we hand out
a short random token that maps (server-side, in memory) back to the real
(telegram_user_id, alias_id, email_id) tuple.

In-memory is fine here: this is only used for the few seconds between
"here's your inbox list" and "user tapped a message to read it". If the
process restarts between those two taps, the user just taps 📥 Inbox again.
"""

import secrets
import time

_TTL_SECONDS = 30 * 60
_store: dict[str, tuple[int, str, str, float]] = {}  # token -> (user_id, alias_id, email_id, expires_at)


def _cleanup() -> None:
    now = time.time()
    expired = [t for t, (_, _, _, exp) in _store.items() if exp < now]
    for t in expired:
        _store.pop(t, None)


def make_token(telegram_user_id: int, alias_id: str, email_id: str) -> str:
    _cleanup()
    token = secrets.token_hex(4)  # 8 chars
    _store[token] = (telegram_user_id, alias_id, email_id, time.time() + _TTL_SECONDS)
    return token


def resolve_token(token: str) -> tuple[int, str, str] | None:
    entry = _store.get(token)
    if not entry:
        return None
    user_id, alias_id, email_id, expires_at = entry
    if expires_at < time.time():
        _store.pop(token, None)
        return None
    return user_id, alias_id, email_id
