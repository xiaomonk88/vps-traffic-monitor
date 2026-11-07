"""Pure accounting functions. Timestamps are UTC epoch seconds, amounts integer bytes."""
from __future__ import annotations

import calendar
import hashlib
import hmac
import json
import math
import secrets
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC = timezone.utc
UNITS = {"GB": 10**9, "GiB": 2**30, "TB": 10**12, "TiB": 2**40}


def uid() -> str:
    return secrets.token_hex(12)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + derived


def password_ok(password: str, saved: str) -> bool:
    try:
        return hmac.compare_digest(password_hash(password, saved.split(":")[0]), saved)
    except (ValueError, TypeError):
        return False


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def month_boundary(year: int, month: int, profile: dict) -> float:
    day = min(int(profile["reset_day"]), calendar.monthrange(year, month)[1])
    hh, mm = map(int, profile.get("reset_time", "00:00").split(":"))
    return datetime(year, month, day, hh, mm, tzinfo=ZoneInfo(profile["timezone"])).timestamp()


def month_shift(year: int, month: int, delta: int) -> tuple[int, int]:
    serial = year * 12 + month - 1 + delta
    return serial // 12, serial % 12 + 1


def cycle_at(profile: dict, at: float) -> tuple[float, float]:
    """Use an explicitly configured first reset, then the recurring calendar rule."""
    zone = ZoneInfo(profile["timezone"])
    first = datetime.fromisoformat(profile["next_reset"])
    if first.tzinfo is None:
        first = first.replace(tzinfo=zone)
    first_ts = first.timestamp()
    if at < first_ts:
        y, m = month_shift(first.year, first.month, -1)
        start = month_boundary(y, m, profile)
        # Initial manual period may be longer than a month; never drop its anchor.
        return min(start, at), first_ts
    local = datetime.fromtimestamp(at, zone)
    boundary = month_boundary(local.year, local.month, profile)
    if boundary <= at:
        start = max(first_ts, boundary)
        y, m = month_shift(local.year, local.month, 1)
        return start, month_boundary(y, m, profile)
    y, m = month_shift(local.year, local.month, -1)
    return max(first_ts, month_boundary(y, m, profile)), boundary


def day_window(at: float, zone: str, offset: int = 0) -> tuple[float, float]:
    local = datetime.fromtimestamp(at, ZoneInfo(zone))
    start = datetime.combine(local.date() + timedelta(days=offset), datetime.min.time(), ZoneInfo(zone))
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def portion(amount: int, start: float, end: float, left: float, right: float) -> int:
    """Prefix subtraction conserves bytes when a sample spans multiple periods."""
    if end <= start or right <= start or left >= end:
        return 0
    a, b = max(start, left), min(end, right)
    # Integer microsecond arithmetic avoids rounding large byte counts via float.
    duration = max(1, round((end - start) * 1_000_000))
    pa = max(0, min(duration, round((a - start) * 1_000_000)))
    pb = max(0, min(duration, round((b - start) * 1_000_000)))
    return amount * pb // duration - amount * pa // duration


def metered(rx: int, tx: int, direction: str) -> int:
    """Billed amount of one span. "max" (出入取大) applies to cycle totals; see accounting.consumed."""
    if direction == "max":
        return max(rx, tx)
    return tx if direction == "tx" else rx if direction == "rx" else rx + tx


def validate_profile(p: dict) -> dict:
    p = dict(p)
    required = {'quota_bytes', 'unit', 'direction', 'timezone', 'next_reset', 'reset_day', 'reset_time'}
    if not required.issubset(p):
        raise ValueError("计费字段不完整，请填写额度、单位、方向、时区和重置规则")
    if p.get("unit") not in UNITS or p.get("direction") not in ("rx", "tx", "sum", "max"):
        raise ValueError("请选择有效单位和计费方向")
    total = int(p.get("quota_bytes", 0))
    if not 0 < total <= 10**17:
        raise ValueError("总额度必须大于零，且不超过 100 PB")
    p["quota_bytes"] = total
    if not 1 <= int(p.get("reset_day", 0)) <= 31:
        raise ValueError("重置日应为 1～31")
    p["reset_day"] = int(p["reset_day"])
    try:
        ZoneInfo(p["timezone"])
    except (KeyError, TypeError):
        raise ValueError("时区无效，请使用 Asia/Shanghai 或 UTC 等 IANA 时区")
    h, m = map(int, p["reset_time"].split(":"))
    if not 0 <= h <= 23 or not 0 <= m <= 59:
        raise ValueError("重置时间无效")
    date = datetime.fromisoformat(p["next_reset"])
    if date.tzinfo is not None:
        date = date.astimezone(ZoneInfo(p["timezone"]))
    if not 2020 <= date.year <= 2100:
        raise ValueError("重置日期超出范围")
    return p


def human_bytes(value: int | float, unit: str = "GB") -> str:
    return f"{value / UNITS.get(unit, 10**9):,.2f} {unit}"


def traffic_bytes(value: int | float, unit: str = "GB") -> str:
    """Auto-scaled size (B..PB, or B..PiB for binary plan units), so small days do not show 0.00 GB."""
    binary = "iB" in unit
    base = 1024 if binary else 1000
    labels = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"] if binary else ["B", "KB", "MB", "GB", "TB", "PB"]
    amount, index = float(value), 0
    while abs(amount) >= base and index < len(labels)-1:
        amount /= base
        index += 1
    return f"{amount:,.0f} {labels[index]}" if index == 0 else f"{amount:,.2f} {labels[index]}"


def time_left(seconds: float) -> str:
    """Compact countdown: "7天19小时", "7天", "5小时", "不足1小时"."""
    if seconds <= 0:
        return "已到期"
    days, rest = divmod(int(seconds), 86400)
    hours = rest // 3600
    if days:
        return f"{days}天{hours}小时" if hours else f"{days}天"
    return f"{hours}小时" if hours else "不足1小时"


def finite_timestamp(value: float) -> bool:
    return math.isfinite(value) and 0 < value < 4_102_444_800
