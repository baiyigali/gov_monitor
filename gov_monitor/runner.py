"""核心逻辑：跑一轮监测，返回新增通知列表。"""

from __future__ import annotations

import gov_site_list

from .db import NoticeDB
from .fetcher import fetch_notice_links


def check_new(db_path: str = "notices.db") -> list[dict]:
    """
    跑一轮监测，返回本轮新增的通知列表。

    返回的每个元素是 dict：
    - url: 通知详情页 URL
    - title: 通知标题
    - site: 站点名称
    - column: 栏目名称
    - first_seen: 我们第一次抓到的时间
    """
    columns = gov_site_list.load_notice_columns()

    db = NoticeDB(db_path)
    known = db.known_urls()

    new_items = []

    for col in columns:
        site = col["site"]
        column = col["column"]
        url = col["url"]
        encoding = col.get("encoding", "utf-8")

        try:
            links = fetch_notice_links(url, encoding=encoding)
            new_links = [l for l in links if l["url"] not in known]

            if new_links:
                items = [
                    {
                        "url": l["url"],
                        "title": l["title"],
                        "site": site,
                        "column": column,
                    }
                    for l in new_links
                ]
                db.insert_new(items)
                for l in new_links:
                    known.add(l["url"])
                new_items.extend(items)

        except Exception:
            # 单个栏目失败就跳过，不影响整体
            pass

    db.close()
    return new_items
