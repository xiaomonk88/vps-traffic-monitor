"""Exercise the actual UI against a separate local test database and a live Windows agent."""
import json
import atexit
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parent.parent
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(ROOT / ".cache/playwright")
sys.path.insert(0, str(ROOT))
from sentinel.agent import default_interface, write_config, AgentState

URL = os.environ.get("SMOKE_URL", "http://127.0.0.1:8081")
OUT = ROOT / ".oil-ui/traffic-monitor/shots/implemented"
OUT.mkdir(parents=True, exist_ok=True)
PASSWORD = "local-e2e-test-password-123"


def screenshot(page, name):
    # Wait for Vue's committed render and finite entrance/selection animations.
    page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    page.evaluate("() => Promise.all(document.getAnimations().filter(a => a.effect?.getTiming().iterations !== Infinity).map(a => a.finished.catch(() => {})))")
    page.screenshot(path=str(OUT/name), full_page=True, animations="disabled")


def run():
    errors, checks = [], []
    process = None
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, record_video_dir=str(OUT / "video"), reduced_motion="no-preference")
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(URL)
        expect(page.get_by_label("用户名", exact=True)).to_be_visible()
        if page.get_by_role("heading", name="创建管理员账户").count():
            token = (ROOT / ".runtime/e2e-data/setup-token.txt").read_text()
            page.get_by_label("初始化密钥").fill(token)
            page.get_by_label("密码", exact=True).fill(PASSWORD)
            page.get_by_role("button", name="创建账户并进入").click()
        else:
            page.get_by_label("用户名", exact=True).fill("admin")
            page.get_by_label("密码", exact=True).fill(PASSWORD)
            page.get_by_role("button", name="登录", exact=True).click()
        expect(page.get_by_role("heading", name="流量总览", exact=True)).to_be_visible()
        checks.append("初始化/登录成功并进入主控")
        with httpx.Client(base_url=URL, trust_env=False) as http:
            login = http.post("/api/login", json={"username": "admin", "password": PASSWORD})
            login.raise_for_status()
            http.headers["X-CSRF-Token"] = login.json()["csrf"]
            # Clear only nodes in the dedicated test DB; never connect this script to production.
            assert URL.endswith(":8081"), "测试脚本只允许使用隔离端口8081"
            for node in http.get("/api/nodes").json()["nodes"]:
                http.delete("/api/nodes/"+node["id"]).raise_for_status()
            page.reload()
            expect(page.get_by_text("接入第一台服务器", exact=True)).to_be_visible()
            screenshot(page,"empty-desktop.png")
            page.get_by_role("button", name="添加服务器", exact=True).first.click()
            page.get_by_label("服务器名称", exact=True).fill("Windows 本地验证")
            page.get_by_role("button", name="创建并生成安装命令").click()
            expect(page.get_by_text("注册凭据已生成", exact=False)).to_be_visible()
            page.get_by_label("目标系统").select_option("windows")
            expect(page.get_by_text("1. 注册本地 Agent", exact=True)).to_be_visible()
            page.get_by_label("连接方式").select_option("true")
            expect(page.locator("pre").first).to_contain_text("--proxy")
            page.get_by_label("连接方式").select_option("false")
            page.get_by_role("button", name="返回服务器列表").click()
            checks.append("添加节点、生成Windows/SOCKS5安装命令")
            node = http.get("/api/nodes").json()["nodes"][0]
            install = http.post(f"/api/nodes/{node['id']}/install").json()
            identity = http.post("/api/agent/v1/enroll", json={"token": install["token"], "hostname": "Windows-live-test"}).json()
            agent_dir = ROOT / ".runtime" / ("e2e-agent-"+node["id"])
            write_config(agent_dir / "config.json", {"server": URL, "proxy": "", "interface": default_interface(), **identity})
            AgentState(agent_dir)
            log = open(agent_dir / "agent.log", "w", encoding="utf-8")
            process = subprocess.Popen([sys.executable, "-m", "sentinel.agent", "run", "--data", str(agent_dir), "--sample-seconds", "1", "--report-seconds", "1"], cwd=ROOT, stdout=log, stderr=log, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
            atexit.register(lambda: process.terminate() if process and process.poll() is None else None)
            deadline = time.monotonic()+20
            while time.monotonic() < deadline:
                data = http.get(f"/api/nodes/{node['id']}").json()
                if data["fresh"]:
                    break
                time.sleep(.3)
            assert data["fresh"], data
            page.get_by_role("button", name="刷新服务器列表").click()
            page.get_by_role("button").filter(has=page.get_by_text("Windows 本地验证", exact=True)).click()
            page.get_by_role("button", name="计费设置", exact=True).click()
            page.get_by_label("每周期总额度", exact=True).fill("600")
            page.get_by_label("计费方向", exact=False).select_option("tx")
            reset = (datetime.now()+timedelta(days=14)).replace(hour=0, minute=0, second=0, microsecond=0)
            page.get_by_label("下次重置日期与时间", exact=True).fill(reset.strftime("%Y-%m-%dT%H:%M"))
            page.get_by_label("之后每月几号", exact=True).fill(str(reset.day))
            page.get_by_role("button", name="保存计费规则", exact=True).click()
            expect(page.get_by_text("计费规则已保存", exact=False)).to_be_visible()
            page.get_by_role("button", name="余额校准", exact=True).click()
            page.get_by_role("button", name="获取检查点", exact=True).click()
            expect(page.get_by_text("检查点就绪", exact=False)).to_be_visible(timeout=20000)
            page.get_by_label("2. 商家当前剩余流量", exact=False).fill("999")
            page.get_by_role("button", name="保存校准余额", exact=True).click()
            expect(page.get_by_role("alert")).to_contain_text("剩余流量不能大于")
            expect(page.get_by_label("2. 商家当前剩余流量", exact=False)).to_have_value("999")
            page.get_by_label("2. 商家当前剩余流量", exact=False).fill("563")
            page.get_by_role("button", name="保存校准余额", exact=True).click()
            expect(page.get_by_role("status")).to_contain_text("余额已校准")
            checks.append("真实网卡采集、计费保存、检查点校准、失败保留输入")
            page.get_by_role("button", name="流量概况", exact=True).click()
            expect(page.locator('.tabs button.active')).to_have_text('流量概况')
            screenshot(page,"detail-desktop.png")
            page.get_by_role("button", name="关闭对话框", exact=True).click()
            page.reload()
            expect(page.get_by_text("Windows 本地验证", exact=True)).to_be_visible()
            expect(page.get_by_text("563", exact=False).first).to_be_visible()
            checks.append("保存后刷新读回")
            screenshot(page,"dashboard-desktop.png")
            page.get_by_role("button", name="通知设置", exact=True).click()
            expect(page.get_by_text('正在加载设置…', exact=True)).to_have_count(0)
            expect(page.get_by_label('Chat ID', exact=False)).to_be_visible()
            screenshot(page,"notifications-desktop.png")
            page.get_by_role("button", name="流量总览", exact=True).click()
            page.set_viewport_size({"width": 390, "height": 844})
            screenshot(page,"dashboard-mobile.png")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth+1"), "移动页面横向溢出"
            checks.append("390px移动视口无横向溢出")
            zoom_context = browser.new_context(viewport={"width":720,"height":500}, device_scale_factor=2, storage_state=context.storage_state())
            zoom_page = zoom_context.new_page()
            zoom_page.goto(URL)
            expect(zoom_page.get_by_text('Windows 本地验证', exact=True)).to_be_visible()
            screenshot(zoom_page,"dashboard-200-percent.png")
            assert zoom_page.evaluate("document.documentElement.scrollWidth <= innerWidth+1"), "等效200%重排横向溢出"
            zoom_context.close()
            checks.append("720CSS像素/2倍设备比例的等效200%重排检查")
            context.storage_state(path=str(ROOT/".runtime/e2e-browser-state.json"))
        context.close()
        browser.close()
        if process:
            process.terminate(); process.wait(timeout=10); log.close()
    assert not errors, errors
    (OUT/"browser-checks.json").write_text(json.dumps({"checks": checks, "console_errors": errors}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": checks, "console_errors": errors}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
