import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from config import PROTOBUF_DECODE, TRACEROUTE_TTL
from database import DB, DB_LOCK, upsert_node, store_metric

if PROTOBUF_DECODE:
    from google.protobuf.json_format import MessageToDict
    from meshtastic import telemetry_pb2, mesh_pb2, portnums_pb2
    HAVE_MESHTASTIC = True
else:
    HAVE_MESHTASTIC = False

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

        def _clean(val: Optional[str]) -> Optional[str]:
            if val is None:
                return None
            val = str(val).strip()
            return val or None

        return (
            nid,
            _clean(u.get("shortName") or u.get("short_name")),
            _clean(u.get("longName") or u.get("LongName") or u.get("long_name")),
        )

    # 1. blocco "user" (come prima)
    for cand in (
        d,
        d.get("payload"),
        d.get("decoded"),
        (d.get("decoded") or {}).get("payload"),
    ):
        if isinstance(cand, dict) and isinstance(cand.get("user"), dict):
            return _from_user(cand["user"])

    # 2. pacchetti "nodeinfo": nomi nel payload
    p = d.get("payload")
    if isinstance(p, dict):
        sn = p.get("shortName") or p.get("shortname") or p.get("short_name")
        ln = p.get("longName") or p.get("longname") or p.get("long_name")
        # Se almeno uno dei due è presente, determinare l'ID nodo
        if sn or ln:
            # priorità: payload.id -> fromId/from -> sender -> node
            nid = _norm_node_id(
                p.get("id")
                or d.get("fromId")
                or d.get("from")
                or d.get("sender")
                or d.get("node")
            )

            def _clean(val: Any) -> Optional[str]:
                if val is None:
                    return None
                s = str(val).strip()
                return s or None

            return (
                nid,
                _clean(sn),
                _clean(ln),
            )

    # 3. fallback: cerca chiavi "shortname"/"longname" ovunque nel messaggio
    short_n: Optional[str] = None
    long_n: Optional[str] = None

    def _search(obj: Any) -> None:
        nonlocal short_n, long_n
        if isinstance(obj, dict):
            for k, v in obj.items():
                kl = k.lower()
                if kl in ("shortname", "short_name") and not short_n:
                    s = str(v).strip()
                    if s:
                        short_n = s
                elif kl in ("longname", "long_name") and not long_n:
                    s = str(v).strip()
                    if s:
                        long_n = s
                _search(v)
        elif isinstance(obj, list):
            for v in obj:
                _search(v)

    _search(d)
    if short_n or long_n:
        # non sappiamo l'ID del nodo da qui; _parse_node_id penserà a ricavarlo
        return None, short_n, long_n

    # Niente nomi trovati
    return None, None, None


