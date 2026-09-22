"""抓取栏目页，解析出链接列表。"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup

from .filter import filter_links


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

TIMEOUT = 15


def fetch_page(url: str, encoding: str = "utf-8") -> str:
    """抓取页面 HTML 文本。"""
    resp = requests.get(url, headers=DEFAULT_HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = encoding
    return resp.text


def extract_links(html: str) -> list[tuple[str, str]]:
    """从 HTML 里提取所有 <a> 标签的 (href, text)。"""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True)
        if text:
            links.append((href, text))
    return links


def fetch_notice_links(
    url: str,
    encoding: str = "utf-8",
) -> list[dict]:
    """
    抓栏目页，过滤后返回通知详情页链接列表。

    输出：[{"url": ..., "title": ...}, ...]
    """
    html = fetch_page(url, encoding=encoding)
    raw_links = extract_links(html)
    return filter_links(raw_links, base_url=url)
