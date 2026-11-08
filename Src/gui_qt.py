import os
import re
import sys
import math
import random
import time
import json
import queue
import logging
import threading
import subprocess
import ctypes
import webbrowser
from concurrent.futures import ThreadPoolExecutor

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import (
    Qt, QTimer, Signal, QPropertyAnimation, QVariantAnimation,
    QEasingCurve, QPoint, QRect, QSize,
)

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

try:
    import res as _res
    ICONS_DIR = _res.ICONS_DIR
    ASSETS_DIR = _res.ASSETS_DIR
except Exception:
    ICONS_DIR = os.path.join(BASE_DIR, "icons")
    ASSETS_DIR = os.path.join(BASE_DIR, "assets")

import downloader
import sites
from sites import post_key
from downloader import (
    config,
    check_tag_details,
    create_save_folder,
    fetch_tag_suggestions,
    search_tags_to_triggers,
    add_own_triggers,
    remove_tags_from_txt_files,
)

import qt_widgets
import qt_theme
import i18n
import updater
from stats_page import StatsPage
from qt_theme import (
    COLOR_ACCENT, COLOR_ACCENT_HOVER, COLOR_BG_CARD, COLOR_BG_CARD_INNER,
    COLOR_BG_HOVER, COLOR_BG_INPUT, COLOR_BG_SIDEBAR, COLOR_BG_WINDOW,
    COLOR_BORDER, COLOR_BORDER_HOVER, COLOR_DANGER, COLOR_RED,
    COLOR_SUCCESS, COLOR_WARN, COLOR_TEXT_INACTIVE, COLOR_TEXT_MUTED,
    COLOR_TEXT_WHITE, B, F, MONO, qcolor, rgba, lerp_color, register_fonts,
)
from qt_widgets import (
    HoverButton, PillTabButton, ToggleSwitchWidget, DarkSlider, Card,
    TagChipInput, FlowLayout, GlowBar, RollingCounter, AnchorCombo, Toast,
)


CONFIG_FILE = os.path.join(BASE_DIR, "gui_config.json")
MAX_CONSOLE_LINES = 2000


def tint(pix: QtGui.QPixmap, color_hex: str) -> QtGui.QPixmap:
    img = pix.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
    p = QtGui.QPainter(img)
    p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
    p.fillRect(img.rect(), qcolor(color_hex))
    p.end()
    return QtGui.QPixmap.fromImage(img)


def load_icon(filename, size=20) -> QtGui.QPixmap | None:
    for folder in (ICONS_DIR, ASSETS_DIR, os.path.join(ASSETS_DIR, "icons")):
        path = os.path.join(folder, filename)
        if os.path.exists(path) and os.path.isfile(path):
            pix = QtGui.QPixmap(path)
            if not pix.isNull():
                return pix.scaled(size, size, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation)
    return None


def app_icon() -> QtGui.QIcon:
    path = None
    for candidate in (os.path.join(ICONS_DIR, "app_icon.png"),
                      os.path.join(ASSETS_DIR, "app_icon.png"),
                      os.path.join(ASSETS_DIR, "icons", "app_icon.png")):
        if os.path.isfile(candidate):
            path = candidate
            break
    if path is None:
        for folder in (ICONS_DIR, ASSETS_DIR):
            candidate = os.path.join(folder, "Konata.png")
            if os.path.isfile(candidate):
                path = candidate
                break
    icon = QtGui.QIcon()
    if path:
        src = QtGui.QPixmap(path)
        if not src.isNull():
            for size in (16, 24, 32, 48, 64, 128, 256):
                icon.addPixmap(src.scaled(size, size, Qt.KeepAspectRatio,
                                          Qt.SmoothTransformation))
    return icon


def flag_pixmap(code, height=18):
    try:
        path = os.path.join(ASSETS_DIR, "flags", code + ".png")
        pm = QtGui.QPixmap(path)
        if not pm.isNull():
            return pm.scaledToHeight(height, Qt.SmoothTransformation)
    except Exception:
        pass
    return None


def eye_icon(color_hex: str, size=16) -> QtGui.QPixmap:
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    c = qcolor(color_hex)
    pen = QtGui.QPen(c)
    pen.setWidthF(1.4)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QtGui.QPainterPath()
    path.moveTo(1.2, size / 2.0)
    path.cubicTo(size * 0.30, 2.2, size * 0.70, 2.2, size - 1.2, size / 2.0)
    path.cubicTo(size * 0.70, size - 2.2, size * 0.30, size - 2.2,
                 1.2, size / 2.0)
    p.drawPath(path)
    p.setPen(Qt.NoPen)
    p.setBrush(c)
    p.drawEllipse(QtCore.QPointF(size / 2.0, size / 2.0), 2.5, 2.5)
    p.end()
    return pm



class QueueLogHandler(logging.Handler):
    def __init__(self, emitter):
        super().__init__()
        self.emitter = emitter

    def emit(self, record):
        try:
            self.emitter(record.levelno, self.format(record))
        except Exception:
            pass


def read_flac_metadata(path):
    try:
        with open(path, "rb") as f:
            if f.read(4) != b"fLaC":
                return None
            artist = title = None
            cover = None
            while True:
                header = f.read(4)
                if len(header) < 4:
                    break
                is_last = bool(header[0] & 0x80)
                block_type = header[0] & 0x7F
                length = int.from_bytes(header[1:4], "big")
                data = f.read(length)
                if block_type == 4:
                    try:
                        pos = 0
                        vendor_len = int.from_bytes(data[pos:pos + 4], "little")
                        pos += 4 + vendor_len
                        count = int.from_bytes(data[pos:pos + 4], "little")
                        pos += 4
                        for _ in range(count):
                            ln = int.from_bytes(data[pos:pos + 4], "little")
                            pos += 4
                            entry = data[pos:pos + ln]
                            pos += ln
                            key, _, val = entry.partition(b"=")
                            key = key.decode("utf-8", "replace").upper()
                            if key == "ARTIST" and not artist:
                                artist = val.decode("utf-8", "replace")
                            elif key == "TITLE" and not title:
                                title = val.decode("utf-8", "replace")
                    except Exception:
                        pass
                elif block_type == 6 and cover is None:
                    try:
                        pos = 4
                        mime_len = int.from_bytes(data[pos:pos + 4], "big")
                        pos += 4 + mime_len
                        desc_len = int.from_bytes(data[pos:pos + 4], "big")
                        pos += 4 + desc_len
                        pos += 16
                        data_len = int.from_bytes(data[pos:pos + 4], "big")
                        pos += 4
                        cover = data[pos:pos + data_len]
                    except Exception:
                        pass
                if is_last:
                    break
            return artist, title, cover
    except Exception:
        return None


class SongToast(QtWidgets.QFrame):

    WIDTH = 300

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("SongToast")
        self.setStyleSheet(
            f"QFrame#SongToast {{ background: {COLOR_BG_CARD};"
            f"border: 1px solid {COLOR_BORDER_HOVER}; border-radius: 12px; }}")
        self.setFixedWidth(self.WIDTH)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        self.cover = QtWidgets.QLabel()
        self.cover.setFixedSize(self.WIDTH - 28, self.WIDTH - 28)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet(
            f"background: {COLOR_BG_CARD_INNER}; border-radius: 8px;"
            f"color: {COLOR_TEXT_MUTED}; font-size: 42px;")
        lay.addWidget(self.cover)

        self.lbl_now = QtWidgets.QLabel(i18n.tr("NOW PLAYING"))
        self.lbl_now.setFont(F(8))
        self.lbl_now.setAlignment(Qt.AlignHCenter)
        self.lbl_now.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        lay.addWidget(self.lbl_now)

        self.lbl_artist = QtWidgets.QLabel("")
        self.lbl_artist.setFont(F(11))
        self.lbl_artist.setAlignment(Qt.AlignHCenter)
        self.lbl_artist.setWordWrap(True)
        self.lbl_artist.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lay.addWidget(self.lbl_artist)

        self.lbl_title = QtWidgets.QLabel("")
        self.lbl_title.setFont(B(13))
        self.lbl_title.setAlignment(Qt.AlignHCenter)
        self.lbl_title.setWordWrap(True)
        self.lbl_title.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        lay.addWidget(self.lbl_title)

        self.effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.effect.setOpacity(0.0)
        self.setGraphicsEffect(self.effect)

        self._fade_in = None
        self._fade_out = None
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._start_fade_out)
        self.hide()

    def show_song(self, artist, title, cover_pix):
        if cover_pix is not None and not cover_pix.isNull():
            side = self.WIDTH - 28
            pm = cover_pix.scaled(side, side, Qt.KeepAspectRatio,
                                  Qt.SmoothTransformation)
            self.cover.setPixmap(pm)
            self.cover.setText("")
        else:
            self.cover.setPixmap(QtGui.QPixmap())
            self.cover.setText("♪")
        self.lbl_artist.setText(artist or i18n.tr("unknown artist"))
        self.lbl_title.setText(title or i18n.tr("unknown track"))
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()

        for anim in (self._fade_in, self._fade_out):
            if anim is not None:
                try:
                    anim.stop()
                except RuntimeError:
                    pass
        self._fade_in = None
        self._fade_out = None

        a = QPropertyAnimation(self.effect, b"opacity", self)
        a.setStartValue(self.effect.opacity())
        a.setEndValue(1.0)
        a.setDuration(650)
        a.setEasingCurve(QEasingCurve.InOutCubic)
        a.finished.connect(a.deleteLater)
        a.start()
        self._fade_in = a
        self._hold.start(5600)

    def _start_fade_out(self):
        a = QPropertyAnimation(self.effect, b"opacity", self)
        a.setStartValue(self.effect.opacity())
        a.setEndValue(0.0)
        a.setDuration(380)
        a.setEasingCurve(QEasingCurve.InCubic)
        a.finished.connect(self.hide)
        a.finished.connect(a.deleteLater)
        a.start()
        self._fade_out = a

    def dismiss(self):
        self._hold.stop()
        for anim in (self._fade_in, self._fade_out):
            if anim is not None:
                try:
                    anim.stop()
                except RuntimeError:
                    pass
        self._fade_in = None
        self._fade_out = None
        try:
            self.effect.setOpacity(0.0)
        except Exception:
            pass
        self.hide()

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        x = parent.width() - self.width() - 18
        y = max(70, (parent.height() - self.height()) // 2)
        self.move(x, y)


class ChenFrames:

    _cache = {}

    @classmethod
    def load(cls, path):
        frames = cls._cache.get(path)
        if frames is not None:
            return frames
        frames = []
        try:
            movie = QtGui.QMovie(path)
            if movie.isValid():
                movie.start()
                movie.stop()
                count = movie.frameCount()
                if count <= 0:
                    movie.jumpToFrame(0)
                    pm = movie.currentPixmap()
                    if not pm.isNull():
                        frames.append(pm)
                else:
                    for i in range(count):
                        movie.jumpToFrame(i)
                        pm = movie.currentPixmap()
                        if not pm.isNull():
                            frames.append(pm)
        except Exception:
            frames = []
        cls._cache[path] = frames
        return frames


class ChenStorm(QtWidgets.QWidget):

    SIZES = (58, 68, 80, 94, 110, 128, 148)

    def __init__(self, parent, gif_path, avoid_fn, max_alive=110):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setGeometry(parent.rect())
        self._avoid_fn = avoid_fn
        self._max = max_alive
        self._frames = ChenFrames.load(gif_path)
        self._scaled = {}
        self._sprites = []
        self._alpha = 1.0
        self._frame_ms = 60.0
        self._t0 = time.perf_counter()
        self._last = self._t0
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)
        self._spawner = QtCore.QTimer(self)
        self._spawner.timeout.connect(self._spawn)
        self._spawner.start(40)
        for _ in range(36):
            self._spawn(offset=random.randint(0, 1400))

    def _frames_for(self, width):
        cached = self._scaled.get(width)
        if cached is None:
            cached = [pm.scaledToWidth(width, Qt.SmoothTransformation)
                      for pm in self._frames]
            self._scaled[width] = cached
        return cached

    def _lane_blocked(self, y, h):
        try:
            rects = self._avoid_fn() if self._avoid_fn else []
        except Exception:
            rects = []
        for rect in rects:
            if y + h > rect.top() and y < rect.bottom():
                return True
        return False

    def _spawn(self, offset=0):
        if not self._frames or len(self._sprites) >= self._max:
            return
        width = random.choice(self.SIZES)
        frames = self._frames_for(width)
        if not frames:
            return
        h = frames[0].height()
        amp = random.uniform(5.0, 18.0) if random.random() < 0.55 else 0.0
        lo = int(4 + amp)
        hi = max(lo, int(self.height() - h - 4 - amp))
        y = random.randint(lo, hi)
        for _try in range(10):
            if not self._lane_blocked(y - amp, h + 2 * amp):
                break
            y = random.randint(lo, hi)
        x = self.width() + offset + random.randint(0, 40)
        self._sprites.append({
            "x": float(x), "y": int(y), "base_y": float(y),
            "w": width, "h": h,
            "frames": frames,
            "speed": random.uniform(230, 500),
            "phase": random.uniform(0.0, float(len(frames))),
            "bob_amp": amp,
            "bob_phase": random.uniform(0.0, 6.283),
            "bob_speed": random.uniform(0.9, 2.4),
        })

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.06, now - self._last)
        self._last = now
        dirty = QtCore.QRect()
        for sprite in list(self._sprites):
            old = QtCore.QRect(int(sprite["x"]), sprite["y"],
                               sprite["w"], sprite["h"])
            sprite["x"] -= sprite["speed"] * dt
            if sprite["bob_amp"] > 0.5:
                sprite["y"] = int(sprite["base_y"] + math.sin(
                    now * sprite["bob_speed"] + sprite["bob_phase"])
                    * sprite["bob_amp"])
            if sprite["x"] + sprite["w"] < -24:
                self._sprites.remove(sprite)
                continue
            new = QtCore.QRect(int(sprite["x"]), sprite["y"],
                               sprite["w"], sprite["h"])
            dirty = dirty.united(old).united(new)
        if not dirty.isEmpty():
            self.update(dirty)

    def paintEvent(self, ev):
        if not self._frames or not self._sprites:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        p.setOpacity(self._alpha)
        idx_base = (time.perf_counter() - self._t0) * 1000.0 / self._frame_ms
        for sprite in self._sprites:
            frames = sprite["frames"]
            if not frames:
                continue
            idx = int(idx_base + sprite["phase"]) % len(frames)
            p.drawPixmap(int(sprite["x"]), sprite["y"], frames[idx])
        p.end()

    def _set_alpha(self, v):
        self._alpha = max(0.0, min(1.0, float(v)))
        self.update()

    def dismiss(self, ms=340):
        self._spawner.stop()
        self._timer.stop()
        anim = QtCore.QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.valueChanged.connect(self._set_alpha)
        anim.finished.connect(self._shutdown)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._fade = anim

    def _shutdown(self):
        self._sprites = []
        self.hide()
        self.deleteLater()


class SmoothScrollArea(QtWidgets.QScrollArea):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anim = QtCore.QPropertyAnimation(
            self.verticalScrollBar(), b"value", self)
        self._anim.setDuration(380)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._target = 0

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        if not delta:
            super().wheelEvent(ev)
            return
        bar = self.verticalScrollBar()
        base = self._target if self._anim.state() == \
            QtCore.QAbstractAnimation.Running else bar.value()
        self._target = max(bar.minimum(),
                           min(bar.maximum(), base - delta * 0.45))
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(self._target)
        self._anim.start()
        ev.accept()


class LanguageDialog(QtWidgets.QDialog):

    def __init__(self, parent, current_code):
        super().__init__(parent)
        self.selected = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        pm = parent.grab()
        small = pm.scaled(max(1, pm.width() // 16), max(1, pm.height() // 16),
                          Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._bg = small.scaled(pm.size(), Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
        self.setGeometry(parent.geometry())

        card = QtWidgets.QFrame()
        card.setObjectName("LangCard")
        card.setStyleSheet(
            f"QFrame#LangCard {{ background: {COLOR_BG_CARD};"
            f"border: 1px solid {COLOR_BORDER_HOVER}; border-radius: 14px; }}")
        card.setFixedWidth(600)
        card.setMaximumHeight(680)
        self._card = card
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(22, 20, 22, 16)
        lay.setSpacing(8)

        title = QtWidgets.QLabel(i18n.tr("Language"))
        title.setFont(B(15))
        title.setStyleSheet(
            f"color: {COLOR_TEXT_WHITE}; background: transparent;")
        lay.addWidget(title)
        sub = QtWidgets.QLabel(
            i18n.tr("Pick a language - it applies immediately."))
        sub.setFont(F(10))
        sub.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED}; background: transparent;")
        lay.addWidget(sub)

        scroll = SmoothScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
            "QScrollBar:vertical { background: transparent; width: 10px;"
            "margin: 2px 2px 2px 0; }"
            "QScrollBar::handle:vertical { background: rgba(255, 255, 255, 40);"
            "border-radius: 4px; min-height: 30px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 70); }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }")
        inner = QtWidgets.QWidget()
        inner.setStyleSheet("background: transparent;")
        v = QtWidgets.QVBoxLayout(inner)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(6)
        for code, native in i18n.LANGUAGES:
            row = QtWidgets.QFrame()
            row.setObjectName("LangRow")
            row.setCursor(Qt.PointingHandCursor)
            row.setStyleSheet(
                "QFrame#LangRow { background: #1e1e24;"
                "border: 1px solid #2b2b34; border-radius: 8px; }"
                "QFrame#LangRow:hover { background: #2c2d38;"
                "border-color: #5a5d70; }")
            rh = QtWidgets.QHBoxLayout(row)
            rh.setContentsMargins(12, 8, 12, 8)
            rh.setSpacing(10)
            flag = QtWidgets.QLabel()
            fpix = flag_pixmap(code, 20)
            if fpix is not None:
                flag.setPixmap(fpix)
            else:
                flag.setText(i18n.FLAGS.get(code, ""))
                flag.setFont(QtGui.QFont("Segoe UI Emoji", 16))
            flag.setFixedSize(36, 24)
            flag.setAlignment(Qt.AlignCenter)
            flag.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            flag.setStyleSheet("background: transparent; border: none;")
            rh.addWidget(flag)
            name = QtWidgets.QLabel(native)
            name.setFont(B(11))
            name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            name.setStyleSheet(
                f"color: {COLOR_TEXT_WHITE}; background: transparent;"
                "border: none;")
            rh.addWidget(name)
            rh.addStretch(1)
            eng = QtWidgets.QLabel(i18n.ENGLISH_NAMES.get(code, ""))
            eng.setFont(F(9))
            eng.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            eng.setStyleSheet(
                f"color: {COLOR_TEXT_MUTED}; background: transparent;"
                "border: none;")
            rh.addWidget(eng)
            if code == current_code:
                cur = QtWidgets.QLabel(i18n.tr("CURRENT"))
                cur.setFont(B(8))
                cur.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                cur.setStyleSheet(
                    "color: #121212; background: #ffffff; border-radius: 4px;"
                    "padding: 2px 6px;")
                rh.addWidget(cur)
            v.addWidget(row)

            def pick(ev=None, c=code):
                self.selected = c
                self.accept()
            row.mousePressEvent = pick
        scroll.setWidget(inner)
        lay.addWidget(scroll, 1)

        cancel = HoverButton(i18n.tr("CANCEL"), fill=COLOR_BG_CARD_INNER,
                             hover=COLOR_BG_HOVER, radius=8, font=B(11),
                             height=36)
        cancel.setFixedWidth(140)
        cancel.clicked.connect(self.reject)
        lay.addWidget(cancel, 0, Qt.AlignRight)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def mousePressEvent(self, ev):
        try:
            local = self._card.mapFrom(self, ev.position().toPoint())
            if self._card.rect().contains(local):
                return
        except Exception:
            pass
        self.reject()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 150))
        p.end()

    def showEvent(self, ev):
        super().showEvent(ev)
        if getattr(self, "_opened", False):
            return
        self._opened = True
        self.setWindowOpacity(0.0)
        anim = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(220)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._fade = anim

    def _close_with(self, result):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        anim = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(160)
        anim.setStartValue(self.windowOpacity())
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.InCubic)
        anim.finished.connect(
            lambda: QtWidgets.QDialog.done(self, result))
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._close_anim = anim

    def accept(self):
        self._close_with(QtWidgets.QDialog.Accepted)

    def reject(self):
        self._close_with(QtWidgets.QDialog.Rejected)


