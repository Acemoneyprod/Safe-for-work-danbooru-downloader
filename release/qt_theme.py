import os
import sys

from PySide6 import QtCore, QtGui, QtWidgets

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import res as _res
    FONTS_DIR = _res.FONTS_DIR
except Exception:
    FONTS_DIR = os.path.join(BASE_DIR, "assets", "fonts")


COLOR_BG_WINDOW = "#121212"
COLOR_BG_SIDEBAR = "#181818"
COLOR_BG_CARD = "#181818"
COLOR_BG_CARD_INNER = "#1e1e1e"
COLOR_BG_INPUT = "#222222"
COLOR_BG_HOVER = "#2a2a2a"
COLOR_BORDER = "#252525"
COLOR_BORDER_HOVER = "#333333"

COLOR_ACCENT = "#ffffff"
COLOR_ACCENT_HOVER = "#e5e5ea"
COLOR_TEXT_WHITE = "#ffffff"
COLOR_TEXT_INACTIVE = "#585969"
COLOR_TEXT_MUTED = "#82849e"
COLOR_RED = "#ff9696"
COLOR_DANGER = "#e05555"
COLOR_SUCCESS = "#4ade80"
COLOR_WARN = "#f59e0b"


FONT = {}

_registered = False

def register_fonts() -> dict:
    global FONT, _registered
    if _registered:
        return FONT
    families = {}
    if os.path.isdir(FONTS_DIR):
        for fn in os.listdir(FONTS_DIR):
            if fn.lower().endswith((".ttf", ".otf")):
                fid = QtGui.QFontDatabase.addApplicationFont(os.path.join(FONTS_DIR, fn))
                if fid != -1:
                    for fam in QtGui.QFontDatabase.applicationFontFamilies(fid):
                        families[fam.lower()] = fam

    def pick(*names):
        for n in names:
            got = families.get(n.lower())
            if got:
                return got
        return None
    FONT.update({
        "semibold": pick("Inter Semi Bold", "Inter Semibold", "Inter"),
        "bold": pick("Inter Extra Bold", "Inter ExtraBold", "Inter Bold", "Inter"),
        "mono": pick("JetBrains Mono", "JetBrains Mono NF", "Consolas"),
    })
    _registered = True
    return FONT

PIX_FACTOR = 1.18

def font(name: str, size: int, weight=None) -> QtGui.QFont:
    fam = FONT.get(name) or FONT.get("semibold") or "Segoe UI"
    f = QtGui.QFont(fam)
    f.setPixelSize(max(7, round(size * PIX_FACTOR)))
    f.setHintingPreference(QtGui.QFont.PreferNoHinting)
    if weight is not None:
        f.setWeight(weight)
    return f


def qcolor(hexstr: str) -> QtGui.QColor:
    return QtGui.QColor(hexstr)

def lerp_color(c1, c2, t: float) -> QtGui.QColor:
    a, b = qcolor(c1), qcolor(c2)
    return QtGui.QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )

def rgba(hexstr: str, alpha: int) -> QtGui.QColor:
    c = qcolor(hexstr)
    c.setAlpha(alpha)
    return c

def qss(str_format: str) -> str:
    return str_format


def F(size: int, name: str = "semibold") -> QtGui.QFont:
    return font(name, size)

def B(size: int) -> QtGui.QFont:
    return font("bold", size)

def MONO(size: int) -> QtGui.QFont:
    return font("mono", size)
