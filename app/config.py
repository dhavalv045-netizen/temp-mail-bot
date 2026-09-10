"""
Central configuration for the bot.

EVERYTHING here is loaded from environment variables. Nothing secret is
ever hardcoded. On Render, you set these under:

    Dashboard -> your service -> Environment tab -> Add Environment Variable

Locally, you set them in a `.env` file (see .env.example) which is loaded
by python-dotenv when the app starts (see main.py).
"""

import os
import logging

from dotenv import load_dotenv

# Loads variables from a local .env file if one exists (for local testing
# only — Render injects real environment variables directly, so this is a
# no-op in production and never overrides variables Render already set).
load_dotenv()

logger = logging.getLogger("tempmail.config")


def _require(name: str) -> str:
    """Fetch a required env var or fail loudly (but WITHOUT printing its value)."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it in Render's Environment tab (or your local .env file)."
        )
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


# --- Telegram ---
TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")

# --- InboxMail ---
INBOXMAIL_API_KEY = _require("INBOXMAIL_API_KEY")
INBOXMAIL_BASE_URL = _optional("INBOXMAIL_BASE_URL", "https://api.useinbox.email")
DOMAIN = _optional("DOMAIN", "deeptracex.online")

# Real email address that created aliases forward to. InboxMail's aliases
# are forward-only (confirmed via their API docs) — every alias needs at
# least one real destination inbox. This is YOUR choice (e.g. your own
# Gmail), not something the bot invents. Optional at startup (so the rest
# of the bot still runs without it) but "Create Email" shows a clear
# message telling you to set this until it's filled in.
FORWARD_TO_EMAIL = _optional("FORWARD_TO_EMAIL", "")

# --- Admin ---
# Comma-separated list of Telegram numeric user IDs allowed to use /admin.
_admin_raw = _optional("ADMIN_TELEGRAM_ID", "")
ADMIN_TELEGRAM_IDS = {
    int(x.strip()) for x in _admin_raw.split(",") if x.strip().isdigit()
}

# --- Webhook ---
# The full public HTTPS URL Render gives your service, e.g.
# https://your-service-name.onrender.com
RENDER_EXTERNAL_URL = _optional("RENDER_EXTERNAL_URL")  # Render sets this automatically
WEBHOOK_SECRET = _require("WEBHOOK_SECRET")
WEBHOOK_PATH = "/telegram/webhook"

# --- Database ---
DATABASE_PATH = _optional("DATABASE_PATH", "tempmail.db")

# --- Rate limiting (client-side, mirrors InboxMail's own limits so we fail
# gracefully instead of hammering their API) ---
INBOXMAIL_MAX_RETRIES = int(_optional("INBOXMAIL_MAX_RETRIES", "3"))
INBOXMAIL_TIMEOUT_SECONDS = float(_optional("INBOXMAIL_TIMEOUT_SECONDS", "15"))
