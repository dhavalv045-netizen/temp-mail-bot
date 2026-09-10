"""
InboxMail API client.

Confirmed via live "Try it out" testing in your Swagger docs
(app.useinbox.email/developer/docs) on 2026-09-09:

  Auth:      Authorization: Bearer <api_key>            (header, never in URL)
  Base URL:  https://api.useinbox.email
  Rate limits (Free plan): 100 req/hour, 500 req/day
              Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset

  Response envelope (confirmed on POST /api/v1/aliases, both success and
  error cases) — ALL endpoints appear to wrap responses like this:
    Success: {"success": true,  "data": {...actual payload...}}
    Error:   {"success": false, "error": {"code": "...", "message": "..."}}
  `_request()` below unwraps this automatically, so every method in this
  class returns the *inner* payload directly, and raises InboxMailError
  (with the real `error.message` in the logs) on any failure.

  ✅ CONFIRMED: POST /api/v1/aliases
    Request body: {"domain_id": "<uuid>", "prefix": "contact",
                    "destinations": ["personal@gmail.com"], "rule_type": "fixed"}
    Response data: {"id", "domain_id", "prefix", "destinations", "rule_type",
                     "status", "created_at", "updated_at"}
    Note: there's no "email"/"address" field — the alias's full address is
    just `prefix + "@" + <your domain>`, which we build ourselves.

  ⚠️ STILL OPEN — see the README's "⚠️ Before you deploy" section:
  `destinations` is a REQUIRED array of real email addresses to forward
  incoming mail to. This means aliases are forward-only by design — it's
  not yet confirmed whether GET /api/v1/aliases/{id}/logs *also* gives us
  the full email content to show in Telegram, or only forwarding metadata.
  This decides the whole inbox/OTP architecture, so nothing alias-logs
  related is wired up with guessed fields yet — see get_alias_logs() below.

  Endpoint map (paths confirmed from the Swagger nav):
    Domains:  GET/POST /api/v1/domains, GET/PUT/DELETE /api/v1/domains/{id}, POST .../verify
    Aliases:  GET/POST /api/v1/aliases, GET/PUT/DELETE /api/v1/aliases/{id}, GET .../logs
    Emails:   POST /api/v1/emails/send (✅ confirmed separately), GET /api/v1/emails,
              GET /api/v1/emails/{id}, GET .../events, POST .../verify
"""

import asyncio
import logging
import secrets
from typing import Any

import httpx

from app.config import (
    INBOXMAIL_API_KEY,
    INBOXMAIL_BASE_URL,
    INBOXMAIL_MAX_RETRIES,
    INBOXMAIL_TIMEOUT_SECONDS,
    DOMAIN,
)

logger = logging.getLogger("tempmail.inboxmail")


def pick_field(data: dict, *keys: str, default=None):
    """Try several possible field names defensively where a schema isn't 100% confirmed."""
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return default


class InboxMailError(Exception):
    """Raised for any InboxMail API failure the caller should show a friendly message for."""


class InboxMailRateLimited(InboxMailError):
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limited, retry after {retry_after:.0f}s")


