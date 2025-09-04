import logging
import os
import subprocess
import threading
import time


def update_repo() -> None:
    """Fetch and merge updates from the tracked remote.

    If the local repository is behind its upstream, perform ``git pull`` to
    update the working tree. Any error during the process is logged but does
    not raise an exception so the application can continue running.
    """
    try:
        subprocess.run(["git", "fetch"], check=True)
        local = subprocess.check_output(["git", "rev-parse", "@"]).strip()
        remote = subprocess.check_output(["git", "rev-parse", "@{u}"]).strip()
        if local != remote:
            logging.info("Updating repository to latest version")
            subprocess.run(["git", "pull"], check=True)
    except Exception as exc:
        logging.warning("Auto-update failed: %s", exc)


def _loop(interval: int) -> None:
    while True:
        update_repo()
        time.sleep(interval)


def maybe_auto_update() -> None:
    """Start periodic repository updates if configured.

    Set the environment variable ``AUTO_UPDATE_INTERVAL`` to an integer value
    in seconds to enable periodic ``git pull`` operations. If the variable is
    unset, the application runs without attempting to update itself.
    """
    interval = os.getenv("AUTO_UPDATE_INTERVAL")
    if not interval:
        return
    try:
        seconds = int(interval)
    except ValueError:
        logging.warning("Invalid AUTO_UPDATE_INTERVAL: %r", interval)
        return
    thread = threading.Thread(target=_loop, args=(seconds,), daemon=True)
    thread.start()
