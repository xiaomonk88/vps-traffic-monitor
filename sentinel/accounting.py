from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .core import cycle_at, day_window, metered, portion


def usage(db, node_id: str, start: float, end: float, anchor=None) -> dict:
    rows = db.execute("SELECT * FROM samples WHERE node_id=? AND end>? AND start<? ORDER BY start", (node_id, start, end)).fetchall()
    rx = tx = 0
    spans = []
    uncertain = False
    archive_covered = 0.0
    for r in db.execute("SELECT * FROM hourly_usage WHERE node_id=? AND hour+3600>? AND hour<?", (node_id, start, end)):
        rx += portion(r["rx"], r["hour"], r["hour"]+3600, start, end)
        tx += portion(r["tx"], r["hour"], r["hour"]+3600, start, end)
        fraction = max(0, min(end, r["hour"]+3600)-max(start, r["hour"]))/3600
        archive_covered += r["covered"]*fraction
        uncertain = uncertain or bool(r["uncertain"])
    for r in rows:
        if anchor and r["epoch"] == anchor["epoch"] and r["seq"] <= anchor["seq"]:
            continue
        rx += portion(r["rx"], r["start"], r["end"], start, end)
        tx += portion(r["tx"], r["start"], r["end"], start, end)
        if r["quality"] == "ok":
            spans.append((max(start, r["start"]), min(end, r["end"])))
        else:
            uncertain = True
    covered = 0.0
    last = start
    for a, b in spans:
        covered += max(0, b - max(a, last))
        last = max(last, b)
    return {"rx": rx, "tx": tx, "coverage": min(1, (covered+archive_covered) / max(1, end-start)), "uncertain": uncertain}


def node_view(db, node, now=None, report_zone="Asia/Shanghai", offline_seconds=300):
    now = now or time.time()
    n = dict(node)
    n.pop("credential", None)
    profile = json.loads(n["profile"]) if n["profile"] else None
    meta = json.loads(n["meta"])
    n["profile"], n["meta"] = profile, meta
    n["checkpoint"] = json.loads(n["checkpoint"]) if n["checkpoint"] else None
    n["online"] = bool(n["heartbeat"] and now-n["heartbeat"] < offline_seconds)
    n["fresh"] = bool(n["online"] and n["last_data"] and now-n["last_data"] < 180 and not meta.get("error") and not meta.get("queue", 0))
    n["today"] = usage(db, n["id"], *day_window(now, report_zone), )
    n["yesterday"] = usage(db, n["id"], *day_window(now, report_zone, -1))
    n.update(remaining=None, used=None, percent=None, cycle_start=None, cycle_end=None, calibration=None, forecast_days=None, exhaustion_risk=False)
    if profile:
        start, end = cycle_at(profile, now)
        n["cycle_start"], n["cycle_end"] = start, end
        anchor = db.execute("SELECT * FROM calibrations WHERE node_id=? AND at<? AND cycle_end=? AND created>=? ORDER BY created DESC LIMIT 1", (n["id"], now+1, end, profile.get("_updated", 0))).fetchone()
        # After the first complete configured reset, quota-based accounting is possible.
        first_reset = datetime.fromisoformat(profile["next_reset"])
        if first_reset.tzinfo is None:
            first_reset = first_reset.replace(tzinfo=ZoneInfo(profile["timezone"]))
        previously_calibrated = db.execute("SELECT 1 FROM calibrations WHERE node_id=? AND created>=? LIMIT 1", (n["id"], profile.get("_updated", 0))).fetchone()
        if anchor or (previously_calibrated and now >= first_reset.timestamp()):
            measured = usage(db, n["id"], anchor["at"] if anchor else start, min(now, end), anchor)
            n["remaining"] = (anchor["remaining"] if anchor else profile["quota_bytes"]) - metered(measured["rx"], measured["tx"], profile["direction"])
            n["used"] = profile["quota_bytes"] - n["remaining"]
            n["percent"] = round(n["used"] / profile["quota_bytes"] * 100, 2)
            n["calibration"] = dict(anchor) if anchor else None
            n["uncertain"] = measured["uncertain"] or meta.get("data_gap", False)
        if n["remaining"] is not None and n["fresh"] and not meta.get("data_gap"):
            recent = usage(db, n["id"], now-86400, now)
            if recent["coverage"] >= .95 and not recent["uncertain"]:
                rate = metered(recent["rx"], recent["tx"], profile["direction"])
                rates = []
                for offset in range(1, 8):
                    u = usage(db, n["id"], *day_window(now, report_zone, -offset))
                    if u["coverage"] >= .95 and not u["uncertain"]:
                        rates.append(metered(u["rx"], u["tx"], profile["direction"]))
                rate = max(rate, sum(rates)/len(rates) if rates else 0)
                if rate > 0:
                    n["forecast_days"] = round(max(0, n["remaining"])/rate, 2)
                    n["exhaustion_risk"] = n["forecast_days"] < (end-now)/86400
    if n["disabled"]:
        n["status"] = "disabled"
    elif not n["enrolled"]:
        n["status"] = "pending"
    elif not n["online"]:
        n["status"] = "offline"
    elif meta.get("error") or meta.get("data_gap"):
        n["status"] = "error"
    elif meta.get("queue", 0):
        n["status"] = "syncing"
    elif n["remaining"] is None:
        n["status"] = "uncalibrated"
    elif (n["percent"] or 0) >= 90 or n["exhaustion_risk"]:
        n["status"] = "warning"
    else:
        n["status"] = "online"
    return n


def history(db, node_id, zone, days=14, now=None):
    now = now or time.time()
    result = []
    for offset in range(-days+1, 1):
        start, end = day_window(now, zone, offset)
        u = usage(db, node_id, start, min(end, now))
        result.append({"date": datetime.fromtimestamp(start, ZoneInfo(zone)).strftime("%m-%d"), **u})
    return result
