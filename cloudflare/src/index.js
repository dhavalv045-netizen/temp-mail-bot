import PostalMime from 'postal-mime';

const response = (data, status = 200) => Response.json({success: true, data}, {status, headers: {'Cache-Control': 'no-store'}});
const error = (message, status) => Response.json({success: false, error: {message}}, {status, headers: {'Cache-Control': 'no-store'}});

async function authorized(request, env) {
  if (!env.BACKEND_TOKEN || env.BACKEND_TOKEN.length < 32) return false;
  const actual = request.headers.get('Authorization') || '';
  const digest = async s => new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
  const [a, b] = await Promise.all([digest(actual), digest(`Bearer ${env.BACKEND_TOKEN}`)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

export async function api(request, env) {
  if (!await authorized(request, env)) return error('Unauthorized', 401);
  const url = new URL(request.url), path = url.pathname, method = request.method;
  if (method === 'GET' && path === '/api/v1/domains') {
    await env.DB.prepare('SELECT id FROM aliases LIMIT 1').all();
    return response([{id: env.DOMAIN, domain: env.DOMAIN}]);
  }
  if (method === 'POST' && path === '/api/v1/aliases') {
    if (Number(request.headers.get('content-length') || 0) > 4096) return error('Request too large', 413);
    let body;
    try { body = JSON.parse(await request.text()); } catch { return error('Invalid JSON', 400); }
    if (!body || body.domain_id !== env.DOMAIN || typeof body.prefix !== 'string' || !/^[a-z0-9]{8,32}$/.test(body.prefix)) return error('Invalid domain or prefix', 400);
    // Deterministic ID makes retries safe after an ambiguous network failure.
    const id = body.prefix, created = new Date().toISOString();
    await env.DB.prepare('INSERT OR IGNORE INTO aliases(id,prefix,created_at) VALUES(?,?,?)').bind(id, body.prefix, created).run();
    return response(await env.DB.prepare('SELECT * FROM aliases WHERE id=?').bind(id).first(), 201);
  }
  if (method === 'GET' && path === '/api/v1/aliases') {
    return response({aliases: (await env.DB.prepare('SELECT * FROM aliases ORDER BY created_at DESC LIMIT 1000').all()).results});
  }
  const match = path.match(/^\/api\/v1\/aliases\/([a-z0-9]{8,32})(\/logs)?$/);
  if (match) {
    const id = match[1];
    if (method === 'DELETE' && !match[2]) {
      await env.DB.batch([
        env.DB.prepare('DELETE FROM messages WHERE alias_id=?').bind(id),
        env.DB.prepare('DELETE FROM aliases WHERE id=?').bind(id)
      ]);
      return response({deleted: true});
    }
    if (method === 'GET') {
      const alias = await env.DB.prepare('SELECT * FROM aliases WHERE id=?').bind(id).first();
      if (!alias) return error('Address not found; create a new email after migration', 404);
      if (!match[2]) return response(alias);
      const limit = Math.min(20, Math.max(1, Number.parseInt(url.searchParams.get('limit') || '20', 10) || 20));
      const rows = await env.DB.prepare('SELECT * FROM messages WHERE alias_id=? ORDER BY created_at DESC LIMIT ?').bind(id, limit).all();
      return response({logs: rows.results});
    }
  }
  const email = path.match(/^\/api\/v1\/emails\/([a-f0-9-]{36})$/);
  if (method === 'GET' && email) {
    const row = await env.DB.prepare('SELECT * FROM messages WHERE id=?').bind(email[1]).first();
    return row ? response(row) : error('Message not found', 404);
  }
  return error('Not found', 404);
}

export async function receive(message, env) {
  const address = message.to.toLowerCase();
  const split = address.lastIndexOf('@');
  if (address.slice(split + 1) !== env.DOMAIN || split < 1) return message.setReject('Unknown domain');
  const alias = await env.DB.prepare('SELECT id FROM aliases WHERE prefix=?').bind(address.slice(0, split)).first();
  if (!alias) return message.setReject('Unknown or deleted address');
  // Bound parsing/storage work on the free plan; attachments are not stored.
  if (message.rawSize > 1024 * 1024) return message.setReject('Message exceeds 1 MiB');
  const mail = await PostalMime.parse(message.raw);
  const id = crypto.randomUUID();
  await env.DB.batch([
    env.DB.prepare(`INSERT INTO messages(id,alias_id,sender,recipient,subject,text_body,html_body,created_at)
      SELECT ?,id,?,?,?,?,?,? FROM aliases WHERE id=?`).bind(
        id, message.from, address, (mail.subject || '').slice(0, 1000),
        (mail.text || '').slice(0, 32768), (mail.html || '').slice(0, 32768), new Date().toISOString(), alias.id),
    env.DB.prepare(`DELETE FROM messages WHERE alias_id=? AND id NOT IN
      (SELECT id FROM messages WHERE alias_id=? ORDER BY created_at DESC, rowid DESC LIMIT 20)`).bind(alias.id, alias.id)
  ]);
}

export default {
  async fetch(request, env) {
    try { return await api(request, env); }
    catch { return error('Cloudflare mail backend failed; check Worker configuration and D1', 503); }
  },
  email: receive,
  async scheduled(event, env) {
    // ISO timestamps compare chronologically; retain mail for seven days.
    await env.DB.prepare('DELETE FROM messages WHERE created_at < ?').bind(new Date(Date.now() - 7 * 86400000).toISOString()).run();
  }
};
