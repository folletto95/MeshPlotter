# MeshPlotter

MeshPlotter is a lightweight collector and dashboard for Meshtastic networks.
It subscribes to one or more MQTT topics, decodes the incoming packets and
persists the information in a SQLite database.  A built‑in FastAPI application
exposes the stored data through a JSON API and serves a small web interface
powered by Chart.js and Leaflet.


## Features

- **MQTT ingestion** – connects to Meshtastic topics and decodes payloads in
  JSON or protobuf format.
- **Data storage** – records every packet in the `messages` table and extracts
  telemetry metrics (temperature, humidity, pressure, voltage, current and
  per‑channel power values), node information, positions and traceroute paths in
  dedicated tables.
- **Web dashboard** – the `/` page displays interactive charts for all
  collected metrics, `/map` shows node positions with hop‑coloured traceroute
  links and `/traceroutes` lists the latest paths between nodes.
- **REST API** – `/api/nodes`, `/api/metrics` and `/api/traceroutes` return the
  stored data as JSON.  The nickname of a node can be changed with a
  `POST /api/nodes/nickname` request.
- **Auto update** – an optional background thread can periodically run
  `git pull` to keep the code in sync with its remote repository.

## Configuration

Copy `example.config.yml` to `config.yml` and adjust the settings to match your
environment.  The file controls:

- **mqtt** – broker address, credentials, protocol version and the list of
  topics to subscribe to (string or array).  Set `embedded_broker: true` to
  launch a lightweight broker with [amqtt](https://github.com/beerfactory/hbmqtt)
  inside the application. TLS options are available through the `tls` section.
- **storage** – path to the SQLite database file.  Use `:memory:` for an
  in‑memory instance.
- **web** – web server host, port and optional CORS support.
- **protobuf_decode** – set to `true` (default) to enable Meshtastic protobuf
  parsing.  Requires the `meshtastic` and `protobuf` packages.

## Quick start

1. Copy `example.config.yml` to `config.yml` and adjust the broker settings.
   If you don't have an external MQTT server, set `embedded_broker: true` to
   run a built-in instance.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `python app.py`
4. Visit `http://localhost:8080` to view the dashboard.
5. Visit `http://localhost:8080/map` to see nodes and traceroute links on a
   map. Use the "Links" ("Collegamenti") checkbox to hide or show the route
   lines and "Node names" ("Nomi nodi") to toggle node labels. Link colours
   range from green (0 hop) to red (7+ hops).

6. Visit `http://localhost:8080/traceroutes` for a per‑node traceroute
   summary.

## Installazione su Windows

Per creare un eseguibile autonomo su Windows:

1. Installare le dipendenze di sviluppo: `pip install -r requirements.txt`
2. Generare il file di specifica:
   ```bash
   pyinstaller --name MeshPlotter --add-data config.yml;. --add-data static;static app.py
   ```
3. Compilare l'eseguibile "one‑file":
   ```bash
   pyinstaller MeshPlotter.spec
   ```
4. L'eseguibile `MeshPlotter.exe` verrà creato nella cartella `dist`. Avviarlo
   con un doppio click o da terminale per avviare il server.


## API overview

| Method | Endpoint               | Description                      |
| ------ | ---------------------- | -------------------------------- |
| `GET`  | `/api/nodes`           | List of known nodes (`include_inactive=false` hides unseen ones) |
| `POST` | `/api/nodes/nickname`  | Set or clear a node nickname     |
| `GET`  | `/api/metrics`         | Telemetry series (chart format)  |
| `GET`  | `/api/traceroutes`     | Recent traceroute discoveries    |

## Auto update

MeshPlotter can keep itself aligned with the latest code in its Git repository
while running. To enable it:

1. **Define the interval** – set the environment variable
   `AUTO_UPDATE_INTERVAL` to the number of seconds between update checks. If the
   variable is unset or contains a non‑numeric value, the feature is disabled.

   ```bash
   export AUTO_UPDATE_INTERVAL=3600  # check every hour
   python app.py
   ```

2. **Background update thread** – on startup the server spawns a thread that,
   at each interval:
   - runs `git fetch` to retrieve remote refs
   - compares the local and upstream commits (`git rev-parse @` vs
     `git rev-parse @{u}`)
   - executes `git pull` when a difference is detected

   Any errors (e.g. network issues or merge conflicts) are logged as warnings
   and do not stop the application.

3. **Keep a clean work tree** – ensure there are no uncommitted changes to
   avoid conflicts during the `git pull` operation.

To disable the auto-update, unset `AUTO_UPDATE_INTERVAL` or provide an empty
value before starting the server.

