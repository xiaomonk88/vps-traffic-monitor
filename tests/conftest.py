import json
import time

import pytest
from fastapi.testclient import TestClient

from sentinel.server import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path, background=False)


@pytest.fixture
def client(app):
    with TestClient(app, base_url="http://127.0.0.1") as c:
        token = (app.state.store.directory / "setup-token.txt").read_text()
        assert c.post("/api/setup", json={"username": "admin", "password": "test-only-password-123", "setup_token": token}).status_code == 200
        login = c.post("/api/login", json={"username": "admin", "password": "test-only-password-123"})
        c.headers["x-csrf-token"] = login.json()["csrf"]
        yield c


@pytest.fixture
def node(client):
    node_id = client.post("/api/nodes", json={"name": "香港测试节点"}).json()["id"]
    token = client.post(f"/api/nodes/{node_id}/install").json()["token"]
    registration = client.post("/api/agent/v1/enroll", json={"token": token, "hostname": "test-machine"}).json()
    return node_id, {"Authorization": "Bearer "+registration["credential"]}


def report(client, node, samples, epoch="test-epoch-001", checkpoint=None, boot="boot-1", queue=0):
    body = {"epoch": epoch, "samples": samples, "meta": {"boot_id": boot, "interface": "eth0", "queue": queue}}
    if checkpoint:
        body.update(checkpoint=checkpoint, checkpoint_seq=samples[-1]["seq"])
    return client.post("/api/agent/v1/report", headers=node[1], json=body)


def sample(seq, start, end, tx, rx=0, quality="ok"):
    return {"seq": seq, "start": start, "end": end, "rx": rx, "tx": tx, "quality": quality}
