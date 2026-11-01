"""SQLite store for sessions, email drafts, review flags and the audit log."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from classpartai.contracts import SessionResults

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    results    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS emails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL,
    person_id   TEXT,                 -- NULL for the prof's summary
    recipient   TEXT NOT NULL,
    kind        TEXT NOT NULL,        -- commend | encourage | prof_summary
    subject     TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL,        -- pending | approved | rejected | sent | failed
    created_at  TEXT NOT NULL,
    decided_by  TEXT,
    decided_at  TEXT,
    sent_to     TEXT,                 -- actual address (differs from recipient in test mode)
    message_id  TEXT,
    error       TEXT,
    UNIQUE (session_id, person_id, kind)
);
CREATE TABLE IF NOT EXISTS flags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    person_id       TEXT,
    contribution_id TEXT,
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS log (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts     TEXT NOT NULL,
    event  TEXT NOT NULL,
    detail TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Email(BaseModel):
    id: int
    session_id: str
    person_id: str | None
    recipient: str
    kind: str
    subject: str
    body: str
    status: str
    created_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    sent_to: str | None = None
    message_id: str | None = None
    error: str | None = None


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # Sessions
    def save_session(self, results: SessionResults) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
                (results.session_id, results.model_dump_json(), now()),
            )

    def get_session(self, session_id: str) -> SessionResults | None:
        row = self.db.execute(
            "SELECT results FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return SessionResults.model_validate_json(row["results"]) if row else None

    def sessions(self) -> list[SessionResults]:
        rows = self.db.execute("SELECT results FROM sessions ORDER BY created_at").fetchall()
        return [SessionResults.model_validate_json(r["results"]) for r in rows]

    # Emails
    def add_email(self, **fields) -> Email:
        with self.db:
            cur = self.db.execute(
                "INSERT INTO emails (session_id, person_id, recipient, kind, subject, body,"
                " status, created_at) VALUES (:session_id, :person_id, :recipient, :kind,"
                " :subject, :body, :status, :created_at)",
                {**fields, "created_at": now()},
            )
        return self.get_email(cur.lastrowid)

    def find_email(self, session_id: str, person_id: str | None, kind: str) -> Email | None:
        row = self.db.execute(
            "SELECT * FROM emails WHERE session_id = ? AND person_id IS ? AND kind = ?",
            (session_id, person_id, kind),
        ).fetchone()
        return Email(**dict(row)) if row else None

    def get_email(self, email_id: int) -> Email:
        row = self.db.execute("SELECT * FROM emails WHERE id = ?", (email_id,)).fetchone()
        if row is None:
            raise KeyError(email_id)
        return Email(**dict(row))

    def emails(self, status: str | None = None) -> list[Email]:
        sql, args = "SELECT * FROM emails", ()
        if status:
            sql, args = sql + " WHERE status = ?", (status,)
        return [Email(**dict(r)) for r in self.db.execute(sql + " ORDER BY id", args)]

    def update_email(self, email_id: int, **fields) -> Email:
        cols = ", ".join(f"{k} = :{k}" for k in fields)
        with self.db:
            self.db.execute(f"UPDATE emails SET {cols} WHERE id = :id", {**fields, "id": email_id})
        return self.get_email(email_id)

    def sent_today(self) -> int:
        today = now()[:10]
        row = self.db.execute(
            "SELECT COUNT(*) FROM emails WHERE status = 'sent' AND substr(decided_at, 1, 10) = ?",
            (today,),
        ).fetchone()
        return row[0]

    # Flags and log
    def add_flag(self, session_id, person_id, contribution_id, reason) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO flags (session_id, person_id, contribution_id, reason, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (session_id, person_id, contribution_id, reason, now()),
            )

    def flags(self, session_id: str | None = None) -> list[dict]:
        sql, args = "SELECT * FROM flags", ()
        if session_id:
            sql, args = sql + " WHERE session_id = ?", (session_id,)
        return [dict(r) for r in self.db.execute(sql + " ORDER BY id", args)]

    def log(self, event: str, **detail) -> None:
        with self.db:
            self.db.execute(
                "INSERT INTO log (ts, event, detail) VALUES (?, ?, ?)",
                (now(), event, json.dumps(detail, default=str)),
            )

    def log_entries(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute("SELECT * FROM log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
