"""Agent SOCKS5 proxy list and the shell commands that carry a proxy to a VPS.

Proxies are stored encrypted as one JSON list (secret "agent_proxies"). Commands are
built here with shlex quoting; the URL is percent-encoded, so it never contains quotes,
backslashes or whitespace and is safe inside the curl config line as well.
"""
from __future__ import annotations

import ipaddress
import json
import re
import shlex
from urllib.parse import quote, unquote, urlparse

from .core import uid
from .network import validate_agent_proxy

SECRET = "agent_proxies"
LEGACY_SECRET = "agent_proxy"
MAX_PROXIES = 50
HOSTNAME = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?)*$")


def proxy_url(entry: dict) -> str:
    host = entry["host"]
    if ":" in host:
        host = f"[{host}]"
    auth = ""
    if entry.get("username"):
        auth = quote(entry["username"], safe="")
        if entry.get("password"):
            auth += ":" + quote(entry["password"], safe="")
        auth += "@"
    return f"socks5h://{auth}{host}:{entry['port']}"


def endpoint(entry: dict) -> str:
    """host:port as reported by an Agent, used to recognise which proxy a node uses."""
    return f"[{entry['host']}]:{entry['port']}" if ":" in entry["host"] else f"{entry['host']}:{entry['port']}"


def endpoint_of_url(url: str) -> str:
    p = urlparse(url)
    if not p.hostname or not p.port:
        return ""
    return f"[{p.hostname}]:{p.port}" if ":" in p.hostname else f"{p.hostname}:{p.port}"


def clean(body: dict, current: dict | None = None) -> dict:
    entry = dict(current or {})
    host = str(body.get("host", entry.get("host", ""))).strip().strip("[]")
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        if not HOSTNAME.match(host):
            raise ValueError("代理地址应为 IP 或域名，不含协议和端口")
    try:
        port = int(body.get("port", entry.get("port", 0)))
    except (TypeError, ValueError):
        port = 0
    if not 1 <= port <= 65535:
        raise ValueError("代理端口应为 1～65535")
    username = str(body.get("username", entry.get("username", ""))).strip()
    password = str(body.get("password", "")) or (entry.get("password", "") if username else "")
    note = str(body.get("note", entry.get("note", ""))).strip()
    if len(username.encode()) > 255 or len(password.encode()) > 255:
        raise ValueError("SOCKS5 用户名和密码各不能超过 255 字节")
    if password and not username:
        raise ValueError("填写密码时必须同时填写用户名")
    if len(note) > 60:
        raise ValueError("备注不能超过 60 个字符")
    entry.update(host=host, port=port, username=username, password=password, note=note)
    validate_agent_proxy(proxy_url(entry))
    return entry


def load(store, db) -> list[dict]:
    raw = store.secret(SECRET, db)
    if raw:
        return json.loads(raw)
    legacy = store.secret(LEGACY_SECRET, db)
    entries = []
    if legacy:
        # v0.1.3 stored a single default URL; turn it into the first list entry.
        p = urlparse(legacy)
        entries.append({"id": uid(), "host": p.hostname or "", "port": p.port or 1080,
                        "username": unquote(p.username or ""), "password": unquote(p.password or ""), "note": "默认代理"})
        save(store, db, entries)
        store.set_secret(LEGACY_SECRET, "", db)
    return entries


def save(store, db, entries: list[dict]):
    store.set_secret(SECRET, json.dumps(entries, ensure_ascii=False), db)


def public(entry: dict, used_by: list[str]) -> dict:
    return {"id": entry["id"], "host": entry["host"], "port": entry["port"], "username": entry["username"],
            "has_password": bool(entry["password"]), "note": entry["note"], "endpoint": endpoint(entry), "nodes": used_by}


def label(entry: dict) -> str:
    return f"{entry['note'] or '未命名代理'}（{endpoint(entry)}）"


q = shlex.quote


def piped(url: str, server: str, args: str) -> str:
    # printf is a shell builtin: the URL reaches curl and the installer through pipes,
    # never through a process argument list visible in `ps`.
    return (f"P={q(url)}; printf 'proxy = \"%s\"\\n' \"$P\" | curl -K - --noproxy '' -fsS {q(server+'/install.sh')} -o install-sentinel.sh"
            f" && printf '%s\\n' \"$P\" | sudo bash install-sentinel.sh --server {q(server)} {args} --proxy-stdin; unset P")


def direct(server: str, args: str) -> str:
    return f"curl --noproxy '*' -fsS {q(server+'/install.sh')} -o install-sentinel.sh && sudo bash install-sentinel.sh --server {q(server)} {args}"


def install_command(server: str, token: str, url: str = "") -> str:
    return piped(url, server, f"--token {q(token)}") if url else direct(server, f"--token {q(token)}")


def switch_command(server: str, url: str = "") -> str:
    """Upgrade the Agent and switch its proxy; the installer keeps the old config if the new path fails."""
    return piped(url, server, "--upgrade") if url else direct(server, "--upgrade --direct")


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_enroll(server: str, token: str, node_id: str, url: str = "") -> str:
    command = f'.\\.venv\\Scripts\\python.exe -m sentinel.agent enroll --server "{server}" --token "{token}" --data "agent-data/{node_id}"'
    return f"{ps_quote(url)} | {command} --proxy-stdin" if url else command


def windows_switch(node_id: str, url: str = "") -> str:
    command = f'.\\.venv\\Scripts\\python.exe -m sentinel.agent configure --data "agent-data/{node_id}"'
    return f"{ps_quote(url)} | {command} --proxy-stdin" if url else f"{command} --direct"