class BlurConfirmDialog(QtWidgets.QDialog):

    def __init__(self, parent, title, message, confirm_text="OK"):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        pm = parent.grab()
        small = pm.scaled(max(1, pm.width() // 16), max(1, pm.height() // 16),
                          Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._bg = small.scaled(pm.size(), Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
        self.setGeometry(parent.geometry())

        card = QtWidgets.QFrame()
        card.setObjectName("ConfirmCard")
        card.setStyleSheet(
            f"QFrame#ConfirmCard {{ background: {COLOR_BG_CARD};"
            f"border: 1px solid {COLOR_BORDER_HOVER}; border-radius: 14px; }}")
        card.setFixedWidth(540)
        lay = QtWidgets.QVBoxLayout(card)
        lay.setContentsMargins(28, 24, 28, 22)
        lay.setSpacing(10)

        t = QtWidgets.QLabel(title)
        t.setFont(B(14))
        t.setStyleSheet(f"color: {COLOR_TEXT_WHITE}; background: transparent;")
        lay.addWidget(t)
        m = QtWidgets.QLabel(message)
        m.setFont(F(11))
        m.setWordWrap(True)
        m.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
        lay.addWidget(m)
        lay.addSpacing(8)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        cancel = HoverButton(i18n.tr("CANCEL"), fill=COLOR_BG_CARD_INNER,
                             hover=COLOR_BG_HOVER, radius=8, font=B(11),
                             height=38)
        cancel.setFixedWidth(140)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        ok = HoverButton(confirm_text, fill="#5a1f1f", hover="#7a2a2a",
                         text_color=COLOR_TEXT_WHITE, radius=8, font=B(11),
                         height=38)
        ok.setFixedWidth(160)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.drawPixmap(0, 0, self._bg)
        p.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 150))
        p.end()


class UiBridge(QtCore.QObject):
    progress = Signal(int, int)
    download_finished = Signal(int, list)
    download_failed = Signal(str)
    live_preview = Signal(str)
    log_entry = Signal(int, str)
    preview_results = Signal(int, int, list, str, bool, int, str)
    preview_prefetched = Signal(object)
    thumb_done = Signal(str, QtGui.QImage)
    thumb_failed = Signal(str)
    large_done = Signal(int, QtGui.QImage)
    large_failed = Signal(int)
    tag_results = Signal(str, object, object)
    multi_tag_results = Signal(list)
    update_checked = Signal(object)
    update_progress = Signal(int, int)
    update_downloaded = Signal(str)
    update_failed = Signal(str)
    gelbooru_test = Signal(bool, str)



class TabWrap(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.content = QtWidgets.QWidget(self)
        self.content.setStyleSheet("background: transparent;")
        self.effect = QtWidgets.QGraphicsOpacityEffect(self.content)
        self.effect.setOpacity(1.0)
        self.content.setGraphicsEffect(self.effect)
        self.fade_anim = None
        self.rise_anim = None

    def resizeEvent(self, ev):
        pad = 10
        self.content.setGeometry(0, pad, self.width(), max(0, self.height() - pad))
        super().resizeEvent(ev)

    def layout_box(self) -> QtWidgets.QVBoxLayout:
        if getattr(self, "_layout", None) is None:
            l = QtWidgets.QVBoxLayout(self.content)
            l.setContentsMargins(0, 0, 0, 0)
            l.setSpacing(0)
            self._layout = l
        return self._layout

    def snap_reveal_start(self):
        self.effect.setOpacity(0.0)

    def finish_all(self):
        for name in ("fade_anim", "rise_anim"):
            anim = getattr(self, name, None)
            if anim is not None:
                try:
                    anim.stop()
                except RuntimeError:
                    pass
                setattr(self, name, None)
        self.fade_anim = self.rise_anim = None
        self.effect.setOpacity(1.0)

    def fade(self, frm, to, duration, easing=QEasingCurve.OutCubic, done=None):
        a = QPropertyAnimation(self.effect, b"opacity", self)
        a.setStartValue(frm)
        a.setEndValue(to)
        a.setDuration(duration)
        a.setEasingCurve(easing)
        if done is not None:
            a.finished.connect(done)
        a.finished.connect(a.deleteLater)
        a.start()
        self.fade_anim = a
        return a

    def rise(self, dy=10, duration=240, easing=QEasingCurve.OutCubic):
        y_base = int(self.height() * 0 + 10)
        a = QPropertyAnimation(self.content, b"pos", self)
        a.setStartValue(QPoint(0, y_base + dy))
        a.setEndValue(QPoint(0, y_base))
        a.setDuration(duration)
        a.setEasingCurve(easing)
        a.finished.connect(a.deleteLater)
        a.start()
        self.rise_anim = a
        return a



def _entry(placeholder, h=36):
    w = QtWidgets.QLineEdit()
    w.setPlaceholderText(placeholder)
    w.setFixedHeight(h)
    w.setFont(F(12))
    w.setStyleSheet(
        f"QLineEdit {{ background: {COLOR_BG_INPUT};"
        f"border: 1px solid {COLOR_BORDER}; border-radius: 8px;"
        f"color: {COLOR_TEXT_WHITE};"
        f"selection-background-color: {COLOR_BORDER_HOVER}; }}"
        f"QLineEdit:focus {{ border-color: {COLOR_BORDER_HOVER}; }}"
        f"QLineEdit:disabled {{ background: {COLOR_BG_WINDOW};"
        f"color: {COLOR_TEXT_INACTIVE}; border-color: {COLOR_BORDER}; }}"
    )
    pal = w.palette()
    pal.setColor(QtGui.QPalette.PlaceholderText, qcolor(COLOR_TEXT_MUTED))
    w.setPalette(pal)
    return w


def _combo_style():
    return (
        f"QComboBox {{ background: {COLOR_BG_INPUT};"
        f"border: 1px solid #3d3f4c; border-radius: 8px;"
        f"color: {COLOR_TEXT_WHITE}; padding-left: 10px; }}"
        f"QComboBox:hover {{ border-color: #4f5162; }}"
        f"QComboBox::drop-down {{ border: none; width: 30px; }}"
        f"QComboBox::down-arrow {{ width: 12px; height: 12px; }}"
        f"QComboBox QAbstractItemView {{ background: {COLOR_BG_INPUT};"
        f"color: {COLOR_TEXT_WHITE}; border: 2px solid #4f5162;"
        f"border-radius: 8px; padding: 6px; outline: 0;"
        f"selection-background-color: #3a3c48;"
        f"selection-color: {COLOR_TEXT_WHITE}; }}"
        f"QComboBox QListView {{ background: {COLOR_BG_INPUT};"
        f"border: 2px solid #4f5162; border-radius: 8px; outline: 0; }}"
        f"QComboBox QAbstractItemView::item {{ min-height: 32px;"
        f"border-radius: 5px; padding-left: 9px; }}"
        f"QComboBox QAbstractItemView::item:hover {{"
        f"background: #34353f; }}"
        f"QComboBox QAbstractItemView::item:selected {{"
        f"background: #3a3c48; color: {COLOR_TEXT_WHITE}; }}"
    )


def _scroll_style():
    return (
        "QScrollArea { background: transparent; border: none; }"
        f"QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}"
        f"QScrollBar::handle:vertical {{ background: {COLOR_BORDER_HOVER};"
        "border-radius: 5px; min-height: 30px; }"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical"
        " { height: 0; }"
        f"QScrollBar::handle:vertical:hover {{ background: {COLOR_TEXT_MUTED}; }}"
    )


class PreviewPostCard(QtWidgets.QFrame):
    open_requested = Signal(object)
    toggle_requested = Signal(object)

    def __init__(self, post: dict, parent=None):
        super().__init__(parent)
        self.post = post
        self.selected = False
        self._hovered = False
        self._border_col = qcolor(COLOR_BORDER)
        self._border_anim = None
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(208, 236)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(4)
        self.thumb = QtWidgets.QLabel("Loading...")
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setFont(F(10))
        self.thumb.setFixedSize(180, 180)
        self.thumb.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        self.thumb.mousePressEvent = self._open
        v.addWidget(self.thumb, 0, Qt.AlignHCenter)

        score = post.get("score", 0)
        width = post.get("image_width", 0)
        height = post.get("image_height", 0)
        ext = (post.get("file_ext") or "?").upper()
        info = QtWidgets.QLabel(
            f"#{post.get('id')} · ★ {score} · {width}x{height} · {ext}")
        info.setFont(F(9))
        info.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        v.addWidget(info)

        site_label = (post.get("site_name") or "").upper()
        if site_label:
            self.badge = QtWidgets.QLabel(site_label, self.thumb)
            self.badge.setFont(B(8))
            self.badge.setStyleSheet(
                "background: rgba(0, 0, 0, 165);"
                f"color: {COLOR_TEXT_WHITE}; border-radius: 4px;"
                "padding: 1px 5px;")
            self.badge.adjustSize()
            self.badge.move(6, 6)
            self.badge.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.badge.raise_()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect().adjusted(0, 0, -1, -1)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(r), 10, 10)
        p.fillPath(path, qcolor(COLOR_BG_CARD_INNER))
        if self.selected:
            pen = QtGui.QPen(qcolor(COLOR_ACCENT), 2)
        else:
            pen = QtGui.QPen(self._border_col, 1)
        p.setPen(pen)
        p.drawPath(path)

    def _animate_border_to(self, col: QtGui.QColor):
        frm = self._border_col
        if self._border_anim is not None:
            try:
                self._border_anim.stop()
            except RuntimeError:
                pass
            self._border_anim = None
        a = QVariantAnimation(self)
        a.setStartValue(frm)
        a.setEndValue(col)
        a.setDuration(170)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(self._border_tick)
        a.finished.connect(a.deleteLater)
        a.start()
        self._border_anim = a

    def _border_tick(self, col):
        try:
            self._border_col = col
            self.update()
        except Exception:
            pass

    def _open(self, ev=None):
        self.open_requested.emit(self.post)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._open()

    def toggle(self):
        self.toggle_requested.emit(self.post)

    def enterEvent(self, e):
        self._hovered = True
        if not self.selected:
            self._animate_border_to(qcolor(COLOR_BORDER_HOVER))
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        if not self.selected:
            self._animate_border_to(qcolor(COLOR_BORDER))
        self.update()

    def set_image(self, img: QtGui.QImage):
        pix = QtGui.QPixmap.fromImage(img)
        self.thumb.setText("")
        self.thumb.setPixmap(pix)

    def set_failed(self):
        self.thumb.setPixmap(QtGui.QPixmap())
        self.thumb.setText("Preview\nunavailable")

    def set_selected(self, selected: bool):
        self.selected = selected
        self._animate_border_to(
            qcolor(COLOR_ACCENT) if selected else qcolor(COLOR_BORDER))
        self.update()



def _hamming64(a, b):
    return bin(a ^ b).count("1")


def load_credits_pool():
    folder = os.path.join(ASSETS_DIR, "credits")
    manifest = os.path.join(folder, "manifest.json")
    if not os.path.isfile(manifest):
        return [], [], []
    try:
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return [], [], []
    entries = []
    for item in data.get("gifs", []):
        path = os.path.join(folder, item.get("file", ""))
        if os.path.isfile(path):
            entry = dict(item)
            entry["path"] = path
            entries.append(entry)
    avoid_hashes = []
    for value in data.get("avoid_hashes", []):
        try:
            avoid_hashes.append(int(value, 16))
        except Exception:
            pass
    return entries, list(data.get("avoid_chars", [])), avoid_hashes


def pick_credits_gifs(entries, count=10, avoid_chars=(), avoid_hashes=()):
    pool = list(entries)
    random.shuffle(pool)
    picked = []
    used_chars = {str(c).lower() for c in avoid_chars}
    used_hashes = list(avoid_hashes)
    per_series = {}

    def take(entry, unique_char, series_cap, min_dist):
        char = str(entry.get("char") or "").lower()
        if unique_char and char in used_chars:
            return False
        try:
            h = int(entry.get("hash") or "0", 16)
        except Exception:
            return False
        if any(_hamming64(h, u) <= min_dist for u in used_hashes):
            return False
        if per_series.get(entry.get("series"), 0) >= series_cap:
            return False
        picked.append(entry)
        used_chars.add(char)
        used_hashes.append(h)
        key = entry.get("series")
        per_series[key] = per_series.get(key, 0) + 1
        return True

    passes = ((True, 2, 8), (True, 99, 4), (False, 99, 2))
    for unique_char, series_cap, min_dist in passes:
        for entry in pool:
            if len(picked) >= count:
                break
            if entry in picked:
                continue
            take(entry, unique_char, series_cap, min_dist)
    return picked


class CreditsDecor(QtWidgets.QWidget):

    SLOTS = [
        (0.128, 0.33, 165), (0.128, 0.58, 155), (0.128, 0.81, 145),
        (0.872, 0.33, 165), (0.872, 0.58, 155), (0.872, 0.81, 145),
        (0.270, 0.145, 105), (0.730, 0.145, 105),
        (0.330, 0.885, 100), (0.670, 0.885, 100),
    ]

    def __init__(self, parent, entries):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self._items = []
        self._movies = []
        for slot, entry in zip(self.SLOTS, entries):
            path = entry.get("path")
            if not path:
                continue
            movie = QtGui.QMovie(path, QtCore.QByteArray(), self)
            if not movie.isValid():
                continue
            image = QtGui.QImage(path)
            gw, gh = image.width(), image.height()
            if gw <= 0 or gh <= 0:
                continue
            size = slot[2]
            scale = min(size / float(gw), size / float(gh), 1.0)
            lw = max(1, int(gw * scale))
            lh = max(1, int(gh * scale))
            movie.setScaledSize(QtCore.QSize(lw, lh))
            label = QtWidgets.QLabel(self)
            label.setMovie(movie)
            label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            label.setStyleSheet("background: transparent;")
            label.setAlignment(Qt.AlignCenter)
            label.setFixedSize(lw, lh)
            movie.start()
            self._movies.append(movie)
            self._items.append((label, slot, lw, lh))
        self.setGeometry(parent.rect())
        self._place()
        parent.installEventFilter(self)

    def _place(self):
        w, h = self.width(), self.height()
        for label, (xf, yf, _size), lw, lh in self._items:
            x = int(xf * w - lw / 2.0)
            y = int(yf * h - lh / 2.0)
            label.move(max(0, x), max(0, y))

    def eventFilter(self, obj, ev):
        if obj is self.parentWidget() and ev.type() == QtCore.QEvent.Resize:
            self.setGeometry(self.parentWidget().rect())
            self._place()
        return False

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()


class DanbooruDownloaderApp(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("Danbooru Downloader")
        self.setWindowIcon(app_icon())
        self.resize(1360, 860)

        self._closing = False
        self._paused = False
        self.active_tab_index = 0

        self.is_running = False
        self.current_download_count = 0
        self._download_total_hint = None
        self._download_source = None

        self._img_executor = ThreadPoolExecutor(max_workers=4,
                                                thread_name_prefix="QtImg")
        self._thumb_cache = {}
        self._thumb_pending = set()
        self._preview_cards = {}
        self._preview_posts = []
        self._preview_page = 1
        self._preview_request_id = 0
        self._preview_next_raw = None
        self._preview_history = []
        self._preview_search_gen = 0
        self._preview_session = "preview"
        self._preview_cache = {}
        self._preview_cache_order = []
        self._prefetch_queued = set()
        self._prefetch_depth = 5
        self._selected_posts = {}
        self._large_preview_post = None
        self._large_request_id = 0
        self._overlay = None
        self._toasts = []
        self._update_info = None
        self._update_busy = False
        self._update_silent = False

        self.bridge = UiBridge()
        self._wire_bridge()

        handler = QueueLogHandler(self.bridge.log_entry.emit)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s", datefmt="%H:%M:%S"))
        logging.getLogger().addHandler(handler)
        logging.getLogger().setLevel(logging.INFO)

        self.cfg_data = {}
        self._config_path = CONFIG_FILE
        self.load_config()
        i18n.set_language(self.cfg_data.get("language", "en"))

        self._build_ui()
        i18n.translate_widgets(self)
        for b in self.tab_buttons:
            b._i18n_label = b.label
            b.label = i18n.tr(b.label)
        self._update_username_privacy()
        self._fit_credit_buttons()
        self.apply_config_to_ui()
        self.select_tab(0, immediate=True)
        self._init_tab_sound()
        self._init_toast_sounds()
        self._fit_to_screen()
        QTimer.singleShot(4200, lambda: self._check_updates(silent=True))


    def showEvent(self, ev):
        super().showEvent(ev)
        if os.name == "nt" and not getattr(self, "_dw_done", False):
            self._dw_done = True
            QTimer.singleShot(0, self._dw_setup)
        if not getattr(self, "_intro_done", False):
            self._intro_done = True
            self._play_intro()

    def _play_intro(self):
        try:
            import welcome
            if welcome.should_play():
                self._welcome_splash = welcome.WelcomeSplash(self)
                self._welcome_splash.start()
        except Exception:
            logging.getLogger().debug("welcome intro failed", exc_info=True)

    def _fit_to_screen(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        width = min(1720, max(1000, int(avail.width() * 0.86)))
        height = min(1080, max(680, int(avail.height() * 0.86)))
        width = min(width, avail.width())
        height = min(height, avail.height())
        self.resize(width, height)
        self.move(avail.x() + max(0, (avail.width() - width) // 2),
                  avail.y() + max(0, (avail.height() - height) // 2))

    def _dw_setup(self):
        try:
            hwnd = int(self.winId())
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                                style | WS_EX_APPWINDOW)
        except Exception:
            pass


    def _wire_bridge(self):
        b = self.bridge
        b.progress.connect(self._on_progress)
        b.download_finished.connect(self._on_download_finished)
        b.download_failed.connect(self._on_download_failed)
        b.live_preview.connect(self._on_live_preview)
        b.log_entry.connect(self._on_log)
        b.preview_results.connect(self._on_preview_results)
        b.preview_prefetched.connect(self._on_prefetched)
        b.thumb_done.connect(self._on_thumb_done)
        b.thumb_failed.connect(self._on_thumb_failed)
        b.large_done.connect(self._on_large_done)
        b.large_failed.connect(self._on_large_failed)
        b.tag_results.connect(self._on_tag_results)
        b.multi_tag_results.connect(self._on_multi_tag_results)
        b.update_checked.connect(self._on_update_checked)
        b.update_progress.connect(self._on_update_progress)
        b.update_downloaded.connect(self._on_update_downloaded)
        b.update_failed.connect(self._on_update_failed)
        b.gelbooru_test.connect(self._on_gelbooru_test)

    def wire_config_callbacks(self):
        config.ON_PREVIEW_CALLBACK = self.on_image_preview_callback
        config.ON_PROGRESS_CALLBACK = self.on_progress


    def _enable_drag(self, widget: QtWidgets.QWidget):
        widget.installEventFilter(self)
        widget._is_drag_zone = True

    def eventFilter(self, obj, ev):
        if getattr(obj, "_is_drag_zone", False):
            if ev.type() == QtCore.QEvent.MouseButtonPress and \
                    ev.button() in (Qt.LeftButton, Qt.RightButton):
                try:
                    local = obj.mapFromGlobal(ev.globalPosition().toPoint())
                    child = obj.childAt(local)
                except Exception:
                    return super().eventFilter(obj, ev)
                if child is None:
                    self.windowHandle().startSystemMove()
                    return True
        return super().eventFilter(obj, ev)


    def _build_ui(self):
        root = QtWidgets.QFrame(self)
        root.setObjectName("RootRoot")
        root.setStyleSheet(
            f"QFrame#RootRoot {{ background: {COLOR_BG_WINDOW};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 12px; }}")
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.addWidget(root)

        grid = QtWidgets.QGridLayout(root)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(4)
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        self.sidebar_frame = QtWidgets.QFrame()
        self.sidebar_frame.setObjectName("Sidebar")
        self.sidebar_frame.setFixedWidth(108)
        self.sidebar_frame.setStyleSheet(
            f"QFrame#Sidebar {{ background: {COLOR_BG_SIDEBAR};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}")
        grid.addWidget(self.sidebar_frame, 0, 0)
        self._enable_drag(self.sidebar_frame)

        sv = QtWidgets.QVBoxLayout(self.sidebar_frame)
        sv.setContentsMargins(6, 6, 6, 10)
        sv.setSpacing(8)
        logo = QtWidgets.QLabel()
        logo.setFixedHeight(70)
        logo.setStyleSheet(f"color: {COLOR_ACCENT}; background: transparent;")
        pix = load_icon("Konata.png", 58)
        if pix is not None:
            logo.setPixmap(pix)
            logo.setAlignment(Qt.AlignCenter)
        else:
            logo.setText("DANBOORU")
            logo.setFont(B(10))
            logo.setAlignment(Qt.AlignCenter)
        self._enable_drag(logo)
        sv.addWidget(logo)

        self.tab_buttons = []
        defs = [("DOWNLOADER", "Download.png"), ("PREVIEW", "preview.png"),
                ("CONSOLE", "Console.png"), ("TAG TOOLS", "Tag tools.png"),
                ("SETTINGS", "setting.png"), ("STATISTICS", "stats.png"),
                ("CREDITS", "Heart.png")]
        for i, (lab, ico) in enumerate(defs):
            btn = PillTabButton(i, lab, load_icon(ico, 24))
            btn.clicked.connect(self.select_tab)
            sv.addWidget(btn)
            self.tab_buttons.append(btn)
        sv.addStretch(1)

        main_col = QtWidgets.QWidget()
        main_col.setStyleSheet("background: transparent;")
        ml = QtWidgets.QGridLayout(main_col)
        ml.setContentsMargins(4, 0, 0, 0)
        ml.setSpacing(10)
        grid.addWidget(main_col, 0, 1)

        self.header_frame = QtWidgets.QFrame()
        self.header_frame.setObjectName("HeaderBar")
        self.header_frame.setFixedHeight(46)
        self.header_frame.setStyleSheet(
            f"QFrame#HeaderBar {{ background: {COLOR_BG_CARD};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}")
        ml.addWidget(self.header_frame, 0, 0)
        self._enable_drag(self.header_frame)

        hh = QtWidgets.QHBoxLayout(self.header_frame)
        hh.setContentsMargins(16, 7, 8, 7)
        hh.setSpacing(4)
        title = QtWidgets.QLabel("DANBOORU DOWNLOADER")
        title.setFont(B(11))
        title.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
        self._enable_drag(title)
        hh.addWidget(title)
        hh.addStretch(1)

        self.btn_open_dir = HoverButton("", radius=8, pix=load_icon("folder.png", 17),
                                        height=32)
        self.btn_open_dir.setFixedSize(36, 32)
        self.btn_open_dir.clicked.connect(self.open_download_folder)
        hh.addWidget(self.btn_open_dir)

        btn_min = HoverButton("—", text_color=COLOR_TEXT_MUTED, radius=8,
                              font=B(11), height=32)
        btn_min.setFixedSize(32, 32)
        btn_min.clicked.connect(self.showMinimized)
        hh.addWidget(btn_min)

        sep = QtWidgets.QFrame()
        sep.setFixedSize(1, 20)
        sep.setStyleSheet(f"background: {COLOR_BORDER}; border: none;")
        hh.addWidget(sep)

        btn_close = HoverButton("✕", hover="#662222", text_color=COLOR_RED,
                                radius=8, font=B(12), height=32)
        btn_close.setFixedSize(32, 32)
        btn_close.clicked.connect(self.close)
        hh.addWidget(btn_close)

        self.stack = QtWidgets.QStackedWidget()
        ml.addWidget(self.stack, 1, 0)
        self.pages = []
        for builder in (self._page_downloader, self._page_preview,
                        self._page_console, self._page_tag_tools,
                        self._page_settings, self._page_stats,
                        self._page_credits):
            wrap = TabWrap()
            builder(wrap)
            self.stack.addWidget(wrap)
            self.pages.append(wrap)

        self._size_grip = QtWidgets.QSizeGrip(root)
        self._size_grip.setFixedSize(16, 16)
        self._size_grip.setStyleSheet("background: transparent;")
        self._size_grip.raise_()

        self._apply_tooltips()

    def _apply_tooltips(self):
        def t(w, text):
            if w is not None:
                w.setToolTip(text)

        t(self.btn_open_dir, "Open the folder with your downloaded files")

        t(self.entry_tags, "Type your search tags here. Press Enter after each one")
        t(self.btn_check_tag, "Checks your tags and shows details in the Tag Tools tab")
        t(self.slider_limit, "How many posts to fetch per page (a page is one batch)")
        t(self.slider_max_pages, "How many pages to walk through in total")
        t(self.slider_max_downloads,
          "Stop after this many files are downloaded (0 = no limit)")
        t(self.slider_min_w, "Skip images narrower than this")
        t(self.slider_min_h, "Skip images shorter than this")
        t(self.slider_min_score, "Only save posts with at least this score")
        t(self.entry_save_base, "Where downloads go. Leave empty to use the default folder")
        t(self.btn_browse, "Pick a folder for the downloads")
        t(self.menu_folder_option,
          "How the download folder gets named:\n"
          "Tag Based = named after your tags (spaces instead of _)\n"
          "Custom Folder Name = your own name\n"
          "Default = danbooru_downloads")
        t(self.entry_custom_folder,
          "Your own folder name (used when the scheme = Custom Folder Name)")
        t(self.switch_resume, "Pick up where the last download left off")
        t(self.switch_save_progress,
          "Remember which files are already downloaded (JSON)")
        t(self.switch_save_txt,
          "Save each post's tags to a .txt file next to the download")
        t(self.btn_start, "Downloads posts that match your tags and settings")
        t(self.btn_stop, "Cancels the download. Files already saved stay saved.")
        t(self.btn_pause,
          "Pauses the download. The big button becomes RESUME, or press again.")
        t(self.btn_action_folder, "Open the folder with your downloaded files")

        t(self.entry_preview_tags, "Type tags to browse posts before downloading")
        t(self.btn_preview_search, "Loads posts from the enabled sources")
        t(self.btn_use_download_tags, "Copies your downloader tags into this search")
        t(self.btn_preview_prev, "Previous page of posts")
        t(self.btn_preview_next, "Next page of posts")
        t(self.btn_clear_selection, "Deselects all ticked posts")
        t(self.btn_select_page, "Ticks every post on this page")
        t(self.btn_download_selected, "Downloads every ticked post")

        t(self.btn_clear_console, "Erases the console text")
        t(self.btn_copy_logs, "Copies all console logs to the clipboard")
        t(self.switch_autoscroll, "Keeps the console scrolled to the newest line")
        t(self.btn_open_preview_current, "Open the currently shown preview image")

        t(self.entry_tool_tag, "Type a tag to look it up on Danbooru")
        t(self.btn_inspect, "Looks up the tag, checks typos and shows suggestions")
        t(self.entry_own_triggers, "Custom words that get added in front of every .txt captions file")
        t(self.entry_strip_tags, "Tags to delete from every .txt captions file")

        t(self.entry_username, "Your Danbooru username (optional, gives higher limits)")
        t(self.entry_api_key, "Your Danbooru API key (optional, gives higher limits)")
        t(self.btn_save_cfg, "Writes the settings to gui_config.json")
        t(self.btn_reload_cfg, "Re-loads the settings from gui_config.json")

        if self._overlay is not None:
            t(self._overlay_big_label, "Click a post in the grid to see it here")
            t(self._overlay_download_btn, "Downloads just this one post")
            t(self._overlay_select_btn, "Adds / removes this post from the download list")
            t(self._overlay_close_btn, "Close this preview window")

        t(self.credits_link, "Open @Acemoneyprod's GitHub profile")


    def _page_downloader(self, wrap):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        wrap.layout_box().addWidget(page)
        grid = QtWidgets.QGridLayout(page)
        grid.setContentsMargins(0, 0, 2, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        left = QtWidgets.QScrollArea()
        left.setWidgetResizable(True)
        left.setFrameShape(QtWidgets.QFrame.NoFrame)
        left.setStyleSheet(_scroll_style())
        left_body = QtWidgets.QWidget()
        left_body.setStyleSheet("background: transparent;")
        lbv = QtWidgets.QVBoxLayout(left_body)
        lbv.setContentsMargins(0, 0, 6, 4)
        lbv.setSpacing(12)
        left.setWidget(left_body)
        grid.addWidget(left, 0, 0)

        card_search = Card("Search & Query", "Tag filters & scope")
        lbv.addWidget(card_search)
        lbl_tag = QtWidgets.QLabel("SEARCH TAGS")
        lbl_tag.setFont(F(12))
        lbl_tag.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        card_search.body.addWidget(lbl_tag)
        irow = QtWidgets.QFrame()
        irow.setStyleSheet("background: transparent;")
        ih = QtWidgets.QHBoxLayout(irow)
        ih.setContentsMargins(0, 0, 0, 0)
        ih.setSpacing(8)
        self.entry_tags = TagChipInput(
            "Type a tag and press Enter...",
            blocked_fn=downloader.is_hard_blocked_tag_name)
        ih.addWidget(self.entry_tags, 1)
        self.btn_check_tag = HoverButton("CHECK", fill=COLOR_ACCENT,
                                         hover=COLOR_ACCENT_HOVER,
                                         text_color=COLOR_BG_WINDOW, radius=8,
                                         font=B(11), height=38)
        self.btn_check_tag.clicked.connect(self.check_active_tags)
        ih.addWidget(self.btn_check_tag, 0, Qt.AlignTop)
        card_search.body.addWidget(irow)
        self.slider_limit = _add_slider(
            card_search, "Limit Per Page", 20, 200, 200, 10, "posts",
            tip="How many posts to fetch per page (a page is one batch of posts)")
        self.slider_max_pages = _add_slider(
            card_search, "Max Pages to Fetch", 1, 50, 20, 1, "pages",
            tip="How many pages to walk through in total")
        self.slider_max_downloads = _add_slider(
            card_search, "Max Download Limit (0 = Unlimited)",
            0, 1000, 0, 25, "files",
            tip="Stop after this many files are downloaded (0 = no limit)")

        card_quality = Card("Dimensions & Criteria", "Image resolution & score")
        lbv.addWidget(card_quality)
        self.slider_min_w = _add_slider(card_quality, "Minimum Width", 0, 3840, 480, 60, "px",
            tip="Skip images narrower than this")
        self.slider_min_h = _add_slider(card_quality, "Minimum Height", 0, 3840, 480, 60, "px",
            tip="Skip images shorter than this")
        self.slider_min_score = _add_slider(card_quality, "Minimum Score", 0, 200, 0, 5, "pts",
            tip="Only save posts with at least this many likes (score)")
        lbv.addStretch(1)

        right = QtWidgets.QScrollArea()
        right.setWidgetResizable(True)
        right.setFrameShape(QtWidgets.QFrame.NoFrame)
        right.setStyleSheet(_scroll_style())
        right_body = QtWidgets.QWidget()
        right_body.setStyleSheet("background: transparent;")
        rbv = QtWidgets.QVBoxLayout(right_body)
        rbv.setContentsMargins(6, 0, 0, 4)
        rbv.setSpacing(12)
        right.setWidget(right_body)
        grid.addWidget(right, 0, 1)

        card_dir = Card("Save Destination", "File organization")
        rbv.addWidget(card_dir)
        lbl_base = QtWidgets.QLabel("BASE SAVE DIRECTORY")
        lbl_base.setFont(F(12))
        lbl_base.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        card_dir.body.addWidget(lbl_base)
        drow = QtWidgets.QFrame()
        drow.setStyleSheet("background: transparent;")
        dh = QtWidgets.QHBoxLayout(drow)
        dh.setContentsMargins(0, 0, 0, 0)
        dh.setSpacing(8)
        self.entry_save_base = _entry("Leave empty for default folder or browse...")
        dh.addWidget(self.entry_save_base, 1)
        self.btn_browse = HoverButton("BROWSE", radius=8, font=B(11), height=36)
        self.btn_browse.clicked.connect(self.browse_save_folder)
        dh.addWidget(self.btn_browse)
        card_dir.body.addWidget(drow)

        lbl_naming = QtWidgets.QLabel("FOLDER NAMING SCHEME")
        lbl_naming.setFont(F(12))
        lbl_naming.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        card_dir.body.addWidget(lbl_naming)
        self.menu_folder_option = AnchorCombo()
        self.menu_folder_option.addItems(["Tag Based Name", "Custom Folder Name",
                                          "Default (danbooru_downloads)"])
        self.menu_folder_option.setFont(F(12))
        self.menu_folder_option.setFixedHeight(36)
        self.menu_folder_option.setStyleSheet(_combo_style())
        self.menu_folder_option.currentTextChanged.connect(
            self.on_folder_option_changed)
        card_dir.body.addWidget(self.menu_folder_option)
        self.entry_custom_folder = _entry("Enter custom folder name...")
        card_dir.body.addWidget(self.entry_custom_folder)

        card_state = Card("State & Persistence", "Session control")
        rbv.addWidget(card_state)
        self.switch_resume = _add_switch(card_state, "Resume previous download", True,
            tip="Pick up where you left off next time you run the app")
        self.switch_save_progress = _add_switch(card_state,
                                                "Save progress file (JSON)", True,
            tip="Remember which files already downloaded, saved to a JSON file")
        self.switch_save_txt = _add_switch(card_state,
                                           "Save tags to .txt sidecar files", False,
            tip="Write each post s tags to a .txt file next to the download (for AI dataset captions)")
        rbv.addStretch(1)

        action_bar = QtWidgets.QFrame()
        action_bar.setObjectName("ActionBar")
        action_bar.setStyleSheet(
            f"QFrame#ActionBar {{ background: {COLOR_BG_CARD};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}")
        grid.addWidget(action_bar, 1, 0, 1, 2)
        abv = QtWidgets.QVBoxLayout(action_bar)
        abv.setContentsMargins(14, 12, 14, 10)
        abv.setSpacing(6)

        brow = QtWidgets.QFrame()
        brow.setStyleSheet("background: transparent;")
        bh = QtWidgets.QHBoxLayout(brow)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(8)
        self.btn_start = HoverButton("START DOWNLOAD", fill=COLOR_ACCENT,
                                     hover=COLOR_ACCENT_HOVER,
                                     text_color=COLOR_BG_WINDOW, radius=8,
                                     pix=load_icon("start download.png", 18),
                                     font=B(13), height=42)
        self.btn_start.clicked.connect(self.on_start_clicked)
        bh.addWidget(self.btn_start, 1)
        self.btn_stop = HoverButton("STOP", hover="#552222", text_color=COLOR_RED,
                                    radius=8, font=B(13), height=42,
                                    pix=tint(load_icon("trash.png", 18), COLOR_RED))
        self.btn_stop.clicked.connect(self.stop_download)
        self.btn_stop.setEnabled(False)
        bh.addWidget(self.btn_stop)
        self.btn_pause = HoverButton(" PAUSE", radius=8, font=B(12), height=42)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_pause.setEnabled(False)
        bh.addWidget(self.btn_pause)
        self.btn_action_folder = btn_folder = HoverButton(" OPEN FOLDER", radius=8, font=B(12), height=42,
                                 pix=load_icon("folder.png", 18))
        btn_folder.clicked.connect(self.open_download_folder)
        bh.addWidget(btn_folder)
        abv.addWidget(brow)

        self.progress_bar = GlowBar()
        abv.addWidget(self.progress_bar)

        self.lbl_action_status = QtWidgets.QLabel(i18n.tr("Ready to download."))
        self.lbl_action_status.setFont(F(12))
        self.lbl_action_status.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        abv.addWidget(self.lbl_action_status)

        self.counter = RollingCounter(lambda text: self.lbl_action_status.setText(text))

    def _page_preview(self, wrap):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        wrap.layout_box().addWidget(page)
        col = QtWidgets.QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(12)

        search_card = Card("Preview Search", "Browse posts before downloading")
        col.addWidget(search_card)
        srow = QtWidgets.QFrame()
        srow.setStyleSheet("background: transparent;")
        sh = QtWidgets.QHBoxLayout(srow)
        sh.setContentsMargins(0, 0, 0, 0)
        sh.setSpacing(8)
        self.entry_preview_tags = TagChipInput(
            "Type a tag and press Enter...",
            blocked_fn=downloader.is_hard_blocked_tag_name)
        sh.addWidget(self.entry_preview_tags, 1)
        self.btn_preview_search = HoverButton("SEARCH", fill=COLOR_ACCENT,
                                              hover=COLOR_ACCENT_HOVER,
                                              text_color=COLOR_BG_WINDOW,
                                              radius=8, font=B(11), height=38)
        self.btn_preview_search.clicked.connect(self._preview_search_clicked)
        sh.addWidget(self.btn_preview_search)
        self.btn_use_download_tags = btn_use = HoverButton("USE DOWNLOAD TAGS", radius=8, font=B(10), height=38)
        btn_use.clicked.connect(self.copy_download_tags_to_preview)
        sh.addWidget(btn_use)
        search_card.body.addWidget(srow)

        nav = QtWidgets.QFrame()
        nav.setStyleSheet("background: transparent;")
        nh = QtWidgets.QHBoxLayout(nav)
        nh.setContentsMargins(0, 0, 0, 0)
        nh.setSpacing(10)
        self.btn_preview_prev = HoverButton("‹ PREV", radius=8, font=B(11), height=30)
        self.btn_preview_prev.setEnabled(False)
        self.btn_preview_prev.clicked.connect(self._prev_page)
        nh.addWidget(self.btn_preview_prev)
        self.lbl_preview_page = QtWidgets.QLabel("Page 1")
        self.lbl_preview_page.setFont(F(11))
        self.lbl_preview_page.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        nh.addWidget(self.lbl_preview_page)
        self.btn_preview_next = HoverButton("NEXT ›", radius=8, font=B(11), height=30)
        self.btn_preview_next.setEnabled(False)
        self.btn_preview_next.clicked.connect(self._next_page)
        nh.addWidget(self.btn_preview_next)
        self.lbl_preview_status = QtWidgets.QLabel(
            "Enter tags and press SEARCH to browse posts.")
        self.lbl_preview_status.setFont(F(11))
        self.lbl_preview_status.setWordWrap(True)
        self.lbl_preview_status.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_preview_status.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        nh.addWidget(self.lbl_preview_status, 1)
        search_card.body.addWidget(nav)

        grid_card = Card("Posts", "Click a post to enlarge · tick to select")
        col.addWidget(grid_card, 1)
        self.preview_scroll = QtWidgets.QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.preview_scroll.setStyleSheet(_scroll_style())
        self._grid_holder = QtWidgets.QWidget()
        self._grid_holder.setStyleSheet("background: transparent;")
        self.preview_grid = QtWidgets.QGridLayout(self._grid_holder)
        self.preview_grid.setContentsMargins(4, 4, 8, 8)
        self.preview_grid.setSpacing(12)
        self.preview_grid.setAlignment(Qt.AlignTop)
        for cx in range(5):
            self.preview_grid.setColumnStretch(cx, 1)
        self.preview_scroll.setWidget(self._grid_holder)
        grid_card.body.addWidget(self.preview_scroll, 1)
        self.preview_empty_label = QtWidgets.QLabel(
            "No posts loaded yet.\nEnter tags and press SEARCH.")
        self.preview_empty_label.setAlignment(Qt.AlignCenter)
        self.preview_empty_label.setFont(F(12))
        self.preview_empty_label.setWordWrap(True)
        self.preview_empty_label.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        self.preview_grid.addWidget(self.preview_empty_label, 0, 0, 1, 5)

        prow = QtWidgets.QFrame()
        prow.setStyleSheet("background: transparent;")
        ph = QtWidgets.QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 6)
        self.lbl_preview_selection = QtWidgets.QLabel("0 " + i18n.tr("selected"))
        self.lbl_preview_selection.setFont(F(11))
        self.lbl_preview_selection.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        ph.addWidget(self.lbl_preview_selection)
        ph.addStretch(1)
        self.btn_clear_selection = HoverButton("CLEAR", radius=8, font=B(10),
                                               height=34)
        self.btn_clear_selection.clicked.connect(self.clear_preview_selection)
        ph.addWidget(self.btn_clear_selection)
        self.btn_select_page = HoverButton("SELECT PAGE", radius=8, font=B(10),
                                           height=34)
        self.btn_select_page.clicked.connect(self.select_all_preview_posts)
        ph.addWidget(self.btn_select_page)
        self.btn_download_selected = HoverButton(
            "DOWNLOAD SELECTED (0)", text_color=COLOR_TEXT_MUTED,
            radius=8, font=B(11), height=34)
        self.btn_download_selected.clicked.connect(
            self.download_selected_preview_posts)
        self.btn_download_selected.setEnabled(False)
        ph.addWidget(self.btn_download_selected)
        grid_card.body.addWidget(prow)

    def _page_console(self, wrap):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        wrap.layout_box().addWidget(page)
        grid = QtWidgets.QGridLayout(page)
        grid.setContentsMargins(0, 0, 2, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)

        term = Card("Live Console & Diagnostics", "Real-time stream")
        grid.addWidget(term, 0, 0)

        self.console_textbox = QtWidgets.QPlainTextEdit()
        self.console_textbox.setReadOnly(True)
        self.console_textbox.setMaximumBlockCount(MAX_CONSOLE_LINES)
        self.console_textbox.setFont(MONO(12))
        self.console_textbox.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.console_textbox.setStyleSheet(
            f"QPlainTextEdit {{ background: {COLOR_BG_WINDOW}; color: #c8c9dc;"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}")

        ctrl = QtWidgets.QFrame()
        ctrl.setStyleSheet("background: transparent;")
        ch = QtWidgets.QHBoxLayout(ctrl)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(6)
        self.btn_clear_console = btn_clear = HoverButton("Clear", font=B(11), height=28,
                                pix=load_icon("trash.png", 14))
        btn_clear.clicked.connect(self.console_textbox.clear)
        ch.addWidget(btn_clear)
        self.btn_copy_logs = btn_copy = HoverButton("Copy Logs", text_color=COLOR_TEXT_MUTED,
                               radius=8, font=B(11), height=28)
        btn_copy.clicked.connect(self.copy_logs)
        ch.addWidget(btn_copy)
        ch.addStretch(1)
        self.switch_autoscroll = ToggleSwitchWidget(True)
        lbl_auto = QtWidgets.QLabel("Auto-scroll")
        lbl_auto.setFont(F(12))
        lbl_auto.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        ch.addWidget(lbl_auto)
        ch.addWidget(self.switch_autoscroll)
        term.body.addWidget(ctrl)

        term.body.addWidget(self.console_textbox, 1)

        live = Card("Live Image Preview", "Latest post")
        grid.addWidget(live, 0, 1)
        frame = QtWidgets.QFrame()
        frame.setFixedHeight(300)
        frame.setStyleSheet(
            f"background: {COLOR_BG_WINDOW}; border: 1px solid {COLOR_BORDER};"
            "border-radius: 10px;")
        fl = QtWidgets.QVBoxLayout(frame)
        fl.setContentsMargins(8, 8, 8, 8)
        self.preview_label = QtWidgets.QLabel(
            "No downloads yet\nStart downloading to see live preview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setFont(F(12))
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        fl.addWidget(self.preview_label, 1)
        live.body.addWidget(frame, 1)

        self.lbl_preview_filename = QtWidgets.QLabel("Filename: —")
        self.lbl_preview_filename.setFont(B(12))
        self.lbl_preview_filename.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        live.body.addWidget(self.lbl_preview_filename)
        self.lbl_preview_details = QtWidgets.QLabel("Resolution: — | Size: —")
        self.lbl_preview_details.setFont(F(11))
        self.lbl_preview_details.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        live.body.addWidget(self.lbl_preview_details)
        self.btn_open_preview_current = btn_open_cur = HoverButton("Open in Default Viewer", radius=8,
                                   font=B(12), height=36)
        btn_open_cur.clicked.connect(self.open_current_preview_image)
        live.body.addWidget(btn_open_cur)
        self.current_preview_filepath = None

    def _page_tag_tools(self, wrap):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        wrap.layout_box().addWidget(page)
        grid = QtWidgets.QGridLayout(page)
        grid.setContentsMargins(0, 0, 2, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        lookup = Card("Tag Inspector",
                      "Check a tag, see its stats, copy suggestions",
                      fill=True)
        lookup.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                             QtWidgets.QSizePolicy.Policy.Expanding)
        grid.addWidget(lookup, 0, 0)

        lh = QtWidgets.QHBoxLayout()
        lh.setSpacing(8)
        self.entry_tool_tag = _entry("Type a tag, e.g. hatsune_miku ...", h=42)
        self.entry_tool_tag.returnPressed.connect(self.run_tag_lookup)
        lh.addWidget(self.entry_tool_tag, 1)
        self.btn_inspect = HoverButton(
            "CHECK", fill=COLOR_ACCENT, hover=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG_WINDOW, radius=8, font=B(11), height=42)
        self.btn_inspect.setFixedWidth(96)
        self.btn_inspect.clicked.connect(self.run_tag_lookup)
        lh.addWidget(self.btn_inspect)
        self.btn_clear_tag = HoverButton("CLEAR", radius=8,
                                         font=B(11), height=42)
        self.btn_clear_tag.setFixedWidth(92)
        self.btn_clear_tag.clicked.connect(self.clear_tag_tool)
        lh.addWidget(self.btn_clear_tag)
        lookup.body.addLayout(lh)

        hint = QtWidgets.QLabel(
            "Press Enter to check  -  click a suggestion to copy it.")
        hint.setFont(F(10))
        hint.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        lookup.body.addWidget(hint)

        quick_row = QtWidgets.QHBoxLayout()
        quick_row.setSpacing(6)
        qlbl = QtWidgets.QLabel("POPULAR")
        qlbl.setFont(F(9))
        qlbl.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        quick_row.addWidget(qlbl)
        for tag in ("hatsune_miku", "1girl", "solo", "long_hair", "smile",
                    "blue_eyes"):
            chip = HoverButton(tag, fill=COLOR_BG_CARD_INNER,
                               hover=COLOR_BG_HOVER, radius=6, font=F(9),
                               height=26)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(
                lambda _checked=False, tag=tag: self.quick_tag(tag))
            quick_row.addWidget(chip)
        quick_row.addStretch(1)
        lookup.body.addLayout(quick_row)

        self.tag_result_view = qt_widgets.TagResultView()
        lookup.body.addWidget(self.tag_result_view, 1)

        post = Card("Post-Processing & Triggers", "Manage .txt captions",
                    fill=True)
        post.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        grid.addWidget(post, 0, 1)
        for title, desc, placeholder, btn_text, handler in (
            ("1. SEARCH TAGS TO TRIGGERS",
             "Moves search tags to the beginning of all existing .txt files in "
             "the output directory.", None,
             "Apply Search Tags to Triggers", self.run_tags_to_triggers),
            ("2. ADD CUSTOM TRIGGER WORDS", None,
             "e.g. style_lora, high quality",
             "Prepend Custom Triggers to All TXT", self.run_add_own_triggers),
            ("3. STRIP UNWANTED TAGS FROM TXT", None,
             "e.g. watermark, text, signature, lowres",
             "Remove Tags from Existing TXT Files", self.run_strip_tags),
        ):
            lbl = QtWidgets.QLabel(title)
            lbl.setFont(B(12))
            lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
            post.body.addWidget(lbl)
            if desc:
                d = QtWidgets.QLabel(desc)
                d.setFont(F(11))
                d.setWordWrap(True)
                d.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
                post.body.addWidget(d)
            if placeholder:
                entry = _entry(placeholder, h=36)
                if title.startswith("2."):
                    self.entry_own_triggers = entry
                elif title.startswith("3."):
                    self.entry_strip_tags = entry
                post.body.addWidget(entry)
            btn = HoverButton(btn_text, radius=8, font=B(12), height=36)
            btn.clicked.connect(handler)
            post.body.addWidget(btn)
            post.body.addSpacing(6)
        post.body.addStretch(1)
        if not hasattr(self, "entry_own_triggers"):
            self.entry_own_triggers = _entry("", h=36)
        if not hasattr(self, "entry_strip_tags"):
            self.entry_strip_tags = _entry("", h=36)

    def _page_settings(self, wrap):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet(_scroll_style())
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        scroll.setWidget(page)
        wrap.layout_box().addWidget(scroll)
        grid = QtWidgets.QGridLayout(page)
        grid.setContentsMargins(0, 0, 2, 0)
        grid.setSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        acc = Card("DANBOORU CREDENTIALS", "API Authentication")
        acc.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                          QtWidgets.QSizePolicy.Policy.Expanding)
        grid.addWidget(acc, 0, 0)

        u = QtWidgets.QLabel("DANBOORU USERNAME")
        u.setFont(F(12))
        u.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        acc.body.addWidget(u)
        self.entry_username = _entry("Enter Danbooru username...", h=36)
        urow = QtWidgets.QWidget()
        urow.setStyleSheet("background: transparent;")
        uh = QtWidgets.QHBoxLayout(urow)
        uh.setContentsMargins(0, 0, 0, 0)
        uh.setSpacing(8)
        uh.addWidget(self.entry_username, 1)
        self.btn_reveal_user = HoverButton(
            "SHOW", fill=COLOR_BG_CARD_INNER, hover=COLOR_BG_HOVER,
            radius=8, font=B(10), height=36, pix=eye_icon(COLOR_TEXT_WHITE, 14),
            icon_size=14)
        self.btn_reveal_user.setFixedWidth(88)
        self.btn_reveal_user.setCursor(Qt.PointingHandCursor)
        self.btn_reveal_user.setToolTip(
            "The username is hidden while an API key is saved. "
            "Click to reveal it.")
        self.btn_reveal_user.clicked.connect(self.toggle_username_visibility)
        uh.addWidget(self.btn_reveal_user, 0)
        acc.body.addWidget(urow)

        krow = QtWidgets.QWidget()
        krow.setStyleSheet("background: transparent;")
        kh = QtWidgets.QHBoxLayout(krow)
        kh.setContentsMargins(0, 0, 0, 0)
        kh.setSpacing(8)
        k = QtWidgets.QLabel("DANBOORU API KEY")
        k.setFont(F(12))
        k.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        kh.addWidget(k)
        kh.addStretch(1)
        self.lbl_api_help = QtWidgets.QLabel(
            '<a href="https://danbooru.donmai.us/wiki_pages/help:api" '
            'style="color: %s; text-decoration: none;">%s</a>'
            % (COLOR_TEXT_MUTED, i18n.tr("How to get an API key")))
        self.lbl_api_help.setTextFormat(Qt.RichText)
        self.lbl_api_help.setOpenExternalLinks(True)
        self.lbl_api_help.setCursor(Qt.PointingHandCursor)
        self.lbl_api_help.setStyleSheet("background: transparent;")
        kh.addWidget(self.lbl_api_help)
        acc.body.addWidget(krow)
        self.entry_api_key = _entry("Enter API key...", h=36)
        self.entry_api_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.entry_api_key.textChanged.connect(self._on_api_key_changed)
        acc.body.addWidget(self.entry_api_key)

        lang_lbl = QtWidgets.QLabel("LANGUAGE")
        lang_lbl.setFont(F(12))
        lang_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        acc.body.addWidget(lang_lbl)
        self.btn_language = HoverButton(
            "  " + i18n.language_name(i18n.current_language()),
            fill=COLOR_BG_INPUT, hover=COLOR_BG_HOVER, radius=8,
            font=F(11), height=36, icon_size=20,
            pix=flag_pixmap(i18n.current_language(), 18))
        self.btn_language._pix_dy = 2
        self.btn_language.setToolTip("Change the app language")
        self.btn_language.clicked.connect(self._open_language_dialog)
        acc.body.addWidget(self.btn_language)

        self._username_revealed = False
        self._update_username_privacy()

        perf = Card("CONCURRENCY & PERFORMANCE", "Network tuning")
        perf.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        grid.addWidget(perf, 1, 0)
        self.slider_workers = _add_slider(perf, "Download Threads (Workers)",
                                          1, 16, 4, 1, "threads",
            tip="How many files download at the same time (more = faster, but harder on the server)")
        self.slider_rate_delay = _add_slider(perf, "Rate Limit Delay",
                                             0.1, 3.0, 1.0, 0.1, "sec",
                                             fmt="{:.1f} sec",
            tip="Short pause between downloads so the server isn t hammered")
        self.slider_timeout = _add_slider(perf, "Request Timeout",
                                          5, 60, 30, 5, "sec",
            tip="Give up on a slow server after this many seconds")

        cats = Card("TAG CATEGORIES IN FILENAME / TXT", "Metadata toggles")
        cats.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        grid.addWidget(cats, 0, 1)
        self.switch_tag_artist = _add_switch(cats, "Include Artist Tags", True,
            tip="Add the artist s name to the filename / tag txt file")
        self.switch_tag_character = _add_switch(cats, "Include Character Tags", True,
            tip="Add character names (e.g. konata) to the filename / tag txt file")
        self.switch_tag_copyright = _add_switch(cats, "Include Copyright Tags", True,
            tip="Add the series / franchise name (e.g. lucky star) to the filename / tag txt file")
        self.switch_tag_general = _add_switch(cats, "Include General Tags", True,
            tip="Add general tags (e.g. long_hair, smile) to the filename / tag txt file")
        self.switch_tag_meta = _add_switch(cats, "Include Meta Tags", True,
            tip="Add technical tags (e.g. highres, 1080p) to the filename / tag txt file")

        fmts = Card("ALLOWED FILE FORMATS", "Whitelist extensions")
        fmts.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        grid.addWidget(fmts, 1, 1)
        self.format_switches = {}
        fgrid = QtWidgets.QGridLayout()
        fgrid.setHorizontalSpacing(18)
        fgrid.setVerticalSpacing(0)
        for i, ext in enumerate(("jpg", "jpeg", "png", "gif",
                                 "webp", "bmp", "mp4", "webm")):
            row = QtWidgets.QWidget()
            row.setStyleSheet("background: transparent;")
            rh = QtWidgets.QHBoxLayout(row)
            rh.setContentsMargins(0, 3, 0, 3)
            rh.setSpacing(8)
            lbl = QtWidgets.QLabel("." + ext)
            lbl.setFont(F(11))
            lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
            rh.addWidget(lbl)
            rh.addStretch(1)
            sw = ToggleSwitchWidget(True)
            sw.setToolTip(f"Allow .{ext} files")
            rh.addWidget(sw)
            self.format_switches[ext] = sw
            fgrid.addWidget(row, i // 2, i % 2)
        fmts.body.addLayout(fgrid)
        fmts.body.addStretch(1)

        src = Card("SEARCH SOURCES", "Sites searched together")
        src.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                          QtWidgets.QSizePolicy.Policy.Preferred)
        grid.addWidget(src, 2, 0, 1, 2)
        self.source_switches = {}
        self.source_status_labels = {}
        for key in sites.SOURCE_ORDER:
            info = sites.SOURCE_INFO[key]
            row = QtWidgets.QFrame()
            row.setStyleSheet("background: transparent;")
            rh = QtWidgets.QHBoxLayout(row)
            rh.setContentsMargins(0, 3, 0, 3)
            rh.setSpacing(10)
            names = QtWidgets.QVBoxLayout()
            names.setContentsMargins(0, 0, 0, 0)
            names.setSpacing(0)
            name_lbl = QtWidgets.QLabel(info["name"])
            name_lbl.setFont(F(12))
            name_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
            names.addWidget(name_lbl)
            status_lbl = QtWidgets.QLabel("")
            status_lbl.setFont(F(9))
            status_lbl._i18n_dynamic = True
            names.addWidget(status_lbl)
            rh.addLayout(names)
            rh.addStretch(1)
            switch = ToggleSwitchWidget(bool(info["default"]))
            switch.toggled.connect(
                lambda _checked: self._update_source_statuses())
            rh.addWidget(switch)
            src.body.addWidget(row)
            self.source_switches[key] = switch
            self.source_status_labels[key] = status_lbl

        gel_row = QtWidgets.QFrame()
        gel_row.setStyleSheet("background: transparent;")
        gel = QtWidgets.QVBoxLayout(gel_row)
        gel.setContentsMargins(0, 8, 0, 0)
        gel.setSpacing(4)
        gel_title_row = QtWidgets.QWidget()
        gel_title_row.setStyleSheet("background: transparent;")
        gel_title_h = QtWidgets.QHBoxLayout(gel_title_row)
        gel_title_h.setContentsMargins(0, 0, 0, 0)
        gel_title_h.setSpacing(8)
        gel_title = QtWidgets.QLabel("GELBOORU CREDENTIALS")
        gel_title.setFont(F(11))
        gel_title.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        gel_title_h.addWidget(gel_title)
        gel_title_h.addStretch(1)
        self.lbl_gelbooru_help = QtWidgets.QLabel(
            '<a href="https://gelbooru.com/index.php?page=wiki&s=view&id=18780" '
            'style="color: %s; text-decoration: none;">%s</a>'
            % (COLOR_TEXT_MUTED, i18n.tr("How to get Gelbooru credentials")))
        self.lbl_gelbooru_help.setTextFormat(Qt.RichText)
        self.lbl_gelbooru_help.setOpenExternalLinks(True)
        self.lbl_gelbooru_help.setCursor(Qt.PointingHandCursor)
        self.lbl_gelbooru_help.setStyleSheet("background: transparent;")
        gel_title_h.addWidget(self.lbl_gelbooru_help)
        gel.addWidget(gel_title_row)
        self.entry_gelbooru_key = _entry("Enter Gelbooru API key...", h=34)
        self.entry_gelbooru_key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.entry_gelbooru_key.textChanged.connect(
            lambda _text: self._update_source_statuses())
        gel.addWidget(self.entry_gelbooru_key)
        self.entry_gelbooru_user = _entry("Enter Gelbooru user ID (number)...", h=34)
        self.entry_gelbooru_user.textChanged.connect(
            lambda _text: self._update_source_statuses())
        gel.addWidget(self.entry_gelbooru_user)
        test_row = QtWidgets.QWidget()
        test_row.setStyleSheet("background: transparent;")
        test_h = QtWidgets.QHBoxLayout(test_row)
        test_h.setContentsMargins(0, 0, 0, 0)
        test_h.addStretch(1)
        self.btn_test_gelbooru = HoverButton(
            "TEST", radius=8, font=B(9), height=30)
        self.btn_test_gelbooru.clicked.connect(self._test_gelbooru)
        test_h.addWidget(self.btn_test_gelbooru)
        gel.addWidget(test_row)
        src.body.addWidget(gel_row)

        src_note = QtWidgets.QLabel(
            "Sources are searched together. Duplicate images are hidden.")
        src_note.setFont(F(9))
        src_note.setWordWrap(True)
        src_note.setStyleSheet(
            f"color: {COLOR_TEXT_INACTIVE}; background: transparent;")
        src.body.addWidget(src_note)
        self._update_source_statuses()


        cfgbar = Card("SAVE CONFIGURATION", "Choose a config file")
        crow = QtWidgets.QFrame()
        crow.setStyleSheet("background: transparent;")
        ch = QtWidgets.QHBoxLayout(crow)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(6)
        self.btn_save_cfg = btn_save = HoverButton(
            "SAVE CONFIGURATION", fill=COLOR_ACCENT, hover=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG_WINDOW, radius=8, font=B(12), height=38)
        btn_save.clicked.connect(self.save_config)
        ch.addWidget(btn_save, 1)
        self.btn_reload_cfg = btn_reload = HoverButton(
            "RELOAD SAVED", radius=8, font=B(12), height=38,
            pix=load_icon("refresh.png", 16))
        btn_reload.clicked.connect(self.apply_config_to_ui)
        ch.addWidget(btn_reload)
        cfgbar.body.addWidget(crow)

        prow = QtWidgets.QWidget()
        prow.setStyleSheet("background: transparent;")
        ph = QtWidgets.QHBoxLayout(prow)
        ph.setContentsMargins(0, 0, 0, 0)
        ph.setSpacing(8)
        plbl = QtWidgets.QLabel("CONFIG FILE")
        plbl.setFont(F(10))
        plbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        ph.addWidget(plbl)
        self.config_combo = AnchorCombo()
        self.config_combo.setFont(F(10))
        self.config_combo.setFixedHeight(34)
        self.config_combo.setStyleSheet(_combo_style())
        self.config_combo.currentTextChanged.connect(self._on_config_selected)
        ph.addWidget(self.config_combo, 1)
        cfgbar.body.addWidget(prow)
        self.lbl_cfg_active = QtWidgets.QLabel("")
        self.lbl_cfg_active.setFont(F(9))
        self.lbl_cfg_active.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
        cfgbar.body.addWidget(self.lbl_cfg_active)

        note_row = QtWidgets.QWidget()
        note_row.setStyleSheet("background: transparent;")
        nh = QtWidgets.QHBoxLayout(note_row)
        nh.setContentsMargins(0, 6, 0, 0)
        nh.setSpacing(10)
        kimg = QtWidgets.QLabel()
        pm = QtGui.QPixmap(os.path.join(ASSETS_DIR, "images", "k_on_cry.png"))
        if not pm.isNull():
            kimg.setPixmap(pm.scaledToHeight(46, Qt.SmoothTransformation))
        kimg.setFixedWidth(60)
        kimg.setAlignment(Qt.AlignCenter)
        kimg.setStyleSheet("background: transparent;")
        nh.addWidget(kimg)
        note = QtWidgets.QLabel(
            "Languages other than English were translated with Google "
            "Translate - sorry for any grammatical mistakes.")
        note.setFont(F(9))
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {COLOR_TEXT_INACTIVE}; background: transparent;")
        nh.addWidget(note, 1)
        cfgbar.body.addWidget(note_row)

        if getattr(sys, "frozen", False):
            appcard = Card("Application", "Installed copy")
            appcard.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                  QtWidgets.QSizePolicy.Policy.Expanding)
            arow = QtWidgets.QWidget()
            arow.setStyleSheet("background: transparent;")
            ah = QtWidgets.QHBoxLayout(arow)
            ah.setContentsMargins(0, 0, 0, 0)
            ah.setSpacing(8)
            b_folder = HoverButton("APP FOLDER", radius=8,
                                   font=B(11), height=38,
                                   pix=load_icon("folder.png", 16))
            b_folder.clicked.connect(lambda: os.startfile(BASE_DIR))
            ah.addWidget(b_folder, 1)
            b_un = HoverButton("UNINSTALL", hover="#552222",
                               text_color=COLOR_RED, radius=8, font=B(11),
                               height=38,
                               pix=tint(load_icon("trash.png", 16), COLOR_RED))
            b_un.clicked.connect(self._confirm_uninstall)
            ah.addWidget(b_un, 1)
            appcard.body.addWidget(arow)
            appcard.body.addStretch(1)
            grid.addWidget(cfgbar, 3, 0)
            grid.addWidget(appcard, 3, 1)
        else:
            grid.addWidget(cfgbar, 3, 0, 1, 2)

        upd = Card("UPDATES", "Version and releases")
        upd.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                          QtWidgets.QSizePolicy.Policy.Preferred)
        self.lbl_update_version = QtWidgets.QLabel(
            i18n.tr("Current version") + ": v" + updater.APP_VERSION)
        self.lbl_update_version._i18n_dynamic = True
        self.lbl_update_version.setFont(F(11))
        self.lbl_update_version.setStyleSheet(
            f"color: {COLOR_TEXT_WHITE};")
        upd.body.addWidget(self.lbl_update_version)
        self.lbl_update_status = QtWidgets.QLabel(i18n.tr("Not checked yet."))
        self.lbl_update_status._i18n_dynamic = True
        self.lbl_update_status.setFont(F(10))
        self.lbl_update_status.setStyleSheet(
            f"color: {COLOR_TEXT_MUTED};")
        upd.body.addWidget(self.lbl_update_status)
        urow = QtWidgets.QWidget()
        urow.setStyleSheet("background: transparent;")
        uh = QtWidgets.QHBoxLayout(urow)
        uh.setContentsMargins(0, 0, 0, 0)
        uh.setSpacing(8)
        self.btn_update_check = HoverButton(
            "Check for updates", radius=8, font=B(10), height=36)
        self.btn_update_check.clicked.connect(
            lambda: self._check_updates(silent=False))
        uh.addWidget(self.btn_update_check)
        self.btn_update_install = HoverButton(
            "Update now", fill=COLOR_ACCENT, hover=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG_WINDOW, radius=8, font=B(11), height=36)
        self.btn_update_install.clicked.connect(self._download_update)
        self.btn_update_install.hide()
        uh.addWidget(self.btn_update_install)
        uh.addStretch(1)
        upd.body.addWidget(urow)
        grid.addWidget(upd, 4, 0, 1, 2)

        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 0)
        grid.setRowStretch(2, 0)
        grid.setRowStretch(3, 0)
        grid.setRowStretch(4, 0)
        grid.setRowStretch(5, 1)

        self._config_path = CONFIG_FILE
        self.refresh_config_profiles()



    def _stats_folder(self):
        try:
            base = self.entry_save_base.text().strip() or BASE_DIR
            idx = self.menu_folder_option.currentIndex()
            if idx == 1:
                name = self.entry_custom_folder.text().strip() \
                    or "custom_downloads"
                return os.path.join(base, name)
            if idx == 0:
                return base
            return os.path.join(base, "danbooru_downloads")
        except Exception:
            return os.path.join(BASE_DIR, "danbooru_downloads")

    def _page_stats(self, wrap):
        page = StatsPage(self._stats_folder)
        wrap.layout_box().addWidget(page)
        self.stats_page = page

    def _page_credits(self, wrap):
        page = QtWidgets.QWidget()
        page.setStyleSheet("background: transparent;")
        wrap.layout_box().addWidget(page)
        self.credits_page = page
        outer = QtWidgets.QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 2, 0)
        outer.setSpacing(12)

        card = Card("Note", "SFW stuff only, be gone gooners")
        card.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                           QtWidgets.QSizePolicy.Policy.Expanding)
        outer.addWidget(card, 1)
        card.body.addStretch(1)

        title = QtWidgets.QLabel("SFW DANBOORU DOWNLOADER")
        title.setFont(B(15))
        title.setAlignment(Qt.AlignHCenter)
        title.setStyleSheet(f"color: {COLOR_TEXT_WHITE}; background: transparent;")
        card.body.addWidget(title, 0, Qt.AlignHCenter)

        made = QtWidgets.QLabel("made by")
        made.setFont(F(10))
        made.setAlignment(Qt.AlignHCenter)
        made.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; background: transparent;")
        card.body.addWidget(made, 0, Qt.AlignHCenter)

        self.credits_link = QtWidgets.QLabel()
        self.credits_link.setTextFormat(Qt.RichText)
        self.credits_link.setOpenExternalLinks(True)
        self.credits_link.setText(
            '<a href="https://github.com/Acemoneyprod" '
            'style="color: %s; text-decoration: none;">@Acemoneyprod</a>'
            % COLOR_ACCENT)
        self.credits_link.setFont(B(14))
        self.credits_link.setAlignment(Qt.AlignHCenter)
        self.credits_link.setCursor(Qt.PointingHandCursor)
        self.credits_link.setStyleSheet("background: transparent;")
        link_pal = self.credits_link.palette()
        link_pal.setColor(QtGui.QPalette.Link, qcolor(COLOR_ACCENT))
        link_pal.setColor(QtGui.QPalette.LinkVisited, qcolor(COLOR_ACCENT_HOVER))
        self.credits_link.setPalette(link_pal)
        card.body.addWidget(self.credits_link, 0, Qt.AlignHCenter)

        assets_dir = ASSETS_DIR
        gifs = []
        if os.path.isdir(assets_dir):
            gifs = sorted(
                [f for f in os.listdir(assets_dir) if f.lower().endswith(".gif")],
                key=lambda f: (f.lower() != "credits.gif", f.lower()))
            if len(gifs) >= 2:
                gifs[0], gifs[1] = gifs[1], gifs[0]
        self._credits_movies = []
        if gifs:
            gif_row = QtWidgets.QFrame()
            gif_row.setStyleSheet("background: transparent;")
            gif_row_layout = QtWidgets.QHBoxLayout(gif_row)
            gif_row_layout.setContentsMargins(0, 0, 0, 0)
            gif_row_layout.setSpacing(16)
            gif_row_layout.setAlignment(Qt.AlignHCenter)
            for gif_name in gifs:
                gif_path = os.path.join(assets_dir, gif_name)
                movie = QtGui.QMovie(gif_path)
                if not movie.isValid():
                    continue
                first = QtGui.QImage(gif_path)
                gw, gh = first.width(), max(1, first.height())
                scale = min(230 / max(1, gw), 230 / gh, 1.0)
                movie.setScaledSize(QtCore.QSize(int(gw * scale),
                                                 int(gh * scale)))
                gif_label = QtWidgets.QLabel()
                gif_label.setMovie(movie)
                gif_label.setAlignment(Qt.AlignCenter)
                gif_label.setStyleSheet("background: transparent;")
                movie.start()
                self._credits_movies.append(movie)
                gif_row_layout.addWidget(gif_label, 0, Qt.AlignCenter)
            if self._credits_movies:
                card.body.addWidget(gif_row, 0, Qt.AlignHCenter)
        if not self._credits_movies:
            missing = QtWidgets.QLabel("(credits art not found)")
            missing.setFont(F(10))
            missing.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
            missing.setAlignment(Qt.AlignCenter)
            card.body.addWidget(missing, 0, Qt.AlignHCenter)

        self._credits_audio_path = None
        if os.path.isdir(assets_dir):
            flacs = [f for f in sorted(os.listdir(assets_dir))
                     if f.lower().endswith(".flac")]
            flacs = [f for f in flacs if "snd cursor" not in f.lower()]
            if flacs:
                self._credits_audio_path = os.path.join(assets_dir, flacs[0])
        self._credits_song = {"artist": "", "title": "", "cover": None}
        if self._credits_audio_path:
            meta = read_flac_metadata(self._credits_audio_path)
            if meta:
                artist, title, cover = meta
                cover_pix = None
                if cover:
                    pm = QtGui.QPixmap()
                    if pm.loadFromData(cover):
                        cover_pix = pm
                self._credits_song = {
                    "artist": artist or "",
                    "title": title or "",
                    "cover": cover_pix,
                }
            if not self._credits_song["title"]:
                base = os.path.splitext(
                    os.path.basename(self._credits_audio_path))[0]
                self._credits_song["title"] = re.sub(
                    r"^\s*\d+[\.\-\s]+\s*", "", base)
        self._song_toast = None
        self._credits_player = None
        self._chen_storm = None
        self.btn_click_me = HoverButton(
            "click me :3", fill=COLOR_BG_CARD_INNER, hover=COLOR_BG_HOVER,
            radius=8, font=B(12), height=38)
        self.btn_click_me.setFixedWidth(150)
        self.btn_click_me.clicked.connect(self._play_credits_audio)
        card.body.addWidget(self.btn_click_me, 0, Qt.AlignHCenter)

        self.btn_stop_music = HoverButton(
            " STOP MUSIC", hover="#552222", text_color=COLOR_RED,
            radius=8, font=B(11), height=32,
            pix=tint(load_icon("trash.png", 16), COLOR_RED))
        self.btn_stop_music.setFixedWidth(150)
        self.btn_stop_music.clicked.connect(self._stop_credits_audio)
        self.btn_stop_music.hide()
        card.body.addWidget(self.btn_stop_music, 0, Qt.AlignHCenter)

        card.body.addStretch(1)

        self._credits_decor = None
        try:
            entries, avoid_chars, avoid_hashes = load_credits_pool()
            if entries:
                picked = pick_credits_gifs(
                    entries, len(CreditsDecor.SLOTS),
                    avoid_chars=avoid_chars, avoid_hashes=avoid_hashes)
                if picked:
                    self._credits_decor = CreditsDecor(page, picked)
                    self._credits_decor.setGeometry(page.rect())
                    self._credits_decor.raise_()
        except Exception:
            logging.getLogger().debug("credits decor failed", exc_info=True)

    def _play_credits_audio(self):
        path = getattr(self, "_credits_audio_path", None)
        if not path or not os.path.exists(path):
            return
        try:
            if getattr(self, "_credits_player", None) is None:
                from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
                self._credits_player = QMediaPlayer(self)
                self._credits_audio_out = QAudioOutput(self)
                self._credits_audio_out.setVolume(0.45)
                self._credits_player.setAudioOutput(self._credits_audio_out)
                self._credits_player.playbackStateChanged.connect(
                    self._on_music_state)
            self._credits_player.setSource(QtCore.QUrl.fromLocalFile(path))
            self._credits_player.setPosition(0)
            self._credits_player.play()
            self.btn_stop_music.show()
        except Exception as e:
            logging.warning(f"Credits audio playback failed: {e}")

        try:
            if self._song_toast is None:
                self._song_toast = SongToast(self)
            song = getattr(self, "_credits_song", {})
            self._song_toast.show_song(song.get("artist"),
                                       song.get("title"),
                                       song.get("cover"))
        except Exception as e:
            logging.warning(f"Song popup failed: {e}")

        QTimer.singleShot(515, self._start_chen_storm)

    def _start_chen_storm(self):
        if getattr(self, "_chen_storm", None) is not None:
            return
        page = getattr(self, "credits_page", None)
        gif = os.path.join(ASSETS_DIR, "easter", "chen.gif")
        if page is None or not os.path.isfile(gif):
            return
        def avoid_rects():
            rects = []
            try:
                btn = getattr(self, "btn_stop_music", None)
                if btn is not None and btn.isVisible():
                    top_left = btn.mapTo(page, QtCore.QPoint(0, 0))
                    rects.append(QtCore.QRect(top_left, btn.size())
                                 .adjusted(-26, -26, 26, 26))
            except Exception:
                pass
            return rects
        try:
            self._chen_storm = ChenStorm(page, gif, avoid_rects)
            self._chen_storm.show()
            self._chen_storm.raise_()
        except Exception as e:
            logging.warning(f"Chen storm failed: {e}")
            self._chen_storm = None

    def _stop_chen_storm(self):
        storm = getattr(self, "_chen_storm", None)
        if storm is None:
            return
        self._chen_storm = None
        try:
            storm.dismiss()
        except Exception:
            pass

    def _on_music_state(self, state):
        try:
            from PySide6.QtMultimedia import QMediaPlayer
            stopped = (state == QMediaPlayer.PlaybackState.StoppedState)
        except Exception:
            stopped = False
        self.btn_stop_music.setVisible(not stopped)
        if stopped:
            self._stop_chen_storm()

    def _stop_credits_audio(self):
        player = getattr(self, "_credits_player", None)
        try:
            if player is not None:
                player.stop()
        except Exception:
            pass
        self.btn_stop_music.hide()
        self._stop_chen_storm()
        toast = getattr(self, "_song_toast", None)
        if toast is not None:
            toast.dismiss()



    def _init_tab_sound(self):
        self._tab_sound_effect = None
        self._tab_sound_player = None
        self._last_tab_sound = 0.0
        try:
            wav = os.path.join(ASSETS_DIR, "03 - SND Cursor.wav")
            if os.path.exists(wav):
                from PySide6.QtMultimedia import QSoundEffect
                effect = QSoundEffect(self)
                effect.setVolume(0.55)
                effect.setSource(QtCore.QUrl.fromLocalFile(wav))
                self._tab_sound_effect = effect
        except Exception:
            self._tab_sound_effect = None

    def _init_toast_sounds(self):
        self._toast_sounds = {}
        try:
            from PySide6.QtMultimedia import QSoundEffect
        except Exception:
            return
        volumes = {"toast_error.wav": 0.42, "toast_normal.wav": 0.7,
                   "toast.wav": 0.62}
        cache = {}
        for kind, name in (("error", "toast_error.wav"),
                           ("warning", "toast_error.wav"),
                           ("success", "toast_normal.wav"),
                           ("info", "toast.wav")):
            effect = cache.get(name)
            if effect is None:
                path = os.path.join(ASSETS_DIR, "sounds", name)
                if not os.path.isfile(path):
                    continue
                try:
                    effect = QSoundEffect(self)
                    effect.setSource(QtCore.QUrl.fromLocalFile(path))
                    effect.setVolume(volumes.get(name, 0.55))
                except Exception:
                    continue
                cache[name] = effect
            self._toast_sounds[kind] = effect

    def _play_tab_sound(self):
        try:
            now = time.perf_counter()
            if now - self._last_tab_sound < 0.10:
                return
            effect = self._tab_sound_effect
            if effect is not None:
                if effect.isPlaying():
                    effect.stop()
                effect.play()
                self._last_tab_sound = now
                return
            path = os.path.join(ASSETS_DIR, "03 - SND Cursor.flac")
            if not os.path.exists(path):
                path = os.path.join(BASE_DIR, "03 - SND Cursor.flac")
            if not os.path.exists(path):
                return
            if getattr(self, "_tab_sound_player", None) is None:
                from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
                self._tab_sound_player = QMediaPlayer(self)
                self._tab_sound_out = QAudioOutput(self)
                self._tab_sound_out.setVolume(0.55)
                self._tab_sound_player.setAudioOutput(self._tab_sound_out)
            self._tab_sound_player.setSource(QtCore.QUrl.fromLocalFile(path))
            self._tab_sound_player.setPosition(0)
            self._tab_sound_player.play()
            self._last_tab_sound = now
        except Exception:
            pass

    def select_tab(self, index, immediate=False):
        if index == self.active_tab_index and not immediate:
            return
        if not immediate:
            self._play_tab_sound()
        self.active_tab_index = index
        for btn in self.tab_buttons:
            btn.set_active(btn.index == index, animate=not immediate)

        old = self.pages[self.stack.currentIndex()]
        new = self.pages[index]
        old.finish_all()

        def transition():
            self.stack.setCurrentWidget(new)
            new.snap_reveal_start()
            new.rise(dy=7, duration=170)
            new.fade(0.0, 1.0, 170)
        if immediate:
            self.stack.setCurrentWidget(new)
            new.finish_all()
            return
        old.fade(1.0, 0.0, 60, easing=QEasingCurve.InCubic, done=transition)
        self._tab_fade = old.fade_anim


    def get_formats(self):
        if not hasattr(self, "format_switches"):
            return "jpg, jpeg, png, gif, webp, bmp, mp4, webm"
        return ", ".join(ext for ext, sw in self.format_switches.items()
                         if sw.isChecked())

    def set_formats(self, text):
        if not hasattr(self, "format_switches"):
            return
        wanted = {x.strip().lower() for x in
                  str(text or "").replace(",", " ").split() if x.strip()}
        if not wanted:
            wanted = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "mp4",
                      "webm"}
        for ext, sw in self.format_switches.items():
            sw.setChecked(ext in wanted)

    def refresh_config_profiles(self):
        if not hasattr(self, "config_combo"):
            return
        names = []
        try:
            for f in os.listdir(BASE_DIR):
                if f.lower().endswith(".json") and "config" in f.lower():
                    names.append(f)
        except Exception:
            pass
        if "gui_config.json" not in names:
            names.insert(0, "gui_config.json")
        names.sort(key=lambda n: (n.lower() != "gui_config.json", n.lower()))
        current = os.path.basename(getattr(self, "_config_path", CONFIG_FILE))
        self.config_combo.blockSignals(True)
        self.config_combo.clear()
        self.config_combo.addItems(names)
        if current in names:
            self.config_combo.setCurrentText(current)
        self.config_combo.blockSignals(False)
        if hasattr(self, "lbl_cfg_active"):
            self.lbl_cfg_active.setText("Active: " + current)

    def _on_config_selected(self, name):
        if not name:
            return
        path = os.path.join(BASE_DIR, name)
        if not os.path.isfile(path):
            return
        self._config_path = path
        if hasattr(self, "lbl_cfg_active"):
            self.lbl_cfg_active.setText("Active: " + name)
        self.apply_config_to_ui()

    def _fit_credit_buttons(self):
        try:
            for btn, font in ((self.btn_click_me, B(12)),
                              (self.btn_stop_music, B(11))):
                fm = QtGui.QFontMetrics(font)
                text = btn.text().strip()
                btn.setFixedWidth(max(150, fm.horizontalAdvance(text) + 60))
        except Exception:
            pass

    def apply_language(self, code):
        i18n.set_language(code)
        i18n.translate_widgets(self)
        for b in self.tab_buttons:
            if not hasattr(b, "_i18n_label"):
                b._i18n_label = b.label
            b.label = i18n.tr(b._i18n_label)
        self.btn_language.setText("  " + i18n.language_name(code))
        self.btn_language._pix = flag_pixmap(code, 18)
        self.btn_language.update()
        try:
            self.lbl_api_help.setText(
                '<a href="https://danbooru.donmai.us/wiki_pages/help:api" '
                'style="color: %s; text-decoration: none;">%s</a>'
                % (COLOR_TEXT_MUTED, i18n.tr("How to get an API key")))
        except Exception:
            pass
        self._update_username_privacy()
        self._update_source_statuses()
        self._fit_credit_buttons()
        try:
            self.lbl_update_version.setText(
                i18n.tr("Current version") + ": v" + updater.APP_VERSION)
        except Exception:
            pass
        try:
            self.stats_page.refresh(force=True)
        except Exception:
            pass
        for name in ("slider_limit", "slider_max_pages",
                     "slider_max_downloads", "slider_min_w", "slider_min_h",
                     "slider_min_score", "slider_workers", "slider_rate_delay",
                     "slider_timeout"):
            sl = getattr(self, name, None)
            if sl is not None and getattr(sl, "_sync_fn", None):
                try:
                    sl._sync_fn(sl.get())
                except Exception:
                    pass

    def _open_language_dialog(self):
        dlg = LanguageDialog(self, i18n.current_language())
        if dlg.exec() != QtWidgets.QDialog.Accepted or not dlg.selected:
            return
        code = dlg.selected
        if code == i18n.current_language():
            return
        i18n.set_language(code)
        self.apply_language(code)
        self.save_config(silent=True)
        try:
            data = {}
            if os.path.isfile(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            data["language"] = code
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass

    def _on_language_changed(self, index):
        if getattr(self, "_lang_guard", False):
            return
        try:
            code = i18n.LANGUAGES[index][0]
        except Exception:
            return
        if code == i18n.current_language():
            return
        i18n.set_language(code)
        self.save_config(silent=True)
        try:
            data = {}
            if os.path.isfile(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
            data["language"] = code
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
        except Exception:
            pass
        self._restart_app()

    def _restart_app(self):
        try:
            if getattr(sys, "frozen", False):
                args = [sys.executable]
            else:
                args = [sys.executable, os.path.abspath(sys.argv[0])]
                args += sys.argv[1:]
            os.execv(sys.executable, args)
        except Exception:
            self.show_toast(
                "Language",
                "Restart the app to apply the new language.", kind="info")

    def _set_update_status(self, text, color):
        try:
            self.lbl_update_status.setText(text)
            self.lbl_update_status.setStyleSheet(
                f"color: {color}; background: transparent;")
        except Exception:
            pass

    def _check_updates(self, silent=False):
        if self._update_busy:
            return
        self._update_busy = True
        self._update_silent = silent
        try:
            self.btn_update_check.setEnabled(False)
            self.btn_update_install.setEnabled(False)
            self._set_update_status(i18n.tr("Checking..."),
                                    COLOR_TEXT_MUTED)
        except Exception:
            pass

        def worker():
            try:
                info = updater.check_latest()
            except Exception as exc:
                info = {"error": str(exc)}
            try:
                self.bridge.update_checked.emit(info)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_checked(self, info):
        self._update_busy = False
        silent = self._update_silent
        try:
            self.btn_update_check.setEnabled(True)
        except Exception:
            pass
        if not info or info.get("error"):
            self._update_info = None
            try:
                self.btn_update_install.hide()
            except Exception:
                pass
            self._set_update_status(
                i18n.tr("Could not check for updates."), COLOR_TEXT_MUTED)
            if not silent:
                self.show_toast(i18n.tr("Updates"),
                                i18n.tr("Could not check for updates."),
                                kind="warning")
            return
        latest = info.get("version") or ""
        if updater.is_newer(latest):
            self._update_info = info
            try:
                self.btn_update_install.show()
                self.btn_update_install.setEnabled(True)
            except Exception:
                pass
            try:
                status = i18n.tr("Version %s is available.") % latest
            except Exception:
                status = "Version %s is available." % latest
            self._set_update_status(status, COLOR_WARN)
            try:
                message = i18n.tr(
                    "%s is ready. Open Settings to update.") % latest
            except Exception:
                message = "%s is ready. Open Settings to update." % latest
            self.show_toast(i18n.tr("Update available"), message,
                            kind="info", duration=8000)
        else:
            self._update_info = None
            try:
                self.btn_update_install.hide()
            except Exception:
                pass
            self._set_update_status(i18n.tr("You're up to date."),
                                    COLOR_SUCCESS)
            if not silent:
                self.show_toast(i18n.tr("Updates"),
                                i18n.tr("You're up to date."),
                                kind="success")

    def _download_update(self):
        info = self._update_info
        if not info:
            return
        url = info.get("installer")
        if not url:
            webbrowser.open(info.get("page") or updater.RELEASES_URL)
            return
        if self._update_busy:
            return
        self._update_busy = True
        try:
            self.btn_update_check.setEnabled(False)
            self.btn_update_install.setEnabled(False)
        except Exception:
            pass
        self._set_update_status(i18n.tr("Downloading update..."),
                                COLOR_TEXT_MUTED)

        def worker():
            try:
                path = updater.download_installer(
                    url,
                    progress=lambda done, total:
                    self.bridge.update_progress.emit(done, total))
                self.bridge.update_downloaded.emit(path)
            except Exception as exc:
                self.bridge.update_failed.emit(str(exc))

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_progress(self, done, total):
        text = i18n.tr("Downloading update...")
        if total:
            text += " %d%%" % int(done * 100 / total)
        self._set_update_status(text, COLOR_TEXT_MUTED)

    def _on_update_downloaded(self, path):
        self._set_update_status(i18n.tr("Starting installer..."),
                                COLOR_SUCCESS)
        QTimer.singleShot(500, lambda: self._run_update_installer(path))

    def _run_update_installer(self, path):
        try:
            updater.launch_installer(path)
        except Exception as exc:
            self._update_busy = False
            try:
                self.btn_update_check.setEnabled(True)
                self.btn_update_install.setEnabled(True)
            except Exception:
                pass
            self._set_update_status(i18n.tr("Update failed."),
                                    COLOR_DANGER)
            self.show_toast(i18n.tr("Update failed"), str(exc),
                            kind="error")
            return
        QTimer.singleShot(400, QtWidgets.QApplication.quit)

    def _on_update_failed(self, error):
        self._update_busy = False
        try:
            self.btn_update_check.setEnabled(True)
            self.btn_update_install.setEnabled(True)
        except Exception:
            pass
        self._set_update_status(i18n.tr("Update failed."), COLOR_DANGER)
        self.show_toast(i18n.tr("Update failed"), error, kind="error")

    def _confirm_uninstall(self):
        unins = os.path.join(BASE_DIR, "unins000.exe")
        dlg = BlurConfirmDialog(
            self, i18n.tr("Uninstall SFW Danbooru Downloader?"),
            i18n.tr("This removes the app and its files. Your downloaded images and "
                    "your config file are kept."), i18n.tr("UNINSTALL"))
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        if not os.path.isfile(unins):
            self.show_toast(
                "Uninstall",
                "The uninstaller was not found next to the app.",
                kind="warning")
            return
        try:
            cmd = ('timeout /t 2 /nobreak >nul & "%s" /VERYSILENT '
                   '/SUPPRESSMSGBOXES /NORESTART' % unins)
            subprocess.Popen(cmd, shell=True, cwd=BASE_DIR,
                             creationflags=0x08000000)
        except Exception as e:
            self.show_toast("Uninstall", str(e), kind="error")
            return
        QtWidgets.QApplication.quit()

    def load_config(self):
        self.cfg_data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    self.cfg_data = json.load(f)
            except Exception:
                pass

    def save_config(self, silent=False):
        data = {
            "username": self.entry_username.text().strip(),
            "api_key": self.entry_api_key.text().strip(),
            "limit_per_page": str(int(self.slider_limit.get())),
            "max_pages": str(int(self.slider_max_pages.get())),
            "max_download_pages": str(int(self.slider_max_downloads.get()))
            if self.slider_max_downloads.get() > 0 else "",
            "save_folder_base": self.entry_save_base.text().strip(),
            "folder_option": "custom" if "Custom" in self.menu_folder_option.currentText()
            else ("tags" if "Tag" in self.menu_folder_option.currentText()
                  else "danbooru_downloads"),
            "custom_folder_name": self.entry_custom_folder.text().strip(),
            "include_artist": self.switch_tag_artist.isChecked(),
            "include_character": self.switch_tag_character.isChecked(),
            "include_copyright": self.switch_tag_copyright.isChecked(),
            "include_general": self.switch_tag_general.isChecked(),
            "include_meta": self.switch_tag_meta.isChecked(),
            "min_width": str(int(self.slider_min_w.get())),
            "min_height": str(int(self.slider_min_h.get())),
            "workers": str(int(self.slider_workers.get())),
            "resume": self.switch_resume.isChecked(),
            "save_progress": self.switch_save_progress.isChecked(),
            "save_txt_tags": self.switch_save_txt.isChecked(),
            "formats": self.get_formats(),
            "language": i18n.current_language(),
            "sources": {
                key: switch.isChecked()
                for key, switch in self.source_switches.items()
            },
            "gelbooru_api_key": self.entry_gelbooru_key.text().strip(),
            "gelbooru_user_id": self.entry_gelbooru_user.text().strip(),
        }
        path = getattr(self, "_config_path", CONFIG_FILE)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4)
            self.cfg_data = data
            self.refresh_config_profiles()
            if not silent:
                self.show_toast(
                    "Config Saved",
                    "Configuration successfully saved to "
                    + os.path.basename(path) + "!", kind="success")
        except Exception as e:
            if not silent:
                self.show_toast("Save Error",
                                f"Could not save config: {e}", kind="error")

    def apply_config_to_ui(self):
        path = getattr(self, "_config_path", CONFIG_FILE)
        d = {}
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8-sig") as f:
                    d = json.load(f)
            except Exception:
                d = {}
        self.cfg_data = d
        self.entry_tags.set_line("")
        self.entry_preview_tags.set_line("")
        self.slider_limit.set_with_sync(int(d.get("limit_per_page", 200)))
        self.slider_max_pages.set_with_sync(int(d.get("max_pages", 20)) or 20)
        max_dl = str(d.get("max_download_pages", ""))
        self.slider_max_downloads.set_with_sync(int(max_dl) if max_dl.isdigit() else 0)
        self.entry_save_base.clear()
        self.entry_save_base.insert(d.get("save_folder_base", ""))
        opt = d.get("folder_option", "tags")
        self.menu_folder_option.setCurrentText(
            "Tag Based Name" if opt == "tags"
            else ("Default (danbooru_downloads)" if opt == "danbooru_downloads"
                  else "Custom Folder Name"))
        self.entry_custom_folder.clear()
        self.entry_custom_folder.insert(d.get("custom_folder_name", "my_downloads"))
        self.slider_min_w.set_with_sync(int(d.get("min_width", 480)))
        self.slider_min_h.set_with_sync(int(d.get("min_height", 480)))
        self.slider_workers.set_with_sync(int(d.get("workers", 4)))
        self.switch_resume.setChecked(bool(d.get("resume", True)))
        self.switch_save_progress.setChecked(bool(d.get("save_progress", True)))
        self.switch_save_txt.setChecked(bool(d.get("save_txt_tags", False)))
        self.switch_tag_artist.setChecked(bool(d.get("include_artist", True)))
        self.switch_tag_character.setChecked(bool(d.get("include_character", True)))
        self.switch_tag_copyright.setChecked(bool(d.get("include_copyright", True)))
        self.switch_tag_general.setChecked(bool(d.get("include_general", True)))
        self.switch_tag_meta.setChecked(bool(d.get("include_meta", True)))
        self.entry_username.clear()
        self.entry_username.insert(d.get("username", ""))
        self.entry_api_key.clear()
        self.entry_api_key.insert(d.get("api_key", ""))
        self.entry_gelbooru_key.clear()
        self.entry_gelbooru_key.insert(d.get("gelbooru_api_key", ""))
        self.entry_gelbooru_user.clear()
        self.entry_gelbooru_user.insert(d.get("gelbooru_user_id", ""))
        source_values = d.get("sources") or {}
        for key, switch in self.source_switches.items():
            switch.setChecked(bool(source_values.get(
                key, sites.DEFAULT_SOURCES.get(key, False))))
        self._update_source_statuses()
        self.set_formats(d.get("formats",
                               "jpg, jpeg, png, gif, webp, bmp, mp4, webm"))
        self.on_folder_option_changed(self.menu_folder_option.currentText())
        self._username_revealed = False
        self._update_username_privacy()
        if hasattr(self, "lbl_cfg_active"):
            self.lbl_cfg_active.setText(
                "Active: " + os.path.basename(path))

    def on_folder_option_changed(self, choice):
        self.entry_custom_folder.setEnabled("Custom" in choice)


    def _api_connected(self):
        return bool(self.entry_api_key.text().strip())

    def _update_username_privacy(self):
        connected = self._api_connected()
        self.btn_reveal_user.setVisible(connected)
        if not connected:
            self._username_revealed = False
            self.entry_username.setEchoMode(QtWidgets.QLineEdit.Normal)
            self.btn_reveal_user.setText(i18n.tr("SHOW"))
            return
        revealed = bool(getattr(self, "_username_revealed", False))
        self.entry_username.setEchoMode(
            QtWidgets.QLineEdit.Normal if revealed
            else QtWidgets.QLineEdit.Password)
        self.btn_reveal_user.setText(
            i18n.tr("HIDE") if revealed else i18n.tr("SHOW"))
        try:
            fm = QtGui.QFontMetrics(B(10))
            self.btn_reveal_user.setFixedWidth(
                max(88, fm.horizontalAdvance(self.btn_reveal_user.text()) + 50))
        except Exception:
            pass
        self.btn_reveal_user.setToolTip(
            i18n.tr("Hide the username again.") if revealed else
            i18n.tr("The username is hidden while an API key is saved. "
                    "Click to reveal it."))

    def toggle_username_visibility(self):
        self._username_revealed = not bool(
            getattr(self, "_username_revealed", False))
        self._update_username_privacy()

    def _on_api_key_changed(self, *_):
        self._username_revealed = False
        self._update_username_privacy()


    def apply_ui_to_downloader_config(self, tags_override=None):
        user_tags = self.entry_tags.get().strip()
        config.TAGS = tags_override if tags_override is not None else user_tags
        config.LIMIT_PER_PAGE = int(self.slider_limit.get())
        config.MAX_PAGES = int(self.slider_max_pages.get())
        max_dl = int(self.slider_max_downloads.get())
        config.MAX_DOWNLOADS = max_dl if max_dl > 0 else None
        base_val = self.entry_save_base.text().strip()
        config.SAVE_FOLDER_BASE = base_val if base_val else \
            os.path.join(BASE_DIR, "danbooru_downloads")
        f_opt = self.menu_folder_option.currentText()
        if "Custom" in f_opt:
            config.SAVE_FOLDER_NAME_OPTION = "custom"
        elif "Tag" in f_opt:
            config.SAVE_FOLDER_NAME_OPTION = "tags"
        else:
            config.SAVE_FOLDER_NAME_OPTION = "danbooru_downloads"
        config.SAVE_FOLDER_CUSTOM_NAME = self.entry_custom_folder.text().strip()
        config.TAG_FOLDER_SPACES = True
        config.ALLOWED_RATINGS = {"g"}
        config.MIN_IMAGE_WIDTH = int(self.slider_min_w.get())
        config.MIN_IMAGE_HEIGHT = int(self.slider_min_h.get())
        score = int(self.slider_min_score.get())
        config.MIN_SCORE = score if score > 0 else None
        config.MAX_WORKERS = int(self.slider_workers.get())
        config.RATE_LIMIT_DELAY = float(self.slider_rate_delay.get())
        config.REQUEST_TIMEOUT = int(self.slider_timeout.get())
        config.RESUME_DOWNLOAD = self.switch_resume.isChecked()
        config.SAVE_PROGRESS = self.switch_save_progress.isChecked()
        config.SAVE_TXT_TAGS = self.switch_save_txt.isChecked()
        config.INCLUDE_ARTIST_TAGS = self.switch_tag_artist.isChecked()
        config.INCLUDE_CHARACTER_TAGS = self.switch_tag_character.isChecked()
        config.INCLUDE_COPYRIGHT_TAGS = self.switch_tag_copyright.isChecked()
        config.INCLUDE_GENERAL_TAGS = self.switch_tag_general.isChecked()
        config.INCLUDE_META_TAGS = self.switch_tag_meta.isChecked()
        config.USERNAME = self.entry_username.text().strip()
        config.API_KEY = self.entry_api_key.text().strip()
        config.SOURCES = {
            key: switch.isChecked()
            for key, switch in self.source_switches.items()
        }
        config.GELBOORU_API_KEY = self.entry_gelbooru_key.text().strip()
        config.GELBOORU_USER_ID = self.entry_gelbooru_user.text().strip()
        raw_formats = self.get_formats()
        if raw_formats:
            config.ALLOWED_EXTENSIONS = {
                ext.strip().lstrip('.').lower()
                for ext in raw_formats.split(',') if ext.strip()}
        config.SAVE_FOLDER = create_save_folder()
        config.CANCELLED = False


    def _enabled_source_keys(self):
        return [
            key for key, switch in getattr(self, "source_switches", {}).items()
            if switch.isChecked()
        ]


    def _update_source_statuses(self):
        switches = getattr(self, "source_switches", None)
        if not switches:
            return
        key_text = (self.entry_gelbooru_key.text().strip()
                    if hasattr(self, "entry_gelbooru_key") else "")
        user_text = (self.entry_gelbooru_user.text().strip()
                     if hasattr(self, "entry_gelbooru_user") else "")
        for key, switch in switches.items():
            label = self.source_status_labels[key]
            if not switch.isChecked():
                text, color = "Off", COLOR_TEXT_INACTIVE
            elif sites.SOURCE_INFO[key]["needs_key"] and not (
                    key_text and user_text):
                text, color = "Needs API key", COLOR_WARN
            else:
                text, color = "Ready", COLOR_SUCCESS
            label.setText(i18n.tr(text))
            label.setStyleSheet(
                f"color: {color}; background: transparent;")


    def _test_gelbooru(self):
        api_key = self.entry_gelbooru_key.text().strip()
        user_id = self.entry_gelbooru_user.text().strip()
        if not api_key or not user_id:
            self.show_toast(
                "Gelbooru",
                "Enter the API key and user ID first.",
                kind="warning")
            return
        self.btn_test_gelbooru.setEnabled(False)
        self.btn_test_gelbooru.setText(i18n.tr("TESTING..."))
        threading.Thread(
            target=self._test_gelbooru_worker,
            args=(api_key, user_id), daemon=True).start()


    def _test_gelbooru_worker(self, api_key, user_id):
        try:
            ok, message = sites.test_gelbooru(api_key, user_id)
        except Exception as exc:
            ok, message = False, str(exc)
        self.bridge.gelbooru_test.emit(bool(ok), str(message))


    def _on_gelbooru_test(self, ok, message):
        self.btn_test_gelbooru.setEnabled(True)
        self.btn_test_gelbooru.setText(i18n.tr("TEST"))
        self.show_toast(
            "Gelbooru", message,
            kind="success" if ok else "error")


    def start_download(self):
        if self.is_running:
            return
        self.entry_tags.commit()
        tags = self.entry_tags.get().strip()
        if not tags:
            self.show_toast(
                "Empty Query",
                "Please specify search tags before starting!",
                kind="error")
            return
        if not self._enabled_source_keys():
            self.show_toast(
                "No Sources",
                "Enable at least one search source in Settings.",
                kind="warning")
            return
        if not downloader.sanitize_sfw_query(tags):
            self.show_toast(
                "Blocked Tags",
                "All of those tags are permanently blocked.", kind="warning")
            return
        self.apply_ui_to_downloader_config()
        self.is_running = True
        self.current_download_count = 0
        self._paused = False
        config.PAUSED = False
        self._download_source = "tags"
        self._download_total_hint = None
        self._set_download_running(True, "Starting download threads...")
        threading.Thread(target=self._download_worker_tags, daemon=True).start()

    def on_start_clicked(self):
        if self.is_running and self._paused:
            self.resume_download()
        elif not self.is_running:
            self.start_download()

    def toggle_pause(self):
        if getattr(self, "_paused", False):
            self.resume_download()
        else:
            self.pause_download()

    def pause_download(self):
        if not self.is_running or getattr(self, "_paused", False):
            return
        self._paused = True
        config.PAUSED = True
        self.btn_pause.setText(" RESUME")
        self.btn_start.setText("RESUME DOWNLOAD")
        self.btn_start.setEnabled(True)
        self.progress_bar.set_running(False)
        self.counter.stop()
        self._status_color(COLOR_WARN)
        self.lbl_action_status.setText(
            i18n.tr("Paused - press RESUME to continue the download."))

    def resume_download(self):
        if not getattr(self, "_paused", False):
            return
        self._paused = False
        config.PAUSED = False
        self.btn_pause.setText(" PAUSE")
        self.btn_start.setText("DOWNLOADING...")
        self.btn_start.setEnabled(False)
        self.progress_bar.set_running(True)
        self._status_color(COLOR_TEXT_WHITE)
        self.lbl_action_status.setText(i18n.tr("Resumed downloading..."))

    def _download_worker_tags(self):
        try:
            total, failed = downloader.download_images()
            self.bridge.download_finished.emit(int(total), list(failed))
        except Exception as e:
            logging.error(f"Download error: {e}")
            self.bridge.download_failed.emit(str(e))

    def _download_worker_selected(self, posts):
        try:
            total, failed = downloader.download_posts(list(posts))
            self.bridge.download_finished.emit(int(total), list(failed))
        except Exception as e:
            logging.error(f"Selected download error: {e}")
            self.bridge.download_failed.emit(str(e))

    def _set_download_running(self, running, status_text=""):
        if running:
            self.btn_start.setEnabled(False)
            self.btn_start.setText("DOWNLOADING...")
            self.btn_stop.setText("CANCEL")
            self.btn_stop._text_color = qcolor(COLOR_TEXT_WHITE)
            self.btn_stop._fill = qcolor("#4d1b1b")
            self.btn_stop._hover = qcolor("#6b2626")
            self.btn_stop._pix = tint(load_icon("trash.png", 18), COLOR_RED)
            self.btn_stop.setEnabled(True)
            self.btn_stop.update()
            self.btn_pause.setEnabled(True)
            self.btn_pause.setText(" PAUSE")
            self.btn_download_selected.setEnabled(False)
            if not getattr(self, "_paused", False):
                self.progress_bar.set_instant(0.0)
                self.progress_bar.set_running(True)
                self.counter.snap(0)
            self._status_color(COLOR_TEXT_WHITE)
            self.lbl_action_status.setText(status_text)
        else:
            self.btn_start.setEnabled(True)
            self.btn_start.setText("START DOWNLOAD")
            self.btn_stop.setEnabled(False)
            self.btn_stop.setText("STOP")
            self.btn_stop._text_color = qcolor(COLOR_RED)
            self.btn_stop._fill = qcolor(COLOR_BG_INPUT)
            self.btn_stop._hover = qcolor("#552222")
            self.btn_stop._pix = tint(load_icon("trash.png", 18), COLOR_RED)
            self.btn_stop.update()
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText(" PAUSE")
            self._paused = False
            config.PAUSED = False
            self._refresh_selection_buttons()

    def stop_download(self):
        if self.is_running:
            config.CANCELLED = True
            self._paused = False
            config.PAUSED = False
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText(" PAUSE")
            self.btn_stop.setEnabled(True)
            self.btn_start.setEnabled(False)
            self.counter.stop()
            self.lbl_action_status.setText(
                i18n.tr("Cancelling downloads, waiting for threads..."))
            self._status_color(COLOR_WARN)

    def on_progress(self, total_downloaded, total_queue=0):
        if not self._closing:
            self.bridge.progress.emit(total_downloaded, total_queue)

    def on_image_preview_callback(self, filepath):
        if not self._closing:
            self.bridge.live_preview.emit(filepath)

    def _status_color(self, hexc):
        self.lbl_action_status.setStyleSheet(f"color: {hexc};")

    def _on_progress(self, downloaded, queued):
        self.current_download_count = downloaded
        total_hint = self._download_total_hint
        max_limit = config.MAX_DOWNLOADS
        folder_name = os.path.basename(config.SAVE_FOLDER or "")
        if total_hint:
            self.progress_bar.set_target(min(1.0, downloaded / total_hint))
            self.counter.set_template(
                lambda n, hint=int(total_hint):
                f"Downloaded {n} / {hint} selected files")
        elif max_limit and max_limit > 0:
            self.progress_bar.set_target(min(1.0, downloaded / max_limit))
            self.counter.set_template(
                lambda n, lim=int(max_limit), fname=folder_name:
                f"Downloaded {n} / {lim} files | Folder: {fname}")
        else:
            pending = max(0, queued - downloaded)
            if pending:
                self.counter.set_template(
                    lambda n, pend=pending:
                    f"Downloaded {n} files · {pend} still processing...")
            else:
                self.progress_bar.set_target(0.55)
                self.counter.set_template(
                    lambda n, fname=folder_name:
                    f"Downloaded {n} files | Target: {fname}")
        self.counter.chase(int(downloaded))
        self._status_color(COLOR_TEXT_WHITE)

    def _on_download_finished(self, total, failed):
        self.is_running = False
        self._download_total_hint = None
        self._set_download_running(False)
        if config.CANCELLED:
            self.counter.stop()
            self.lbl_action_status.setText(i18n.tr("Download cancelled by user."))
            self._status_color(COLOR_WARN)
        else:
            self.counter.snap(int(total))
            self.lbl_action_status.setText(
                f"Download complete! Successfully saved {total} files "
                f"({len(failed)} skipped/failed).")
            self._status_color(COLOR_SUCCESS)
            self.progress_bar.finish_flash()
        if self._download_source == "selection":
            self.lbl_preview_status.setText(
                f"Selected download finished: {total} file(s) saved.")
            self._status_color(COLOR_SUCCESS if not config.CANCELLED else COLOR_WARN)
            if self._overlay is not None:
                self._overlay_download_btn.setEnabled(True)
                self._overlay_download_btn.setText(i18n.tr("DOWNLOAD THIS POST"))
        self._download_source = None
        try:
            self.stats_page.refresh(force=True)
        except Exception:
            pass

    def _on_download_failed(self, error):
        self.is_running = False
        self._download_total_hint = None
        self._set_download_running(False)
        self.progress_bar.error_state()
        self.counter.stop()
        self.lbl_action_status.setText(f"Download failed: {error}")
        self._status_color(COLOR_DANGER)
        self.show_toast("Error", f"Download failed: {error}",
                        kind="error", duration=6000)
        try:
            self.stats_page.refresh(force=True)
        except Exception:
            pass
        if self._download_source == "selection":
            self.lbl_preview_status.setText(f"Selected download failed: {error}")
            self._status_color(COLOR_DANGER)
            if self._overlay is not None:
                self._overlay_download_btn.setEnabled(True)
        self._download_source = None


    TOAST_W = 364
    TOAST_MARGIN = 16
    TOAST_GAP = 10

    def _toast_top(self):
        try:
            return self.stack.mapTo(self, QtCore.QPoint(0, 0)).y() + 8
        except Exception:
            return 56

    def show_toast(self, title, message, kind="error", duration=4200):
        try:
            alive = []
            for t in self._toasts:
                try:
                    if t.isVisible():
                        alive.append(t)
                except RuntimeError:
                    pass
            self._toasts = alive
            while len(self._toasts) >= 3:
                old = self._toasts.pop(0)
                try:
                    old.dismiss()
                except RuntimeError:
                    pass

            toast = Toast(self, i18n.tr(title), i18n.tr(message),
                          kind=kind, duration=duration, width=self.TOAST_W)
            toast.setToolTip(i18n.tr("Click to dismiss"))
            toast.dismissed.connect(self._on_toast_dismissed)
            effect = self._toast_sounds.get(kind)
            if effect is not None:
                try:
                    if effect.isPlaying():
                        effect.stop()
                    effect.play()
                except Exception:
                    pass
            self._toasts.append(toast)
            self._layout_toasts(animate=False, only=toast)
            toast.show_in(toast.pos())
        except Exception:
            logging.getLogger().debug("toast failed", exc_info=True)

    def _layout_toasts(self, animate=True, only=None):
        x = self.width() - self.TOAST_W - self.TOAST_MARGIN
        y = self._toast_top()
        for toast in list(self._toasts):
            try:
                height = toast.height()
                if getattr(toast, "_closing", False):
                    y += height + self.TOAST_GAP
                    continue
                target = QtCore.QPoint(x, y)
                if only is toast or not animate:
                    toast.move(target)
                elif toast.pos() != target:
                    anim = QPropertyAnimation(toast, b"pos", toast)
                    anim.setDuration(220)
                    anim.setStartValue(toast.pos())
                    anim.setEndValue(target)
                    anim.setEasingCurve(QEasingCurve.OutCubic)
                    anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
                toast.raise_()
            except RuntimeError:
                continue
            y += height + self.TOAST_GAP

    def _on_toast_dismissed(self, toast):
        self._toasts = [t for t in self._toasts if t is not toast]
        self._layout_toasts(animate=True)


    def _on_log(self, level, line):
        self.console_textbox.appendPlainText(line)
        if self.switch_autoscroll.isChecked():
            bar = self.console_textbox.verticalScrollBar()
            bar.setValue(bar.maximum())

    def copy_logs(self):
        QtWidgets.QApplication.clipboard().setText(
            self.console_textbox.toPlainText())
        self.show_toast("Copied", "Logs copied to clipboard!", kind="success")

    def browse_save_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Base Download Directory",
            self.entry_save_base.text().strip() or BASE_DIR)
        if d:
            self.entry_save_base.clear()
            self.entry_save_base.insert(d)

    def open_download_folder(self):
        folder = config.SAVE_FOLDER or self.entry_save_base.text().strip() \
            or os.path.join(BASE_DIR, "danbooru_downloads")
        if not os.path.exists(folder):
            os.makedirs(folder, exist_ok=True)
        if os.name == 'nt':
            os.startfile(folder)
        else:
            subprocess.Popen(["xdg-open", folder])

    def open_current_preview_image(self):
        if self.current_preview_filepath and \
                os.path.exists(self.current_preview_filepath) and os.name == 'nt':
            os.startfile(self.current_preview_filepath)


    def _on_live_preview(self, filepath):
        if self._closing or not filepath or not os.path.exists(filepath):
            return
        self.current_preview_filepath = filepath
        try:
            fname = os.path.basename(filepath)
            fsize_kb = os.path.getsize(filepath) / 1024
            if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.webp',
                                       '.bmp', '.gif')):
                pix = QtGui.QPixmap(filepath)
                if not pix.isNull() and (pix.width() > 280 or pix.height() > 280):
                    pix = pix.scaled(280, 280, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
                self.preview_label.setText("")
                self.preview_label.setPixmap(pix)
                self.lbl_preview_filename.setText(f"File: {fname[:38]}...")
                self.lbl_preview_details.setText(
                    f"Dimensions: {pix.width()}x{pix.height()} px | "
                    f"Size: {fsize_kb:.1f} KB")
            else:
                self.preview_label.setPixmap(QtGui.QPixmap())
                self.preview_label.setText(
                    f"Media File:\n{fname}\n({fsize_kb:.1f} KB)")
                self.lbl_preview_filename.setText(f"File: {fname}")
                self.lbl_preview_details.setText(f"Size: {fsize_kb:.1f} KB")
        except Exception:
            pass


    def open_preview_for_current_tags(self):
        tags = self.entry_tags.get().strip()
        if not tags:
            self.show_toast("Preview", "Add some tags first.", kind="info")
            return
        self.entry_preview_tags.set_line(tags)
        self.select_tab(1)
        self.start_preview_search(1)

    def copy_download_tags_to_preview(self):
        tags = self.entry_tags.get().strip()
        if not tags:
            self.show_toast("Preview", "The downloader has no tags yet.",
                            kind="info")
            return
        self.entry_preview_tags.set_line(tags)
        self.select_tab(1)

    def _preview_search_clicked(self):
        self.start_preview_search(1)

    def _prev_page(self):
        if not self._preview_history:
            return
        page, raw = self._preview_history.pop()
        self._run_preview_search(page, raw)

    def _next_page(self):
        if self._preview_next_raw is None:
            return
        self._preview_history.append((self._preview_page, self._preview_raw_start))
        self._run_preview_search(self._preview_page + 1, self._preview_next_raw)

    def start_preview_search(self, page=1):
        self._preview_history = []
        self._preview_search_gen += 1
        self._preview_session = f"preview-{time.time_ns()}"
        self._preview_cache.clear()
        self._preview_cache_order.clear()
        self._prefetch_queued.clear()
        self._run_preview_search(1, None)


    def _cache_key(self, start_raw):
        return int(start_raw) if start_raw else 0

    def _kick_prefetch(self, start_raw):
        if start_raw is None or self._closing:
            return
        marker = (self._preview_search_gen, self._cache_key(start_raw))
        if marker in self._prefetch_queued:
            return
        tags = self.entry_preview_tags.get().strip()
        if not tags:
            return
        self._prefetch_queued.add(marker)
        threading.Thread(
            target=self._prefetch_worker,
            args=(self._preview_search_gen, tags, int(start_raw),
                  self._prefetch_depth, self._preview_session),
            daemon=True).start()

    def _prefetch_worker(self, gen, tags, raw_start, depth, session):
        raw = raw_start
        for _ in range(depth):
            if self._closing or gen != self._preview_search_gen:
                return
            try:
                posts, note, has_more, next_raw = \
                    downloader.fetch_posts_for_preview(
                        tags, page=1, limit=40, start_raw=raw,
                        session=session, reset=False)
            except Exception:
                return
            if self._closing or gen != self._preview_search_gen:
                return
            self.bridge.preview_prefetched.emit({
                "gen": gen,
                "raw": raw,
                "posts": posts,
                "note": note,
                "has_more": has_more,
                "next_raw": next_raw,
            })
            if not has_more or next_raw is None:
                return
            raw = int(next_raw)
            time.sleep(0.9)

    def _on_prefetched(self, data):
        if self._closing or data.get("gen") != self._preview_search_gen:
            return
        key = self._cache_key(data.get("raw"))
        self._preview_cache[key] = (
            data.get("posts") or [], data.get("note") or "",
            bool(data.get("has_more")), data.get("next_raw"))
        self._preview_cache_order.append(key)
        while len(self._preview_cache_order) > 15:
            old = self._preview_cache_order.pop(0)
            self._preview_cache.pop(old, None)

    def _run_preview_search(self, page, start_raw):
        self.entry_preview_tags.commit()
        tags = self.entry_preview_tags.get().strip()
        if not tags:
            self.show_toast("Preview", "Please enter tags to preview.",
                            kind="warning")
            return
        if not self._enabled_source_keys():
            self.show_toast(
                "No Sources",
                "Enable at least one search source in Settings.",
                kind="warning")
            return
        if self.active_tab_index != 1:
            self.select_tab(1)
        self._apply_preview_config()
        self._preview_request_id += 1
        request_id = self._preview_request_id
        self._preview_page = max(1, int(page))
        self._preview_raw_start = start_raw
        self._preview_next_raw = None
        self.lbl_preview_page.setText(f"Page {self._preview_page}")
        self.btn_preview_prev.setEnabled(False)
        self.btn_preview_next.setEnabled(False)

        cached = self._preview_cache.pop(self._cache_key(start_raw), None)
        if cached is not None:
            posts, note, has_more, next_raw = cached
            self.btn_preview_search.setEnabled(True)
            self.btn_preview_search.setText("SEARCH")
            self._display_preview_results(
                request_id, self._preview_page, posts, note, has_more,
                next_raw, None)
            return

        self.lbl_preview_status.setText("Loading posts...")
        self._status_color(COLOR_TEXT_MUTED)
        self.btn_preview_search.setEnabled(False)
        self.btn_preview_search.setText("LOADING...")
        self._clear_grid("Loading posts...")
        threading.Thread(target=self._preview_search_worker,
                         args=(request_id, self._preview_page, tags, start_raw,
                               self._preview_session),
                         daemon=True).start()

    def _preview_search_worker(self, request_id, page, tags, start_raw,
                               session):
        try:
            posts, note, has_more, next_raw = downloader.fetch_posts_for_preview(
                tags, page=page, limit=40, start_raw=start_raw,
                session=session, reset=(start_raw is None))
            self.bridge.preview_results.emit(request_id, page, posts, note,
                                             has_more,
                                             int(next_raw) if next_raw else 0,
                                             None)
        except Exception as e:
            self.bridge.preview_results.emit(request_id, page, [], "", False,
                                             0, str(e))

    def _on_preview_results(self, request_id, page, posts, note, has_more,
                            next_raw, error):
        self._display_preview_results(request_id, page, posts, note, has_more,
                                      next_raw, error)

    def _display_preview_results(self, request_id, page, posts, note, has_more,
                                 next_raw, error):
        if self._closing or request_id != self._preview_request_id:
            return
        self.btn_preview_search.setEnabled(True)
        self.btn_preview_search.setText("SEARCH")
        if error:
            self.lbl_preview_status.setText(f"Preview error: {error}")
            self._status_color(COLOR_DANGER)
            self._clear_grid(f"Could not load posts.\n{error}")
            return
        self._populate_grid(posts or [])
        self._preview_next_raw = int(next_raw) if next_raw else None
        self.btn_preview_prev.setEnabled(bool(self._preview_history))
        self.btn_preview_next.setEnabled(self._preview_next_raw is not None)
        if self._preview_posts:
            status = f"{len(self._preview_posts)} post(s) · page {page}"
            if note:
                status += f" · {note}"
            self.lbl_preview_status.setText(status)
            self._status_color(COLOR_TEXT_MUTED)
        else:
            self.lbl_preview_status.setText(note or "No posts found.")
            self._clear_grid("No posts found.\nTry different tags.")
        if self._preview_next_raw is not None:
            self._kick_prefetch(self._preview_next_raw)

    def _grid_clear_widgets(self):
        while self.preview_grid.count():
            item = self.preview_grid.takeAt(0)
            w = item.widget() if item else None
            if w is not None and w is not self.preview_empty_label:
                w.deleteLater()
        self.preview_empty_label.hide()
        self._preview_cards.clear()
        self._preview_posts = []

    def _clear_grid(self, message=None):
        self._grid_clear_widgets()
        if message is not None:
            self.preview_empty_label.setText(message)
            self.preview_empty_label.show()
            self.preview_grid.addWidget(self.preview_empty_label, 0, 0, 1, 5)

    def _populate_grid(self, posts):
        self._grid_clear_widgets()
        self._preview_posts = list(posts or [])
        if not self._preview_posts:
            self.preview_empty_label.setText("No posts found.")
            self.preview_empty_label.show()
            self.preview_grid.addWidget(self.preview_empty_label, 0, 0, 1, 5)
            return
        for index, post in enumerate(posts):
            row, colx = divmod(index, 5)
            card = PreviewPostCard(post)
            card.open_requested.connect(self._open_overlay)
            card.toggle_requested.connect(self.toggle_preview_selection)
            self.preview_grid.addWidget(card, row, colx)
            key = post_key(post)
            self._preview_cards[key] = card
            if key in self._selected_posts:
                card.set_selected(True)
            self._load_thumbnail(post)
        self._grid_holder.adjustSize()

    def _load_thumbnail(self, post):
        key = post_key(post)
        card = self._preview_cards.get(key)
        if card is None:
            return
        cached = self._thumb_cache.get(key)
        if cached is not None:
            card.set_image(cached)
            return
        if key in self._thumb_pending:
            return
        url = post.get("preview_file_url") or post.get("large_file_url") \
            or post.get("file_url")
        if not url:
            card.set_failed()
            return
        self._thumb_pending.add(key)
        self._img_executor.submit(self._thumb_worker, key, url)

    def _thumb_worker(self, key, url):
        try:
            response = downloader.http_get(url, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            img = _letterbox(response.content, (180, 180))
            self.bridge.thumb_done.emit(key, img)
        except Exception:
            self.bridge.thumb_failed.emit(key)

    def _on_thumb_done(self, key, image):
        self._thumb_pending.discard(key)
        if len(self._thumb_cache) > 600:
            self._thumb_cache.clear()
        self._thumb_cache[key] = image
        card = self._preview_cards.get(key)
        if card is not None:
            card.set_image(image)

    def _on_thumb_failed(self, key):
        self._thumb_pending.discard(key)
        card = self._preview_cards.get(key)
        if card is not None:
            card.set_failed()


    def toggle_preview_selection(self, post, refresh_overlay=False):
        key = post_key(post)
        if key in self._selected_posts:
            del self._selected_posts[key]
        else:
            self._selected_posts[key] = post
        card = self._preview_cards.get(key)
        if card is not None:
            card.set_selected(key in self._selected_posts)
        if refresh_overlay and self._large_preview_post and \
                post_key(self._large_preview_post) == key:
            self._overlay_select_btn.setText(
                "REMOVE FROM SELECTION" if key in self._selected_posts
                else i18n.tr("ADD TO SELECTION"))
        self._refresh_selection_buttons()

    def toggle_large_preview_selection(self):
        if self._large_preview_post:
            self.toggle_preview_selection(self._large_preview_post,
                                          refresh_overlay=True)

    def select_all_preview_posts(self):
        for post in self._preview_posts:
            key = post_key(post)
            self._selected_posts[key] = post
            card = self._preview_cards.get(key)
            if card is not None:
                card.set_selected(True)
        self._refresh_selection_buttons()

    def clear_preview_selection(self):
        self._selected_posts.clear()
        for card in self._preview_cards.values():
            card.set_selected(False)
        self._refresh_selection_buttons()

    def _refresh_selection_buttons(self):
        count = len(self._selected_posts)
        self.lbl_preview_selection.setText(f"{count} " + i18n.tr("selected"))
        self.btn_download_selected.setEnabled(count > 0)
        self.btn_download_selected.setText(f"DOWNLOAD SELECTED ({count})")
        if count:
            self.btn_download_selected._fill = qcolor(COLOR_ACCENT)
            self.btn_download_selected._hover = qcolor(COLOR_ACCENT_HOVER)
            self.btn_download_selected._text_color = qcolor(COLOR_BG_WINDOW)
        else:
            self.btn_download_selected._fill = qcolor(COLOR_BG_INPUT)
            self.btn_download_selected._hover = qcolor(COLOR_ACCENT_HOVER)
            self.btn_download_selected._text_color = qcolor(COLOR_TEXT_MUTED)
        self.btn_download_selected.update()

    def download_selected_preview_posts(self):
        posts = list(self._selected_posts.values())
        if posts:
            self.start_selected_download(posts)

    def start_selected_download(self, posts):
        if self.is_running:
            self.show_toast("Download", "A download is already running.",
                            kind="info")
            return
        posts = list(posts or [])
        if not posts:
            return
        self.apply_ui_to_downloader_config(
            tags_override=self.entry_preview_tags.get().strip() or None)
        self.is_running = True
        self._paused = False
        config.PAUSED = False
        self.current_download_count = 0
        self._download_source = "selection"
        self._download_total_hint = len(posts)
        self._set_download_running(
            True, f"Downloading {len(posts)} selected post(s)...")
        self.lbl_preview_status.setText(
            f"Downloading {len(posts)} selected post(s)...")
        threading.Thread(target=self._download_worker_selected,
                         args=(posts,), daemon=True).start()


    def _open_overlay(self, post):
        self._large_preview_post = post
        self._large_request_id += 1
        request_id = self._large_request_id
        self._ensure_overlay()
        self._configure_overlay(post)
        self._overlay_big_label.setPixmap(QtGui.QPixmap())
        self._overlay_big_label.setText(i18n.tr("Loading preview..."))
        self.overlay_adjust()
        if not self._overlay.isVisible():
            self._overlay.show()
            self._overlay.raise_()
            self._overlay_fade_in()
        else:
            self._overlay.raise_()

        ext = (post.get("file_ext") or "").lower()
        if ext in {"mp4", "webm", "swf", "zip", "avif"}:
            url = post.get("preview_file_url")
        else:
            url = post.get("large_file_url") or post.get("file_url") \
                or post.get("preview_file_url")
        if url:
            self._img_executor.submit(self._large_worker, request_id, url)
        else:
            self._overlay_big_label.setText(i18n.tr("Preview unavailable"))

    def _overlay_fade_in(self):
        self._overlay.effect.setOpacity(0.0)
        a = QPropertyAnimation(self._overlay.effect, b"opacity", self._overlay)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.setDuration(200)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.finished.connect(a.deleteLater)
        a.start()

    def _large_worker(self, request_id, url):
        try:
            response = downloader.http_get(url, timeout=config.REQUEST_TIMEOUT)
            response.raise_for_status()
            img = _letterbox(response.content, (780, 620))
            self.bridge.large_done.emit(request_id, img)
        except Exception:
            self.bridge.large_failed.emit(request_id)

    def _on_large_done(self, request_id, image):
        if request_id != self._large_request_id or self._overlay is None \
                or not self._overlay.isVisible():
            return
        self._overlay_big_label.setText("")
        self._overlay_big_label.setPixmap(QtGui.QPixmap.fromImage(image))

    def _on_large_failed(self, request_id):
        if request_id != self._large_request_id or self._overlay is None \
                or not self._overlay.isVisible():
            return
        self._overlay_big_label.setPixmap(QtGui.QPixmap())
        self._overlay_big_label.setText(i18n.tr("Preview unavailable"))

    def _ensure_overlay(self):
        if self._overlay is not None:
            return
        ov = QtWidgets.QFrame(self)
        ov.setObjectName("Overlay")
        ov.setStyleSheet(
            f"QFrame#Overlay {{ background: {COLOR_BG_WINDOW};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 12px; }}")
        ov.effect = QtWidgets.QGraphicsOpacityEffect(ov)
        ov.effect.setOpacity(1.0)
        ov.setGraphicsEffect(ov.effect)
        v = QtWidgets.QVBoxLayout(ov)
        v.setContentsMargins(16, 12, 16, 16)
        v.setSpacing(8)

        header = QtWidgets.QFrame()
        header.setStyleSheet("background: transparent;")
        hh = QtWidgets.QHBoxLayout(header)
        hh.setContentsMargins(2, 0, 0, 0)
        self._overlay_title = QtWidgets.QLabel("Post")
        self._overlay_title.setFont(B(15))
        self._overlay_title.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        hh.addWidget(self._overlay_title)
        hh.addStretch(1)
        self._overlay_close_btn = x = HoverButton("✕", hover="#662222", text_color=COLOR_RED, radius=8,
                        font=B(12), height=32)
        x.setFixedSize(32, 32)
        x.clicked.connect(self._close_overlay)
        hh.addWidget(x)
        v.addWidget(header)
        sep = QtWidgets.QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {COLOR_BORDER}; border: none;"
                          "margin-left: 6px; margin-right: 6px;")
        v.addWidget(sep)

        body = QtWidgets.QFrame()
        body.setStyleSheet("background: transparent;")
        bh = QtWidgets.QHBoxLayout(body)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(12)
        self._overlay_big_label = QtWidgets.QLabel(i18n.tr("Loading preview..."))
        self._overlay_big_label.setAlignment(Qt.AlignCenter)
        self._overlay_big_label.setFont(F(12))
        self._overlay_big_label.setStyleSheet(
            f"background: {COLOR_BG_WINDOW}; color: {COLOR_TEXT_INACTIVE};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px;")
        bh.addWidget(self._overlay_big_label, 3)

        info = QtWidgets.QWidget()
        info.setStyleSheet("background: transparent;")
        iv = QtWidgets.QVBoxLayout(info)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(8)
        self._overlay_meta = QtWidgets.QLabel("")
        self._overlay_meta.setFont(F(12))
        self._overlay_meta.setWordWrap(True)
        self._overlay_meta.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        self._overlay_meta.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        iv.addWidget(self._overlay_meta)
        self._overlay_tags = QtWidgets.QPlainTextEdit()
        self._overlay_tags.setReadOnly(True)
        self._overlay_tags.setFont(MONO(11))
        self._overlay_tags.setStyleSheet(
            f"QPlainTextEdit {{ background: {COLOR_BG_INPUT}; color: #c8c9dc;"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 8px; }}")
        iv.addWidget(self._overlay_tags, 1)

        self._overlay_download_btn = HoverButton(
            i18n.tr("DOWNLOAD THIS POST"), fill=COLOR_ACCENT, hover=COLOR_ACCENT_HOVER,
            text_color=COLOR_BG_WINDOW, radius=8, font=B(11), height=36)
        self._overlay_download_btn.clicked.connect(
            self.download_single_preview_post)
        iv.addWidget(self._overlay_download_btn)
        self._overlay_select_btn = HoverButton(i18n.tr("ADD TO SELECTION"), radius=8,
                                               font=B(10), height=32)
        self._overlay_select_btn.clicked.connect(
            self.toggle_large_preview_selection)
        iv.addWidget(self._overlay_select_btn)
        btn_web = HoverButton(i18n.tr("OPEN ON SOURCE"), radius=8, font=B(10), height=32)
        btn_web.clicked.connect(self.open_preview_post_in_browser)
        iv.addWidget(btn_web)
        bh.addWidget(info, 2)
        v.addWidget(body, 1)

        self._overlay = ov

    def overlay_adjust(self):
        if self._overlay is not None:
            self._overlay.setGeometry(self.rect())

    def _configure_overlay(self, post):
        site_label = post.get("site_name") or "Danbooru"
        self._overlay_title.setText(
            f"{site_label} · Post #{post.get('id')}")
        media = post.get("media_asset") or {}
        size = media.get("file_size") or post.get("file_size")
        size_str = f"{size / 1024 / 1024:.1f} MB" if size else "—"
        ext = (post.get("file_ext") or "?").upper()
        width = post.get("image_width", 0)
        height = post.get("image_height", 0)
        rating = (post.get("rating") or "?").upper()
        score = post.get("score", 0)
        self._overlay_meta.setText(
            f"Score: {score} · Rating: {rating} · {width}x{height} · "
            f"{ext} · {size_str}")
        sections = []
        for label, key in (("Artist", "tag_string_artist"),
                           ("Character", "tag_string_character"),
                           ("Copyright", "tag_string_copyright"),
                           ("General", "tag_string_general"),
                           ("Meta", "tag_string_meta")):
            tags = (post.get(key) or "").strip()
            if not tags:
                continue
            if key == "tag_string_general":
                parts = tags.split()
                if len(parts) > 80:
                    tags = " ".join(parts[:80]) + " …"
            sections.append(f"{label}:\n{tags}")
        self._overlay_tags.setPlainText("\n\n".join(sections) or "No tags.")
        key = post_key(post)
        self._overlay_select_btn.setText(
            "REMOVE FROM SELECTION" if key in self._selected_posts
            else i18n.tr("ADD TO SELECTION"))

    def _close_overlay(self):
        ov = self._overlay
        if ov is None or not ov.isVisible():
            return
        self._large_request_id += 1
        self._large_preview_post = None
        a = QPropertyAnimation(ov.effect, b"opacity", ov)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.setDuration(150)
        a.setEasingCurve(QEasingCurve.InCubic)
        a.finished.connect(ov.hide)
        a.finished.connect(a.deleteLater)
        a.start()

    def download_single_preview_post(self):
        if not self._large_preview_post:
            return
        if self.is_running:
            self.show_toast("Download", "A download is already running.",
                            kind="info")
            return
        self._overlay_download_btn.setEnabled(False)
        self._overlay_download_btn.setText("DOWNLOADING...")
        self.start_selected_download([self._large_preview_post])

    def open_preview_post_in_browser(self):
        if not self._large_preview_post:
            return
        url = self._large_preview_post.get("page_url")
        if not url:
            post_id = self._large_preview_post.get("id")
            url = f"https://danbooru.donmai.us/posts/{post_id}"
        webbrowser.open(url)


    def check_active_tags(self):
        tags = self.entry_tags.get().strip()
        if not tags:
            self.show_toast("Tags", "Please enter tags first.",
                            kind="warning")
            return
        queries = [q for q in tags.split()
                   if not downloader.is_hard_blocked_tag_name(q)]
        if not queries:
            self.select_tab(3)
            self.tag_result_view.show_message(
                "All of those tags are permanently blocked.")
            return
        self.select_tab(3)
        self.entry_tool_tag.clear()
        self.entry_tool_tag.insert(queries[0])
        if len(queries) == 1:
            self.run_tag_lookup()
            return
        self.tag_result_view.show_message(f"Checking {len(queries)} tags...")
        threading.Thread(target=self._multi_tag_worker, args=(queries,),
                         daemon=True).start()

    def _multi_tag_worker(self, queries):
        results = [(q, check_tag_details(q), fetch_tag_suggestions(q, limit=5))
                   for q in queries]
        self.bridge.multi_tag_results.emit(results)

    def _on_multi_tag_results(self, results):
        self.tag_result_view.show_multi(results)

    def run_tag_lookup(self):
        query = self.entry_tool_tag.text().strip()
        if not query:
            self.tag_result_view.show_message(
                i18n.tr("Type a tag above, then press CHECK (or Enter)."))
            return
        if downloader.is_hard_blocked_tag_name(query):
            self.tag_result_view.show_message(f"'{query}' " + i18n.tr("is permanently blocked."))
            return
        self.tag_result_view.show_message(i18n.tr("Checking") + f" '{query}'...")
        threading.Thread(target=self._tag_lookup_worker, args=(query,),
                         daemon=True).start()

    def quick_tag(self, tag):
        self.entry_tool_tag.setText(tag)
        self.run_tag_lookup()

    def clear_tag_tool(self):
        self.entry_tool_tag.clear()
        self.tag_result_view.show_message(
            i18n.tr("Type a tag above, then press CHECK (or Enter)."))

    def _tag_lookup_worker(self, query):
        details = check_tag_details(query)
        suggestions = fetch_tag_suggestions(query, limit=10)
        self.bridge.tag_results.emit(query, details, suggestions)

    def _on_tag_results(self, query, details, suggestions):
        self.tag_result_view.show_result(query, details, suggestions)

    def _apply_preview_config(self):
        config.USERNAME = self.entry_username.text().strip()
        config.API_KEY = self.entry_api_key.text().strip()
        config.REQUEST_TIMEOUT = int(self.slider_timeout.get())
        config.ALLOWED_RATINGS = {"g"}
        config.SOURCES = {
            key: switch.isChecked()
            for key, switch in self.source_switches.items()
        }
        config.GELBOORU_API_KEY = self.entry_gelbooru_key.text().strip()
        config.GELBOORU_USER_ID = self.entry_gelbooru_user.text().strip()

    def run_tags_to_triggers(self):
        self.apply_ui_to_downloader_config()
        config.TAGS_TO_TRIGGER_WORDS = True
        try:
            search_tags_to_triggers()
            self.show_toast(
                "Success",
                "Search tags prioritized to triggers in all .txt files!",
                kind="success")
        except Exception as e:
            self.show_toast("Error", f"Failed: {e}", kind="error")

    def run_add_own_triggers(self):
        self.apply_ui_to_downloader_config()
        words = self.entry_own_triggers.text().strip()
        if not words:
            self.show_toast("Empty", "Please enter trigger words.",
                            kind="warning")
            return
        config.ADD_OWN_TRIGGER_WORDS = words
        try:
            add_own_triggers()
            self.show_toast(
                "Success", f"Added triggers '{words}' to all .txt files!",
                kind="success")
        except Exception as e:
            self.show_toast("Error", f"Failed: {e}", kind="error")

    def run_strip_tags(self):
        self.apply_ui_to_downloader_config()
        raw = self.entry_strip_tags.text().strip()
        if not raw:
            self.show_toast("Empty", "Please enter tags to remove.",
                            kind="warning")
            return
        tags_set = {t.strip() for t in raw.split(',') if t.strip()}
        config.REMOVE_FROM_TXT_FILES = tags_set
        try:
            remove_tags_from_txt_files()
            self.show_toast(
                "Success",
                f"Stripped {len(tags_set)} tag types from .txt files!",
                kind="success")
        except Exception as e:
            self.show_toast("Error", f"Failed: {e}", kind="error")


    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._overlay is not None and self._overlay.isVisible():
            self.overlay_adjust()
        toast = getattr(self, "_song_toast", None)
        if toast is not None and toast.isVisible():
            toast.reposition()
        if getattr(self, "_toasts", None):
            self._layout_toasts(animate=False)
        for page in (self.pages if hasattr(self, "pages") else []):
            page.updateGeometry()
        try:
            self._size_grip.move(self._root_frame.width() - 22,
                                 self._root_frame.height() - 22)
            self._size_grip.raise_()
        except Exception:
            pass

    def closeEvent(self, ev):
        self._closing = True
        config.ON_PREVIEW_CALLBACK = None
        config.ON_PROGRESS_CALLBACK = None
        if hasattr(config, "CANCELLED"):
            if self.is_running:
                config.CANCELLED = True
        config.PAUSED = False
        try:
            self._img_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        try:
            self.progress_bar._tick.stop()
        except Exception:
            pass
        super().closeEvent(ev)
        ev.accept()


