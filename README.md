# Telegram temp mail bot — Cloudflare backend

Default mail backend: Cloudflare Email Routing + Email Worker + D1. The Telegram app stays on Render. Existing commands and buttons are preserved; mail checking remains manual.

**Start here: [Complete Cloudflare + Render setup (Hinglish)](docs/CLOUDFLARE_SETUP.md).**

- Worker source and schema: `cloudflare/`
- Render environment template: `render.yaml`
- No InboxMail API key or forwarding address required in Cloudflare mode.
- Deploy/configure the Worker and set Render environment before deploying this version.
- Old InboxMail mailboxes are not migrated. Generate new addresses after cutover.
- Mail storage persists in D1; existing Render SQLite bot history still needs a persistent disk to survive filesystem resets. See setup guide before relying on saved batches.

## Previous InboxMail documentation (legacy / rollback only)

The documentation below describes the old provider. It does not describe the default Cloudflare setup. For current instructions use the guide above. Set `MAIL_BACKEND=inboxmail` only when deliberately restoring that backend.

# Telegram Temporary Mail Bot (InboxMail + deeptracex.online)

A Telegram bot front-end for your InboxMail account — create disposable
addresses on `deeptracex.online` and check OTP codes manually in Telegram.

## Private access and manual batches

- Send the private key once in a private chat. Authorization is saved in SQLite and applies to all commands/buttons.
- `/gen 4` creates four emails in one message; valid range is 1–10. Emails and OTPs use copyable monospace text, with `code -` below each address and no sender details.
- Tap **Check Mail** below the batch to check pending addresses sequentially. A 15-second per-user cooldown limits repeated clicks. Completed OTPs are cached and no longer checked.
- Partial generation retains successful emails. Provider errors stop further requests in that batch.
- Automatic OTP polling is disabled. The legacy authenticated `/cron/check-otp` endpoint now returns health status without querying mailboxes.
- Set `BOT_ACCESS_KEY` in the server environment to your private access key before deploying. No key or key hash is stored in the repository; new access fails closed when the variable is missing. Changing the key does not revoke already authorized users.
- Authorization and batches persist only while the SQLite file survives. Use durable storage for `DATABASE_PATH` to retain access across redeploys. After an ephemeral disk reset, users must enter the key again.
- Existing menus and admin commands remain available.

Run mocked regression tests with `python -m unittest discover -s tests -v`.



## ✅ Status: fully wired up

Every InboxMail endpoint this bot uses has been confirmed live against
your account's Swagger docs — nothing here is guessed:

```
POST /api/v1/aliases                    create a temp email
GET  /api/v1/aliases/{id}/logs           check for new mail (id, sender,
                                          recipient, subject, status,
                                          direction, created_at)
DELETE /api/v1/aliases/{id}              delete a temp email
POST /api/v1/emails/send                 (available, not exposed to users yet)
```

**Important discovery:** InboxMail's aliases are a **forwarding service**
— every alias must forward to a real destination email address you own
(the `destinations` field, required). One environment variable handles this:

| Key | Value |
|---|---|
| `FORWARD_TO_EMAIL` | your own real email address |

**One known limitation:** the alias-logs endpoint only gives a
**subject line**, not the full email body — there's no body/content field
in its response. OTP extraction therefore checks the subject first (works
for the very common "123456 is your code" style), and as a best-effort
fallback tries fetching the full email via `GET /api/v1/emails/{id}` —
that endpoint's exact response shape isn't confirmed, so this fallback is
defensively parsed and just skips silently if it doesn't recognise the
shape, rather than ever guessing a fake code. If you find OTPs that only
appear in the body aren't being caught, send me a screenshot of that
endpoint's schema the same way as before and I'll lock it in properly.

