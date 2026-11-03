import json
import time
from datetime import datetime, timedelta, timezone

from sentinel.core import canonical, cycle_at
from sentinel.accounting import node_view
from conftest import report, sample


def profile(now):
    reset = datetime.fromtimestamp(now, timezone.utc)+timedelta(days=14)
    return {"quota_bytes": 600*10**9, "unit": "GB", "direction": "tx", "timezone": "UTC", "next_reset": reset.strftime("%Y-%m-%dT00:00"), "reset_day": reset.day, "reset_time": "00:00"}


def test_auth_csrf_and_origin(client):
    assert client.post("/api/nodes", json={"name": "x"}, headers={"x-csrf-token": "bad"}).status_code == 403
    assert client.post("/api/nodes", json={"name": "x"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/nodes").status_code == 200
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/nodes").status_code == 401


def test_checkpoint_is_frozen_and_stops_fast_polling(client, node):
    now = time.time()
    assert report(client, node, [sample(1, now-60, now-40, 100)]).status_code == 200
    check = client.post(f"/api/nodes/{node[0]}/checkpoint").json()["id"]
    result = report(client, node, [sample(2, now-40, now-20, 200)], checkpoint=check)
    assert result.status_code == 200
    assert result.json()["checkpoint_request"] is None
    original = client.get(f"/api/nodes/{node[0]}").json()["checkpoint"]
    assert original["seq"] == 2
    # A retry/late report cannot move the already displayed anchor forward.
    assert report(client, node, [sample(3, now-20, now-1, 300)], checkpoint=check).status_code == 200
    assert client.get(f"/api/nodes/{node[0]}").json()["checkpoint"] == original


def test_install_tokens_single_use_and_revocation(client, node):
    assert client.post(f"/api/nodes/{node[0]}/install").status_code == 409
    assert client.post(f"/api/nodes/{node[0]}/revoke").status_code == 200
    assert report(client, node, []).status_code == 401
    token = client.post(f"/api/nodes/{node[0]}/install").json()["token"]
    assert client.post("/api/agent/v1/enroll", json={"token": token, "hostname": "new"}).status_code == 200
    assert client.post("/api/agent/v1/enroll", json={"token": token, "hostname": "new"}).status_code == 401


def test_563_minus_10_minus_2_across_reboot_and_duplicate(client, node, app):
    now = time.time()
    assert client.put(f"/api/nodes/{node[0]}/billing", json=profile(now)).status_code == 200
    first = sample(1, now-60, now-50, 100)
    assert report(client, node, [first]).status_code == 200
    check = client.post(f"/api/nodes/{node[0]}/checkpoint").json()["id"]
    second = sample(2, now-50, now-40, 200)
    assert report(client, node, [second], checkpoint=check).status_code == 200
    calibrated = client.post(f"/api/nodes/{node[0]}/calibrate", json={"checkpoint_id": check, "remaining_bytes": 563*10**9})
    assert calibrated.status_code == 200, calibrated.text
    third = sample(3, now-40, now-20, 10*10**9)
    fourth = sample(4, now-10, now-1, 2*10**9, quality="reboot")
    assert report(client, node, [third, fourth], boot="boot-2").status_code == 200
    assert report(client, node, [first, second, third, fourth], boot="boot-2").status_code == 200
    result = client.get(f"/api/nodes/{node[0]}").json()
    assert result["remaining"] == 551*10**9
    assert len(result["calibrations"]) == 1
    # A replay of a sample preceding calibration cannot consume the new balance.
    assert report(client, node, [first]).status_code == 200
    assert client.get(f"/api/nodes/{node[0]}").json()["remaining"] == 551*10**9
    assert client.post(f"/api/nodes/{node[0]}/calibrate", json={"checkpoint_id": check, "remaining_bytes": 400*10**9}).status_code == 409


def test_out_of_order_or_conflicting_records_are_atomic(client, node, app):
    now = time.time()
    a = sample(1, now-30, now-20, 100)
    c = sample(3, now-10, now, 300)
    assert report(client, node, [a, c]).status_code == 409
    with app.state.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0
    assert report(client, node, [a]).status_code == 200
    a["tx"] = 101
    assert report(client, node, [a]).status_code == 409


def test_late_samples_belong_to_original_cycle(client, node, app):
    now = time.time()
    boundary = now-3600
    local = datetime.fromtimestamp(boundary, timezone.utc)
    p = profile(now)
    p.update(next_reset=local.isoformat(), reset_day=local.day, reset_time=local.strftime("%H:%M"))
    client.put(f"/api/nodes/{node[0]}/billing", json=p)
    with app.state.store.connect() as db:
        p['_updated'] = boundary-86400
        db.execute("UPDATE nodes SET profile=? WHERE id=?", (canonical(p), node[0]))
        db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?,?,?,?,?,?)", ('previous-period', node[0], boundary-800, boundary-800, 'test-epoch-001', 0, 563*10**9, boundary, None, 'initial calibration'))
    assert report(client, node, [sample(1, boundary-600, boundary-300, 40*10**9), sample(2, boundary-100, boundary+100, 20*10**9)]).status_code == 200
    # Explicit first reset includes seconds; half the crossing sample is new-cycle usage.
    result = client.get(f"/api/nodes/{node[0]}").json()
    assert result["remaining"] == 590*10**9


def test_future_time_and_overlap_rejected(client, node):
    now = time.time()
    assert report(client, node, [sample(1, now, now+600, 10)]).status_code == 400
    assert report(client, node, [sample(1, now-30, now-10, 10)]).status_code == 200
    assert report(client, node, [sample(2, now-20, now, 10)]).status_code == 400


def test_offline_calibration_refused(client, node):
    assert client.post(f"/api/nodes/{node[0]}/checkpoint").status_code == 409


def test_never_calibrated_node_does_not_invent_balance_after_reset(client, node):
    now = time.time()
    p = profile(now)
    p['next_reset'] = datetime.fromtimestamp(now-86400, timezone.utc).isoformat()
    client.put(f"/api/nodes/{node[0]}/billing", json=p)
    report(client, node, [sample(1, now-30, now-1, 10)])
    assert client.get(f"/api/nodes/{node[0]}").json()['remaining'] is None


def test_secrets_not_returned_and_backup_is_consistent(client, app):
    token = "123456:fake-token-for-tests"
    assert client.post("/api/telegram/channels", json={"name": "主账号", "bot_token": token, "chat_id": "123"}).status_code == 200
    assert client.put("/api/settings", json={"telegram_enabled": True}).status_code == 200
    data = client.get("/api/settings").json()
    assert data["channels"][0]["token_configured"] and token not in json.dumps(data)
    assert token.encode() not in app.state.store.path.read_bytes()
    backup = client.get("/api/backup")
    assert backup.status_code == 200 and backup.content.startswith(b"PK")
