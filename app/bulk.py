"""Persistent /gen batches. One worker polls one address per interval."""
import asyncio
import html
import logging
import os
import time
from telegram.error import BadRequest, Forbidden, RetryAfter
from app import database
from app.config import DOMAIN, FORWARD_TO_EMAIL
from app.inboxmail import client, pick_field, InboxMailRateLimited
from app.mail_lookup import find_otp_in_message

log = logging.getLogger(__name__)
INTERVAL = max(5, int(os.getenv('LIVE_POLL_SECONDS', '90')))
TTL = max(300, int(os.getenv('LIVE_WATCH_SECONDS', '3600')))
_generation_lock = asyncio.Lock()


def init():
    database._get_conn().executescript('''
    CREATE TABLE IF NOT EXISTS live_batches (
      id INTEGER PRIMARY KEY, user_id INTEGER, chat_id INTEGER, message_id INTEGER,
      expires REAL, status TEXT, dirty INTEGER DEFAULT 1);
    CREATE TABLE IF NOT EXISTS live_items (
      id INTEGER PRIMARY KEY, batch_id INTEGER, alias_id TEXT UNIQUE,
      email TEXT, code TEXT DEFAULT '', checked REAL DEFAULT 0);
    ''')
    database._get_conn().commit()


def execute(sql, args=()):
    conn = database._get_conn()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur


def render(batch):
    items = execute('SELECT * FROM live_items WHERE batch_id=? ORDER BY id', (batch['id'],)).fetchall()
    lines = []
    for i, row in enumerate(items, 1):
        code = f"<code>{html.escape(row['code'])}</code>" if row['code'] else 'Waiting…'
        lines.append(f"{i}. <code>{html.escape(row['email'])}</code>\ncode - {code}")
    if batch['status'] == 'partial':
        lines.append('Some emails could not be created. Auto-check active.')
    elif batch['status'] == 'expired':
        lines.append('Auto-check ended.')
    elif not items:
        lines.append('No emails created. Please try again.')
    return '\n\n'.join(lines), None



async def publish(bot, batch_id):
    batch = execute('SELECT * FROM live_batches WHERE id=?', (batch_id,)).fetchone()
    text, markup = render(batch)
    try:
        await bot.edit_message_text(chat_id=batch['chat_id'], message_id=batch['message_id'],
                                    text=text, parse_mode='HTML', reply_markup=markup)
    except BadRequest as exc:
        if 'message is not modified' not in str(exc).lower():
            if 'message to edit not found' in str(exc).lower():
                execute("UPDATE live_batches SET status='stopped', dirty=0 WHERE id=?", (batch_id,))
                return
            raise
    except Forbidden:
        execute("UPDATE live_batches SET status='stopped', dirty=0 WHERE id=?", (batch_id,))
        return
    execute('UPDATE live_batches SET dirty=0 WHERE id=?', (batch_id,))


async def gen_command(update, context):
    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text('Use /gen in a private chat with this bot.')
        return
    if len(context.args) != 1 or not context.args[0].isdigit() or not 1 <= int(context.args[0]) <= 10:
        await update.effective_message.reply_text('Use /gen 4 (1–10 emails).')
        return
    if not FORWARD_TO_EMAIL:
        await update.effective_message.reply_text('Set FORWARD_TO_EMAIL in Render first.')
        return
    if _generation_lock.locked():
        await update.effective_message.reply_text('Email generation is in progress. Please try again shortly.')
        return
    async with _generation_lock:
        user = update.effective_user
        await database.ensure_user(user.id, user.username)
        message = await update.effective_message.reply_text('⏳ Generating emails…')
        batch_id = execute('INSERT INTO live_batches(user_id,chat_id,message_id,expires,status) VALUES(?,?,?,?,?)',
            (user.id, message.chat_id, message.message_id, time.time()+TTL, 'creating')).lastrowid
        count = int(context.args[0])
        created = 0
        try:
            for _ in range(count):
                result = await client.create_alias(destinations=[FORWARD_TO_EMAIL])
                alias_id, prefix = pick_field(result, 'id', 'alias_id'), pick_field(result, 'prefix')
                if not alias_id or not prefix:
                    raise ValueError('Alias response missing id/prefix')
                address = f'{prefix}@{DOMAIN}'
                await database.add_alias(user.id, str(alias_id), address)
                execute('INSERT INTO live_items(batch_id,alias_id,email) VALUES(?,?,?)',
                        (batch_id, str(alias_id), address))
                created += 1
        except Exception:
            log.exception('Bulk generation failed after %s aliases', created)
        execute('UPDATE live_batches SET status=?,dirty=1 WHERE id=?',
                ('active' if created == count else 'partial' if created else 'stopped', batch_id))
        try:
            await publish(context.bot, batch_id)
        except Exception:
            log.exception('Batch delivery pending; worker will retry')


async def poll_one(bot):
    row = execute('''SELECT i.*, b.user_id FROM live_items i JOIN live_batches b ON b.id=i.batch_id
        JOIN aliases a ON a.alias_id=i.alias_id AND a.telegram_user_id=b.user_id
        WHERE b.status IN ('active','partial') AND b.expires>?
        ORDER BY i.checked, i.id LIMIT 1''', (time.time(),)).fetchone()
    if not row:
        return
    execute('UPDATE live_items SET checked=? WHERE id=?', (time.time(), row['id']))
    messages = await client.get_alias_logs(row['alias_id'])
    # Sort by provider timestamp; retain all messages for which no code is yet available.
    messages = sorted(messages, key=lambda m: str(pick_field(m, 'created_at', 'received_at', default='')))
    latest = row['code']
    for msg in messages:
        key = str(pick_field(msg, 'id', 'message_id', 'email_id', default='')) or repr((msg.get('subject'), msg.get('created_at')))
        if key not in await database.get_unseen_message_ids(row['alias_id'], [key]):
            continue
        code = await find_otp_in_message(msg)
        if code:
            latest = str(code)
            await database.mark_messages_seen(row['alias_id'], [key])
            await database.bump_stats(row['user_id'], emails=1, otps=1)
    if latest != row['code']:
        execute('UPDATE live_items SET code=? WHERE id=?', (latest, row['id']))
        execute('UPDATE live_batches SET dirty=1 WHERE id=?', (row['batch_id'],))


async def worker(bot):
    next_poll = 0.0
    while True:
        try:
            execute("UPDATE live_batches SET status='expired',dirty=1 WHERE status IN ('active','partial') AND expires<=?", (time.time(),))
            if time.monotonic() >= next_poll:
                next_poll = time.monotonic() + INTERVAL
                await poll_one(bot)
            for row in execute("SELECT id FROM live_batches WHERE dirty=1 AND status!='creating'").fetchall():
                await publish(bot, row['id'])
        except InboxMailRateLimited as exc:
            next_poll = time.monotonic() + max(INTERVAL, exc.retry_after)
            log.warning('Live polling paused for API rate limit')
        except RetryAfter as exc:
            delay = exc.retry_after.total_seconds() if hasattr(exc.retry_after, 'total_seconds') else float(exc.retry_after)
            await asyncio.sleep(delay + 1)
        except Exception:
            log.exception('Live refresh failed; will retry')
        await asyncio.sleep(2)
