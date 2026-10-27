"""SQLite state and URL canonicalization for the news bot."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


def canonicalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Unsupported article URL: {url!r}")
    hostname = parsed.hostname.casefold()
    port = parsed.port
    if port and not ((parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)):
        hostname = f"{hostname}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.casefold(), hostname, path, urlencode(sorted(query)), ""))


class ArticleStore:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS articles (
                    canonical_url TEXT PRIMARY KEY,
                    original_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'seen'
                        CHECK (status IN ('seen', 'failed', 'dry_run', 'posted')),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_attempt_at TEXT,
                    posted_at TEXT,
                    tweet_id TEXT,
                    last_error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status)"
            )

    def record_seen(self, original_url: str, title: str) -> str:
        canonical_url = canonicalize_url(original_url)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO articles (canonical_url, original_url, title)
                VALUES (?, ?, ?)
                ON CONFLICT(canonical_url) DO UPDATE SET
                    original_url = excluded.original_url,
                    title = excluded.title
                """,
                (canonical_url, original_url, title),
            )
        return canonical_url

    def posted_urls(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT canonical_url FROM articles WHERE status = 'posted'"
            ).fetchall()
        return {str(row["canonical_url"]) for row in rows}

    def can_attempt(self, canonical_url: str, max_attempts: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, attempts FROM articles WHERE canonical_url = ?",
                (canonical_url,),
            ).fetchone()
        return bool(row and row["status"] != "posted" and row["attempts"] < max_attempts)

    def mark_posted(self, canonical_url: str, tweet_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE articles
                SET status = 'posted', attempts = attempts + 1,
                    last_attempt_at = CURRENT_TIMESTAMP, posted_at = CURRENT_TIMESTAMP,
                    tweet_id = ?, last_error = NULL
                WHERE canonical_url = ?
                """,
                (tweet_id, canonical_url),
            )

    def mark_failed(self, canonical_url: str, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE articles
                SET status = 'failed', attempts = attempts + 1,
                    last_attempt_at = CURRENT_TIMESTAMP, last_error = ?
                WHERE canonical_url = ?
                """,
                (error[:1000], canonical_url),
            )

    def mark_dry_run(self, canonical_url: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE articles
                SET status = 'dry_run',
                    last_attempt_at = CURRENT_TIMESTAMP, last_error = NULL
                WHERE canonical_url = ?
                """,
                (canonical_url,),
            )

    def get(self, original_or_canonical_url: str) -> dict | None:
        canonical_url = canonicalize_url(original_or_canonical_url)
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM articles WHERE canonical_url = ?", (canonical_url,)
            ).fetchone()
        return dict(row) if row else None

    def migrate_legacy_file(self, path: Path) -> int:
        if not path.exists():
            return 0
        migrated = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            url = line.strip()
            if not url:
                continue
            try:
                canonical_url = self.record_seen(url, "legacy import")
            except ValueError:
                continue
            with self._connect() as connection:
                cursor = connection.execute(
                    """
                    UPDATE articles
                    SET status = 'posted', posted_at = COALESCE(posted_at, CURRENT_TIMESTAMP)
                    WHERE canonical_url = ? AND status != 'posted'
                    """,
                    (canonical_url,),
                )
                migrated += cursor.rowcount
        return migrated
