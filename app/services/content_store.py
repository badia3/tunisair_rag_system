import sqlite3
from contextlib import closing
from pathlib import Path

from app.services.tunisair import TunisairPage


def store_pages(
    path: Path,
    pages: list[TunisairPage],
    content_hashes: dict[str, str],
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    active_urls = {page.url for page in pages}

    try:
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS source_pages (
                        url TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        content_text TEXT NOT NULL,
                        content_sha256 TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        synced_at TEXT NOT NULL
                    )"""
                )
                connection.executemany(
                    """INSERT INTO source_pages
                       (url, title, content_text, content_sha256, fetched_at, synced_at)
                       VALUES (?, ?, ?, ?, ?, ?)
                       ON CONFLICT(url) DO UPDATE SET
                           title = excluded.title,
                           content_text = excluded.content_text,
                           content_sha256 = excluded.content_sha256,
                           fetched_at = excluded.fetched_at,
                           synced_at = excluded.synced_at""",
                    [
                        (
                            page.url,
                            page.title,
                            page.text,
                            content_hashes[page.url],
                            page.fetched_at,
                            page.fetched_at,
                        )
                        for page in pages
                    ],
                )
                if active_urls:
                    placeholders = ", ".join("?" for _ in active_urls)
                    connection.execute(
                        f"DELETE FROM source_pages WHERE url NOT IN ({placeholders})",
                        tuple(sorted(active_urls)),
                    )
                else:
                    connection.execute("DELETE FROM source_pages")
                count = connection.execute("SELECT COUNT(*) FROM source_pages").fetchone()[0]
    except sqlite3.Error as exc:
        raise RuntimeError(f"Could not persist extracted Tunisair pages to {path}: {exc}") from exc

    return count
