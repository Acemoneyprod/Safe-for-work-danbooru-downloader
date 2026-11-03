import os
import sys
import ctypes


def _console_process_count():
    try:
        k32 = ctypes.windll.kernel32
        buf = (ctypes.c_uint * 16)()
        return int(k32.GetConsoleProcessList(buf, 16))
    except Exception:
        return 0


def _hide_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def _relaunch_without_console():
    if os.name != "nt" or os.environ.get("DANBOORU_LAUNCHED"):
        return
    if _console_process_count() > 1:
        return
    exe = sys.executable.lower()
    if not exe.endswith("python.exe"):
        return
    pyw = sys.executable[:-len("python.exe")] + "pythonw.exe"
    if not os.path.exists(pyw):
        return
    try:
        _hide_console()
        import subprocess
        env = dict(os.environ, DANBOORU_LAUNCHED="1")
        subprocess.Popen(
            [pyw, os.path.abspath(__file__)] + sys.argv[1:],
            env=env, cwd=os.getcwd(), close_fds=True)
    except Exception:
        return
    sys.exit(0)


if __name__ == "__main__":
    _relaunch_without_console()

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)

    from bootstrap import ensure_ready
    if not ensure_ready():
        sys.exit(1)

    from gui_qt import main
    main()
