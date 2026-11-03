import ctypes
import importlib
import importlib.util
import os
import queue
import subprocess
import sys
import threading

MIN_PYTHON = (3, 9)

REQUIRED = (
    ("PySide6", "PySide6"),
    ("requests", "requests"),
    ("pillow", "PIL"),
)

BG = "#121212"
CARD = "#1a1a1a"
TEXT = "#ffffff"
MUTED = "#82849e"
ACCENT = "#ffffff"
SUCCESS = "#7ee0a1"
ERROR = "#ff9696"


def missing_packages():
    missing = []
    for pip_name, module in REQUIRED:
        try:
            found = importlib.util.find_spec(module) is not None
        except Exception:
            found = False
        if not found:
            missing.append(pip_name)
    return missing


def _creation_flags():
    if os.name == "nt":
        return 0x08000000
    return 0


def _run(cmd, on_line=None):
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, creationflags=_creation_flags(),
        cwd=os.path.dirname(os.path.abspath(__file__)))
    if proc.stdout is not None:
        for line in proc.stdout:
            if on_line is not None:
                on_line(line.rstrip())
    return proc.wait()


def _pip_install(pkgs, on_line):
    base = [sys.executable, "-m", "pip", "install", "--upgrade",
            "--no-input", "--disable-pip-version-check"]
    if _run([sys.executable, "-m", "pip", "--version"], None) != 0:
        on_line("pip was not found - preparing it (ensurepip)...")
        _run([sys.executable, "-m", "ensurepip", "--upgrade"], on_line)
    on_line("Installing: " + ", ".join(pkgs))
    if _run(base + list(pkgs), on_line) == 0:
        return True
    on_line("Retrying with a per-user install (--user)...")
    return _run(base + ["--user"] + list(pkgs), on_line) == 0


def _fatal(message):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("SFW Danbooru Downloader", message)
        root.destroy()
        return
    except Exception:
        pass
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(
                0, message, "SFW Danbooru Downloader", 0x10)
            return
        except Exception:
            pass
    print(message)


def _installer_window(pkgs):
    import tkinter as tk
    from tkinter import ttk

    state = {"ok": False, "running": False, "closed": False}
    events = queue.Queue()

    root = tk.Tk()
    root.title("SFW Danbooru Downloader - Setup")
    root.configure(bg=BG)
    root.resizable(False, False)
    width, height = 680, 480
    root.update_idletasks()
    x = (root.winfo_screenwidth() - width) // 2
    y = (root.winfo_screenheight() - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    tk.Label(root, text="SFW DANBOORU DOWNLOADER", bg=BG, fg=TEXT,
             font=("Segoe UI Semibold", 16)).pack(pady=(26, 2))
    tk.Label(root, text="First-time setup", bg=BG, fg=MUTED,
             font=("Segoe UI", 10)).pack()

    tk.Label(
        root,
        text=("This app needs a few Python packages.\n"
              "They will be downloaded and installed automatically "
              "(one time only)."),
        bg=BG, fg=TEXT, font=("Segoe UI", 10), justify="center").pack(pady=(16, 6))
    tk.Label(root, text="   •   ".join(pkgs), bg=BG, fg=ACCENT,
             font=("Segoe UI Semibold", 10)).pack()

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Setup.Horizontal.TProgressbar",
                    troughcolor=CARD, background="#ffffff",
                    bordercolor=CARD, lightcolor="#ffffff",
                    darkcolor="#ffffff")
    prog = ttk.Progressbar(root, style="Setup.Horizontal.TProgressbar",
                           mode="indeterminate", length=580)
    prog.pack(pady=14)

    status = tk.Label(root, text="Waiting to install...", bg=BG, fg=MUTED,
                      font=("Segoe UI", 9))
    status.pack()

    log = tk.Text(root, height=9, bg="#0c0c0e", fg="#b9b9c4",
                  insertbackground=TEXT, relief="flat",
                  font=("Consolas", 8), wrap="none")
    log.pack(fill="both", expand=True, padx=30, pady=(10, 0))
    log.configure(state="normal")

    buttons = tk.Frame(root, bg=BG)
    buttons.pack(fill="x", padx=30, pady=14)

    install_btn = tk.Button(
        buttons, text="INSTALL NOW", bg="#ffffff", fg="#121212",
        activebackground="#e5e5ea", activeforeground="#121212",
        relief="flat", font=("Segoe UI Semibold", 10),
        padx=20, pady=7, cursor="hand2")
    install_btn.pack(side="left")
    quit_btn = tk.Button(
        buttons, text="QUIT", bg=CARD, fg=TEXT,
        activebackground="#2a2a32", activeforeground=TEXT,
        relief="flat", font=("Segoe UI", 10),
        padx=20, pady=7, cursor="hand2")
    quit_btn.pack(side="left", padx=(10, 0))

    def add_log(text):
        log.insert("end", text + "\n")
        try:
            if int(log.index("end-1c").split(".")[0]) > 400:
                log.delete("1.0", "80.0")
        except Exception:
            pass
        log.see("end")

    def worker():
        try:
            ok = _pip_install(pkgs, lambda line: events.put(("log", line)))
            events.put(("done" if ok else "fail", None))
        except Exception as e:
            events.put(("log", f"Error: {e}"))
            events.put(("fail", None))

    def start():
        if state["running"]:
            return
        state["running"] = True
        install_btn.config(state="disabled", text="INSTALLING...")
        prog.start(12)
        status.config(text="Installing packages - this can take a few minutes "
                           "(PySide6 is large)...", fg=MUTED)
        threading.Thread(target=worker, daemon=True).start()

    def poll():
        if state["closed"]:
            return
        try:
            while True:
                kind, payload = events.get_nowait()
                if kind == "log":
                    add_log(payload)
                elif kind == "done":
                    state["ok"] = True
                    state["running"] = False
                    prog.stop()
                    status.config(text="Done - starting the app...", fg=SUCCESS)
                    root.after(800, root.destroy)
                elif kind == "fail":
                    state["running"] = False
                    prog.stop()
                    status.config(
                        text="Installation failed. Check your internet "
                             "connection and try again.", fg=ERROR)
                    install_btn.config(state="normal", text="RETRY")
        except queue.Empty:
            pass
        root.after(80, poll)

    def on_quit():
        state["closed"] = True
        root.destroy()

    install_btn.config(command=start)
    quit_btn.config(command=on_quit)
    root.protocol("WM_DELETE_WINDOW", on_quit)
    root.after(80, poll)
    root.after(450, start)
    root.mainloop()
    state["closed"] = True
    return state["ok"]


def ensure_ready():
    if getattr(sys, "frozen", False):
        return True
    if sys.version_info < MIN_PYTHON:
        _fatal(f"This app needs Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} "
               f"or newer.\nYou are running Python "
               f"{sys.version_info.major}.{sys.version_info.minor}.")
        return False

    pkgs = missing_packages()
    if not pkgs:
        return True

    if not _installer_window(pkgs):
        return False

    script = os.path.abspath(sys.argv[0])
    args = [sys.executable, script] + sys.argv[1:]
    try:
        os.execv(sys.executable, args)
    except Exception:
        importlib.invalidate_caches()
        try:
            import site
            site.main()
        except Exception:
            pass
        return not missing_packages()
    return True


if __name__ == "__main__":
    print("missing packages:", missing_packages())
