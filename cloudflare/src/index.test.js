import {test} from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
import worker from './index.js';

function setup() {
  const db = new DatabaseSync(':memory:');
  db.exec('PRAGMA foreign_keys=ON;');
  db.exec(readFileSync(new URL('../schema.sql', import.meta.url), 'utf8'));
  const wrap = (sql, args = []) => ({
    bind: (...params) => wrap(sql, params),
    async first() { return db.prepare(sql).get(...args) || null; },
    async all() { return {results: db.prepare(sql).all(...args)}; },
    async run() { return db.prepare(sql).run(...args); }
  });
  const env = {DOMAIN: 'example.test', BACKEND_TOKEN: 'a'.repeat(64), DB: {
    prepare: wrap, async batch(statements) {
      db.exec('BEGIN');
      try { const out = []; for (const statement of statements) out.push(await statement.run()); db.exec('COMMIT'); return out; }
      catch (e) {db.exec('ROLLBACK'); throw e;}
    }
  }};
  const call = async (path, method = 'GET', body, token = env.BACKEND_TOKEN) => worker.fetch(new Request(`https://mail.test/api/v1/${path}`, {
    method, headers: {Authorization: `Bearer ${token}`}, ...(body === undefined ? {} : {body: JSON.stringify(body)})
  }), env);
  const create = () => call('aliases', 'POST', {domain_id: env.DOMAIN, prefix: '12345678'});
  const mail = (to = '12345678@example.test') => ({to, from: 'sender@example.org', rawSize: 500,
    raw: new Response('From: sender@example.org\r\nTo: ' + to + '\r\nSubject: Verify account\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\nWW91ciBjb2RlIGlzIDEyMzQ1Ng==').body,
    setReject(reason) { this.rejected = reason; }
  });
  return {db, env, call, create, mail};
}

test('auth fails closed, domain health checks schema, invalid input rejected', async () => {
  const {env, call} = setup();
  assert.equal((await call('domains', 'GET', undefined, 'wrong')).status, 401);
  assert.equal((await call('domains')).status, 200);
  assert.equal((await call('aliases', 'POST', {domain_id: 'wrong', prefix: '12345678'})).status, 400);
  assert.equal((await call('aliases', 'POST', null)).status, 400);
  env.BACKEND_TOKEN = '';
  assert.equal((await call('domains')).status, 401);
});

test('create retry, MIME receive, read body, delete, and reject deleted recipient', async () => {
  const {env, call, create, mail, db} = setup();
  assert.equal((await create()).status, 201);
  await create();
  assert.equal(db.prepare('SELECT count(*) n FROM aliases').get().n, 1);
  const message = mail();
  await worker.email(message, env);
  assert.equal(message.rejected, undefined);
  const logs = (await (await call('aliases/12345678/logs')).json()).data.logs;
  assert.equal(logs.length, 1);
  assert.equal(logs[0].text_body, 'Your code is 123456');
  assert.equal((await (await call(`emails/${logs[0].id}`)).json()).data.subject, 'Verify account');
  assert.equal((await call('aliases/12345678', 'DELETE')).status, 200);
  assert.equal(db.prepare('SELECT count(*) n FROM messages').get().n, 0);
  const after = mail(); await worker.email(after, env);
  assert.match(after.rejected, /deleted/);
  assert.equal((await call('aliases/12345678', 'DELETE')).status, 200);
});

test('unregistered, wrong-domain, oversized mail rejected; retention bounded', async () => {
  const {env, create, mail, db} = setup();
  const unknown = mail(); await worker.email(unknown, env); assert.ok(unknown.rejected);
  await create();
  const wrong = mail('12345678@other.test'); await worker.email(wrong, env); assert.ok(wrong.rejected);
  const large = mail(); large.rawSize = 2 * 1024 * 1024;
  await worker.email(large, env); assert.ok(large.rejected);
  for (let i = 0; i < 22; i++) await worker.email(mail(), env);
  assert.equal(db.prepare('SELECT count(*) n FROM messages').get().n, 20);
  db.exec("UPDATE messages SET created_at='2000-01-01T00:00:00.000Z'");
  await worker.scheduled({}, env);
  assert.equal(db.prepare('SELECT count(*) n FROM messages').get().n, 0);
});
