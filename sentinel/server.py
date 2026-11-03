from __future__ import annotations

import argparse
import asyncio
import contextlib
import hmac
import json
import os
import secrets
import shlex
import sqlite3
import time
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from . import __version__
from .accounting import node_view, history
from .core import canonical, cycle_at, digest, finite_timestamp, password_hash, password_ok, uid, validate_profile
from .models import Credentials, NodeInput, Enrollment, Report, Calibration
from .network import validate_agent_proxy, validate_proxy, validate_url
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent


def create_app(data_dir=None, background=True, telegram_transport=None):
    store = Store(data_dir or os.environ.get("SENTINEL_DATA", "data"))
    attempts = defaultdict(list)

    @asynccontextmanager
    async def lifespan(app):
        from .notifications import Scheduler
        scheduler = Scheduler(store, telegram_transport)
        app.state.scheduler = scheduler
        async def worker():
            while True:
                try:
                    await asyncio.to_thread(scheduler.tick)
                except Exception as exc:
                    # Never log remote exception URLs: they may contain Telegram credentials.
                    print(f"scheduler error: {type(exc).__name__}", flush=True)
                await asyncio.sleep(15)
        task = asyncio.create_task(worker()) if background else None
        yield
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="流量哨", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store = store

    @app.middleware("http")
    async def security(request, call_next):
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            length = request.headers.get("content-length")
            if length and (not length.isdigit() or int(length) > 1_000_000):
                return JSONResponse({"detail": "请求体过大"}, status_code=413)
            if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/agent/"):
                origin = request.headers.get("origin")
                if origin and urlparse(origin).netloc != request.headers.get("host"):
                    return JSONResponse({"detail": "请求来源不匹配"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def admin(request: Request):
        token = request.cookies.get("sentinel_session", "")
        with store.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE token=? AND expires>?", (digest(token), time.time())).fetchone()
        if not row:
            raise HTTPException(401, "请先登录")
        if request.method not in ("GET", "HEAD") and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), row["csrf"]):
            raise HTTPException(403, "会话校验失败，请刷新页面")
        return dict(row)

    def agent_identity(request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        with store.connect() as db:
            node = db.execute("SELECT * FROM nodes WHERE credential=? AND disabled=0", (digest(token),)).fetchone()
        if not node:
            raise HTTPException(401, "节点凭据无效或已撤销")
        return dict(node)

    def get_node(db, node_id):
        node = db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if not node:
            raise HTTPException(404, "服务器不存在")
        return node

    @app.get("/api/status")
    def status():
        return {"initialized": store.initialized(), "version": __version__}

    @app.get("/healthz")
    def health():
        with store.connect() as db:
            db.execute("SELECT 1").fetchone()
        return {"ok": True}

    @app.post("/api/setup")
    def setup(body: Credentials):
        if store.initialized():
            raise HTTPException(409, "初始化已经完成")
        path = store.directory / "setup-token.txt"
        if not path.exists() or not hmac.compare_digest(body.setup_token, path.read_text().strip()):
            raise HTTPException(403, "初始化密钥不正确，请查看主控数据目录的 setup-token.txt")
        if len(body.password) < 12:
            raise ValueError("管理员密码至少 12 个字符")
        with store.connect() as db:
            try:
                db.execute("INSERT INTO admin VALUES (1,?,?)", (body.username, password_hash(body.password)))
            except sqlite3.IntegrityError:
                raise HTTPException(409, "初始化已经完成")
        path.unlink(missing_ok=True)
        return {"ok": True}

    @app.post("/api/login")
    def login(body: Credentials, request: Request, response: Response):
        now = time.time()
        key = request.client.host if request.client else "local"
        attempts[key] = [t for t in attempts[key] if now-t < 600]
        if len(attempts[key]) >= 10:
            raise HTTPException(429, "尝试过多，请 10 分钟后重试")
        attempts[key].append(now)
        with store.connect() as db:
            row = db.execute("SELECT * FROM admin").fetchone()
            if not row or body.username != row["username"] or not password_ok(body.password, row["password"]):
                raise HTTPException(401, "用户名或密码不正确")
            token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
            db.execute("DELETE FROM sessions WHERE expires<?", (now,))
            db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), csrf, now+86400))
        attempts[key].clear()
        response.set_cookie("sentinel_session", token, max_age=86400, httponly=True, samesite="strict", secure=os.getenv("SENTINEL_SECURE_COOKIE") == "1")
        return {"csrf": csrf, "username": body.username}

    @app.get("/api/me")
    def me(session=Depends(admin)):
        with store.connect() as db:
            name = db.execute("SELECT username FROM admin").fetchone()[0]
        return {"username": name, "csrf": session["csrf"]}

    @app.post("/api/logout")
    def logout(response: Response, session=Depends(admin)):
        with store.connect() as db:
            db.execute("DELETE FROM sessions WHERE token=?", (session["token"],))
        response.delete_cookie("sentinel_session")
        return {"ok": True}

    @app.post("/api/password", dependencies=[Depends(admin)])
    def change_password(body: dict):
        old, new = str(body.get("old", "")), str(body.get("new", ""))
        if not 12 <= len(new) <= 256:
            raise ValueError("新密码需为 12～256 个字符")
        with store.connect() as db:
            if not password_ok(old, db.execute("SELECT password FROM admin").fetchone()[0]):
                raise ValueError("当前密码不正确")
            db.execute("UPDATE admin SET password=?", (password_hash(new),))
            db.execute("DELETE FROM sessions")
        return {"ok": True}

    @app.get("/api/nodes", dependencies=[Depends(admin)])
    def nodes():
        with store.connect() as db:
            settings = store.settings(db)
            result = [node_view(db, row, report_zone=settings["timezone"], offline_seconds=settings["offline_minutes"]*60) for row in db.execute("SELECT * FROM nodes ORDER BY created DESC").fetchall()]
        return {"nodes": result, "now": time.time(), "timezone": settings["timezone"]}

    @app.post("/api/nodes", dependencies=[Depends(admin)])
    def add_node(body: NodeInput):
        node_id = uid()
        with store.connect() as db:
            db.execute("INSERT INTO nodes(id,name,group_name,note,created) VALUES(?,?,?,?,?)", (node_id, body.name.strip(), body.group_name, body.note, time.time()))
            store.event(db, node_id, "created", f"添加服务器：{body.name}")
        return {"id": node_id}

    @app.put("/api/nodes/{node_id}", dependencies=[Depends(admin)])
    def edit_node(node_id: str, body: NodeInput):
        with store.connect() as db:
            get_node(db, node_id)
            db.execute("UPDATE nodes SET name=?,group_name=?,note=? WHERE id=?", (body.name, body.group_name, body.note, node_id))
        return {"ok": True}

    @app.delete("/api/nodes/{node_id}", dependencies=[Depends(admin)])
    def delete_node(node_id: str):
        with store.connect() as db:
            node = get_node(db, node_id)
            db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
            db.execute("DELETE FROM node_alert_state WHERE node_id=?", (node_id,))
            store.event(db, None, "deleted", f"删除服务器及统计：{node['name']}")
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/revoke", dependencies=[Depends(admin)])
    def revoke(node_id: str):
        with store.connect() as db:
            get_node(db, node_id)
            db.execute("UPDATE nodes SET credential=NULL,disabled=1 WHERE id=?", (node_id,))
            db.execute("DELETE FROM enrollments WHERE node_id=?", (node_id,))
            store.event(db, node_id, "revoked", "节点凭据已撤销，重新注册前不能上报")
        return {"ok": True}

    @app.get("/api/nodes/{node_id}", dependencies=[Depends(admin)])
    def detail(node_id: str):
        with store.connect() as db:
            settings = store.settings(db)
            node = node_view(db, get_node(db, node_id), report_zone=settings["timezone"], offline_seconds=settings["offline_minutes"]*60)
            node["history"] = history(db, node_id, settings["timezone"])
            node["calibrations"] = [dict(r) for r in db.execute("SELECT * FROM calibrations WHERE node_id=? ORDER BY created DESC LIMIT 20", (node_id,))]
        return node

    @app.post("/api/nodes/{node_id}/install", dependencies=[Depends(admin)])
    def install(node_id: str, request: Request):
        token = secrets.token_urlsafe(32)
        with store.connect() as db:
            node = get_node(db, node_id)
            if node["credential"] and not node["disabled"]:
                raise HTTPException(409, "此节点已有 Agent；重新安装前请先撤销旧凭据")
            settings = store.settings(db)
            server = validate_url(settings.get("public_url") or str(request.base_url).rstrip("/"))
            db.execute("DELETE FROM enrollments WHERE node_id=?", (node_id,))
            db.execute("INSERT INTO enrollments VALUES(?,?,?)", (digest(token), node_id, time.time()+1800))
        command = f"curl -fsS {shlex.quote(server+'/install.sh')} -o install-sentinel.sh && sudo bash install-sentinel.sh --server {shlex.quote(server)} --token {shlex.quote(token)}"
        # The admin UI embeds the saved default Agent proxy into the SOCKS5 install command.
        return {"token": token, "server": server, "expires_in": 1800, "linux_command": command, "agent_proxy": store.secret("agent_proxy"),
                "windows_command": f'.\\.venv\\Scripts\\python.exe -m sentinel.agent enroll --server "{server}" --token "{token}" --data "agent-data/{node_id}"'}

    @app.put("/api/nodes/{node_id}/billing", dependencies=[Depends(admin)])
    def billing(node_id: str, body: dict):
        profile = validate_profile(body)
        profile["_updated"] = time.time()
        with store.connect() as db:
            get_node(db, node_id)
            db.execute("UPDATE nodes SET profile=?,checkpoint=NULL,checkpoint_request=NULL WHERE id=?", (canonical(profile), node_id))
            store.event(db, node_id, "billing", "计费配置已更新，请重新校准当前余额")
        return {"ok": True}

    @app.post("/api/nodes/{node_id}/checkpoint", dependencies=[Depends(admin)])
    def checkpoint(node_id: str):
        with store.connect() as db:
            node = get_node(db, node_id)
            if not node["heartbeat"] or time.time()-node["heartbeat"] > 180:
                raise HTTPException(409, "节点离线或数据过期，请等待 Agent 上报")
            check_id = uid()
            db.execute("UPDATE nodes SET checkpoint_request=?,checkpoint=NULL WHERE id=?", (check_id, node_id))
        return {"id": check_id}

    @app.post("/api/nodes/{node_id}/calibrate", dependencies=[Depends(admin)])
    def calibrate(node_id: str, body: Calibration):
        now = time.time()
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            raw = get_node(db, node_id)
            if not raw["profile"]:
                raise ValueError("请先保存计费配置")
            point = json.loads(raw["checkpoint"]) if raw["checkpoint"] else None
            if not point or point["id"] != body.checkpoint_id or now-point["at"] > 120 or now-raw["heartbeat"] > 120:
                raise HTTPException(409, "采集检查点尚未就绪或已过期，请重新获取")
            profile = json.loads(raw["profile"])
            if body.remaining_bytes > profile["quota_bytes"]:
                raise ValueError("剩余流量不能大于周期总额度")
            _, end = cycle_at(profile, point["at"])
            _, current_end = cycle_at(profile, now)
            if end != current_end:
                raise HTTPException(409, "刚跨越重置时间，请重新获取检查点")
            old = node_view(db, raw, now)["remaining"]
            db.execute("INSERT INTO calibrations VALUES(?,?,?,?,?,?,?,?,?,?)", (uid(), node_id, now, point["at"], point["epoch"], point["seq"], body.remaining_bytes, end, old, body.note))
            meta = json.loads(raw["meta"])
            meta.update(data_gap=False, gap_ack_epoch=point["epoch"], gap_ack_interface=meta.get("interface"))
            db.execute("UPDATE nodes SET checkpoint=NULL,checkpoint_request=NULL,meta=? WHERE id=?", (canonical(meta), node_id))
            store.event(db, node_id, "calibrated", "已按商家余额校准；历史采集记录保持不变")
        return {"ok": True}

    MAX_CHANNELS = 20

    def channel_view(channel):
        return {**channel, "token_configured": bool(store.secret("telegram_token:"+channel["id"]))}

    def channel_input(body: dict, current: dict | None = None):
        channel = dict(current or {})
        name = str(body.get("name", channel.get("name", ""))).strip()
        chat = str(body.get("chat_id", channel.get("chat_id", ""))).strip()
        if not name or len(name) > 40:
            raise ValueError("渠道名称应为 1～40 个字符")
        if not chat or len(chat) > 100 or any(ch.isspace() for ch in chat):
            raise ValueError("请填写有效的 Chat ID")
        channel.update(name=name, chat_id=chat)
        for flag in ("enabled", "daily", "alerts"):
            value = body.get(flag, channel.get(flag, True))
            if not isinstance(value, bool):
                raise ValueError("开关设置必须是布尔值")
            channel[flag] = value
        token = str(body.get("bot_token", "")).strip()
        if token and (len(token) > 200 or ":" not in token or "/" in token or " " in token):
            raise ValueError("Bot Token 格式无效")
        return channel, token

    def save_settings(db, cfg, message):
        db.execute("UPDATE settings SET value=? WHERE key='general'", (canonical(cfg),))
        store.event(db, None, "settings", message)

    @app.get("/api/settings", dependencies=[Depends(admin)])
    def settings_get():
        cfg = store.settings()
        cfg["channels"] = [channel_view(c) for c in cfg["channels"]]
        cfg["proxy_configured"] = bool(store.secret("telegram_proxy"))
        cfg["agent_proxy_configured"] = bool(store.secret("agent_proxy"))
        cfg["proxy_url"] = ""
        return cfg

    @app.put("/api/settings", dependencies=[Depends(admin)])
    def settings_put(body: dict):
        with store.connect() as db:
            cfg = store.settings(db)
            for key in ("timezone", "daily_time", "daily_enabled", "telegram_enabled", "thresholds", "offline_minutes", "forecast_enabled", "reset_notice", "pre_reset_notice", "public_url"):
                if key in body:
                    cfg[key] = body[key]
            try:
                ZoneInfo(cfg["timezone"])
            except (KeyError, TypeError):
                raise ValueError("时区无效，请使用 Asia/Shanghai 或 UTC 等 IANA 时区")
            for flag in ("daily_enabled", "telegram_enabled", "forecast_enabled", "reset_notice", "pre_reset_notice"):
                if not isinstance(cfg[flag], bool):
                    raise ValueError("开关设置必须是布尔值")
            hh, mm = map(int, cfg["daily_time"].split(":"))
            if not (0 <= hh < 24 and 0 <= mm < 60):
                raise ValueError("日报时间无效")
            cfg["offline_minutes"] = int(cfg["offline_minutes"])
            if not 1 <= cfg["offline_minutes"] <= 1440:
                raise ValueError("离线阈值应为 1～1440 分钟")
            if not isinstance(cfg["thresholds"], list) or not 1 <= len(cfg["thresholds"]) <= 10 or any(not 1 <= float(t) <= 100 for t in cfg["thresholds"]):
                raise ValueError("告警阈值应为 1～100 的百分比列表")
            cfg["thresholds"] = sorted(set(float(t) for t in cfg["thresholds"]))
            if cfg["public_url"]:
                cfg["public_url"] = validate_url(cfg["public_url"])
            if body.get("proxy_url"):
                store.set_secret("telegram_proxy", validate_proxy(body["proxy_url"]), db)
            if body.get("clear_proxy"):
                store.set_secret("telegram_proxy", "", db)
            if body.get("agent_proxy_url"):
                store.set_secret("agent_proxy", validate_agent_proxy(body["agent_proxy_url"]), db)
            if body.get("clear_agent_proxy"):
                store.set_secret("agent_proxy", "", db)
            if cfg["telegram_enabled"] and not any(c["enabled"] for c in cfg["channels"]):
                raise ValueError("启用 Telegram 前请先添加并启用至少一个通知渠道")
            save_settings(db, cfg, "通知与系统设置已保存")
        return {"ok": True}

    @app.post("/api/telegram/channels", dependencies=[Depends(admin)])
    def channel_create(body: dict):
        with store.connect() as db:
            cfg = store.settings(db)
            if len(cfg["channels"]) >= MAX_CHANNELS:
                raise ValueError(f"最多添加 {MAX_CHANNELS} 个通知渠道")
            channel, token = channel_input(body)
            if not token:
                raise ValueError("请填写 Bot Token")
            channel["id"] = uid()
            store.set_secret("telegram_token:"+channel["id"], token, db)
            cfg["channels"].append(channel)
            save_settings(db, cfg, f"已添加 Telegram 通知渠道：{channel['name']}")
        return channel_view(channel)

    @app.put("/api/telegram/channels/{channel_id}", dependencies=[Depends(admin)])
    def channel_update(channel_id: str, body: dict):
        with store.connect() as db:
            cfg = store.settings(db)
            index = next((i for i, c in enumerate(cfg["channels"]) if c["id"] == channel_id), None)
            if index is None:
                raise HTTPException(404, "通知渠道不存在")
            channel, token = channel_input(body, cfg["channels"][index])
            if token:
                store.set_secret("telegram_token:"+channel_id, token, db)
            cfg["channels"][index] = channel
            if cfg["telegram_enabled"] and not any(c["enabled"] for c in cfg["channels"]):
                raise ValueError("Telegram 通知已启用，至少保留一个启用的渠道；或先关闭 Telegram 通知")
            save_settings(db, cfg, f"已更新 Telegram 通知渠道：{channel['name']}")
        return channel_view(channel)

    @app.delete("/api/telegram/channels/{channel_id}", dependencies=[Depends(admin)])
    def channel_delete(channel_id: str):
        with store.connect() as db:
            cfg = store.settings(db)
            channel = next((c for c in cfg["channels"] if c["id"] == channel_id), None)
            if not channel:
                raise HTTPException(404, "通知渠道不存在")
            cfg["channels"].remove(channel)
            # Deleting the last enabled channel switches Telegram off rather than failing.
            if cfg["telegram_enabled"] and not any(c["enabled"] for c in cfg["channels"]):
                cfg["telegram_enabled"] = False
            db.execute("DELETE FROM settings WHERE key=?", ("telegram_token:"+channel_id,))
            db.execute("UPDATE notifications SET state='expired',error='通知渠道已删除' WHERE channel=? AND state IN ('pending','retry','sending')", (channel_id,))
            save_settings(db, cfg, f"已删除 Telegram 通知渠道：{channel['name']}")
        return {"ok": True, "telegram_enabled": cfg["telegram_enabled"]}

    @app.post("/api/telegram/test", dependencies=[Depends(admin)])
    def telegram_test(body: dict | None = None):
        from .notifications import Scheduler
        channel = (body or {}).get("channel") or None
        cfg = store.settings()
        names = {c["id"]: c["name"] for c in cfg["channels"]}
        if channel and channel not in names:
            raise HTTPException(404, "通知渠道不存在")
        if not channel and not any(c["enabled"] for c in cfg["channels"]):
            raise ValueError("还没有启用的通知渠道")
        with store.connect() as db:
            ids = store.enqueue(db, "manual-test:"+uid(), "✅ 流量哨连接测试成功。日报与流量告警将发送到此会话。", kind="test", channel=channel)
        Scheduler(store, telegram_transport).deliver(only=ids)
        with store.connect() as db:
            rows = [dict(r) for r in db.execute(f"SELECT channel,state,error FROM notifications WHERE id IN ({','.join('?'*len(ids))})", ids)]
        results = [{**r, "name": names.get(r["channel"], "")} for r in rows]
        failed = [r for r in results if r["state"] != "sent"]
        return {"state": "failed" if failed else "sent", "error": "；".join(f"{r['name']}：{r['error'] or '等待重试'}" for r in failed), "results": results}

    @app.post("/api/telegram/daily", dependencies=[Depends(admin)])
    def daily_now():
        from .notifications import Scheduler
        if not store.settings()["telegram_enabled"]:
            raise ValueError("请先启用 Telegram")
        if not Scheduler(store, telegram_transport).queue_daily(manual=True):
            raise ValueError("没有勾选接收日报的已启用渠道")
        return {"ok": True}

    @app.get("/api/telegram/preview", dependencies=[Depends(admin)])
    def daily_preview():
        from .notifications import Scheduler
        return {"text": Scheduler(store).daily_text(time.time())}

    @app.get("/api/events", dependencies=[Depends(admin)])
    def events():
        with store.connect() as db:
            names = {c["id"]: c["name"] for c in store.settings(db)["channels"]}
            notifications = [{**dict(r), "channel_name": names.get(r["channel"], "")} for r in db.execute("SELECT * FROM notifications ORDER BY created DESC LIMIT 100")]
            return {"events": [dict(r) for r in db.execute("SELECT e.*,n.name AS node_name FROM events e LEFT JOIN nodes n ON e.node_id=n.id ORDER BY at DESC LIMIT 150")], "notifications": notifications}

    @app.get("/api/backup", dependencies=[Depends(admin)])
    def backup():
        destination = store.directory / "exports" / (uid()+".zip")
        snapshot = destination.with_suffix(".db")
        store.backup(snapshot)
        with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "sentinel.db")
            archive.write(store.directory / "master.key", "master.key")
        snapshot.unlink()
        return FileResponse(destination, filename="sentinel-backup.zip", background=BackgroundTask(destination.unlink, missing_ok=True))

    @app.post("/api/agent/v1/enroll")
    def enroll(body: Enrollment):
        credential = secrets.token_urlsafe(40)
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM enrollments WHERE token=? AND expires>?", (digest(body.token), time.time())).fetchone()
            if not row:
                raise HTTPException(401, "注册凭据已使用、已过期或无效，请重新生成")
            node_id = row["node_id"]
            db.execute("DELETE FROM enrollments WHERE node_id=?", (node_id,))
            db.execute("UPDATE nodes SET credential=?,enrolled=?,disabled=0,checkpoint=NULL,checkpoint_request=NULL WHERE id=?", (digest(credential), time.time(), node_id))
            store.event(db, node_id, "enrolled", f"Agent 注册成功：{body.hostname}")
        return {"node_id": node_id, "credential": credential}

    @app.post("/api/agent/v1/report")
    def report(body: Report, identity=Depends(agent_identity)):
        now, node_id = time.time(), identity["id"]
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            node = get_node(db, node_id)
            old_meta = json.loads(node["meta"])
            cursor = db.execute("SELECT seq,last_end FROM cursors WHERE node_id=? AND epoch=?", (node_id, body.epoch)).fetchone()
            ack, last_end = (cursor["seq"], cursor["last_end"]) if cursor else (0, 0)
            previous_epochs = db.execute("SELECT COUNT(*) FROM cursors WHERE node_id=?", (node_id,)).fetchone()[0]
            new_epoch = not cursor and previous_epochs > 0
            last_data = node["last_data"] or 0
            for sample in body.samples:
                item = sample.model_dump()
                hash_value = digest(canonical(item))
                if sample.seq <= ack:
                    previous = db.execute("SELECT hash FROM samples WHERE node_id=? AND epoch=? AND seq=?", (node_id, body.epoch, sample.seq)).fetchone()
                    if previous and previous["hash"] != hash_value:
                        raise HTTPException(409, "相同采样序号的内容发生变化")
                    continue
                if sample.seq != ack+1:
                    raise HTTPException(409, {"message": "采样序号不连续", "expected_seq": ack+1})
                if not finite_timestamp(sample.start) or not finite_timestamp(sample.end) or sample.end <= sample.start or sample.end > now+120 or sample.start < last_end-.001:
                    raise ValueError("采集时间无效、重叠或机器时钟偏差过大")
                db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?)", (node_id, body.epoch, sample.seq, sample.start, sample.end, sample.rx, sample.tx, sample.quality, hash_value))
                ack, last_end = sample.seq, sample.end
                last_data = max(last_data, last_end)
            db.execute("INSERT INTO cursors VALUES(?,?,?,?) ON CONFLICT(node_id,epoch) DO UPDATE SET seq=excluded.seq,last_end=excluded.last_end", (node_id, body.epoch, ack, last_end))
            meta = body.meta.model_dump()
            meta["epoch"] = body.epoch
            gap_ack = old_meta.get("gap_ack_epoch") == body.epoch and old_meta.get("gap_ack_interface") == meta.get("interface")
            meta["data_gap"] = (meta["data_gap"] and not gap_ack) or new_epoch or old_meta.get("data_gap", False)
            for key in ("gap_ack_epoch", "gap_ack_interface"):
                if key in old_meta:
                    meta[key] = old_meta[key]
            if new_epoch:
                store.event(db, node_id, "data_gap", "Agent 状态已重新建立，请核对并校准余额")
            if old_meta.get("boot_id") and meta["boot_id"] and old_meta["boot_id"] != meta["boot_id"]:
                store.event(db, node_id, "reboot", "检测到机器重启，累计记录继续保留")
            checkpoint_value = node["checkpoint"]
            checkpoint_request = node["checkpoint_request"]
            if body.checkpoint and body.checkpoint == node["checkpoint_request"] and body.checkpoint_seq == ack and meta["queue"] == 0 and now-last_end <= 120:
                checkpoint_value = canonical({"id": body.checkpoint, "epoch": body.epoch, "seq": ack, "at": last_end})
                # Freeze the calibration anchor and stop accelerated checkpoint polling,
                # including when the user closes the dialog without submitting a balance.
                checkpoint_request = None
            db.execute("UPDATE nodes SET heartbeat=?,last_data=?,meta=?,checkpoint=?,checkpoint_request=? WHERE id=?", (now, last_data, canonical(meta), checkpoint_value, checkpoint_request, node_id))
        return {"ack": ack, "server_time": now, "checkpoint_request": checkpoint_request, "sample_seconds": 10, "report_seconds": 60}

    @app.get("/install.sh", response_class=PlainTextResponse)
    def installer():
        path = ROOT / "scripts" / "install-agent.sh"
        if not path.exists():
            raise HTTPException(503, "安装器尚未构建")
        return path.read_text(encoding="utf-8")

    @app.get("/downloads/{filename}")
    def download(filename: str):
        if filename not in ("sentinel-agent.zip", "SHA256SUMS", "requirements-agent.txt"):
            raise HTTPException(404)
        path = ROOT / "dist" / filename
        if not path.is_file():
            raise HTTPException(503, "请先构建 Agent 发布包")
        return FileResponse(path)

    web_dir = Path(os.environ.get("SENTINEL_WEB", str(ROOT / "frontend" / "dist")))
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    else:
        @app.get("/")
        def no_web():
            return PlainTextResponse("前端尚未构建。请运行 scripts/start-local.ps1，或在 frontend 中运行 npm run build。")
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", default=os.getenv("SENTINEL_DATA", "data"))
    args = parser.parse_args()
    import uvicorn
    app = create_app(args.data)
    print(f"流量哨 http://{args.host}:{args.port} | 数据目录：{Path(args.data).resolve()}")
    if not app.state.store.initialized():
        print("首次初始化密钥保存在数据目录的 setup-token.txt；请在网页创建管理员。")
    uvicorn.run(app, host=args.host, port=args.port, proxy_headers=True, forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"), access_log=False)


if __name__ == "__main__":
    main()
