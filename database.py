import sqlite3
import threading
from typing import List, Optional

from config import DB_PATH

# ---------- DB + migrazioni ----------
DB_LOCK = threading.Lock()
DB = sqlite3.connect(DB_PATH, check_same_thread=False)
DB.execute("PRAGMA journal_mode=WAL")
DB.execute("PRAGMA synchronous=NORMAL")


def _cols(table: str) -> List[str]:
    cur = DB.execute(f"PRAGMA table_info('{table}')")
    return [r[1] for r in cur.fetchall()]


def migrate() -> None:
    with DB_LOCK:
        # tabelle base
        DB.execute(
            """
            CREATE TABLE IF NOT EXISTS telemetry (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER,
              node_id TEXT,
              node_name TEXT,
              metric TEXT NOT NULL,
              value REAL NOT NULL,
              ts_ms INTEGER, topic TEXT, node TEXT, raw_json TEXT
            )
            """,
        )

        DB.execute(
            """
            CREATE TABLE IF NOT EXISTS nodes (
              node_id TEXT PRIMARY KEY,
              short_name TEXT,
              long_name TEXT,
              last_seen INTEGER,
              info_packets INTEGER DEFAULT 0,
              lat REAL,
              lon REAL,
              alt REAL
            )
            """,
        )

        # colonne telemetry
        tcols = _cols("telemetry")
        if "ts" not in tcols:
            DB.execute("ALTER TABLE telemetry ADD COLUMN ts INTEGER")
        if "ts_ms" in tcols:
            DB.execute("UPDATE telemetry SET ts = COALESCE(ts, ts_ms/1000)")
        if "node_id" not in tcols:
            DB.execute("ALTER TABLE telemetry ADD COLUMN node_id TEXT")
        if "node" in tcols:
            DB.execute("UPDATE telemetry SET node_id = COALESCE(node_id, node)")
        if "node_name" not in tcols:
            DB.execute("ALTER TABLE telemetry ADD COLUMN node_name TEXT")
        DB.execute("UPDATE telemetry SET metric='humidity' WHERE metric='relative_humidity'")
        DB.execute("UPDATE telemetry SET metric='pressure'  WHERE metric='barometric_pressure'")

        # colonne nodes (aggiungi se mancano)
        ncols = _cols("nodes")
        if "short_name" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN short_name TEXT")
        if "long_name" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN long_name TEXT")
        if "last_seen" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN last_seen INTEGER")
        if "info_packets" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN info_packets INTEGER DEFAULT 0")
        if "lat" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN lat REAL")
        if "lon" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN lon REAL")
        if "alt" not in ncols:
            DB.execute("ALTER TABLE nodes ADD COLUMN alt REAL")
        DB.execute("UPDATE nodes SET last_seen = 0 WHERE last_seen IS NULL")
        DB.execute("UPDATE nodes SET info_packets = 0 WHERE info_packets IS NULL")

        DB.execute(
            """
            CREATE TABLE IF NOT EXISTS traceroutes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER,
              src_id TEXT,
              dest_id TEXT,
              route TEXT,
              hop_count INTEGER
            )
            """,
        )

        DB.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER,
              node_id TEXT,
              portnum TEXT,
              raw_json TEXT
            )
            """,
        )

        # indici
        DB.execute("CREATE INDEX IF NOT EXISTS idx_telem_ts ON telemetry(ts)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_telem_nodeid ON telemetry(node_id)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_telem_metric ON telemetry(metric)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(COALESCE(long_name, short_name))")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_traceroutes_ts ON traceroutes(ts)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_messages_ts ON messages(ts)")
        DB.commit()


migrate()


def upsert_node(
    node_id: Optional[str],
    short_name: Optional[str],
    long_name: Optional[str],
    ts: int,
    info_packet: bool = False,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    alt: Optional[float] = None,
) -> None:
    if not node_id and not (short_name or long_name):
        return
    short_name = (short_name or "").strip() or None
    long_name = (long_name or "").strip() or None
    inc = 1 if info_packet else 0
    with DB_LOCK:
        DB.execute(
            """
          INSERT INTO nodes(node_id, short_name, long_name, last_seen, info_packets, lat, lon, alt)
          VALUES(?, ?, ?, ?, ?, ?, ?, ?)
          ON CONFLICT(node_id) DO UPDATE SET
            short_name = COALESCE(excluded.short_name, nodes.short_name),
            long_name  = COALESCE(excluded.long_name, nodes.long_name),
            last_seen  = MAX(nodes.last_seen, excluded.last_seen),

            info_packets = nodes.info_packets + excluded.info_packets,
            lat = COALESCE(excluded.lat, nodes.lat),
            lon = COALESCE(excluded.lon, nodes.lon),
            alt = COALESCE(excluded.alt, nodes.alt)
        """,
            (node_id, short_name, long_name, ts, inc, lat, lon, alt),
        )
        name_to_set = long_name or short_name
        if node_id and name_to_set:
            DB.execute(
                """
              UPDATE telemetry SET node_name = ?
              WHERE node_id = ? AND (node_name IS NULL OR node_name = '')
            """,
                (name_to_set, node_id),
            )

        DB.commit()


def store_metric(ts: int, node_id: str, metric: str, value: float) -> None:
    with DB_LOCK:
        cur = DB.execute("SELECT long_name, short_name FROM nodes WHERE node_id=?", (node_id,))
        row = cur.fetchone()
        node_name = (row[0] or row[1]) if row else None
        DB.execute(
            "INSERT INTO telemetry(ts, node_id, node_name, metric, value) VALUES(?,?,?,?,?)",
            (ts, node_id, node_name, metric, float(value)),
        )
        DB.commit()
