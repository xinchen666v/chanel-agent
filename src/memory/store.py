"""SQLite-based persistent storage for thought chains, user profiles, and sessions."""

import sqlite3
import threading
from pathlib import Path
from datetime import datetime
import uuid


class MemoryStore:
    """Persistent SQLite storage for agent memory.

    Thread-safe. Schema auto-created on first use.

    Tables:
        thought_chains:  Observation → Inference → Action → Outcome records
        user_profile:    Key-value user behavior profile
        sessions:        Session lifecycle tracking
    """

    SQL_CREATE = """
    CREATE TABLE IF NOT EXISTS thought_chains (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        chain_id    TEXT NOT NULL,
        session_id  TEXT NOT NULL,
        timestamp   TEXT NOT NULL,
        observation TEXT NOT NULL,
        inference   TEXT DEFAULT '',
        action      TEXT DEFAULT '',
        content     TEXT DEFAULT '',
        outcome     TEXT DEFAULT '',
        created_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS user_profile (
        key         TEXT PRIMARY KEY,
        value       TEXT NOT NULL,
        updated_at  TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id          TEXT PRIMARY KEY,
        started_at  TEXT DEFAULT (datetime('now','localtime')),
        ended_at    TEXT,
        summary     TEXT DEFAULT ''
    );

    CREATE INDEX IF NOT EXISTS idx_chains_session ON thought_chains(session_id);
    CREATE INDEX IF NOT EXISTS idx_chains_timestamp ON thought_chains(timestamp);
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._local = threading.local()
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _ensure_schema(self):
        conn = self._get_conn()
        conn.executescript(self.SQL_CREATE)
        conn.commit()

    # ---- Session Management ----

    def start_session(self) -> str:
        """Create a new session and return its ID."""
        session_id = uuid.uuid4().hex[:12]
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
                (session_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
        return session_id

    def end_session(self, session_id: str, summary: str = ""):
        """Mark a session as ended."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "UPDATE sessions SET ended_at=?, summary=? WHERE id=?",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), summary, session_id),
            )
            conn.commit()

    def get_active_session_id(self) -> str | None:
        """Get the most recent session that hasn't ended."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id FROM sessions WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return row["id"] if row else None

    # ---- Thought Chains ----

    def record_chain(
        self,
        chain_id: str,
        session_id: str,
        observation: str,
        inference: str = "",
        action: str = "",
        content: str = "",
        outcome: str = "",
    ):
        """Record a complete thought chain entry."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO thought_chains
                   (chain_id, session_id, timestamp, observation, inference, action, content, outcome)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    chain_id,
                    session_id,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    observation,
                    inference,
                    action,
                    content,
                    outcome,
                ),
            )
            conn.commit()

    def get_recent_chains(self, session_id: str, limit: int = 5) -> list[dict]:
        """Get the most recent thought chains for a session."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM thought_chains
               WHERE session_id = ?
               ORDER BY id DESC LIMIT ?""",
            (session_id, limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_recent_chains_across_sessions(self, limit: int = 5) -> list[dict]:
        """Get the most recent thought chains across all sessions."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM thought_chains ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_session_stats(self, session_id: str) -> dict:
        """Get stats for the current session."""
        conn = self._get_conn()
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM thought_chains WHERE session_id=?",
            (session_id,),
        ).fetchone()
        spoke = conn.execute(
            "SELECT COUNT(*) as cnt FROM thought_chains WHERE session_id=? AND action='send_message'",
            (session_id,),
        ).fetchone()
        silent = conn.execute(
            "SELECT COUNT(*) as cnt FROM thought_chains WHERE session_id=? AND action='silent'",
            (session_id,),
        ).fetchone()
        return {
            "total_wakes": total["cnt"],
            "messages_sent": spoke["cnt"],
            "silent_wakes": silent["cnt"],
        }

    # ---- User Profile ----

    def set_profile(self, key: str, value: str):
        """Upsert a user profile key-value pair."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO user_profile (key, value, updated_at)
                   VALUES (?, ?, datetime('now','localtime'))
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (key, value),
            )
            conn.commit()

    def get_profile(self, key: str) -> str | None:
        """Get a user profile value by key."""
        conn = self._get_conn()
        row = conn.execute("SELECT value FROM user_profile WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def get_all_profile(self) -> dict[str, str]:
        """Get all user profile entries."""
        conn = self._get_conn()
        rows = conn.execute("SELECT key, value FROM user_profile").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def search_observations(self, keyword: str, limit: int = 20) -> list[dict]:
        """Search thought chains where observation contains a keyword.

        Searches the JSON observation text (includes window title, app name, etc.).
        """
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM thought_chains
               WHERE observation LIKE ? OR content LIKE ?
               ORDER BY id DESC LIMIT ?""",
            (f"%{keyword}%", f"%{keyword}%", limit),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_chain_detail(self, chain_id: str) -> dict | None:
        """Get full detail of a specific thought chain by chain_id or row id."""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM thought_chains WHERE chain_id=? OR id=?",
            (chain_id, chain_id),
        ).fetchone()
        return dict(row) if row else None

    def get_observations_timeline(self, limit: int = 50) -> list[dict]:
        """Get recent observations across all sessions (for timeline view)."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT id, chain_id, session_id, timestamp, observation, action, content
               FROM thought_chains ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def get_observation_field_summary(self) -> list[dict]:
        """Get a summary of observation fields (parsed JSON) for recent chains.

        Returns list of dicts with: timestamp, window_title, app_name, idle_seconds, action, content.
        """
        import json
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT timestamp, observation, action, content
               FROM thought_chains ORDER BY id DESC LIMIT 100""",
        ).fetchall()
        results = []
        for row in reversed(rows):
            try:
                obs = json.loads(row["observation"])
            except (json.JSONDecodeError, TypeError):
                obs = {}
            results.append({
                "timestamp": row["timestamp"],
                "window_title": obs.get("active_window_title", "?"),
                "app_name": obs.get("active_app_name", "?"),
                "idle_seconds": obs.get("user_idle_seconds", "?"),
                "hour_of_day": obs.get("hour_of_day", "?"),
                "is_weekend": obs.get("is_weekend", "?"),
                "action": row["action"],
                "content": row["content"],
            })
        return results

    # ---- Close ----

    def close(self):
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None