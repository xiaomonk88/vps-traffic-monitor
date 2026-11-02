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
