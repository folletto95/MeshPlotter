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


def test_process_json_camelcase_humidity_pressure():
    """Ensure camelCase environment metrics are normalized correctly."""
    reset_db()
    msg = {
        'environment_metrics': {
            'relativeHumidity': 64.2,
            'barometricPressure': 1012.3,
        },
        'user': {'id': 'abcd'},
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/test', payload)
    with app.DB_LOCK:
        rows = app.DB.execute(
            'SELECT node_id, metric, value FROM telemetry ORDER BY metric'
        ).fetchall()
    assert rows == [
        ('abcd', 'humidity', 64.2),
        ('abcd', 'pressure', 1012.3),
    ]
