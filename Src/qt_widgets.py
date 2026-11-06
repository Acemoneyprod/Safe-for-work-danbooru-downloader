import math

from PySide6 import QtCore, QtGui, QtWidgets

import i18n
from qt_theme import (
    COLOR_ACCENT, COLOR_ACCENT_HOVER, COLOR_BG_CARD, COLOR_BG_CARD_INNER,
    COLOR_BG_HOVER, COLOR_BG_INPUT, COLOR_BG_WINDOW, COLOR_BORDER,
    COLOR_BORDER_HOVER, COLOR_DANGER, COLOR_RED, COLOR_SUCCESS,
    COLOR_TEXT_INACTIVE, COLOR_TEXT_MUTED, COLOR_TEXT_WHITE, COLOR_WARN,
    B, F, qcolor, rgba, lerp_color,
)


class HoverButton(QtWidgets.QPushButton):

    def __init__(self, text="", *, fill=COLOR_BG_INPUT, hover=COLOR_BG_HOVER,
                 text_color=COLOR_TEXT_WHITE, radius=8, pix=None, icon_size=18,
                 font=None, height=36, parent=None):
        super().__init__(text, parent)
        self._fill = qcolor(fill)
        self._hover = qcolor(hover)
        self._text_color = qcolor(text_color)
        self._radius = radius
        self._pix = pix
        self._icon_size = icon_size
        self._flash = 0.0
        self._flash_color = rgba(text_color, 60)
        self._pix_dy = 0
        self._hovered = False
        if font is not None:
            self.setFont(font)
        self.setMinimumHeight(height)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.pressed.connect(self._start_flash)
        self.setText(text)

    def sizeHint(self):
        base = super().sizeHint()
        fm = QtGui.QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        iw = (self._icon_size + 7) if self._pix is not None else 0
        w = tw + iw + 24
        return QtCore.QSize(max(base.width(), w),
                            max(base.height(), self.minimumHeight() or base.height()))

    def set_pix(self, pix: QtGui.QPixmap):
        self._pix = pix
        self.update()

    def _start_flash(self):
        a = QtCore.QVariantAnimation(self)
        a.setStartValue(1.0)
        a.setEndValue(0.0)
        a.setDuration(300)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.valueChanged.connect(self._on_flash)
        a.finished.connect(a.deleteLater)
        a.start()

    def _on_flash(self, v):
        self._flash = v
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        body = self.rect().adjusted(1, 1, -2, -2)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(body), self._radius, self._radius)

        if not self.isEnabled():
            fill = self._fill
            col = lerp_color(self._text_color, self._fill, 0.55)
        else:
            fill = self._hover if self._hovered else self._fill
            if self.isDown():
                fill = lerp_color(fill, self._flash_color, 0.12)
            col = self._text_color
        p.fillPath(path, fill)
        if self._flash > 0.001 and self.isEnabled():
            fc = QtGui.QColor(self._flash_color)
            fc.setAlpha(int(fc.alpha() * self._flash))
            p.fillPath(path, fc)

        fm = QtGui.QFontMetrics(self.font())
        tw = fm.horizontalAdvance(self.text())
        iw = (self._icon_size + 7) if self._pix is not None else 0
        start = body.center().x() - (tw + iw) / 2.0
        if self._pix is not None:
            isz = self._icon_size
            pm = self._pix.scaled(isz, isz, QtCore.Qt.KeepAspectRatio,
                                  QtCore.Qt.SmoothTransformation)
            p.drawPixmap(int(start),
                         int((body.height() - pm.height()) / 2.0 + self._pix_dy),
                         pm)
            start += iw
        p.setPen(QtGui.QPen(col))
        p.setFont(self.font())
        text_rect = QtCore.QRectF(start, 0, tw + 2, body.height())
        p.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self.text())
        p.end()


class PillTabButton(QtWidgets.QWidget):
    clicked = QtCore.Signal(int)

    def __init__(self, index: int, text: str, pix: QtGui.QPixmap, parent=None):
        super().__init__(parent)
        self.index = index
        self.label = text
        self.pix = pix
        self.active = False
        self._hovered = False
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(96, 74)

    def set_active(self, active: bool, animate=True):
        self.active = bool(active)
        self._hovered = self.underMouse()
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(self.index)

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = self.rect().adjusted(1, 2, -2, -2)
        path = QtGui.QPainterPath()
        path.addRoundedRect(QtCore.QRectF(r), 8, 8)
        if self.active:
            p.fillPath(path, qcolor(COLOR_BG_CARD_INNER))
        elif self._hovered:
            p.fillPath(path, qcolor(COLOR_BG_HOVER))

        if self.pix is not None:
            isz = 24
            pm = self.pix.scaled(isz, isz, QtCore.Qt.KeepAspectRatio,
                                 QtCore.Qt.SmoothTransformation)
            ix = (w - isz) / 2.0
            p.drawPixmap(int(ix), 15, pm)

        size = 10.0
        f = B(size)
        fm = QtGui.QFontMetrics(f)
        while size > 7.0 and fm.horizontalAdvance(self.label) > w - 10:
            size -= 0.5
            f = B(size)
            fm = QtGui.QFontMetrics(f)
        label = fm.elidedText(self.label, QtCore.Qt.ElideRight, w - 8)
        p.setFont(f)
        p.setPen(QtGui.QPen(qcolor(COLOR_TEXT_WHITE if self.active
                                   else COLOR_TEXT_INACTIVE)))
        p.drawText(QtCore.QRect(4, 46, w - 8, 16),
                   QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop, label)
        p.end()