**No more manual "📥 Inbox" browsing** — removed per request. The flow now
is: `/gen 4` → receive addresses → tap **Check Mail**. "🔢 Get OTP" still exists as an on-demand manual check.

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
| `FORWARD_TO_EMAIL` | your own real email — InboxMail forwards created aliases' mail here |
| `WEBHOOK_SECRET` | any random string you make up, e.g. run `openssl rand -hex 32` |
| `CRON_SECRET` | another random string — protects the auto-OTP cron endpoint (see step Q) |

## F. Test locally (optional but recommended)

```bash
git clone <your-repo-url>
cd telegram-temp-mail
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# open .env and fill in the values from the table above
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
| `FORWARD_TO_EMAIL` | *(your own real email address)* |
| `WEBHOOK_SECRET` | *(paste a random string here)* |
| `CRON_SECRET` | *(paste another random string here)* |

3. Click **Save Changes**.

(If you prefer Blueprints: this repo includes `render.yaml` with these same
keys pre-listed as `sync: false`, so clicking **New + → Blueprint**
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

## P. Manual checking

No mail polling schedule is needed. Tap **Check Mail** under a batch.
An existing authenticated `/cron/check-otp` schedule now only returns health status.

## Q. Troubleshooting

- **Bot doesn't respond at all**: check Render's **Logs** tab for errors.
  Most common cause: a typo in `TELEGRAM_BOT_TOKEN`.
- **"Missing required environment variable" on startup**: only
  `TELEGRAM_BOT_TOKEN`, `INBOXMAIL_API_KEY`, and `WEBHOOK_SECRET` are
  hard-required — add whichever one the error names and redeploy. The
  others (`FORWARD_TO_EMAIL`, `CRON_SECRET`, `ADMIN_TELEGRAM_ID`, `DOMAIN`)
  are optional and just disable one feature each until set.
- **Bot is slow to respond the first time**: Render Free sleeps your
  service after ~15 minutes of no traffic and takes 30–60 seconds to wake
  up on the next request. Setting up cron-job.org (step P) fixes this as
  a side effect, since it pings the service regularly for a real purpose
  (auto-OTP checks) rather than as an artificial keep-alive hack.
- **"Create Email" asks you to set `FORWARD_TO_EMAIL`**: expected — add
  that variable (step J) and redeploy.
- **"Get OTP" / auto-push says no OTP found, but you know mail arrived**:
  the code might only be in the email body, not the subject — see the
  "known limitation" note at the top of this file.
- **cron-job.org shows failed executions**: double check the URL in step P
  — the `token` query value must exactly match `CRON_SECRET` in Render,
  and the URL must be your real `.onrender.com` address.
- **429 / rate limit messages**: the Free InboxMail plan allows 100
  requests/hour — the bot already retries with backoff and tells the user
  to wait, this isn't an error in the code.

---

## Project structure

```
telegram-temp-mail/
├── app/
│   ├── main.py          FastAPI app, webhook + cron endpoints, startup/shutdown
│   ├── bot.py            Registers all Telegram handlers
│   ├── config.py         Loads all settings from environment variables
│   ├── cron.py            Auto-OTP polling logic (called by cron-job.org)
│   ├── database.py       SQLite: users, aliases, stats, seen-message tracking
│   ├── inboxmail.py       InboxMail API client (retry/backoff/rate-limit)
│   ├── mail_lookup.py     Shared OTP-in-message lookup (subject + body fallback)
│   ├── handlers/          start, email, otp, admin, help
│   └── utils/             otp extraction, formatting, security, keyboards
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
upgrade path is durable storage (mount it and
point `DATABASE_PATH` at a file inside it) — this is optional and not
required for the bot to work correctly.

## Free vs Pro (per the InboxMail docs)

- **Free-compatible**: aliases, sending mail, reading logs, everything this bot uses.
- **Pro only** (per the docs' own labels): creating/editing/deleting *domains*
  via the API, and **Webhooks**. Since Webhooks aren't available on Free,
  this bot checks mail only when a user taps a manual check button. If you upgrade later, a real Webhooks integration would remove
  that delay entirely — that's a different `POST /telegram-notify`-style
  endpoint, not a small tweak to `cron.py`.

