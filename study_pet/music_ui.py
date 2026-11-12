"""A compact transparent player that follows the pet's scale."""
from PySide6.QtCore import QRectF,Qt,Signal
from PySide6.QtGui import QColor,QFont,QPainter,QPainterPath,QPen
from PySide6.QtWidgets import QLabel,QPushButton,QWidget

from .music_core import MusicState


class TransportButton(QPushButton):
    def __init__(self,kind,parent=None):
        super().__init__(parent);self.kind=kind;self.playing=False
        self.setCursor(Qt.CursorShape.PointingHandCursor);self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet('QPushButton{background:transparent;border:0;padding:0;}')

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side=min(self.width(),self.height());cx=self.width()/2;cy=self.height()/2
        accent=self.kind=='toggle';color=QColor('#59451D' if self.isEnabled() else '#B5AA91')
        p.setPen(Qt.PenStyle.NoPen)
        if accent or self.underMouse():
            p.setBrush(QColor('#E6B847' if self.isDown() else '#F4C64E' if accent else '#F3E8C6'))
            radius=side*.46;p.drawEllipse(QRectF(cx-radius,cy-radius,radius*2,radius*2))
        p.setBrush(color);size=side*.20
        if accent and self.playing:
            for offset in (-.65,.25):p.drawRoundedRect(QRectF(cx+offset*size,cy-size,.4*size,2*size),.6,.6)
        else:
            direction=-1 if self.kind=='previous' else 1
            x=cx+(size*.15 if self.kind=='previous' else -size*.15)
            path=QPainterPath();path.moveTo(x+direction*size,cy)
            path.lineTo(x-direction*size*.65,cy-size);path.lineTo(x-direction*size*.65,cy+size);path.closeSubpath()
            p.drawPath(path)
            if not accent:
                bar=cx+direction*size*1.15
                p.drawRoundedRect(QRectF(bar-size*.12,cy-size,size*.25,2*size),.5,.5)


class MusicCard(QWidget):
    command_requested=Signal(str,str)

    def __init__(self,parent=None):
        super().__init__(parent);self.factor=1.;self.state=MusicState();self.busy=False
        self.setAccessibleName('QQ 音乐迷你播放器')
        self.title=QLabel(self);self.artist=QLabel(self)
        for label in (self.title,self.artist):
            label.setTextFormat(Qt.TextFormat.PlainText);label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet('background:transparent;border:0;padding:0;')
        self.buttons={}
        for key,text in (('previous','上一首'),('toggle','播放或暂停'),('next','下一首')):
            button=TransportButton(key,self);button.setAccessibleName(text);button.setToolTip(text)
            button.clicked.connect(lambda checked=False,k=key:self.command_requested.emit(k,self.state.session_id))
            self.buttons[key]=button
        self.set_state(self.state)

    def set_scale(self,factor):self.factor=factor;self.layout_controls()

    def set_state(self,state):
        self.state=state;playing=state.status=='playing'
        self.buttons['toggle'].playing=playing
        label='暂停' if playing else '播放'
        self.buttons['toggle'].setAccessibleName(label);self.buttons['toggle'].setToolTip(label)
        self.title.setToolTip(state.title);self.artist.setToolTip(state.artist)
        self.update_enabled();self.layout_controls();self.update()

    def set_busy(self,busy):self.busy=busy;self.update_enabled()

    def update_enabled(self):
        for key,allowed in (('previous',self.state.can_previous),('toggle',self.state.can_toggle),('next',self.state.can_next)):
            self.buttons[key].setEnabled(allowed and not self.busy)
            self.buttons[key].update()

    def show_error(self,ok,message):
        if not ok and message:
            self.artist.setText(self.artist.fontMetrics().elidedText(message,Qt.TextElideMode.ElideRight,self.artist.width()))
            self.artist.setToolTip(message)

    def resizeEvent(self,event):super().resizeEvent(event);self.layout_controls()

    def layout_controls(self):
        f=self.factor;w=self.width();pad=round(13*f)
        for label,size,bold,y,height in ((self.title,12,True,9,19),(self.artist,10,False,29,16)):
            font=QFont('Microsoft YaHei UI');font.setPixelSize(max(9,round(size*f)));font.setBold(bold)
            label.setFont(font)
            label.setStyleSheet(f'background:transparent;border:0;padding:0;font-size:{max(9,round(size*f))}px;'
                f'font-weight:{600 if bold else 400};color:{"#59451D" if bold else "#827052"};')
            label.setGeometry(pad,round(y*f),max(1,w-pad*2),max(round(height*f),label.fontMetrics().height()+1))
        title=self.state.title or 'QQ 音乐'
        artist=self.state.artist or ('正在播放' if self.state.status=='playing' else '已暂停')
        self.title.setText(self.title.fontMetrics().elidedText(title,Qt.TextElideMode.ElideRight,max(1,w-pad*2)))
        self.artist.setText(self.artist.fontMetrics().elidedText(artist,Qt.TextElideMode.ElideRight,max(1,w-pad*2)))
        side=round(38*f);gap=round(17*f);start=round((w-3*side-2*gap)/2)
        for index,key in enumerate(('previous','toggle','next')):
            self.buttons[key].setGeometry(start+index*(side+gap),round(49*f),side,side)

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor('#DEC889'),1));p.setBrush(QColor(255,250,232,240))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(.7,.7,-.7,-.7),15*self.factor,15*self.factor)
