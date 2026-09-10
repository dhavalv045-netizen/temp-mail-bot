import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Header, HTTPException
from telegram import Update

from app.config import RENDER_EXTERNAL_URL, WEBHOOK_SECRET, WEBHOOK_PATH
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
        current = await telegram_app.bot.get_webhook_info()
        if current.url != webhook_url:
            await telegram_app.bot.set_webhook(
                url=webhook_url,
                secret_token=WEBHOOK_SECRET,
                allowed_updates=Update.ALL_TYPES,
            )
            logger.info("Webhook configured")
        else:
            logger.info("Webhook already up to date, skipping re-registration")
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


@app.post(WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
):
    if x_telegram_bot_api_secret_token != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