def _letterbox(data: bytes, size):
    target_w, target_h = size
    img = QtGui.QImage.fromData(data)
    img = img.scaled(target_w, target_h, Qt.KeepAspectRatio,
                     Qt.SmoothTransformation)
    canvas = QtGui.QImage(target_w, target_h, QtGui.QImage.Format_ARGB32)
    canvas.fill(qcolor(COLOR_BG_CARD_INNER))
    x = (target_w - img.width()) // 2
    y = (target_h - img.height()) // 2
    p = QtGui.QPainter(canvas)
    p.drawImage(x, y, img)
    p.end()
    return canvas


def _set_row_tip(row, tip):
    if not tip:
        return
    widgets = [row] + row.findChildren(QtWidgets.QWidget)
    for w in widgets:
        w.setToolTip(tip)


def _add_slider(card, label, lo, hi, default, step, unit, fmt=None, tip=None):
    row = QtWidgets.QFrame()
    row.setStyleSheet("background: transparent;")
    rv = QtWidgets.QVBoxLayout(row)
    rv.setContentsMargins(0, 6, 0, 10)
    rv.setSpacing(4)
    head = QtWidgets.QFrame()
    head.setStyleSheet("background: transparent;")
    hh = QtWidgets.QHBoxLayout(head)
    hh.setContentsMargins(0, 0, 0, 0)
    title = QtWidgets.QLabel(label)
    title.setFont(F(12))
    title.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
    hh.addWidget(title)
    hh.addStretch(1)
    display_fmt = fmt if callable(fmt) else (
        (lambda v, f=fmt: f.format(v).replace(unit, i18n.tr(unit))
         if unit else f.format(v)) if fmt else
        (lambda v: f"{v:.1f} {i18n.tr(unit)}" if isinstance(step, float)
         else f"{int(v)} {i18n.tr(unit)}"))
    val_lbl = QtWidgets.QLabel(display_fmt(default))
    val_lbl.setFont(F(12))
    val_lbl.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
    hh.addWidget(val_lbl)
    rv.addWidget(head)
    s = DarkSlider(lo, hi, default, step)

    def on_change(_=None):
        val_lbl.setText(display_fmt(s.get()))
        val_lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        title.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")

    s.valueChanged.connect(on_change)
    s.set_display_sync(on_change)
    rv.addWidget(s)
    card.body.addWidget(row)
    _set_row_tip(row, tip)
    return s


