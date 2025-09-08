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

from config import ALLOW_CORS, UNITS, POWER_V_KEYS, POWER_I_KEYS, TRACEROUTE_TTL
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


@app.get("/setup")
def setup_ui():
    return FileResponse(os.path.join("static", "setup.html"))


def _estimate_missing_positions(nodes: List[Dict[str, Any]]) -> None:
    """Assign estimated coordinates to nodes lacking a position.

    Nodes that have no ``lat``/``lon`` values but appear in traceroute paths
    alongside nodes with known coordinates will be placed near or between those
    neighbours:

    * if only a single neighbour has a known position, the node is placed just
      offset from that neighbour's location;
    * if two or more neighbours have known positions, the node is centred
      amongst them (average latitude/longitude).

    The function mutates the ``nodes`` list in place.
    """

    known_pos = {
        n["node_id"]: (n["lat"], n["lon"], n.get("alt"))
        for n in nodes
        if n.get("lat") is not None and n.get("lon") is not None
    }
    unknown = [n for n in nodes if n.get("lat") is None or n.get("lon") is None]
    if not unknown:
        return

    with DB_LOCK:
        cur = DB.execute("SELECT route FROM traceroutes")
        routes = [json.loads(r[0]) for r in cur.fetchall() if r[0]]

    for node in unknown:
        nid = node["node_id"]
        neighbours: set[str] = set()
        for route in routes:
            if nid in route:
                for other in route:
                    if other != nid and other in known_pos:
                        neighbours.add(other)

        if not neighbours:
            continue

        if len(neighbours) == 1:
            lat, lon, alt = known_pos[next(iter(neighbours))]
            offset = 0.001
            node["lat"] = lat + offset
            node["lon"] = lon + offset
            if node.get("alt") is None and alt is not None:
                node["alt"] = alt
        else:
            lats = [known_pos[n][0] for n in neighbours]
            lons = [known_pos[n][1] for n in neighbours]
            alts = [known_pos[n][2] for n in neighbours if known_pos[n][2] is not None]
            node["lat"] = sum(lats) / len(lats)
            node["lon"] = sum(lons) / len(lons)
            if alts and node.get("alt") is None:
                node["alt"] = sum(alts) / len(alts)


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
    _estimate_missing_positions(out)
    return JSONResponse(out)


@app.get("/api/traceroutes")
def api_traceroutes(
    limit: int = Query(default=100, ge=1, le=1000),
    max_age: int = Query(default=TRACEROUTE_TTL, ge=0),
):
    params: List[Any] = []
    sub_where = ""
    if max_age:
        cutoff = int(time.time()) - max_age
        sub_where = "WHERE ts >= ?"
        params.append(cutoff)
    params.append(limit)
    with DB_LOCK:
        cur = DB.execute(
            f"""
            SELECT t.ts, t.src_id, t.dest_id, t.route, t.hop_count, t.radio
            FROM (
                SELECT src_id, dest_id, MAX(ts) AS max_ts
                FROM traceroutes
                {sub_where}
                GROUP BY src_id, dest_id
            ) AS latest
            JOIN traceroutes AS t
              ON t.src_id = latest.src_id
             AND t.dest_id = latest.dest_id
             AND t.ts = latest.max_ts
            ORDER BY t.ts DESC
            LIMIT ?
            """,
            params,
        )
        rows = cur.fetchall()
    out = []
    for ts, src, dest, route_json, hop, radio_json in rows:
        try:
            route = json.loads(route_json) if route_json else []
        except Exception:
            route = []
        try:
            radio = json.loads(radio_json) if radio_json else None
        except Exception:
            radio = None
        via = "radio" if radio else "mqtt"
        out.append(
            {
                "ts": ts,
                "src_id": src,
                "dest_id": dest,
                "route": route,
                "hop_count": hop,
                "radio": radio,
                "via": via,
            }
        )
    return JSONResponse(out)


@app.delete("/api/traceroutes")
def api_delete_traceroutes():
    with DB_LOCK:
        DB.execute("DELETE FROM traceroutes")
        DB.commit()
    return JSONResponse({"status": "ok"})


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


@app.put("/api/admin/nodes/{node_id}")
def api_admin_update_node(node_id: str, payload: Dict[str, Any] = Body(...)):
    allowed = ["short_name", "long_name", "nickname", "lat", "lon", "alt"]
    updates = {k: payload.get(k) for k in allowed if k in payload}
    if not updates:
        return JSONResponse({"error": "no fields"}, status_code=400)
    set_clause = ", ".join(f"{k}=?" for k in updates)
    params = list(updates.values()) + [node_id]
    with DB_LOCK:
        DB.execute(f"UPDATE nodes SET {set_clause} WHERE node_id=?", params)
        DB.commit()
    return JSONResponse({"status": "ok"})


@app.delete("/api/admin/nodes/empty")
def api_admin_delete_empty_nodes():
    with DB_LOCK:
        before = DB.total_changes
        DB.execute(
            """
            DELETE FROM nodes
            WHERE COALESCE(TRIM(short_name), '') = ''
              AND COALESCE(TRIM(long_name), '') = ''
              AND COALESCE(TRIM(nickname), '') = ''
              AND (lat IS NULL OR lat = 0)
              AND (lon IS NULL OR lon = 0)
            """,
        )
        DB.commit()
        deleted = DB.total_changes - before
    return JSONResponse({"deleted": deleted})


@app.delete("/api/admin/nodes/{node_id}")
def api_admin_delete_node(node_id: str):
    with DB_LOCK:
        DB.execute("DELETE FROM nodes WHERE node_id=?", (node_id,))
        DB.commit()
    return JSONResponse({"status": "ok"})

@app.post("/api/admin/sql")
def api_admin_sql(payload: Dict[str, Any] = Body(...)):
    query = payload.get("query")
    params = payload.get("params") or []
    if not query:
        return JSONResponse({"error": "query required"}, status_code=400)
    with DB_LOCK:
        cur = DB.execute(query, params)
        if query.strip().lower().startswith("select"):
            cols = [c[0] for c in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            return JSONResponse({"rows": rows})
        DB.commit()
    return JSONResponse({"status": "ok"})



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
