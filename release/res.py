import os
import sys
import zipfile
import tempfile

if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(APP_DIR, "resources.dat")
_CACHE_NAME = "DanbooruDownloaderResources"


def _archive_stamp():
    try:
        st = os.stat(ARCHIVE)
        return f"{st.st_size}-{int(st.st_mtime)}"
    except Exception:
        return None


def _extract_archive():
    base = os.path.join(tempfile.gettempdir(), _CACHE_NAME)
    stamp_path = os.path.join(base, ".stamp")
    stamp = _archive_stamp()
    if stamp:
        try:
            with open(stamp_path, "r", encoding="utf-8") as f:
                cached = f.read().strip()
            if cached == stamp and os.path.isdir(os.path.join(base, "icons")):
                return base
        except Exception:
            pass
    os.makedirs(base, exist_ok=True)
    with zipfile.ZipFile(ARCHIVE) as z:
        z.extractall(base)
    try:
        with open(stamp_path, "w", encoding="utf-8") as f:
            f.write(stamp or "")
    except Exception:
        pass
    return base


def _resolve_root():
    if os.path.isfile(ARCHIVE):
        try:
            return _extract_archive()
        except Exception:
            pass
    return APP_DIR


ROOT = _resolve_root()
ICONS_DIR = os.path.join(ROOT, "icons")
ASSETS_DIR = os.path.join(ROOT, "assets")
FONTS_DIR = os.path.join(ASSETS_DIR, "fonts")
