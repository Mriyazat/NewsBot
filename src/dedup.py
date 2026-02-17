"""
Deduplication Tracker - SQLite-based tracking of already-sent articles.

Prevents the same article from being sent to Teams multiple times.
Uses article URL as the unique identifier, with a hash fallback for
articles with identical URLs but different content.
"""

import hashlib
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = "data/seen_articles.db"


class DedupTracker:
    """Tracks which articles have already been sent to Teams."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._ensure_db_dir()
        self._init_db()

    def _ensure_db_dir(self):
        """Create the data directory if it doesn't exist."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self):
        """Initialize the SQLite database and create table if needed."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS seen_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT UNIQUE NOT NULL,
                    title TEXT,
                    url TEXT,
                    source_name TEXT,
                    sent_at TEXT NOT NULL,
                    relevance_score REAL DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_url_hash
                ON seen_articles (url_hash)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sent_at
                ON seen_articles (sent_at)
            """)
            conn.commit()

    def _hash_url(self, url: str) -> str:
        """Create a SHA-256 hash of the article URL."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def is_seen(self, article) -> bool:
        """Check if an article has already been sent."""
        url_hash = self._hash_url(article.link)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM seen_articles WHERE url_hash = ?",
                (url_hash,),
            )
            return cursor.fetchone() is not None

    def mark_seen(self, article):
        """Mark an article as sent."""
        url_hash = self._hash_url(article.link)
        sent_at = datetime.now(timezone.utc).isoformat()
        score = getattr(article, "relevance_score", 0)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO seen_articles
                    (url_hash, title, url, source_name, sent_at, relevance_score)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        url_hash,
                        article.title[:200],
                        article.link,
                        article.source_name,
                        sent_at,
                        score,
                    ),
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to mark article as seen: {e}")

    def mark_batch_seen(self, articles: list):
        """Mark multiple articles as sent in a single transaction."""
        sent_at = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            for article in articles:
                url_hash = self._hash_url(article.link)
                score = getattr(article, "relevance_score", 0)
                try:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO seen_articles
                        (url_hash, title, url, source_name, sent_at, relevance_score)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            url_hash,
                            article.title[:200],
                            article.link,
                            article.source_name,
                            sent_at,
                            score,
                        ),
                    )
                except sqlite3.Error as e:
                    logger.error(f"Failed to mark article: {e}")
            conn.commit()

        logger.info(f"Marked {len(articles)} articles as seen")

    def filter_unseen(self, articles: list) -> list:
        """Filter out already-seen articles, returning only new ones."""
        unseen = []
        seen_count = 0

        for article in articles:
            if self.is_seen(article):
                seen_count += 1
                logger.debug(f"Already seen: {article.title[:50]}...")
            else:
                unseen.append(article)

        logger.info(
            f"Dedup: {len(unseen)} new articles, {seen_count} already sent"
        )
        return unseen

    def cleanup_old(self, days: int = 30):
        """Remove entries older than N days to keep the DB small."""
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff = (cutoff - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM seen_articles WHERE sent_at < ?",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()

        if deleted:
            logger.info(f"Cleaned up {deleted} articles older than {days} days")

    def stats(self) -> dict:
        """Get statistics about tracked articles."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM seen_articles"
            ).fetchone()[0]
            recent = conn.execute(
                "SELECT COUNT(*) FROM seen_articles WHERE sent_at > datetime('now', '-1 day')"
            ).fetchone()[0]
        return {"total_tracked": total, "sent_last_24h": recent}
