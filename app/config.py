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
MAIL_BACKEND = _optional("MAIL_BACKEND", "cloudflare").lower()
if MAIL_BACKEND not in {"cloudflare", "inboxmail"}:
    raise RuntimeError("MAIL_BACKEND must be cloudflare or inboxmail")
CLOUDFLARE_MAIL_URL = _optional("CLOUDFLARE_MAIL_URL").rstrip("/")
CLOUDFLARE_MAIL_TOKEN = _optional("CLOUDFLARE_MAIL_TOKEN")
if MAIL_BACKEND == "cloudflare":
    from urllib.parse import urlparse
    parsed = urlparse(CLOUDFLARE_MAIL_URL)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise RuntimeError("Set CLOUDFLARE_MAIL_URL to the HTTPS Worker origin, without a path")
    if len(CLOUDFLARE_MAIL_TOKEN) < 32:
        raise RuntimeError("CLOUDFLARE_MAIL_TOKEN must contain at least 32 characters")
INBOXMAIL_API_KEY = _require("INBOXMAIL_API_KEY") if MAIL_BACKEND == "inboxmail" else ""
INBOXMAIL_BASE_URL = _optional("INBOXMAIL_BASE_URL", "https://api.useinbox.email")
DOMAIN = _optional("DOMAIN", "accounthub.live")

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

# --- Cron (for auto-OTP polling + keeping Render awake, see cron-job.org) ---
# Any long random string — protects /cron/check-otp from random hits.
CRON_SECRET = _optional("CRON_SECRET", "")

# --- Database ---
DATABASE_PATH = _optional("DATABASE_PATH", "tempmail.db")

# --- Rate limiting (client-side, mirrors InboxMail's own limits so we fail
# gracefully instead of hammering their API) ---
INBOXMAIL_MAX_RETRIES = int(_optional("INBOXMAIL_MAX_RETRIES", "3"))
INBOXMAIL_TIMEOUT_SECONDS = float(_optional("INBOXMAIL_TIMEOUT_SECONDS", "15"))
