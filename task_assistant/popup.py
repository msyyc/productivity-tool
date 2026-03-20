import json
import subprocess
import sys
import threading
import queue
import webbrowser
from pathlib import Path


_popup_queue: queue.Queue = queue.Queue()
_popup_thread: threading.Thread | None = None
_popup_lock = threading.Lock()

# Path to the subprocess script that contains the Tkinter UI
_POPUP_SCRIPT = Path(__file__).parent / "_popup_ui.py"


def show_popup(title: str, message: str, link: str, on_dismiss=None):
    """Queue a popup notification. Thread-safe."""
    _popup_queue.put((title, message, link, on_dismiss))
    _ensure_popup_thread()


def _ensure_popup_thread():
    global _popup_thread
    with _popup_lock:
        if _popup_thread is None or not _popup_thread.is_alive():
            _popup_thread = threading.Thread(target=_popup_worker, daemon=True)
            _popup_thread.start()


def _popup_worker():
    """Process popup queue one at a time, spawning each in a subprocess."""
    while True:
        try:
            title, message, link, on_dismiss = _popup_queue.get(timeout=5)
            _spawn_popup(title, message, link, on_dismiss)
        except queue.Empty:
            break


def _spawn_popup(title: str, message: str, link: str, on_dismiss=None):
    """Run popup in a separate process so Tcl crashes never affect the server."""
    payload = json.dumps({"title": title, "message": message, "link": link})
    try:
        result = subprocess.run(
            [sys.executable, str(_POPUP_SCRIPT)],
            input=payload,
            text=True,
            capture_output=True,
            timeout=600,
        )
        # Subprocess returns "dismissed" if user clicked dismiss/close
        if on_dismiss and result.stdout.strip() == "dismissed":
            on_dismiss()
    except (subprocess.TimeoutExpired, Exception):
        pass
