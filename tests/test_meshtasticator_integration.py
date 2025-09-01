"""Integration test simulating a Meshtastic node via MQTT.

This test spins up a local Mosquitto MQTT broker and uses the application's
MQTT stack to consume messages published by a simulated node.  The behaviour
mimics the Meshtasticator project:
https://meshtastic.org/docs/software/meshtasticator/

Two messages are sent:
* JSON telemetry
* Protobuf-encoded telemetry

The application should decode both and store the metrics in the database.
"""

import importlib
import json
import os
import subprocess
import sys
import time

from paho.mqtt.client import Client as MQTTClient
from meshtastic import telemetry_pb2

# Ensure the app uses the test configuration
os.environ['TP_CONFIG'] = os.path.join(os.path.dirname(__file__), 'test.config.yml')
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import app  # noqa: E402
importlib.reload(app)


def reset_db():
    with app.DB_LOCK:
        app.DB.execute('DELETE FROM telemetry')
        app.DB.execute('DELETE FROM nodes')
        app.DB.commit()


def start_broker():
    proc = subprocess.Popen(['mosquitto', '-p', '1883'])
    # Give the broker a moment to start
    time.sleep(0.5)
    return proc


def stop_broker(proc):
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()


def publish_json():
    client = MQTTClient()
    client.connect('localhost', 1883, 60)
    client.loop_start()
    msg = {
        'environment_metrics': {'temperature': 21.5},
        'user': {'id': 'jsonnode'}
    }
    client.publish('msh/jsonnode/telemetry', json.dumps(msg).encode())
    time.sleep(0.1)
    client.loop_stop()
    client.disconnect()


def publish_proto():
    client = MQTTClient()
    client.connect('localhost', 1883, 60)
    client.loop_start()
    t = telemetry_pb2.Telemetry()
    t.environment_metrics.temperature = 32.1
    client.publish('msh/abc123/telemetry', t.SerializeToString())
    time.sleep(0.1)
    client.loop_stop()
    client.disconnect()


def test_meshtasticator_simulation():
    reset_db()
    broker = start_broker()
    try:
        # Connect the application to the broker
        mqtt_client = app.start_mqtt()
        time.sleep(0.5)

        publish_json()
        publish_proto()

        # Allow messages to be processed
        time.sleep(0.5)

        with app.DB_LOCK:
            rows = app.DB.execute('SELECT node_id, metric, value FROM telemetry ORDER BY node_id').fetchall()
        assert ('jsonnode', 'temperature', 21.5) in rows
        assert ('abc123', 'temperature', 32.1) in rows

        mqtt_client.loop_stop()
        mqtt_client.disconnect()
    finally:
        stop_broker(broker)
