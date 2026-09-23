"""API 逻辑单元测试：直接测 NoticeDB 的方法（API 只是它的薄包装）。

不依赖 fastapi TestClient / httpx，CI 上零外部依赖。
跑法：
    .venv/bin/python -m pytest gov_monitor/tests/test_api.py -v
"""

from __future__ import annotations

import sqlite3

import pytest


@pytest.fixture()
def db(tmp_path):
    from gov_monitor.db import NoticeDB
    d = NoticeDB(str(tmp_path / "test.db"))
    d.connect()
    yield d
    d.close()


def _insert_row(db: NoticeDB, url: str, title: str = "测试标题",
                site: str = "测试站", column: str = "测试栏目") -> int:
    db.insert_new([{"url": url, "title": title, "site": site, "column": column}])
    conn = db.connect()
    row = conn.execute("SELECT rowid FROM notices WHERE url=?", (url,)).fetchone()
    return row[0]


def test_insert_and_known_urls(db):
    assert db.count() == 0
    _insert_row(db, "https://example.com/1")
    assert db.count() == 1
    assert "https://example.com/1" in db.known_urls()


def test_pending_classify_returns_id(db):
    _insert_row(db, "https://example.com/1", title="第一条")
    _insert_row(db, "https://example.com/2", title="第二条")

    items = db.pending_classify(limit=10)
    assert len(items) == 2
    assert all("id" in it for it in items)
    assert all(isinstance(it["id"], int) for it in items)
    urls = {it["url"] for it in items}
    assert "https://example.com/1" in urls


def test_update_category(db):
    item_id = _insert_row(db, "https://example.com/3")
    assert db.update_category(item_id, "notice") is True

    # 标了 notice 后不在 pending 里
    pending_urls = {it["url"] for it in db.pending_classify(100)}
    assert "https://example.com/3" not in pending_urls


def test_update_category_not_found(db):
    assert db.update_category(999999, "notice") is False


def test_pending_write_filters_by_category(db):
    id1 = _insert_row(db, "https://example.com/a", title="通知A")
    id2 = _insert_row(db, "https://example.com/b", title="新闻B")

    db.update_category(id1, "notice")
    db.update_category(id2, "news")

    items = db.pending_write(limit=10)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/a"


def test_record_interpretation_increments_count(db):
    item_id = _insert_row(db, "https://example.com/c")
    db.update_category(item_id, "notice")

    assert db.record_interpretation(item_id, writer="doubao", article_title="解读1") is True

    # 写完后不在 pending-write
    assert len(db.pending_write(10)) == 0

    # interpretations 表有记录
    conn = db.connect()
    count = conn.execute("SELECT COUNT(*) FROM interpretations").fetchone()[0]
    assert count == 1

    # 主表 interpreted_count = 1
    row = conn.execute(
        "SELECT interpreted_count FROM notices WHERE rowid=?", (item_id,)
    ).fetchone()
    assert row[0] == 1


def test_record_interpretation_not_found(db):
    assert db.record_interpretation(999999, writer="x") is False
