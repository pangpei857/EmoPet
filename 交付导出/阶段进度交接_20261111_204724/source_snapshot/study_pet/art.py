"""Original, replaceable vector cat. No external image assets are needed."""

import math
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget


def path(points):
    p = QPainterPath(QPointF(*points[0]))
    for group in points[1:]:
        if len(group) == 6:
            p.cubicTo(*group)
        else:
            p.lineTo(*group)
    return p


def draw_cat(p: QPainter, bounds: QRectF, time_s: float = 0, mood: str = "idle"):
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(bounds.x(), bounds.y())
    p.scale(bounds.width() / 220, bounds.height() / 230)
    # Tail and body use a cool charcoal palette, keeping the eyes the focal point.
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(20, 30, 35, 20))
    p.drawEllipse(QRectF(42, 211, 147, 12))
    sway = math.sin(time_s * 1.4) * 9
    tail = path([(153, 191), (210, 211, 218+sway, 154, 187+sway, 142)])
    p.setPen(QPen(QColor("#252A30"), 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(tail)
    p.setPen(Qt.PenStyle.NoPen)
    p.translate(0, math.sin(time_s * 2) * 1.2)
    gradient = QRadialGradient(95, 145, 93)
    gradient.setColorAt(0, QColor("#393D45")); gradient.setColorAt(1, QColor("#191C23"))
    p.setBrush(gradient)
    p.drawPath(path([(66, 144), (73, 117, 151, 116, 159, 151),
                     (168, 173, 174, 206, 150, 214),
                     (133, 219, 93, 218, 75, 213), (51, 207, 56, 169, 66, 144)]))
    p.setBrush(QColor("#20242B"))
    p.drawEllipse(QRectF(64, 199, 45, 18)); p.drawEllipse(QRectF(117, 199, 45, 18))
    # A little shoulder paw lifts when interacting.
    if mood in {"happy", "care"}:
        p.save(); p.translate(63, 163)
        p.rotate(-30 + math.sin(time_s * 6) * 12)
        p.setBrush(QColor("#2A2F36")); p.drawRoundedRect(QRectF(-17, -49, 28, 64), 14, 14)
        p.setBrush(QColor("#A97F8A")); p.drawEllipse(QRectF(-11, -41, 16, 16))
        for x,y in [(-12,-48),(-4,-51),(4,-47)]: p.drawEllipse(QRectF(x, y, 5, 6))
        p.restore()
    else:
        p.setBrush(QColor("#272C33")); p.drawEllipse(QRectF(64, 153, 27, 46))
    p.setBrush(QColor("#2C3038")); p.drawEllipse(QRectF(136, 153, 26, 46))
    # Ears are drawn behind a generous, round head.
    p.setBrush(QColor("#242830"))
    p.drawPath(path([(43, 81), (32, 29, 37, 14, 49, 24), (68, 33), (81, 54), (43, 81)]))
    p.drawPath(path([(139, 51), (165, 20, 180, 9, 182, 26), (182, 62), (175, 86), (139, 51)]))
    p.setBrush(QColor("#775965"))
    p.drawPath(path([(44, 35), (48, 59), (64, 48), (44, 35)]))
    p.drawPath(path([(173, 30), (155, 49), (174, 61), (173, 30)]))
    head = QRadialGradient(92, 66, 115)
    head.setColorAt(0, QColor("#41454D")); head.setColorAt(0.7, QColor("#262B32")); head.setColorAt(1, QColor("#1B1F27"))
    p.setBrush(head); p.drawEllipse(QRectF(35, 45, 151, 114))
    # A few forehead tufts keep the silhouette recognisable at small sizes.
    p.drawPath(path([(87, 50), (96, 39), (100, 49), (109, 40), (116, 51), (87, 50)]))
    blink = (time_s % 5.7) > 5.52 or mood == "rest"
    for x in (68, 126):
        if blink:
            p.setPen(QPen(QColor("#B6D6DE"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPath(path([(x-1, 99), (x+7, 106, x+19, 106, x+27, 98)]))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(QColor("#111920")); p.drawEllipse(QRectF(x-5, 84, 38, 32))
            eye = QRadialGradient(x+12, 98, 17)
            eye.setColorAt(0, QColor("#C7F8F0")); eye.setColorAt(.55, QColor("#70C2CF")); eye.setColorAt(1, QColor("#346C83"))
            p.setBrush(eye); p.drawEllipse(QRectF(x, 86, 29, 28))
            p.setBrush(QColor("#111A24")); p.drawEllipse(QRectF(x+10, 88, 10, 24))
            p.setBrush(QColor("#FFFFFF")); p.drawEllipse(QRectF(x+5, 89, 8, 7))
            p.setBrush(QColor(255,255,255,160)); p.drawEllipse(QRectF(x+20, 104, 4, 4))
    p.setBrush(QColor("#C58D9D"))
    p.drawPath(path([(105, 119), (116, 119), (111, 125), (105, 119)]))
    p.setPen(QPen(QColor("#B2A7AD"), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawPath(path([(111, 125), (111, 131, 104, 133, 101, 128)]))
    p.drawPath(path([(111, 125), (111, 132, 118, 133, 122, 128)]))
    p.setPen(QPen(QColor(172,182,195,130), 1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for a,b in [((87,122),(48,117)),((87,129),(46,133)),((133,122),(172,117)),((133,129),(174,133))]:
        p.drawLine(QPointF(*a), QPointF(*b))
    p.restore()


def cat_icon():
    pix = QPixmap(96, 96); pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix); draw_cat(p,QRectF(1,-7,94,100)); p.end()
    return QIcon(pix)


class CatCanvas(QWidget):
    clicked = Signal()
    double_clicked = Signal()
    dragged = Signal(QPointF)
    drag_finished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mood = "idle"
        self.time_s = 0
        self._origin = None
        self._moved = False
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.clicked)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("点一下摸摸，双击打开学习面板，拖动换个位置")
        self._animation = QTimer(self)
        self._animation.timeout.connect(self.advance)
        self._animation.start(50)

    def advance(self):
        self.time_s += .05
        self.update()

    def paintEvent(self, event):
        p=QPainter(self)
        draw_cat(p, QRectF(0,0,self.width(),self.height()), self.time_s, self.mood)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition()
            self._window_origin = self.window().pos()
            self._moved = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta = event.globalPosition() - self._origin
            if delta.manhattanLength() > 5:
                self._moved = True
                self._click_timer.stop()
                self.dragged.emit(QPointF(self._window_origin) + delta)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            if self._moved:
                self.drag_finished.emit()
            else:
                self._click_timer.start(220)
            self._origin = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop()
            self._origin = None
            self.double_clicked.emit()
