# MeshPlotter

MeshPlotter collects telemetry data from Meshtastic MQTT topics, stores them in SQLite and provides a simple web dashboard built with FastAPI and Chart.js. A map view illustrates node positions and their traceroute connections.

All MQTT packets, including text messages, waypoints and other application types, are stored in the `messages` table for future use alongside the parsed telemetry and traceroute information.

## Quick start

1. Copy `example.config.yml` to `config.yml` and adjust the broker settings.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `python app.py`
4. Visit `http://localhost:8080` to view the dashboard.
5. Visit `http://localhost:8080/map` to see nodes and traceroute links on a map. Use the "Collegamenti" checkbox to hide or show the route lines and "Nomi nodi" to toggle node labels. Link colours range from green (0 hop) to red (7+ hops).
6. Visit `http://localhost:8080/traceroutes` for a per-node traceroute summary.

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

3. **Keep a clean work tree** – ensure there are no uncommitted changes to avoid
   conflicts during the `git pull` operation.

To disable the auto-update, unset `AUTO_UPDATE_INTERVAL` or provide an empty
value before starting the server.