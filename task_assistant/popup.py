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
    BG = "#1e1e2e"
    FG = "#cdd6f4"
    ACCENT = "#89b4fa"
    BTN_BG = "#313244"
    BTN_HOVER = "#45475a"
    DISMISS_BG = "#585b70"

    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG)
    root.overrideredirect(True)  # Remove title bar for cleaner look
    root.attributes("-topmost", True)

    W, H = 480, 200
    root.update_idletasks()
    x = (root.winfo_screenwidth() - W) // 2
    y = (root.winfo_screenheight() - H) // 2
    root.geometry(f"{W}x{H}+{x}+{y}")

    title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
    msg_font = tkfont.Font(family="Segoe UI", size=10)
    link_font = tkfont.Font(family="Segoe UI", size=9, underline=True)
    btn_font = tkfont.Font(family="Segoe UI", size=9)

    # Title bar area
    title_frame = tk.Frame(root, bg=BG, pady=12)
    title_frame.pack(fill="x", padx=20)
    tk.Label(title_frame, text=title, font=title_font, bg=BG, fg=FG, anchor="w").pack(fill="x")

    # Message
    if message:
        tk.Label(root, text=message, font=msg_font, bg=BG, fg=FG,
                 wraplength=440, anchor="w", justify="left").pack(fill="x", padx=20)

    # Clickable link (show actual URL, truncated)
    display_link = link if len(link) <= 65 else link[:62] + "..."
    link_label = tk.Label(root, text=display_link, font=link_font, bg=BG, fg=ACCENT,
                          cursor="hand2", anchor="w")
    link_label.pack(fill="x", padx=20, pady=(8, 0))
    link_label.bind("<Button-1>", lambda e: (webbrowser.open(link), _close()))
    link_label.bind("<Enter>", lambda e: link_label.configure(fg="#b4d0fb"))
    link_label.bind("<Leave>", lambda e: link_label.configure(fg=ACCENT))

    def _close():
        if on_dismiss:
            on_dismiss()
        root.destroy()

    # Button row
    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(fill="x", padx=20, pady=(16, 14), side="bottom")

    open_btn = tk.Button(btn_frame, text="Open Link", font=btn_font,
                         bg=ACCENT, fg="#1e1e2e", activebackground="#b4d0fb",
                         relief="flat", padx=16, pady=4, cursor="hand2",
                         command=lambda: (webbrowser.open(link), _close()))
    open_btn.pack(side="left")

    dismiss_btn = tk.Button(btn_frame, text="Dismiss", font=btn_font,
                            bg=DISMISS_BG, fg=FG, activebackground=BTN_HOVER,
                            relief="flat", padx=16, pady=4, cursor="hand2",
                            command=_close)
    dismiss_btn.pack(side="left", padx=(10, 0))

    root.protocol("WM_DELETE_WINDOW", _close)

    # Allow dragging the borderless window
    def _start_drag(event):
        root._drag_x = event.x
        root._drag_y = event.y

    def _on_drag(event):
        dx = event.x - root._drag_x
        dy = event.y - root._drag_y
        new_x = root.winfo_x() + dx
        new_y = root.winfo_y() + dy
        root.geometry(f"+{new_x}+{new_y}")

    root.bind("<Button-1>", _start_drag)
    root.bind("<B1-Motion>", _on_drag)

    root.mainloop()