def safe_stop(anim):
    if anim is None:
        return
    try:
        anim.stop()
    except RuntimeError:
        pass


class ToggleSwitchWidget(QtWidgets.QAbstractButton):
    WIDTH, HEIGHT = 42, 22

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(self.WIDTH + 2, self.HEIGHT)
        self._t = 1.0 if checked else 0.0
        self._anim = None
        self.toggled.connect(self._animate)

    def _animate(self, checked):
        if self._anim is not None:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
            self._anim = None
        a = QtCore.QVariantAnimation(self)
        a.setStartValue(self._t)
        a.setEndValue(1.0 if checked else 0.0)
        a.setDuration(180)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.valueChanged.connect(self._on_anim)
        a.finished.connect(a.deleteLater)
        a.start()
        self._anim = a

    def _on_anim(self, v):
        self._t = float(v)
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        track = lerp_color(COLOR_BG_INPUT, COLOR_ACCENT, self._t)
        knob = lerp_color(COLOR_TEXT_INACTIVE, COLOR_BG_WINDOW, self._t)
        tp = QtGui.QPainterPath()
        tp.addRoundedRect(QtCore.QRectF(0, 0, self.WIDTH + 1, self.HEIGHT),
                          self.HEIGHT / 2, self.HEIGHT / 2)
        p.fillPath(tp, track)
        knob_x = 2 + self._t * (self.WIDTH - 20)
        kp = QtGui.QPainterPath()
        kp.addEllipse(QtCore.QRectF(knob_x, 2, 18, 18))
        p.fillPath(kp, knob)
        p.end()


class DarkSlider(QtWidgets.QWidget):
    valueChanged = QtCore.Signal(float)

    TRACK_H = 4
    KNOB_W, KNOB_H = 28, 15
    TOTAL_H = 20

    def __init__(self, minimum, maximum, value=0.0, step=1, *, parent=None):
        super().__init__(parent)
        self.min, self.max, self.step = minimum, maximum, step
        self._value = float(value)
        self._hovered = False
        self._dragging = False
        self.setFixedHeight(self.TOTAL_H)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def get(self):
        return self._snap(self._value)

    def set_value(self, v, notify=False):
        v = min(max(float(v), self.min), self.max)
        self._value = v
        if notify:
            self.valueChanged.emit(self.get())
        self.update()

    def set_display_sync(self, fn):
        self._sync_fn = fn

    def set_with_sync(self, v):
        self.set_value(v, notify=False)
        if getattr(self, "_sync_fn", None):
            self._sync_fn(self.get())

    def _snap(self, v):
        if self.step:
            return round(v / self.step) * self.step
        return v

    def _t(self):
        span = max(1e-6, self.max - self.min)
        return min(1.0, max(0.0, (self._value - self.min) / span))

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        cy = h / 2.0

        track = QtCore.QRectF(0, cy - self.TRACK_H / 2.0, w, self.TRACK_H)
        tp = QtGui.QPainterPath()
        tp.addRoundedRect(track, self.TRACK_H / 2, self.TRACK_H / 2)
        p.fillPath(tp, qcolor(COLOR_BG_INPUT))

        fill_w = (w - 2) * self._t()
        if fill_w > 0.5:
            fp = QtGui.QPainterPath()
            if fill_w >= w - 0.5:
                fp.addRoundedRect(QtCore.QRectF(0, cy - self.TRACK_H / 2.0,
                                                w, self.TRACK_H),
                                  self.TRACK_H / 2, self.TRACK_H / 2)
            else:
                fp.addRoundedRect(QtCore.QRectF(0, cy - self.TRACK_H / 2.0,
                                                fill_w + self.TRACK_H / 2.0,
                                                self.TRACK_H),
                                  self.TRACK_H / 2, self.TRACK_H / 2)
            p.fillPath(fp, qcolor(COLOR_ACCENT))

        kx = self.KNOB_W / 2.0 + (w - self.KNOB_W) * self._t()
        scale = 1.08 if self._dragging else (1.04 if self._hovered else 1.0)
        kw, kh = self.KNOB_W * scale, self.KNOB_H * scale
        kp = QtGui.QPainterPath()
        kp.addRoundedRect(QtCore.QRectF(kx - kw / 2.0, cy - kh / 2.0, kw, kh),
                          kh / 2.0, kh / 2.0)
        p.fillPath(kp, qcolor(COLOR_ACCENT_HOVER if self._hovered
                              else COLOR_ACCENT))
        p.end()

    def _pos_to_value(self, xf):
        span = max(1e-6, self.width() - self.KNOB_W)
        t = min(1.0, max(0.0, (xf - self.KNOB_W / 2.0) / span))
        return self.min + t * (self.max - self.min)

    def mousePressEvent(self, e):
        if e.button() == QtCore.Qt.LeftButton:
            self._dragging = True
            self.set_value(self._pos_to_value(e.position().x()), notify=True)

    def mouseMoveEvent(self, e):
        if self._dragging:
            self.set_value(self._pos_to_value(e.position().x()), notify=True)

    def mouseReleaseEvent(self, e):
        self._dragging = False
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()


