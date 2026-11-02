"""Archive old samples while retaining the current billing period at full resolution."""
import json
from .core import cycle_at, portion


def compact(db, now, batch_size=10000):
    archived = 0
    for node in db.execute("SELECT id,profile FROM nodes").fetchall():
        cutoff = now-30*86400
        if node["profile"]:
            start, _ = cycle_at(json.loads(node["profile"]), now)
            cutoff = min(cutoff, start)
            anchor = db.execute("SELECT MIN(at) FROM calibrations WHERE node_id=? AND cycle_end>?", (node["id"], now)).fetchone()[0]
            if anchor:
                cutoff = min(cutoff, anchor)
        cutoff = int(cutoff//3600)*3600
        rows = db.execute("SELECT * FROM samples WHERE node_id=? AND end<=? ORDER BY end LIMIT ?", (node["id"], cutoff, batch_size)).fetchall()
        for row in rows:
            hour = int(row["start"]//3600)*3600
            while hour < row["end"]:
                rx = portion(row["rx"], row["start"], row["end"], hour, hour+3600)
                tx = portion(row["tx"], row["start"], row["end"], hour, hour+3600)
                covered = max(0, min(row["end"], hour+3600)-max(row["start"], hour)) if row["quality"] == "ok" else 0
                db.execute("INSERT INTO hourly_usage VALUES(?,?,?,?,?,?) ON CONFLICT(node_id,hour) DO UPDATE SET rx=rx+excluded.rx,tx=tx+excluded.tx,covered=MIN(3600,covered+excluded.covered),uncertain=MAX(uncertain,excluded.uncertain)", (node["id"], hour, rx, tx, covered, int(row["quality"] != "ok")))
                hour += 3600
            db.execute("DELETE FROM samples WHERE node_id=? AND epoch=? AND seq=?", (node["id"], row["epoch"], row["seq"]))
            archived += 1
    # Hourly archives retain two years; cursor rows remain to prevent replay double-counting.
    db.execute("DELETE FROM hourly_usage WHERE hour<?", (now-730*86400,))
    return archived
