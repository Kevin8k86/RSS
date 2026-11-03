import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any


def hash_id(link: str, guid: Optional[str] = None) -> str:
    """Generate a stable unique identifier for an RSS item."""
    identifier = guid if guid else link
    return hashlib.sha256(identifier.encode("utf-8")).hexdigest()


class Storage:
    def __init__(self, db_path: str = "curator.db"):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    feed_url TEXT,
                    title TEXT,
                    link TEXT,
                    author TEXT,
                    pub_date TEXT,
                    original_content TEXT,
                    score REAL,
                    recommendation TEXT,
                    status TEXT, -- 'ACCEPTED', 'REJECTED', 'SKIPPED', 'ERROR'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status_created ON articles (status, created_at DESC);")
            conn.commit()

    def is_processed(self, item_id: str) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM articles WHERE id = ?", (item_id,))
            return cur.fetchone() is not None

    def save_result(
        self,
        item_id: str,
        feed_url: str,
        title: str,
        link: str,
        author: str,
        pub_date: str,
        original_content: str,
        score: float,
        recommendation: str,
        status: str,
    ):
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO articles 
                (id, feed_url, title, link, author, pub_date, original_content, score, recommendation, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
                (
                    item_id,
                    feed_url,
                    title,
                    link,
                    author,
                    pub_date,
                    original_content,
                    score,
                    recommendation,
                    status,
                ),
            )
            conn.commit()

    def get_recent_accepted(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieve latest accepted high-quality articles."""
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT id, feed_url, title, link, author, pub_date, original_content, score, recommendation, created_at
                FROM articles
                WHERE status = 'ACCEPTED'
                ORDER BY created_at DESC
                LIMIT ?
            """,
                (limit,),
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]

    def cleanup_old_records(self, days: int = 45):
        """Clean up records older than `days` to keep DB lightweight."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_connection() as conn:
            conn.execute("DELETE FROM articles WHERE created_at < ?", (cutoff,))
            conn.commit()
