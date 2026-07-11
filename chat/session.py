"""Session stores for persistent chat conversations (SQLite + Postgres)."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Session:
    """Represents a chat session tied to a platform thread."""

    session_id: str  # Composite: {platform}:{channel_id}:{thread_id}
    agent_session_id: str  # Claude Agent SDK session ID for resume
    platform: str
    channel_id: str
    thread_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0
    total_cost_usd: float = 0.0
    status: str = "active"


@dataclass
class HeartbeatThread:
    """Tracks a heartbeat notification posted to Slack so thread replies can start conversations."""

    channel_id: str
    thread_ts: str  # The Slack message ts — becomes the thread_ts for replies
    alert_text: str
    created_at: datetime


class SQLiteSessionStore:
    """Persistent session storage backed by SQLite."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the chat_sessions and heartbeat_threads tables if they don't exist."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL UNIQUE,
                    agent_session_id TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    channel_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    total_cost_usd REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'active'
                );
                CREATE INDEX IF NOT EXISTS idx_platform_thread
                    ON chat_sessions(platform, channel_id, thread_id);
                CREATE TABLE IF NOT EXISTS heartbeat_threads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    alert_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_hb_channel_thread
                    ON heartbeat_threads(channel_id, thread_ts);
            """)

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            session_id=row["session_id"],
            agent_session_id=row["agent_session_id"],
            platform=row["platform"],
            channel_id=row["channel_id"],
            thread_id=row["thread_id"],
            user_id=row["user_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            message_count=row["message_count"],
            total_cost_usd=row["total_cost_usd"],
            status=row["status"],
        )

    def get(self, platform: str, channel_id: str, thread_id: str) -> Session | None:
        """Look up a session by platform, channel, and thread."""
        session_id = f"{platform}:{channel_id}:{thread_id}"
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM chat_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_session(row)

    def create(self, session: Session) -> None:
        """Insert a new session."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.execute(
                """INSERT INTO chat_sessions
                   (session_id, agent_session_id, platform, channel_id, thread_id,
                    user_id, created_at, updated_at, message_count, total_cost_usd, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session.session_id,
                    session.agent_session_id,
                    session.platform,
                    session.channel_id,
                    session.thread_id,
                    session.user_id,
                    session.created_at.isoformat(),
                    session.updated_at.isoformat(),
                    session.message_count,
                    session.total_cost_usd,
                    session.status,
                ),
            )

    def update(self, session: Session) -> None:
        """Update an existing session's mutable fields.

        `created_at` is also written so the engine's rotation logic can reset
        it when starting a fresh underlying agent session. Without persisting
        created_at, any rotation that resets it in-memory is silently dropped,
        which causes every subsequent message to re-rotate (memory-loss bug
        observed 2026-05-06 → 2026-05-08).
        """
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.execute(
                """UPDATE chat_sessions
                   SET agent_session_id = ?, created_at = ?, updated_at = ?,
                       message_count = ?, total_cost_usd = ?, status = ?
                   WHERE session_id = ?""",
                (
                    session.agent_session_id,
                    session.created_at.isoformat(),
                    datetime.now().isoformat(),
                    session.message_count,
                    session.total_cost_usd,
                    session.status,
                    session.session_id,
                ),
            )

    def list_active(self, platform: str | None = None) -> list[Session]:
        """List active sessions, optionally filtered by platform."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            if platform:
                rows = conn.execute(
                    "SELECT * FROM chat_sessions WHERE status = 'active' AND platform = ? "
                    "ORDER BY updated_at DESC",
                    (platform,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM chat_sessions WHERE status = 'active' ORDER BY updated_at DESC"
                ).fetchall()
            return [self._row_to_session(row) for row in rows]

    def save_heartbeat_thread(self, thread: HeartbeatThread) -> None:
        """Record a heartbeat notification so thread replies can be linked."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO heartbeat_threads
                   (channel_id, thread_ts, alert_text, created_at)
                   VALUES (?, ?, ?, ?)""",
                (thread.channel_id, thread.thread_ts, thread.alert_text, thread.created_at.isoformat()),
            )

    def get_heartbeat_thread(self, channel_id: str, thread_ts: str) -> HeartbeatThread | None:
        """Look up a heartbeat thread by channel and ts."""
        with sqlite3.connect(self.db_path, check_same_thread=False) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM heartbeat_threads WHERE channel_id = ? AND thread_ts = ?",
                (channel_id, thread_ts),
            ).fetchone()
            if row is None:
                return None
            return HeartbeatThread(
                channel_id=row["channel_id"],
                thread_ts=row["thread_ts"],
                alert_text=row["alert_text"],
                created_at=datetime.fromisoformat(row["created_at"]),
            )


