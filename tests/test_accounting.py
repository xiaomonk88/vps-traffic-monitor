from datetime import datetime, timezone

from sentinel.core import cycle_at, day_window, portion, password_hash, password_ok
from sentinel.agent import AgentState


def ts(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp()


def test_month_end_returns_to_original_day():
    profile = {"timezone": "UTC", "next_reset": "2026-01-31T00:00", "reset_day": 31, "reset_time": "00:00"}
    assert cycle_at(profile, ts("2026-02-15")) == (ts("2026-01-31"), ts("2026-02-28"))
    assert cycle_at(profile, ts("2026-03-01")) == (ts("2026-02-28"), ts("2026-03-31"))
    assert cycle_at(profile, ts("2026-03-31"))[1] == ts("2026-04-30")


def test_split_conserves_bytes_even_at_large_values():
    amount = 2**60+37
    pieces = [portion(amount, 100, 199, a, b) for a, b in [(0, 113), (113, 158), (158, 300)]]
    assert sum(pieces) == amount
    assert portion(200, 10, 20, 20, 30) == 0


def test_day_uses_timezone_and_dst():
    start, end = day_window(ts("2026-03-08T18:00"), "America/New_York")
    assert end-start == 23*3600


def test_password_hashes_salted_and_checked():
    a, b = password_hash("a long password"), password_hash("a long password")
    assert a != b
    assert password_ok("a long password", a)
    assert not password_ok("wrong", a)


def test_agent_restart_and_machine_reboot_preserve_totals(tmp_path):
    state = AgentState(tmp_path)
    state.record(500_000, 800_000, "boot1", "eth0", 100)
    state.record(501_000, 810_000, "boot1", "eth0", 110)
    # Restart only the process. State survives and fills the gap using the counters.
    state = AgentState(tmp_path)
    state.record(503_000, 820_000, "boot1", "eth0", 120)
    # A machine reboot resets kernel counters, not the saved outbox.
    state.record(400, 2000, "boot2", "eth0", 140, 130)
    _, records, _ = state.batch()
    assert sum(r["tx"] for r in records) == 22_000
    assert sum(r["rx"] for r in records) == 3_400
    assert records[-1]["quality"] == "reboot"
    state.acknowledge(2)
    assert state.batch()[1][0]["seq"] == 3


def test_counter_reset_never_creates_negative_traffic(tmp_path):
    state = AgentState(tmp_path)
    state.record(900, 1000, "boot1", "eth0", 100)
    state.record(3, 4, "boot1", "eth0", 110)
    sample = state.batch()[1][0]
    assert sample["rx"] == 3 and sample["tx"] == 4
    assert sample["quality"] == "counter_reset"


def test_ack_rollback_replays_retained_records(tmp_path):
    state = AgentState(tmp_path)
    state.record(0, 0, "boot1", "eth0", 100)
    for i in range(1, 4):
        state.record(i*100, i*200, "boot1", "eth0", 100+i*10)
    state.acknowledge(3)
    assert state.batch()[1] == []
    state.acknowledge(1)
    assert [r["seq"] for r in state.batch()[1]] == [2, 3]
