"""Web 服务：把采集结果和下游队列暴露成 HTTP API。

采集在服务后台按 poll_interval 自动跑一轮；下游（AI 分类服务、写作服务）
通过这几个接口拉活、回写，不直接碰 SQLite 文件。

【规则】已有接口不删不改，要加功能就加新接口（如 /v2/...），不破坏兼容。

  GET  /health
  GET  /stats
  GET  /items/pending-classify?limit=20   → AI 分类服务拉待分类（返回带数字 id）
  GET  /items/{id}/content                → 抓详情页正文返回给分类服务
  POST /items/{id}/category               → AI 分类服务回写分类
  POST /items/{id}/times                  → 回写 publish_time / document_time
  GET  /items/pending-write?limit=5       → 写作服务拉可写通知（只拉没写过的）
  GET  /v2/items/pending-write           → 新版：max_count=3 可重复写，支持 published_after
  POST /items/{id}/interpreted            → 写作服务写完回写计数+1
  POST /admin/run                         → 手动触发一轮采集
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .db import NoticeDB
from .runner import check_new

logger = logging.getLogger(__name__)


class CategoryIn(BaseModel):
    category: str  # pending / notice / news / other


class TimesIn(BaseModel):
    publish_time: str | None = None
    document_time: str | None = None


class InterpretedIn(BaseModel):
    writer: str | None = None
    article_title: str | None = None
    article_path: str | None = None
    status: str = "success"  # success / failed


def create_app(db_path: str = "notices.db", poll_interval: int = 300) -> FastAPI:
    db = NoticeDB(db_path)
    db.connect()  # 启动即建表 / 迁移
    run_lock = threading.Lock()  # 防止一轮没跑完又触发下一轮

    def _trigger_run() -> int:
        """触发一轮采集，返回新增条数；正在跑就跳过。"""
        if not run_lock.acquire(blocking=False):
            logger.info("上一轮采集还在进行，跳过本次触发")
            return 0
        try:
            new_items = check_new(db_path)
            return len(new_items)
        except Exception as e:
            logger.exception("采集轮次异常: %s", e)
            return 0
        finally:
            run_lock.release()

    def _scheduler_loop() -> None:
        """后台线程：每 poll_interval 秒跑一轮。"""
        # 启动后先等一个间隔再跑（服务刚起来，不必立刻跑）
        while True:
            time.sleep(poll_interval)
            logger.info("定时触发采集")
            _trigger_run()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        t = threading.Thread(target=_scheduler_loop, daemon=True)
        t.start()
        logger.info("后台采集调度已启动，间隔 %d 秒", poll_interval)
        yield

    app = FastAPI(title="gov-monitor", version="1.0.4", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/stats")
    def stats():
        total = db.count()
        rows = db.connect().execute(
            "SELECT category, COUNT(*) AS c FROM notices GROUP BY category"
        ).fetchall()
        by_category = {r["category"] or "pending": r["c"] for r in rows}
        interpreted = db.connect().execute(
            "SELECT COUNT(*) AS c FROM interpretations WHERE status='success'"
        ).fetchone()["c"]
        return {
            "total": total,
            "by_category": by_category,
            "interpreted_total": interpreted,
        }

    @app.get("/items/pending-classify")
    def pending_classify(limit: int = 20):
        return {"items": db.pending_classify(limit)}

    @app.get("/items/{item_id}/content")
    def get_content(item_id: int):
        """抓详情页正文，返回给分类服务用，不用前端自己开网页。"""
        item = db.get_item(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="item not found")
        from .fetcher import fetch_page
        from bs4 import BeautifulSoup
        try:
            html = fetch_page(item["url"])
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            lines = [l.strip() for l in soup.get_text(separator="\n").splitlines() if l.strip()]
            content = "\n".join(lines)[:3000]
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"fetch failed: {e}")
        return {"id": item_id, "url": item["url"], "title": item["title"], "content": content}

    @app.post("/items/{item_id}/category")
    def set_category(item_id: int, body: CategoryIn):
        if not db.update_category(item_id, body.category):
            raise HTTPException(status_code=404, detail="item not found")
        return {"ok": True, "id": item_id, "category": body.category}

    @app.post("/items/{item_id}/times")
    def set_times(item_id: int, body: TimesIn):
        if not db.update_times(item_id, body.publish_time, body.document_time):
            raise HTTPException(status_code=404, detail="item not found")
        return {"ok": True, "id": item_id}

    @app.get("/items/pending-write")
    def pending_write(limit: int = 5):
        return {"items": db.pending_write(limit)}

    @app.get("/v2/items/notices")
    def list_notices(limit: int = 10, published_after: str | None = None, document_after: str | None = None):
        return {"items": db.list_notices(limit=limit, published_after=published_after, document_after=document_after)}

    @app.get("/v2/items/pending-write")
    def pending_write_v2(limit: int = 5, max_count: int = 3, since: str | None = None, published_after: str | None = None):
        return {"items": db.pending_write_v2(limit=limit, max_count=max_count, since=since, published_after=published_after)}

    @app.post("/items/{item_id}/interpreted")
    def mark_interpreted(item_id: int, body: InterpretedIn):
        if not db.record_interpretation(
            item_id, body.writer, body.article_title, body.article_path, body.status
        ):
            raise HTTPException(status_code=404, detail="item not found")
        return {"ok": True, "id": item_id}

    @app.post("/admin/run")
    def admin_run():
        new_count = _trigger_run()
        return {"started": True, "new": new_count}

    return app
