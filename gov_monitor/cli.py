"""命令行入口：跑一轮监测、查看统计、或启动 Web 服务。"""

from __future__ import annotations

import logging
import os
import sys

from .db import NoticeDB
from .runner import check_new


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def run(db_path: str = "notices.db") -> None:
    """跑一轮监测，打印进度和结果。"""
    _setup_logging()
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


def serve(db_path: str = "notices.db") -> None:
    """启动 Web 服务，暴露 HTTP API，后台按间隔自动采集。

    host / port / 采集间隔从环境变量读，方便 systemd 配置：
      GOV_MONITOR_HOST     默认 0.0.0.0
      GOV_MONITOR_PORT     默认 8000
      GOV_MONITOR_INTERVAL 默认 300（秒，即 5 分钟）
    """
    import uvicorn

    from .server import create_app

    _setup_logging()
    host = os.environ.get("GOV_MONITOR_HOST", "0.0.0.0")
    port = int(os.environ.get("GOV_MONITOR_PORT", "8000"))
    interval = int(os.environ.get("GOV_MONITOR_INTERVAL", "300"))

    app = create_app(db_path, poll_interval=interval)
    uvicorn.run(app, host=host, port=port, log_level="info")


def main() -> None:
    if len(sys.argv) < 2:
        print("用法:")
        print("  gov-monitor run [db_path]            跑一轮采集")
        print("  gov-monitor stats [db_path]          查看统计")
        print("  gov-monitor serve [db_path]          启动 Web 服务（后台定时采集）")
        sys.exit(1)

    cmd = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else "notices.db"

    if cmd == "run":
        run(db_path)
    elif cmd == "stats":
        stats(db_path)
    elif cmd == "serve":
        serve(db_path)
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
