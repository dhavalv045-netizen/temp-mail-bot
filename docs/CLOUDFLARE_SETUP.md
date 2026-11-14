# Cloudflare backend setup — Hinglish guide

Bot Render par hi chalega. Incoming email Cloudflare Email Routing → Worker → D1 mein save hoga. Bot Worker API se mail/OTP read karega, so Render asleep ho tab bhi mail receive ho sakta hai.

Same commands/buttons: private access key, /start, /gen 1–10, Check Mail, Create Email, My Emails, Get OTP, Delete, Delete All, /stats, /admin, /users, /broadcast, /health. Existing manual checking behaviour stays: cron endpoint is a health check, not automatic OTP delivery. Gmail forwarding is no longer required. Sending outbound emails is not implemented by this backend (the current bot has no send-email command).

## 1. Domain ready karo

1. Cloudflare account mein `accounthub.live` add karo (Free plan). Agar dusra domain use karna hai, Worker aur Render dono mein same domain set karo.
2. Agar Cloudflare DNS already active nahi hai, existing DNS records review/copy karo, phir domain registrar mein Cloudflare ke assigned nameservers set karo. Website ke existing A/CNAME records preserve karo. Domain status Active hone do.
3. Email Routing ke MX changes abhi last step tak hold karo: pehle Worker deploy karenge. MX cutover ke baad incoming mail InboxMail ki jagah Cloudflare par aayega; old mailbox contents migrate nahi honge.

## 2. PC par Worker install karo

Node.js 22 LTS or newer aur Git install hone chahiye. Is PR ko main mein merge karne ke baad terminal mein:

```sh
git clone https://github.com/dhavalv045-netizen/temp-mail-bot.git
cd temp-mail-bot/cloudflare
npm ci
npx wrangler login
npx wrangler d1 create temp-mail
```

Browser login mein apna Cloudflare account authorize karo. Last command se `database_id` milega. `cloudflare/wrangler.toml` mein `REPLACE_WITH_D1_DATABASE_ID` replace karo. Binding name **DB** hi rakho, database_name **temp-mail**. `[vars]` ke DOMAIN ko apne domain se match karo.

Then same `cloudflare` folder mein:

```sh
npx wrangler d1 execute temp-mail --remote --file=schema.sql
npx wrangler secret put BACKEND_TOKEN
```

Secret prompt mein password manager se generated **64-character random string** paste karo. Isi exact value ko baad mein Render ke `CLOUDFLARE_MAIL_TOKEN` mein set karna hai. Ye tumhara private shared backend secret hai, Cloudflare API token nahi. GitHub files/chat mein secret paste mat karo.

```sh
npm run deploy
```

Deployment output se `https://temp-mail-backend.YOUR-SUBDOMAIN.workers.dev` URL copy karo. Dashboard mein Worker ke Settings → Bindings mein `DB` binding aur Variables/Secrets mein `DOMAIN`, `BACKEND_TOKEN` verify karo. Root URL ko browser mein open karne par Unauthorized expected hai: API private hai.

## 3. Render environment update karo

Existing service → Environment mein:

| Variable | Value / action |
|---|---|
| `MAIL_BACKEND` | `cloudflare` |
| `CLOUDFLARE_MAIL_URL` | Deployed Worker HTTPS origin; no `/api/v1` path |
| `CLOUDFLARE_MAIL_TOKEN` | Exact same secret as Worker `BACKEND_TOKEN` |
| `DOMAIN` | `accounthub.live` (same as Worker DOMAIN) |
| `TELEGRAM_BOT_TOKEN` | Existing bot token keep karo |
| `BOT_ACCESS_KEY` | Apna private bot access password; existing value keep karo |
| `ADMIN_TELEGRAM_ID` | Apna numeric Telegram ID; existing value keep karo |
| `WEBHOOK_SECRET` | Existing value keep karo; letters/numbers/underscore/hyphen only |
| `CRON_SECRET` | Existing value keep karo if using health-check scheduler |
| `RENDER_EXTERNAL_URL` | Render normally sets automatically; if manually set, correct service URL rakho |
| `INBOXMAIL_API_KEY` | Cloudflare mode mein unused; rollback complete hone tak optional keep |
| `INBOXMAIL_BASE_URL` | Cloudflare mode mein unused |
| `FORWARD_TO_EMAIL` | Cloudflare mode mein unused; remove optional |

Build command unchanged: `pip install -r requirements.txt`

Start command unchanged: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

Root Directory stays repository root, NOT `cloudflare`. Save environment, deploy the merged commit. Existing manually configured Render services do not automatically pick up every `render.yaml` change: set the variables yourself.

Telegram mein access key bhejo if requested, phir `/health` (admin) and `/gen 1`. Health reachable hona Worker secret, domain-list endpoint and D1 schema verify karta hai; DNS delivery ka proof nahi hai.

