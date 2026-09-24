"""API 接口单元测试：用 TestClient 测 HTTP 层。

跑法：
    .venv/bin/python -m pytest gov_monitor/tests/test_api.py -v

【规则】
1. 测试用例只准加不准删，除非用户明确要求。
2. 已有接口不要删、不要改行为/参数/返回结构，要加功能就加新接口（如 /v2/...），不破坏兼容。除非用户明确要求改。
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


def test_get_content(client, tmp_path, monkeypatch):
    """GET /items/{id}/content：mock fetcher，不发外网请求。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
        ("https://example.com/doc1", "关于XX的通知", "站", "栏目", "2026-01-01T00:00:00"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/doc1",)).fetchone()[0]
    conn.close()

    fake_html = """
    <html><body>
    <nav>导航链接</nav>
    <h1>关于XX的通知</h1>
    <p>现将有关事项通知如下：一、XXX</p>
    <p>此通知。</p>
    <footer>版权所有</footer>
    </body></html>
    """
    monkeypatch.setattr("gov_monitor.fetcher.fetch_page", lambda url, encoding="utf-8": fake_html)

    r = client.get(f"/items/{item_id}/content")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == item_id
    assert data["url"] == "https://example.com/doc1"
    assert data["title"] == "关于XX的通知"
    assert "导航" not in data["content"]
    assert "版权" not in data["content"]
    assert "通知" in data["content"]


def test_get_content_404(client):
    r = client.get("/items/999999/content")
    assert r.status_code == 404


def test_get_content_fetch_error(client, tmp_path, monkeypatch):
    """抓页面失败返回 502。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
        ("https://example.com/err", "标题", "站", "栏目", "2026-01-01T00:00:00"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/err",)).fetchone()[0]
    conn.close()

    def boom(url, encoding="utf-8"):
        raise Exception("timeout")
    monkeypatch.setattr("gov_monitor.fetcher.fetch_page", boom)

    r = client.get(f"/items/{item_id}/content")
    assert r.status_code == 502


def test_admin_run(client, monkeypatch):
    """POST /admin/run 触发采集，mock check_new 不发外网。"""
    monkeypatch.setattr("gov_monitor.server.check_new", lambda db_path: [{"url": "x", "title": "y"}])
    r = client.post("/admin/run")
    assert r.status_code == 200
    assert r.json()["started"] is True
    assert r.json()["new"] == 1


def test_interpretation_failed_not_counted(client, tmp_path):
    """写 failed 状态不增加 interpreted_total。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen, category) VALUES (?,?,?,?,?,?)",
        ("https://example.com/fail", "标题", "站", "栏目", "2026-01-01T00:00:00", "notice"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/fail",)).fetchone()[0]
    conn.close()

    r = client.post(f"/items/{item_id}/interpreted",
                    json={"writer": "doubao", "status": "failed"})
    assert r.status_code == 200

    r = client.get("/stats")
    assert r.json()["interpreted_total"] == 0


def test_pending_write_ordering(client, tmp_path):
    """pending-write：interpreted_count 低的优先。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for url, cnt, ts in [
        ("https://example.com/p0", 0, "2026-01-01T00:00:00"),
        ("https://example.com/p1", 1, "2026-01-02T00:00:00"),
        ("https://example.com/p2", 2, "2026-01-03T00:00:00"),
    ]:
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen, category, interpreted_count) VALUES (?,?,?,?,?,?,?)",
            (url, url, "站", "栏目", ts, "notice", cnt),
        )
    conn.commit()
    conn.close()

    r = client.get("/items/pending-write?limit=10")
    items = r.json()["items"]
    assert items[0]["url"] == "https://example.com/p0"


def test_pending_write_v2_default_max_count_3(client, tmp_path):
    """v2 默认 max_count=3，写过1次的也能拉出来。旧接口默认0不变。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen, category, interpreted_count) VALUES (?,?,?,?,?,?,?)",
        ("https://example.com/w1", "写过1次", "站", "栏目", "2026-01-01T00:00:00", "notice", 1),
    )
    conn.commit()
    conn.close()

    # 旧接口（默认0）：拉不到
    r = client.get("/items/pending-write?limit=10")
    assert len(r.json()["items"]) == 0

    # v2（默认3）：能拉到
    r = client.get("/v2/items/pending-write?limit=10")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/w1"


