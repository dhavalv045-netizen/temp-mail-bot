import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('MAIL_BACKEND', 'inboxmail')
os.environ.setdefault('TELEGRAM_BOT_TOKEN', '123456:test-token')
os.environ.setdefault('INBOXMAIL_API_KEY', 'test-key')
os.environ.setdefault('WEBHOOK_SECRET', 'test-secret')
os.environ.setdefault('CRON_SECRET', 'test-cron')
os.environ['DATABASE_PATH'] = ':memory:'

from telegram.ext import ApplicationHandlerStop
from app import database
from app.handlers import batch
from app.inboxmail import InboxMailError, InboxMailRateLimited


def update(user_id=1, callback=None, text='/gen 4'):
    message = SimpleNamespace(text=text, reply_text=AsyncMock())
    message.reply_text.return_value = SimpleNamespace(edit_text=AsyncMock())
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, username='tester'),
                           effective_chat=SimpleNamespace(type='private'),
                           effective_message=message, callback_query=callback)


class BatchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        if database._conn:
            database._conn.close()
        database._conn = None
        database.init_db()
        batch._auth_attempts.clear()
        batch._generating.clear()
        batch._checking.clear()
        await database.ensure_user(1, 'tester')
        await database.authorize_user(1)

    async def make_batch(self):
        await database.create_batch('abcdef0123456789', 1)
        for i in range(4):
            await database.add_alias(1, str(i), f'{i}@example.test')
            await database.add_batch_item('abcdef0123456789', str(i), f'{i}@example.test')

    async def test_access_key_once_and_all_callbacks_blocked(self):
        with self.assertRaises(ApplicationHandlerStop):
            await batch.access_guard(update(2, text='/start'), None)
        with patch.dict(os.environ, {'BOT_ACCESS_KEY': 'test-access-key'}):
            with self.assertRaises(ApplicationHandlerStop):
                await batch.access_guard(update(2, text='wrong'), None)
            self.assertFalse(await database.is_authorized(2))
            batch._auth_attempts.clear()
            with self.assertRaises(ApplicationHandlerStop):
                await batch.access_guard(update(2, text='test-access-key'), None)
        self.assertTrue(await database.is_authorized(2))
        await batch.access_guard(update(2), None)
        q = SimpleNamespace(answer=AsyncMock())
        with self.assertRaises(ApplicationHandlerStop):
            await batch.access_guard(update(3, callback=q), None)
        q.answer.assert_awaited_once()

    async def test_missing_key_fails_closed(self):
        with patch.dict(os.environ, {'BOT_ACCESS_KEY': ''}):
            with self.assertRaises(ApplicationHandlerStop):
                await batch.access_guard(update(7, text='any-key'), None)
        self.assertFalse(await database.is_authorized(7))

    async def test_generation_bounds_and_format(self):
        for arg in [[], ['0'], ['11'], ['-1'], ['abc'], ['4', '5'], ['999999999999999']]:
            with patch.object(batch.client, 'create_alias', new_callable=AsyncMock) as create:
                await batch.gen_command(update(), SimpleNamespace(args=arg))
                create.assert_not_awaited()
        for n in [4, 10]:
            u = update()
            with patch.object(batch, 'FORWARD_TO_EMAIL', 'owner@example.test'), patch.object(
                batch.client, 'create_alias', new_callable=AsyncMock,
                side_effect=[{'id': f'{n}-{i}', 'prefix': f'mail{i}'} for i in range(n)]
            ) as create:
                await batch.gen_command(u, SimpleNamespace(args=[str(n)]))
                self.assertEqual(create.await_count, n)
            call = u.effective_message.reply_text.return_value.edit_text.call_args
            self.assertEqual(call.args[0].count('code -'), n)
            self.assertEqual(call.args[0].count('<code>'), n)
            self.assertEqual(len(call.kwargs['reply_markup'].inline_keyboard), 1)

    async def test_partial_generation_retains_addresses(self):
        u = update()
        with patch.object(batch, 'FORWARD_TO_EMAIL', 'owner@example.test'), patch.object(
            batch.client, 'create_alias', new_callable=AsyncMock,
            side_effect=[{'id': 'one', 'prefix': 'one'}, InboxMailError('failed')]
        ):
            await batch.gen_command(u, SimpleNamespace(args=['4']))
        self.assertIn('Created 1 of 4', u.effective_message.reply_text.return_value.edit_text.call_args.args[0])
        self.assertEqual(len(await database.list_aliases(1)), 1)

    async def test_check_ownership_cooldown_and_cached_codes(self):
        await self.make_batch()
        q = SimpleNamespace(data='batch:check:abcdef0123456789', answer=AsyncMock(), edit_message_text=AsyncMock())
        with patch.object(batch.client, 'get_alias_logs', new_callable=AsyncMock, return_value=[{'subject': 'Your code is 123456'}]) as logs:
            await batch.check_batch_callback(update(2, callback=q), None)
            logs.assert_not_awaited()
            await batch.check_batch_callback(update(callback=q), None)
            self.assertEqual(logs.await_count, 4)
            text = q.edit_message_text.call_args.args[0]
            self.assertEqual(text.count('<code>123456</code>'), 4)
            self.assertNotIn('sender', text)
            await batch.check_batch_callback(update(callback=q), None)
            self.assertEqual(logs.await_count, 4)
            database._get_conn().execute('UPDATE authorized_users SET last_mail_check=0')
            database._get_conn().commit()
            await batch.check_batch_callback(update(callback=q), None)
            self.assertEqual(logs.await_count, 4)

    async def test_deleted_alias_and_rate_limit(self):
        await self.make_batch()
        await database.delete_alias(1, '0')
        q = SimpleNamespace(data='batch:check:abcdef0123456789', answer=AsyncMock(), edit_message_text=AsyncMock())
        with patch.object(batch.client, 'get_alias_logs', new_callable=AsyncMock, side_effect=InboxMailRateLimited(60)) as logs:
            await batch.check_batch_callback(update(callback=q), None)
            logs.assert_awaited_once_with('1')
            self.assertIn('rate limited', q.edit_message_text.call_args.args[0])
        self.assertFalse(batch._checking)

    async def test_legacy_cron_makes_no_mail_requests(self):
        from app.main import cron_check_otp
        with patch.object(batch.client, 'get_alias_logs', new_callable=AsyncMock) as logs:
            result = await cron_check_otp(os.environ['CRON_SECRET'])
            self.assertEqual(result['checked'], 0)
            logs.assert_not_awaited()

    async def test_authorization_and_batches_survive_database_reopen(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            database._conn.close()
            database._conn = None
            with patch.object(database, 'DATABASE_PATH', directory + '/state.db'):
                database.init_db()
                await database.authorize_user(1)
                await self.make_batch()
                await database.set_batch_otp('abcdef0123456789', '0', '456789')
                database._conn.close()
                database._conn = None
                database.init_db()
                self.assertTrue(await database.is_authorized(1))
                rows = await database.get_batch_items('abcdef0123456789', 1)
                self.assertEqual(len(rows), 4)
                self.assertEqual(rows[0]['otp'], '456789')
                database._conn.close()
                database._conn = None

    async def test_handler_gate_runs_before_commands(self):
        from app.bot import build_application
        app = build_application()
        self.assertEqual(app.handlers[-1][0].callback, batch.access_guard)
        self.assertTrue(any(h.callback == batch.gen_command for h in app.handlers[0]))


if __name__ == '__main__':
    unittest.main()
