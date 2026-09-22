"""gov-watcher: 政府网站通知监测，发现新通知落 SQLite。"""

from .db import NoticeDB
from .fetcher import fetch_notice_links
from .filter import filter_links

__all__ = ["NoticeDB", "fetch_notice_links", "filter_links"]
__version__ = "0.1.0"
