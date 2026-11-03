"""Custom server list order (drag-and-drop in the panel)."""
import sqlite3

from sentinel.server import create_app


def names(client):
    return [n["name"] for n in sorted(client.get("/api/nodes").json()["nodes"], key=lambda n: n["position"])]


def test_new_servers_append_and_order_is_saved(client):
    ids = [client.post("/api/nodes", json={"name": name}).json()["id"] for name in ("甲", "乙", "丙", "丁")]
    assert names(client) == ["甲", "乙", "丙", "丁"]
    assert client.put("/api/nodes/order", json={"ids": [ids[2], ids[0], "unknown"]}).status_code == 200
    assert names(client) == ["丙", "甲", "乙", "丁"]  # unlisted servers keep their relative order after
    client.post("/api/nodes", json={"name": "戊"})
    assert names(client)[-1] == "戊"
    assert client.put("/api/nodes/order", json={"ids": "bad"}).status_code == 400


def test_existing_servers_get_positions_by_creation_on_upgrade(tmp_path):
    create_app(tmp_path, background=False)
    db = sqlite3.connect(tmp_path / "sentinel.db")
    db.execute("ALTER TABLE nodes DROP COLUMN position")
    for i, name in enumerate(("二", "一", "三")):
        db.execute("INSERT INTO nodes(id,name,created) VALUES(?,?,?)", (f"id{i}", name, [20, 10, 30][i]))
    db.commit()
    db.close()
    store = create_app(tmp_path, background=False).state.store
    with store.connect() as db:
        assert [r[0] for r in db.execute("SELECT name FROM nodes ORDER BY position")] == ["一", "二", "三"]
