import os
import yaml
from typing import List

# ---------- CONFIG: SOLO config.yml ----------
CFG_PATH = os.getenv("TP_CONFIG", "config.yml")
if not os.path.isfile(CFG_PATH):
    raise SystemExit(f"config.yml non trovato: {os.path.abspath(CFG_PATH)}")

with open(CFG_PATH, "r", encoding="utf-8") as f:
    cfg = yaml.safe_load(f)


def _normalize_topics(raw) -> List[str]:
    """Normalizza i topic MQTT permettendo stringhe o liste."""
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
EMBEDDED_BROKER = bool(cfg["mqtt"].get("embedded_broker", False))

# Percorso SQLite relativo al file di config
_raw_db_path = cfg["storage"].get("sqlite_path")
if not _raw_db_path:
    raise SystemExit("[CFG] storage.sqlite_path mancante in config.yml")
if _raw_db_path == ":memory:":
    DB_PATH = _raw_db_path
else:
    cfg_dir = os.path.dirname(os.path.abspath(CFG_PATH))
    DB_PATH = os.path.abspath(os.path.join(cfg_dir, _raw_db_path))

WEB_HOST = cfg["web"].get("host", "0.0.0.0")
WEB_PORT = int(cfg["web"].get("port", 8080))
ALLOW_CORS = bool(cfg["web"].get("allow_cors", True))
# Rimuove automaticamente le tracce di traceroute più vecchie di 12 ore
# se non diversamente specificato nella configurazione.
TRACEROUTE_TTL = int(cfg["web"].get("traceroute_ttl", 12 * 3600))

# Diagnostica avvio (no password)
print(f"[CFG] Loaded: {os.path.abspath(CFG_PATH)}")
print(f"[CFG] MQTT host={MQTT_HOST} port={MQTT_PORT} client_id={MQTT_CLIENT_ID} proto={MQTT_PROTO}")
print(f"[CFG] Topics (raw type={type(cfg['mqtt'].get('topics')).__name__}): {cfg['mqtt'].get('topics')!r}")
print(f"[CFG] Topics (normalized): {MQTT_TOPICS}")
print(f"[CFG] SQLite DB: {DB_PATH}")
print(f"[CFG] Embedded broker: {EMBEDDED_BROKER}")

if not MQTT_HOST or not MQTT_PORT:
    raise SystemExit("[CFG] mqtt.host/port mancanti in config.yml")
if not MQTT_TOPICS:
    raise SystemExit("[CFG] mqtt.topics è vuoto. In config.yml usa: topics: \"#\" oppure una lista di topic.")

# --------- Protobuf decode ON di default ----------
PROTOBUF_DECODE = bool(cfg.get("protobuf_decode", True))
HAVE_MESHTASTIC = False
if PROTOBUF_DECODE:
    try:
        from google.protobuf.json_format import MessageToDict  # noqa: F401
        from meshtastic import telemetry_pb2, mesh_pb2, portnums_pb2  # noqa: F401
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
    "current": "mA",
    **{k: "V" for k in POWER_V_KEYS},
    **{k: "mA" for k in POWER_I_KEYS},
}
