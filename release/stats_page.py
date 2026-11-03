import os
import shutil
import threading
import time
from collections import Counter
from datetime import datetime, timedelta

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import (
    QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
)

import i18n
from qt_theme import B, F


CARD_BG = "#1c1c1e"
CARD_BG_SOFT = "#242427"
TEXT = "#f5f5f7"
MUTED = "#8e8e93"
FAINT = "rgba(255, 255, 255, 0.07)"
ACCENTS = ["#0a84ff", "#30d158", "#ff375f", "#ff9f0a",
           "#bf5af2", "#64d2ff", "#ffd60a", "#ff6482"]

MEDIA_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp", "avif",
              "mp4", "webm"}

SKIP_DIRS = {"_internal", "assets", "icons", "fonts", "images", "sounds",
             "east", "credits", "__pycache__", "release", "windows release",
             "gui", "tools", "new credits gifs"}

CARD_QSS = (
    "QFrame#StatCard { background: %s; border: 1px solid %s;"
    "border-radius: 16px; }" % (CARD_BG, FAINT)
)


def human_size(num):
    num = float(num or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024.0 or unit == "TB":
            if unit == "B":
                return "%d B" % int(num)
            return "%.1f %s" % (num, unit)
        num /= 1024.0


def human_ago(ts):
    if not ts:
        return i18n.tr("Never")
    delta = max(0, int(time.time() - ts))
    if delta < 60:
        return i18n.tr("just now")
    if delta < 3600:
        return "%d %s" % (delta // 60, i18n.tr("min ago"))
    if delta < 86400:
        return "%d %s" % (delta // 3600, i18n.tr("h ago"))
    if delta < 86400 * 7:
        return "%d %s" % (delta // 86400, i18n.tr("days ago"))
    return datetime.fromtimestamp(ts).strftime("%b %d, %Y")



def collect_stats(folder):
    now = datetime.now()
    today = now.date()
    files = []
    if folder and os.path.isdir(folder):
        base = folder.rstrip("\\/")
        base_depth = base.count(os.sep)
        for root, dirs, names in os.walk(folder):
            depth = root.rstrip("\\/").count(os.sep) - base_depth
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_DIRS]
            if depth >= 2:
                dirs[:] = []
            for name in names:
                ext = os.path.splitext(name)[1].lower().lstrip(".")
                if ext not in MEDIA_EXTS:
                    continue
                path = os.path.join(root, name)
                try:
                    st = os.stat(path)
                except OSError:
                    continue
                parent = os.path.basename(root.rstrip("\\/")) or folder
                files.append({
                    "path": path,
                    "name": name,
                    "ext": ext,
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                    "folder": parent,
                })

    total_bytes = sum(f["size"] for f in files)
    formats = Counter(f["ext"] for f in files)
    folders = Counter(f["folder"] for f in files)

    days = Counter()
    for f in files:
        days[datetime.fromtimestamp(f["mtime"]).date()] += 1

    series = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        series.append((d, days.get(d, 0)))

    week = sum(count for d, count in series[-7:])
    last = max((f["mtime"] for f in files), default=0)
    last_file = max(files, key=lambda f: f["mtime"])["name"] if files else ""
    largest = max(files, key=lambda f: f["size"]) if files else None
    free = 0
    try:
        probe = folder if (folder and os.path.isdir(folder)) else os.getcwd()
        free = shutil.disk_usage(probe).free
    except Exception:
        pass

    return {
        "folder": folder,
        "count": len(files),
        "bytes": total_bytes,
        "avg": (total_bytes / len(files)) if files else 0,
        "week": week,
        "last": last,
        "last_file": last_file,
        "formats": formats.most_common(),
        "folders": folders.most_common(7),
        "series": series,
        "largest": largest,
        "free": free,
        "folders_count": len(folders),
    }



class StatCard(QtWidgets.QFrame):

    def __init__(self, label, accent, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(CARD_QSS)
        self.setMinimumHeight(104)
        self._accent = QColor(accent)
        box = QtWidgets.QVBoxLayout(self)
        box.setContentsMargins(18, 15, 18, 15)
        box.setSpacing(6)

        head = QtWidgets.QWidget()
        head.setStyleSheet("background: transparent;")
        hl = QtWidgets.QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(7)
        dot = QtWidgets.QWidget()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(
            "background: %s; border-radius: 3px;" % accent)
        hl.addWidget(dot, 0, Qt.AlignVCenter)
        self.lbl_label = QtWidgets.QLabel(label.upper())
        self.lbl_label.setFont(B(9))
        self.lbl_label.setStyleSheet(
            "color: %s; letter-spacing: 1px; background: transparent;"
            % MUTED)
        hl.addWidget(self.lbl_label)
        hl.addStretch(1)
        box.addWidget(head)

        self.lbl_value = QtWidgets.QLabel("-")
        self.lbl_value._i18n_dynamic = True
        self.lbl_value.setFont(B(25))
        self.lbl_value.setStyleSheet(
            "color: %s; background: transparent;" % TEXT)
        box.addWidget(self.lbl_value)

        self.lbl_sub = QtWidgets.QLabel("")
        self.lbl_sub._i18n_dynamic = True
        self.lbl_sub.setFont(F(9))
        self.lbl_sub.setStyleSheet(
            "color: %s; background: transparent;" % MUTED)
        box.addWidget(self.lbl_sub)
        box.addStretch(1)

    def set(self, value, sub=""):
        self.lbl_value.setText(str(value))
        self.lbl_sub.setText(sub)


class CardFrame(QtWidgets.QFrame):

    def __init__(self, title=None, subtitle=None, parent=None):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setStyleSheet(CARD_QSS)
        self._box = QtWidgets.QVBoxLayout(self)
        self._box.setContentsMargins(18, 15, 18, 15)
        self._box.setSpacing(10)
        if title:
            head = QtWidgets.QHBoxLayout()
            head.setSpacing(8)
            t = QtWidgets.QLabel(title.upper())
            t.setFont(B(9))
            t.setStyleSheet(
                "color: %s; letter-spacing: 1px; background: transparent;"
                % MUTED)
            head.addWidget(t)
            if subtitle:
                s = QtWidgets.QLabel(subtitle)
                s.setFont(F(9))
                s.setStyleSheet(
                    "color: %s; background: transparent;" % MUTED)
                head.addWidget(s)
            head.addStretch(1)
            self._box.addLayout(head)
        self.body = self._box



class ActivityChart(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series = []
        self._accent = QColor(ACCENTS[0])
        self.setMinimumHeight(170)

    def set_series(self, series):
        self._series = list(series or [])
        self.update()

    def _path(self, pts):
        path = QPainterPath(pts[0])
        for i in range(len(pts) - 1):
            p0 = pts[i - 1] if i > 0 else pts[i]
            p1 = pts[i]
            p2 = pts[i + 1]
            p3 = pts[i + 2] if i + 2 < len(pts) else p2
            c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                         p1.y() + (p2.y() - p0.y()) / 6.0)
            c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                         p2.y() - (p3.y() - p1.y()) / 6.0)
            path.cubicTo(c1, c2, p2)
        return path

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        w, h = self.width(), self.height()
        plot = QRectF(6, 10, max(1, w - 12), max(1, h - 34))
        if not self._series:
            p.setPen(QColor(MUTED))
            p.setFont(F(10))
            p.drawText(self.rect(), Qt.AlignCenter,
                       i18n.tr("No downloads yet"))
            return

        counts = [c for _d, c in self._series]
        if not any(counts):
            p.setPen(QColor(MUTED))
            p.setFont(F(10))
            p.drawText(self.rect(), Qt.AlignCenter,
                       i18n.tr("No downloads yet"))
            return
        vmax = max(1, max(counts))

        grid = QPen(QColor(255, 255, 255, 14))
        grid.setWidthF(1.0)
        p.setPen(grid)
        for i in range(4):
            y = plot.top() + plot.height() * i / 3.0
            p.drawLine(QPointF(plot.left(), y),
                       QPointF(plot.right(), y))

        n = len(self._series)
        pts = []
        for i, (_d, count) in enumerate(self._series):
            x = plot.left() + plot.width() * (i / float(max(1, n - 1)))
            y = plot.bottom() - plot.height() * (count / float(vmax))
            pts.append(QPointF(x, y))

        line = self._path(pts)
        area = QPainterPath(line)
        area.lineTo(pts[-1].x(), plot.bottom())
        area.lineTo(pts[0].x(), plot.bottom())
        area.closeSubpath()
        grad = QLinearGradient(0, plot.top(), 0, plot.bottom())
        grad.setColorAt(0.0, QColor(10, 132, 255, 95))
        grad.setColorAt(1.0, QColor(10, 132, 255, 0))
        p.fillPath(area, grad)

        p.setPen(QPen(self._accent, 2.0, Qt.SolidLine,
                      Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(line)

        p.setPen(QPen(QColor("#141416"), 1.5))
        p.setBrush(self._accent)
        for pt in pts:
            p.drawEllipse(pt, 2.7, 2.7)

        p.setFont(F(8))
        p.setPen(QColor(MUTED))
        for i in range(0, n, 7):
            if n - 1 - i < 4:
                continue
            d = self._series[i][0]
            lx = min(max(pts[i].x() - 32, 0), w - 64)
            p.drawText(QRectF(lx, plot.bottom() + 8, 64, 16),
                       Qt.AlignHCenter, d.strftime("%b %d"))
        d = self._series[-1][0]
        lx = min(max(pts[-1].x() - 32, 0), w - 64)
        p.drawText(QRectF(lx, plot.bottom() + 8, 64, 16),
                   Qt.AlignHCenter, d.strftime("%b %d"))

        p.setFont(F(8))
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(plot.right() - 46, plot.top() - 2, 46, 14),
                   Qt.AlignRight, str(max(counts)))


class DonutChart(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setMinimumSize(150, 150)

    def set_items(self, items):
        self._items = list(items or [])
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        side = min(self.width(), self.height()) - 14
        rect = QRectF((self.width() - side) / 2.0,
                      (self.height() - side) / 2.0, side, side)
        rect = rect.adjusted(9, 9, -9, -9)
        total = sum(v for _k, v, _c in self._items)
        if total <= 0:
            p.setPen(QPen(QColor(255, 255, 255, 18), 14))
            p.drawEllipse(rect)
            p.setPen(QColor(MUTED))
            p.setFont(F(9))
            p.drawText(self.rect(), Qt.AlignCenter,
                       i18n.tr("No data yet"))
            return

        start = -90 * 16
        gap = 1.6 * 16 if len(self._items) > 1 else 0
        for _key, value, color in self._items:
            span = 360 * 16 * (value / float(total))
            p.setPen(QPen(QColor(color), 14, Qt.SolidLine, Qt.FlatCap))
            p.drawArc(rect, int(start + gap / 2),
                      max(1, int(span - gap)))
            start += span

        p.setPen(QColor(TEXT))
        p.setFont(B(21))
        p.drawText(rect.adjusted(0, -8, 0, -8), Qt.AlignCenter,
                   str(total))
        p.setPen(QColor(MUTED))
        p.setFont(F(9))
        p.drawText(rect.adjusted(0, 30, 0, 30), Qt.AlignCenter,
                   i18n.tr("files"))


class BarsChart(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = []
        self.setMinimumHeight(130)

    def set_items(self, items):
        self._items = list(items or [])
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)
        if not self._items:
            p.setPen(QColor(MUTED))
            p.setFont(F(10))
            p.drawText(self.rect(), Qt.AlignCenter,
                       i18n.tr("No data yet"))
            return

        rows = len(self._items)
        row_h = self.height() / float(max(1, rows))
        label_w = self.width() * 0.34
        value_w = 30.0
        bar_x = label_w + 8
        bar_w = max(10.0, self.width() - bar_x - value_w - 12)
        vmax = max(1, max(v for _k, v in self._items))

        for i, (name, value) in enumerate(self._items):
            y = i * row_h
            mid = y + row_h / 2.0
            p.setFont(F(9))
            p.setPen(QColor(TEXT))
            fm = QFontMetrics(p.font())
            text = fm.elidedText(name, Qt.ElideRight, int(label_w) - 4)
            p.drawText(QRectF(0, y, label_w - 4, row_h),
                       Qt.AlignLeft | Qt.AlignVCenter, text)

            track = QRectF(bar_x, mid - 3.5, bar_w, 7.0)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(track, 3.5, 3.5)
            fill = QRectF(track)
            fill.setWidth(max(6.0, bar_w * (value / float(vmax))))
            p.setBrush(QColor(ACCENTS[0]))
            p.drawRoundedRect(fill, 3.5, 3.5)

            p.setPen(QColor(MUTED))
            p.drawText(QRectF(bar_x + bar_w + 8, y, value_w, row_h),
                       Qt.AlignRight | Qt.AlignVCenter, str(value))



class StatsPage(QtWidgets.QWidget):

    data_ready = Signal(dict)

    def __init__(self, folder_getter, parent=None):
        super().__init__(parent)
        self._folder_getter = folder_getter
        self._thread = None
        self._last_refresh = 0.0
        self.setStyleSheet("background: transparent;")

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 2, 0)
        outer.setSpacing(0)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { background: transparent; width: 10px; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,30);"
            "border-radius: 5px; min-height: 30px; }"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }")
        outer.addWidget(scroll)

        content = QtWidgets.QWidget()
        content.setStyleSheet("background: transparent;")
        scroll.setWidget(content)
        v = QtWidgets.QVBoxLayout(content)
        v.setContentsMargins(14, 12, 14, 18)
        v.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(10)
        title = QtWidgets.QLabel("STATISTICS")
        title.setFont(B(20))
        title.setStyleSheet("color: %s; background: transparent;" % TEXT)
        head.addWidget(title)
        head.addStretch(1)
        self.btn_refresh = QtWidgets.QPushButton("Refresh")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.setFixedHeight(30)
        self.btn_refresh.setFont(F(9))
        self.btn_refresh.setStyleSheet(
            "QPushButton { background: %s; color: %s; border: 1px solid %s;"
            "border-radius: 15px; padding: 0 16px; }"
            "QPushButton:hover { background: #2c2c2f; }"
            % (CARD_BG, TEXT, FAINT))
        self.btn_refresh.clicked.connect(lambda: self.refresh(force=True))
        head.addWidget(self.btn_refresh)
        v.addLayout(head)

        sub = QtWidgets.QLabel("Your download library at a glance")
        sub.setFont(F(10))
        sub.setStyleSheet("color: %s; background: transparent;" % MUTED)
        v.addWidget(sub)

        metrics = QtWidgets.QHBoxLayout()
        metrics.setSpacing(12)
        self.card_files = StatCard("TOTAL FILES", ACCENTS[0])
        self.card_size = StatCard("LIBRARY SIZE", ACCENTS[1])
        self.card_week = StatCard("THIS WEEK", ACCENTS[3])
        self.card_last = StatCard("LAST DOWNLOAD", ACCENTS[2])
        for card in (self.card_files, self.card_size,
                     self.card_week, self.card_last):
            metrics.addWidget(card, 1)
        v.addLayout(metrics)

        activity = CardFrame("Activity",
                             "Downloads over the last 30 days")
        self.chart = ActivityChart()
        activity.body.addWidget(self.chart, 1)
        v.addWidget(activity)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(12)
        fmt = CardFrame("File formats")
        fmt_row = QtWidgets.QHBoxLayout()
        fmt_row.setSpacing(10)
        self.donut = DonutChart()
        fmt_row.addWidget(self.donut, 0)
        self.legend = QtWidgets.QVBoxLayout()
        self.legend.setSpacing(6)
        self.legend.addStretch(1)
        fmt_row.addLayout(self.legend, 1)
        fmt.body.addLayout(fmt_row, 1)
        row.addWidget(fmt, 1)

        tags = CardFrame("Top tags")
        self.bars = BarsChart()
        tags.body.addWidget(self.bars, 1)
        row.addWidget(tags, 1)
        v.addLayout(row)

        storage = CardFrame("Storage")
        st_row = QtWidgets.QHBoxLayout()
        st_row.setSpacing(24)
        self.lbl_avg = self._storage_item(st_row, "Average file size")
        self.lbl_big = self._storage_item(st_row, "Largest file")
        self.lbl_free = self._storage_item(st_row, "Free disk space")
        st_row.addStretch(1)
        storage.body.addLayout(st_row)
        v.addWidget(storage)
        v.addStretch(1)

        self.data_ready.connect(self._apply)

    @staticmethod
    def _storage_item(layout, label):
        box = QtWidgets.QVBoxLayout()
        box.setSpacing(2)
        cap = QtWidgets.QLabel(label)
        cap.setFont(F(9))
        cap.setStyleSheet("color: %s; background: transparent;" % MUTED)
        box.addWidget(cap)
        value = QtWidgets.QLabel("-")
        value._i18n_dynamic = True
        value.setFont(B(13))
        value.setStyleSheet("color: %s; background: transparent;" % TEXT)
        box.addWidget(value)
        layout.addLayout(box)
        return value


    def showEvent(self, ev):
        super().showEvent(ev)
        if time.time() - self._last_refresh > 4:
            self.refresh()

    def refresh(self, force=False):
        if self._thread is not None and self._thread.is_alive():
            return
        if not force and time.time() - self._last_refresh < 2:
            return
        self._last_refresh = time.time()
        try:
            folder = self._folder_getter()
        except Exception:
            folder = None
        self._thread = threading.Thread(
            target=self._worker, args=(folder,), daemon=True)
        self._thread.start()

    def _worker(self, folder):
        try:
            data = collect_stats(folder)
        except Exception:
            data = collect_stats(None)
        try:
            self.data_ready.emit(data)
        except Exception:
            pass

    def _apply(self, data):
        self.card_files.set(data["count"],
                            "%d %s" % (data["folders_count"],
                                       i18n.tr("folders")))
        self.card_size.set(human_size(data["bytes"]),
                           "%s %s" % (human_size(data["avg"]),
                                      i18n.tr("average")))
        self.card_week.set(str(data["week"]),
                           i18n.tr("last 7 days"))
        last_name = data.get("last_file") or i18n.tr("No downloads yet")
        fm_last = QFontMetrics(self.card_last.lbl_sub.font())
        self.card_last.set(
            human_ago(data["last"]),
            fm_last.elidedText(last_name, Qt.ElideMiddle, 250))

        self.chart.set_series(data["series"])

        formats = data["formats"][:5]
        items = [(ext.upper(), count, ACCENTS[i % len(ACCENTS)])
                 for i, (ext, count) in enumerate(formats)]
        self.donut.set_items(items)
        while self.legend.count() > 1:
            item = self.legend.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for ext, count, color in items:
            self.legend.insertWidget(self.legend.count() - 1,
                                     self._legend_row(ext, count, color))

        self.bars.set_items(data["folders"])

        self.lbl_avg.setText(human_size(data["avg"]))
        if data["largest"]:
            name = data["largest"]["name"]
            fm = QFontMetrics(self.lbl_big.font())
            self.lbl_big.setText(fm.elidedText(name, Qt.ElideMiddle, 260))
            self.lbl_big.setToolTip(name)
        else:
            self.lbl_big.setText("-")
        self.lbl_free.setText(human_size(data["free"]))

    @staticmethod
    def _legend_row(name, count, color):
        row = QtWidgets.QWidget()
        row.setStyleSheet("background: transparent;")
        h = QtWidgets.QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(7)
        dot = QtWidgets.QWidget()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet("background: %s; border-radius: 4px;" % color)
        h.addWidget(dot, 0, Qt.AlignVCenter)
        label = QtWidgets.QLabel(name)
        label._i18n_dynamic = True
        label.setFont(F(9))
        label.setStyleSheet("color: %s; background: transparent;" % TEXT)
        h.addWidget(label)
        h.addStretch(1)
        num = QtWidgets.QLabel(str(count))
        num._i18n_dynamic = True
        num.setFont(F(9))
        num.setStyleSheet("color: %s; background: transparent;" % MUTED)
        h.addWidget(num)
        return row
