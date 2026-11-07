import time

from sentinel.accounting import usage
from sentinel.retention import compact
from conftest import report, sample


def test_archiving_preserves_totals_and_dedup_cursor(client, node, app):
    now = time.time()
    old = int((now-40*86400)//3600)*3600
    samples = [sample(1, old+300, old+4300, 123456789, 987654321), sample(2, old+4300, old+8000, 123, 456)]
    assert report(client, node, samples).status_code == 200
    with app.state.store.connect() as db:
        before = usage(db, node[0], old, old+10800)
        assert compact(db, now) == 2
        after = usage(db, node[0], old, old+10800)
        assert before['tx'] == after['tx'] and before['rx'] == after['rx']
        assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 0
    assert report(client, node, samples).status_code == 200
    with app.state.store.connect() as db:
        assert usage(db, node[0], old, old+10800)['tx'] == before['tx']
        assert db.execute('SELECT COUNT(*) FROM samples').fetchone()[0] == 0


def test_hourly_partial_window_is_bounded(client, node, app):
    now = time.time()
    old = int((now-40*86400)//3600)*3600
    report(client, node, [sample(1, old, old+3600, 1000, 2000)])
    with app.state.store.connect() as db:
        compact(db, now)
        half = usage(db, node[0], old+1800, old+3600)
    assert half['tx'] == 500 and half['rx'] == 1000


import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sentinel.accounting import node_view
from sentinel.core import cycle_at


@pytest.mark.parametrize("direction", ["tx", "max"])
def test_rollup_keeps_every_balance_identical(client, node, app, direction):
    """Archiving old samples into hourly totals must not change any number in the panel."""
    now = time.time()
    reset = datetime.fromtimestamp(now, timezone.utc) + timedelta(days=12)
    profile = {"quota_bytes": 10**12, "unit": "GB", "direction": direction, "timezone": "UTC",
               "next_reset": reset.strftime("%Y-%m-%dT%H:%M"), "reset_day": reset.day, "reset_time": "00:00"}
    assert client.put(f"/api/nodes/{node[0]}/billing", json=profile).status_code == 200
    store = app.state.store
    with store.connect() as db:
        stored = json.loads(db.execute("SELECT profile FROM nodes WHERE id=?", (node[0],)).fetchone()[0])
        start, end = cycle_at(stored, now)
        # 10-minute samples, deliberately not aligned to hours, from cycle start to now.
        t, seq, rows = start + 37, 0, []
        while t + 600 < now:
            seq += 1
            rows.append((node[0], "e1", seq, t, t + 600, 1000 + seq * 7 % 900, 3000 + seq * 13 % 1700, "ok", f"h{seq}"))
            t += 600
        db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)", rows)
        # Calibrate mid-cycle exactly at the end of a sample, as a real checkpoint would be.
        anchor = rows[len(rows) // 2]
        db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?,?,?,?,?,?)",
                   (uuid.uuid4().hex, node[0], time.time() + 1, anchor[4], "e1", anchor[2], 8 * 10**11, end, None, "test"))
        db.execute("UPDATE nodes SET heartbeat=?, last_data=? WHERE id=?", (now, rows[-1][4], node[0]))
        raw = db.execute("SELECT * FROM nodes WHERE id=?", (node[0],)).fetchone()
        before = node_view(db, raw, now, "UTC")
        while compact(db, now):
            pass
        remaining_raw = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        after = node_view(db, raw, now, "UTC")
    assert remaining_raw < len(rows) / 3  # most of the cycle is now hourly totals
    assert before["remaining"] is not None
    for key in ("remaining", "used", "percent"):
        assert after[key] == before[key], key
    for day in ("today", "yesterday"):
        assert (after[day]["rx"], after[day]["tx"]) == (before[day]["rx"], before[day]["tx"]), day
        assert after[day]["coverage"] == pytest.approx(before[day]["coverage"], abs=1e-6), day


def test_recent_and_calibration_samples_stay_raw(client, node, app):
    now = time.time()
    store = app.state.store
    with store.connect() as db:
        old, recent, anchor_time = now - 10 * 86400, now - 3600, now - 5 * 86400
        for seq, s in enumerate((old, anchor_time - 300, recent), start=1):
            db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)", (node[0], "e1", seq, s, s + 600, 1, 1, "ok", f"h{seq}"))
        db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?,?,?,?,?,?)", ("c", node[0], now, anchor_time, "e1", 2, 1, now + 86400, None, ""))
        assert compact(db, now) == 1
        assert [r[0] for r in db.execute("SELECT seq FROM samples ORDER BY seq")] == [2, 3]
