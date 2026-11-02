"""Cross-platform collector with an atomic SQLite outbox and explicit SOCKS proxy."""
from __future__ import annotations

import argparse
import contextlib
import getpass
import json
import os
import platform
import signal
import socket
import sqlite3
import sys
import threading
import time
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

from . import __version__
from .core import canonical, uid
from .network import client, validate_proxy, validate_url


def boot_id():
    path = Path("/proc/sys/kernel/random/boot_id")
    return path.read_text().strip() if path.exists() else f"boot-{int(boot_time())}"


def boot_time():
    path = Path("/proc/stat")
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("btime "):
                return float(line.split()[1])
    if psutil is not None:
        return psutil.boot_time()
    raise RuntimeError("非 Linux 环境需要安装 psutil")


def interfaces():
    base = Path("/sys/class/net")
    if base.exists():
        result = []
        for path in base.iterdir():
            try:
                result.append({"name": path.name, "rx": int((path / "statistics/rx_bytes").read_text()), "tx": int((path / "statistics/tx_bytes").read_text()), "up": (path / "operstate").read_text().strip() in ("up", "unknown")})
            except OSError:
                continue
        return result
    if psutil is None:
        raise RuntimeError("Windows 网卡采集需要安装 psutil")
    counters = psutil.net_io_counters(pernic=True, nowrap=False)
    states = psutil.net_if_stats()
    return [{"name": name, "rx": c.bytes_recv, "tx": c.bytes_sent, "up": bool(states.get(name) and states[name].isup)} for name, c in counters.items()]


def default_interface():
    route = Path("/proc/net/route")
    if route.exists():
        for line in route.read_text().splitlines()[1:]:
            parts = line.split()
            if len(parts) > 3 and parts[1] == "00000000" and int(parts[3], 16) & 1:
                return parts[0]
    available = [i for i in interfaces() if i["up"] and not i["name"].lower().startswith(("lo", "loopback"))]
    if not available:
        raise ValueError("找不到活动网卡，请使用 interfaces 命令检查")
    return max(available, key=lambda i: i["rx"]+i["tx"])["name"]


def read_counter(interface):
    if Path("/sys/class/net").exists():
        for entry in interfaces():
            if entry["name"] == interface:
                return entry["rx"], entry["tx"]
        raise ValueError("选定网卡不存在，请检查本地接口配置")
    counters = psutil.net_io_counters(pernic=True, nowrap=False)
    if interface not in counters:
        raise ValueError("选定网卡不存在，请检查本地接口配置")
    c = counters[interface]
    return c.bytes_recv, c.bytes_sent


