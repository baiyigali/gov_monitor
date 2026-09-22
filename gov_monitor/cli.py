"""命令行入口：跑一轮监测，或者查看统计。"""

from __future__ import annotations

import sys

from .db import NoticeDB
from .runner import check_new


def run(db_path: str = "notices.db") -> None:
    """跑一轮监测，打印进度和结果。"""
    print("开始监测...")
    new_items = check_new(db_path)
    print(f"\n本轮新增 {len(new_items)} 条通知：")
    for item in new_items:
        print(f"  [{item['site']}/{item['column']}] {item['title'][:50]}")
        print(f"    {item['url']}")

    db = NoticeDB(db_path)
    print(f"\n数据库现有 {db.count()} 条记录")
    db.close()


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
        run(db_path)
    elif cmd == "stats":
        stats(db_path)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
