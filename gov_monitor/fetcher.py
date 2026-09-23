"""抓取栏目页，解析出链接列表。

HTTP 层做了几件兼容处理：
- trust_env=False：不走系统/环境变量代理。政府站直连。
- 自定义 SSL adapter：放宽到 SECLEVEL=1 并允许 legacy renegotiation，兼容老 TLS 站。
- 浏览器 UA：很多政府站 WAF 直接拦 python-requests 默认 UA（返回 403），
  只加一个 UA 就能过；不加完整 Accept/Accept-Language 头，避免触发瑞数那种 JS challenge。
- 重试：连接错误/超时自动重试 2 次。
"""

from __future__ import annotations

import ssl

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.util.ssl_ import create_urllib3_context

from .filter import filter_links

TIMEOUT = 15

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class _LegacySSLAdapter(HTTPAdapter):
    """允许旧 TLS 协议握手 + 连接错误自动重试。"""

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        try:
            ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        except ssl.SSLError:
            pass
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _build_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # 忽略 HTTP_PROXY/HTTPS_PROXY/NO_PROXY
    s.headers.update({"User-Agent": BROWSER_UA})

    retry = Retry(
        total=2,
        backoff_factor=0.5,
        connect=2,
        read=2,
        status_forcelist=[],  # 4xx/5xx 不重试，只重试连接层错误
    )
    adapter = _LegacySSLAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


_session = _build_session()


def fetch_page(url: str, encoding: str = "utf-8") -> str:
    """抓取页面 HTML 文本。"""
    resp = _session.get(url, timeout=TIMEOUT)
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
