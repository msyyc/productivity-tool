"""Standalone popup window process. Receives JSON on stdin, shows Tkinter popup.

Prints "opened" on stdout when the link is opened, "dismissed" when dismissed.
This runs in its own process so Tcl crashes never affect the main server.
"""

import json
import sys
import webbrowser
import tkinter as tk
from tkinter import font as tkfont


def main():
    payload = json.loads(sys.stdin.read())
    title = payload["title"]
    message = payload.get("message", "")
    link = payload["link"]

    _show_popup_window(title, message, link)


def _show_popup_window(title: str, message: str, link: str):
    BG = "#1e1e2e"
    SURFACE0 = "#313244"
    SURFACE1 = "#45475a"
    OVERLAY = "#6c7086"
    FG = "#cdd6f4"
    SUBTEXT = "#a6adc8"
    ACCENT = "#89b4fa"
    ACCENT_HOVER = "#b4d0fb"
    RED = "#f38ba8"

    root = tk.Tk()
    root.title(title)
    root.configure(bg=BG)
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.0)

    W, H = 560, 280
    root.update_idletasks()
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    target_x = screen_w - W - 24
    target_y = screen_h - H - 60
    root.geometry(f"{W}x{H}+{target_x}+{screen_h}")

    # Rounded window border
    RADIUS = 18
    canvas = tk.Canvas(root, width=W, height=H, bg=BG, highlightthickness=0)
    canvas.place(x=0, y=0)
    _rounded_rect(canvas, 0, 0, W, H, RADIUS, fill=BG, outline=SURFACE1, width=2)

    # Accent stripe at top
    canvas.create_rectangle(RADIUS, 0, W - RADIUS, 5, fill=ACCENT, outline="")
    canvas.create_rectangle(2, 5, W - 2, 5, fill=ACCENT, outline="")

    # Fonts
    icon_font = tkfont.Font(family="Segoe UI Emoji", size=26)
    title_font = tkfont.Font(family="Segoe UI", size=16, weight="bold")
    msg_font = tkfont.Font(family="Segoe UI", size=12)
    link_font = tkfont.Font(family="Segoe UI", size=10, underline=True)
    btn_font = tkfont.Font(family="Segoe UI Semibold", size=11)
    close_font = tkfont.Font(family="Segoe UI", size=13)

    # Icon + title row
    icon = "🔔" if "Reminder" in title else "●" if "PR" in title else "📋"
    header_frame = tk.Frame(root, bg=BG)
    header_frame.place(x=24, y=18, width=W - 48, height=44)

    tk.Label(header_frame, text=icon, font=icon_font, bg=BG, fg=ACCENT).pack(side="left", padx=(0, 12))
    tk.Label(header_frame, text=title, font=title_font, bg=BG, fg=FG, anchor="w").pack(
        side="left", fill="x", expand=True
    )

    close_btn = tk.Label(header_frame, text="✕", font=close_font, bg=BG, fg=OVERLAY, cursor="hand2")
    close_btn.pack(side="right")

    minimize_btn = tk.Label(header_frame, text="—", font=close_font, bg=BG, fg=OVERLAY, cursor="hand2")
    minimize_btn.pack(side="right", padx=(0, 8))

    # Message (PR title or description)
    content_y = 70
    body_widgets = []
    if message:
        msg_label = tk.Label(
            root, text=message, font=msg_font, bg=BG, fg=FG, wraplength=W - 56, anchor="w", justify="left"
        )
        msg_label.place(x=28, y=content_y)
        body_widgets.append(msg_label)
        content_y += 36

    # Divider
    divider = tk.Frame(root, bg=SURFACE1, height=1)
    divider.place(x=28, y=content_y + 2, width=W - 56)
    body_widgets.append(divider)

    # Link row
    display_link = link if len(link) <= 65 else link[:62] + "…"
    link_label = tk.Label(root, text=display_link, font=link_font, bg=BG, fg=ACCENT, cursor="hand2", anchor="w")
    link_label.place(x=28, y=content_y + 14)
    body_widgets.append(link_label)

    result = ["dismissed"]

    def _close():
        root.destroy()

    def _open_link():
        webbrowser.open(link)
        result[0] = "opened"
        root.destroy()

    # Rounded buttons via Canvas
    btn_y = H - 62
    btn_canvas = tk.Canvas(root, width=W - 56, height=42, bg=BG, highlightthickness=0)
    btn_canvas.place(x=28, y=btn_y)
    body_widgets.append(btn_canvas)

    open_btn_id = _rounded_rect(btn_canvas, 0, 0, 140, 40, 10, fill=ACCENT, outline="")
    btn_canvas.create_text(70, 20, text="Open Link", font=btn_font, fill=BG)

    dismiss_btn_id = _rounded_rect(btn_canvas, 154, 0, 280, 40, 10, fill=SURFACE0, outline="")
    dismiss_txt_id = btn_canvas.create_text(217, 20, text="Dismiss", font=btn_font, fill=SUBTEXT)

    def _btn_click(e):
        if e.x <= 140:
            _open_link()
        elif 154 <= e.x <= 280:
            _close()

    btn_canvas.bind("<Button-1>", _btn_click)
    btn_canvas.bind(
        "<Motion>",
        lambda e: (
            btn_canvas.itemconfig(open_btn_id, fill=ACCENT_HOVER if e.x <= 140 else ACCENT),
            btn_canvas.itemconfig(dismiss_btn_id, fill=SURFACE1 if 154 <= e.x <= 280 else SURFACE0),
            btn_canvas.itemconfig(dismiss_txt_id, fill=FG if 154 <= e.x <= 280 else SUBTEXT),
        ),
    )
    btn_canvas.bind(
        "<Leave>",
        lambda e: (
            btn_canvas.itemconfig(open_btn_id, fill=ACCENT),
            btn_canvas.itemconfig(dismiss_btn_id, fill=SURFACE0),
            btn_canvas.itemconfig(dismiss_txt_id, fill=SUBTEXT),
        ),
    )

    # Minimize / Restore logic
    minimized = [False]
    MINI_H = 52

    def _minimize(e=None):
        if minimized[0]:
            return
        minimized[0] = True
        for w in body_widgets:
            w.place_forget()
        canvas.place_forget()
        canvas_mini = tk.Canvas(root, width=W, height=MINI_H, bg=BG, highlightthickness=0)
        canvas_mini.place(x=0, y=0)
        _rounded_rect(canvas_mini, 0, 0, W, MINI_H, RADIUS, fill=BG, outline=SURFACE1, width=2)
        canvas_mini.create_rectangle(RADIUS, 0, W - RADIUS, 5, fill=ACCENT, outline="")
        canvas_mini.create_rectangle(2, 5, W - 2, 5, fill=ACCENT, outline="")
        canvas_mini.bind("<Button-1>", _start_drag)
        canvas_mini.bind("<B1-Motion>", _on_drag)
        root._mini_canvas = canvas_mini
        header_frame.lift()
        minimize_btn.configure(text="□")
        cur_x = root.winfo_x()
        new_y = root.winfo_y() + (H - MINI_H)
        root.geometry(f"{W}x{MINI_H}+{cur_x}+{new_y}")

    def _restore(e=None):
        if not minimized[0]:
            return
        minimized[0] = False
        if hasattr(root, "_mini_canvas"):
            root._mini_canvas.destroy()
        canvas.place(x=0, y=0)
        # Re-place body widgets at original positions
        _restore_body_widgets()
        header_frame.lift()
        minimize_btn.configure(text="—")
        cur_x = root.winfo_x()
        new_y = root.winfo_y() - (H - MINI_H)
        root.geometry(f"{W}x{H}+{cur_x}+{new_y}")

    def _restore_body_widgets():
        _content_y = 70
        if message:
            body_widgets[0].place(x=28, y=_content_y)
            _content_y += 36
        idx = 1 if message else 0
        body_widgets[idx].place(x=28, y=_content_y + 2, width=W - 56)
        body_widgets[idx + 1].place(x=28, y=_content_y + 14)
        body_widgets[idx + 2].place(x=28, y=H - 62)

    def _toggle_minimize(e=None):
        if minimized[0]:
            _restore()
        else:
            _minimize()

    minimize_btn.bind("<Button-1>", _toggle_minimize)
    minimize_btn.bind("<Enter>", lambda e: minimize_btn.configure(fg=ACCENT))
    minimize_btn.bind("<Leave>", lambda e: minimize_btn.configure(fg=OVERLAY))

    # Close button and link
    close_btn.bind("<Button-1>", lambda e: _close())
    close_btn.bind("<Enter>", lambda e: close_btn.configure(fg=RED))
    close_btn.bind("<Leave>", lambda e: close_btn.configure(fg=OVERLAY))
    link_label.bind("<Button-1>", lambda e: _open_link())
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
    print(result[0], flush=True)


def _rounded_rect(canvas, x1, y1, x2, y2, r, **kwargs):
    points = [
        x1 + r,
        y1,
        x2 - r,
        y1,
        x2,
        y1,
        x2,
        y1 + r,
        x2,
        y2 - r,
        x2,
        y2,
        x2 - r,
        y2,
        x1 + r,
        y2,
        x1,
        y2,
        x1,
        y2 - r,
        x1,
        y1 + r,
        x1,
        y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def _animate_in(root, target_x, target_y, screen_h):
    steps = 14
    current_step = [0]
    start_y = screen_h

    def _step():
        t = current_step[0] / steps
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


if __name__ == "__main__":
    main()