class PostgresSessionStore:
    """Persistent session storage backed by PostgreSQL."""

    def __init__(self, database_url: str) -> None:
        import psycopg

        self._url = database_url
        self._conn = psycopg.connect(database_url, autocommit=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create the chat_sessions and heartbeat_threads tables if they don't exist."""
        cur = self._conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id SERIAL PRIMARY KEY,
                session_id TEXT NOT NULL UNIQUE,
                agent_session_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL,
                message_count INTEGER DEFAULT 0,
                total_cost_usd DOUBLE PRECISION DEFAULT 0.0,
                status TEXT DEFAULT 'active'
            )
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_platform_thread
                ON chat_sessions(platform, channel_id, thread_id)
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS heartbeat_threads (
                id SERIAL PRIMARY KEY,
                channel_id TEXT NOT NULL,
                thread_ts TEXT NOT NULL,
                alert_text TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
        """)
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_hb_channel_thread
                ON heartbeat_threads(channel_id, thread_ts)
        """)

    def _row_to_session(self, row: tuple) -> Session:
        """Convert a database row to a Session object."""
        return Session(
            session_id=row[1],
            agent_session_id=row[2],
            platform=row[3],
            channel_id=row[4],
            thread_id=row[5],
            user_id=row[6],
            created_at=row[7] if isinstance(row[7], datetime) else datetime.fromisoformat(str(row[7])),
            updated_at=row[8] if isinstance(row[8], datetime) else datetime.fromisoformat(str(row[8])),
            message_count=row[9],
            total_cost_usd=float(row[10]),
            status=row[11],
        )

    def get(self, platform: str, channel_id: str, thread_id: str) -> Session | None:
        """Look up a session by platform, channel, and thread."""
        session_id = f"{platform}:{channel_id}:{thread_id}"
        cur = self._conn.cursor()
        cur.execute(
            "SELECT * FROM chat_sessions WHERE session_id = %s",
            (session_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return self._row_to_session(row)

    def create(self, session: Session) -> None:
        """Insert a new session."""
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO chat_sessions
               (session_id, agent_session_id, platform, channel_id, thread_id,
                user_id, created_at, updated_at, message_count, total_cost_usd, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                session.session_id,
                session.agent_session_id,
                session.platform,
                session.channel_id,
                session.thread_id,
                session.user_id,
                session.created_at,
                session.updated_at,
                session.message_count,
                session.total_cost_usd,
                session.status,
            ),
        )

    def update(self, session: Session) -> None:
        """Update an existing session's mutable fields.

        `created_at` is included so engine rotation can reset it; without
        this, rotated sessions silently re-rotate on every message. Match
        the SQLite store's behaviour.
        """
        cur = self._conn.cursor()
        cur.execute(
            """UPDATE chat_sessions
               SET agent_session_id = %s, created_at = %s, updated_at = %s,
                   message_count = %s, total_cost_usd = %s, status = %s
               WHERE session_id = %s""",
            (
                session.agent_session_id,
                session.created_at,
                datetime.now(),
                session.message_count,
                session.total_cost_usd,
                session.status,
                session.session_id,
            ),
        )

    def list_active(self, platform: str | None = None) -> list[Session]:
        """List active sessions, optionally filtered by platform."""
        cur = self._conn.cursor()
        if platform:
            cur.execute(
                "SELECT * FROM chat_sessions WHERE status = 'active' AND platform = %s "
                "ORDER BY updated_at DESC",
                (platform,),
            )
        else:
            cur.execute(
                "SELECT * FROM chat_sessions WHERE status = 'active' ORDER BY updated_at DESC"
            )
        return [self._row_to_session(row) for row in cur.fetchall()]

    def save_heartbeat_thread(self, thread: HeartbeatThread) -> None:
        """Record a heartbeat notification so thread replies can be linked."""
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO heartbeat_threads (channel_id, thread_ts, alert_text, created_at)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (channel_id, thread_ts) DO UPDATE SET
                   alert_text = EXCLUDED.alert_text,
                   created_at = EXCLUDED.created_at""",
            (thread.channel_id, thread.thread_ts, thread.alert_text, thread.created_at),
        )

    def get_heartbeat_thread(self, channel_id: str, thread_ts: str) -> HeartbeatThread | None:
        """Look up a heartbeat thread by channel and ts."""
        cur = self._conn.cursor()
        cur.execute(
            "SELECT channel_id, thread_ts, alert_text, created_at FROM heartbeat_threads "
            "WHERE channel_id = %s AND thread_ts = %s",
            (channel_id, thread_ts),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return HeartbeatThread(
            channel_id=row[0],
            thread_ts=row[1],
            alert_text=row[2],
            created_at=row[3] if isinstance(row[3], datetime) else datetime.fromisoformat(str(row[3])),
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn and not self._conn.closed:
            self._conn.close()


def get_session_store(
    chat_db_path: Path | None = None,
) -> SQLiteSessionStore | PostgresSessionStore:
    """Factory: returns Postgres if DATABASE_URL is set, else SQLite."""
    url = os.getenv("DATABASE_URL", "")
    if url:
        return PostgresSessionStore(url)
    if chat_db_path is None:
        from config import CHAT_DB_PATH

        chat_db_path = CHAT_DB_PATH
    return SQLiteSessionStore(chat_db_path)
