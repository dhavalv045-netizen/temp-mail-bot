"""
InboxMail API client.

Confirmed from the docs pages you sent (app.useinbox.email/developer/docs,
captured via your saved .mht files) + https://api.useinbox.email:

  Auth:      Authorization: Bearer <api_key>            (header, never in URL)
  Base URL:  https://api.useinbox.email
  Rate limits (Free plan): 100 req/hour, 500 req/day
              Headers: X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset

  Endpoint map (paths confirmed from the Swagger nav; only emails/send has a
  confirmed full body+response schema — see the ⚠️ blocks below):

    Domains
      GET    /api/v1/domains
      GET    /api/v1/domains/{id}
      POST   /api/v1/domains/{id}/verify

    Aliases
      GET    /api/v1/aliases
      POST   /api/v1/aliases
      GET    /api/v1/aliases/{id}
      PUT    /api/v1/aliases/{id}
      DELETE /api/v1/aliases/{id}
      GET    /api/v1/aliases/{id}/logs      <- how a temp-mail bot reads "inbox"

    Emails
      POST   /api/v1/emails/send             <- CONFIRMED schema below
      GET    /api/v1/emails
      GET    /api/v1/emails/{id}
      GET    /api/v1/emails/{id}/events
      POST   /api/v1/emails/verify

⚠️ NOT YET CONFIRMED: the request body for POST /api/v1/aliases, and the
response shapes for GET /api/v1/aliases, GET /api/v1/aliases/{id}/logs,
and GET /api/v1/emails/{id}. Your Swagger page renders these behind
collapsed accordions that weren't expanded in the .mht files you sent me,
so I have the URLs and methods but not the field names. I did NOT invent
them (per your instructions) — see the docstrings below for exactly what
to copy from the docs UI so these can be finished.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config import (
    INBOXMAIL_API_KEY,
    INBOXMAIL_BASE_URL,
    INBOXMAIL_MAX_RETRIES,
    INBOXMAIL_TIMEOUT_SECONDS,
)

logger = logging.getLogger("tempmail.inboxmail")


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

    async def aclose(self) -> None:
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Core request wrapper: timeout + retry + exponential backoff + 429
    # ------------------------------------------------------------------
    async def _request(
        self, method: str, path: str, *, json: dict | None = None, params: dict | None = None
    ) -> dict:
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

            if resp.status_code >= 400:
                # Do not leak raw body (could contain account info) to end users;
                # log it safely (status + path only) for the operator.
                logger.error("InboxMail %s error on %s %s", resp.status_code, method, path)
                raise InboxMailError(f"InboxMail returned HTTP {resp.status_code}")

            try:
                return resp.json() if resp.content else {}
            except ValueError as exc:
                logger.error("InboxMail returned non-JSON body on %s %s", method, path)
                raise InboxMailError("InboxMail returned an unexpected response") from exc

        logger.error("InboxMail request failed after %s attempts: %s %s",
                      INBOXMAIL_MAX_RETRIES, method, path)
        raise InboxMailError("InboxMail is temporarily unreachable") from last_exc

    # ------------------------------------------------------------------
    # Domains
    # ------------------------------------------------------------------
    async def list_domains(self) -> list[dict]:
        """
        GET /api/v1/domains

        ⚠️ Response field names not yet confirmed. Expand "List all domains"
        in the Swagger docs and check the example response — this method
        currently assumes the payload is a JSON array, or an object with a
        "data"/"domains" list inside it, and tries both. Adjust `_unwrap_list`
        below once you confirm the real shape.
        """
        data = await self._request("GET", "/api/v1/domains")
        return self._unwrap_list(data)

    @staticmethod
    def _unwrap_list(data: Any) -> list[dict]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("data", "domains", "aliases", "items", "results", "logs", "emails"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        return []

    # ------------------------------------------------------------------
    # Aliases  ⚠️ schema not yet confirmed — see module docstring
    # ------------------------------------------------------------------
    async def create_alias(self, domain: str) -> dict:
        """
        POST /api/v1/aliases

        ⚠️ NOT CONFIRMED. To finish this method, open the docs, expand
        "Create a new alias" under Aliases, and copy:
          1. The "Request body schema" (likely needs a domain id and maybe
             a chosen local-part/username — or the API may auto-generate
             a random one if you omit it).
          2. A "201/200 response" example, so we know whether the created
             alias comes back as `id` + `email` or different field names.

        The placeholder payload below is a guess-free minimal attempt using
        the domain string itself; it WILL need adjusting once you confirm
        the schema, or alias creation will fail/behave unexpectedly.
        """
        payload = {"domain": domain}  # TODO: confirm real field name(s)
        return await self._request("POST", "/api/v1/aliases", json=payload)

    async def list_aliases(self) -> list[dict]:
        """GET /api/v1/aliases — ⚠️ response item shape not yet confirmed."""
        data = await self._request("GET", "/api/v1/aliases")
        return self._unwrap_list(data)

    async def get_alias(self, alias_id: str) -> dict:
        """GET /api/v1/aliases/{id}"""
        return await self._request("GET", f"/api/v1/aliases/{alias_id}")

    async def delete_alias(self, alias_id: str) -> dict:
        """DELETE /api/v1/aliases/{id} — endpoint confirmed, response shape not."""
        return await self._request("DELETE", f"/api/v1/aliases/{alias_id}")

    async def get_alias_logs(self, alias_id: str) -> list[dict]:
        """
        GET /api/v1/aliases/{id}/logs

        This is almost certainly how "inbox" (received messages) is read
        for a temp alias. ⚠️ NOT CONFIRMED: whether each log entry includes
        the full email body, or just headers (from/subject/date) plus a
        message id you then fetch separately via GET /api/v1/emails/{id}.
        Expand "Get alias email logs" in the docs and copy a response
        example so `format_inbox()` in utils/formatting.py can be finished.
        """
        data = await self._request("GET", f"/api/v1/aliases/{alias_id}/logs")
        return self._unwrap_list(data)

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
