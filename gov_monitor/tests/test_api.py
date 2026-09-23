"""API 接口单元测试：用 TestClient 测 HTTP 层。

跑法：
    .venv/bin/python -m pytest gov_monitor/tests/test_api.py -v
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    """每个测试用一个干净的临时 DB。"""
    from gov_monitor.server import create_app
    app = create_app(str(tmp_path / "test.db"), poll_interval=999999)
    yield TestClient(app)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_pending_classify_returns_id(client, tmp_path):
    # 直接往 DB 插两条
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for i in (1, 2):
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
            (f"https://example.com/{i}", f"标题{i}", "测试站", "测试栏目", "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()

    r = client.get("/items/pending-classify?limit=10")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert all("id" in it for it in items)
    assert all(isinstance(it["id"], int) for it in items)


def test_update_category(client, tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
        ("https://example.com/3", "标题3", "测试站", "栏目", "2026-01-01T00:00:00"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/3",)).fetchone()[0]
    conn.close()

    r = client.post(f"/items/{item_id}/category", json={"category": "notice"})
    assert r.status_code == 200
    assert r.json()["category"] == "notice"

    # 再查应该不在 pending 里
    r = client.get("/items/pending-classify?limit=100")
    pending_urls = {it["url"] for it in r.json()["items"]}
    assert "https://example.com/3" not in pending_urls


def test_update_category_404(client):
    r = client.post("/items/999999/category", json={"category": "notice"})
    assert r.status_code == 404


def test_pending_write_filters_by_category(client, tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for url, cat in [("https://example.com/a", "notice"), ("https://example.com/b", "news")]:
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
            (url, url, "站", "栏目", "2026-01-01T00:00:00"),
        )
    conn.commit()
    # 直接 UPDATE 分类
    conn.execute("UPDATE notices SET category='notice' WHERE url='https://example.com/a'")
    conn.execute("UPDATE notices SET category='news' WHERE url='https://example.com/b'")
    conn.commit()
    conn.close()

    r = client.get("/items/pending-write?limit=10")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/a"


def test_record_interpretation_increments_count(client, tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen, category) VALUES (?,?,?,?,?,?)",
        ("https://example.com/c", "标题C", "站", "栏目", "2026-01-01T00:00:00", "notice"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/c",)).fetchone()[0]
    conn.close()

    r = client.post(f"/items/{item_id}/interpreted",
                    json={"writer": "doubao", "article_title": "解读1"})
    assert r.status_code == 200

    r = client.get("/items/pending-write?limit=10")
    assert len(r.json()["items"]) == 0

    r = client.get("/stats")
    assert r.json()["interpreted_total"] == 1


def test_record_interpretation_404(client):
    r = client.post("/items/999999/interpreted", json={"writer": "x"})
    assert r.status_code == 404


def test_stats(client, tmp_path):
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for i in (1, 2):
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
            (f"https://example.com/s{i}", f"标题{i}", "站", "栏目", "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()

    r = client.get("/stats")
    data = r.json()
    assert data["total"] == 2
    assert data["by_category"]["pending"] == 2
    assert data["interpreted_total"] == 0
