import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('MAIL_BACKEND', 'inboxmail')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '123456:test')
os.environ.setdefault('INBOXMAIL_API_KEY', 'test')
os.environ.setdefault('WEBHOOK_SECRET', 'test')
os.environ.setdefault('CRON_SECRET', 'test-cron')
os.environ['DATABASE_PATH'] = ':memory:'

import httpx
from app import database, inboxmail
from app.handlers import email, batch
from app.mail_lookup import find_otp_in_message

class CloudflareTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if database._conn:
            database._conn.close()
        database._conn = None
        database.init_db()
        await database.ensure_user(1, 'tester')

    async def test_worker_url_auth_and_no_forward_destination(self):
        def handler(req):
            self.assertEqual(req.url.host, 'mail.example.workers.dev')
            self.assertEqual(req.headers['authorization'], 'Bearer ' + 'x'*64)
            if req.url.path.endswith('domains'):
                return httpx.Response(200, json={'data': [{'domain': inboxmail.DOMAIN, 'id': inboxmail.DOMAIN}]})
            return httpx.Response(201, json={'data': {'id': '12345678', 'prefix': '12345678'}})
        with patch.multiple(inboxmail, MAIL_BACKEND='cloudflare', CLOUDFLARE_MAIL_URL='https://mail.example.workers.dev', CLOUDFLARE_MAIL_TOKEN='x'*64):
            client = inboxmail.InboxMailClient()
        await client._client.aclose()
        client._client = httpx.AsyncClient(base_url='https://mail.example.workers.dev', headers=client._headers, transport=httpx.MockTransport(handler))
        self.assertEqual((await client.create_alias([]))['id'], '12345678')
        await client.aclose()

    async def test_inline_html_otp_needs_no_detail_request(self):
        with patch.object(inboxmail.client, 'get_email', new_callable=AsyncMock) as detail:
            self.assertEqual(await find_otp_in_message({'subject': 'Verify', 'html_body': '<p>Code: <b>654321</b></p>'}), '654321')
            detail.assert_not_awaited()

    async def test_create_and_batch_work_without_forwarding(self):
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        message = SimpleNamespace(reply_text=AsyncMock())
        message.reply_text.return_value = SimpleNamespace(edit_text=AsyncMock())
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1, username='tester'), effective_message=message)
        with patch.object(email, 'MAIL_BACKEND', 'cloudflare'), patch.object(email, 'FORWARD_TO_EMAIL', ''), patch.object(inboxmail.client, 'create_alias', new_callable=AsyncMock, return_value={'id':'12345678','prefix':'12345678'}) as create:
            await email.create_email_callback(update, None)
            create.assert_awaited_once()
        with patch.object(batch, 'MAIL_BACKEND', 'cloudflare'), patch.object(batch, 'FORWARD_TO_EMAIL', ''), patch.object(inboxmail.client, 'create_alias', new_callable=AsyncMock, return_value={'id':'87654321','prefix':'87654321'}) as create:
            await batch.gen_command(update, SimpleNamespace(args=['1']))
            create.assert_awaited_once()

    async def test_delete_all_keeps_failed_addresses(self):
        for alias in ['ok', 'failed']:
            await database.add_alias(1, alias, alias+'@example.test')
        query = SimpleNamespace(answer=AsyncMock(), edit_message_text=AsyncMock())
        update = SimpleNamespace(callback_query=query, effective_user=SimpleNamespace(id=1))
        with patch.object(inboxmail.client, 'delete_alias', new_callable=AsyncMock, side_effect=[None, inboxmail.InboxMailError('offline')]):
            await email.delete_all_callback(update, None)
        remaining = await database.list_aliases(1)
        self.assertEqual(len(remaining), 1)
        self.assertIn('remain in your list', query.edit_message_text.call_args.args[0])
