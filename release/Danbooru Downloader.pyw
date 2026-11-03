import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from bootstrap import ensure_ready

if __name__ == "__main__":
    if not ensure_ready():
        sys.exit(1)
    from gui_qt import main
    main()
