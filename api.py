import json
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple

from fastapi import Body, FastAPI, Query, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
try:
    from fastapi.middleware.cors import CORSMiddleware
    HAVE_CORS = True
except Exception:  # pragma: no cover - middleware non disponibile
    HAVE_CORS = False

from config import ALLOW_CORS, UNITS, POWER_V_KEYS, POWER_I_KEYS
from database import DB, DB_LOCK
from mqtt_client import start_mqtt

from paho.mqtt.client import Client as MQTTClient

mqtt_client_ref: Optional[MQTTClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global mqtt_client_ref
    mqtt_client_ref = start_mqtt()
    try:
        yield
    finally:
        try:
            if mqtt_client_ref:
                mqtt_client_ref.loop_stop()
        except Exception:
            pass
        try:
            if mqtt_client_ref:
                mqtt_client_ref.disconnect()
        except Exception:
            pass
        try:
            DB.close()
        except Exception:
            pass


app = FastAPI(title="Meshtastic Telemetry (embedded UI)", lifespan=lifespan)
if ALLOW_CORS and HAVE_CORS:
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serve the browser favicon."""
    return FileResponse(os.path.join("static", "favicon.svg"), media_type="image/svg+xml")


@app.get("/")
def ui():
    return FileResponse(os.path.join("static", "index.html"))


@app.get("/map")
def map_ui():
    return FileResponse(os.path.join("static", "map.html"))


@app.get("/traceroutes")
def traceroutes_ui():
    return FileResponse(os.path.join("static", "traceroutes.html"))


@app.get("/admin")
def admin_ui():
    return FileResponse(os.path.join("static", "admin.html"))


@app.get("/api/nodes")
def api_nodes():
    with DB_LOCK:
        old_factory = DB.row_factory
        DB.row_factory = sqlite3.Row
        try:
            cur = DB.execute(
                """
            SELECT node_id, short_name, long_name, nickname, last_seen, info_packets, lat, lon, alt
            FROM nodes ORDER BY COALESCE(nickname, long_name, short_name, node_id)
        """
            )
            rows = cur.fetchall()
        finally:
            DB.row_factory = old_factory
    out = []
    for r in rows:
        disp = r["nickname"] or r["long_name"] or r["short_name"] or r["node_id"]
        out.append(
            {
                "node_id": r["node_id"],
                "short_name": r["short_name"],
                "long_name": r["long_name"],
                "nickname": r["nickname"],
                "display_name": disp,
                "last_seen": r["last_seen"],
                "info_packets": r["info_packets"],
                "lat": r["lat"],
                "lon": r["lon"],
                "alt": r["alt"],
            }
        )

    return JSONResponse(out)


@app.get("/api/traceroutes")
def api_traceroutes(limit: int = Query(default=100, ge=1, le=1000)):
    with DB_LOCK:
        cur = DB.execute(
            """
            SELECT MAX(ts) AS ts, src_id, dest_id, route, hop_count
            FROM traceroutes
            GROUP BY src_id, dest_id, route, hop_count
            ORDER BY ts DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cur.fetchall()
    out = []
    for ts, src, dest, route_json, hop in rows:
        try:
            route = json.loads(route_json) if route_json else []
        except Exception:
            route = []
        out.append({"ts": ts, "src_id": src, "dest_id": dest, "route": route, "hop_count": hop})
    return JSONResponse(out)


@app.post("/api/nodes/nickname")
async def api_set_nickname(req: Request):
    data = await req.json()
    node_id = data.get("node_id")
    nickname = (data.get("nickname") or "").strip() or None
    if not node_id:
        return JSONResponse({"error": "node_id required"}, status_code=400)
    with DB_LOCK:
        DB.execute("UPDATE nodes SET nickname=? WHERE node_id=?", (nickname, node_id))
        DB.commit()
    return JSONResponse({"status": "ok"})


@app.post("/api/admin/sql")
def api_admin_sql(payload: Dict[str, Any] = Body(...)):
    query = (payload.get("query") or "").strip()
    params = payload.get("params") or []
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    with DB_LOCK:
        cur = DB.execute(query, params)
        rows: List[Dict[str, Any]] = []
        if query.lstrip().lower().startswith("select"):
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        DB.commit()
    return JSONResponse({"rows": rows})


def _resolve_ids(names: List[str]) -> List[str]:
    if not names:
        return []
    qs = ",".join("?" for _ in names)
    with DB_LOCK:
        cur = DB.execute(
            f"""
            SELECT node_id FROM nodes
            WHERE COALESCE(nickname, long_name, short_name, node_id) IN ({qs})
        """,
            (*names,),
        )
        ids = [r[0] for r in cur.fetchall()]
    for n in names:
        if n not in ids:
            ids.append(n)  # consenti passare direttamente node_id
    return list(dict.fromkeys(ids))


@app.get("/api/metrics")
def api_metrics(
    nodes: Optional[str] = Query(default=None, description="Nomi visuali o node_id separati da virgola"),
    since_s: int = Query(default=24 * 3600, ge=0, le=30 * 24 * 3600),
    use_nick: int = Query(default=0, ge=0, le=1),
):
    since_ts = int(time.time()) - since_s
    selected = [s.strip() for s in (nodes.split(",") if nodes else []) if s.strip()]
    ids = _resolve_ids(selected) if selected else []
    name_expr = (
        "COALESCE(nodes.nickname, telemetry.node_name, nodes.long_name, nodes.short_name, telemetry.node_id)"
        if use_nick
        else "COALESCE(telemetry.node_name, nodes.long_name, nodes.short_name, telemetry.node_id)"
    )

    with DB_LOCK:
        old_factory = DB.row_factory
        DB.row_factory = sqlite3.Row
        try:
            if ids:
                qs = ",".join("?" for _ in ids)
                cur = DB.execute(
                    f"""
                SELECT
                    telemetry.ts            AS ts,
                    telemetry.node_id       AS node_id,
                    {name_expr} AS disp,
                    telemetry.metric        AS metric,
                    telemetry.value         AS value
                FROM telemetry
                LEFT JOIN nodes ON nodes.node_id = telemetry.node_id
                WHERE telemetry.ts >= ? AND telemetry.node_id IN ({qs})
                ORDER BY telemetry.ts ASC
            """,
                    (since_ts, *ids),
                )
            else:
                cur = DB.execute(
                    f"""
                SELECT
                    telemetry.ts            AS ts,
                    telemetry.node_id       AS node_id,
                    {name_expr} AS disp,
                    telemetry.metric        AS metric,
                    telemetry.value         AS value
                FROM telemetry
                LEFT JOIN nodes ON nodes.node_id = telemetry.node_id
                WHERE telemetry.ts >= ?
                ORDER BY telemetry.ts ASC
            """,
                    (since_ts,),
                )
            rows = cur.fetchall()
        finally:
            DB.row_factory = old_factory

    fams = {"temperature": [], "humidity": [], "pressure": [], "voltage": [], "current": []}
    acc: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def add(fam: str, node_id: str, label: str, ts: int, val: float):
        acc.setdefault((fam, node_id), {"node_id": node_id, "label": label, "data": []})["data"].append(
            {"x": ts * 1000, "y": float(val)}
        )

    for r in rows:
        ts, node_id, disp, met, val = int(r["ts"]), r["node_id"], r["disp"], r["metric"], float(r["value"])
        if met == "temperature":
            add("temperature", node_id, f"{disp} — Temperatura ({UNITS['temperature']})", ts, val)
        elif met == "humidity":
            add("humidity", node_id, f"{disp} — Umidità ({UNITS['humidity']})", ts, val)
        elif met == "pressure":
            add("pressure", node_id, f"{disp} — Pressione ({UNITS['pressure']})", ts, val)
        elif met == "voltage":
            add("voltage", node_id, f"{disp} — Tensione ({UNITS['voltage']})", ts, val)
        elif met == "current":
            add("current", node_id, f"{disp} — Corrente ({UNITS['current']})", ts, val)
        elif met in POWER_V_KEYS:
            ch = met.replace("ch", "").replace("_voltage", "")
            add("voltage", node_id, f"{disp} — Tensione ch{ch} (V)", ts, val)
        elif met in POWER_I_KEYS:
            ch = met.replace("ch", "").replace("_current", "")
            add("current", node_id, f"{disp} — Corrente ch{ch} ({UNITS[met]})", ts, val)

    out = {k: [] for k in fams}
    for (fam, _node_id), ds in acc.items():
        out[fam].append(ds)
    return JSONResponse({"units": UNITS, "series": out})
