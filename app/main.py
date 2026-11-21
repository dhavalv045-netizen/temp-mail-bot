import logging
from secrets import compare_digest
from app.config import CLOUDFLARE_MAIL_TOKEN, DOMAIN
from app.full_mail import deliver
from app.utils.security import is_admin
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException
from telegram import Update

from app.config import RENDER_EXTERNAL_URL, WEBHOOK_SECRET, WEBHOOK_PATH, CRON_SECRET
from app import database
from app.bot import build_application
from app.inboxmail import client as inboxmail_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("tempmail.main")

telegram_app = build_application()


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()

    await telegram_app.initialize()
    await telegram_app.start()
    logger.info("Bot started")

    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"
        # Re-register to also apply a rotated secret at an unchanged URL.
        await telegram_app.bot.set_webhook(
            url=webhook_url, secret_token=WEBHOOK_SECRET,
            allowed_updates=Update.ALL_TYPES,
        )
        logger.info("Webhook configured")
    else:
        logger.warning(
            "RENDER_EXTERNAL_URL not set — skipping automatic webhook registration "
            "(expected when running locally; set the webhook manually for local testing)."
        )

    yield

    await telegram_app.stop()
    await telegram_app.shutdown()
    await inboxmail_client.aclose()
    logger.info("Bot stopped")


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/cron/check-otp")
async def cron_check_otp(token: str = ""):
    """Legacy scheduler URL remains a health check; no mailbox API calls."""
    if not CRON_SECRET or token != CRON_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    return {"status": "ok", "mode": "manual", "checked": 0}


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.update_queue.put(update)
    return {"ok": True}


@app.post("/cloudflare/full-mail")
async def full_mail(request: Request):
    token = request.headers.get("authorization", "").encode()
    if not CLOUDFLARE_MAIL_TOKEN or not compare_digest(token, f"Bearer {CLOUDFLARE_MAIL_TOKEN}".encode()):
        raise HTTPException(status_code=401)
    alias = request.headers.get("x-mail-alias", "")
    recipient = request.headers.get("x-mail-recipient", "")
    owner = await database.get_alias_owner(alias)
    if recipient != f"{alias}@{DOMAIN}" or owner is None or not is_admin(owner) or not database.full_mail_enabled(owner):
        return {"delivered": False}
    await deliver(telegram_app.bot, owner, recipient, await request.body())
    return {"delivered": True}