class InboxMailClient:
    def __init__(self) -> None:
        self._headers = {
            "Authorization": f"Bearer {INBOXMAIL_API_KEY}",
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(
            base_url=INBOXMAIL_BASE_URL,
            headers=self._headers,
            timeout=INBOXMAIL_TIMEOUT_SECONDS,
        )
        self._domain_id_cache: str | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Core request wrapper: timeout + retry + exponential backoff + 429
    # + confirmed {"success","data"/"error"} envelope unwrapping
    # ------------------------------------------------------------------
    async def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, INBOXMAIL_MAX_RETRIES + 1):
            try:
                resp = await self._client.request(method, path, json=json, params=params)
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("InboxMail timeout (attempt %s/%s) on %s %s",
                                attempt, INBOXMAIL_MAX_RETRIES, method, path)
                await asyncio.sleep(2 ** attempt)
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("InboxMail network error (attempt %s/%s) on %s %s: %s",
                                attempt, INBOXMAIL_MAX_RETRIES, method, path, exc.__class__.__name__)
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                logger.warning("InboxMail 429 rate limited on %s %s, retry_after=%s",
                                method, path, retry_after)
                if attempt == INBOXMAIL_MAX_RETRIES:
                    raise InboxMailRateLimited(retry_after)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                logger.warning("InboxMail %s on %s %s (attempt %s/%s)",
                                resp.status_code, method, path, attempt, INBOXMAIL_MAX_RETRIES)
                await asyncio.sleep(2 ** attempt)
                continue

            try:
                body = resp.json() if resp.content else {}
            except ValueError as exc:
                logger.error("InboxMail returned non-JSON body on %s %s", method, path)
                raise InboxMailError("InboxMail returned an unexpected response") from exc

            if resp.status_code >= 400:
                # Confirmed envelope: {"success": false, "error": {"code","message"}}
                err = body.get("error", {}) if isinstance(body, dict) else {}
                msg = err.get("message", f"HTTP {resp.status_code}")
                code = err.get("code", "UNKNOWN")
                logger.error("InboxMail %s error on %s %s | %s: %s",
                              resp.status_code, method, path, code, msg)
                raise InboxMailError(msg)

            # Success: unwrap the confirmed {"success": true, "data": ...} envelope.
            if isinstance(body, dict) and "data" in body:
                return body["data"]
            return body

        logger.error("InboxMail request failed after %s attempts: %s %s",
                      INBOXMAIL_MAX_RETRIES, method, path)
        raise InboxMailError("InboxMail is temporarily unreachable") from last_exc

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------
    async def list_domains(self) -> list[dict]:
        """GET /api/v1/domains — endpoint confirmed; exact list-item field
        names not yet screenshotted, so this defensively unwraps a few
        likely shapes rather than assuming one."""
        data = await self._request("GET", "/api/v1/domains")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("domains", "items", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    async def resolve_domain_id(self, domain: str = DOMAIN) -> str:
        """Looks up the domain_id for `domain` (defaults to your configured
        DOMAIN) and caches it for the process lifetime — aliases need this
        id, not the domain name string."""
        if self._domain_id_cache:
            return self._domain_id_cache
        domains = await self.list_domains()
        for d in domains:
            name = pick_field(d, "domain", "name", "hostname", "domain_name")
            if name == domain:
                domain_id = pick_field(d, "id", "domain_id")
                if domain_id:
                    self._domain_id_cache = domain_id
                    return domain_id
        raise InboxMailError(f"Domain '{domain}' not found on this InboxMail account")

    # ------------------------------------------------------------------
    # Aliases
    # ------------------------------------------------------------------
    async def create_alias(self, destinations: list[str], prefix: str | None = None) -> dict:
        """
        POST /api/v1/aliases — ✅ CONFIRMED request/response schema.

        `destinations` (required by InboxMail): real email address(es) the
        incoming mail actually forwards to. `prefix` is the local-part
        before the @ — random one generated if not given.
        """
        domain_id = await self.resolve_domain_id()
        payload = {
            "domain_id": domain_id,
            "prefix": prefix or secrets.token_hex(4),
            "destinations": destinations,
            "rule_type": "fixed",
        }
        return await self._request("POST", "/api/v1/aliases", json=payload)

    async def list_aliases(self) -> list[dict]:
        """GET /api/v1/aliases — endpoint confirmed, list-item shape not screenshotted yet."""
        data = await self._request("GET", "/api/v1/aliases")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("aliases", "items", "results"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    async def get_alias(self, alias_id: str) -> dict:
        """GET /api/v1/aliases/{id}"""
        return await self._request("GET", f"/api/v1/aliases/{alias_id}")

    async def delete_alias(self, alias_id: str) -> dict:
        """DELETE /api/v1/aliases/{id} — endpoint confirmed."""
        return await self._request("DELETE", f"/api/v1/aliases/{alias_id}")

    async def get_alias_logs(self, alias_id: str) -> list[dict]:
        """
        GET /api/v1/aliases/{id}/logs

        ⚠️ NOT YET WIRED UP. Since aliases forward to real `destinations`
        (confirmed above), it's not yet confirmed whether these logs also
        include the full email body/subject/sender for us to show in
        Telegram, or just forwarding metadata (delivered/bounced, timestamp).
        This decides the inbox + OTP feature's whole design — see the
        README for what screenshot finishes this.
        """
        raise NotImplementedError(
            "get_alias_logs: response schema not yet confirmed — see the ⚠️ note above"
        )

    # ------------------------------------------------------------------
    # Emails
    # ------------------------------------------------------------------
    async def send_email(
        self,
        from_alias_id: str,
        from_name: str,
        to: list[str],
        subject: str,
        text_body: str,
        html_body: str,
    ) -> dict:
        """
        POST /api/v1/emails/send  — ✅ CONFIRMED schema (from your working
        example / the docs' "Sending an Email" page).
        """
        payload = {
            "from_alias_id": from_alias_id,
            "from_name": from_name,
            "to": to,
            "subject": subject,
            "text_body": text_body,
            "html_body": html_body,
        }
        return await self._request("POST", "/api/v1/emails/send", json=payload)

    async def get_email(self, email_id: str) -> dict:
        """GET /api/v1/emails/{id} — ⚠️ full response shape (body fields) not yet confirmed."""
        return await self._request("GET", f"/api/v1/emails/{email_id}")


# Single shared client instance for the whole app.
client = InboxMailClient()