def write_config(path: Path, config: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    fd = os.open(temp, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    if os.name != "nt":
        path.chmod(0o600)


class AgentState:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "state.db"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
            CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), epoch TEXT, seq INTEGER, ack INTEGER, boot TEXT, interface TEXT, at REAL, rx INTEGER, tx INTEGER);
            CREATE TABLE IF NOT EXISTS outbox (seq INTEGER PRIMARY KEY, start REAL, end REAL, rx INTEGER, tx INTEGER, quality TEXT, confirmed REAL);
            """)
            db.execute("INSERT OR IGNORE INTO state VALUES(1,?,0,0,'','',0,0,0)", (uid(),))

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            db.close()

    def record(self, rx, tx, boot, interface, at, boot_at=None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM state WHERE id=1").fetchone()
            if previous["at"] == 0:
                db.execute("UPDATE state SET boot=?,interface=?,at=?,rx=?,tx=? WHERE id=1", (boot, interface, at, rx, tx))
                return None
            if at <= previous["at"]:
                raise ValueError("系统时钟倒退，请校正时间后继续采集")
            if interface != previous["interface"]:
                # Do not interpret unrelated interface totals as traffic.
                raise ValueError("采集网卡已改变，请使用 configure --interface 并重新校准")
            start, quality = previous["at"], "ok"
            if boot != previous["boot"]:
                delta_rx, delta_tx = rx, tx
                start = max(start, boot_at or start)
                quality = "reboot"
            elif rx < previous["rx"] or tx < previous["tx"]:
                delta_rx, delta_tx, quality = rx, tx, "counter_reset"
            else:
                delta_rx, delta_tx = rx-previous["rx"], tx-previous["tx"]
                if at-start > 120:
                    quality = "gap"
            if start >= at:
                raise ValueError("启动时间异常，请检查系统时钟")
            if db.execute("SELECT COUNT(*) FROM outbox WHERE confirmed IS NULL").fetchone()[0] >= 250000:
                raise RuntimeError("待发送缓存已达上限，暂停分段采集；恢复后补回可识别的总增量并标记缺口")
            seq = previous["seq"]+1
            db.execute("INSERT INTO outbox VALUES(?,?,?,?,?,?,NULL)", (seq, start, at, delta_rx, delta_tx, quality))
            db.execute("UPDATE state SET seq=?,boot=?,at=?,rx=?,tx=? WHERE id=1", (seq, boot, at, rx, tx))
            return seq

    def batch(self):
        with self.connect() as db:
            state = dict(db.execute("SELECT * FROM state").fetchone())
            rows = db.execute("SELECT * FROM outbox WHERE seq>? ORDER BY seq LIMIT 500", (state["ack"],)).fetchall()
            result = [{key: r[key] for key in ("seq", "start", "end", "rx", "tx", "quality")} for r in rows]
            count = db.execute("SELECT COUNT(*) FROM outbox WHERE seq>?", (state["ack"],)).fetchone()[0]
        return state, result, max(0, count-len(result))

    def acknowledge(self, seq):
        with self.connect() as db:
            s = db.execute("SELECT * FROM state").fetchone()
            if seq > s["seq"] or seq < 0:
                raise ValueError("主控返回了无效的确认序号")
            if seq < s["ack"]:
                oldest = db.execute("SELECT MIN(seq) FROM outbox WHERE seq>?", (seq,)).fetchone()[0]
                if oldest != seq+1:
                    raise ValueError("主控恢复点早于本地重放窗口，请重新校准和注册")
            db.execute("UPDATE state SET ack=? WHERE id=1", (seq,))
            db.execute("UPDATE outbox SET confirmed=? WHERE seq<=? AND confirmed IS NULL", (time.time(), seq))
            db.execute("DELETE FROM outbox WHERE seq<=? AND confirmed<?", (seq, time.time()-7*86400))

    def rebase_interface(self, interface):
        rx, tx = read_counter(interface)
        with self.connect() as db:
            db.execute("UPDATE state SET interface=?,rx=?,tx=?,at=?,boot=? WHERE id=1", (interface, rx, tx, time.time(), boot_id()))


class Agent:
    def __init__(self, directory, transport=None):
        self.directory = Path(directory)
        self.config = json.loads((self.directory / "config.json").read_text(encoding="utf-8"))
        if not (self.directory / "state.db").exists():
            self.config["data_gap"] = True
            write_config(self.directory / "config.json", self.config)
        self.state = AgentState(directory)
        self.transport = transport
        self.error = ""
        self.checkpoint = None
        self.stop = threading.Event()

    def collect(self):
        try:
            rx, tx = read_counter(self.config["interface"])
            self.state.record(rx, tx, boot_id(), self.config["interface"], time.time(), boot_time())
            self.error = ""
        except Exception as exc:
            self.error = str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"采集失败：{type(exc).__name__}"

    def report(self):
        state, samples, queue = self.state.batch()
        meta = {"hostname": socket.gethostname(), "os": platform.system(), "version": __version__,
                "interface": self.config["interface"], "interfaces": [i["name"] for i in interfaces()],
                "boot_id": boot_id(), "connection": "socks5" if self.config.get("proxy") else "direct",
                "queue": queue, "error": self.error, "data_gap": bool(self.config.get("data_gap"))}
        body = {"epoch": state["epoch"], "samples": samples, "meta": meta}
        if self.checkpoint and not queue and samples:
            body.update(checkpoint=self.checkpoint, checkpoint_seq=samples[-1]["seq"])
        with client(self.config.get("proxy", ""), transport=self.transport) as http:
            response = http.post(self.config["server"]+"/api/agent/v1/report", headers={"Authorization": "Bearer "+self.config["credential"]}, json=body)
            if response.status_code == 409:
                detail = response.json().get("detail", {})
                if isinstance(detail, dict) and "expected_seq" in detail:
                    self.state.acknowledge(detail["expected_seq"]-1)
                    return True
            if not response.is_success:
                raise RuntimeError(f"主控返回 {response.status_code}，请检查身份、时钟和采集状态")
            result = response.json()
        self.state.acknowledge(int(result["ack"]))
        self.checkpoint = result.get("checkpoint_request")
        return bool(queue)

    def run(self, sample_seconds=10, report_seconds=60):
        def reporting():
            delay = 0
            failures = 0
            while not self.stop.wait(delay):
                try:
                    backlog = self.report()
                    failures = 0
                    delay = 1 if backlog or self.checkpoint else report_seconds
                except Exception as exc:
                    failures += 1
                    delay = min(300, 5*2**min(failures, 6))
                    # Never print HTTP URLs containing credentials.
                    print(f"上报未完成：{type(exc).__name__}；{delay} 秒后重试，本地采集继续。", flush=True)
        self.collect()
        worker = threading.Thread(target=reporting, daemon=True)
        worker.start()
        print(f"Agent 已启动：{self.config['interface']}，{'SOCKS5' if self.config.get('proxy') else '直连'}，{sample_seconds} 秒采集 / {report_seconds} 秒上报", flush=True)
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: self.stop.set())
        try:
            while not self.stop.wait(sample_seconds):
                self.collect()
        finally:
            self.stop.set()
            self.collect()
            worker.join(timeout=35)


def main():
    parser = argparse.ArgumentParser(description="流量哨 Agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("interfaces", help="列出可统计的网卡")
    enroll = commands.add_parser("enroll", help="注册并保存配置")
    enroll.add_argument("--server", required=True)
    enroll.add_argument("--token")
    enroll.add_argument("--interface")
    enroll.add_argument("--proxy", action="store_true", help="交互输入 SOCKS5 代理 URL，不写入命令历史")
    enroll.add_argument("--proxy-file", help="读取权限受限文件内的代理 URL")
    for name in ("enroll", "run", "once", "configure", "diagnose"):
        sub = enroll if name == "enroll" else commands.add_parser(name)
        sub.add_argument("--data", default="agent-data")
        if name == "run":
            sub.add_argument("--sample-seconds", type=int, default=10)
            sub.add_argument("--report-seconds", type=int, default=60)
        if name == "configure":
            sub.add_argument("--proxy", action="store_true")
            sub.add_argument("--direct", action="store_true")
            sub.add_argument("--interface")
    args = parser.parse_args()
    if args.command == "interfaces":
        for interface in interfaces():
            print(json.dumps(interface, ensure_ascii=False))
        return
    directory = Path(args.data)
    path = directory / "config.json"
    if args.command == "enroll":
        if path.exists():
            parser.error("节点已注册，请使用 run；修改代理使用 configure")
        server = validate_url(args.server)
        proxy = Path(args.proxy_file).read_text().strip() if args.proxy_file else getpass.getpass("SOCKS5 URL（含可选认证）：") if args.proxy else ""
        proxy = validate_proxy(proxy)
        interface = args.interface or default_interface()
        read_counter(interface)
        token = args.token or os.environ.pop("SENTINEL_ENROLL_TOKEN", "") or getpass.getpass("一次性注册凭据：")
        with client(proxy) as http:
            response = http.post(server+"/api/agent/v1/enroll", json={"token": token, "hostname": socket.gethostname()})
            if not response.is_success:
                raise RuntimeError(f"注册失败（{response.status_code}），请检查一次性凭据和主控地址")
            identity = response.json()
        write_config(path, {"server": server, "proxy": proxy, "interface": interface, **identity})
        AgentState(directory)
        print(f"注册成功，网卡：{interface}。配置已保存在 {path}。")
        print(f'运行：python -m sentinel.agent run --data "{directory}"')
    elif args.command == "configure":
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if args.proxy:
            cfg["proxy"] = validate_proxy(getpass.getpass("新的 SOCKS5 URL："))
        elif args.direct:
            cfg["proxy"] = ""
        with client(cfg.get("proxy", "")) as http:
            response = http.get(cfg["server"]+"/healthz")
            if not response.is_success:
                raise RuntimeError("新连接测试失败，原配置保持不变")
        if args.interface and args.interface != cfg["interface"]:
            AgentState(directory).rebase_interface(args.interface)
            cfg["interface"], cfg["data_gap"] = args.interface, True
        write_config(path, cfg)
        print("配置已保存，请重启 Agent；修改网卡后请重新校准。")
    else:
        agent = Agent(directory)
        if args.command == "diagnose":
            with client(agent.config.get("proxy", "")) as http:
                response = http.get(agent.config["server"]+"/healthz")
            print(f"{'代理' if agent.config.get('proxy') else '直连'}路径主控健康检查：{response.status_code}")
            print(f"选定网卡：{agent.config['interface']}；RX/TX：{read_counter(agent.config['interface'])}")
        elif args.command == "once":
            agent.collect(); agent.report(); print("采集与上报完成")
        else:
            agent.run(max(1, args.sample_seconds), max(1, args.report_seconds))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Connection exceptions can carry proxy credentials. Keep CLI errors bounded.
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError)) else f"操作失败：{type(exc).__name__}，请检查连接配置。", file=sys.stderr)
        sys.exit(1)