## 4. Email Routing enable karke Worker connect karo

Cloudflare dashboard → Email Service / Email Routing → select/onboard domain. UI account ke hisaab se domain → Email → Email Routing ke under bhi ho sakti hai.

1. Cloudflare ke shown MX/TXT records configure karo. Existing InboxMail MX records ko Cloudflare routing ke records se replace karna hoga. Dono providers ke MX mix mat karo. Other website DNS records untouched rakho. Existing SPF ho to wizard ke guidance ke hisaab se update karo; duplicate SPF records mat add karo.
2. Routing Rules → Catch-all → Enable.
3. Action **Send to a Worker**, Worker **temp-mail-backend** choose karo and Save.
4. Existing explicit rules catch-all se pehle match ho sakte hain. Bot addresses par conflicting forwarding/drop rules na hon. Important non-bot mailboxes ke liye separate explicit rules preserve/configure karo.
5. Agar wizard destination verification maange, apna real email verify karo; final catch-all action Worker hi rakho.

Worker sirf bot-created addresses accept karta hai. Random unknown/deleted addresses reject honge. Har generated address ke liye individual Cloudflare routing rule create nahi hota.

## 5. Live test

1. Telegram `/gen 2` se **new** addresses generate karo.
2. Apne real email se generated address ko message bhejo: subject `Verification code 123456`; next test mein subject `Verify account`, body `Your code is 654321`.
3. Telegram **Check Mail** ya **Get OTP** tap karo. Code appear hona chahiye.
4. My Emails → Delete ek test address; us address ko new mail send karne par rejection expected hai.
5. Remaining address par new email receive check karo. DNS propagation pending ho to Cloudflare routing activity inspect karo.

## Existing addresses and Render storage

Old InboxMail addresses/messages automatically migrate nahi hote. Cloudflare par new addresses generate karo. For rollback: old MX records restore karo, `MAIL_BACKEND=inboxmail`, original API key/domain/forwarding config restore karo and redeploy. Existing remote InboxMail data is not deleted by this migration.

Mail aliases/bodies are durable in Cloudflare D1. **Telegram user ownership, authorization, batches and stats still use the original SQLite database on Render.** Render Free redeploy/restart may lose that database, making old bot lists/batches unavailable even though mail still exists in D1. This is an existing limitation, not full persistence. Re-enter access key and generate new addresses if it happens. For durable bot history, use a Render persistent disk mounted at `/var/data` with `DATABASE_PATH=/var/data/tempmail.db` (paid option), or implement a separate persistent bot-state database before relying on history. Do not set that path on Free without a mounted writable disk. Keep one bot instance/one Uvicorn worker.

## Limits and privacy

No hardcoded two-address quota. Cloudflare Workers/D1 free plan quotas still apply; this is not unlimited infrastructure. Domain registration/renewal remains separate. Worker stores only latest 20 messages per address; scheduled cleanup deletes messages older than 7 days daily. Max incoming raw email is 1 MiB; text/HTML stored up to 32,768 characters each; attachments not saved. Aliases remain until deleted. Large/complex MIME emails may exceed Workers Free CPU limits; check Worker logs if delivery fails. Mail filtering by senders/Cloudflare can also affect delivery.

Backend token grants access to all mail in this dedicated Worker. Use a dedicated D1 database and keep token private. Bot continues its existing per-user ownership checks. No public mail-reading or public mailbox-creation endpoint is provided.

## Troubleshooting

- `/health` unreachable: check Worker URL, matching shared token, D1 `DB` binding, schema initialization and Worker logs.
- Create works but mail absent: check MX activation, catch-all action, DOMAIN match and exact new generated recipient. HTTP health does not check MX.
- Browser Worker URL says Unauthorized: expected without bearer authentication.
- Access not configured: set `BOT_ACCESS_KEY` in Render; send it in private bot chat.
- Old email unavailable: generate a new Cloudflare address; old provider IDs aren't migrated.
- Bot no response after secret change: redeploy; startup now always refreshes Telegram webhook secret.
- Worker limits/errors: inspect Cloudflare Worker logs, D1 usage, email routing activity. Never publish tokens or full private email content in logs/screenshots.

## Verification commands

From repo root: `python -m unittest discover -s tests -v`

From cloudflare folder: `npm test` and `npm run build` (deployment dry run).

Official references:
- https://developers.cloudflare.com/email-service/get-started/route-emails/
- https://developers.cloudflare.com/email-service/api/route-emails/email-handler/
- https://developers.cloudflare.com/d1/get-started/
- https://developers.cloudflare.com/email-service/platform/pricing/
- https://developers.cloudflare.com/workers/platform/limits/
