"""出入取大: the merchant bills max(cycle upload, cycle download)."""
import pytest

from sentinel.accounting import consumed
from sentinel.core import metered, validate_profile
from test_api import profile

MAX = {"direction": "max"}


def add(db, node_id, seq, start, end, rx, tx):
    db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)", (node_id, "e1", seq, start, end, rx, tx, "ok", f"h{seq}"))


def test_metered_and_profile_accept_max():
    assert metered(5, 3, "max") == 5 and metered(2, 7, "max") == 7
    assert validate_profile({**profile(1_800_000_000), "direction": "max"})["direction"] == "max"
    with pytest.raises(ValueError):
        validate_profile({**profile(1_800_000_000), "direction": "avg"})


def test_from_cycle_start_bills_the_larger_total(app, node):
    with app.state.store.connect() as db:
        add(db, node[0], 1, 1000, 2000, rx=10, tx=4)
        add(db, node[0], 2, 2000, 3000, rx=1, tx=9)
        billed, _ = consumed(db, node[0], MAX, 1000, 3000)
    assert billed == 13  # max(rx 11, tx 13), not 11+13 and not max per span (10+9)


def test_after_calibration_uses_cycle_totals_when_data_is_complete(app, node):
    with app.state.store.connect() as db:
        add(db, node[0], 1, 1000, 2000, rx=10, tx=4)   # before calibration: download leads
        add(db, node[0], 2, 2000, 3000, rx=1, tx=9)    # after: upload overtakes
        billed, _ = consumed(db, node[0], MAX, 1000, 3000, {"at": 2000, "epoch": "e1", "seq": 1})
    assert billed == 3  # cycle max goes from 10 to 13


def test_mid_cycle_install_uses_the_safe_upper_bound(app, node):
    with app.state.store.connect() as db:
        add(db, node[0], 1, 1900, 2000, rx=10, tx=4)   # only the last 10% before calibration
        add(db, node[0], 2, 2000, 3000, rx=1, tx=9)
        billed, _ = consumed(db, node[0], MAX, 1000, 3000, {"at": 2000, "epoch": "e1", "seq": 1})
    assert billed == 9  # split unknown: assume the larger increase, never overstating remaining


def test_other_directions_unchanged(app, node):
    with app.state.store.connect() as db:
        add(db, node[0], 1, 1000, 2000, rx=10, tx=4)
        assert consumed(db, node[0], {"direction": "sum"}, 1000, 2000)[0] == 14
        assert consumed(db, node[0], {"direction": "tx"}, 1000, 2000)[0] == 4


def test_billing_api_accepts_max(client, node):
    import time
    response = client.put(f"/api/nodes/{node[0]}/billing", json={**profile(time.time()), "direction": "max"})
    assert response.status_code == 200
    assert client.get(f"/api/nodes/{node[0]}").json()["profile"]["direction"] == "max"