class AnchorCombo(QtWidgets.QComboBox):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._popup_locked = False

    def _prep_popup(self):
        view = self.view()
        view.setMouseTracking(True)
        view.viewport().setMouseTracking(True)
        view.setStyleSheet(
            "QListView { background: #222222; color: #ffffff;"
            "border: 2px solid #4f5162; border-radius: 8px;"
            "padding: 6px; outline: 0; }"
            "QListView::item { min-height: 34px; padding-left: 10px;"
            "border-radius: 6px; margin: 1px 2px; }"
            "QListView::item:hover { background: #4a4e63;"
            "border: 1px solid #6a6f8a; color: #ffffff; }"
            "QListView::item:selected { background: #3f4356;"
            "color: #ffffff; }"
            "QListView::item:selected:hover { background: #5b6078;"
            "border: 1px solid #7d83a0; }")
        view.window().setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
        rows = max(1, self.count())
        row_h = max(32, view.sizeHintForRow(0) or 32)
        view.setFixedHeight(min(rows, 10) * row_h + 16)

    def showPopup(self):
        self._prep_popup()
        super().showPopup()
        try:
            popup = self.view().window()
            popup.move(self.mapToGlobal(QtCore.QPoint(0, self.height())))
            popup.setFixedWidth(max(self.width(), popup.sizeHint().width() + 4))
            popup.raise_()
        except Exception:
            pass


class Card(QtWidgets.QFrame):
    def __init__(self, title=None, subtitle=None, parent=None, fill=False):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"QFrame#Card {{ background: %s; border: 1px solid %s;"
            "border-radius: 12px; }"
            % (COLOR_BG_CARD, COLOR_BORDER)
        )
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        if title:
            head = QtWidgets.QFrame()
            head.setStyleSheet("background: transparent;")
            hl = QtWidgets.QHBoxLayout(head)
            hl.setContentsMargins(16, 14, 16, 6)
            hl.setSpacing(10)
            t = QtWidgets.QLabel(title.upper())
            t.setFont(B(13))
            t.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
            hl.addWidget(t)
            if subtitle:
                s = QtWidgets.QLabel(subtitle)
                s.setFont(F(11))
                s.setStyleSheet(f"color: {COLOR_TEXT_INACTIVE};")
                hl.addWidget(s)
                hl.addStretch(1)
            else:
                hl.addStretch(1)
            box.addWidget(head)
            sep = QtWidgets.QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(
                f"background: {COLOR_BORDER}; border: none;"
                "margin-left: 12px; margin-right: 12px;"
            )
            box.addWidget(sep)
            space = QtWidgets.QSpacerItem(4, 8)
            box.addItem(space)
        self.body = QtWidgets.QVBoxLayout()
        self.body.setContentsMargins(16, 0, 16, 14)
        self.body.setSpacing(6)
        if fill:
            box.addLayout(self.body, 1)
        else:
            box.addLayout(self.body)


