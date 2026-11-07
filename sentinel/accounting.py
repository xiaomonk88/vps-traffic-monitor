from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .core import cycle_at, day_window, metered, portion


def usage(db, node_id: str, start: float, end: float, anchor=None) -> dict:
    """Traffic and coverage of [start, end).

    Samples fully inside the window are summed by SQLite; only the few that cross a window
    edge are split proportionally in Python. Iterating every 10-second sample of a whole
    billing cycle in Python made the server list take seconds and grow every day.
    """
    rx = tx = 0
    uncertain = False
    archive_covered = 0.0
    for r in db.execute("SELECT * FROM hourly_usage WHERE node_id=? AND hour+3600>? AND hour<?", (node_id, start, end)):
        rx += portion(r["rx"], r["hour"], r["hour"]+3600, start, end)
        tx += portion(r["tx"], r["hour"], r["hour"]+3600, start, end)
        fraction = max(0, min(end, r["hour"]+3600)-max(start, r["hour"]))/3600
        archive_covered += r["covered"]*fraction
        uncertain = uncertain or bool(r["uncertain"])
    # Samples up to the calibration checkpoint are already reflected in the calibrated balance.
    skip, params = "", []
    if anchor:
        skip, params = " AND NOT (epoch=? AND seq<=?)", [anchor["epoch"], anchor["seq"]]
    inside = db.execute("SELECT COALESCE(SUM(rx),0), COALESCE(SUM(tx),0), COALESCE(SUM(CASE WHEN quality='ok' THEN end-start ELSE 0 END),0), "
                        "COALESCE(MAX(quality!='ok'),0) FROM samples WHERE node_id=? AND end>? AND end<=? AND start>=?"+skip,
                        [node_id, start, end, start, *params]).fetchone()
    rx, tx, covered = rx+inside[0], tx+inside[1], float(inside[2])
    uncertain = uncertain or bool(inside[3])
    for r in db.execute("SELECT * FROM samples WHERE node_id=? AND end>? AND start<? AND (start<? OR end>?)"+skip,
                        [node_id, start, end, start, end, *params]):
        rx += portion(r["rx"], r["start"], r["end"], start, end)
        tx += portion(r["tx"], r["start"], r["end"], start, end)
        if r["quality"] == "ok":
            covered += max(0, min(end, r["end"])-max(start, r["start"]))
        else:
            uncertain = True
    return {"rx": rx, "tx": tx, "coverage": min(1, (covered+archive_covered) / max(1, end-start)), "uncertain": uncertain}


def consumed(db, node_id: str, profile: dict, start: float, until: float, anchor=None) -> tuple[int, dict]:
    """Billed traffic since the anchor (or cycle start) and the raw measurement after it.

    For "max" (出入取大) the merchant bills max(cycle upload, cycle download), which is not
    additive. With full data from the cycle start, the increase is computed on cycle totals
    and applied on top of the calibrated balance. Without it (Agent installed mid-cycle) the
    pre-calibration split is unknown, so the larger per-direction increase is used: an upper
    bound that never overstates the remaining quota.
    """
    after = usage(db, node_id, anchor["at"] if anchor else start, until, anchor)
    if profile["direction"] != "max":
        return metered(after["rx"], after["tx"], profile["direction"]), after
    if anchor:
        before = usage(db, node_id, start, anchor["at"])
        if before["coverage"] >= .95:
            increase = max(before["rx"]+after["rx"], before["tx"]+after["tx"]) - max(before["rx"], before["tx"])
            return increase, after
    return max(after["rx"], after["tx"]), after


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
            billed, measured = consumed(db, n["id"], profile, start, min(now, end), anchor)
            n["remaining"] = (anchor["remaining"] if anchor else profile["quota_bytes"]) - billed
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
