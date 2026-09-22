"""SQLite 数据库操作：存已发现的通知 URL，做去重。"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    url         TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    site        TEXT NOT NULL,
    column_name TEXT NOT NULL,
    first_seen  TEXT NOT NULL
);
"""


class NoticeDB:
    def __init__(self, db_path: str | Path = "notices.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "NoticeDB":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def known_urls(self) -> set[str]:
        """返回库里已有的所有 URL。"""
        conn = self.connect()
        rows = conn.execute("SELECT url FROM notices").fetchall()
        return {r["url"] for r in rows}

    def insert_new(self, items: Iterable[dict]) -> int:
        """插入新通知，返回插入条数。已存在的 URL 自动忽略。"""
        conn = self.connect()
        now = datetime.now().isoformat(timespec="seconds")
        count = 0
        for item in items:
            try:
                conn.execute(
                    """
                    INSERT INTO notices (url, title, site, column_name, first_seen)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item["url"],
                        item["title"],
                        item["site"],
                        item["column"],
                        now,
                    ),
                )
                count += 1
            except sqlite3.IntegrityError:
                pass  # URL 已存在，跳过
        conn.commit()
        return count

    def count(self) -> int:
        conn = self.connect()
        row = conn.execute("SELECT COUNT(*) AS c FROM notices").fetchone()
        return row["c"]
