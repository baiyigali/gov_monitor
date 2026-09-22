"""URL 过滤：从栏目页的一堆链接里筛出通知详情页。"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

# 附件类后缀，这些肯定不是通知详情页
EXCLUDE_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".zip", ".rar", ".7z", ".gz", ".tar",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".msi", ".apk", ".dmg",
    ".mp3", ".mp4", ".avi", ".mov",
    ".css", ".js", ".ico", ".svg",
}

# URL 里包含这些词的，大概率是导航/功能页，不是通知
EXCLUDE_KEYWORDS = {
    "javascript:", "mailto:", "tel:",
    "/index", "/list", "/search", "/login", "/logout",
    "/about", "/contact", "/nav", "/menu",
    "page=", "p=",  # 分页参数
    "index_",  # 很多 gov 站分页是 index_2.shtml
}


def filter_links(
    raw_links: list[tuple[str, str]],
    base_url: str,
) -> list[dict]:
    """
    从原始链接列表里筛出通知详情页。

    输入：[(href, title), ...]
    输出：[{"url": ..., "title": ...}, ...]
    """
    base_domain = urlparse(base_url).netloc
    results = []

    for href, title in raw_links:
        href = href.strip()
        title = title.strip()

        # 空链接
        if not href or not title:
            continue

        # 排除锚点
        if href.startswith("#"):
            continue

        # 排除协议类
        if any(kw in href.lower() for kw in EXCLUDE_KEYWORDS):
            continue

        # 补全成绝对 URL
        absolute = urljoin(base_url, href)

        # 同域名过滤
        parsed = urlparse(absolute)
        if parsed.netloc != base_domain:
            continue

        # 排除附件后缀
        path_lower = parsed.path.lower()
        if any(path_lower.endswith(ext) for ext in EXCLUDE_EXTENSIONS):
            continue

        results.append({"url": absolute, "title": title})

    return results
