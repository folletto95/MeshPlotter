import json, os, re, sqlite3, threading, time
from typing import Any, Dict, List, Optional, Tuple

import yaml
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse, HTMLResponse
try:
    from fastapi.middleware.cors import CORSMiddleware
    HAVE_CORS = True
except Exception:
    HAVE_CORS = False

from contextlib import asynccontextmanager
from paho.mqtt.client import Client as MQTTClient, CallbackAPIVersion, MQTTv311, MQTTv5
import ssl

# ---------- CONFIG: SOLO config.yml ----------
CFG_PATH = os.getenv("TP_CONFIG", "config.yml")
if not os.path.isfile(CFG_PATH):
    raise SystemExit(f"config.yml non trovato: {os.path.abspath(CFG_PATH)}")

with open(CFG_PATH, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)

def _normalize_topics(raw) -> List[str]:
    # Accetta stringa o lista; restituisce lista pulita
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        out = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []

# Sezioni richieste
if "mqtt" not in cfg or "storage" not in cfg or "web" not in cfg:
    raise SystemExit(f"config.yml mancante sezioni mqtt/storage/web. File: {os.path.abspath(CFG_PATH)}")

MQTT_HOST = cfg["mqtt"].get("host")
MQTT_PORT = int(cfg["mqtt"].get("port", 0))
MQTT_USER = cfg["mqtt"].get("username") or None
MQTT_PASS = cfg["mqtt"].get("password") or None
MQTT_CLIENT_ID = cfg["mqtt"].get("client_id", "telemetry-plotter")
MQTT_PROTO = (cfg["mqtt"].get("protocol", "v311") or "v311").lower()
MQTT_TOPICS = _normalize_topics(cfg["mqtt"].get("topics"))
TLS_CFG = cfg["mqtt"].get("tls") or {"enabled": False}

DB_PATH = cfg["storage"].get("sqlite_path")
WEB_HOST = cfg["web"].get("host", "0.0.0.0")
WEB_PORT = int(cfg["web"].get("port", 8080))
ALLOW_CORS = bool(cfg["web"].get("allow_cors", True))

# Diagnostica avvio (no password)
print(f"[CFG] Loaded: {os.path.abspath(CFG_PATH)}")
print(f"[CFG] MQTT host={MQTT_HOST} port={MQTT_PORT} client_id={MQTT_CLIENT_ID} proto={MQTT_PROTO}")
print(f"[CFG] Topics (raw type={type(cfg['mqtt'].get('topics')).__name__}): {cfg['mqtt'].get('topics')!r}")
print(f"[CFG] Topics (normalized): {MQTT_TOPICS}")

if not MQTT_HOST or not MQTT_PORT:
    raise SystemExit("[CFG] mqtt.host/port mancanti in config.yml")
if not MQTT_TOPICS:
    raise SystemExit("[CFG] mqtt.topics è vuoto. In config.yml usa: topics: \"#\" oppure una lista di topic.")

# --------- Protobuf decode ON di default ----------
PROTOBUF_DECODE = bool(cfg.get("protobuf_decode", True))
HAVE_MESHTASTIC = False
if PROTOBUF_DECODE:
    try:
        from google.protobuf.json_format import MessageToDict
        from meshtastic import telemetry_pb2, mesh_pb2
        HAVE_MESHTASTIC = True
    except Exception as e:
        raise SystemExit(
            "protobuf_decode=true ma mancano i pacchetti. Esegui:\n"
            "  pip install meshtastic protobuf\nDettagli: " + str(e)
        )

# ---------- Unità ----------
POWER_V_KEYS = [f"ch{i}_voltage" for i in range(1, 9)]
POWER_I_KEYS = [f"ch{i}_current" for i in range(1, 9)]
UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "pressure": "hPa",
    "voltage": "V",
    "current": "A",
    **{k: "V" for k in POWER_V_KEYS},
    **{k: "A" for k in POWER_I_KEYS},
}

# ---------- DB + migrazioni ----------
DB_LOCK = threading.Lock()
DB = sqlite3.connect(DB_PATH, check_same_thread=False)
DB.execute("PRAGMA journal_mode=WAL")
DB.execute("PRAGMA synchronous=NORMAL")

