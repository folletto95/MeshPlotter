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