class FlowLayout(QtWidgets.QLayout):

    def __init__(self, parent=None, spacing=6):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self._spacing = spacing
        self._items = []

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        if 0 <= i < len(self._items):
            return self._items[i]
        return None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            return self._items.pop(i)
        return None

    def expandingDirections(self):
        return QtCore.Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do_layout(QtCore.QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QtCore.QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _do_layout(self, rect, test_only):
        x, y = rect.x(), rect.y()
        row_h = 0
        limit = rect.right()
        for item in self._items:
            hint = item.sizeHint()
            if x + hint.width() > limit and row_h > 0:
                x = rect.x()
                y += row_h + self._spacing
                row_h = 0
            if not test_only:
                item.setGeometry(QtCore.QRect(QtCore.QPoint(x, y), hint))
            x += hint.width() + self._spacing
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + self._spacing


def _grow_chip(chip, final_w):
    chip.setMaximumWidth(0)
    a = QtCore.QVariantAnimation(chip)
    a.setStartValue(0)
    a.setEndValue(final_w)
    a.setDuration(150)
    a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
    def _grow(v):
        chip.setMinimumWidth(0)
        chip.setMaximumWidth(int(v) + 2)
    def _grown():
        chip.setMinimumWidth(0)
        chip.setMaximumWidth(16777215)
    a.valueChanged.connect(_grow)
    a.finished.connect(_grown)
    a.finished.connect(a.deleteLater)
    a.start()


def _shrink_remove(chip, on_done=None):
    target_w = max(chip.width(), chip.sizeHint().width())
    chip.setFixedSize(target_w, chip.height())
    a = QtCore.QVariantAnimation(chip)
    a.setStartValue(target_w)
    a.setEndValue(0)
    a.setDuration(120)
    a.setEasingCurve(QtCore.QEasingCurve.InCubic)
    def _shrink(v):
        chip.setFixedSize(max(1, int(v)), chip.height())
    def _gone():
        chip.deleteLater()
        if on_done is not None:
            QtCore.QTimer.singleShot(10, on_done)
    a.valueChanged.connect(_shrink)
    a.finished.connect(_gone)
    a.finished.connect(a.deleteLater)
    a.start()


class TagChipWidget(QtWidgets.QFrame):
    removed = QtCore.Signal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self.tag = tag
        self.setStyleSheet(
            f"background: {COLOR_BG_HOVER}; border: 1px solid {COLOR_BORDER_HOVER};"
            "border-radius: 6px;"
        )
        hl = QtWidgets.QHBoxLayout(self)
        hl.setContentsMargins(8, 1, 4, 1)
        hl.setSpacing(2)
        lbl = QtWidgets.QLabel(tag)
        lbl.setFont(F(11))
        lbl.setStyleSheet(f"color: {COLOR_TEXT_WHITE}; border: none;")
        hl.addWidget(lbl)
        x = QtWidgets.QLabel("✕")
        x.setFont(F(9))
        x.setStyleSheet(f"color: {COLOR_TEXT_MUTED}; border: none;")
        x.setCursor(QtCore.Qt.PointingHandCursor)
        x.mousePressEvent = lambda e: self.removed.emit(tag)
        hl.addWidget(x)


class TagChipInput(QtWidgets.QFrame):
    changed = QtCore.Signal()

    def __init__(self, placeholder="Type a tag and press Enter...", *,
                 parent=None, blocked_fn=None):
        super().__init__(parent)
        self.setObjectName("TagChipInput")
        self.setStyleSheet(
            "QFrame#TagChipInput { background: %s; border: 1px solid %s;"
            "border-radius: 8px; }\n"
            "QFrame#TagChipInput:focus { border-color: %s; }"
            % (COLOR_BG_INPUT, COLOR_BORDER, COLOR_BORDER_HOVER)
        )
        self.blocked_fn = blocked_fn
        self.tags = []
        self._chips = {}
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(7, 4, 7, 3)
        box.setSpacing(4)
        self.chips_holder = QtWidgets.QWidget()
        self.chips_holder.setStyleSheet("background: transparent;")
        self.chips_layout = FlowLayout(self.chips_holder, spacing=6)
        box.addWidget(self.chips_holder)
        self.chips_holder.hide()
        self.entry = QtWidgets.QLineEdit()
        self.entry.setPlaceholderText(self._smart_placeholder(placeholder))
        self.entry.setFont(F(12))
        self.entry.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f"outline: none; color: {COLOR_TEXT_WHITE}; }}")
        pal = self.entry.palette()
        pal.setColor(QtGui.QPalette.PlaceholderText, qcolor(COLOR_TEXT_MUTED))
        self.entry.setPalette(pal)
        box.addWidget(self.entry)
        self.entry.returnPressed.connect(self.commit)
        self.entry.installEventFilter(self)
        self.mousePressEvent = self._focus_entry

    def _smart_placeholder(self, placeholder):
        return placeholder

    def _flash_blocked(self, tag: str):
        fg = COLOR_RED
        chip = QtWidgets.QFrame(self.chips_holder)
        chip.setObjectName("BlockedChip")
        chip.setStyleSheet(
            "QFrame#BlockedChip { background: rgba(224, 85, 85, 40);"
            "border: 1px solid #e05555; border-radius: 6px; }")
        hl = QtWidgets.QHBoxLayout(chip)
        hl.setContentsMargins(10, 2, 10, 2)
        lbl = QtWidgets.QLabel(f"BLOCKED: {tag[:26]}")
        lbl.setFont(F(9))
        lbl.setStyleSheet(f"color: {fg}; border: none; background: transparent;")
        hl.addWidget(lbl)
        self.chips_layout.addWidget(chip)
        self.chips_holder.show()
        QtCore.QTimer.singleShot(1600, self._relayout)
        QtCore.QTimer.singleShot(1500, chip.deleteLater)

    def _focus_entry(self, ev):
        self.entry.setFocus()
        ev.accept()

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and obj is self.entry:
            if ev.key() == QtCore.Qt.Key_Backspace and self.entry.text() == "" \
                    and self.tags:
                self.remove_tag(self.tags[-1])
                return True
        return super().eventFilter(obj, ev)

    def get(self):
        return " ".join(self.tags)

    def insert(self, index, text):
        self.set_line(text)

    def delete(self, first=0, last=None):
        self.clear()

    def set_line(self, text):
        self.clear()
        for token in str(text or "").replace(",", " ").split():
            self.add_tag(token, notify=False)

    def add_tag(self, tag, notify=True):
        tag = str(tag or "").strip().replace(" ", "_").lower().strip(",")
        if not tag or tag.lower() in [t.lower() for t in self.tags]:
            return False
        if self.blocked_fn is not None and self.blocked_fn(tag):
            self._flash_blocked(tag)
            return False
        self.tags.append(tag)
        chip = TagChipWidget(tag)
        chip.removed.connect(self.remove_tag)
        self._chips[tag.lower()] = chip
        self.chips_layout.addWidget(chip)
        _grow_chip(chip, max(chip.sizeHint().width(), 60))
        self.chips_holder.show()
        self.chips_holder.adjustSize()
        self.adjustSize()
        if notify:
            self.changed.emit()
        return True

    def remove_tag(self, tag):
        key = tag.lower()
        if key not in [t.lower() for t in self.tags]:
            return
        self.tags = [t for t in self.tags if t.lower() != key]
        chip = self._chips.pop(key, None)
        if chip is not None:
            _shrink_remove(chip, self._relayout)
        self.changed.emit()

    def _relayout(self):
        self.chips_holder.adjustSize()
        self.adjustSize()

    def clear(self):
        self.tags.clear()
        for chip in self._chips.values():
            try:
                chip.deleteLater()
            except Exception:
                pass
        self._chips.clear()
        while self.chips_layout.count():
            self.chips_layout.takeAt(0)
        self.chips_holder.hide()
        self.entry.clear()
        self._relayout()

    def commit(self):
        raw = self.entry.text().strip()
        if not raw:
            return
        self.entry.clear()
        for part in raw.split(","):
            self.add_tag(part)

    def keyPressEvent(self, e):
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self.commit()
        super().keyPressEvent(e)


