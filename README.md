# MeshPlotter

MeshPlotter collects telemetry data from Meshtastic MQTT topics, stores them in SQLite and provides a simple web dashboard built with FastAPI and Chart.js.

## Quick start

1. Copy `example.config.yml` to `config.yml` and adjust the broker settings.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `python app.py`
4. Visit `http://localhost:8080` to view the dashboard.

