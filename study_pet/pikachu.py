"""Raincoat character rendering and desktop mouse interactions."""
import math
import time
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget
from .gaze import gaze_direction, smooth_gaze
from .raincoat import draw_character, hit_shape

ART_WIDTH, ART_HEIGHT = 280, 300
ACTION_LABELS = {"idle":"待机", "care":"关心", "remind":"提醒", "encourage":"鼓励",
                 "pet":"摸摸头", "poke":"戳肚子", "tail":"碰尾巴", "rest":"休息"}


def heart(p,x,y,size):
    p.save();p.translate(x,y);p.scale(size/20,size/20)
    p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#EFA28E'))
    shape=QPainterPath(QPointF(0,5));shape.cubicTo(-12,-4,-12,-13,-5,-12)
    shape.cubicTo(-1,-12,0,-8,0,-8);shape.cubicTo(5,-17,19,-7,0,5)
    p.drawPath(shape);p.restore()


def star(p,x,y,r,rotation):
    shape=QPainterPath()
    for i in range(10):
        angle=math.radians(rotation-90+i*36);radius=r if i%2==0 else r*.44
        point=QPointF(x+math.cos(angle)*radius,y+math.sin(angle)*radius)
        shape.moveTo(point) if i==0 else shape.lineTo(point)
    shape.closeSubpath();p.setPen(QPen(QColor('#C7913C'),.7));p.setBrush(QColor('#FFE6A6'));p.drawPath(shape)


def draw_pikachu(p,bounds,time_s=0.,mood="idle",gaze=(0.,0.),hovering=False):
    draw_character(p,bounds,time_s,mood,gaze,hovering)
    p.save();p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(bounds.x(),bounds.y());p.scale(bounds.width()/ART_WIDTH,bounds.height()/ART_HEIGHT)
    p.setOpacity(.8)
    if mood in {'care','pet'}:
        for i,(x,y) in enumerate(((35,121),(208,112))):heart(p,x,y-(time_s*12+i*11)%30,12+i*2)
    if mood in {'encourage','tail'}:
        for i,(x,y) in enumerate(((37,172),(230,109),(232,253))):star(p,x,y+math.sin(time_s*4+i)*4,7+i,time_s*24)
    if mood=='remind':
        p.setPen(QPen(QColor('#A47739'),1.5));p.setBrush(QColor('#FFF8E7'));p.drawEllipse(QRectF(25,190,27,27))
        p.drawLine(QPointF(38,196),QPointF(38,204));p.drawLine(QPointF(38,204),QPointF(44,207))
    if mood=='rest':
        p.setPen(QColor('#B29768'));p.drawText(QPointF(206,134),'z');p.drawText(QPointF(219,120),'Z')
    p.restore()


def pet_icon():
    pix=QPixmap(128,128);pix.fill(Qt.GlobalColor.transparent)
    p=QPainter(pix);draw_pikachu(p,QRectF(0,0,128,128));p.end()
    return QIcon(pix)


class PetCanvas(QWidget):
    touched=Signal(str)
    double_clicked=Signal()
    dragged=Signal(QPointF)
    drag_finished=Signal()
    scale_requested=Signal(int)

    def __init__(self,parent=None):
        super().__init__(parent)
        self.setObjectName('pikachuCanvas')
        self.setAccessibleName('雨衣皮卡丘，点击摸头或肚子，拖动移动，滚轮缩放')
        self.mood='idle';self.base_mood='idle';self.hovering=False
        self._started=time.monotonic();self.time_s=0.;self._action_until=0.
        self._last_frame=self._started;self.gaze=(0.,0.)
        self._origin=None;self._moved=False;self._double_release=False;self._touch_region='body'
        self.drag_enabled=True
        self._shape=hit_shape()
        self._click_timer=QTimer(self);self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(lambda:self.touched.emit(self._touch_region))
        self.setMouseTracking(True);self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._animation=QTimer(self);self._animation.timeout.connect(self.advance);self._animation.start(33)

    def set_action(self,mood,milliseconds=4000):
        if mood not in ACTION_LABELS:raise ValueError(f'Unknown action {mood}')
        self.mood=mood;self._action_until=time.monotonic()+milliseconds/1000 if milliseconds else float('inf')
        self.update()

    def clear_action(self):
        self._action_until=0.;self.mood=self.base_mood;self.update()

    def advance(self):
        now=time.monotonic();self.time_s=now-self._started
        if now>=self._action_until:self.mood=self.base_mood
        cursor=self.canonical(self.mapFromGlobal(QCursor.pos()))
        target=gaze_direction(cursor.x(),cursor.y())
        self.gaze=smooth_gaze(self.gaze,target,now-self._last_frame)
        self._last_frame=now;self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.save();p.scale(self.width()/ART_WIDTH,self.height()/ART_HEIGHT)
        p.fillPath(self._shape,QColor(255,220,80,1));p.restore()
        draw_pikachu(p,QRectF(0,0,self.width(),self.height()),self.time_s,self.mood,self.gaze,self.hovering)

    def enterEvent(self,event):self.hovering=True;self.update()
    def leaveEvent(self,event):self.hovering=False;self.update()

    def canonical(self,point):
        return QPointF(point.x()*ART_WIDTH/max(1,self.width()),point.y()*ART_HEIGHT/max(1,self.height()))

    def cancel_pointer(self):
        self._click_timer.stop();self._origin=None;self._moved=False;self._double_release=False
        self.hovering=False
        if QWidget.mouseGrabber() is self:self.releaseMouse()
        self.setCursor(Qt.CursorShape.OpenHandCursor if self.drag_enabled else Qt.CursorShape.PointingHandCursor)

    def set_drag_enabled(self,enabled):
        self.drag_enabled=bool(enabled);self.cancel_pointer()

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self._origin=event.globalPosition();self._window_origin=self.window().pos();self._moved=False;self._double_release=False
            point=self.canonical(event.position())
            self._touch_region='tail' if point.x()>174 and point.y()>190 else 'head' if point.y()<190 else 'body'
            self.setCursor(Qt.CursorShape.ClosedHandCursor if self.drag_enabled else Qt.CursorShape.PointingHandCursor);event.accept()

    def mouseMoveEvent(self,event):
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            delta=event.globalPosition()-self._origin
            if delta.manhattanLength()>=QApplication.startDragDistance():
                self._moved=True;self._click_timer.stop()
                if self.drag_enabled:self.dragged.emit(QPointF(self._window_origin)+delta)
        self.update()

    def mouseReleaseEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            if self._origin is not None and not self._double_release:
                if self._moved and self.drag_enabled:self.drag_finished.emit()
                elif self._moved:pass
                else:self._click_timer.start(QApplication.doubleClickInterval()+25)
            self._origin=None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.drag_enabled else Qt.CursorShape.PointingHandCursor);event.accept()

    def mouseDoubleClickEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self._click_timer.stop();self._origin=None;self._double_release=True;self.double_clicked.emit();event.accept()

    def wheelEvent(self,event):
        delta=event.angleDelta().y() or event.pixelDelta().y()
        if delta:self.scale_requested.emit(1 if delta>0 else -1)
        event.accept()

    def hideEvent(self,event):
        self._animation.stop();self.cancel_pointer()
    def showEvent(self,event):self._last_frame=time.monotonic();self._animation.start(33)
