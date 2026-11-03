import json
import time
from datetime import datetime, timezone

import httpx
from sentinel.notifications import Scheduler
from sentinel.core import canonical
from conftest import report, sample


def add_channel(client, name="主账号", chat="99", **flags):
    response = client.post("/api/telegram/channels", json={"name": name, "bot_token": "123456:fake-for-test", "chat_id": chat, **flags})
    assert response.status_code == 200, response.text
    return response.json()["id"]


def enabled(client):
    add_channel(client)
    assert client.put("/api/settings", json={"telegram_enabled": True}).status_code == 200


def test_telegram_429_respects_retry_and_hides_token(client, app):
    enabled(client)
    requests = []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 123}})
        return httpx.Response(200, json={"ok": True})
    scheduler = Scheduler(app.state.store, httpx.MockTransport(handler))
    now = time.time()
    with app.state.store.connect() as db:
        app.state.store.enqueue(db, "test", "中文日报", now)
    scheduler.deliver(now)
    with app.state.store.connect() as db:
        row = dict(db.execute("SELECT * FROM notifications").fetchone())
    assert row["state"] == "retry" and row["due"] == now+123
    assert "fake-for-test" not in row["error"]
    scheduler.deliver(now+122)
    assert len(requests) == 1
    scheduler.deliver(now+124)
    with app.state.store.connect() as db:
        assert db.execute("SELECT state FROM notifications").fetchone()[0] == "sent"
    assert len(requests) == 2


def test_daily_dedup_and_yesterday_timezone(client, app):
    enabled(client)
    scheduler = Scheduler(app.state.store)
    now = datetime(2026, 11, 3, 1, 0, tzinfo=timezone.utc).timestamp()
    scheduler.queue_daily(now)
    scheduler.queue_daily(now+20)
    with app.state.store.connect() as db:
        rows = db.execute("SELECT * FROM notifications").fetchall()
    assert len(rows) == 1
    assert "2026-11-02" in rows[0]["text"]
    assert "Asia/Shanghai" in rows[0]["text"]


def test_quota_alert_merges_lower_tiers(client, app, node):
    from test_api import profile
    enabled(client)
    now = time.time()
    p = profile(now)
    p["next_reset"] = datetime.fromtimestamp(now-3600, timezone.utc).isoformat()
    p["reset_day"] = datetime.fromtimestamp(now-3600, timezone.utc).day
    client.put(f"/api/nodes/{node[0]}/billing", json=p)
    with app.state.store.connect() as db:
        p['_updated'] = now-7200
        db.execute("UPDATE nodes SET profile=? WHERE id=?", (canonical(p), node[0]))
        db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?,?,?,?,?,?)", ('previous-period', node[0], now-4000, now-4000, 'test-epoch-001', 0, 563*10**9, now-3600, None, 'initial calibration'))
    report(client, node, [sample(1, now-60, now-1, 580*10**9)])
    sched = Scheduler(app.state.store, httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True})))
    sched.tick(now)
    sched.tick(now+1)
    with app.state.store.connect() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM notifications WHERE dedupe LIKE 'quota:%'")]
    assert len(rows) == 3
    assert len([r for r in rows if r["state"] != "suppressed"]) == 1


def test_long_messages_split_safely(client, app):
    add_channel(client)
    with app.state.store.connect() as db:
        app.state.store.enqueue(db, "long", ("节点 🟢 详细报告\n"*1000))
        chunks = db.execute("SELECT text FROM notifications").fetchall()
    assert len(chunks) > 1
    assert all(len(r[0].encode("utf-16-le")) <= 7000 for r in chunks)
