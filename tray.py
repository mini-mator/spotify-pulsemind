"""
Windows System Tray Launcher for PulseMind (`tray.py`).
- Redirects `sys.stdout` and `sys.stderr` to `data/pulsemind.log` when launched via `pythonw.exe`
  from a Windows Desktop shortcut (where stdout/stderr are `None`, which otherwise crashes uvicorn's
  logging formatter).
- Single-instance aware: if port 8765 is already listening, opens the dashboard in the browser and exits.
- Waits until the local FastAPI server is actively accepting connections before opening the browser.
"""
from __future__ import annotations

import argparse
import os
import socket
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "data"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "pulsemind.log"

# Crucial for pythonw.exe / Desktop shortcut launch: sys.stdout and sys.stderr are None without a console!
if sys.stdout is None or sys.stderr is None:
    _log_handle = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log_handle
    if sys.stderr is None:
        sys.stderr = _log_handle

import threading
import time
import webbrowser

import uvicorn
from PIL import Image, ImageDraw

from app import app, db, spotify_client, tracker

DASHBOARD_URL = "http://127.0.0.1:8765"


def is_port_listening(host: str = "127.0.0.1", port: int = 8765, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_and_open_browser(host: str = "127.0.0.1", port: int = 8765, max_wait: float = 12.0) -> None:
    deadline = time.time() + max_wait
    while time.time() < deadline:
        if is_port_listening(host, port):
            webbrowser.open(f"http://{host}:{port}")
            return
        time.sleep(0.25)
    webbrowser.open(f"http://{host}:{port}")


def create_tray_icon_image(active: bool = True) -> Image.Image:
    """Generates a clean 64x64 waveform/pulse icon for the Windows System Tray."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    bg_color = (19, 24, 34, 255)
    ring_color = (29, 185, 84, 255) if active else (245, 158, 11, 255)
    draw.ellipse((4, 4, size - 4, size - 4), fill=bg_color, outline=ring_color, width=4)

    bar_x = [18, 26, 34, 42, 50]
    bar_h = [16, 28, 36, 24, 14]
    for x, h in zip(bar_x, bar_h):
        y0 = (size - h) // 2
        y1 = y0 + h
        draw.rounded_rectangle((x - 2, y0, x + 2, y1), radius=2, fill=ring_color)
    return img


def start_uvicorn_in_thread(host: str = "127.0.0.1", port: int = 8765) -> threading.Thread:
    # Disable uvicorn's TTY-dependent default log_config so pythonw.exe never fails on .isatty()
    config = uvicorn.Config(
        app=app,
        host=host,
        port=port,
        log_level="warning",
        log_config=None,
    )
    server = uvicorn.Server(config=config)
    t = threading.Thread(target=server.run, name="PulseMindUvicorn", daemon=True)
    t.start()
    return t


def run_tray_app(open_browser_on_start: bool = True) -> None:
    import pystray

    settings = db.get_settings()
    # If PulseMind is already running in the background, just open the dashboard and exit
    if is_port_listening(settings.host, settings.port):
        if open_browser_on_start:
            webbrowser.open(f"http://{settings.host}:{settings.port}")
        return

    start_uvicorn_in_thread(host=settings.host, port=settings.port)
    tracker.start_background_loop()

    if open_browser_on_start:
        threading.Thread(
            target=wait_and_open_browser,
            args=(settings.host, settings.port),
            daemon=True,
        ).start()

    def on_open_dashboard(icon, item):
        webbrowser.open(DASHBOARD_URL)

    def on_toggle_pause(icon, item):
        tracker.paused_by_user = not tracker.paused_by_user
        icon.icon = create_tray_icon_image(active=not tracker.paused_by_user)

    def on_backfill_now(icon, item):
        if spotify_client.is_authenticated():
            tracker.backfill_recent_plays()

    def on_quit(icon, item):
        tracker.flush_active_track()
        tracker.stop_background_loop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Open PulseMind Dashboard", on_open_dashboard, default=True),
        pystray.MenuItem(
            lambda item: "Resume Spotify Tracking" if tracker.paused_by_user else "Pause Spotify Tracking",
            on_toggle_pause,
        ),
        pystray.MenuItem("Backfill Last 50 Spotify Plays", on_backfill_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit PulseMind", on_quit),
    )

    icon = pystray.Icon(
        name="PulseMind",
        icon=create_tray_icon_image(active=True),
        title="PulseMind — Spotify Tracker & Sonic DNA",
        menu=menu,
    )
    icon.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PulseMind Spotify Tracker & Recommender")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser on start")
    parser.add_argument("--headless", action="store_true", help="Run server + tracker without system tray icon")
    args = parser.parse_args()

    if args.headless:
        settings = db.get_settings()
        tracker.start_background_loop()
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning", log_config=None)
    else:
        run_tray_app(open_browser_on_start=not args.no_browser)
