CREATE TABLE IF NOT EXISTS aliases (
 id TEXT PRIMARY KEY,
 prefix TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
 id TEXT PRIMARY KEY,
 alias_id TEXT NOT NULL REFERENCES aliases(id) ON DELETE CASCADE,
 sender TEXT NOT NULL,
 recipient TEXT NOT NULL,
 subject TEXT NOT NULL,
 text_body TEXT NOT NULL,
 html_body TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_alias_date ON messages(alias_id, created_at DESC);
CREATE INDEX IF NOT EXISTS messages_date ON messages(created_at);
