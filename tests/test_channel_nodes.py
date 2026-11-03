"""Servers are assigned to Telegram channels; unassigned servers are not notified."""
import json
import time
from datetime import datetime, timezone

import httpx

from conftest import report, sample
from sentinel.core import canonical
from sentinel.notifications import Scheduler
from sentinel.server import create_app
from test_notifications import add_channel


def recorder():
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})
    return sent, httpx.MockTransport(handler)


def make_node(client, name):
    return client.post("/api/nodes", json={"name": name}).json()["id"]


def test_new_channel_notifies_no_server_until_assigned(client, app):
    hk, us = make_node(client, "香港"), make_node(client, "美国")
    ops = add_channel(client, "运维群", chat="-1", all_nodes=False, nodes=[hk, "unknown-id"])
    empty = add_channel(client, "空渠道", chat="-2", all_nodes=False)
    everyone = add_channel(client, "个人", chat="1")
    client.put("/api/settings", json={"telegram_enabled": True})
    channels = {c["id"]: c for c in client.get("/api/settings").json()["channels"]}
    assert channels[ops]["nodes"] == [hk] and channels[empty]["nodes"] == []
    sent, transport = recorder()
    store = app.state.store
    with store.connect() as db:
        store.enqueue(db, "offline:hk", "香港离线", node=hk)
        store.enqueue(db, "offline:us", "美国离线", node=us)
    Scheduler(store, transport).deliver()
    assert sorted((m["chat_id"], m["text"]) for m in sent) == [("-1", "香港离线"), ("1", "美国离线"), ("1", "香港离线")]
    nodes = {n["name"]: n for n in client.get("/api/nodes").json()["nodes"]}
    assert nodes["香港"]["notify_channels"] == ["运维群", "个人"] and nodes["美国"]["notify_channels"] == ["个人"]


def test_daily_report_lists_only_assigned_servers(client, app):
    hk, us = make_node(client, "香港节点"), make_node(client, "美国节点")
    add_channel(client, "香港群", chat="-1", all_nodes=False, nodes=[hk])
    add_channel(client, "无服务器", chat="-2", all_nodes=False)
    add_channel(client, "全部", chat="1")
    client.put("/api/settings", json={"telegram_enabled": True})
    sent, transport = recorder()
    scheduler = Scheduler(app.state.store, transport)
    scheduler.queue_daily(datetime(2026, 11, 3, 2, tzinfo=timezone.utc).timestamp())
    scheduler.deliver()
    by_chat = {m["chat_id"]: m["text"] for m in sent}
    assert set(by_chat) == {"-1", "1"}
    assert "香港节点" in by_chat["-1"] and "美国节点" not in by_chat["-1"]
    assert "香港节点" in by_chat["1"] and "美国节点" in by_chat["1"]


def test_unassigned_server_alerts_are_not_queued(client, app, node):
    add_channel(client, "其他", chat="-9", all_nodes=False)
    mine = add_channel(client, "本机群", chat="-8", all_nodes=False, nodes=[node[0]])
    client.put("/api/settings", json={"telegram_enabled": True})
    now = time.time()
    with app.state.store.connect() as db:
        db.execute("UPDATE nodes SET heartbeat=?, enrolled=? WHERE id=?", (now-3600, now-7200, node[0]))
    Scheduler(app.state.store, httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))).tick(now)
    with app.state.store.connect() as db:
        rows = db.execute("SELECT channel FROM notifications WHERE dedupe LIKE 'offline:%'").fetchall()
    assert [r[0] for r in rows] == [mine]  # queued for the assigned channel only


def test_assign_from_server_side_and_cleanup_on_delete(client, app):
    hk = make_node(client, "香港")
    a = add_channel(client, "甲", chat="1", all_nodes=False)
    b = add_channel(client, "乙", chat="2", all_nodes=False, nodes=[hk])
    everyone = add_channel(client, "全部", chat="3")
    assert client.put(f"/api/nodes/{hk}/channels", json={"channels": [a]}).status_code == 200
    detail = {c["name"]: c["assigned"] for c in client.get(f"/api/nodes/{hk}").json()["channels"]}
    assert detail == {"甲": True, "乙": False, "全部": True}
    assert client.delete(f"/api/nodes/{hk}").status_code == 200
    channels = {c["id"]: c for c in client.get("/api/settings").json()["channels"]}
    assert channels[a]["nodes"] == [] and channels[everyone]["all_nodes"] is True


def test_existing_channels_keep_notifying_every_server_after_upgrade(tmp_path):
    store = create_app(tmp_path, background=False).state.store
    with store.connect() as db:
        cfg = store.settings(db)
        cfg["channels"] = [{"id": "old", "name": "旧渠道", "chat_id": "1", "enabled": True, "daily": True, "alerts": True}]
        db.execute("UPDATE settings SET value=? WHERE key='general'", (canonical(cfg),))
    store = create_app(tmp_path, background=False).state.store
    [channel] = store.settings()["channels"]
    assert channel["all_nodes"] is True and channel["nodes"] == []
