"""Windows entry point: a single local server and a browser tab."""
import os
import json
import socket
import threading
import time
import urllib.request
import uuid
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

import uvicorn

ROOT = Path(__file__).resolve().parent


def valid_dashboard_url(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port is not None and 1 <= parsed.port <= 65535
                and parsed.username is None and parsed.password is None
                and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment)
    except (ValueError, TypeError, AttributeError):
        return False


def dashboard_responds(url, instance_id):
    try:
        # A local dashboard should not depend on the machine's internet proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url.rstrip("/") + "/health", timeout=1) as response:
            data = json.loads(response.read(4096))
        return data.get("app") == "tabchi" and data.get("instance_id") == instance_id
    except (OSError, ValueError, AttributeError):
        return False


def reopen_existing(marker, attempts=20):
    for _ in range(attempts):
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
            url, instance_id = info["url"], info["instance_id"]
            if valid_dashboard_url(url) and instance_id and dashboard_responds(url, instance_id):
                print(f"The app is already running.\nDashboard: {url}", flush=True)
                if not os.getenv("TABCHI_NO_BROWSER") and not webbrowser.open(url):
                    print("Could not open the browser automatically. Copy the Dashboard address above.", flush=True)
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        time.sleep(0.25)
    print("An app instance is running, but its dashboard is not ready. Wait a moment and try again.\n"
          "If this continues, close the original app terminal and start again.", flush=True)
    return False


def main():
    os.chdir(ROOT)
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    marker = data / "server.json"
    lock = open(data / "app.lock", "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        return 0 if reopen_existing(marker) else 1
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"
    instance_id = uuid.uuid4().hex
    os.environ["TABCHI_INSTANCE_ID"] = instance_id
    temporary = data / "server.next.json"
    temporary.write_text(json.dumps({"url": url, "instance_id": instance_id, "pid": os.getpid()}), encoding="utf-8")
    temporary.replace(marker)
    print(f"Dashboard: {url}\nKeep this window open while working. Ctrl+C stops the app.", flush=True)

    def open_when_ready():
        for _ in range(100):
            if dashboard_responds(url, instance_id):
                if not webbrowser.open(url):
                    print("Copy the Dashboard address above into your browser.", flush=True)
                return
            time.sleep(0.1)

    if not os.getenv("TABCHI_NO_BROWSER"):
        threading.Thread(target=open_when_ready, daemon=True).start()
    try:
        uvicorn.run("app.web:app", host="127.0.0.1", port=port, access_log=False)
    finally:
        try:
            if json.loads(marker.read_text(encoding="utf-8")).get("instance_id") == instance_id:
                marker.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