class GlowBar(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = 0.0
        self._target = 0.0
        self._running = False
        self._flash = None
        self._phase = 0.0
        self._tick = QtCore.QTimer(self)
        self._tick.timeout.connect(self._on_tick)
        self._tick.setInterval(16)
        self.setFixedHeight(9)

    def set_instant(self, v):
        self._value = self._target = float(min(max(v, 0.0), 1.0))
        self.update()

    def set_target(self, v):
        self._target = float(min(max(v, 0.0), 1.0))
        if not self._tick.isActive():
            self._tick.start()

    def set_running(self, running: bool):
        self._running = running
        self._phase = 0.0
        self.update()

    def finish_flash(self):
        self._running = False
        self._flash = "success"
        self.set_target(1.0)
        QtCore.QTimer.singleShot(900, self._back_to_neutral)

    def error_state(self):
        self._running = False
        self._flash = None
        self.set_target(0.0)

    def _back_to_neutral(self):
        if self._flash == "success":
            self._flash = None
            self.update()

    def _on_tick(self):
        diff = self._target - self._value
        if abs(diff) > 0.0015:
            self._value += diff * 0.2
        else:
            self._value = self._target
        self._phase += 0.016
        if abs(self._target - self._value) < 0.0015 and not self._running:
            self._tick.stop()
        self.update()

    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)
        w, h = self.width(), self.height()
        bg = QtGui.QPainterPath()
        bg.addRoundedRect(QtCore.QRectF(0, 0, w, h), h / 2, h / 2)
        p.fillPath(bg, qcolor(COLOR_BG_INPUT))
        if self._value > 0.002:
            color = qcolor(COLOR_ACCENT)
            if self._flash == "success":
                color = qcolor(COLOR_SUCCESS)
            elif self._running:
                f = 0.5 - 0.5 * math.cos(2 * math.pi * (self._phase / 1.6))
                color = lerp_color("#5b5e73", COLOR_ACCENT, f)
            chunk = QtGui.QPainterPath()
            chunk.addRoundedRect(QtCore.QRectF(0, 0, int(w * self._value), h),
                                 h / 2, h / 2)
            p.fillPath(chunk, color)
        if self._flash == "success":
            soft = QtGui.QPainterPath()
            soft.addRoundedRect(QtCore.QRectF(0, 0, w, h), h / 2, h / 2)
            p.fillPath(soft, rgba(COLOR_SUCCESS, 28))
        p.end()


class RollingCounter(QtCore.QObject):

    def __init__(self, setter):
        super().__init__()
        self._setter = setter
        self._template = lambda n: str(n)
        self._current = 0.0
        self._anim = None

    def set_template(self, template):
        self._template = template

    def set_static(self, text, template=None):
        self.stop()
        if template is not None:
            self._template = template
        self._current = 0.0
        self._apply(int(self._current))

    def _safe_stop(self):
        if self._anim is not None:
            try:
                self._anim.stop()
            except RuntimeError:
                pass
            self._anim = None

    def chase(self, target: int):
        self._safe_stop()
        a = QtCore.QVariantAnimation(self)
        a.setStartValue(float(self._current))
        a.setEndValue(float(target))
        a.setDuration(450)
        a.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        a.valueChanged.connect(self._on_value)
        a.finished.connect(a.deleteLater)
        a.start()
        self._anim = a

    def snap(self, target: int):
        self._safe_stop()
        self._current = float(target)
        self._apply(int(target))

    def stop(self):
        self._safe_stop()

    def _on_value(self, v):
        self._current = float(v)
        self._apply(int(round(v)))

    def _apply(self, n):
        try:
            self._setter(self._template(n))
        except Exception:
            pass


def _rgb_str(hex_str):
    h = hex_str.lstrip("#")
    return ", ".join(str(int(h[i:i + 2], 16)) for i in (0, 2, 4))


_RESULT_SCROLL_STYLE = (
    "QScrollArea { background: transparent; border: none; }"
    f"QScrollBar:vertical {{ background: transparent; width: 9px; margin: 0; }}"
    f"QScrollBar::handle:vertical {{ background: {COLOR_BORDER_HOVER};"
    "border-radius: 4px; min-height: 24px; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
)


