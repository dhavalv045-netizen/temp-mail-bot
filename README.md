# Telegram Temporary Mail Bot (InboxMail + deeptracex.online)

A Telegram bot front-end for your InboxMail account — create disposable
addresses on `deeptracex.online`, read incoming mail, and auto-extract OTP
codes, all from Telegram.

## ⚠️ Before you deploy: one thing is still unconfirmed

Everything in this project is finished **except** the exact JSON field
names for three InboxMail endpoints:

- `POST /api/v1/aliases` (create an email) — request body fields
- `GET /api/v1/aliases` and `GET /api/v1/aliases/{id}/logs` — response field names (id, email address, sender, subject, date)
- `GET /api/v1/emails/{id}` — response field names for the full email body

I have the correct **URLs, HTTP methods, and auth** for all of these (confirmed
from the docs pages and files you sent), but the Swagger page on
`app.useinbox.email/developer/docs` renders the request/response *schemas*
behind collapsed accordions that weren't expanded in the `.mht` snapshots
you attached — so I don't have the real field names, and I didn't want to
guess and hand you code that silently breaks.

**To finish this in 2 minutes:** log into `app.useinbox.email` → Developer →
API docs → under **Aliases**, click to expand "Create a new alias", "List
all aliases", and "Get alias email logs" — each one shows a *Request body
schema* and a *Responses* example. Screenshot those three (plus "Get email
details" under Emails) and send them to me, and I'll fill in the exact
field names in `app/inboxmail.py` (they're all marked with `⚠️ TODO`
comments so you can find them, or search for `_pick(` in `app/handlers/`).

Everything else below — Telegram UI, OTP extraction, database, security,
rate-limit handling, and the full Render deployment — is complete and
ready to run right now.

---

## A. Requirements

- A Telegram account
- Your InboxMail account (Free plan is fine) with `deeptracex.online` added as a domain
- A free [Render](https://render.com) account
- A free [GitHub](https://github.com) account
- Python 3.13 only if you want to test locally before deploying (optional)

## B. Create your Telegram bot with BotFather

1. Open Telegram, search for **@BotFather**, tap Start.
2. Send `/newbot`.
3. Give it a name (shown to users), then a username ending in `bot` (e.g. `deeptracex_mail_bot`).

## C. Get your Telegram bot token

BotFather replies with a message containing a token that looks like:

```
123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
```

Copy this — you'll paste it into Render in step J, **not** into any code file.

## D. Get your InboxMail API key

1. Log into `app.useinbox.email`.
2. Go to **Developer → API keys**.
3. Create a key (it will look like `neus_...`). Copy it immediately — most
   platforms only show the full key once.

## E. Configure environment variables (reference)

This project reads all configuration from environment variables — never
from a line inside a `.py` file. Here's the full list (see `.env.example`):

| Variable | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | from step C |
| `INBOXMAIL_API_KEY` | from step D |
| `ADMIN_TELEGRAM_ID` | your numeric Telegram user ID (get it from **@userinfobot**) |
| `DOMAIN` | `deeptracex.online` |
| `WEBHOOK_SECRET` | any random string you make up, e.g. run `openssl rand -hex 32` |

## F. Test locally (optional but recommended)

```bash
git clone <your-repo-url>
cd telegram-temp-mail
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# open .env and fill in the 5 values from the table above
```

Local webhook testing needs a public HTTPS URL (Render gives you one for
free, so most people skip local testing and go straight to step I). If you
want to test locally anyway, run `ngrok http 8000` in another terminal,
put that ngrok URL in `.env` as `RENDER_EXTERNAL_URL`, then:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## G. Create a GitHub repository

1. On GitHub, click **New repository** (keep it Private if you like).
2. Don't add a README/gitignore there — you already have both.

## H. Push your code

```bash
cd telegram-temp-mail
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/<your-repo>.git
git push -u origin main
```

`.gitignore` already excludes `.env` and the local `.db` file, so your
secrets never reach GitHub as long as you don't `git add -f` them.

## I. Deploy to Render Free (step by step)

1. Go to [dashboard.render.com](https://dashboard.render.com) → **New +** → **Web Service**.
2. Connect your GitHub account, pick the repo you just pushed.
3. Render auto-detects Python. Fill in:
   - **Name**: anything, e.g. `telegram-temp-mail`
   - **Region**: closest to you
   - **Branch**: `main`
   - **Runtime**: Python 3
   - **Instance Type**: **Free**

## J. Add environment variables — exactly where the API key goes

This is the answer to "which line do I paste the key into": **there is no
code line.** The key is never typed into any file. You paste it into
Render's dashboard, which injects it as an environment variable at
runtime — `app/config.py` then reads it with
`os.environ["INBOXMAIL_API_KEY"]`. That's the only place the code ever
touches it, and it's never logged or printed.

On the same "Create Web Service" page (or afterwards under your service →
**Environment** tab):

1. Click **Add Environment Variable** once for each row below.
2. **Key** = the left column, **Value** = your real secret from steps C/D/E.

| Key | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | *(paste your bot token here)* |
| `INBOXMAIL_API_KEY` | *(paste your InboxMail API key here)* |
| `ADMIN_TELEGRAM_ID` | *(your numeric Telegram ID)* |
| `DOMAIN` | `deeptracex.online` |
| `WEBHOOK_SECRET` | *(paste a random string here)* |

3. Click **Save Changes**.

(If you prefer Blueprints: this repo includes `render.yaml` with these same
five keys pre-listed as `sync: false`, so clicking **New + → Blueprint**
instead of **Web Service** will prompt you for the same values in one
screen.)

## K. Set the build command

In the service settings, **Build Command**:

```
pip install -r requirements.txt
```

## L. Set the start command

**Start Command**:

```
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

`$PORT` is provided by Render automatically — never hardcode a port number.

## M. Deploy

Click **Create Web Service** (or **Deploy** if you already created it).
Watch the **Logs** tab — you should see:

```
INFO tempmail.database: Database initialised at tempmail.db
INFO tempmail.main: Bot started
INFO tempmail.main: Webhook configured
```

## N. Configure the webhook

You don't need to do anything manually — `app/main.py` calls
`set_webhook()` automatically on startup, pointed at
`https://<your-service>.onrender.com/telegram/webhook`, using Render's
own `RENDER_EXTERNAL_URL` variable (which Render sets for you — you don't
add this one yourself). It only re-registers the webhook if it's missing
or different, so redeploys don't spam Telegram's API.

## O. Test your bot

Open Telegram, find your bot by its username, send `/start`. You should
see the welcome message and the main menu buttons.

## P. Troubleshooting

- **Bot doesn't respond at all**: check Render's **Logs** tab for errors.
  Most common cause: a typo in `TELEGRAM_BOT_TOKEN`.
- **"Missing required environment variable" on startup**: you forgot one
  of the 5 keys in step J — add it and redeploy.
- **Bot is slow to respond the first time**: Render Free sleeps your
  service after ~15 minutes of no traffic and takes 30–60 seconds to wake
  up on the next request. This is a Render Free limitation, not a bug —
  don't run background scripts to "ping" it constantly, as that goes
  against the spirit of the free tier and can get flagged.
- **"Create Email" gives a friendly error**: this is expected until the
  alias schema is confirmed — see the ⚠️ section at the top of this file.
- **429 / rate limit messages**: the Free InboxMail plan allows 100
  requests/hour — the bot already retries with backoff and tells the user
  to wait, this isn't an error in the code.

---

## Project structure

```
telegram-temp-mail/
├── app/
│   ├── main.py          FastAPI app, webhook endpoint, startup/shutdown
│   ├── bot.py            Registers all Telegram handlers
│   ├── config.py         Loads all settings from environment variables
│   ├── database.py       SQLite: users, aliases, stats
│   ├── inboxmail.py       InboxMail API client (retry/backoff/rate-limit)
│   ├── handlers/          start, email, inbox, otp, admin, help
│   └── utils/             otp extraction, formatting, security, keyboards, sessions
├── requirements.txt
├── .env.example
├── .gitignore
├── render.yaml
└── README.md
```

## About the SQLite database on Render Free

Render Free's disk is **ephemeral** — it's wiped on redeploys and some
restarts. This bot only uses SQLite to remember *which Telegram user
created which alias* (so people can't access each other's inboxes) and
simple stats counters. If the disk is wiped, InboxMail itself still has
your aliases (it's the source of truth) — they just won't show up under
"My Emails" until you recreate them, since the ownership mapping was lost.

If you want this mapping to survive restarts, the free-tier-friendly
upgrade path is Render's free **persistent disk** add-on (mount it and
point `DATABASE_PATH` at a file inside it) — this is optional and not
required for the bot to work correctly.

## Free vs Pro (per the InboxMail docs)

- **Free-compatible**: aliases, sending mail, reading logs, everything this bot uses.
- **Pro only** (per the docs' own labels): creating/editing/deleting *domains*
  via the API, and **Webhooks** — which is why this bot uses manual 🔄 Refresh
  instead of real-time push notifications. If you upgrade later and want
  instant delivery instead of tap-to-refresh, that's a webhook-based
  rewrite of the inbox flow, not a small tweak.
