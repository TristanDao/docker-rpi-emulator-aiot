import json
import logging
import sqlite3
import threading
import time

from app.config import OFFLINE_QUEUE_DB, OFFLINE_MAX_RETRIES

logger = logging.getLogger(__name__)


class OfflineQueue:
    """SQLite-backed persistent queue for events that failed to reach the server."""

    def __init__(self, db_path: str = OFFLINE_QUEUE_DB):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_table()

    def _init_table(self):
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_events (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type  TEXT NOT NULL,
                    payload     TEXT NOT NULL,
                    created_at  REAL NOT NULL,
                    retry_count INTEGER DEFAULT 0
                )
            """)
            self._conn.commit()

    def push(self, event_type: str, payload: dict):
        with self._lock:
            self._conn.execute(
                "INSERT INTO pending_events (event_type, payload, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps(payload), time.time()),
            )
            self._conn.commit()
        logger.info("Queued offline event: %s", event_type)

    def pop_batch(self, limit: int = 10) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT id, event_type, payload, retry_count FROM pending_events "
                "WHERE retry_count < ? ORDER BY id LIMIT ?",
                (OFFLINE_MAX_RETRIES, limit),
            )
            rows = cursor.fetchall()
            return [
                {"id": r[0], "event_type": r[1], "payload": json.loads(r[2]), "retry_count": r[3]}
                for r in rows
            ]

    def mark_done(self, event_id: int):
        with self._lock:
            self._conn.execute("DELETE FROM pending_events WHERE id = ?", (event_id,))
            self._conn.commit()

    def increment_retry(self, event_id: int):
        with self._lock:
            self._conn.execute(
                "UPDATE pending_events SET retry_count = retry_count + 1 WHERE id = ?",
                (event_id,),
            )
            self._conn.commit()

    def pending_count(self) -> int:
        with self._lock:
            cursor = self._conn.execute(
                "SELECT COUNT(*) FROM pending_events WHERE retry_count < ?",
                (OFFLINE_MAX_RETRIES,),
            )
            return cursor.fetchone()[0]
