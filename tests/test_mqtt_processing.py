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
        app.DB.execute('DELETE FROM messages')
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


def test_process_power_metrics_channels():
    reset_db()
    msg = {
        'power_metrics': {
            'ch1_voltage': 1.1,
            'ch2_voltage': 2.2,
            'ch3_voltage': 3.3,
            'ch1_current': 10.0,
            'ch2_current': 20.0,
            'ch3_current': 30.0,
        },
        'user': {'id': 'abcd'}
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/test', payload)
    with app.DB_LOCK:
        rows = sorted(app.DB.execute('SELECT metric, value FROM telemetry').fetchall())
    assert ('ch1_voltage', 1.1) in rows
    assert ('ch2_voltage', 2.2) in rows
    assert ('ch3_voltage', 3.3) in rows
    assert ('ch1_current', 10.0) in rows
    assert ('ch2_current', 20.0) in rows
    assert ('ch3_current', 30.0) in rows


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



def test_process_json_snakecase_pressure():
    """Extract barometric_pressure fields per telemetry docs."""
    reset_db()
    msg = {
        'environment_metrics': {
            'barometric_pressure': 999.9,
        },
        'user': {'id': 'abcd'},
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/test', payload)
    with app.DB_LOCK:
        rows = app.DB.execute('SELECT metric, value FROM telemetry').fetchall()
    assert rows == [('pressure', 999.9)]

def test_nodeinfo_pressure_extraction():
    """Extract pressure metric from full NodeInfo messages."""
    reset_db()
    msg = {
        '$typeName': 'meshtastic.NodeInfo',
        'user': {'id': 'node1'},
        'environmentMetrics': {
            'temperature': 25.7,
            'barometricPressure': 1017.6,
        },
        'deviceMetrics': {'batteryLevel': 88},
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/node1/info', payload)
    with app.DB_LOCK:
        rows = app.DB.execute('SELECT metric, value FROM telemetry').fetchall()
    assert ('pressure', 1017.6) in rows


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


def test_position_update_without_position_key():
    """Positions present outside a 'position' block should update nodes."""
    reset_db()
    # first message with position block
    msg1 = {
        'user': {'id': 'moveme'},
        'position': {'latitude': 1.0, 'longitude': 2.0},
    }
    app.process_mqtt_message('msh/moveme/telemetry', json.dumps(msg1).encode())

    # second message with top-level coordinates only
    msg2 = {
        'user': {'id': 'moveme'},
        'latitude': 3.0,
        'longitude': 4.0,
    }
    app.process_mqtt_message('msh/moveme/telemetry', json.dumps(msg2).encode())

    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT lat, lon FROM nodes WHERE node_id=?', ('moveme',)
        ).fetchone()
    assert row == (3.0, 4.0)


def test_position_uses_newest_timestamp(monkeypatch):
    """Positions should update only when a newer timestamp is provided."""
    reset_db()
    import processing

    times = iter([1000, 2000, 3000])
    monkeypatch.setattr(processing.time, "time", lambda: next(times))

    msg1 = {
        'user': {'id': 'timed'},
        'position': {'latitude': 1.0, 'longitude': 2.0, 'time': 100},
    }
    app.process_mqtt_message('msh/timed/telemetry', json.dumps(msg1).encode())

    msg2 = {
        'user': {'id': 'timed'},
        'position': {'latitude': 5.0, 'longitude': 6.0, 'time': 90},
    }
    app.process_mqtt_message('msh/timed/telemetry', json.dumps(msg2).encode())

    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT lat, lon, pos_ts FROM nodes WHERE node_id=?', ('timed',)
        ).fetchone()
    assert row == (1.0, 2.0, 100)

    msg3 = {
        'user': {'id': 'timed'},
        'position': {'latitude': 7.0, 'longitude': 8.0},
    }
    app.process_mqtt_message('msh/timed/telemetry', json.dumps(msg3).encode())

    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT lat, lon, pos_ts FROM nodes WHERE node_id=?', ('timed',)
        ).fetchone()
    assert row == (7.0, 8.0, 3000)


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


def test_store_generic_message():
    reset_db()
    msg = {
        'from': 'abcd',
        'decoded': {
            'portnum': 'TEXT_MESSAGE_APP',
            'payload': {'text': 'hello'},
        },
    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/abcd/text', payload)
    with app.DB_LOCK:
        row = app.DB.execute(
            'SELECT node_id, portnum, raw_json FROM messages'
        ).fetchone()
    data = json.loads(row[2])
    assert row[0] == 'abcd'
    assert row[1] == 'TEXT_MESSAGE_APP'
    assert data['decoded']['payload']['text'] == 'hello'


def test_process_traceroute_json():
    reset_db()
    msg = {
        'from': 'ff01',
        'to': 'a1b2',
        'route': ['ff01', 'a1b2'],

        'snr': 7.5,
        'rssi': -120,

    }
    payload = json.dumps(msg).encode()
    app.process_mqtt_message('msh/ff01/traceroute', payload)
    with app.DB_LOCK:
        row = app.DB.execute(

            'SELECT src_id, dest_id, hop_count, route, radio FROM traceroutes'

        ).fetchone()
    assert row[0] == 'ff01'
    assert row[1] == 'a1b2'
    assert row[2] == 1
    assert json.loads(row[3]) == ['ff01', 'a1b2']

    radio = json.loads(row[4])
    assert radio['snr'] == 7.5
    assert radio['rssi'] == -120


def test_store_traceroute_overwrites_old():
    reset_db()
    msg1 = {'from': 'ff01', 'to': 'a1b2', 'route': ['ff01', 'a1b2']}
    msg2 = {'from': 'ff01', 'to': 'a1b2', 'route': ['ff01', 'cafe', 'a1b2'], 'hop_count': 2}
    app.process_mqtt_message('msh/ff01/traceroute', json.dumps(msg1).encode())
    app.process_mqtt_message('msh/ff01/traceroute', json.dumps(msg2).encode())
    with app.DB_LOCK:
        rows = app.DB.execute(
            'SELECT hop_count, route FROM traceroutes WHERE src_id=? AND dest_id=?',
            ('ff01', 'a1b2'),
        ).fetchall()
    assert len(rows) == 1
    hop, route = rows[0]
    assert hop == 2
    assert json.loads(route) == ['ff01', 'cafe', 'a1b2']


def test_store_traceroute_removes_reverse_pair():
    reset_db()
    msg1 = {'from': 'aa01', 'to': 'bb02', 'route': ['aa01', 'bb02']}
    msg2 = {'from': 'bb02', 'to': 'aa01', 'route': ['bb02', 'aa01']}
    app.process_mqtt_message('msh/aa01/traceroute', json.dumps(msg1).encode())
    app.process_mqtt_message('msh/bb02/traceroute', json.dumps(msg2).encode())
    with app.DB_LOCK:
        rows = app.DB.execute('SELECT src_id, dest_id FROM traceroutes').fetchall()
    assert len(rows) == 1
    assert rows[0] == ('bb02', 'aa01')