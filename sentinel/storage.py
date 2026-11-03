from __future__ import annotations

import contextlib
import json
import os
import secrets
import sqlite3
import time
from pathlib import Path

from cryptography.fernet import Fernet

from .core import canonical, uid

SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (id INTEGER PRIMARY KEY CHECK(id=1), username TEXT, password TEXT);
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, csrf TEXT, expires REAL);
CREATE TABLE IF NOT EXISTS nodes (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, group_name TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
 created REAL NOT NULL, credential TEXT, profile TEXT, enrolled REAL,
 heartbeat REAL, last_data REAL, meta TEXT NOT NULL DEFAULT '{}',
 checkpoint_request TEXT, checkpoint TEXT, disabled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS enrollments (token TEXT PRIMARY KEY, node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE, expires REAL);
CREATE TABLE IF NOT EXISTS cursors (node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE, epoch TEXT, seq INTEGER NOT NULL DEFAULT 0, last_end REAL NOT NULL DEFAULT 0, PRIMARY KEY(node_id,epoch));
CREATE TABLE IF NOT EXISTS samples (
 node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE, epoch TEXT, seq INTEGER,
 start REAL, end REAL, rx INTEGER, tx INTEGER, quality TEXT, hash TEXT,
 PRIMARY KEY(node_id,epoch,seq)
);
CREATE INDEX IF NOT EXISTS samples_time ON samples(node_id,end,start);
CREATE TABLE IF NOT EXISTS hourly_usage (node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE, hour REAL, rx INTEGER, tx INTEGER, covered REAL, uncertain INTEGER, PRIMARY KEY(node_id,hour));
CREATE TABLE IF NOT EXISTS calibrations (id TEXT PRIMARY KEY, node_id TEXT REFERENCES nodes(id) ON DELETE CASCADE, created REAL, at REAL, epoch TEXT, seq INTEGER, remaining INTEGER, cycle_end REAL, previous REAL, note TEXT);
CREATE INDEX IF NOT EXISTS calibration_time ON calibrations(node_id,at);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, node_id TEXT, at REAL, kind TEXT, message TEXT);
CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, dedupe TEXT UNIQUE, created REAL, due REAL, text TEXT, state TEXT DEFAULT 'pending', attempts INTEGER DEFAULT 0, error TEXT, delivered REAL, channel TEXT);
CREATE TABLE IF NOT EXISTS node_alert_state (node_id TEXT PRIMARY KEY, offline INTEGER DEFAULT 0, cycle_end REAL);
"""

DEFAULT_SETTINGS = {
    "timezone": "Asia/Shanghai", "daily_time": "09:00", "daily_enabled": True,
    "telegram_enabled": False, "channels": [], "thresholds": [80, 90, 95],
    "offline_minutes": 5, "forecast_enabled": True, "reset_notice": True,
    "pre_reset_notice": True, "public_url": "", "proxy_url": "",
}


class Store:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "sentinel.db"
        keypath = self.directory / "master.key"
        if not keypath.exists():
            if self.path.exists() and self.path.stat().st_size > 0:
                raise RuntimeError("master.key 缺失，请从备份恢复，不能生成新密钥覆盖现有数据")
            self.private_write(keypath, Fernet.generate_key())
        self.cipher = Fernet(keypath.read_bytes().strip())
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO settings VALUES ('general',?)", (canonical(DEFAULT_SETTINGS),))
            self.migrate(db)
        setup = self.directory / "setup-token.txt"
        if not self.initialized() and not setup.exists():
            self.private_write(setup, secrets.token_urlsafe(24).encode())

    # Legacy single-recipient installs become the channel "default". Its dedupe keys keep
    # the old format so already-sent alerts are not repeated after upgrading.
    LEGACY_CHANNEL = "default"

    def migrate(self, db):
        if "channel" not in [r[1] for r in db.execute("PRAGMA table_info(notifications)")]:
            db.execute("ALTER TABLE notifications ADD COLUMN channel TEXT")
        cfg = self.settings(db)
        if "channels" in cfg:
            return
        token, chat = self.secret("telegram_token", db), str(cfg.pop("chat_id", "")).strip()
        cfg["channels"] = []
        if token or chat:
            cfg["channels"].append({"id": self.LEGACY_CHANNEL, "name": "默认", "chat_id": chat, "enabled": True, "daily": True, "alerts": True})
            if token:
                self.set_secret("telegram_token:"+self.LEGACY_CHANNEL, token, db)
            db.execute("UPDATE notifications SET channel=? WHERE channel IS NULL", (self.LEGACY_CHANNEL,))
        db.execute("DELETE FROM settings WHERE key='telegram_token'")
        db.execute("UPDATE settings SET value=? WHERE key='general'", (canonical(cfg),))

    @staticmethod
    def private_write(path: Path, value: bytes):
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def initialized(self):
        with self.connect() as db:
            return db.execute("SELECT 1 FROM admin").fetchone() is not None

    def settings(self, db=None):
        if db is not None:
            return json.loads(db.execute("SELECT value FROM settings WHERE key='general'").fetchone()[0])
        with self.connect() as handle:
            return self.settings(handle)

    def secret(self, key: str, db=None):
        if db is None:
            with self.connect() as handle:
                return self.secret(key, handle)
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return self.cipher.decrypt(row[0].encode()).decode() if row else ""

    def set_secret(self, key, value, db):
        db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, self.cipher.encrypt(value.encode()).decode()))

    def event(self, db, node_id, kind, message, now=None):
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (uid(), node_id, now or time.time(), kind, message))

    def enqueue(self, db, key, text, now=None, kind="alert", channel=None):
        """Queue one copy per receiving channel; returns the inserted row ids.

        kind is "daily", "alert" or "test". A named channel is targeted even when it is
        switched off, so an administrator can test it before enabling.
        """
        now = now or time.time()
        targets = [c for c in self.settings(db).get("channels", [])
                   if (c["id"] == channel if channel else c.get("enabled") and (kind == "test" or c.get("daily" if kind == "daily" else "alerts")))]
        # UTF-16 units are conservatively bounded below the Telegram message limit.
        chunks, current = [], ""
        for line in text.splitlines(keepends=True):
            while len(line.encode("utf-16-le")) > 6000:
                chunks.append(line[:1400]); line = line[1400:]
            if len((current + line).encode("utf-16-le")) > 7000:
                chunks.append(current); current = ""
            current += line
        if current:
            chunks.append(current)
        ids = []
        for target in targets:
            prefix = key if target["id"] == self.LEGACY_CHANNEL else f"{key}@{target['id']}"
            for i, chunk in enumerate(chunks):
                row_id = uid()
                if db.execute("INSERT OR IGNORE INTO notifications(id,dedupe,created,due,text,channel) VALUES(?,?,?,?,?,?)", (row_id, f"{prefix}:{i}", now, now, chunk, target["id"])).rowcount:
                    ids.append(row_id)
        return ids

    def backup(self, destination: Path):
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as source, contextlib.closing(sqlite3.connect(destination)) as target:
            with target:
                source.backup(target)
                if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("备份数据库校验失败")
