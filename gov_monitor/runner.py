"""核心逻辑：跑一轮监测，返回新增通知列表。

采集本身是"最保守的 URL 级筛选"：只把栏目页里看起来像详情页的链接收进来，
不判断是通知还是新闻——那是下游 AI 分类服务的事。

状态缓存：维护一个 {url: status_code} 的 JSON 文件，遇到 403/404/412 这种
永久性失败就跳过，不每 5 分钟都去敲一遍 WAF。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import gov_site_list
import requests

from .db import NoticeDB
from .fetcher import fetch_notice_links

logger = logging.getLogger(__name__)

# 并发抓栏目数。政府站不要打太狠，6 个并发足够把一轮压在几分钟内。
MAX_WORKERS = 6

# 这些状态码说明这个 URL 是死链 / WAF 拦死的，下次直接跳过
BAD_STATUSES = {403, 404, 410, 412}


def _load_status_cache(cache_path: Path) -> dict[str, int]:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("状态缓存文件损坏，重新开始: %s", cache_path)
    return {}


def _save_status_cache(cache_path: Path, cache: dict[str, int]) -> None:
    cache_path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _fetch_one(args: tuple) -> tuple:
    """抓单个栏目。在线程里跑，返回 (site, column, links, status_code, error)。

    status_code: 200 成功；HTTP 错误码；-1 网络/超时错误。
    """
    site, column, url, encoding = args
    try:
        links = fetch_notice_links(url, encoding=encoding)
        return site, column, links, 200, None
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else -1
        return site, column, [], code, str(e)
    except Exception as e:  # 超时 / DNS / 连接错误
        return site, column, [], -1, str(e)


def check_new(db_path: str = "notices.db") -> list[dict]:
    """跑一轮监测，返回本轮新增的通知列表。"""
    columns = gov_site_list.load_notice_columns()
    logger.info("加载 %d 个栏目，开始抓取", len(columns))

    db = NoticeDB(db_path)
    known = db.known_urls()
    logger.info("库中已有 %d 条历史 URL", len(known))

    cache_path = Path(db_path).with_name("fetch_status.json")
    status_cache = _load_status_cache(cache_path)

    # 先过一遍：已知坏站直接跳过，不发请求
    tasks = []
    skipped = 0
    for col in columns:
        url = col["url"]
        cached = status_cache.get(url)
        if cached in BAD_STATUSES:
            skipped += 1
            logger.info("跳过已知坏站 [%s/%s] %s (上次 %s)",
                        col["site"], col["column"], url, cached)
            continue
        tasks.append((
            col["site"],
            col["column"],
            url,
            col.get("encoding", "utf-8"),
        ))
    logger.info("跳过 %d 个已知坏站，实际抓取 %d 个", skipped, len(tasks))

    new_items: list[dict] = []
    failed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        # 用 future 直接绑定 url，避免事后反查
        future_to_url = {pool.submit(_fetch_one, t): t[2] for t in tasks}
        for fut in as_completed(future_to_url):
            url = future_to_url[fut]
            site, column, links, code, err = fut.result()
            status_cache[url] = code

            if err:
                failed += 1
                logger.warning(
                    "栏目 %s [%s/%s] code=%s: %s",
                    "坏站" if code in BAD_STATUSES else "失败",
                    site, column, code, err,
                )
                continue

            fresh = [l for l in links if l["url"] not in known]
            if not fresh:
                continue
            items = [
                {"url": l["url"], "title": l["title"], "site": site, "column": column}
                for l in fresh
            ]
            db.insert_new(items)
            for l in fresh:
                known.add(l["url"])
            new_items.extend(items)
            logger.info("[%s/%s] 新增 %d 条", site, column, len(fresh))

    _save_status_cache(cache_path, status_cache)
    db.close()
    logger.info(
        "本轮完成：新增 %d 条，失败 %d，跳过坏站 %d / %d",
        len(new_items), failed, skipped, len(columns),
    )
    return new_items
