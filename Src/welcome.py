import os

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import (
    Qt, QTimer, QSize, QRectF, QEasingCurve, QPropertyAnimation,
    QVariantAnimation,
)

try:
    import res as _res
    ASSETS_DIR = _res.ASSETS_DIR
except Exception:
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "assets")

import i18n
from qt_theme import B

INTRO_ENV = "DANBOORU_NO_INTRO"


def should_play():
    raw = os.environ.get(INTRO_ENV, "").strip().lower()
    return raw not in ("1", "true", "yes", "on")


def _blur_pixmap(pixmap, factor=20):
    img = pixmap.toImage().convertToFormat(
        QtGui.QImage.Format_ARGB32_Premultiplied)
    if img.isNull():
        return None
    w = max(1, img.width() // factor)
    h = max(1, img.height() // factor)
    small = img.scaled(w, h, Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation)
    blurred = small.scaled(img.size(), Qt.IgnoreAspectRatio,
                           Qt.SmoothTransformation)
    return QtGui.QPixmap.fromImage(blurred)


class WelcomeSplash(QtWidgets.QWidget):

    HOLD_MS = 2460
    FADE_OUT_MS = 460

    def __init__(self, main):
        super().__init__(main, Qt.Tool | Qt.FramelessWindowHint)
        self._main = main

        self._closing = False
        self._finished = False
        self._anims = []

        self._bg = None
        self._bg_op = 0.0
        self._logo_op = 0.0
        self._logo_scale = 0.94
        self._text_op = 0.0
        self._text_dy = 18.0

        self._movie = None
        self._sound = None

        self._logo_rect = None
        self._text_rect = None
        self._font = B(33)
        self._fm = QtGui.QFontMetrics(self._font)
        self._text = i18n.tr("Welcome")

        self.setWindowTitle("Welcome")
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setFocusPolicy(Qt.StrongFocus)


    def start(self):
        try:
            self.setGeometry(self._main.geometry())
        except Exception:
            pass

        self._setup_movie()
        self._setup_sound()
        self._layout()

        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        try:
            QtWidgets.QApplication.instance().installEventFilter(self)
        except Exception:
            pass
        self._timeline()

    def _timeline(self):
        self._later(30, self._capture_and_fade)
        self._later(110, self._play_sound)
        self._later(300, self._animate_logo)
        self._later(620, self._animate_text)
        self._later(self.HOLD_MS,
                    lambda: self._begin_close(self.FADE_OUT_MS,
                                              QEasingCurve.InCubic))

    def _later(self, ms, fn):
        def run():
            if self._closing or self._finished:
                return
            try:
                fn()
            except Exception:
                pass
        QTimer.singleShot(ms, run)

    def _animate(self, duration, curve, on_value):
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(int(duration))
        anim.setEasingCurve(curve)
        anim.valueChanged.connect(on_value)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._anims.append(anim)
        return anim


    def _setup_movie(self):
        path = os.path.join(ASSETS_DIR, "images", "welcome.gif")
        if not os.path.isfile(path):
            return
        try:
            movie = QtGui.QMovie(path, QtCore.QByteArray(), self)
            movie.setCacheMode(QtGui.QMovie.CacheNone)
            movie.frameChanged.connect(lambda _i: self.update())
            movie.start()
            self._movie = movie
        except Exception:
            self._movie = None

    def _setup_sound(self):
        path = os.path.join(ASSETS_DIR, "sounds", "app_start.wav")
        if not os.path.isfile(path):
            return
        try:
            from PySide6.QtMultimedia import QSoundEffect
            snd = QSoundEffect(self)
            snd.setSource(QtCore.QUrl.fromLocalFile(path))
            snd.setVolume(0.65)
            self._sound = snd
        except Exception:
            self._sound = None

    def _play_sound(self):
        try:
            if self._sound is not None:
                self._sound.play()
        except Exception:
            pass

    def _stop_media(self):
        try:
            if self._sound is not None:
                self._sound.stop()
        except Exception:
            pass
        try:
            if self._movie is not None:
                self._movie.stop()
        except Exception:
            pass


    def _capture_and_fade(self):
        if self._bg is None:
            try:
                self._bg = _blur_pixmap(self._main.grab())
            except Exception:
                self._bg = None
        self._fade_backdrop()

    def _fade_backdrop(self):
        def on_value(value):
            self._bg_op = float(value)
            self.update()
        self._animate(360, QEasingCurve.OutCubic, on_value)

    def _animate_logo(self):
        def on_value(value):
            t = float(value)
            self._logo_op = min(1.0, t * 1.25)
            self._logo_scale = 0.94 + 0.06 * t
            self.update()
        self._animate(480, QEasingCurve.OutCubic, on_value)

    def _animate_text(self):
        def on_value(value):
            t = float(value)
            self._text_op = min(1.0, t * 1.15)
            self._text_dy = 18.0 * (1.0 - t)
            self.update()
        self._animate(520, QEasingCurve.OutCubic, on_value)

    def _begin_close(self, duration=460, curve=QEasingCurve.InCubic):
        if self._closing or self._finished:
            return
        self._closing = True
        self._stop_media()
        try:
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(int(duration))
            anim.setStartValue(self.windowOpacity())
            anim.setEndValue(0.0)
            anim.setEasingCurve(curve)
            anim.finished.connect(self._finish)
            anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
            self._anims.append(anim)
        except Exception:
            self._finish()

    def _finish(self):
        if self._finished:
            return
        self._finished = True
        self._stop_media()
        try:
            QtWidgets.QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        try:
            self.hide()
        except Exception:
            pass
        try:
            self._main.raise_()
            self._main.activateWindow()
        except Exception:
            pass
        self.close()
        self.deleteLater()


    def mousePressEvent(self, ev):
        self._begin_close(170, QEasingCurve.OutCubic)
        ev.accept()

    def eventFilter(self, obj, ev):
        try:
            if (ev.type() == QtCore.QEvent.KeyPress
                    and not self._closing and not self._finished
                    and ev.key() in (Qt.Key_Escape, Qt.Key_Space,
                                     Qt.Key_Return, Qt.Key_Enter)):
                self._begin_close(170, QEasingCurve.OutCubic)
                return True
        except Exception:
            pass
        return False


    def _layout(self):
        if not hasattr(self, "_font"):
            return
        w = max(1.0, float(self.width()))
        h = max(1.0, float(self.height()))
        text_h = float(self._fm.height()) + 4.0

        if self._movie is not None:
            logo_w = min(380.0, max(220.0, w * 0.28))
            logo_h = logo_w * 280.0 / 498.0
            gap = max(22.0, logo_h * 0.16)
            try:
                dpr = float(self.devicePixelRatioF())
                self._movie.setScaledSize(
                    QSize(int(logo_w * dpr), int(logo_h * dpr)))
            except Exception:
                pass
        else:
            logo_w = logo_h = gap = 0.0

        block_h = logo_h + gap + text_h + 24.0
        top = (h - block_h) / 2.0 - h * 0.01

        if logo_h:
            self._logo_rect = QRectF((w - logo_w) / 2.0, top, logo_w, logo_h)
        else:
            self._logo_rect = None
        self._text_rect = QRectF(0.0, top + logo_h + gap, w, text_h)
        self.update()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._layout()


    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)

        clip = QtGui.QPainterPath()
        clip.addRoundedRect(
            QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0), 12.0, 12.0)
        p.setClipPath(clip)

        p.fillRect(self.rect(), QtGui.QColor("#0a0a0c"))

        if self._bg is not None and self._bg_op > 0.002:
            p.setOpacity(self._bg_op)
            p.drawPixmap(self.rect(), self._bg)
            p.setOpacity(1.0)
        p.fillRect(self.rect(),
                   QtGui.QColor(8, 8, 10, int(186 * self._bg_op)))

        fade = QtGui.QLinearGradient(0.0, self.height() * 0.42,
                                     0.0, float(self.height()))
        fade.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
        fade.setColorAt(1.0, QtGui.QColor(0, 0, 0,
                                          int(150 * self._bg_op)))
        p.fillRect(self.rect(), fade)

        if self._logo_rect is not None and self._bg_op > 0.002:
            center = self._logo_rect.center()
            radius = max(170.0, self._logo_rect.width() * 1.05)
            glow = QtGui.QRadialGradient(center, radius)
            glow.setColorAt(0.0, QtGui.QColor(255, 255, 255,
                                              int(26 * self._bg_op)))
            glow.setColorAt(0.55, QtGui.QColor(255, 255, 255,
                                               int(9 * self._bg_op)))
            glow.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), glow)

        if (self._movie is not None and self._logo_rect is not None
                and self._logo_op > 0.004):
            frame = self._movie.currentPixmap()
            if not frame.isNull():
                target = QRectF(self._logo_rect)
                if abs(self._logo_scale - 1.0) > 0.001:
                    tw = target.width() * self._logo_scale
                    th = target.height() * self._logo_scale
                    target = QRectF(target.center().x() - tw / 2.0,
                                    target.center().y() - th / 2.0,
                                    tw, th)
                rounded = QtGui.QPainterPath()
                rounded.addRoundedRect(target, 16.0, 16.0)

                p.save()
                p.setOpacity(self._logo_op)
                p.setClipPath(rounded)
                p.drawPixmap(target, frame, QRectF(frame.rect()))
                p.restore()

                p.save()
                p.setOpacity(self._logo_op * 0.6)
                p.setBrush(Qt.NoBrush)
                p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 52), 1.2))
                p.drawRoundedRect(target.adjusted(0.6, 0.6, -0.6, -0.6),
                                  15.4, 15.4)
                p.restore()

        if self._text_op > 0.004 and self._text_rect is not None:
            p.save()
            p.setOpacity(self._text_op)
            rect = QRectF(self._text_rect)
            rect.translate(0.0, -self._text_dy)
            p.setPen(QtGui.QColor(255, 255, 255))
            p.setFont(self._font)
            p.drawText(rect, Qt.AlignHCenter | Qt.AlignTop, self._text)

            line_w = 54.0 * (0.55 + 0.45 * self._text_op)
            line_x = rect.center().x() - line_w / 2.0
            line_y = rect.top() + float(self._fm.height()) + 16.0
            p.setPen(Qt.NoPen)
            p.setBrush(QtGui.QColor(255, 255, 255, 170))
            p.drawRoundedRect(QRectF(line_x, line_y, line_w, 2.6),
                              1.3, 1.3)
            p.restore()

        p.end()
