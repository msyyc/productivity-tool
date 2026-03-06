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
    # --- Catppuccin Mocha palette ---
    BG = "#1e1e2e"
    SURFACE0 = "#313244"
    SURFACE1 = "#45475a"
    OVERLAY = "#6c7086"
    FG = "#cdd6f4"
    SUBTEXT = "#a6adc8"
    ACCENT = "#89b4fa"
    ACCENT_HOVER = "#b4d0fb"
    GREEN = "#a6e3a1"
    GREEN_HOVER = "#c6f0c0"
    RED = "#f38ba8"
    RED_HOVER = "#f5a3b8"

    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG)
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.0)

    W, H = 520, 240
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    target_x = screen_w - W - 24
    target_y = screen_h - H - 60
    root.geometry(f"{W}x{H}+{target_x}+{screen_h}")

    # Rounded border via Canvas
    RADIUS = 16
    canvas = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
    canvas.place(x=0, y=0)
    _rounded_rect(canvas, 0, 0, W, H, RADIUS, fill=BG, outline=SURFACE1, width=2)

    # Accent stripe at top
    canvas.create_rectangle(RADIUS, 0, W - RADIUS, 4, fill=ACCENT, outline="")
    canvas.create_rectangle(2, 4, W - 2, 4, fill=ACCENT, outline="")

    # Icon + title row
    icon = "🔔" if "Reminder" in title else "●" if "PR" in title else "📋"
    icon_font = tkfont.Font(family="Segoe UI Emoji", size=22)
    title_font = tkfont.Font(family="Segoe UI", size=14, weight="bold")
    msg_font = tkfont.Font(family="Segoe UI", size=10)
    link_font = tkfont.Font(family="Segoe UI", size=9, underline=True)
    btn_font = tkfont.Font(family="Segoe UI Semibold", size=10)
    close_font = tkfont.Font(family="Segoe UI", size=11)

    header_frame = tk.Frame(root, bg=BG)
    header_frame.place(x=20, y=16, width=W - 40, height=40)

    tk.Label(header_frame, text=icon, font=icon_font, bg=BG, fg=ACCENT).pack(side="left", padx=(0, 10))
    tk.Label(header_frame, text=title, font=title_font, bg=BG, fg=FG, anchor="w").pack(side="left", fill="x", expand=True)

    # Close (X) button in top-right
    close_btn = tk.Label(header_frame, text="✕", font=close_font, bg=BG, fg=OVERLAY, cursor="hand2")
    close_btn.pack(side="right")

    # Message
    msg_y = 62
    if message:
        msg_label = tk.Label(root, text=message, font=msg_font, bg=BG, fg=SUBTEXT,
                             wraplength=W - 48, anchor="w", justify="left")
        msg_label.place(x=24, y=msg_y)
        msg_y += 30

    # Divider line
    sep = tk.Frame(root, bg=SURFACE1, height=1)
    sep.place(x=24, y=msg_y + 4, width=W - 48)

    # Link row
    display_link = link if len(link) <= 70 else link[:67] + "…"
    link_label = tk.Label(root, text=display_link, font=link_font, bg=BG, fg=ACCENT,
                          cursor="hand2", anchor="w")
    link_label.place(x=24, y=msg_y + 14)

    # Button row at bottom
    btn_y = H - 56
    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.place(x=24, y=btn_y, width=W - 48, height=40)

    def _close():
        if on_dismiss:
            on_dismiss()
        root.destroy()

    def _make_btn(parent, text, bg_color, fg_color, hover_bg, hover_fg, command):
        btn = tk.Label(parent, text=text, font=btn_font, bg=bg_color, fg=fg_color,
                       cursor="hand2", padx=20, pady=6)
        btn.bind("<Button-1>", lambda e: command())
        btn.bind("<Enter>", lambda e: btn.configure(bg=hover_bg, fg=hover_fg))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg_color, fg=fg_color))
        return btn

    open_btn = _make_btn(btn_frame, "  Open Link  ", ACCENT, BG, ACCENT_HOVER, BG,
                         lambda: (webbrowser.open(link), _close()))
    open_btn.pack(side="left")

    dismiss_btn = _make_btn(btn_frame, "  Dismiss  ", SURFACE0, SUBTEXT, SURFACE1, FG, _close)
    dismiss_btn.pack(side="left", padx=(12, 0))

    # Wire up close button and link
    close_btn.bind("<Button-1>", lambda e: _close())
    close_btn.bind("<Enter>", lambda e: close_btn.configure(fg=RED))
    close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=OVERLAY))
    link_label.bind("<Button-1>", lambda e: (webbrowser.open(link), _close()))
    link_label.bind("<Enter>", lambda e: link_label.configure(fg=ACCENT_HOVER))
    link_label.bind("<Leave>", lambda e: link_label.configure(fg=ACCENT))

    root.protocol("WM_DELETE_WINDOW", _close)

    # Dragging
    def _start_drag(event):
        root._drag_x = event.x
        root._drag_y = event.y

    def _on_drag(event):
        dx = event.x - root._drag_x
        dy = event.y - root._drag_y
        root.geometry(f"+{root.winfo_x() + dx}+{root.winfo_y() + dy}")

    for widget in (canvas, header_frame):
        widget.bind("<Button-1>", _start_drag)
        widget.bind("<B1-Motion>", _on_drag)

    # Slide-in + fade animation
    _animate_in(root, target_x, target_y, screen_h)

    root.mainloop()


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    """Draw a rounded rectangle on a Canvas."""
    points = [
        x1 + r, y1, x2 - r, y1,
        x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2,
        x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r,
        x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def _animate_in(root, target_x, target_y, screen_h):
    """Animate the popup sliding up from the bottom with a fade."""
    steps = 14
    current_step = [0]
    start_y = screen_h

    def _step():
        t = current_step[0] / steps
        # Ease-out cubic
        t = 1 - (1 - t) ** 3
        y = int(start_y + (target_y - start_y) * t)
        alpha = min(1.0, t * 1.15)
        try:
            root.geometry(f"+{target_x}+{y}")
            root.attributes("-alpha", alpha)
        except tk.TclError:
            return
        current_step[0] += 1
        if current_step[0] <= steps:
            root.after(16, _step)

    root.after(10, _step)
