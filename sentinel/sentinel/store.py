"""Tiny SQLite store: event log, push tokens and a few persisted flags."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                event_id TEXT,
                data TEXT
            );
            CREATE INDEX IF NOT EXISTS log_ts ON log(ts DESC);
            CREATE TABLE IF NOT EXISTS tokens (token TEXT PRIMARY KEY, added REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )
        self.db.commit()

    # -- log
    def add_log(self, kind: str, text: str, event_id: str | None = None,
                data: dict | None = None, ts: float | None = None) -> None:
        self.db.execute(
            "INSERT INTO log (ts, kind, text, event_id, data) VALUES (?,?,?,?,?)",
            (ts if ts is not None else time.time(), kind, text, event_id, json.dumps(data) if data else None),
        )
        # keep the table small: newest 2000 rows
        self.db.execute("DELETE FROM log WHERE id <= (SELECT MAX(id) FROM log) - 2000")
        self.db.commit()

    def recent(self, limit: int = 50) -> list[dict]:
        limit = max(1, min(int(limit), 500))
        rows = self.db.execute("SELECT * FROM log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r["id"], "ts": r["ts"], "kind": r["kind"], "text": r["text"],
                "event_id": r["event_id"], "data": json.loads(r["data"]) if r["data"] else None,
            })
        return out

    def purge_before(self, ts: float) -> int:
        """Delete log rows older than `ts`. Returns how many were removed."""
        n = self.db.execute("DELETE FROM log WHERE ts < ?", (ts,)).rowcount
        self.db.commit()
        return n

    def clip_folder(self, event_id: str) -> str | None:
        """Cloud folder the clips of an event were saved to (from the 'clips' log entry)."""
        row = self.db.execute(
            "SELECT data FROM log WHERE kind = 'clips' AND event_id = ? ORDER BY id DESC LIMIT 1", (event_id,)
        ).fetchone()
        try:
            return json.loads(row["data"])["folder"] if row and row["data"] else None
        except (ValueError, KeyError, TypeError):
            return None

    def since(self, ts: float, limit: int = 5000) -> list[dict]:
        """Log rows newer than `ts`, oldest first."""
        rows = self.db.execute(
            "SELECT * FROM log WHERE ts >= ? ORDER BY id ASC LIMIT ?", (ts, limit)
        ).fetchall()
        return [{
            "id": r["id"], "ts": r["ts"], "kind": r["kind"], "text": r["text"],
            "event_id": r["event_id"], "data": json.loads(r["data"]) if r["data"] else None,
        } for r in rows]

    # -- push tokens
    def add_token(self, token: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO tokens (token, added) VALUES (?, ?)", (token, time.time()))
        self.db.commit()

    def remove_token(self, token: str) -> None:
        self.db.execute("DELETE FROM tokens WHERE token = ?", (token,))
        self.db.commit()

    def tokens(self) -> list[str]:
        return [r["token"] for r in self.db.execute("SELECT token FROM tokens")]

    # -- kv
    def set(self, key: str, value: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, value))
        self.db.commit()

    def get(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return r["value"] if r else default
