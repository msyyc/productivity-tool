import threading
import webbrowser
from PIL import Image, ImageDraw
import pystray

DASHBOARD_URL = "http://localhost:8347"


def _create_icon_image(color="green"):
    """Create a simple colored circle icon."""
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    colors = {"green": "#4CAF50", "red": "#F44336", "gray": "#9E9E9E"}
    fill = colors.get(color, colors["green"])
    draw.ellipse([8, 8, 56, 56], fill=fill, outline="#FFFFFF", width=2)
    return img


def _open_dashboard(icon=None, item=None):
    webbrowser.open(DASHBOARD_URL)


def _quit(icon, item):
    icon.stop()
    import sys

    sys.exit(0)


def run_tray():
    """Start the system tray icon. Call from a background thread."""
    icon = pystray.Icon(
        "task_assistant",
        _create_icon_image(),
        "Task Assistant",
        menu=pystray.Menu(
            pystray.MenuItem("Open Dashboard", _open_dashboard, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        ),
    )
    icon.run()


def start_tray_thread():
    """Start tray icon in a daemon thread."""
    t = threading.Thread(target=run_tray, daemon=True)
    t.start()
    return t
