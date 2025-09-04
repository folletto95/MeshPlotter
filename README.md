# MeshPlotter

MeshPlotter collects telemetry data from Meshtastic MQTT topics, stores them in SQLite and provides a simple web dashboard built with FastAPI and Chart.js. A map view illustrates node positions and their traceroute connections.

All MQTT packets, including text messages, waypoints and other application types, are stored in the `messages` table for future use alongside the parsed telemetry and traceroute information.

## Quick start

1. Copy `example.config.yml` to `config.yml` and adjust the broker settings.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `python app.py`
4. Visit `http://localhost:8080` to view the dashboard.
5. Visit `http://localhost:8080/map` to see nodes and traceroute links on a map. Use the "Collegamenti" checkbox to hide or show the orange route lines.
6. Visit `http://localhost:8080/traceroutes` for a per-node traceroute summary.