def _cols(table: str) -> List[str]:
    cur = DB.execute(f"PRAGMA table_info('{table}')")
    return [r[1] for r in cur.fetchall()]

def migrate():
    with DB_LOCK:
        # tabelle base
        DB.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts INTEGER,
              node_id TEXT,
              node_name TEXT,
              metric TEXT NOT NULL,
              value REAL NOT NULL,
              ts_ms INTEGER, topic TEXT, node TEXT, raw_json TEXT
            )
        """)
        DB.execute("""
            CREATE TABLE IF NOT EXISTS nodes (
              node_id TEXT PRIMARY KEY,
              short_name TEXT,
              long_name TEXT,
              last_seen INTEGER
            )
        """)

        # colonne telemetry
        tcols = _cols("telemetry")
        if "ts" not in tcols: DB.execute("ALTER TABLE telemetry ADD COLUMN ts INTEGER")
        if "ts_ms" in tcols:  DB.execute("UPDATE telemetry SET ts = COALESCE(ts, ts_ms/1000)")
        if "node_id" not in tcols: DB.execute("ALTER TABLE telemetry ADD COLUMN node_id TEXT")
        if "node" in tcols:      DB.execute("UPDATE telemetry SET node_id = COALESCE(node_id, node)")
        if "node_name" not in tcols: DB.execute("ALTER TABLE telemetry ADD COLUMN node_name TEXT")
        DB.execute("UPDATE telemetry SET metric='humidity' WHERE metric='relative_humidity'")
        DB.execute("UPDATE telemetry SET metric='pressure'  WHERE metric='barometric_pressure'")

        # colonne nodes (aggiungi se mancano)
        ncols = _cols("nodes")
        if "short_name" not in ncols: DB.execute("ALTER TABLE nodes ADD COLUMN short_name TEXT")
        if "long_name"  not in ncols: DB.execute("ALTER TABLE nodes ADD COLUMN long_name TEXT")
        if "last_seen"  not in ncols: DB.execute("ALTER TABLE nodes ADD COLUMN last_seen INTEGER")
        DB.execute("UPDATE nodes SET last_seen = 0 WHERE last_seen IS NULL")

        # indici
        DB.execute("CREATE INDEX IF NOT EXISTS idx_telem_ts ON telemetry(ts)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_telem_nodeid ON telemetry(node_id)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_telem_metric ON telemetry(metric)")
        DB.execute("CREATE INDEX IF NOT EXISTS idx_nodes_name ON nodes(COALESCE(long_name, short_name))")
        DB.commit()
migrate()

def upsert_node(node_id: Optional[str], short_name: Optional[str], long_name: Optional[str], ts: int):
    if not node_id and not (short_name or long_name): return
    with DB_LOCK:
        DB.execute("""
          INSERT INTO nodes(node_id, short_name, long_name, last_seen)
          VALUES(?, ?, ?, ?)
          ON CONFLICT(node_id) DO UPDATE SET
            short_name = COALESCE(excluded.short_name, nodes.short_name),
            long_name  = COALESCE(excluded.long_name, nodes.long_name),
            last_seen  = MAX(nodes.last_seen, excluded.last_seen)
        """, (node_id, short_name, long_name, ts))
        name_to_set = long_name or short_name
        if node_id and name_to_set:
            DB.execute("""
              UPDATE telemetry SET node_name = ?
              WHERE node_id = ? AND (node_name IS NULL OR node_name = '')
            """, (name_to_set, node_id))
        DB.commit()

def store_metric(ts: int, node_id: str, metric: str, value: float):
    with DB_LOCK:
        cur = DB.execute("SELECT long_name, short_name FROM nodes WHERE node_id=?", (node_id,))
        row = cur.fetchone()
        node_name = (row[0] or row[1]) if row else None
        DB.execute(
            "INSERT INTO telemetry(ts, node_id, node_name, metric, value) VALUES(?,?,?,?,?)",
            (ts, node_id, node_name, metric, float(value))
        )
        DB.commit()

# ---------- parsing helpers ----------
def _json_loads(b: bytes) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(b.decode("utf-8"))
    except Exception:
        return None

def _find_user_blocks(obj: Any) -> List[Dict[str, Any]]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "user" and isinstance(v, dict):
                out.append(v)
            else:
                out.extend(_find_user_blocks(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(_find_user_blocks(v))
    return out

def _norm_node_id(val: Any) -> Optional[str]:
    """Normalize numeric/hex node IDs to a consistent lowercase hex string."""
    if val is None:
        return None
    s = str(val).lstrip("!")
    if s.isdigit():
        return format(int(s), "x")
    try:
        int(s, 16)
        return s.lower()
    except ValueError:
        return s or None

def _extract_user_info(d: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract node_id, short and long names from a decoded message dict."""

    def _from_user(u: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        nid = _norm_node_id(u.get("id"))
        return (
            nid,
            u.get("shortName") or u.get("short_name"),
            u.get("longName") or u.get("LongName") or u.get("long_name"),
        )

    for cand in (
        d,
        d.get("payload"),
        d.get("decoded"),
        (d.get("decoded") or {}).get("payload"),
    ):
        if isinstance(cand, dict) and isinstance(cand.get("user"), dict):
            return _from_user(cand["user"])

    blocks = _find_user_blocks(d)
    if blocks:
        return _from_user(blocks[0])
    return None, None, None

def _parse_node_id(d: Dict[str, Any], topic: str) -> Optional[str]:
    """Try to locate a node identifier in the message or topic.

    Meshtastic packets may expose the originating node in various places:
    ``fromId`` is the canonical user identifier while older firmwares use
    ``from`` or ``id``.  Some integrations nest these fields under other
    objects.  To make telemetry storage reliable we recursively walk the
    message looking for the first usable value and normalise it to a lowercase
    hexadecimal string.
    """

    def _find(obj: Any) -> Optional[str]:
        if isinstance(obj, dict):
            for key in ("fromId", "from", "sender", "node", "id"):
                if key in obj:
                    n = _norm_node_id(obj[key])
                    if n:
                        return n
            for v in obj.values():
                n = _find(v)
                if n:
                    return n
        elif isinstance(obj, list):
            for v in obj:
                n = _find(v)
                if n:
                    return n
        return None

    n = _find(d)
    if n:
        return n
    for p in topic.split("/"):
        n = _norm_node_id(p)
        if n and re.fullmatch(r"[0-9a-fA-F]{6,}", n):
            return n
    return None

def flatten_numeric(d: Any, prefix: str = "") -> Dict[str, float]:
    out: Dict[str, float] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            out.update(flatten_numeric(v, key))
    elif isinstance(d, list):
        for i, v in enumerate(d):
            key = f"{prefix}[{i}]"
            out.update(flatten_numeric(v, key))
    else:
        if isinstance(d, (int, float)) and not isinstance(d, bool):
            out[prefix] = float(d)
    return out

# --- normalizzazione etichette (telemetria pulita) ---
_RE_ENV = re.compile(r'(?:^|\.)(environment_metrics)\.(temperature|relative_humidity|humidity|barometric_pressure|pressure)\b')
_RE_DEV = re.compile(r'(?:^|\.)(device_metrics)\.(voltage)\b')
_RE_PWR = re.compile(r'(?:^|\.)(power_metrics)\.(bus_voltage|shunt_voltage|current|current_ma|current_a)\b')
_RE_GENERIC = re.compile(r'(?:^|\.)(temp(?:erature)?|hum(?:idity)?|press(?:ure)?|volt(?:age)?|current(?:_ma|_a)?)\b', re.I)

def _normalize_metric(k: str, v: float) -> Optional[Tuple[str, float]]:
    k_low = k.lower()
    m = _RE_ENV.search(k_low)
    if m:
        f = m.group(2)
        if f == "temperature": return ("temperature", v)
        if f in ("relative_humidity", "humidity"): return ("humidity", v)
        if f in ("barometric_pressure", "pressure"): return ("pressure", v)
    m = _RE_DEV.search(k_low)
    if m: return ("voltage", v)
    m = _RE_PWR.search(k_low)
    if m:
        f = m.group(2)
        if f in ("bus_voltage", "shunt_voltage"): return ("voltage", v)
        if f in ("current", "current_a"): return ("current", v)
        if f == "current_ma": return ("current", v/1000.0)
    if "config." in k_low or "prefs." in k_low: return None
    if _RE_GENERIC.search(k_low):
        if "temp" in k_low: return ("temperature", v)
        if "hum" in k_low: return ("humidity", v)
        if "press" in k_low: return ("pressure", v)
        if "volt" in k_low: return ("voltage", v)
        if "current_ma" in k_low: return ("current", v/1000.0)
        if "current" in k_low: return ("current", v)
    return None

def normalize_flat(flat: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in flat.items():
        t = _normalize_metric(k, v)
        if t: out[t[0]] = t[1]
    return out

# ---------- Protobuf ----------
def pb_to_dict(msg) -> Dict[str, Any]:
    return MessageToDict(msg, preserving_proto_field_name=True)

def try_decode_protobuf(payload: bytes) -> Optional[Dict[str, Any]]:
    # Telemetry
    try:
        t = telemetry_pb2.Telemetry()
        t.ParseFromString(payload)
        if len(t.ListFields()) > 0:
            return pb_to_dict(t)
    except Exception:
        pass
    # User (per nomi)
    try:
        u = mesh_pb2.User()
        u.ParseFromString(payload)
        if len(u.ListFields()) > 0:
            return {"user": pb_to_dict(u)}
    except Exception:
        pass
    return None

# ---------- MQTT (una sola istanza via lifespan) ----------
def start_mqtt():
    proto = MQTTv311 if MQTT_PROTO == "v311" else MQTTv5
    client = MQTTClient(callback_api_version=CallbackAPIVersion.VERSION2,
                        client_id=MQTT_CLIENT_ID, clean_session=True, protocol=proto)
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    if TLS_CFG.get("enabled"):
        client.tls_set(
            ca_certs=TLS_CFG.get("ca_certs") or None,
            certfile=TLS_CFG.get("certfile") or None,
            keyfile=TLS_CFG.get("keyfile") or None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT
        )
        if TLS_CFG.get("insecure"):
            client.tls_insecure_set(True)

    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        ok = (getattr(reason_code, "value", reason_code) == 0)
        if ok:
            print(f"[MQTT] Connected OK to {MQTT_HOST}:{MQTT_PORT}")
            for t in MQTT_TOPICS:
                try:
                    client.subscribe(t, qos=0)
                    print(f"[MQTT] Subscribed: {t}")
                except Exception as e:
                    print(f"[MQTT] Subscribe error on {t}: {e}")
        else:
            print(f"[MQTT] Connect failed rc={reason_code}. Ritento...")

    def on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
        print(f"[MQTT] Disconnected rc={reason_code}. Retry automatico attivo.")

    def on_message(client, userdata, msg):
        now_s = int(time.time())
        # Prova JSON, poi Protobuf se abilitato
        data = _json_loads(msg.payload)
        if not isinstance(data, dict) and PROTOBUF_DECODE and HAVE_MESHTASTIC:
            data = try_decode_protobuf(msg.payload)
        if not isinstance(data, dict):
            return

        uid, sname, lname = _extract_user_info(data)
        node_id = uid or _parse_node_id(data, msg.topic)
        if not node_id:
            return

        if sname or lname:
            upsert_node(node_id, sname, lname, now_s)

        # blocchi con metriche
        candidates: List[Dict[str, Any]] = []
        if "payload" in data and isinstance(data["payload"], dict):
            candidates.append(data["payload"])
        if any(k in data for k in ("environment_metrics", "device_metrics", "power_metrics")):
            candidates.append(data)
        if not candidates:
            candidates.append(data)

        for d in candidates:
            flat_all = flatten_numeric(d)
            flat = normalize_flat(flat_all)
            if not flat:
                continue
            for metric, value in flat.items():
                store_metric(now_s, node_id, metric, value)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client

# ---------- FastAPI app (lifespan) ----------
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

# ----------- UI EMBEDDED -----------
INDEX_HTML = """<!doctype html>
<html lang="it"><head>
<meta charset="utf-8"/><title>Meshtastic Telemetry</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3"></script>
<style>
:root{--bd:#e5e7eb}
body{font-family:system-ui,Segoe UI,Roboto,Ubuntu,sans-serif;margin:16px}
header{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
select,button{padding:6px}
select{min-width:260px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px;margin-top:12px}
.card{border:1px solid var(--bd);border-radius:12px;padding:12px}
canvas{width:100%;height:320px}
small{color:#666}
</style>
</head>
<body>
<header>
  <h2 style="margin:0">Meshtastic Telemetry</h2>
  <label>
    <small>Nodi (Long/Short/ID)</small><br/>
    <select id="nodes" multiple size="5"></select>
  </label>
  <label>
    <small>Intervallo</small><br/>
    <select id="range">
      <option value="3600">Ultima ora</option>
      <option value="21600">Ultime 6 ore</option>
      <option value="86400" selected>Ultime 24 ore</option>
      <option value="604800">Ultimi 7 giorni</option>
    </select>
  </label>
  <button id="refresh">Aggiorna</button>
  <label style="margin-left:auto">
    <input type="checkbox" id="autoref"/> Auto-refresh (15s)
  </label>
</header>

<div class="grid">
  <div class="card"><h3 style="margin:0 0 8px">Temperatura</h3><canvas id="chart-temp"></canvas></div>
  <div class="card"><h3 style="margin:0 0 8px">Umidità</h3><canvas id="chart-hum"></canvas></div>
  <div class="card"><h3 style="margin:0 0 8px">Pressione</h3><canvas id="chart-press"></canvas></div>
  <div class="card"><h3 style="margin:0 0 8px">Tensione</h3><canvas id="chart-volt"></canvas></div>
  <div class="card"><h3 style="margin:0 0 8px">Corrente</h3><canvas id="chart-curr"></canvas></div>
</div>

<script>
const $nodes = document.getElementById('nodes');
const $range = document.getElementById('range');
const $refresh = document.getElementById('refresh');
const $autoref = document.getElementById('autoref');

function fmtTs(ms){ return new Date(ms).toLocaleString(); }

function mkChart(ctx, yLabel){
  return new Chart(ctx, {
    type: 'line',
    data: { datasets: [] },
    options: {
      responsive: true, parsing: false, animation: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: { position: 'bottom' },
        tooltip: {
          callbacks: {
            title: items => fmtTs(items[0].raw[0]),
            label: item => `${item.dataset.label}: ${item.raw[1]}`
          }
        }
      },
      scales: { x: { type:'time', time:{ unit:'minute' } }, y: { title: { display:true, text:yLabel } } }
    }
  });
}
const charts = {
  temperature: mkChart(document.getElementById('chart-temp'), '°C'),
  humidity:    mkChart(document.getElementById('chart-hum'), '%'),
  pressure:    mkChart(document.getElementById('chart-press'), 'hPa'),
  voltage:     mkChart(document.getElementById('chart-volt'), 'V'),
  current:     mkChart(document.getElementById('chart-curr'), 'A')
};

async function loadNodes(){
  const res = await fetch('/api/nodes');
  const nodes = await res.json();
  $nodes.innerHTML = '';
  for (const n of nodes){
    const opt = document.createElement('option');
    opt.value = n.node_id;
    const disp = n.display_name || n.long_name || n.short_name || n.node_id;
    let label = disp;
    if (n.short_name && n.short_name !== n.long_name) label += ` (${n.short_name})`;
    label += ` [${n.node_id}]`;
    opt.textContent = label;
    $nodes.appendChild(opt);
  }
}

async function loadData(){
  const names = Array.from($nodes.selectedOptions).map(o => o.value).join(',');
  const since = $range.value;
  const url = new URL('/api/metrics', location.origin);
  if (names) url.searchParams.set('nodes', names);
  url.searchParams.set('since_s', since);
  const res = await fetch(url);
  const data = await res.json();
  const series = data.series || {};
  for (const fam of Object.keys(charts)){
    const ds = (series[fam] || []).map(s => ({ label: s.label, data: s.data }));
    charts[fam].data.datasets = ds;
    charts[fam].update();
  }
}

$refresh.onclick = loadData;
$autoref.onchange = () => {
  if ($autoref.checked){ loadData(); window._timer = setInterval(loadData, 15000); }
  else { clearInterval(window._timer); }
};

(async function init(){ await loadNodes(); await loadData(); })();
</script>
</body></html>
"""

@app.get("/", response_class=HTMLResponse)
def ui():
    return HTMLResponse(INDEX_HTML)

# --------- API ----------
@app.get("/api/nodes")
def api_nodes():
    with DB_LOCK:
        DB.row_factory = sqlite3.Row
        cur = DB.execute("""
            SELECT node_id, short_name, long_name, last_seen
            FROM nodes ORDER BY COALESCE(long_name, short_name, node_id)
        """)
        rows = cur.fetchall()
    out = []
    for r in rows:
        disp = r["long_name"] or r["short_name"] or r["node_id"]
        out.append({"node_id": r["node_id"], "short_name": r["short_name"],
                    "long_name": r["long_name"], "display_name": disp, "last_seen": r["last_seen"]})
    return JSONResponse(out)

def _resolve_ids(names: List[str]) -> List[str]:
    if not names: return []
    qs = ",".join("?" for _ in names)
    with DB_LOCK:
        cur = DB.execute(f"""
            SELECT node_id FROM nodes
            WHERE COALESCE(long_name, short_name, node_id) IN ({qs})
        """, (*names,))
        ids = [r[0] for r in cur.fetchall()]
    for n in names:
        if n not in ids:
            ids.append(n)  # consenti passare direttamente node_id
    return list(dict.fromkeys(ids))

@app.get("/api/metrics")
def api_metrics(
    nodes: Optional[str] = Query(default=None, description="Nomi visuali o node_id separati da virgola"),
    since_s: int = Query(default=24*3600, ge=0, le=30*24*3600),
):
    since_ts = int(time.time()) - since_s
    selected = [s.strip() for s in (nodes.split(",") if nodes else []) if s.strip()]
    ids = _resolve_ids(selected) if selected else []

    with DB_LOCK:
        DB.row_factory = sqlite3.Row
        if ids:
            qs = ",".join("?" for _ in ids)
            cur = DB.execute(f"""
                SELECT
                    telemetry.ts            AS ts,
                    telemetry.node_id       AS node_id,
                    COALESCE(telemetry.node_name, nodes.long_name, nodes.short_name, telemetry.node_id) AS disp,
                    telemetry.metric        AS metric,
                    telemetry.value         AS value
                FROM telemetry
                LEFT JOIN nodes ON nodes.node_id = telemetry.node_id
                WHERE telemetry.ts >= ? AND telemetry.node_id IN ({qs})
                ORDER BY telemetry.ts ASC
            """, (since_ts, *ids))
        else:
            cur = DB.execute("""
                SELECT
                    telemetry.ts            AS ts,
                    telemetry.node_id       AS node_id,
                    COALESCE(telemetry.node_name, nodes.long_name, nodes.short_name, telemetry.node_id) AS disp,
                    telemetry.metric        AS metric,
                    telemetry.value         AS value
                FROM telemetry
                LEFT JOIN nodes ON nodes.node_id = telemetry.node_id
                WHERE telemetry.ts >= ?
                ORDER BY telemetry.ts ASC
            """, (since_ts,))
        rows = cur.fetchall()

    fams = {"temperature": [], "humidity": [], "pressure": [], "voltage": [], "current": []}
    acc: Dict[Tuple[str, str], List[List[float]]] = {}

    def add(fam: str, label: str, ts: int, val: float):
        acc.setdefault((fam, label), []).append([ts * 1000, float(val)])

    for r in rows:
        ts, disp, met, val = int(r["ts"]), r["disp"], r["metric"], float(r["value"])
        if met == "temperature":
            add("temperature", f"{disp} — Temperatura ({UNITS['temperature']})", ts, val)
        elif met == "humidity":
            add("humidity", f"{disp} — Umidità ({UNITS['humidity']})", ts, val)
        elif met == "pressure":
            add("pressure", f"{disp} — Pressione ({UNITS['pressure']})", ts, val)
        elif met == "voltage":
            add("voltage", f"{disp} — Tensione ({UNITS['voltage']})", ts, val)
        elif met == "current":
            add("current", f"{disp} — Corrente ({UNITS['current']})", ts, val)
        elif met in POWER_V_KEYS:
            ch = met.replace("ch", "").replace("_voltage", "")
            add("voltage", f"{disp} — Tensione ch{ch} (V)", ts, val)
        elif met in POWER_I_KEYS:
            ch = met.replace("ch", "").replace("_current", "")
            add("current", f"{disp} — Corrente ch{ch} (A)", ts, val)

    out = {k: [] for k in fams}
    for (fam, label), pts in acc.items():
        out[fam].append({"label": label, "data": pts})
    return JSONResponse({"units": UNITS, "series": out})

# ---------- avvio ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="info")
