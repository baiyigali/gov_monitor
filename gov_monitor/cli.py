"""命令行入口：跑一轮监测，或者查看统计。"""

from __future__ import annotations

import sys

import gov_site_list

from .db import NoticeDB
from .fetcher import fetch_notice_links


def run_once(db_path: str = "notices.db") -> None:
    """跑一轮：遍历所有栏目，发现新通知入库。"""
    columns = gov_site_list.load_notice_columns()
    print(f"共 {len(columns)} 个栏目待监测")

    db = NoticeDB(db_path)
    known = db.known_urls()
    print(f"数据库已有 {len(known)} 条记录")

    total_new = 0
    errors = 0

    for i, col in enumerate(columns, 1):
        site = col["site"]
        column = col["column"]
        url = col["url"]
        encoding = col.get("encoding", "utf-8")

        print(f"[{i}/{len(columns)}] {site} / {column} ... ", end="", flush=True)

        try:
            links = fetch_notice_links(url, encoding=encoding)
            # 过滤掉已有的
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
                inserted = db.insert_new(items)
                for l in new_links:
                    known.add(l["url"])
                total_new += inserted
                print(f"发现 {len(links)} 条链接，新增 {inserted} 条")
            else:
                print(f"发现 {len(links)} 条链接，无新增")

        except Exception as e:
            errors += 1
            print(f"失败: {e}")

    db.close()
    print(f"\n完成。本轮新增 {total_new} 条，失败 {errors} 个栏目。")
    print(f"数据库现有 {NoticeDB(db_path).count()} 条记录")


def stats(db_path: str = "notices.db") -> None:
    """显示数据库统计。"""
    db = NoticeDB(db_path)
    total = db.count()
    print(f"总记录数: {total}")
    db.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: gov-monitor run [db_path]")
        print("      gov-monitor stats [db_path]")
        sys.exit(1)

    cmd = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else "notices.db"

    if cmd == "run":
        run_once(db_path)
    elif cmd == "stats":
        stats(db_path)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
