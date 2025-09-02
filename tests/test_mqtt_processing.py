import os
import importlib
import json

# Config per l'app: puntiamo al file di test
os.environ['TP_CONFIG'] = os.path.join(os.path.dirname(__file__), 'test.config.yml')

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app  # noqa: E402

# Garantiamo che l'app utilizzi la nuova configurazione
importlib.reload(app)


def reset_db():
    with app.DB_LOCK:
        app.DB.execute('DELETE FROM telemetry')
        app.DB.execute('DELETE FROM nodes')
        app.DB.execute('DELETE FROM traceroutes')
        app.DB.commit()


def test_process_json_message():
    reset_db()
    msg = {
        'environment_metrics': {'temperature': 23.5},
        'user': {'id': 'abcd'}
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/test', payload)
    with app.DB_LOCK:
        rows = app.DB.execute('SELECT node_id, metric, value FROM telemetry').fetchall()
    assert rows == [('abcd', 'temperature', 23.5)]


def test_process_json_camelcase_env():
    """Support camelCase environmentMetrics keys for humidity/pressure."""
    reset_db()
    msg = {
        'environmentMetrics': {
            'relativeHumidity': 40.5,
            'barometricPressure': 1001.1,
        },
        'user': {'id': 'abcd'},
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/test', payload)
    with app.DB_LOCK:
        rows = sorted(app.DB.execute('SELECT metric, value FROM telemetry').fetchall())
    assert rows == [('humidity', 40.5), ('pressure', 1001.1)]


def test_process_proto_message():
    reset_db()
    from meshtastic import telemetry_pb2

    t = telemetry_pb2.Telemetry()
    t.environment_metrics.temperature = 31.5
    payload = t.SerializeToString()
    app.process_mqtt_message('msh/abcdef/telemetry', payload)
    with app.DB_LOCK:
        rows = app.DB.execute('SELECT node_id, metric, value FROM telemetry').fetchall()
    assert rows == [('abcdef', 'temperature', 31.5)]


def test_process_meshpacket_message():
    """Ensure that we can decode a full MeshPacket with nested telemetry."""
    reset_db()
    from meshtastic import telemetry_pb2, mesh_pb2, portnums_pb2

    telem = telemetry_pb2.Telemetry()
    telem.environment_metrics.temperature = 29.0

    pkt = mesh_pb2.MeshPacket()
    setattr(pkt, 'from', int('a1b2c3', 16))
    pkt.decoded.portnum = portnums_pb2.PortNum.TELEMETRY_APP
    pkt.decoded.payload = telem.SerializeToString()

    payload = pkt.SerializeToString()
    app.process_mqtt_message('msh/a1b2c3/telemetry', payload)
    with app.DB_LOCK:
        rows = app.DB.execute('SELECT node_id, metric, value FROM telemetry').fetchall()
    assert rows == [('a1b2c3', 'temperature', 29.0)]

    
def test_position_extraction_float():
    """Ensure latitude/longitude fields are stored for JSON payloads."""
    reset_db()
    msg = {
        'user': {'id': 'posfloat'},
        'position': {'latitude': 45.123456, 'longitude': 7.987654, 'altitude': 100.5},
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/posfloat/telemetry', payload)
    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT lat, lon, alt FROM nodes WHERE node_id=?', ('posfloat',)
        ).fetchone()
    assert row == (45.123456, 7.987654, 100.5)


def test_position_extraction_int_fields():
    """Ensure latitude_i/longitude_i fields are converted to floats."""
    reset_db()
    msg = {
        'user': {'id': 'posint'},
        'position': {
            'latitude_i': int(45.123456 * 1e7),
            'longitude_i': int(7.987654 * 1e7),
            'altitude': 42,
        },
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/posint/telemetry', payload)
    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT lat, lon, alt FROM nodes WHERE node_id=?', ('posint',)
        ).fetchone()
    assert round(row[0], 6) == 45.123456
    assert round(row[1], 6) == 7.987654
    assert row[2] == 42.0


def test_process_traceroute_packet():
    reset_db()
    from meshtastic import mesh_pb2, portnums_pb2

    rd = mesh_pb2.RouteDiscovery(route=[int('ff01', 16), int('a1b2', 16)])
    pkt = mesh_pb2.MeshPacket()
    setattr(pkt, 'from', int('ff01', 16))
    setattr(pkt, 'to', int('a1b2', 16))
    pkt.decoded.portnum = portnums_pb2.PortNum.TRACEROUTE_APP
    pkt.decoded.payload = rd.SerializeToString()

    app.process_mqtt_message('msh/ff01/traceroute', pkt.SerializeToString())
    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT src_id, dest_id, hop_count, route FROM traceroutes'
        ).fetchone()
    assert row[0] == 'ff01'
    assert row[1] == 'a1b2'
    assert row[2] == 1
    assert json.loads(row[3]) == ['ff01', 'a1b2']

