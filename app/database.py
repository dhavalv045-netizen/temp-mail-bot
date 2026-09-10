"""
Lightweight SQLite storage.

IMPORTANT (Render Free): Render's free-tier filesystem is EPHEMERAL — the
disk is wiped on every deploy and on some restarts. This file therefore
only caches things that are safe to lose:

  - which Telegram user created which InboxMail alias (so we can enforce
    "you can only touch your own aliases")
  - simple counters for /stats

The InboxMail API itself remains the source of truth for whether an alias
actually exists and what mail is in it. If this cache is wiped, a user's
"My Emails" list will show empty even though the aliases may still exist
on InboxMail's side until they expire/are deleted there — this is called
out in the README along with the optional upgrade path (Render persistent
disk / a managed Postgres) if you want the mapping to survive restarts.

We use the stdlib `sqlite3` module with `check_same_thread=False` plus a
single connection guarded by an asyncio lock, which is enough for a bot
handling one update at a time per user and keeps things dependency-free.
"""

import sqlite3
import asyncio
import logging
from contextlib import contextmanager
from datetime import datetime, timezone

from app.config import DATABASE_PATH

logger = logging.getLogger("tempmail.database")

_lock = asyncio.Lock()
_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
    return _conn


def init_db() -> None:
    """Create tables if they don't exist yet. Call once on startup."""
    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            telegram_user_id INTEGER PRIMARY KEY,
            username         TEXT,
            created_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS aliases (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_user_id    INTEGER NOT NULL,
            alias_id            TEXT NOT NULL,   -- InboxMail's alias id (source of truth lives there)
            email_address       TEXT NOT NULL,
            created_at          TEXT NOT NULL,
            last_message_count  INTEGER NOT NULL DEFAULT 0,  -- for "🆕 New email received!" detection
            UNIQUE(telegram_user_id, alias_id)
        );
        CREATE INDEX IF NOT EXISTS idx_aliases_user ON aliases(telegram_user_id);
        CREATE INDEX IF NOT EXISTS idx_aliases_alias_id ON aliases(alias_id);

        CREATE TABLE IF NOT EXISTS stats (
            telegram_user_id  INTEGER PRIMARY KEY,
            emails_received   INTEGER NOT NULL DEFAULT 0,
            otps_found        INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    conn.commit()
    logger.info("Database initialised at %s", DATABASE_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def ensure_user(telegram_user_id: int, username: str | None) -> None:
    async with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO users (telegram_user_id, username, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(telegram_user_id) DO UPDATE SET username=excluded.username
            """,
            (telegram_user_id, username, _now()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO stats (telegram_user_id) VALUES (?)",
            (telegram_user_id,),
        )
        conn.commit()


async def add_alias(telegram_user_id: int, alias_id: str, email_address: str) -> None:
    async with _lock:
        conn = _get_conn()
        conn.execute(
            """
            INSERT OR IGNORE INTO aliases (telegram_user_id, alias_id, email_address, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (telegram_user_id, alias_id, email_address, _now()),
        )
        conn.commit()


async def list_aliases(telegram_user_id: int) -> list[sqlite3.Row]:
    async with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT * FROM aliases WHERE telegram_user_id = ? ORDER BY created_at DESC",
            (telegram_user_id,),
        )
        return cur.fetchall()


async def get_alias_owner(alias_id: str) -> int | None:
    """Used for ownership checks before any inbox/delete action."""
    async with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT telegram_user_id FROM aliases WHERE alias_id = ?", (alias_id,)
        )
        row = cur.fetchone()
        return row["telegram_user_id"] if row else None


async def update_message_count(telegram_user_id: int, alias_id: str, count: int) -> int:
    """Stores the latest known message count for an alias and returns the
    PREVIOUS count, so callers can detect '🆕 New email received!'."""
    async with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT last_message_count FROM aliases WHERE telegram_user_id = ? AND alias_id = ?",
            (telegram_user_id, alias_id),
        )
        row = cur.fetchone()
        previous = row["last_message_count"] if row else 0
        conn.execute(
            "UPDATE aliases SET last_message_count = ? WHERE telegram_user_id = ? AND alias_id = ?",
            (count, telegram_user_id, alias_id),
        )
        conn.commit()
        return previous


async def delete_alias(telegram_user_id: int, alias_id: str) -> None:
    async with _lock:
        conn = _get_conn()
        conn.execute(
            "DELETE FROM aliases WHERE telegram_user_id = ? AND alias_id = ?",
            (telegram_user_id, alias_id),
        )
        conn.commit()


async def delete_all_aliases(telegram_user_id: int) -> int:
    async with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "DELETE FROM aliases WHERE telegram_user_id = ?", (telegram_user_id,)
        )
        conn.commit()
        return cur.rowcount


async def bump_stats(telegram_user_id: int, *, emails: int = 0, otps: int = 0) -> None:
    async with _lock:
        conn = _get_conn()
        conn.execute(
            """
            UPDATE stats SET emails_received = emails_received + ?,
                              otps_found = otps_found + ?
            WHERE telegram_user_id = ?
            """,
            (emails, otps, telegram_user_id),
        )
        conn.commit()


async def get_stats(telegram_user_id: int) -> sqlite3.Row | None:
    async with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "SELECT * FROM stats WHERE telegram_user_id = ?", (telegram_user_id,)
        )
        return cur.fetchone()


async def admin_totals() -> dict:
    async with _lock:
        conn = _get_conn()
        users = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
        aliases = conn.execute("SELECT COUNT(*) c FROM aliases").fetchone()["c"]
        return {"users": users, "aliases": aliases}