def test_update_times(client, tmp_path):
    """POST /items/{id}/times 回写发布时间和成文时间。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
        ("https://example.com/t1", "标题", "站", "栏目", "2026-01-01T00:00:00"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/t1",)).fetchone()[0]
    conn.close()

    r = client.post(f"/items/{item_id}/times",
                    json={"publish_time": "2026-09-24", "document_time": "2026-09-11"})
    assert r.status_code == 200

    # 再拉 pending-write 应该带上时间字段
    r = client.get("/items/pending-write?limit=10&max_count=0")
    # 这条还没分类成 notice，不在 pending-write 里，直接查 DB
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    row = conn.execute("SELECT publish_time, document_time FROM notices WHERE rowid=?", (item_id,)).fetchone()
    assert row[0] == "2026-09-24"
    assert row[1] == "2026-09-11"
    conn.close()


def test_update_times_404(client):
    r = client.post("/items/999999/times", json={"publish_time": "2026-09-24"})
    assert r.status_code == 404


def test_pending_write_published_after(client, tmp_path):
    """published_after 按 publish_time 过滤。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    # 两条 notice，publish_time 不同
    for url, pt in [("https://example.com/n1", "2026-09-20"), ("https://example.com/n2", "2026-09-24")]:
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen, category, publish_time, interpreted_count) VALUES (?,?,?,?,?,?,?,?)",
            (url, url, "站", "栏目", "2026-09-24T00:00:00", "notice", pt, 0),
        )
    conn.commit()
    conn.close()

    # published_after=2026-09-23 只拉 n2
    r = client.get("/v2/items/pending-write?limit=10&published_after=2026-09-23")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/n2"


def test_list_notices_default_latest(client, tmp_path):
    """不传时间，按最新倒序返回。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for url, pt in [("https://example.com/a", "2026-09-20"), ("https://example.com/b", "2026-09-24")]:
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen, category, publish_time) VALUES (?,?,?,?,?,?,?)",
            (url, url, "站", "栏目", "2026-09-24T00:00:00", "notice", pt),
        )
    conn.commit()
    conn.close()

    r = client.get("/v2/items/notices?limit=10")
    items = r.json()["items"]
    assert items[0]["url"] == "https://example.com/b"  # 最新的在前


def test_list_notices_published_after(client, tmp_path):
    """传 published_after，按增序拉之后的。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for url, pt in [("https://example.com/old", "2026-09-10"),
                    ("https://example.com/mid", "2026-09-20"),
                    ("https://example.com/new", "2026-09-24")]:
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen, category, publish_time) VALUES (?,?,?,?,?,?,?)",
            (url, url, "站", "栏目", "2026-09-24T00:00:00", "notice", pt),
        )
    conn.commit()
    conn.close()

    r = client.get("/v2/items/notices?limit=10&published_after=2026-09-15")
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["url"] == "https://example.com/mid"  # 最早的在前
    assert items[1]["url"] == "https://example.com/new"


def test_list_notices_document_after(client, tmp_path):
    """传 document_after，按成文时间增序拉。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    for url, dt in [("https://example.com/d1", "2026-09-01"),
                    ("https://example.com/d2", "2026-09-15")]:
        conn.execute(
            "INSERT INTO notices (url, title, site, column_name, first_seen, category, document_time) VALUES (?,?,?,?,?,?,?)",
            (url, url, "站", "栏目", "2026-09-24T00:00:00", "notice", dt),
        )
    conn.commit()
    conn.close()

    r = client.get("/v2/items/notices?limit=10&document_after=2026-09-10")
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["url"] == "https://example.com/d2"


def test_get_content_cache(client, tmp_path, monkeypatch):
    """第一次请求抓网页并存缓存，第二次直接命中缓存不再抓。"""
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    conn.execute(
        "INSERT INTO notices (url, title, site, column_name, first_seen) VALUES (?,?,?,?,?)",
        ("https://example.com/cache", "标题", "站", "栏目", "2026-01-01T00:00:00"),
    )
    conn.commit()
    item_id = conn.execute("SELECT rowid FROM notices WHERE url=?", ("https://example.com/cache",)).fetchone()[0]
    conn.close()

    calls = {"n": 0}
    def fake_fetch(url):
        calls["n"] += 1
        return "<html><body><p>正文内容</p></body></html>"
    monkeypatch.setattr("gov_monitor.fetcher.fetch_page", fake_fetch)

    r1 = client.get(f"/items/{item_id}/content")
    assert r1.status_code == 200
    assert r1.json()["cached"] is False
    assert calls["n"] == 1

    r2 = client.get(f"/items/{item_id}/content")
    assert r2.status_code == 200
    assert r2.json()["cached"] is True
    assert calls["n"] == 1  # 第二次没再抓
    assert r2.json()["content"] == r1.json()["content"]
