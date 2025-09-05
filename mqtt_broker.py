import asyncio
import threading

from amqtt.broker import Broker

from config import MQTT_HOST, MQTT_PORT


def start_broker() -> Broker:
    """Avvia un broker MQTT embedded tramite amqtt in un thread dedicato."""

    config = {
        "listeners": {
            "default": {
                "type": "tcp",
                "bind": f"{MQTT_HOST}:{MQTT_PORT}",
            }
        },
        "sys_interval": 10,
        "auth": {"allow-anonymous": True},
    }

    broker = Broker(config)

    async def _start():
        await broker.start()

    def run():
        asyncio.run(_start())

    threading.Thread(target=run, daemon=True).start()
    return broker

