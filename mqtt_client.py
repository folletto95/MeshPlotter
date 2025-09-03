import ssl
from paho.mqtt.client import Client as MQTTClient, CallbackAPIVersion, MQTTv311, MQTTv5

from config import MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_CLIENT_ID, MQTT_PROTO, MQTT_TOPICS, TLS_CFG
from processing import process_mqtt_message


def start_mqtt():
    """Configura e avvia il client MQTT."""
    proto = MQTTv311 if MQTT_PROTO == "v311" else MQTTv5
    client = MQTTClient(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id=MQTT_CLIENT_ID,
        clean_session=True,
        protocol=proto,
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS)
    if TLS_CFG.get("enabled"):
        client.tls_set(
            ca_certs=TLS_CFG.get("ca_certs") or None,
            certfile=TLS_CFG.get("certfile") or None,
            keyfile=TLS_CFG.get("keyfile") or None,
            tls_version=ssl.PROTOCOL_TLS_CLIENT,
        )
        if TLS_CFG.get("insecure"):
            client.tls_insecure_set(True)

    client.reconnect_delay_set(min_delay=1, max_delay=30)

    def on_connect(client, userdata, flags, reason_code, properties=None):
        ok = getattr(reason_code, "value", reason_code) == 0
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
        process_mqtt_message(msg.topic, msg.payload)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    return client
