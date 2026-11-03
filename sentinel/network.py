from __future__ import annotations

from urllib.parse import urlparse
import httpx


def validate_url(url: str, allow_local_http=True):
    p = urlparse(url)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise ValueError("主控地址不能包含凭据、查询参数或片段")
    if p.scheme != "https" and not (allow_local_http and p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost", "::1")):
        raise ValueError("远程主控必须使用 HTTPS；HTTP 仅允许本机测试")
    return url.rstrip("/")


def validate_proxy(proxy: str):
    if not proxy:
        return ""
    p = urlparse(proxy)
    if p.scheme not in ("socks5", "socks5h") or not p.hostname or not p.port:
        raise ValueError("代理格式应为 socks5h://主机:端口，可包含用户名与密码")
    if p.path not in ("", "/") or p.query or p.fragment:
        raise ValueError("SOCKS5 代理地址格式无效")
    return proxy


def validate_agent_proxy(proxy: str):
    """A proxy that is embedded in a generated shell command and a curl config line."""
    proxy = validate_proxy(proxy.strip())
    if any(ch.isspace() or ch in '"\\' for ch in proxy):
        raise ValueError("代理地址不能包含空白、双引号或反斜杠；用户名或密码中的特殊字符请使用百分号编码")
    return proxy


def client(proxy="", timeout=30, transport=None):
    # HTTPX SOCKS transport forwards the hostname to the proxy, no local target DNS.
    # Disabling environment overrides prevents accidental NO_PROXY/direct fallback.
    return httpx.Client(proxy=validate_proxy(proxy) or None, timeout=httpx.Timeout(timeout, connect=10), trust_env=False, follow_redirects=False, transport=transport)
