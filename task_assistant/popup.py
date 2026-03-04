import threading
import queue
import webbrowser
import tkinter as tk
from tkinter import font as tkfont


_popup_queue: queue.Queue = queue.Queue()
_popup_thread: threading.Thread | None = None
_popup_lock = threading.Lock()


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
    """Process popup queue one at a time."""
    while True:
        try:
            title, message, link, on_dismiss = _popup_queue.get(timeout=5)
            _show_popup_window(title, message, link, on_dismiss)
        except queue.Empty:
            break  # Exit thread when queue is empty for 5 seconds


def _show_popup_window(title: str, message: str, link: str, on_dismiss=None):
    root = tk.Tk()
    root.title(title)
    root.geometry("450x180")
    root.attributes("-topmost", True)
    root.resizable(False, False)

    # Center on screen
    root.update_idletasks()
    x = (root.winfo_screenwidth() - 450) // 2
    y = (root.winfo_screenheight() - 180) // 2
    root.geometry(f"450x180+{x}+{y}")

    bold_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
    normal_font = tkfont.Font(family="Segoe UI", size=10)
    link_font = tkfont.Font(family="Segoe UI", size=10, underline=True)

    tk.Label(root, text=title, font=bold_font, pady=10).pack()
    tk.Label(root, text=message, font=normal_font, wraplength=400).pack()

    link_label = tk.Label(root, text="Open Link", font=link_font, fg="blue", cursor="hand2")
    link_label.pack(pady=5)
    link_label.bind("<Button-1>", lambda e: (webbrowser.open(link), root.destroy()))

    def dismiss():
        if on_dismiss:
            on_dismiss()
        root.destroy()

    tk.Button(root, text="Dismiss", command=dismiss, width=10).pack(pady=5)

    root.protocol("WM_DELETE_WINDOW", dismiss)
    root.mainloop()
