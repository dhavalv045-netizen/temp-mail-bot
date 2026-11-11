"""Mail backend adapter.

Cloudflare is the default; cloudflare/src/index.js implements the same
small response contract used by the handlers. MAIL_BACKEND=inboxmail is
retained for rollback. Historical class names are compatibility names.
"""

import asyncio
import logging
import secrets
from typing import Any

import httpx

from app.config import (
    MAIL_BACKEND, CLOUDFLARE_MAIL_URL, CLOUDFLARE_MAIL_TOKEN,
    INBOXMAIL_API_KEY,
    INBOXMAIL_BASE_URL,
    INBOXMAIL_MAX_RETRIES,
    INBOXMAIL_TIMEOUT_SECONDS,
    DOMAIN,
)

logger = logging.getLogger("tempmail.mail_backend")


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
            "Authorization": f"Bearer {CLOUDFLARE_MAIL_TOKEN if MAIL_BACKEND == 'cloudflare' else INBOXMAIL_API_KEY}",
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(
            base_url=CLOUDFLARE_MAIL_URL if MAIL_BACKEND == "cloudflare" else INBOXMAIL_BASE_URL,
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
                logger.warning("Mail backend timeout (attempt %s/%s) on %s %s",
                                attempt, INBOXMAIL_MAX_RETRIES, method, path)
                await asyncio.sleep(2 ** attempt)
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                logger.warning("Mail backend network error (attempt %s/%s) on %s %s: %s",
                                attempt, INBOXMAIL_MAX_RETRIES, method, path, exc.__class__.__name__)
                await asyncio.sleep(2 ** attempt)
                continue

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", 2 ** attempt))
                logger.warning("Mail backend 429 rate limited on %s %s, retry_after=%s",
                                method, path, retry_after)
                if attempt == INBOXMAIL_MAX_RETRIES:
                    raise InboxMailRateLimited(retry_after)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                logger.warning("Mail backend %s on %s %s (attempt %s/%s)",
                                resp.status_code, method, path, attempt, INBOXMAIL_MAX_RETRIES)
                await asyncio.sleep(2 ** attempt)
                continue

            try:
                body = resp.json() if resp.content else {}
            except ValueError as exc:
                logger.error("Mail backend returned non-JSON body on %s %s", method, path)
                raise InboxMailError("Mail backend returned an unexpected response") from exc

            if resp.status_code >= 400:
                # Confirmed envelope: {"success": false, "error": {"code","message"}}
                err = body.get("error", {}) if isinstance(body, dict) else {}
                msg = err.get("message", f"HTTP {resp.status_code}")
                code = err.get("code", "UNKNOWN")
                logger.error("Mail backend %s error on %s %s | %s: %s",
                              resp.status_code, method, path, code, msg)
                raise InboxMailError(msg)

            # Success: unwrap the confirmed {"success": true, "data": ...} envelope.
            if isinstance(body, dict) and "data" in body:
                return body["data"]
            return body

        logger.error("Mail backend request failed after %s attempts: %s %s",
                      INBOXMAIL_MAX_RETRIES, method, path)
        raise InboxMailError("Mail backend is temporarily unreachable") from last_exc

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
            "prefix": prefix or secrets.token_hex(12),
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

    async def get_alias_logs(self, alias_id: str, *, limit: int = 20) -> list[dict]:
        """
        GET /api/v1/aliases/{id}/logs — ✅ CONFIRMED via live docs testing.

        Response: {"success": true, "data": {"logs": [{"id", "domain_id",
        "alias_id", "sender", "recipient", "subject", "status", "direction",
        "s3_message_id", "has_attachments", "size_bytes", "error_message",
        "created_at"}, ...]}}

        Note: NO body/content field here — only metadata + subject. Filters
        to inbound mail only (direction=inbound) since outbound is mail the
        alias itself sent, not received.
        """
        data = await self._request(
            "GET", f"/api/v1/aliases/{alias_id}/logs",
            params={"direction": "inbound", "limit": limit},
        )
        if isinstance(data, dict) and "logs" in data:
            return data["logs"]
        if isinstance(data, list):
            return data
        return []

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

