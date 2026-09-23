"""API 接口单元测试：用临时 DB + TestClient，不发外网请求。

跑法：
    .venv/bin/python -m pytest gov_monitor/tests/test_api.py -v
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    """每个测试用一个干净的临时 DB。"""
    db = tmp_path / "test.db"
    from gov_monitor.server import create_app
    app = create_app(str(db), poll_interval=999999)
    yield TestClient(app)


def _insert_row(db_path: str, url: str, title: str = "测试标题",
                site: str = "测试站", column: str = "测试栏目"):
    """直接往临时 DB 插一条，模拟采集结果。"""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen) "
        "VALUES (?, ?, ?, ?, '2026-01-01T00:00:00')",
        (url, title, site, column),
    )
    conn.commit()
    row = conn.execute("SELECT rowid FROM notices WHERE url=?", (url,)).fetchone()
    conn.close()
    return row[0]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_pending_classify_returns_id(client, tmp_path):
    db_path = str(tmp_path / "test.db")
    _insert_row(db_path, "https://example.com/1", title="第一条")
    _insert_row(db_path, "https://example.com/2", title="第二条")

    r = client.get("/items/pending-classify?limit=10")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    # 必须带数字 id
    assert all("id" in it for it in items)
    assert all(isinstance(it["id"], int) for it in items)
    # URL 在返回里
    urls = {it["url"] for it in items}
    assert "https://example.com/1" in urls


def test_update_category(client, tmp_path):
    db_path = str(tmp_path / "test.db")
    item_id = _insert_row(db_path, "https://example.com/3")

    r = client.post(f"/items/{item_id}/category", json={"category": "notice"})
    assert r.status_code == 200
    assert r.json()["category"] == "notice"

    # 再查应该不在 pending 里了
    r = client.get("/items/pending-classify?limit=100")
    pending_urls = {it["url"] for it in r.json()["items"]}
    assert "https://example.com/3" not in pending_urls


def test_update_category_404(client):
    r = client.post("/items/999999/category", json={"category": "notice"})
    assert r.status_code == 404


def test_pending_write_filters_by_category(client, tmp_path):
    db_path = str(tmp_path / "test.db")
    id1 = _insert_row(db_path, "https://example.com/a", title="通知A")
    id2 = _insert_row(db_path, "https://example.com/b", title="新闻B")

    # 只有 id1 标成 notice
    client.post(f"/items/{id1}/category", json={"category": "notice"})
    client.post(f"/items/{id2}/category", json={"category": "news"})

    r = client.get("/items/pending-write?limit=10")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/a"


def test_record_interpretation_increments_count(client, tmp_path):
    db_path = str(tmp_path / "test.db")
    item_id = _insert_row(db_path, "https://example.com/c")
    client.post(f"/items/{item_id}/category", json={"category": "notice"})

    # 第一次写作
    r = client.post(f"/items/{item_id}/interpreted",
                    json={"writer": "doubao", "article_title": "解读1"})
    assert r.status_code == 200

    # 写完后应该不在 pending-write 里了
    r = client.get("/items/pending-write?limit=10")
    assert len(r.json()["items"]) == 0

    # stats 里 interpreted_total = 1
    r = client.get("/stats")
    assert r.json()["interpreted_total"] == 1


def test_record_interpretation_404(client):
    r = client.post("/items/999999/interpreted", json={"writer": "x"})
    assert r.status_code == 404


def test_stats(client, tmp_path):
    db_path = str(tmp_path / "test.db")
    _insert_row(db_path, "https://example.com/s1", title="站1")
    _insert_row(db_path, "https://example.com/s2", title="站2")

    r = client.get("/stats")
    data = r.json()
    assert data["total"] == 2
    assert data["by_category"]["pending"] == 2
    assert data["interpreted_total"] == 0
