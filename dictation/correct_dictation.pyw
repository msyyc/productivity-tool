"""Desktop dictation correction over a persistent, text-only Copilot connection."""

from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from dictation_client import DictationClient


ROOT = Path(__file__).resolve().parent
SKILL = ROOT.parent / ".github" / "skills" / "correct-dictation" / "SKILL.md"


def correct_text(transcript, cancelled=None):
    client = DictationClient()
    try:
        return client.correct(transcript, SKILL, cancelled)
    finally:
        client.close()


class DictationWindow:
    def __init__(self, root):
        self.root = root
        self.results = queue.Queue()
        self.requests = queue.Queue()
        self.client = DictationClient()
        self.cancelled = threading.Event()
        self.busy = False
        self.closing = False
        root.title("Correct Dictation")
        root.geometry("820x720")
        root.minsize(480, 480)
        root.configure(background="#f3f5f4")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#f3f5f4")
        style.configure("TLabel", background="#f3f5f4", foreground="#202c29", font=("Segoe UI", 11))
        style.configure("TButton", font=("Segoe UI", 10), padding=(14, 7))
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 20))
        style.configure("Accent.TButton", background="#126b56", foreground="white")
        style.map("Accent.TButton", background=[("active", "#0c5342"), ("disabled", "#ced6d2")])
        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        frame.rowconfigure(4, weight=1)
        ttk.Label(frame, text="Correct Dictation", style="Title.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 18))
        input_header = ttk.Frame(frame)
        input_header.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(input_header, text="Input").pack(side="left")
        self.clear_button = ttk.Button(input_header, text="Clear", command=self.clear_input)
        self.clear_button.pack(side="right", padx=(8, 0))
        self.start_button = ttk.Button(input_header, text="Start", style="Accent.TButton",
                           command=self.start, state="disabled")
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(input_header, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=8)
        self.input = ScrolledText(frame, wrap="word", font=("Segoe UI", 12),
                                  height=7, width=30, relief="flat", padx=12, pady=12, undo=True)
        self.input.grid(row=2, column=0, sticky="nsew")
        output_header = ttk.Frame(frame)
        output_header.grid(row=3, column=0, sticky="ew", pady=(18, 8))
        ttk.Label(output_header, text="Output").pack(side="left")
        self.copy_button = ttk.Button(output_header, text="Copy", command=self.copy, state="disabled")
        self.copy_button.pack(side="right")
        self.output = ScrolledText(frame, wrap="word", font=("Segoe UI", 12),
                                   height=7, width=30, relief="flat", padx=12, pady=12,
                                   state="disabled", undo=True)
        self.output.grid(row=4, column=0, sticky="nsew")
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(row=5, column=0, sticky="ew", pady=(16, 8))
        self.status = tk.StringVar(value="Connecting...")
        status_label = ttk.Label(frame, textvariable=self.status, wraplength=720)
        status_label.grid(row=6, column=0, sticky="ew")
        status_label.bind("<Configure>", lambda event: status_label.configure(wraplength=max(100, event.width)))
        self.input.focus_set()
        self.worker = threading.Thread(target=self.work)
        self.worker.start()
        self.poll_id = root.after(100, self.poll)

    def start(self):
        if self.busy or self.closing:
            return
        transcript = self.input.get("1.0", "end-1c")
        if not transcript.strip():
            self.status.set("Enter some text first.")
            return
        self.busy = True
        self.cancelled.clear()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.clear_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.input.configure(state="disabled")
        self.set_output("")
        self.status.set("Correcting...")
        self.progress.start(12)
        self.requests.put(transcript)

    def work(self):
        try:
            try:
                self.client.start(self.cancelled)
                self.results.put(("ready", "Ready"))
            except (OSError, RuntimeError, ValueError) as error:
                self.results.put(("ready", str(error)))
            while True:
                transcript = self.requests.get()
                if transcript is None or self.closing:
                    break
                try:
                    output = self.client.correct(
                        transcript, SKILL, self.cancelled,
                        on_text=lambda text: self.results.put(("text", text)),
                    )
                    self.results.put(("done", output))
                except (OSError, RuntimeError, ValueError, KeyError) as error:
                    self.results.put(("error", str(error)))
        finally:
            self.client.close()

    def poll(self):
        if self.closing:
            if not self.worker.is_alive():
                self.root.destroy()
                return
            self.poll_id = self.root.after(100, self.poll)
            return
        for _ in range(200):
            try:
                kind, text = self.results.get_nowait()
            except queue.Empty:
                break
            if kind == "ready":
                self.start_button.configure(state="normal")
                self.status.set(text)
                continue
            if kind == "text":
                if not self.cancelled.is_set():
                    self.output.configure(state="normal")
                    self.output.insert("end", text)
                    self.output.see("end")
                    self.output.configure(state="disabled")
                continue
            self.busy = False
            self.progress.stop()
            self.start_button.configure(state="normal")
            self.cancel_button.configure(state="disabled")
            self.clear_button.configure(state="normal")
            self.input.configure(state="normal")
            if kind == "done" and not self.cancelled.is_set():
                self.set_output(text)
                self.output.configure(state="normal")
                self.copy_button.configure(state="normal")
                self.status.set("Done")
            else:
                self.set_output("")
                self.status.set("Cancelled." if self.cancelled.is_set() else text)
        self.poll_id = self.root.after(100, self.poll)

    def clear_input(self):
        if self.busy or self.closing:
            return
        self.input.delete("1.0", "end")
        self.input.focus_set()

    def set_output(self, text):
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.edit_reset()
        self.output.configure(state="disabled")

    def copy(self):
        text = self.output.get("1.0", "end-1c")
        if text:
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.root.update_idletasks()
                self.status.set("Copied")
            except tk.TclError:
                self.status.set("Clipboard is busy. Try Copy again.")

    def cancel(self):
        self.cancelled.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("Cancelling...")

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.cancelled.set()
        self.requests.put(None)
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self.clear_button.configure(state="disabled")
        self.copy_button.configure(state="disabled")
        self.status.set("Closing...")


if __name__ == "__main__":
    window = tk.Tk()
    DictationWindow(window)
    window.mainloop()