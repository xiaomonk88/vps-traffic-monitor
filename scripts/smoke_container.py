"""Check a built image with a private ephemeral port/volume; no Telegram delivery."""
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    return subprocess.check_output(["docker", *args], text=True).strip()


name = "sentinel-smoke-" + uuid.uuid4().hex[:12]
volume = name + "-data"
image = sys.argv[1] if len(sys.argv) > 1 else "traffic-sentinel:ci"
created = False
docker("volume", "create", volume)
try:
    docker("run", "-d", "--name", name, "--read-only", "--tmpfs", "/tmp",
           "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
           "-p", "127.0.0.1::8080", "-v", volume+":/data", image)
    created = True
    port = docker("port", name, "8080/tcp").rsplit(":", 1)[1]
    base = "http://127.0.0.1:" + port
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get(path):
        with opener.open(base+path, timeout=5) as response:
            return response.read()

    def ready():
        for _ in range(45):
            try:
                if json.loads(get("/healthz"))["ok"]:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(1)
        raise RuntimeError("Container health check timed out")

    ready()
    assert b"/assets/" in get("/")
    assert json.loads(get("/api/status"))["initialized"] is False
    assert get("/install.sh").startswith(b"#!/usr/bin/env bash")
    expected = get("/downloads/SHA256SUMS").decode().split()[0]
    assert hashlib.sha256(get("/downloads/sentinel-agent.zip")).hexdigest() == expected
    original_key = docker("exec", name, "sha256sum", "/data/master.key")
    docker("restart", name)
    # Docker may assign a different ephemeral host port after a restart.
    port = docker("port", name, "8080/tcp").rsplit(":", 1)[1]
    base = "http://127.0.0.1:" + port
    ready()
    assert original_key == docker("exec", name, "sha256sum", "/data/master.key")
    print("Container health, static assets, Agent package, non-root volume and restart passed")
except BaseException:
    if created:
        print(docker("logs", name))
    raise
finally:
    if created:
        docker("rm", "-f", name)
    docker("volume", "rm", volume)
