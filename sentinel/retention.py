"""Roll old 10-second samples into hourly totals to keep the database and queries small.

Agents report a sample every 10 seconds (8,640 per server per day). Keeping a whole billing
cycle at that resolution made every balance calculation scan millions of rows. Hourly
totals give the same sums; full resolution is only needed for recent data (checkpoints are
at most a few minutes old) and around calibration points, where usage is split exactly at
the checkpoint sample.
"""
from .core import portion

RAW_WINDOW = 48*3600        # recent samples stay at full resolution
ANCHOR_MARGIN = 3600        # ...and so do samples within an hour of a current calibration


def compact(db, now, batch_size=5000):
    """Archive up to `batch_size` samples per server; returns how many were archived."""
    archived = 0
    cutoff = int((now-RAW_WINDOW)//3600)*3600
    for node in db.execute("SELECT id FROM nodes").fetchall():
        anchors = [r[0] for r in db.execute("SELECT at FROM calibrations WHERE node_id=? AND cycle_end>?", (node["id"], now))]
        keep = " ".join(f"AND NOT (end>{a-ANCHOR_MARGIN!r} AND start<{a+ANCHOR_MARGIN!r})" for a in anchors)
        rows = db.execute(f"SELECT * FROM samples WHERE node_id=? AND end<=? {keep} ORDER BY end LIMIT ?", (node["id"], cutoff, batch_size)).fetchall()
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
