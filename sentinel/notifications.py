from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .accounting import node_view
from .core import human_bytes, time_left, traffic_bytes, uid
from .network import client


class Scheduler:
    def __init__(self, store, transport=None):
        self.store = store
        self.transport = transport

    def daily_text(self, now, node_ids=None):
        """Daily report of today's traffic; `node_ids` limits it to one channel's servers."""
        cfg = self.store.settings()
        local = datetime.fromtimestamp(now, ZoneInfo(cfg["timezone"]))
        with self.store.connect() as db:
            nodes = [node_view(db, r, now, cfg["timezone"], cfg["offline_minutes"]*60) for r in db.execute("SELECT * FROM nodes WHERE disabled=0").fetchall()
                     if node_ids is None or r["id"] in node_ids]
        nodes.sort(key=lambda n: (n["status"] == "online", -(n["percent"] or 0)))
        tx, rx = sum(n["today"]["tx"] for n in nodes), sum(n["today"]["rx"] for n in nodes)
        lines = ["📊 流量哨 · VPS 流量日报", f"统计时段：{local:%Y-%m-%d} 00:00 – {local:%H:%M}"]
        if nodes:
            lines.append(f"今日合计（{len(nodes)} 台）：上传 {traffic_bytes(tx)} / 下载 {traffic_bytes(rx)} / 总计 {traffic_bytes(tx+rx)}")
        lines += ["余额为本地估算，以各节点最近上报为准。", ""]
        if not nodes:
            lines.append("暂无已添加的服务器。")
        for n in nodes:
            unit = n["profile"]["unit"] if n["profile"] else "GB"
            today = n["today"]
            icon = "🟢" if n["status"] == "online" else "🟠"
            lines += [f"{icon} {n['name']}",
                      f"今日上传：{traffic_bytes(today['tx'],unit)} / 下载：{traffic_bytes(today['rx'],unit)} / 合计：{traffic_bytes(today['tx']+today['rx'],unit)}"]
            if n["remaining"] is None:
                lines.append("预计剩余：尚未校准")
            else:
                lines.append(f"预计剩余：{human_bytes(n['remaining'],unit)}（已用 {n['percent']:.1f}%）")
            if n["cycle_end"]:
                # Shown in the billing timezone, matching the reset time the user configured.
                reset = datetime.fromtimestamp(n["cycle_end"], ZoneInfo(n["profile"]["timezone"])).strftime("%Y-%m-%d %H:%M")
                lines.append(f"下次重置：{reset}（{time_left(n['cycle_end']-now)}）")
            if not n["fresh"]:
                lines.append("⚠️ 数据过期或尚未追平，余额可能偏高")
            if n["forecast_days"] is not None:
                lines.append(f"按近期消耗预计可用：{n['forecast_days']:.1f} 天")
            if n["exhaustion_risk"]:
                lines.append("⚠️ 预计无法撑到重置日")
            if n["last_data"]:
                lines.append("最近采集："+datetime.fromtimestamp(n["last_data"], ZoneInfo(cfg["timezone"])).strftime("%m-%d %H:%M"))
            lines.append("")
        return "\n".join(lines)

    def queue_daily(self, now=None, manual=False):
        now = now or time.time()
        cfg = self.store.settings()
        date = datetime.fromtimestamp(now, ZoneInfo(cfg["timezone"])).date().isoformat()
        key = "manual-daily:"+uid() if manual else "daily:"+date
        ids = []
        # Each channel gets a report of only its own servers; channels without servers get none.
        for channel in cfg.get("channels", []):
            if not channel.get("enabled") or not channel.get("daily"):
                continue
            node_ids = None if channel.get("all_nodes") else set(channel.get("nodes", []))
            if node_ids is not None and not node_ids:
                continue
            text = self.daily_text(now, node_ids)
            with self.store.connect() as db:
                ids += self.store.enqueue(db, key, text, now, kind="daily", channel=channel["id"])
        return ids

    def tick(self, now=None):
        now = now or time.time()
        cfg = self.store.settings()
        self.maintenance(now, cfg)
        if not cfg["telegram_enabled"]:
            return
        local = datetime.fromtimestamp(now, ZoneInfo(cfg["timezone"]))
        if cfg["daily_enabled"] and local.strftime("%H:%M") >= cfg["daily_time"]:
            self.queue_daily(now)
        with self.store.connect() as db:
            for row in db.execute("SELECT * FROM nodes WHERE disabled=0 AND enrolled IS NOT NULL").fetchall():
                n = node_view(db, row, now, cfg["timezone"], cfg["offline_minutes"]*60)
                state = db.execute("SELECT * FROM node_alert_state WHERE node_id=?", (n["id"],)).fetchone()
                offline = not n["online"] and now-(n["heartbeat"] or n["enrolled"]) >= cfg["offline_minutes"]*60
                if offline and (not state or not state["offline"]):
                    self.store.enqueue(db, f"offline:{n['id']}:{int(n['heartbeat'] or n['enrolled'])}", f"🔴 {n['name']} 已超过 {cfg['offline_minutes']} 分钟未上报。\n本地余额可能偏高，请检查 Agent 或代理连接。", now, node=n["id"])
                if not offline and n["online"] and state and state["offline"]:
                    self.store.enqueue(db, f"recovered:{n['id']}:{int(n['heartbeat'])}", f"🟢 {n['name']} 已恢复连接。断线期间数据将继续补报。", now, node=n["id"])
                end = n["cycle_end"]
                if end and state and state["cycle_end"] and state["cycle_end"] != end and cfg["reset_notice"]:
                    self.store.enqueue(db, f"reset:{n['id']}:{end}", f"🔄 {n['name']} 已按设置进入新计费周期。\n这是本地规则推算，尚未核对商家后台。", now, node=n["id"])
                if end and 0 < end-now <= 86400 and cfg["pre_reset_notice"]:
                    self.store.enqueue(db, f"before-reset:{n['id']}:{end}", f"📅 {n['name']} 距配置的流量重置时间不足 24 小时。", now, node=n["id"])
                db.execute("INSERT INTO node_alert_state VALUES(?,?,?) ON CONFLICT(node_id) DO UPDATE SET offline=excluded.offline,cycle_end=excluded.cycle_end", (n["id"], int(offline), end))
                if n["fresh"] and n["percent"] is not None:
                    exceeded = [t for t in cfg["thresholds"] if n["percent"] >= t]
                    if exceeded:
                        highest = max(exceeded)
                        key = f"quota:{n['id']}:{end}:{highest}"
                        # Mark lower tiers as suppressed when jumping over several thresholds.
                        for lower in exceeded[:-1]:
                            db.execute("INSERT OR IGNORE INTO notifications(id,dedupe,created,due,text,state) VALUES(?,?,?,?,?,'suppressed')", (uid(), f"quota:{n['id']}:{end}:{lower}:0", now, now, "已合并到更高等级告警"))
                        self.store.enqueue(db, key, f"⚠️ {n['name']} 流量已用约 {n['percent']:.1f}%\n预计剩余：{human_bytes(n['remaining'],n['profile']['unit'])}\n请及时检查，余额为本地估算。", now, node=n["id"])
                if cfg["forecast_enabled"] and n["exhaustion_risk"]:
                    self.store.enqueue(db, f"forecast:{n['id']}:{local.date()}", f"⚠️ {n['name']} 按近期消耗预计还能使用 {n['forecast_days']:.1f} 天，可能在重置前用完。", now, node=n["id"])
                if n["meta"].get("error"):
                    self.store.enqueue(db, f"agent-error:{n['id']}:{local.date()}", f"⚠️ {n['name']} 采集异常：{n['meta']['error']}", now, node=n["id"])
            db.execute("UPDATE notifications SET state='expired',error='超过24小时未发送' WHERE state IN ('pending','retry') AND created<?", (now-86400,))
        self.deliver(now)

    def deliver(self, now=None, only=None, limit=20):
        """Send due messages, oldest first, at most `limit` per call.

        `only` restricts delivery to specific row ids (manual tests); those may target a
        channel that is switched off, and bypass the global Telegram switch.
        """
        now = now or time.time()
        cfg = self.store.settings()
        channels = {c["id"]: c for c in cfg.get("channels", []) if only or c.get("enabled")}
        if not only:
            if not cfg["telegram_enabled"]:
                return
            with self.store.connect() as db:
                marks = ",".join("?"*len(channels))
                db.execute(f"UPDATE notifications SET state='expired',error='通知渠道已删除或停用' WHERE state IN ('pending','retry','sending') AND (channel IS NULL OR channel NOT IN ({marks}))", tuple(channels))
        for _ in range(limit):
            with self.store.connect() as db:
                db.execute("UPDATE notifications SET state='retry' WHERE state='sending' AND due<?", (now,))
                db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
                query, params = "SELECT * FROM notifications WHERE state IN ('pending','retry') AND due<=?", [now]
                if only:
                    query += f" AND id IN ({','.join('?'*len(only))})"
                    params += list(only)
                row = db.execute(query+" ORDER BY created LIMIT 1", params).fetchone()
                if not row:
                    return
                db.execute("UPDATE notifications SET state='sending',due=?,attempts=attempts+1 WHERE id=?", (now+300, row["id"]))
            self.send(row, channels.get(row["channel"]), cfg, now)

    def send(self, row, channel, cfg, now):
        error, retry = "", min(3600, 30*2**min(row["attempts"], 7))
        token = self.store.secret("telegram_token:"+channel["id"]) if channel else ""
        if not channel:
            error, retry = "通知渠道已删除", 86400
        elif not token or not channel.get("chat_id"):
            error = "该通知渠道缺少 Bot Token 或 Chat ID"
        else:
            try:
                with client(self.store.secret("telegram_proxy"), transport=self.transport) as http:
                    response = http.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": channel["chat_id"], "text": row["text"]})
                    body = response.json()
                    if not response.is_success or not body.get("ok"):
                        # Only the status is stored; remote text or exception URLs may echo secrets.
                        error = f"Telegram 返回错误 {response.status_code}，请检查 Token、Chat ID 和网络"
                        if response.status_code == 429:
                            retry = max(1, min(86400, int(body.get("parameters", {}).get("retry_after", 60))))
            except Exception as exc:
                error = f"发送失败：{type(exc).__name__}，将自动重试"
        with self.store.connect() as db:
            db.execute("UPDATE notifications SET state=?,error=?,due=?,delivered=? WHERE id=?", ("retry" if error else "sent", error, now+retry if error else now, None if error else now, row["id"]))

    def maintenance(self, now, cfg):
        local = datetime.fromtimestamp(now, ZoneInfo(cfg["timezone"]))
        directory = self.store.directory / "backups"
        target = directory / f"sentinel-{local.date()}.db"
        if not target.exists():
            self.store.backup(target)
            for old in sorted(directory.glob("sentinel-*.db"))[:-7]:
                old.unlink()
        with self.store.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            db.execute("DELETE FROM enrollments WHERE expires<?", (now,))
            db.execute("DELETE FROM notifications WHERE created<? AND state IN ('sent','expired','suppressed')", (now-90*86400,))
            row = db.execute("SELECT value FROM settings WHERE key='last_compact'").fetchone()
            if not row or now-float(row[0]) >= 3600:
                from .retention import compact
                compact(db, now)
                db.execute("INSERT OR REPLACE INTO settings VALUES('last_compact',?)", (str(now),))
