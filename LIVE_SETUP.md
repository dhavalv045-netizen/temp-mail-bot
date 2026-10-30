# /gen live email lists

This update is based on the uploaded temp-mail-bot-main.zip plus the missing OTP/help modules supplied in chat. It has not been pushed to GitHub or deployed.

Upload these changed/new files to the matching paths in GitHub:
- app/bulk.py
- app/bot.py
- app/main.py
- app/cron.py
- app/utils/otp.py
- app/handlers/help.py
- app/config.py
- render.yaml
- .env.example (example only; never upload your real .env)

Deploy latest commit on Render. Existing environment secrets stay in Render.

Commands: /gen 4, /gen 1, /gen 10. Private chats only. Each command creates one new list and watches it for one hour. Codes are updated in-place; emails and codes use Telegram monospace formatting; no inline buttons. Batch emails are excluded from the legacy cron sender notifications. Legacy single-email behavior is unchanged. A failed partial creation retains successfully created emails.

Optional Render variables:
- LIVE_POLL_SECONDS=90 (default; delay between polling individual addresses globally)
- LIVE_WATCH_SECONDS=3600 (default one-hour monitoring)

For faster refresh, LIVE_POLL_SECONDS=10 polls one address every 10 seconds: four addresses need about 40 seconds per round, plus API latency. Only use a fast interval when your InboxMail API quota supports it. Ten seconds permits about 360 log requests/hour, plus alias creation and full-body lookups. There is no guaranteed instant push. More active addresses mean longer rounds. Provider 429 responses trigger backoff; legacy cron/manual API calls share the same provider quota.

No external cron is needed for /gen lists while the process is running. Render Free sleeping pauses the worker; waking resumes it only if its SQLite data survives. Render Free does not preserve SQLite across restarts/deployments. For reliable operation use an always-running paid service with a persistent disk and DATABASE_PATH pointing inside that disk. Existing /cron/check-otp can continue for legacy single aliases.

OTP extraction supports 4–8 digit numeric codes near a verification/code keyword. Full email-body retrieval is best effort in the original integration; if the provider exposes only the subject and the OTP exists only in the body, it cannot reliably be extracted. No sender or subject is displayed in a batch list.

Validation: local tests mock InboxMail and Telegram; no live API credentials used. Deployment and real message delivery must be tested in your account.