def _extract_position(d: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """Look for latitude/longitude/altitude in the message."""

    def _search(obj: Any):
        if isinstance(obj, dict):
            lat = obj.get("latitude") or obj.get("lat")
            lon = obj.get("longitude") or obj.get("lon") or obj.get("lng")
            if lat is None and obj.get("latitude_i") is not None:
                try:
                    lat = float(obj.get("latitude_i")) / 1e7
                except (TypeError, ValueError):
                    lat = None
            if lon is None and obj.get("longitude_i") is not None:
                try:
                    lon = float(obj.get("longitude_i")) / 1e7
                except (TypeError, ValueError):
                    lon = None
            if lat is not None and lon is not None:
                alt = obj.get("altitude") or obj.get("alt") or obj.get("altitude_m")
                if alt is None and obj.get("altitude_i") is not None:
                    alt = float(obj.get("altitude_i"))
                try:
                    lat_f = float(lat)
                    lon_f = float(lon)
                    if lat_f == 0 and lon_f == 0:
                        raise ValueError
                    alt_f = float(alt) if alt is not None else None
                    return lat_f, lon_f, alt_f
                except (TypeError, ValueError):
                    pass
            for v in obj.values():
                res = _search(v)
                if res:
                    return res
        elif isinstance(obj, list):
            for v in obj:
                res = _search(v)
                if res:
                    return res
        return None

    res = _search(d)
    if res:
        return res
    return None, None, None


def _parse_node_id(d: Dict[str, Any], topic: str) -> Optional[str]:
    """Try to locate a node identifier in the message or topic."""

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
        if n and re.fullmatch(r"[0-9a-fA-F]+", n):
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
_RE_ENV = re.compile(
    r'(?:^|\.)(environment_?metrics)\.'
    r'(temperature|relative_humidity|relativehumidity|humidity|'
    r'barometric_pressure|barometricpressure|pressure)\b'
)
_RE_DEV = re.compile(r'(?:^|\.)(device_?metrics)\.(voltage)\b')
_RE_PWR = re.compile(r'(?:^|\.)(power_?metrics)\.(bus_voltage|shunt_voltage|current|current_ma|current_a)\b')
_RE_PWR_CH = re.compile(r'(?:^|\.)(ch\d+_(?:voltage|current|current_ma|current_a))\b')
_RE_GENERIC = re.compile(
    r'(?:^|\.)(temp(?:erature)?|hum(?:idity)?|relativehumidity|'
    r'press(?:ure)?|barometricpressure|volt(?:age)?|current(?:_ma|_a)?)\b',
    re.I,
)


def _normalize_metric(k: str, v: float) -> Optional[Tuple[str, float]]:
    k_low = k.lower()
    # Official telemetry docs define `barometricPressure` in EnvironmentMetrics
    # (https://meshtastic.org/docs/developers/protobufs/telemetry). Handle it
    # explicitly even if the prefix is missing.
    if "barometricpressure" in k_low or "barometric_pressure" in k_low:
        return ("pressure", v)
    m = _RE_ENV.search(k_low)
    if m:
        f = m.group(2)
        if f == "temperature":
            return ("temperature", v)
        if f in ("relative_humidity", "relativehumidity", "humidity"):
            return ("humidity", v)
        if f in ("barometric_pressure", "barometricpressure", "pressure"):
            return ("pressure", v)
    m = _RE_DEV.search(k_low)
    if m:
        return ("voltage", v)
    m = _RE_PWR.search(k_low)
    if m:
        f = m.group(2)
        if f in ("bus_voltage", "shunt_voltage"):
            return ("voltage", v)
        if f in ("current", "current_a"):
            return ("current", v)
        if f == "current_ma":
            return ("current", v)
    m = _RE_PWR_CH.search(k_low)
    if m:
        raw = m.group(1)
        if raw.endswith("_voltage"):
            return (raw, v)
        if raw.endswith("_current_ma"):
            return (raw.replace("_current_ma", "_current"), v)
        if raw.endswith("_current_a"):
            return (raw.replace("_current_a", "_current"), v * 1000)
        if raw.endswith("_current"):
            return (raw, v)
    if "config." in k_low or "prefs." in k_low:
        return None
    if _RE_GENERIC.search(k_low):
        if "temp" in k_low:
            return ("temperature", v)
        if "hum" in k_low:
            return ("humidity", v)
        if "press" in k_low:
            return ("pressure", v)
        if "volt" in k_low:
            return ("voltage", v)
        if "current_ma" in k_low:
            return ("current", v)
        if "current" in k_low:
            return ("current", v)
    return None


def normalize_flat(flat: Dict[str, float]) -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in flat.items():
        t = _normalize_metric(k, v)
        if t:
            out[t[0]] = t[1]
    return out


# ---------- Protobuf ----------
def pb_to_dict(msg) -> Dict[str, Any]:
    return MessageToDict(msg, preserving_proto_field_name=True)


def try_decode_protobuf(payload: bytes, *, portnum: Optional[int] = None, _nested: bool = False) -> Optional[Dict[str, Any]]:
    """Best‑effort decoding of Meshtastic protobuf payloads."""

    if not HAVE_MESHTASTIC:
        return None

    # Full MeshPacket (contains portnum + decoded payload)
    if not _nested:
        try:
            pkt = mesh_pb2.MeshPacket()
            pkt.ParseFromString(payload)
            if len(pkt.ListFields()) > 0:
                inner: Optional[Dict[str, Any]] = None
                try:
                    if pkt.decoded and pkt.decoded.payload:
                        inner = try_decode_protobuf(
                            pkt.decoded.payload, portnum=pkt.decoded.portnum, _nested=True
                        )
                except Exception:
                    inner = None
                pkt_dict = pb_to_dict(pkt)
                if inner:
                    pkt_dict.setdefault("decoded", {})["payload"] = inner
                return pkt_dict
        except Exception:
            pass

    if portnum == getattr(portnums_pb2.PortNum, "TRACEROUTE_APP", None):
        try:
            rd = mesh_pb2.RouteDiscovery()
            rd.ParseFromString(payload)
            if len(rd.ListFields()) > 0:
                return pb_to_dict(rd)
        except Exception:
            pass

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

    # Position (lat/lon)
    try:
        p = mesh_pb2.Position()
        p.ParseFromString(payload)
        if len(p.ListFields()) > 0:
            return {"position": pb_to_dict(p)}
    except Exception:
        pass
    return None


def _decode_message(payload: bytes) -> Optional[Dict[str, Any]]:
    """Try to decode a MQTT payload into a dictionary."""

    data = _json_loads(payload)
    if not isinstance(data, dict) and PROTOBUF_DECODE and HAVE_MESHTASTIC:
        data = try_decode_protobuf(payload)
    return data if isinstance(data, dict) else None


def _extract_portnum(data: Dict[str, Any]) -> Optional[str]:
    """Retrieve the Meshtastic port number from a decoded message."""

    decoded = data.get("decoded") if isinstance(data.get("decoded"), dict) else None
    if decoded and isinstance(decoded.get("portnum"), str):
        return decoded.get("portnum")
    if isinstance(data.get("portnum"), str):
        return data.get("portnum")
    return None


def _process_node(data: Dict[str, Any], topic: str, now_s: int, portnum: Optional[str]) -> str:
    uid, sname, lname = _extract_user_info(data)
    topic_id = _parse_node_id(data, topic)
    node_id = uid or topic_id
    lat = lon = alt = None
    should_locate = False
    if portnum in {"POSITION_APP", "NODEINFO_APP", "WAYPOINT_APP"}:
        should_locate = True
    elif "position" in data or (
        isinstance(data.get("payload"), dict) and "position" in data["payload"]
    ):
        should_locate = True
    if should_locate:
        lat, lon, alt = _extract_position(data)
        if lat is not None and lon is not None:
            print(
                f"[DBG] Position for node {node_id or '(unknown)'}: lat={lat} lon={lon} alt={alt}"
            )
        else:
            print(
                f"[DBG] No position for node {node_id or '(unknown)'}; keys={list(data.keys())}"
            )
    has_info = bool(uid or sname or lname)
    if not node_id:
        node_id = "unknown"
        upsert_node(node_id, None, "Sconosciuto", now_s)
    else:
        upsert_node(
            node_id,
            sname,
            lname,
            now_s,
            info_packet=has_info,
            lat=lat,
            lon=lon,
            alt=alt,
        )
    return node_id


def _store_metrics(node_id: str, now_s: int, data: Dict[str, Any]) -> None:
    """Flatten metrics from a message and store them in the DB."""

    candidates: List[Dict[str, Any]] = []
    if isinstance(data.get("payload"), dict):
        candidates.append(data["payload"])
    for k in (
        "environment_metrics",
        "device_metrics",
        "power_metrics",
        "environmentMetrics",
        "deviceMetrics",
        "powerMetrics",
    ):
        if isinstance(data.get(k), dict):
            candidates.append(data[k])
    if not candidates:
        candidates.append(data)

    for d in candidates:
        flat_all = flatten_numeric(d)
        flat = normalize_flat(flat_all)
        if not flat:
            continue
        for metric, value in flat.items():
            store_metric(now_s, node_id, metric, value)


def _store_traceroute(node_id: str, now_s: int, data: Dict[str, Any]) -> None:
    """Persist traceroute information if present in the message."""
    decoded = data.get("decoded") if isinstance(data.get("decoded"), dict) else None
    payload: Optional[Dict[str, Any]] = None

    if decoded:
        portnum = decoded.get("portnum")
        if isinstance(portnum, int):
            if portnum != 70:  # TRACEROUTE_APP
                return
        elif portnum != "TRACEROUTE_APP":
            return
        payload = decoded.get("payload") if isinstance(decoded.get("payload"), dict) else {}

    if payload is None:
        cand = data.get("payload") if isinstance(data.get("payload"), dict) else data
        if not isinstance(cand.get("route"), list):
            return
        payload = cand

    route_vals = payload.get("route") or []
    route_hex = [r for r in (_norm_node_id(v) for v in route_vals) if r]
    if len(route_hex) < 2:
        return

    src = _norm_node_id(payload.get("from") or data.get("from")) or node_id
    dest = _norm_node_id(payload.get("to") or data.get("to"))
    hop_count = (
        payload.get("hop_count")
        or payload.get("hopCount")
        or max(len(route_hex) - 1, 0)
    )


    radio_info: Dict[str, Any] = {}
    for k in ("snr", "SNR", "rssi", "RSSI"):
        if k in payload:
            radio_info[k.lower()] = payload[k]
    if isinstance(payload.get("radio"), dict):
        for k, v in payload["radio"].items():
            radio_info[str(k)] = v
    radio_json = json.dumps(radio_info) if radio_info else None

    with DB_LOCK:
        DB.execute("DELETE FROM traceroutes WHERE src_id=? AND dest_id=?", (src, dest))
        if TRACEROUTE_TTL > 0:
            cutoff = now_s - TRACEROUTE_TTL
            DB.execute("DELETE FROM traceroutes WHERE ts < ?", (cutoff,))
        DB.execute(
            "INSERT INTO traceroutes(ts, src_id, dest_id, route, hop_count, radio) VALUES(?,?,?,?,?,?)",
            (now_s, src, dest, json.dumps(route_hex), hop_count, radio_json),
        )
        DB.commit()
        
        
def _store_message(
    node_id: str, now_s: int, data: Dict[str, Any], portnum: Optional[str]
) -> None:
    """Persist any incoming message for later inspection."""
    with DB_LOCK:
        DB.execute(
            "INSERT INTO messages(ts, node_id, portnum, raw_json) VALUES(?,?,?,?)",
            (now_s, node_id, portnum, json.dumps(data)),
        )
        DB.commit()

def process_mqtt_message(topic: str, payload: bytes) -> None:
    """Elabora un messaggio MQTT in formato JSON o Protobuf."""

    now_s = int(time.time())
    data = _decode_message(payload)
    if not data:
        return

    portnum = _extract_portnum(data)
    node_id = _process_node(data, topic, now_s, portnum)
    _store_metrics(node_id, now_s, data)
    _store_traceroute(node_id, now_s, data)
    _store_message(node_id, now_s, data, portnum)