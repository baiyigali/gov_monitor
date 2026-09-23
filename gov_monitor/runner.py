"""核心逻辑：跑一轮监测，返回新增通知列表。

采集本身是"最保守的 URL 级筛选"：只把栏目页里看起来像详情页的链接收进来，
不判断是通知还是新闻——那是下游 AI 分类服务的事。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import gov_site_list

from .db import NoticeDB
from .fetcher import fetch_notice_links

logger = logging.getLogger(__name__)

# 并发抓栏目数。政府站不要打太狠，6 个并发足够把一轮压在几分钟内。
MAX_WORKERS = 6


def _fetch_one(args: tuple) -> tuple:
    """抓单个栏目。在线程里跑，只返回结果，不碰 DB。"""
    site, column, url, encoding = args
    try:
        links = fetch_notice_links(url, encoding=encoding)
        return site, column, links, None
    except Exception as e:  # 单栏目失败不影响整体
        logger.warning("栏目抓取失败 [%s/%s] %s: %s", site, column, url, e)
        return site, column, [], str(e)


def check_new(db_path: str = "notices.db") -> list[dict]:
    """跑一轮监测，返回本轮新增的通知列表。

    返回的每个元素是 dict：url / title / site / column / first_seen
    """
    columns = gov_site_list.load_notice_columns()
    logger.info("加载 %d 个栏目，开始抓取", len(columns))

    db = NoticeDB(db_path)
    known = db.known_urls()
    logger.info("库中已有 %d 条历史 URL", len(known))

    tasks = [
        (
            col["site"],
            col["column"],
            col["url"],
            col.get("encoding", "utf-8"),
        )
        for col in columns
    ]

    new_items: list[dict] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = [pool.submit(_fetch_one, t) for t in tasks]
        for fut in as_completed(futures):
            site, column, links, err = fut.result()
            if err:
                failed += 1
                continue
            fresh = [l for l in links if l["url"] not in known]
            if not fresh:
                continue
            items = [
                {
                    "url": l["url"],
                    "title": l["title"],
                    "site": site,
                    "column": column,
                }
                for l in fresh
            ]
            # DB 写操作都在主线程串行做，避免连接竞争
            db.insert_new(items)
            for l in fresh:
                known.add(l["url"])
            new_items.extend(items)
            logger.info("[%s/%s] 新增 %d 条", site, column, len(fresh))

    db.close()
    logger.info(
        "本轮完成：新增 %d 条，失败栏目 %d / %d",
        len(new_items), failed, len(columns),
    )
    return new_items
