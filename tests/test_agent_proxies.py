"""Agent proxy list, generated install / switch commands and proxy reporting."""
import io
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import report, sample
from sentinel import proxies
from sentinel.agent import read_proxy
from sentinel.server import create_app

PROXY = {"host": "203.0.113.8", "port": 1080, "username": "user", "password": "p@ss'w:rd", "note": "香港中转"}
URL = "socks5h://user:p%40ss%27w%3Ard@203.0.113.8:1080"


def add(client, **overrides):
    response = client.post("/api/agent-proxies", json={**PROXY, **overrides})
    assert response.status_code == 200, response.text
    return response.json()


def test_proxy_list_hides_password_and_encodes_url(client, app):
    created = add(client)
    assert created["endpoint"] == "203.0.113.8:1080" and created["has_password"] is True
    listed = client.get("/api/agent-proxies").json()["proxies"]
    assert "p@ss" not in json.dumps(listed) and listed[0]["note"] == "香港中转"
    assert b"p@ss" not in app.state.store.path.read_bytes()
    with app.state.store.connect() as db:
        assert proxies.proxy_url(proxies.load(app.state.store, db)[0]) == URL


@pytest.mark.parametrize("overrides", [
    {"host": "socks5://1.2.3.4"}, {"host": "1.2.3.4:1080"}, {"host": "bad host"},
    {"port": 0}, {"port": 70000}, {"port": "abc"},
    {"username": "", "password": "only-password"}, {"note": "长" * 61},
])
def test_proxy_validation(client, overrides):
    assert client.post("/api/agent-proxies", json={**PROXY, **overrides}).status_code == 400


def test_ipv6_and_anonymous_proxy(client, app):
    add(client, host="2001:db8::1", username="", password="")
    with app.state.store.connect() as db:
        assert proxies.proxy_url(proxies.load(app.state.store, db)[0]) == "socks5h://[2001:db8::1]:1080"


def test_update_keeps_or_clears_password(client, app):
    proxy_id = add(client)["id"]
    assert client.put(f"/api/agent-proxies/{proxy_id}", json={"note": "改名", "password": ""}).json()["has_password"] is True
    assert client.put(f"/api/agent-proxies/{proxy_id}", json={"clear_password": True}).json()["has_password"] is False
    assert client.delete(f"/api/agent-proxies/{proxy_id}").status_code == 200
    assert client.get("/api/agent-proxies").json()["proxies"] == []


def test_install_offers_one_command_per_proxy(client):
    proxy_id = add(client)["id"]
    node_id = client.post("/api/nodes", json={"name": "代理节点"}).json()["id"]
    data = client.post(f"/api/nodes/{node_id}/install").json()
    assert "--proxy" not in data["linux_command"]
    [option] = data["proxies"]
    assert option["id"] == proxy_id and option["label"] == "香港中转（203.0.113.8:1080）"
    assert URL in option["linux_command"] and "--proxy-stdin" in option["linux_command"] and data["token"] in option["linux_command"]
    assert option["windows_command"].startswith(f"'{URL}' | ") and option["windows_command"].endswith("--proxy-stdin")


def test_switch_command_upgrades_and_switches(client, node):
    proxy_id = add(client)["id"]
    via_proxy = client.post(f"/api/nodes/{node[0]}/switch-proxy", json={"proxy_id": proxy_id}).json()
    assert "--upgrade --proxy-stdin" in via_proxy["linux_command"] and URL in via_proxy["linux_command"]
    direct = client.post(f"/api/nodes/{node[0]}/switch-proxy", json={}).json()
    assert "--upgrade --direct" in direct["linux_command"] and direct["target"] == "直连主控"
    assert client.post(f"/api/nodes/{node[0]}/switch-proxy", json={"proxy_id": "missing"}).status_code == 404


def test_reported_endpoint_names_the_proxy(client, node):
    add(client)
    now = time.time()
    body = {"epoch": "test-epoch-001", "samples": [sample(1, now-30, now-1, 10)],
            "meta": {"boot_id": "b", "interface": "eth0", "connection": "socks5", "proxy_endpoint": "203.0.113.8:1080"}}
    assert client.post("/api/agent/v1/report", headers=node[1], json=body).status_code == 200
    assert client.get("/api/nodes").json()["nodes"][0]["proxy_name"] == "香港中转"
    assert client.get(f"/api/nodes/{node[0]}").json()["proxy_name"] == "香港中转"
    assert client.get("/api/agent-proxies").json()["proxies"][0]["nodes"] == ["香港测试节点"]


def test_proxy_test_reports_failure_without_secrets(client):
    proxy_id = add(client, host="127.0.0.1", port=1)["id"]
    result = client.post(f"/api/agent-proxies/{proxy_id}/test").json()
    assert result["ok"] is False and "p@ss" not in result["error"] and "%40" not in result["error"]


def test_legacy_single_proxy_is_migrated(tmp_path):
    store = create_app(tmp_path, background=False).state.store
    with store.connect() as db:
        store.set_secret("agent_proxy", "socks5h://old:p%40ss@10.0.0.1:1080", db)
    with store.connect() as db:
        [entry] = proxies.load(store, db)
        assert (entry["host"], entry["port"], entry["username"], entry["password"], entry["note"]) == ("10.0.0.1", 1080, "old", "p@ss", "默认代理")
        assert store.secret("agent_proxy", db) == ""


def test_agent_reads_proxy_from_stdin(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(URL + "\n"))
    assert read_proxy(SimpleNamespace(proxy_file=None, proxy_stdin=True, proxy=False), "") == URL
    assert read_proxy(SimpleNamespace(proxy_file=None, proxy_stdin=False, proxy=False), "") == ""


def bash():
    if os.name == "nt":
        path = Path("C:/Program Files/Git/bin/bash.exe")
        return str(path) if path.exists() else None
    return shutil.which("bash")


@pytest.mark.parametrize("kind", ["install", "switch"])
def test_generated_command_pipes_proxy_to_curl_and_installer(tmp_path, kind):
    shell = bash()
    if not shell:
        pytest.skip("bash is not installed")
    server = "https://m.example.com"
    command = proxies.install_command(server, "tok'en", URL) if kind == "install" else proxies.switch_command(server, URL)
    # Stub curl and sudo, then run the generated command verbatim.
    (tmp_path / "run.sh").write_text('''
curl() { echo "curl-config: $(cat)"; printf '%s\\n' 'IFS= read -r X; echo "installer-proxy: $X"; echo "installer-args: $*"' > install-sentinel.sh; }
sudo() { "$@"; }
source ./command.sh
echo "P-after: ${P-unset}"
''', encoding="utf-8")
    (tmp_path / "command.sh").write_text(command + "\n", encoding="utf-8")
    result = subprocess.run([shell, "run.sh"], cwd=tmp_path, capture_output=True, encoding="utf-8", timeout=20)
    assert result.returncode == 0, result.stderr
    assert f'curl-config: proxy = "{URL}"' in result.stdout
    assert f"installer-proxy: {URL}" in result.stdout
    expected = "--token tok'en --proxy-stdin" if kind == "install" else "--upgrade --proxy-stdin"
    assert expected in result.stdout and "P-after: unset" in result.stdout
