"""SQLite spot-price snapshot store + TWAP.

Phase 0 keeps it deliberately simple: every refresh appends one snapshot
per priced token; TWAP is the plain average of snapshots inside the
window, returned only when there is enough history (see twap()).
(The design draft's V2 cumulative-price TWAP is a later refinement.)
"""

import sqlite3
import time

WINDOWS = {"1h": 3600, "24h": 86400}

# "Enough history": at least 2 snapshots whose timestamps span at least
# half of the requested window.
MIN_SNAPSHOTS = 2
MIN_SPAN_FRACTION = 0.5


class SnapshotStore:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS snapshots ("
            " ts REAL NOT NULL, symbol TEXT NOT NULL,"
            " address TEXT, price REAL NOT NULL)")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snap_addr_ts"
            " ON snapshots(address, ts)")
        self._conn.commit()

    def add_snapshots(self, ts: float, rows):
        """rows: iterable of (symbol, address, price).

        Addresses are stored lowercased: Ethereum addresses are
        case-insensitive, and a checksummed snapshot must be findable by a
        lowercase query (review finding, 2026-11-14).
        """
        self._conn.executemany(
            "INSERT INTO snapshots (ts, symbol, address, price)"
            " VALUES (?, ?, ?, ?)",
            [(ts, s, a.lower() if a else a, p) for (s, a, p) in rows])
        self._conn.commit()

    def twap(self, address: str, window_seconds: int, now: float | None = None):
        """-> dict with twap (float|None), snapshots count, span, note."""
        now = now if now is not None else time.time()
        cur = self._conn.execute(
            "SELECT ts, price FROM snapshots"
            " WHERE lower(address) = ? AND ts >= ? ORDER BY ts",
            (address.lower(), now - window_seconds))
        rows = cur.fetchall()
        if len(rows) < MIN_SNAPSHOTS:
            return {"twap": None, "snapshots": len(rows), "span_seconds": 0.0,
                    "note": "insufficient_history: "
                            f"{len(rows)} snapshot(s) in window"}
        span = rows[-1][0] - rows[0][0]
        if span < MIN_SPAN_FRACTION * window_seconds:
            return {"twap": None, "snapshots": len(rows), "span_seconds": span,
                    "note": "insufficient_history: snapshots span "
                            f"{span:.0f}s of {window_seconds}s window"}
        avg = sum(p for _ts, p in rows) / len(rows)
        return {"twap": avg, "snapshots": len(rows), "span_seconds": span,
                "note": None}
