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
ITEM_TIMEOUT = 15 * 60
_poll_lock = asyncio.Lock()
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
    conn = database._get_conn()
    columns = {r['name'] for r in conn.execute('PRAGMA table_info(live_items)')}
    if 'watch_started' not in columns:
        conn.execute('ALTER TABLE live_items ADD COLUMN watch_started REAL')
    if 'state' not in columns:
        conn.execute("ALTER TABLE live_items ADD COLUMN state TEXT NOT NULL DEFAULT 'queued'")
    conn.execute("UPDATE live_items SET state='done' WHERE code!=''")
    conn.commit()


def execute(sql, args=()):
    conn = database._get_conn()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur


def render(batch):
    items = execute('SELECT * FROM live_items WHERE batch_id=? ORDER BY id', (batch['id'],)).fetchall()
    lines = []
    for i, row in enumerate(items, 1):
        code = f"<code>{html.escape(row['code'])}</code>" if row['code'] else {'queued': 'Waiting for turn…', 'watching': 'Waiting…', 'timeout': 'No code — 15 min timeout', 'deleted': 'Deleted'}.get(row['state'], 'Waiting…')
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
            (user.id, message.chat_id, message.message_id, 0, 'creating')).lastrowid
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


def advance_queue():
    # A single global queue: older batches first, then top-to-bottom emails.
    # Only a started email has a deadline; queued emails keep their full 15 minutes.
    now = time.time()
    rows = execute("SELECT * FROM live_items WHERE state IN ('queued','watching')").fetchall()
    for row in rows:
        state = None
        owner = execute('SELECT 1 FROM aliases a JOIN live_batches b ON b.id=? WHERE a.alias_id=? AND a.telegram_user_id=b.user_id',
                        (row['batch_id'], row['alias_id'])).fetchone()
        if not owner:
            state = 'deleted'
        elif row['watch_started'] is not None and now >= row['watch_started'] + ITEM_TIMEOUT:
            state = 'timeout'
        if state:
            execute('UPDATE live_items SET state=? WHERE id=?', (state, row['id']))
            execute('UPDATE live_batches SET dirty=1 WHERE id=?', (row['batch_id'],))
    execute("""UPDATE live_batches SET status='completed',dirty=1
        WHERE status IN ('active','partial') AND NOT EXISTS
        (SELECT 1 FROM live_items WHERE batch_id=live_batches.id AND state IN ('queued','watching'))""")


async def poll_one(bot):
    async with _poll_lock:
        advance_queue()
        row = execute("""SELECT i.*, b.user_id FROM live_items i JOIN live_batches b ON b.id=i.batch_id
            WHERE b.status IN ('active','partial') AND i.state IN ('queued','watching') AND i.code=''
            ORDER BY b.id, i.id LIMIT 1""").fetchone()
        if not row:
            return
        started = row['watch_started']
        if started is None:
            started = time.time()
            execute("UPDATE live_items SET state='watching',watch_started=? WHERE id=?", (started, row['id']))
            execute('UPDATE live_batches SET dirty=1 WHERE id=?', (row['batch_id'],))
        execute('UPDATE live_items SET checked=? WHERE id=?', (time.time(), row['id']))
        remaining = started + ITEM_TIMEOUT - time.time()
        if remaining <= 0:
            advance_queue()
            return
        try:
            # Bound stalled network calls without ever polling another email concurrently.
            await asyncio.wait_for(check_item(row), timeout=min(30, remaining))
        except asyncio.TimeoutError:
            log.warning('Current email check timed out; retrying on next interval')
        advance_queue()


async def check_item(row):
    messages = await client.get_alias_logs(row['alias_id'])
    messages = sorted(messages, key=lambda m: str(pick_field(m, 'created_at', 'received_at', default='')))
    for msg in messages:
        key = str(pick_field(msg, 'id', 'message_id', 'email_id', default='')) or repr((msg.get('subject'), msg.get('created_at')))
        code = await find_otp_in_message(msg)
        if code:
            # First successful code is final; this address is never selected again.
            execute("UPDATE live_items SET code=?,state='done' WHERE id=?", (str(code), row['id']))
            execute('UPDATE live_batches SET dirty=1 WHERE id=?', (row['batch_id'],))
            await database.mark_messages_seen(row['alias_id'], [key])
            await database.bump_stats(row['user_id'], emails=1, otps=1)
            return


async def worker(bot):
    next_poll = 0.0
    while True:
        try:
            advance_queue()
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