class TagResultView(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet(_RESULT_SCROLL_STYLE)
        self.inner = QtWidgets.QWidget()
        self.inner.setStyleSheet("background: transparent;")
        self.v = QtWidgets.QVBoxLayout(self.inner)
        self.v.setContentsMargins(2, 4, 6, 6)
        self.v.setSpacing(8)
        self.v.setAlignment(QtCore.Qt.AlignTop)
        self.scroll.setWidget(self.inner)
        box.addWidget(self.scroll)

    def clear(self):
        while self.v.count():
            item = self.v.takeAt(0)
            w = item.widget() if item else None
            lay = item.layout() if item else None
            if lay is not None:
                while lay.count():
                    c = lay.takeAt(0)
                    if c is not None and c.widget() is not None:
                        c.widget().deleteLater()
            if w is not None:
                w.deleteLater()
        self.inner.updateGeometry()

    def show_message(self, text):
        self.clear()
        lbl = QtWidgets.QLabel(text)
        lbl.setFont(F(10))
        lbl.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        lbl.setAlignment(QtCore.Qt.AlignCenter)
        lbl.setFont(F(11))
        self.v.addWidget(lbl, 0, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)
        self.v.addStretch(1)

    def _kv_row(self, key, value, value_color=COLOR_TEXT_WHITE):
        row = QtWidgets.QWidget()
        row.setStyleSheet("background: transparent;")
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(14, 2, 14, 2)
        k = QtWidgets.QLabel(key)
        k.setFont(F(9))
        k.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
        h.addWidget(k)
        h.addStretch(1)
        v = QtWidgets.QLabel(value)
        v.setFont(F(11))
        v.setStyleSheet(f"color: {value_color};")
        h.addWidget(v)
        return row

    def _chip(self, text, bg_hex, fg_hex):
        chip = QtWidgets.QLabel(text)
        chip.setFont(F(8))
        chip.setStyleSheet(
            f"QLabel {{ background: rgba({_rgb_str(bg_hex)}, 30); color: {fg_hex};"
            "border-radius: 3px; padding: 2px 7px; }")
        return chip

    def show_result(self, query, details, suggestions):
        self.clear()

        head = QtWidgets.QWidget()
        head.setStyleSheet("background: transparent;")
        hh = QtWidgets.QHBoxLayout(head)
        hh.setContentsMargins(4, 2, 4, 4)
        hh.setSpacing(10)
        name = QtWidgets.QLabel(str(query))
        name.setFont(B(13))
        name.setStyleSheet(f"color: {COLOR_TEXT_WHITE};")
        hh.addWidget(name)
        exists = bool(details.get("exists"))
        hh.addWidget(self._chip(i18n.tr("FOUND") if exists else i18n.tr("NOT FOUND"),
                                "#4ade80" if exists else "#e05555",
                                "#4ade80" if exists else "#ff9696"))
        if details.get("is_deprecated"):
            hh.addWidget(self._chip(i18n.tr("DEPRECATED"), "#f59e0b", "#f59e0b"))
        hh.addStretch(1)
        self.v.addWidget(head)

        box = QtWidgets.QFrame()
        box.setObjectName("TagDetailBox")
        box.setStyleSheet(
            f"QFrame#TagDetailBox {{ background: {COLOR_BG_CARD_INNER};"
            f"border: 1px solid {COLOR_BORDER}; border-radius: 10px; }}")
        bv = QtWidgets.QVBoxLayout(box)
        bv.setContentsMargins(4, 6, 4, 8)
        bv.setSpacing(2)
        pc = details.get("post_count")
        if pc is not None:
            inner = QtWidgets.QWidget()
            inner.setStyleSheet("background: transparent;")
            il = QtWidgets.QVBoxLayout(inner)
            il.setContentsMargins(0, 0, 0, 0)
            il.setSpacing(2)
            il.addWidget(self._kv_row(i18n.tr("POST COUNT"), f"{pc:,}"))
            il.addWidget(self._kv_row(i18n.tr("CATEGORY"),
                                      str(details.get("category_name", "General"))))
            if details.get("suggestion"):
                il.addWidget(self._kv_row(
                    i18n.tr("DID YOU MEAN"),
                    f"{details.get('suggestion')}  "
                    f"({details.get('suggestion_count', 0):,} posts)",
                    value_color="#f59e0b"))
            bv.addWidget(inner)
        else:
            empty = QtWidgets.QLabel(i18n.tr("No details available for this tag."))
            empty.setFont(F(10))
            empty.setStyleSheet(
                f"color: {COLOR_TEXT_MUTED}; background: transparent;")
            empty.setContentsMargins(14, 2, 14, 2)
            bv.addWidget(empty)
        if details.get("is_deprecated"):
            warn = QtWidgets.QLabel(i18n.tr("Warning: this tag is deprecated on Danbooru!"))
            warn.setFont(F(10))
            warn.setStyleSheet(f"color: #f59e0b; background: transparent;")
            warn.setContentsMargins(14, 0, 14, 0)
            bv.addWidget(warn)
        self.v.addWidget(box)

        if suggestions:
            hdr = QtWidgets.QLabel(i18n.tr("SUGGESTIONS") + f" ({len(suggestions)})")
            hdr.setFont(F(9))
            hdr.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            hdr.setContentsMargins(6, 4, 0, 0)
            self.v.addWidget(hdr)
            for s in suggestions:
                row = QtWidgets.QFrame()
                row.setObjectName("TagRow")
                row.setStyleSheet(
                    f"QFrame#TagRow {{ background: {COLOR_BG_CARD_INNER};"
                    f"border: 1px solid {COLOR_BORDER}; border-radius: 8px; }}"
                    f"QFrame#TagRow:hover {{ background: #24252c;"
                    f"border-color: {COLOR_BORDER_HOVER}; }}")
                rh = QtWidgets.QHBoxLayout(row)
                rh.setContentsMargins(14, 8, 14, 8)
                rh.setSpacing(8)
                tag_val = str(s.get("value", ""))
                nm = QtWidgets.QLabel(tag_val)
                nm.setFont(F(11))
                nm.setStyleSheet(
                    f"color: {COLOR_TEXT_WHITE}; border: none; background: transparent;")
                rh.addWidget(nm)
                if s.get("is_autocorrect"):
                    rh.addWidget(self._chip("AUTOCORRECT",
                                            "#82849e", COLOR_TEXT_MUTED))
                rh.addStretch(1)
                cat = QtWidgets.QLabel(
                    str(s.get("category_name", "General")).lower())
                cat.setFont(F(9))
                cat.setStyleSheet(
                    f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;")
                rh.addWidget(cat)
                cnt = QtWidgets.QLabel(f"{s.get('post_count', 0):,} posts")
                cnt.setFont(F(9))
                cnt.setStyleSheet(
                    f"color: {COLOR_TEXT_MUTED}; border: none; background: transparent;")
                rh.addWidget(cnt, 0, QtCore.Qt.AlignRight)

                def _copy_suggestion(ev=None, tag=tag_val, frame=row):
                    QtWidgets.QApplication.clipboard().setText(tag)
                    try:
                        copied = self._chip(i18n.tr("COPIED"), "#4ade80", COLOR_TEXT_WHITE)
                        frame.layout().insertWidget(1, copied)
                        QtCore.QTimer.singleShot(1100, copied.deleteLater)
                    except RuntimeError:
                        pass

                row.setCursor(QtCore.Qt.PointingHandCursor)
                row.setToolTip(f"Click to copy '{tag_val}' - then paste it "
                               "into the downloader or preview search")
                row.mousePressEvent = _copy_suggestion
                self.v.addWidget(row)
        else:
            none = QtWidgets.QLabel(i18n.tr("No autocomplete suggestions."))
            none.setFont(F(10))
            none.setStyleSheet(f"color: {COLOR_TEXT_MUTED};")
            none.setContentsMargins(6, 2, 0, 2)
            self.v.addWidget(none)

        self.v.addStretch(1)
        self.inner.updateGeometry()
        self.scroll.verticalScrollBar().setValue(0)

    def show_multi(self, results):
        first = True
        for query, details, suggestions in (results or []):
            if not first:
                sep = QtWidgets.QFrame()
                sep.setFixedHeight(1)
                sep.setStyleSheet(f"background: {COLOR_BORDER}; border: none;"
                                  "margin: 6px 2px;")
                self.v.addWidget(sep)
            first = False
            self.show_result(query, details, suggestions)
        self.inner.updateGeometry()
        self.scroll.verticalScrollBar().setValue(0)


class Toast(QtWidgets.QWidget):

    dismissed = QtCore.Signal(object)

    PAD_T = 14
    PAD_B = 14
    TEXT_X = 52

    def __init__(self, parent, title, message, *, kind="error",
                 duration=4200, width=364):
        super().__init__(parent)
        self._title = (title or "").strip()
        self._message = (message or "").strip()
        self._kind = kind
        self._duration = max(1200, int(duration))
        self._opacity = 0.0
        self._progress = 0.0
        self._closing = False
        self._finished = False
        self._slide = None
        self._progress_anim = None

        base = {"error": COLOR_DANGER, "warning": COLOR_WARN,
                "success": COLOR_SUCCESS}.get(kind, COLOR_ACCENT)
        self._accent = qcolor(base)

        self._title_font = B(11)
        self._msg_font = F(10)
        text_w = width - self.TEXT_X - 18
        self._text_w = text_w
        fm_t = QtGui.QFontMetrics(self._title_font)
        fm_m = QtGui.QFontMetrics(self._msg_font)
        self._title_h = fm_t.height()
        if self._message:
            self._msg_h = fm_m.boundingRect(
                QtCore.QRect(0, 0, text_w, 2000),
                QtCore.Qt.TextWordWrap | QtCore.Qt.AlignLeft,
                self._message).height()
        else:
            self._msg_h = 0
        gap = 5 if self._message else 0
        height = self.PAD_T + self._title_h + gap + self._msg_h + self.PAD_B
        self.setFixedSize(width, max(72, height))

        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip("Click to dismiss")


    def show_in(self, rest_pos):
        self._rest_pos = QtCore.QPoint(rest_pos)
        parent = self.parentWidget()
        start_x = (parent.width() + 10) if parent is not None \
            else self._rest_pos.x() + 60
        self.move(start_x, self._rest_pos.y())
        self.show()
        self.raise_()

        slide = QtCore.QPropertyAnimation(self, b"pos", self)
        slide.setDuration(300)
        slide.setStartValue(QtCore.QPoint(start_x, self._rest_pos.y()))
        slide.setEndValue(self._rest_pos)
        slide.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        slide.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._slide = slide

        fade = QtCore.QVariantAnimation(self)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setDuration(240)
        fade.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        fade.valueChanged.connect(self._set_opacity)
        fade.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._fade = fade

        QtCore.QTimer.singleShot(250, self._start_progress)

    def _start_progress(self):
        if self._closing:
            return
        anim = QtCore.QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(self._duration)
        anim.setEasingCurve(QtCore.QEasingCurve.Linear)
        anim.valueChanged.connect(self._set_progress)
        anim.finished.connect(self.dismiss)
        anim.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._progress_anim = anim

    def dismiss(self):
        if self._closing:
            return
        self._closing = True
        for anim in (self._progress_anim,):
            try:
                if anim is not None:
                    anim.stop()
            except Exception:
                pass

        parent = self.parentWidget()
        end_x = (parent.width() + 14) if parent is not None else self.x() + 80
        slide = QtCore.QPropertyAnimation(self, b"pos", self)
        slide.setDuration(240)
        slide.setStartValue(self.pos())
        slide.setEndValue(QtCore.QPoint(end_x, self.y()))
        slide.setEasingCurve(QtCore.QEasingCurve.InCubic)
        slide.finished.connect(self._done)
        slide.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._slide = slide
        QtCore.QTimer.singleShot(360, self._done)

        fade = QtCore.QVariantAnimation(self)
        fade.setStartValue(self._opacity)
        fade.setEndValue(0.0)
        fade.setDuration(220)
        fade.setEasingCurve(QtCore.QEasingCurve.InCubic)
        fade.valueChanged.connect(self._set_opacity)
        fade.start(QtCore.QAbstractAnimation.DeleteWhenStopped)
        self._fade = fade

    def _done(self):
        if self._finished:
            return
        self._finished = True
        try:
            self.dismissed.emit(self)
        except Exception:
            pass
        self.hide()
        self.deleteLater()


    def _set_opacity(self, value):
        self._opacity = float(value)
        self.update()

    def _set_progress(self, value):
        self._progress = float(value)
        self.update()

    def mousePressEvent(self, ev):
        self.dismiss()
        ev.accept()


    def paintEvent(self, ev):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        p.setOpacity(max(0.0, min(1.0, self._opacity)))

        card = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        p.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 44), 1.0))
        p.setBrush(QtGui.QColor(28, 28, 34, 252))
        p.drawRoundedRect(card, 11.0, 11.0)

        track = QtCore.QRectF(10.0, self.height() - 8.0,
                              self.width() - 20.0, 3.0)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(QtGui.QColor(255, 255, 255, 16))
        p.drawRoundedRect(track, 1.5, 1.5)
        if self._progress > 0.001:
            fill = QtCore.QRectF(track)
            fill.setWidth(track.width() * min(1.0, self._progress))
            radius = min(1.5, fill.width() / 2.0)
            p.setBrush(self._accent)
            p.drawRoundedRect(fill, radius, radius)

        col = self._accent
        cx, cy = 18.0, float(self.PAD_T)
        icon = QtCore.QRectF(cx, cy, 22.0, 22.0)
        p.setBrush(QtGui.QColor(col.red(), col.green(), col.blue(), 38))
        p.setPen(QtGui.QPen(
            QtGui.QColor(col.red(), col.green(), col.blue(), 155), 1.2))
        p.drawEllipse(icon)
        if self._kind == "success":
            p.setPen(QtGui.QPen(col, 2.0, QtCore.Qt.SolidLine,
                                QtCore.Qt.RoundCap))
            p.drawLine(QtCore.QPointF(cx + 6.3, cy + 11.4),
                       QtCore.QPointF(cx + 9.7, cy + 14.8))
            p.drawLine(QtCore.QPointF(cx + 9.7, cy + 14.8),
                       QtCore.QPointF(cx + 15.6, cy + 7.4))
        elif self._kind == "info":
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QtCore.QPointF(cx + 11.0, cy + 6.5), 1.35, 1.35)
            p.setPen(QtGui.QPen(col, 2.0, QtCore.Qt.SolidLine,
                                QtCore.Qt.RoundCap))
            p.drawLine(QtCore.QPointF(cx + 11.0, cy + 10.0),
                       QtCore.QPointF(cx + 11.0, cy + 15.7))
        else:
            p.setPen(QtGui.QPen(col, 2.0, QtCore.Qt.SolidLine,
                                QtCore.Qt.RoundCap))
            p.drawLine(QtCore.QPointF(cx + 11.0, cy + 6.2),
                       QtCore.QPointF(cx + 11.0, cy + 12.4))
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            p.drawEllipse(QtCore.QPointF(cx + 11.0, cy + 16.2), 1.35, 1.35)

        p.setPen(QtGui.QColor(255, 255, 255))
        p.setFont(self._title_font)
        p.drawText(QtCore.QRectF(self.TEXT_X, self.PAD_T - 1.0,
                                 self._text_w, float(self._title_h)),
                   QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self._title)

        if self._message:
            p.setPen(QtGui.QColor(0x9a, 0x9c, 0xae))
            p.setFont(self._msg_font)
            p.drawText(QtCore.QRectF(self.TEXT_X,
                                     self.PAD_T + self._title_h + 4.0,
                                     self._text_w, float(self._msg_h) + 2.0),
                       QtCore.Qt.AlignLeft | QtCore.Qt.TextWordWrap,
                       self._message)
        p.end()
