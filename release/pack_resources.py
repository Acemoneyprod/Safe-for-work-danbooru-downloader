import os
import zipfile
import tempfile
import shutil

BASE = os.path.dirname(os.path.abspath(__file__))
ARCHIVE = os.path.join(BASE, "resources.dat")


def _set_attr(attrs):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(ARCHIVE, attrs)
        except Exception:
            pass


def main():
    new_files = []
    for folder in ("icons", "assets"):
        src_root = os.path.join(BASE, folder)
        if not os.path.isdir(src_root):
            continue
        for dirpath, _dirnames, filenames in os.walk(src_root):
            for fn in filenames:
                full = os.path.join(dirpath, fn)
                new_files.append((full, os.path.relpath(full, BASE)))

    if not new_files:
        print("Nothing to pack: no icons/ or assets/ folders found.")
        return

    tmp = tempfile.mkdtemp(prefix="res_pack_")
    try:
        if os.path.isfile(ARCHIVE):
            _set_attr(0x80)
            with zipfile.ZipFile(ARCHIVE) as z:
                z.extractall(tmp)

        merged = 0
        for full, rel in new_files:
            target = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(full, target)
            merged += 1

        with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as z:
            for dirpath, _dirs, files in os.walk(tmp):
                for fn in files:
                    full = os.path.join(dirpath, fn)
                    z.write(full, os.path.relpath(full, tmp))

        _set_attr(0x02)
        with zipfile.ZipFile(ARCHIVE) as z:
            total = len(z.namelist())
        print(f"Packed {merged} file(s) - archive now holds {total} files "
              f"({os.path.getsize(ARCHIVE) / 1024 / 1024:.1f} MB)")
        print("It will be re-extracted automatically next time the app starts.")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
