import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        (root / "sessions").mkdir(exist_ok=True)
        (root / "uploads").mkdir(exist_ok=True)
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS accounts (
                  id TEXT PRIMARY KEY, label TEXT NOT NULL, phone TEXT NOT NULL,
                  user_id INTEGER, username TEXT, status TEXT NOT NULL,
                  error TEXT, wait_until REAL NOT NULL DEFAULT 0);
                CREATE UNIQUE INDEX IF NOT EXISTS account_phone ON accounts(phone);
                CREATE UNIQUE INDEX IF NOT EXISTS account_user ON accounts(user_id) WHERE user_id IS NOT NULL;
                CREATE TABLE IF NOT EXISTS lists (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, status TEXT NOT NULL,
                  source TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS members (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, list_id TEXT NOT NULL REFERENCES lists(id),
                  user_id INTEGER, username TEXT, name TEXT NOT NULL,
                  excluded INTEGER NOT NULL DEFAULT 0, access_json TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS members_list ON members(list_id);
                CREATE INDEX IF NOT EXISTS members_user ON members(list_id, user_id);
                CREATE TABLE IF NOT EXISTS uploads (
                  id TEXT PRIMARY KEY, path TEXT NOT NULL, mime TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS campaigns (
                  id TEXT PRIMARY KEY, title TEXT NOT NULL, list_id TEXT NOT NULL REFERENCES lists(id),
                  status TEXT NOT NULL, text TEXT NOT NULL, photo_id TEXT REFERENCES uploads(id),
                  accounts_json TEXT NOT NULL, batch_size INTEGER NOT NULL,
                  delay_min REAL NOT NULL, delay_max REAL NOT NULL,
                  next_attempt_at REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '',
                  reviewed_at TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS deliveries (
                  id INTEGER PRIMARY KEY AUTOINCREMENT, campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                  user_id INTEGER, username TEXT, name TEXT NOT NULL, access_json TEXT NOT NULL,
                  account_id TEXT NOT NULL REFERENCES accounts(id), status TEXT NOT NULL DEFAULT 'pending',
                  error TEXT, message_id INTEGER, attempted_at TEXT);
                CREATE INDEX IF NOT EXISTS deliveries_queue ON deliveries(campaign_id, status, id);
            """)
            additions = {
                'members': {'last_active_at': 'REAL'},
                'campaigns': {'scheduled_at': 'REAL', 'server_wait_until': 'REAL NOT NULL DEFAULT 0',
                              'active_within_days': 'INTEGER', 'filter_counts_json': "TEXT NOT NULL DEFAULT '{}'",
                              'bio_texts_json': "TEXT NOT NULL DEFAULT '[]'"},
                'deliveries': {'last_active_at': 'REAL', 'wait_until': 'REAL NOT NULL DEFAULT 0'},
            }
            for table, columns in additions.items():
                existing = {row['name'] for row in db.execute(f'PRAGMA table_info({table})')}
                for name, definition in columns.items():
                    if name not in existing:
                        db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
            db.execute("""CREATE TABLE IF NOT EXISTS campaign_bios (
                campaign_id TEXT NOT NULL REFERENCES campaigns(id),
                account_id TEXT NOT NULL REFERENCES accounts(id), text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                PRIMARY KEY(campaign_id, account_id))""")

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.root / "app.sqlite3", timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all(self, query, args=()):
        with self.db() as db:
            return [dict(row) for row in db.execute(query, args).fetchall()]

    def one(self, query, args=()):
        rows = self.all(query, args)
        return rows[0] if rows else None

    def execute(self, query, args=()):
        with self.db() as db:
            cur = db.execute(query, args)
            return cur.lastrowid

    def get_setting(self, key):
        row = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(row["value"]) if row else None

    def set_setting(self, key, value):
        self.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value)))

    def recover(self):
        with self.db() as db:
            db.execute("UPDATE deliveries SET status='uncertain', error='Interrupted while sending; review before retry' WHERE status='sending'")
            db.execute("UPDATE campaigns SET status='paused', note='Application restarted; review before resuming' WHERE status='running'")
            db.execute("UPDATE lists SET status='partial', note='Collection interrupted; saved members retained' WHERE status='collecting'")
            db.execute("UPDATE accounts SET status='disconnected', error='Login interrupted; reconnect' WHERE status='pending'")
