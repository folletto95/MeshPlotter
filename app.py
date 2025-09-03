from api import app
from config import WEB_HOST, WEB_PORT
from database import DB, DB_LOCK
from mqtt_client import start_mqtt
from processing import process_mqtt_message

__all__ = [
    "app",
    "process_mqtt_message",
    "start_mqtt",
    "DB",
    "DB_LOCK",
]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=WEB_HOST, port=WEB_PORT, log_level="info")
