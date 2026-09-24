"""SQLite 数据库操作：存已发现的通知 URL，做去重、分类和写作计数。

表结构：
- notices：一个 URL 一行，主键 url。采集只负责插入，category / interpreted_count
  等字段由下游（AI 分类服务、写作服务）通过 API 回写。
- interpretations：一个 URL 对应多条解读记录（一对多），写作完成后追加。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable


SCHEMA = """
CREATE TABLE IF NOT EXISTS notices (
    url               TEXT PRIMARY KEY,
    title             TEXT NOT NULL,
    site              TEXT NOT NULL,
    column_name       TEXT NOT NULL,
    first_seen        TEXT NOT NULL,
    publish_time      TEXT,
    document_time     TEXT,
    category          TEXT,
    category_at       TEXT,
    interpreted_count INTEGER NOT NULL DEFAULT 0,
    last_written_at   TEXT
);

CREATE TABLE IF NOT EXISTS interpretations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    url            TEXT NOT NULL,
    writer         TEXT,
    article_title  TEXT,
    article_path   TEXT,
    status         TEXT,
    written_at     TEXT NOT NULL,
    FOREIGN KEY (url) REFERENCES notices(url)
);
"""

# 索引要等列迁移完成后再建，否则老表缺列会报错
INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_notices_category    ON notices(category);
CREATE INDEX IF NOT EXISTS idx_notices_first_seen ON notices(first_seen);
CREATE INDEX IF NOT EXISTS idx_interpretations_url ON interpretations(url);
"""

# 旧库迁移：已存在的 notices 表缺这些列就补上（SQLite 不支持 IF NOT EXISTS 加列）
_COLUMN_MIGRATIONS = [
    ("category", "ALTER TABLE notices ADD COLUMN category TEXT"),
    ("category_at", "ALTER TABLE notices ADD COLUMN category_at TEXT"),
    (
        "interpreted_count",
        "ALTER TABLE notices ADD COLUMN interpreted_count INTEGER NOT NULL DEFAULT 0",
    ),
    ("last_written_at", "ALTER TABLE notices ADD COLUMN last_written_at TEXT"),
    ("publish_time", "ALTER TABLE notices ADD COLUMN publish_time TEXT"),
    ("document_time", "ALTER TABLE notices ADD COLUMN document_time TEXT"),
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class NoticeDB:
    def __init__(self, db_path: str | Path = "notices.db"):
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        # 写锁：SQLite 单写，API 请求线程和后台采集线程都可能写
        self._write_lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            # check_same_thread=False：FastAPI 请求线程 + 后台采集线程共用同一连接
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # WAL 模式支持并发读写，适合"API 读 + 后台写"
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.executescript(INDEX_SQL)
            self._conn.commit()
        return self._conn

    def _migrate(self) -> None:
        """给老版本库补列，已存在就跳过。"""
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(notices)")}
        for col_name, sql in _COLUMN_MIGRATIONS:
            if col_name not in cols:
                self._conn.execute(sql)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "NoticeDB":
        self.connect()
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # ---- 采集写入 ----------------------------------------------------------

    def known_urls(self) -> set[str]:
        """返回库里已有的所有 URL。"""
        conn = self.connect()
        rows = conn.execute("SELECT url FROM notices").fetchall()
        return {r["url"] for r in rows}

    def insert_new(self, items: Iterable[dict]) -> int:
        """插入新通知，返回插入条数。已存在的 URL 自动忽略。"""
        conn = self.connect()
        now = _now()
        count = 0
        with self._write_lock:
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

    # ---- AI 分类服务回写 ---------------------------------------------------

    def pending_classify(self, limit: int = 20) -> list[dict]:
        """拉待分类的链接（category 为空或 pending）。返回里带数字 id 供 API 用。"""
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT rowid AS id, url, title, site, column_name, first_seen
            FROM notices
            WHERE category IS NULL OR category = 'pending'
            ORDER BY first_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_item(self, item_id: int) -> dict | None:
        """按数字 id 查一条记录。"""
        conn = self.connect()
        row = conn.execute(
            "SELECT rowid AS id, url, title, site, column_name, category FROM notices WHERE rowid=?",
            (item_id,),
        ).fetchone()
        return dict(row) if row else None

    def update_category(self, item_id: int, category: str) -> bool:
        """按数字 id 回写分类结果，返回是否命中已有记录。"""
        conn = self.connect()
        with self._write_lock:
            cur = conn.execute(
                "UPDATE notices SET category = ?, category_at = ? WHERE rowid = ?",
                (category, _now(), item_id),
            )
            conn.commit()
        return cur.rowcount > 0

    def update_times(self, item_id: int, publish_time: str | None = None,
                     document_time: str | None = None) -> bool:
        """回写发布时间和成文时间。传 null 表示提取过了但没有，写进去避免重复处理。"""
        conn = self.connect()
        with self._write_lock:
            fields = []
            params: list = []
            if publish_time is not None:
                fields.append("publish_time = ?")
                params.append(publish_time)
            elif publish_time == "":
                # 显式传空字符串 = 提取过但没有，写 null
                fields.append("publish_time = NULL")
            if document_time is not None:
                fields.append("document_time = ?")
                params.append(document_time)
            elif document_time == "":
                fields.append("document_time = NULL")
            if not fields:
                return True
            params.append(item_id)
            cur = conn.execute(
                f"UPDATE notices SET {', '.join(fields)} WHERE rowid = ?",
                params,
            )
            conn.commit()
        return cur.rowcount > 0

    # ---- 写作服务回写 ------------------------------------------------------

    def pending_write(self, limit: int = 5) -> list[dict]:
        """旧版：已分类为 notice，只拉没写过的（interpreted_count=0）。"""
        conn = self.connect()
        rows = conn.execute(
            """
            SELECT rowid AS id, url, title, site, column_name, first_seen, category
            FROM notices
            WHERE category = 'notice' AND interpreted_count = 0
            ORDER BY first_seen DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def pending_write_v2(
        self,
        limit: int = 5,
        max_count: int = 3,
        since: str | None = None,
        published_after: str | None = None,
    ) -> list[dict]:
        """新版：写得少的优先，max_count=3 可重复写，published_after 按 publish_time 过滤。"""
        conn = self.connect()
        sql = """
            SELECT rowid AS id, url, title, site, column_name, first_seen, publish_time, document_time, category, interpreted_count
            FROM notices
            WHERE category = 'notice' AND interpreted_count <= ?
        """
        params: list = [max_count]
        if since:
            sql += " AND first_seen >= ?"
            params.append(since)
        if published_after:
            sql += " AND publish_time >= ?"
            params.append(published_after)
        sql += " ORDER BY interpreted_count ASC, first_seen DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def record_interpretation(
        self,
        item_id: int,
        writer: str | None = None,
        article_title: str | None = None,
        article_path: str | None = None,
        status: str = "success",
    ) -> bool:
        """写作完成后：按数字 id 定位，往 interpretations 插记录，主表计数 +1。"""
        conn = self.connect()
        with self._write_lock:
            row = conn.execute(
                "SELECT url FROM notices WHERE rowid = ?", (item_id,)
            ).fetchone()
            if not row:
                return False
            url = row["url"]
            now = _now()
            conn.execute(
                """
                INSERT INTO interpretations
                    (url, writer, article_title, article_path, status, written_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (url, writer, article_title, article_path, status, now),
            )
            conn.execute(
                """
                UPDATE notices
                SET interpreted_count = interpreted_count + 1, last_written_at = ?
                WHERE rowid = ?
                """,
                (now, item_id),
            )
            conn.commit()
        return True