def _add_switch(card, label, default, tip=None):
    row = QtWidgets.QFrame()
    row.setStyleSheet("background: transparent;")
    rh = QtWidgets.QHBoxLayout(row)
    rh.setContentsMargins(0, 2, 0, 2)
    lbl = QtWidgets.QLabel(label)
    lbl.setFont(F(12))
    lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE if default else COLOR_TEXT_INACTIVE};")
    rh.addWidget(lbl)
    rh.addStretch(1)
    sw = ToggleSwitchWidget(default)

    def sync(on):
        lbl.setStyleSheet(
            f"color: {COLOR_TEXT_WHITE if on else COLOR_TEXT_INACTIVE};")

    sw.toggled.connect(sync)
    rh.addWidget(sw)
    card.body.addWidget(row)
    _set_row_tip(row, tip)
    return sw


def _format_tag_details(query, details, suggestions):
    lines = [f"=== TAG DETAILS: '{query}' ==="]
    lines.append(f"• Exists: {'Yes' if details.get('exists') else 'No'}")
    if details.get('post_count') is not None:
        lines.append(f"• Post Count: {details.get('post_count', 0):,}")
    else:
        lines.append("• Post Count: N/A")
    lines.append(f"• Category: {details.get('category_name', 'General')}"
                 f" (ID {details.get('category', 0)})")
    if details.get('is_deprecated'):
        lines.append("WARNING: This tag is DEPRECATED on Danbooru!")
    if details.get('suggestion'):
        lines.append(f"Typo Suggestion: '{details.get('suggestion')}' "
                     f"({details.get('suggestion_count', 0):,} posts)")
    lines.append("")
    lines.append("=== AUTOCOMPLETE SUGGESTIONS ===")
    if suggestions:
        for s in suggestions:
            cat = s.get('category_name', 'General')
            count = s.get('post_count', 0)
            name = s.get('value', '')
            autocorr = " [Autocorrect]" if s.get('is_autocorrect') else ""
            lines.append(f"• {name:<28} | {cat:<10} | {count:>7,} posts{autocorr}")
    else:
        lines.append("No autocomplete matches found.")
    return "\n".join(lines)


def main():
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    _icon = app_icon()
    if not _icon.isNull():
        app.setWindowIcon(_icon)
    register_fonts()
    app.setStyle("Fusion")
    app.setStyleSheet(
        "QToolTip { background-color: %s; color: #ccd0dd;"
        "border: 1px solid %s; border-radius: 6px; padding: 6px 9px;"
        "font-family: '%s'; font-size: %dpx; opacity: 230; }"
        % (COLOR_BG_CARD, COLOR_BORDER_HOVER,
           qt_theme.FONT.get("semibold") or "Segoe UI", 14)
    )
    win = DanbooruDownloaderApp()
    win.wire_config_callbacks()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
