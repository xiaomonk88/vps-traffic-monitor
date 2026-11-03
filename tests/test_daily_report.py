"""Daily report: today's traffic per server and per channel, and the reset countdown."""
import time
from datetime import datetime, timedelta, timezone

from conftest import report, sample
from sentinel.core import canonical, time_left, traffic_bytes
from sentinel.notifications import Scheduler
from test_api import profile


def test_traffic_bytes_scales_small_values():
    assert traffic_bytes(0) == "0 B"
    assert traffic_bytes(340_000) == "340.00 KB"
    assert traffic_bytes(1_234_567_890) == "1.23 GB"
    assert traffic_bytes(5 * 1024**3, "GiB") == "5.00 GiB"


def test_time_left():
    assert time_left(16*86400 + 22*3600 + 59) == "还剩 16 天 22 小时"
    assert time_left(3*86400 + 10) == "还剩 3 天"
    assert time_left(5*3600) == "还剩 5 小时"
    assert time_left(120) == "不足 1 小时"
    assert time_left(-1) == "已到期"


def test_report_shows_today_totals_and_countdown_without_yesterday(client, app, node):
    now = time.time()
    p = profile(now)
    client.put(f"/api/nodes/{node[0]}/billing", json=p)
    start = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=1).timestamp()
    report(client, node, [sample(1, max(start, now-120), now-1, tx=300_000_000, rx=45_000_000)])
    text = Scheduler(app.state.store).daily_text(time.time())
    assert "今日合计（1 台）：上传 300.00 MB / 下载 45.00 MB / 总计 345.00 MB" in text
    assert "今日上传：300.00 MB / 下载：45.00 MB / 合计：345.00 MB" in text
    assert "昨日" not in text
    [reset_line] = [line for line in text.splitlines() if line.startswith("下次重置：")]
    assert "（还剩 " in reset_line and "Asia/Shanghai" not in reset_line and "UTC" not in reset_line


def test_channel_report_totals_only_its_servers(client, app, node):
    from test_notifications import add_channel
    other = client.post("/api/nodes", json={"name": "未分配服务器"}).json()["id"]
    channel = add_channel(client, "仅香港", chat="-1", all_nodes=False, nodes=[node[0]])
    now = time.time()
    report(client, node, [sample(1, now-60, now-1, tx=2_000_000, rx=1_000_000)])
    cfg = app.state.store.settings()
    [entry] = [c for c in cfg["channels"] if c["id"] == channel]
    text = Scheduler(app.state.store).daily_text(now, set(entry["nodes"]))
    assert "今日合计（1 台）：上传 2.00 MB / 下载 1.00 MB / 总计 3.00 MB" in text
    assert "未分配服务器" not in text
