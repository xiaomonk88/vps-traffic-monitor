"""Multiple Telegram channels, per-channel routing and the legacy single-chat migration."""
import json
import time

import httpx
import pytest

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


def test_channels_route_daily_and_alerts_separately(client, app):
    add_channel(client, "日报群", chat="-100", alerts=False)
    add_channel(client, "值班", chat="200", daily=False)
    add_channel(client, "停用", chat="300", enabled=False)
    assert client.put("/api/settings", json={"telegram_enabled": True}).status_code == 200
    sent, transport = recorder()
    scheduler = Scheduler(app.state.store, transport)
    now = time.time()
    scheduler.queue_daily(now)
    with app.state.store.connect() as db:
        app.state.store.enqueue(db, "alert-test", "⚠️ 告警", now)
    scheduler.deliver(now)
    assert sorted((m["chat_id"], m["text"][0]) for m in sent) == [("-100", "📊"), ("200", "⚠")]


def test_test_message_reaches_a_disabled_channel_and_secrets_stay_hidden(client, app):
    channel = add_channel(client, "备用", chat="400", enabled=False)
    sent, transport = recorder()
    with app.state.store.connect() as db:
        ids = app.state.store.enqueue(db, "manual-test:x", "hello", kind="test", channel=channel)
    Scheduler(app.state.store, transport).deliver(only=ids)
    assert [m["chat_id"] for m in sent] == ["400"]
    data = client.get("/api/settings").json()
    assert "fake-for-test" not in json.dumps(data)
    assert data["channels"][0]["token_configured"] is True


def test_update_keeps_token_and_delete_expires_pending(client, app):
    channel = add_channel(client)
    assert client.put(f"/api/telegram/channels/{channel}", json={"name": "改名", "chat_id": "555", "bot_token": ""}).status_code == 200
    assert app.state.store.secret("telegram_token:"+channel) == "123456:fake-for-test"
    assert client.put("/api/settings", json={"telegram_enabled": True}).status_code == 200
    with app.state.store.connect() as db:
        app.state.store.enqueue(db, "pending", "待发送")
    result = client.delete(f"/api/telegram/channels/{channel}").json()
    assert result["telegram_enabled"] is False
    assert app.state.store.secret("telegram_token:"+channel) == ""
    with app.state.store.connect() as db:
        assert db.execute("SELECT state FROM notifications").fetchone()[0] == "expired"


def test_enabling_requires_an_enabled_channel(client):
    response = client.put("/api/settings", json={"telegram_enabled": True})
    assert response.status_code == 400 and "通知渠道" in response.json()["detail"]
    assert client.post("/api/telegram/channels", json={"name": "无 Token", "chat_id": "1"}).status_code == 400


def test_legacy_single_chat_becomes_default_channel(tmp_path):
    app = create_app(tmp_path, background=False)
    store = app.state.store
    with store.connect() as db:
        cfg = store.settings(db)
        cfg.pop("channels")
        cfg.update(chat_id="777", telegram_enabled=True)
        db.execute("UPDATE settings SET value=? WHERE key='general'", (canonical(cfg),))
        store.set_secret("telegram_token", "123:legacy", db)
        db.execute("INSERT INTO notifications(id,dedupe,created,due,text) VALUES('old','daily:2026-11-03:0',0,0,'旧日报')")
    store = create_app(tmp_path, background=False).state.store
    cfg = store.settings()
    assert "chat_id" not in cfg and cfg["channels"][0]["chat_id"] == "777"
    assert store.secret("telegram_token:default") == "123:legacy" and store.secret("telegram_token") == ""
    with store.connect() as db:
        # Old dedupe keys still match, so the same daily report is not sent twice.
        assert store.enqueue(db, "daily:2026-11-03", "新日报", kind="daily") == []
        assert db.execute("SELECT channel FROM notifications WHERE id='old'").fetchone()[0] == "default"
