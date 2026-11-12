import random
from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QPainter, QPainterPath, QPen, QShortcut, QKeySequence
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPushButton, QSpinBox, QSystemTrayIcon, QVBoxLayout, QWidget)

from .pikachu import PetCanvas, pet_icon, ACTION_LABELS
from .focus import FocusSession, Status
from .storage import Store
from .perception import FeedbackEvent,ReminderGate
from .history import parse
from .music_core import MusicState,MusicVisibility
from .music_ui import MusicCard
from .music_service import MusicController


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI', 'Microsoft YaHei'; color: #263532; font-size: 13px; }
QWidget#panel { background: #FBF9F0; }
QLabel#title { font-size: 25px; font-weight: 700; color: #71501D; }
QLabel#muted { color: #7A8580; font-size: 12px; }
QLabel#question { font-size: 15px; font-weight: 600; }
QLineEdit { background: white; border: 1px solid #DCE4DD; border-radius: 10px; padding: 12px; selection-background-color: #D0E8DC; }
QLineEdit:focus { border-color: #50957D; }
QLineEdit:disabled { background: #F0F1EB; color: #7A8580; }
QPushButton { background: #FFFFFF; border: 1px solid #DCE4DD; border-radius: 9px; padding: 9px 14px; }
QPushButton:hover { background: #EDF3EB; border-color: #B1C7BA; }
QPushButton:pressed { background: #E2EDE2; }
QPushButton:checked { background: #FFF0B9; border-color: #CFAC51; color: #795619; font-weight: 600; }
QPushButton:disabled { color: #A3ABA4; background: #F0F1EB; }
QPushButton#primary { background: #F1C44E; color: #563D15; border: 0; font-weight: 600; }
QPushButton#primary:hover { background: #E8B739; }
QPushButton#primary:disabled { background: #F0F1EB; color: #A3ABA4; }
QPushButton#textButton { border: 0; background: transparent; color: #648071; padding: 5px; }
QSpinBox { border: 1px solid #DCE4DD; background: white; border-radius: 8px; padding: 7px; }
QSpinBox QLineEdit { border: 0; padding: 0; border-radius: 0; background: transparent; }
QSpinBox:disabled { background: #F0F1EB; color: #7A8580; }
QMenu { background: #FCFCF8; border: 1px solid #DCE4DD; padding: 6px; }
QMenu::item { padding: 7px 24px 7px 12px; border-radius: 5px; }
QMenu::item:selected { background: #FFF0B9; }
"""


class Bubble(QWidget):
    dismissed=Signal()
    hover_changed=Signal(bool)
    response_requested=Signal(str,str)
    def __init__(self, parent):
        super().__init__(parent)
        self.label=QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setWordWrap(True)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color:#40504A; font-size:13px; background:transparent;")
        self.close_button=QPushButton("×",self)
        self.close_button.setAccessibleName("关闭气泡")
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.clicked.connect(self.dismissed)
        self.reminder_id=None;self.reminder_kind=None
        self.actions=QWidget(self);self.action_buttons={}
        for key,title in [('research','我在查资料'),('false_positive','这次识别错了'),('snooze','稍后提醒')]:
            button=QPushButton(title,self.actions);button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False,k=key:self.respond(k))
            self.action_buttons[key]=button
        self.actions.hide()
        self.factor=1.;self.raw_text='';self.hovering=False;self._style_scale=None

    def respond(self,response):
        if self.reminder_id:self.response_requested.emit(self.reminder_id,response)

    def set_actions(self,reminder=None):
        self.reminder_id,self.reminder_kind=reminder if reminder else (None,None)
        self.actions.setVisible(bool(self.reminder_id))
        self.action_buttons['research'].setVisible(self.reminder_kind=='phone')

    def actions_height(self):
        if not self.reminder_id:return 0
        row=max(26,round(29*self.factor))
        return row*2+5 if self.reminder_kind=='phone' else row

    def set_message(self,text):
        self.raw_text=str(text).strip()[:2000]
        self.label.setToolTip(self.raw_text)

    def prepare(self,width,factor):
        self.set_scale(factor)
        metrics=self.label.fontMetrics();available=max(40,width-2*max(12,round(17*factor)))
        lines=[];line=''
        for char in self.raw_text:
            if char=='\n':lines.append(line);line=''
            elif metrics.horizontalAdvance(line+char)>available and line:
                lines.append(line);line=char
            else:line+=char
        lines.append(line)
        if len(lines)>6:
            lines=lines[:6]
            while lines[-1] and metrics.horizontalAdvance(lines[-1]+'…')>available:lines[-1]=lines[-1][:-1]
            lines[-1]+='…'
        self.label.setText('\n'.join(lines))
        return max(round(87*factor),self.header_height()+len(lines)*metrics.lineSpacing()+23+self.actions_height()+(8 if self.reminder_id else 0))

    def header_height(self):return max(28,max(24,round(21*self.factor))+8)

    def set_scale(self,factor):
        self.factor=factor
        if self._style_scale==factor:return
        self._style_scale=factor
        self.label.setStyleSheet(f"color:#665128;font-size:{max(12,min(20,round(13*factor)))}px;background:transparent;")
        self.label.ensurePolished()
        self.close_button.setStyleSheet(f"QPushButton{{border:0;background:transparent;color:#A68C52;font-size:{round(16*factor)}px;padding:0;}} QPushButton:hover{{color:#60471E;}}")
        self.actions.setStyleSheet(f'QPushButton{{background:#F7EAC6;color:#665128;border:1px solid #DCC48C;border-radius:6px;padding:2px;font-size:{max(11,min(17,round(12*factor)))}px;}} QPushButton:hover{{background:#FFE19A;}}')
        self.resizeEvent(None)

    def resizeEvent(self, event):
        pad=max(12,round(17*self.factor))
        header=self.header_height()
        extra=self.actions_height()+(8 if self.reminder_id else 0)
        self.label.setGeometry(pad,header,self.width()-2*pad,max(1,self.height()-header-23-extra))
        self.actions.setGeometry(pad,self.height()-18-self.actions_height(),self.width()-2*pad,self.actions_height())
        row=max(26,round(29*self.factor));half=(self.actions.width()-5)//2
        if self.reminder_kind=='phone':
            self.action_buttons['research'].setGeometry(0,0,self.actions.width(),row)
        y=row+5 if self.reminder_kind=='phone' else 0
        self.action_buttons['false_positive'].setGeometry(0,y,half,row)
        self.action_buttons['snooze'].setGeometry(half+5,y,self.actions.width()-half-5,row)
        side=max(24,round(21*self.factor))
        self.close_button.setGeometry(self.width()-side-4,4,side,side)

    def enterEvent(self,event):
        self.hovering=True;self.hover_changed.emit(True)

    def leaveEvent(self,event):
        self.hovering=False;self.hover_changed.emit(False)

    def paintEvent(self, event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape=QPainterPath();shape.addRoundedRect(QRectF(2,2,self.width()-4,self.height()-17),15,15)
        shape.moveTo(self.width()/2-8,self.height()-16)
        shape.lineTo(self.width()/2,self.height()-3)
        shape.lineTo(self.width()/2+8,self.height()-16)
        p.setPen(QPen(QColor("#E2CEA1"),1));p.setBrush(QColor("#FFFCF0"));p.drawPath(shape)


class PetWindow(QWidget):
    open_panel = Signal()
    touched = Signal(str)
    pause_requested = Signal()
    quit_requested = Signal()
    position_changed = Signal()
    scale_changed = Signal(int)
    reminder_response=Signal(str,str)
    music_command=Signal(str,str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("雨衣皮卡丘 · 桌面伙伴")
        self.setWindowIcon(pet_icon())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.scale_percent=100;self.menu=None
        self.bubbles_enabled=True;self.position_locked=False;self._layout_ready=False;self._paused_bubble_time=0
        self.bubble=Bubble(self)
        self.canvas=PetCanvas(self)
        self.canvas.touched.connect(self.touched)
        self.canvas.double_clicked.connect(self.open_panel)
        self.canvas.dragged.connect(self.move_bounded)
        self.canvas.drag_finished.connect(self.finish_drag)
        self.canvas.scale_requested.connect(lambda step:self.set_scale(self.scale_percent+step*10))
        self.badge=QPushButton("开始专注",self)
        self.badge.setAccessibleName("打开学习面板")
        self.badge.clicked.connect(self.open_panel)
        self.music_card=MusicCard(self);self.music_card.hide();self._music_visible=False
        self._music_state=MusicState();self._music_display=MusicVisibility()
        self.music_card.command_requested.connect(self.music_command)
        self._music_timer=QTimer(self);self._music_timer.setInterval(1000)
        self._music_timer.timeout.connect(self.refresh_music_visibility)
        self._bubble_timer=QTimer(self);self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.dismiss_bubble)
        self.bubble.dismissed.connect(self.dismiss_bubble)
        self.bubble.hover_changed.connect(self.pause_bubble_on_hover)
        self.bubble.response_requested.connect(self.reminder_response)
        self._mood_timer=QTimer(self);self._mood_timer.setSingleShot(True)
        self._mood_timer.timeout.connect(self.clear_mood)
        self.base_mood="idle"
        self.layout_pet()
        self._screen_timer=QTimer(self);self._screen_timer.setSingleShot(True)
        self._screen_timer.timeout.connect(self.ensure_on_screen)
        self._watched_screens=[]
        for screen in QApplication.screens():self.watch_screen(screen)
        QApplication.instance().screenAdded.connect(self.watch_screen)
        QApplication.instance().screenRemoved.connect(self.schedule_screen_repair)
        self.dismiss_shortcut=QShortcut(QKeySequence('Escape'),self)
        self.dismiss_shortcut.activated.connect(self.dismiss_bubble)

    def say(self, text, mood="encourage", milliseconds=8000,reminder=None):
        self.bubble.set_actions(reminder)
        self.bubble.set_message(text)
        self.layout_pet(keep_anchor=True)
        self.canvas.set_action(mood, min(milliseconds,5500))
        self._mood_timer.start(min(milliseconds,5500))
        if not self.bubbles_enabled:
            self.dismiss_bubble();return
        self.bubble.show()
        duration=max(milliseconds,min(30000,2500+len(self.bubble.label.text())*100))
        self._paused_bubble_time=duration
        self._bubble_timer.start(duration)
        if self.bubble.hovering:self.pause_bubble_on_hover(True)

    def dismiss_bubble(self):
        self._bubble_timer.stop();self._paused_bubble_time=0;self.bubble.hide();self.bubble.hovering=False
        had_content=bool(self.bubble.raw_text or self.bubble.reminder_id)
        self.bubble.set_actions()
        if self._layout_ready and had_content:
            self.bubble.set_message('');self.layout_pet(keep_anchor=True)

    def pause_bubble_on_hover(self,inside):
        if inside and self._bubble_timer.isActive():
            self._paused_bubble_time=max(1,self._bubble_timer.remainingTime());self._bubble_timer.stop()
        elif not inside and self.bubble.isVisible() and self._paused_bubble_time>0:
            self._bubble_timer.start(self._paused_bubble_time)

    def set_bubbles_enabled(self,enabled):
        self.bubbles_enabled=bool(enabled)
        if not enabled:self.dismiss_bubble()

    def set_locked(self,locked):
        self.position_locked=bool(locked);self.canvas.set_drag_enabled(not locked)

    def clear_mood(self):
        self.canvas.base_mood=self.base_mood;self.canvas.clear_action()

    def foot_anchor(self):
        return QPointF(self.x()+self.width()/2,self.y()+self._anchor_y)

    def move_to_anchor(self,anchor):
        self.move_bounded(QPointF(anchor.x()-self.width()/2,anchor.y()-self._anchor_y))

    def set_music_state(self,state):
        self._music_state=state;self.music_card.set_state(state);self.refresh_music_visibility()

    def refresh_music_visibility(self):
        visible=self._music_display.visible(self._music_state)
        if visible!=self._music_visible:
            self._music_visible=visible;self.music_card.setVisible(visible)
            self.layout_pet(keep_anchor=True);self.ensure_on_screen()
        if visible and self._music_state.status=='paused':
            if not self._music_timer.isActive():self._music_timer.start()
        else:self._music_timer.stop()

    def layout_size(self,percent):
        f=percent/100;width=round(300*f)
        bubble_height=self.bubble.prepare(round(294*f),f)
        canvas_y=round(3*f)+bubble_height+round(3*f)
        badge_y=canvas_y+round(273*f)
        height=badge_y+round(33*f)
        if self._music_visible:height+=round(106*f)
        return width,height,bubble_height,canvas_y,badge_y

    def layout_pet(self,keep_anchor=False):
        anchor=self.foot_anchor() if keep_anchor and self._layout_ready else None
        f=self.scale_percent/100
        width,height,bubble_height,canvas_y,badge_y=self.layout_size(self.scale_percent)
        self.setFixedSize(width,height)
        self.bubble.setGeometry(round(3*f),round(3*f),round(294*f),bubble_height)
        self.canvas.setGeometry(round(20*f),canvas_y,round(260*f),round(278*f))
        self.badge.setGeometry(round(53*f),badge_y,round(194*f),round(30*f))
        self._anchor_y=badge_y+round(33*f)
        self.music_card.setGeometry(round(20*f),self._anchor_y+round(7*f),round(260*f),round(96*f))
        self.music_card.set_scale(f)
        self.badge.setStyleSheet(f"QPushButton{{background:#FFF8E2;color:#79591E;border:1px solid #E0C477;border-radius:{round(15*f)}px;font-size:{max(11,round(12*f))}px;padding:0;}} QPushButton:hover{{background:#FFE8A0;}}")
        self._layout_ready=True
        if anchor is not None:self.move_to_anchor(anchor)

    def set_scale(self,percent):
        area=(self.screen() or QApplication.primaryScreen()).availableGeometry()
        percent=max(70,min(160,int(percent)))
        while percent>70:
            width,height,*_=self.layout_size(percent)
            if width<=area.width()-12 and height<=area.height()-12:break
            percent-=1
        if percent==self.scale_percent:return
        anchor=self.foot_anchor()
        self.scale_percent=percent;self.layout_pet()
        self.move_to_anchor(anchor)
        self.scale_changed.emit(percent)

    def set_topmost(self,enabled):
        visible=self.isVisible();anchor=self.foot_anchor()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,enabled)
        self.move_to_anchor(anchor)
        if visible:self.show();self.move_to_anchor(anchor)

    def finish_drag(self):
        area=(QApplication.screenAt(self.geometry().center()) or self.screen()).availableGeometry()
        x,y=self.x(),self.y()
        if abs(x-area.left())<24:x=area.left()
        elif abs(x+self.width()-area.right()-1)<24:x=area.right()-self.width()+1
        if abs(y-area.top())<24:y=area.top()
        elif abs(y+self.height()-area.bottom()-1)<24:y=area.bottom()-self.height()+1
        self.move(x,y);self.position_changed.emit()

    def move_bounded(self, point):
        screen=QApplication.screenAt((point+QPointF(self.width()/2,self.height()/2)).toPoint()) or self.screen() or QApplication.primaryScreen()
        area=screen.availableGeometry()
        self.move(max(area.left(),min(int(point.x()),max(area.left(),area.right()-self.width()+1))),
                  max(area.top(),min(int(point.y()),max(area.top(),area.bottom()-self.height()+1))))

    def watch_screen(self,screen):
        if screen not in self._watched_screens:
            self._watched_screens.append(screen)
            screen.availableGeometryChanged.connect(self.schedule_screen_repair)
            screen.geometryChanged.connect(self.schedule_screen_repair)
        self.schedule_screen_repair()

    def schedule_screen_repair(self,*args):self._screen_timer.start(150)

    def ensure_on_screen(self):
        self.set_scale(self.scale_percent)
        self.move_bounded(QPointF(self.pos()))
        self.position_changed.emit()

    def reset_position(self):
        area=QApplication.primaryScreen().availableGeometry()
        self.move_bounded(QPointF(area.right()-self.width()-28,area.bottom()-self.height()-12))
        self.position_changed.emit()

    def hideEvent(self,event):
        self.dismiss_bubble();self._mood_timer.stop();self.clear_mood()

    def contextMenuEvent(self,event):
        if self.menu:self.menu.exec(event.globalPos())


class ClockFace(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(195)
        self.seconds=25*60;self.progress=0;self.caption="准备好了就开始";self.running=False

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x=(self.width()-168)/2; r=QRectF(x,8,168,168)
        p.setPen(QPen(QColor("#F0E8D0"),6));p.drawEllipse(r)
        p.setPen(QPen(QColor("#D6A633"),6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        p.drawArc(r,90*16,-int(360*16*self.progress))
        p.setPen(QColor("#664B22"));p.setFont(QFont("Segoe UI",32,QFont.Weight.DemiBold))
        p.drawText(QRectF(x,44,168,65),Qt.AlignmentFlag.AlignCenter,f"{self.seconds//60:02d}:{self.seconds%60:02d}")
        p.setFont(QFont("Microsoft YaHei UI",10));p.setPen(QColor("#7C8B7B"))
        p.drawText(QRectF(x,111,168,30),Qt.AlignmentFlag.AlignCenter,self.caption)


class FocusPanel(QWidget):
    start_requested=Signal()
    stop_requested=Signal()
    rest_requested=Signal()
    encourage=Signal()
    action_requested=Signal(str)
    camera_requested=Signal()
    history_requested=Signal()
    chat_requested=Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("panel");self.setWindowTitle("雨衣皮卡丘 · 学习面板")
        self.setWindowIcon(pet_icon());self.setFixedWidth(430)
        outer=QVBoxLayout(self);outer.setContentsMargins(30,25,30,22);outer.setSpacing(14)
        header=QHBoxLayout()
        icon=QLabel();icon.setPixmap(pet_icon().pixmap(QSize(52,52)));header.addWidget(icon)
        title_col=QVBoxLayout();title_col.setSpacing(1)
        title=QLabel("雨衣皮卡丘");title.setObjectName("title");title_col.addWidget(title)
        sub=QLabel("你的学习搭子");sub.setObjectName("muted");title_col.addWidget(sub)
        header.addLayout(title_col);header.addStretch()
        self.pet_settings=QPushButton('桌宠设置');self.pet_settings.setAccessibleName('桌宠设置')
        self.pet_settings.setStyleSheet('QPushButton{padding:7px 9px;font-size:12px;}')
        header.addWidget(self.pet_settings);outer.addLayout(header)
        self.camera_entry=QPushButton('视觉陪伴')
        self.camera_entry.setToolTip('开启本地预览、手机检测和眉部关怀；摄像头默认关闭')
        self.camera_entry.clicked.connect(self.camera_requested)
        self.history_entry=QPushButton('学习记录');self.history_entry.clicked.connect(self.history_requested)
        self.chat_entry=QPushButton('学习对话');self.chat_entry.clicked.connect(self.chat_requested)
        entries=QHBoxLayout();entries.addWidget(self.camera_entry,1);entries.addWidget(self.history_entry,1);entries.addWidget(self.chat_entry,1);outer.addLayout(entries)
        question=QLabel("这次想完成什么？");question.setObjectName("question");outer.addWidget(question)
        self.task=QLineEdit();self.task.setPlaceholderText("比如：读完第三章，或写完一道题");self.task.setMaxLength(80)
        self.task.returnPressed.connect(self.start_requested);outer.addWidget(self.task)
        durations=QHBoxLayout();durations.setSpacing(7)
        self.choices=[];self.duration_group=QButtonGroup(self)
        for minutes in (15,25,45):
            b=QPushButton(f"{minutes} 分钟");b.setCheckable(True)
            self.duration_group.addButton(b,minutes);self.choices.append(b);durations.addWidget(b)
            b.clicked.connect(lambda checked=False,m=minutes:self.duration.setValue(m))
        self.duration=QSpinBox();self.duration.setRange(1,120);self.duration.setValue(25);self.duration.setSuffix(" 分钟")
        self.duration.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.duration.setToolTip("自定义时长，支持1到120分钟")
        self.duration.setMinimumWidth(95);durations.addWidget(self.duration)
        self.duration.valueChanged.connect(self.sync_duration);self.sync_duration(25)
        outer.addLayout(durations)
        self.clock=ClockFace();outer.addWidget(self.clock)
        self.active_task=QLabel("一次只做一件事，我陪着你。");self.active_task.setWordWrap(True)
        self.active_task.setAlignment(Qt.AlignmentFlag.AlignCenter);outer.addWidget(self.active_task)
        controls=QHBoxLayout()
        self.start=QPushButton("开始专注");self.start.setObjectName("primary");self.start.setMinimumHeight(43)
        self.start.clicked.connect(self.start_requested);controls.addWidget(self.start,2)
        self.stop=QPushButton("结束本轮");self.stop.setMinimumHeight(43);self.stop.clicked.connect(self.stop_requested)
        controls.addWidget(self.stop,1);outer.addLayout(controls)
        links=QHBoxLayout()
        self.rest=QPushButton("休息 5 分钟");self.rest.setObjectName("textButton");self.rest.clicked.connect(self.rest_requested)
        self.cheer=QPushButton("给我一点鼓励");self.cheer.setObjectName("textButton");self.cheer.clicked.connect(self.encourage)
        links.addWidget(self.rest);links.addWidget(self.cheer);outer.addLayout(links)
        actions=QHBoxLayout();actions.setSpacing(7);self.action_buttons={}
        for key,label in [("idle","待机"),("care","关心我"),("remind","提醒我"),("encourage","为我加油")]:
            button=QPushButton(label);button.setToolTip(f"让皮卡丘做出{ACTION_LABELS[key]}动作")
            button.clicked.connect(lambda checked=False,k=key:self.action_requested.emit(k))
            actions.addWidget(button);self.action_buttons[key]=button
        outer.addLayout(actions)
        self.summary=QLabel();self.summary.setObjectName("muted");self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.summary)
        tip=QLabel("摸头或戳肚子 · 拖动移动 · 滚轮缩放");tip.setObjectName("muted")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter);outer.addWidget(tip)
        self.adjustSize()

    def sync_duration(self, minutes):
        self.duration_group.setExclusive(False)
        for b in self.choices:b.setChecked(self.duration_group.id(b)==minutes)
        self.duration_group.setExclusive(True)

    def closeEvent(self,event):
        self.hide();event.ignore()


class Companion:
    """Coordinates task state and feedback. Future perception modules can call feedback()."""
    def __init__(self, store: Store, tray_enabled=True,music_autostart=None):
        self.store=store;self.session=FocusSession();self._accounted=False
        self.history=store.history;self.history.recover_incomplete();self.history_panel=None
        self._history_id=None;self._history_saved_elapsed=0.;self._last_checkpoint=-float('inf')
        self.reminder_gate=ReminderGate()
        self.vision_controller=None;self.camera_panel=None
        self.chat_panel=None
        self.pet=PetWindow();self.panel=FocusPanel()
        self.music_enabled=bool(store.get('music_enabled',True))
        self.music_controller=MusicController(self.pet)
        self.music_controller.state_changed.connect(self.on_music_state)
        self.music_controller.busy_changed.connect(self.pet.music_card.set_busy)
        self.music_controller.command_finished.connect(self.pet.music_card.show_error)
        self.pet.music_command.connect(self.music_controller.command)
        QApplication.instance().aboutToQuit.connect(self.music_controller.shutdown)
        try:self.pet.set_scale(int(store.get("scale",100)))
        except (ValueError,TypeError):pass
        self.pet.set_topmost(bool(store.get("topmost",True)))
        self.pet.set_locked(bool(store.get('locked',False)))
        self.pet.set_bubbles_enabled(bool(store.get('bubbles',True)))
        try:
            minutes=max(1,min(120,int(store.get("minutes",25))))
        except (ValueError,TypeError):minutes=25
        self.panel.duration.setValue(minutes)
        self.panel.task.setText(str(store.get("task",""))[:80])
        self.panel.duration.valueChanged.connect(self.refresh)
        self.panel.start_requested.connect(self.toggle)
        self.panel.stop_requested.connect(self.stop)
        self.panel.rest_requested.connect(self.rest)
        self.panel.encourage.connect(self.encourage)
        self.panel.action_requested.connect(self.perform_action)
        self.panel.camera_requested.connect(self.show_camera)
        self.panel.history_requested.connect(self.show_history)
        self.panel.chat_requested.connect(self.show_chat)
        self.pet.reminder_response.connect(self.respond_to_reminder)
        self.pet.touched.connect(self.touch)
        self.pet.open_panel.connect(self.show_panel)
        self.pet.pause_requested.connect(self.toggle)
        self.pet.quit_requested.connect(self.quit)
        self.pet.position_changed.connect(self.save_position)
        self.pet.scale_changed.connect(lambda _:self.save_position())
        self.tray_menu=self.create_menu();self.pet.menu=self.tray_menu
        self.panel.pet_settings.setMenu(self.tray_menu)
        self.quit_shortcut=QShortcut(QKeySequence("Ctrl+Q"),self.panel)
        self.quit_shortcut.activated.connect(self.quit)
        self.tray=None
        if tray_enabled and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray=QSystemTrayIcon(pet_icon(),self.pet);self.tray.setToolTip("雨衣皮卡丘 · 你的学习搭子")
            self.tray.setContextMenu(self.tray_menu)
            self.tray.activated.connect(self.tray_activated)
            self.tray.show()
        screen=QApplication.primaryScreen().availableGeometry()
        anchor=self.store.get('anchor');pos=self.store.get("position")
        if isinstance(anchor,list) and len(anchor)==2 and all(isinstance(x,(int,float)) for x in anchor):
            self.pet.move_to_anchor(QPointF(anchor[0],anchor[1]))
        elif isinstance(pos,list) and len(pos)==2 and all(isinstance(x,int) for x in pos):
            point=QPoint(*pos)
            if any(s.availableGeometry().intersects(self.pet.rect().translated(point)) for s in QApplication.screens()):
                self.pet.move_bounded(point.toPointF())
            else:self.pet.move(screen.right()-self.pet.width()-38,screen.bottom()-self.pet.height()-18)
        else:self.pet.move(screen.right()-self.pet.width()-38,screen.bottom()-self.pet.height()-18)
        self.timer=QTimer(self.pet);self.timer.timeout.connect(self.on_tick);self.timer.start(200)
        self.pet.show();self.feedback("摸摸头或戳戳肚子，\n双击打开面板，右键还有更多。","idle")
        self.refresh()
        if self.music_enabled and (tray_enabled if music_autostart is None else music_autostart):
            QTimer.singleShot(0,self.music_controller.start)

    def feedback(self,text,mood="encourage",notify=False):
        if self.pet.isVisible():self.pet.say(text,mood)
        if notify and self.tray:
            self.tray.showMessage("皮卡丘",text,QSystemTrayIcon.MessageIcon.Information,8000)

    def create_menu(self):
        menu=QMenu(self.pet)
        menu.addAction("打开学习面板",self.show_panel)
        menu.addAction('视觉陪伴 · 摄像头',self.show_camera)
        menu.addAction('学习记录',self.show_history)
        menu.addAction('和皮卡丘聊聊 · DeepSeek',self.show_chat)
        music=menu.addMenu('QQ 音乐联动')
        self.music_action=music.addAction('自动显示音乐条');self.music_action.setCheckable(True)
        self.music_action.setChecked(self.music_enabled);self.music_action.triggered.connect(self.toggle_music)
        self.music_status=music.addAction('等待 QQ 音乐播放');self.music_status.setEnabled(False)
        music.addAction('重新检测 QQ 音乐',self.retry_music)
        samples=menu.addMenu('发送示例提醒')
        samples.addAction('示例：手机提醒',lambda:self.send_sample('phone'))
        samples.addAction('示例：眉部关怀',lambda:self.send_sample('care'))
        self.visibility_action=menu.addAction("隐藏桌宠",self.toggle_pet)
        self.recover_action=menu.addAction('找回桌宠 · 回到右下角',self.recover_pet)
        self.lock_action=menu.addAction('锁定位置');self.lock_action.setCheckable(True)
        self.lock_action.triggered.connect(self.toggle_locked)
        self.bubbles_action=menu.addAction('显示气泡提示');self.bubbles_action.setCheckable(True)
        self.bubbles_action.triggered.connect(self.toggle_bubbles)
        self.pause_action=menu.addAction("暂停学习",self.toggle)
        menu.addSeparator()
        motions=menu.addMenu("互动动作")
        for key in ("idle","care","remind","encourage","pet","poke","rest"):
            motions.addAction(ACTION_LABELS[key],lambda checked=False,k=key:self.perform_action(k))
        self.size_menu=menu.addMenu("桌宠大小")
        self.scale_group=QActionGroup(menu);self.scale_actions={}
        for percent in (70,85,100,125,150,160):
            action=self.size_menu.addAction(f"{percent}%");action.setCheckable(True)
            action.triggered.connect(lambda checked=False,s=percent:self.pet.set_scale(s))
            self.scale_group.addAction(action);self.scale_actions[percent]=action
        menu.addAction("恢复默认大小",lambda:self.pet.set_scale(100))
        self.top_action=menu.addAction("始终置顶");self.top_action.setCheckable(True)
        self.top_action.triggered.connect(self.toggle_topmost)
        menu.addSeparator();menu.addAction("退出皮卡丘",self.quit)
        menu.aboutToShow.connect(self.sync_menu)
        return menu

    def sync_menu(self):
        self.music_action.setChecked(self.music_enabled)
        self.visibility_action.setText("隐藏桌宠" if self.pet.isVisible() else "显示桌宠")
        self.pause_action.setText("继续学习" if self.session.status==Status.PAUSED else "暂停学习")
        self.pause_action.setEnabled(self.session.status in {Status.RUNNING,Status.PAUSED})
        self.top_action.setChecked(bool(self.pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))
        self.lock_action.setChecked(self.pet.position_locked)
        self.bubbles_action.setChecked(self.pet.bubbles_enabled)
        self.size_menu.setTitle(f"桌宠大小 · {self.pet.scale_percent}%")
        for value,action in self.scale_actions.items():action.setChecked(value==self.pet.scale_percent)

    def on_music_state(self,state):
        self.pet.set_music_state(state)
        self.music_status.setText(state.message)
        self.music_status.setToolTip('QQ 音乐需开放 Windows 系统媒体控制。'+state.message)

    def toggle_music(self,enabled):
        self.music_enabled=bool(enabled);self.store.save(music_enabled=self.music_enabled)
        if self.music_enabled:self.music_controller.start()
        else:self.music_controller.stop()

    def retry_music(self):
        if self.music_enabled:self.music_controller.retry()

    def shutdown_music(self):self.music_controller.shutdown();self.pet._music_timer.stop()

    def toggle_pet(self):
        self.pet.hide() if self.pet.isVisible() else self.show_pet()

    def toggle_topmost(self,enabled):
        self.pet.set_topmost(enabled);self.store.save(topmost=enabled)

    def toggle_locked(self,locked):
        self.pet.set_locked(locked);self.store.save(locked=locked)

    def toggle_bubbles(self,enabled):
        self.pet.set_bubbles_enabled(enabled);self.store.save(bubbles=enabled)

    def recover_pet(self):
        self.pet.ensure_on_screen();self.pet.reset_position();self.show_pet()

    def tray_activated(self,reason):
        if reason==QSystemTrayIcon.ActivationReason.Trigger:self.show_pet()
        elif reason==QSystemTrayIcon.ActivationReason.DoubleClick:self.restore()

    def restore(self):
        self.show_pet();self.show_panel()

    def touch(self,region):
        key={"head":"pet","body":"poke","tail":"tail"}.get(region,"pet")
        self.perform_action(key)

    def perform_action(self,key):
        messages={"idle":"皮卡丘在这里，\n安安静静地陪着你。", "care":"辛苦啦，先放松一下。\n要不要喝口水？",
                  "remind":"皮卡！该看看学习目标啦。\n我们一起完成这一小步。", "encourage":"皮卡皮卡！给你充满电，\n你一定可以的！",
                  "pet":"皮～卡～好舒服！\n再摸一下也可以哦。", "poke":"皮卡？！肚子痒痒的！", "tail":"尾巴收到一份能量，\n给你一颗小星星！", "rest":"陪你闭眼歇一会儿。\n准备好了再出发。"}
        self.show_pet();self.feedback(messages[key],key)

    def show_pet(self):
        self.pet.ensure_on_screen();self.pet.show();self.pet.raise_()

    def show_panel(self):
        if not self.panel.isVisible():
            area=(self.pet.screen() or QApplication.primaryScreen()).availableGeometry()
            target_x=self.pet.x()-self.panel.width()-18
            x=max(area.left()+16,min(target_x,area.right()-self.panel.width()-16))
            y=max(area.top()+16,min(self.pet.y()-120,area.bottom()-self.panel.height()-16))
            self.panel.move(x,y)
        self.panel.showNormal();self.panel.raise_();self.panel.activateWindow()

    def show_camera(self):
        if self.camera_panel is None:
            from .camera import VisionController
            from .camera_ui import CameraPanel
            from .perception import VisionSettings
            self.vision_controller=VisionController(self.pet)
            QApplication.instance().aboutToQuit.connect(self.vision_controller.shutdown)
            self.camera_panel=CameraPanel(self.vision_controller,
                VisionSettings.from_dict(self.store.get('vision',{})),
                context=lambda:(self.session.kind=='focus' and self.session.status==Status.RUNNING and self.session.remaining>0,
                                self.pet.isVisible()),gate=self.reminder_gate)
            self.camera_panel.setWindowIcon(pet_icon())
            self.camera_panel.settings_changed.connect(lambda settings:self.store.save(vision=settings))
            self.camera_panel.feedback_requested.connect(self.receive_vision_event)
            self.camera_panel.mirror.setChecked(bool(self.store.get('vision_mirror',True)))
            self.camera_panel.mirror.toggled.connect(lambda value:self.store.save(vision_mirror=value))
            self.camera_panel.scan()
        if not self.camera_panel.isVisible():
            area=(self.pet.screen() or QApplication.primaryScreen()).availableGeometry()
            self.camera_panel.move(area.center()-self.camera_panel.rect().center())
        self.camera_panel.showNormal();self.camera_panel.raise_();self.camera_panel.activateWindow()

    def show_history(self):
        if self.history_panel is None:
            from .history_ui import HistoryPanel
            self.history_panel=HistoryPanel(self.history,lambda:self.checkpoint_round(force=True),self.can_control_reminder)
            self.history_panel.setWindowIcon(pet_icon())
            self.history_panel.response_requested.connect(self.respond_to_reminder)
            self.history_panel.sample_requested.connect(self.send_sample)
        if not self.history_panel.isVisible():
            area=(self.pet.screen() or QApplication.primaryScreen()).availableGeometry()
            self.history_panel.resize(min(1000,area.width()-32),min(700,area.height()-64))
            self.history_panel.move(area.center()-self.history_panel.rect().center())
        self.history_panel.showNormal();self.history_panel.raise_();self.history_panel.activateWindow()

    def chat_context(self):
        s=self.session;active=s.status in {Status.RUNNING,Status.PAUSED}
        states={Status.IDLE:'未开始',Status.RUNNING:'进行中',Status.PAUSED:'已暂停',Status.COMPLETED:'已完成'}
        return {'task':s.task if active else self.panel.task.text().strip(),
            'state':states[s.status],'kind':s.kind if active else 'focus',
            'planned_minutes':s.duration//60 if active else self.panel.duration.value(),
            'remaining_seconds':s.display_seconds if active else 0}

    def show_chat(self):
        if self.chat_panel is None:
            from .chat_ui import ChatPanel
            self.chat_panel=ChatPanel(self.store,self.chat_context,
                lambda:self.session.status not in {Status.RUNNING,Status.PAUSED})
            self.chat_panel.setWindowIcon(pet_icon())
            self.chat_panel.reply_for_pet.connect(lambda text:self.feedback(text,'care'))
            self.chat_panel.task_selected.connect(self.apply_chat_task)
        if not self.chat_panel.isVisible():
            area=(self.pet.screen() or QApplication.primaryScreen()).availableGeometry()
            self.chat_panel.resize(min(1040,area.width()-32),min(750,area.height()-64))
            self.chat_panel.move(area.center()-self.chat_panel.rect().center())
        self.chat_panel.showNormal();self.chat_panel.raise_();self.chat_panel.activateWindow()

    def apply_chat_task(self,title,minutes):
        if self.session.status in {Status.RUNNING,Status.PAUSED}:
            if self.chat_panel:self.chat_panel.status.setText('请先完成或结束当前一轮，再选择下一项任务。')
            return False
        if self.session.status==Status.COMPLETED:
            self.account();self.session.reset();self._history_saved_elapsed=0.
        self.panel.task.setText(title[:80]);self.panel.duration.setValue(max(1,min(120,minutes)))
        self.store.save(task=self.panel.task.text(),minutes=self.panel.duration.value())
        self.refresh()
        self.show_panel();return True

    def shutdown_chat(self):
        if self.chat_panel is not None:self.chat_panel.shutdown();self.chat_panel.hide()

    def checkpoint_round(self,force=False,status=None):
        s=self.session
        if s.status==Status.IDLE or not s.round_id:return
        now=s.clock()
        if not force and (self._accounted or (s.round_id==self._history_id and now-self._last_checkpoint<10)):return
        if self.history.ensure_session(s) is None:return
        state=status or s.status.value
        value=self.history.checkpoint(s.round_id,s.elapsed,state,s.pause_count,now=s.wall_clock())
        if value is not None:
            self._history_id=s.round_id;self._history_saved_elapsed=value;self._last_checkpoint=now

    def receive_vision_event(self,event):
        if not self.pet.isVisible() or event.kind not in {'phone','care'}:return None
        return self.present_reminder(event,'vision')

    def send_sample(self,kind='phone'):
        examples={'phone':FeedbackEvent('phone','这是一条手机提醒示例。\n试着告诉我：正在查资料、识别错了，或稍后提醒。','remind'),
                  'care':FeedbackEvent('care','这是一条关怀提醒示例。\n辛苦啦，要不要放松一下眉头？','care')}
        if kind not in examples:return None
        self.show_pet()
        return self.present_reminder(examples[kind],'example')

    def present_reminder(self,event,source):
        linked=None
        if source=='vision' and self.session.kind=='focus' and self.session.status in {Status.RUNNING,Status.PAUSED}:
            self.checkpoint_round(force=True);linked=self.session.round_id
        event_id=self.history.add_reminder(event.kind,event.text,source,linked)
        self.pet.say(event.text,event.mood,20000,reminder=(event_id,event.kind) if event_id else None)
        if self.history_panel is not None and self.history_panel.isVisible():self.history_panel.refresh_data()
        if source=='example' and not self.pet.bubbles_enabled:
            self.show_history();self.history_panel.reveal_reminder(event_id)
            self.history_panel.message.setText('气泡提示已关闭，可以在这里回应示例。')
        return event_id

    def can_control_reminder(self,event):
        if event['source']=='example':return True
        if event['session_id']:
            return event['session_id']==self.session.round_id and self.session.status in {Status.RUNNING,Status.PAUSED}
        age=(self.history.clock()-parse(event['created_at'])).total_seconds()
        return 0<=age<=120

    def respond_to_reminder(self,event_id,response):
        event=self.history.reminder(event_id)
        if not event or (response=='research' and event['kind']!='phone'):return False
        controls=self.can_control_reminder(event)
        if response!='false_positive' and not controls:return False
        if not self.history.respond(event_id,response):return False
        if event['source']=='example':message='示例回应已记录。\n真实提醒设置保持不变。'
        else:
            if controls:self.reminder_gate.apply(response,event['kind'])
            if response=='research':message='好呀，安心查资料。\n手机提醒暂停5分钟，关怀继续保留。'
            elif response=='snooze':message='好的，接下来10分钟\n我会暂停视觉提醒。'
            elif controls:message='已记下这次误报。\n1分钟内不重复这类提醒。'
            else:message='已补记这次误报。\n谢谢你的反馈。'
        if self.camera_panel is not None and event['source']=='vision' and controls:
            self.camera_panel.policy.reset_evidence();self.camera_panel.update_reminder_controls()
            self.camera_panel.notice.setText(message.replace('\n',' '))
        if self.pet.isVisible():self.pet.say(message,'care')
        if self.history_panel is not None:
            self.history_panel.refresh_data();self.history_panel.message.setText(message.replace('\n',' '))
        return True

    def shutdown_vision(self):
        if self.vision_controller is not None:self.vision_controller.shutdown()
        if self.camera_panel is not None:self.camera_panel.preview.clear()

    def save_position(self):
        anchor=self.pet.foot_anchor()
        self.store.save(position=[self.pet.x(),self.pet.y()],anchor=[anchor.x(),anchor.y()],scale=self.pet.scale_percent)

    def account(self,reason='stopped'):
        if not self._accounted and self.session.status!=Status.IDLE:
            self.checkpoint_round(force=True,status='completed' if self.session.status==Status.COMPLETED else reason)
            self._accounted=True

    def begin(self,kind="focus"):
        self.account('replaced')
        minutes=5 if kind=="break" else self.panel.duration.value()
        self.session.start(minutes,self.panel.task.text(),kind)
        self._accounted=False
        self._history_saved_elapsed=0.;self._last_checkpoint=-float('inf')
        self.reminder_gate.reset_round();self.checkpoint_round(force=True)
        self.store.save(minutes=self.panel.duration.value(),task=self.panel.task.text())
        self.feedback("先放松一下，五分钟后我叫你。" if kind=="break" else "皮卡！开始啦。\n你专心，我陪你。", "rest" if kind=="break" else "encourage")
        self.refresh()

    def toggle(self):
        # Complete expired rounds before acting on a possibly delayed UI callback.
        if self.session.tick():
            self.completed()
            return
        if self.session.status in {Status.IDLE,Status.COMPLETED}:
            self.begin()
        elif self.session.status==Status.RUNNING:
            self.session.pause();self.checkpoint_round(force=True);self.feedback("先停一会儿也没关系。\n准备好再继续。","care")
        else:
            self.session.resume();self.checkpoint_round(force=True);self.feedback("欢迎回来，继续一起加油。")
        self.refresh()

    def stop(self):
        if self.session.tick():self.completed()
        if self.session.status==Status.IDLE:return
        self.account();self.session.reset();self.reminder_gate.reset_round()
        self.feedback("这一段辛苦啦。\n想继续时，再来找我。","care");self.refresh()

    def rest(self):
        if self.session.status in {Status.RUNNING,Status.PAUSED}:return
        self.begin("break")

    def completed(self):
        self.account()
        if self.session.kind=="break":self.feedback("休息结束啦。\n准备好开始下一轮了吗？","remind",notify=True)
        else:self.feedback("这一轮完成啦，辛苦了！\n伸个懒腰，休息一下吧。","remind",notify=True)
        self.refresh()

    def on_tick(self):
        if self.session.tick() or (self.session.status==Status.COMPLETED and not self._accounted):
            self.completed()
        self.checkpoint_round()
        self.refresh()

    def encourage(self):
        choices=["不用一下做完。\n先完成眼前这一小步。","你认真投入的时间，\n都算数。","我在呢，慢慢来。\n累了就休息一下。","摸摸收到！\n我们再一起努力一会儿。"]
        self.show_pet();self.feedback(random.choice(choices),"care" if self.session.status==Status.PAUSED else "encourage")

    def refresh(self):
        s=self.session;p=self.panel
        active=s.status in {Status.RUNNING,Status.PAUSED}
        p.task.setEnabled(not active);p.duration.setEnabled(not active)
        for b in p.choices:b.setEnabled(not active)
        p.stop.setEnabled(s.status!=Status.IDLE);p.rest.setEnabled(not active)
        seconds=s.display_seconds if s.status!=Status.IDLE else p.duration.value()*60
        p.clock.seconds=seconds;p.clock.progress=s.progress if s.status!=Status.IDLE else 0
        if s.status==Status.IDLE:
            caption="准备好了就开始";button="开始专注";badge="开始专注";task="一次只做一件事，我陪着你。"
        elif s.status==Status.COMPLETED:
            caption="这一轮完成啦";button="再学一轮";badge="完成啦 · 休息一下";task=s.task
        else:
            paused=s.status==Status.PAUSED
            caption="已暂停" if paused else ("好好休息一下" if s.kind=="break" else "正在专注")
            button="继续" if paused else "暂停一下"
            badge=f"{'已暂停' if paused else ('休息中' if s.kind=='break' else '专注中')} · {seconds//60:02d}:{seconds%60:02d}"
            task=s.task
        p.clock.caption=caption;p.clock.update();p.start.setText(button)
        p.active_task.setText(task);self.pet.badge.setText(badge)
        self.pet.base_mood="rest" if s.kind=="break" and active else "idle"
        if not self.pet._mood_timer.isActive():self.pet.clear_mood()
        stats=self.store.today()
        pending=max(0,int(s.elapsed)-int(self._history_saved_elapsed)) if active and s.kind=='focus' and not self._accounted else 0
        now_seconds=stats['seconds']+pending
        p.summary.setText(f"今天已专注 {now_seconds//60} 分钟 · 完成 {stats['completed']} 轮")

    def quit(self):
        if self.session.tick():self.account()
        self.account('exited');self.save_position()
        self.store.save(minutes=self.panel.duration.value(),task=self.panel.task.text())
        if self.tray:self.tray.hide()
        self.shutdown_vision()
        self.shutdown_chat()
        self.shutdown_music()
        if self.history_panel is not None:self.history_panel.hide()
        QApplication.quit()
