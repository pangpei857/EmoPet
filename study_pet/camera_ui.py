"""User-controlled local vision preview and reminder settings."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QAbstractSpinBox,QCheckBox,QComboBox,QDoubleSpinBox,QFileDialog,QFormLayout,
    QHBoxLayout,QLabel,QLayout,QPushButton,QScrollArea,QSizePolicy,QSpinBox,QVBoxLayout,QWidget,QGroupBox)

from .perception import BrowCalibration, ReminderPolicy, VisionSettings, ReminderGate
from .face_tracking import FaceDiagnostics

FACE_REASONS={
    'acquiring_primary':'正在确认主用户','primary_missing':'主用户暂时离开',
    'extra_face_pending':'额外人脸待确认','phone_unaligned':'手机与人脸时间未对齐',
    'phone_candidate_pending':'疑似手机假脸，正在验证',
    'single_recovery':'正在确认恢复单人','confirmed_multiple':'已确认多人',
    'stale_face':'面部结果过期','invalid_timestamp':'时间戳异常',
    'stable_primary':'主用户稳定','phone_attached_filtered':'已排除疑似手机假脸',
}


class _StepButtons:
    """Visible text controls instead of platform-dependent spin arrow glyphs."""
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.plus_button=QPushButton('+',self);self.minus_button=QPushButton('−',self)
        for button,label in ((self.plus_button,'增加'),(self.minus_button,'减少')):
            button.setAccessibleName(label);button.setToolTip(label)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus);button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAutoRepeat(True);button.setAutoRepeatDelay(400);button.setAutoRepeatInterval(100)
            button.setStyleSheet('''QPushButton { padding:0; min-width:0; min-height:0;
                border:0; border-left:1px solid #DCE4DD; border-radius:0;
                background:#FFF3CE; color:#6F501C; font-size:17px; font-weight:600; }
                QPushButton:hover { background:#FFE4A0; }
                QPushButton:pressed { background:#F3CF70; }
                QPushButton:disabled { color:#B9B6AC; background:#F2F2EB; }''')
        self.plus_button.clicked.connect(self.stepUp);self.minus_button.clicked.connect(self.stepDown)
        self.valueChanged.connect(self.update_steps)

    def update_steps(self,*args):
        self.plus_button.setEnabled(not self.isReadOnly() and self.value()<self.maximum())
        self.minus_button.setEnabled(not self.isReadOnly() and self.value()>self.minimum())

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if not hasattr(self,'plus_button'):return
        width=28;top=(self.height()-2)//2
        self.plus_button.setGeometry(self.width()-width-1,1,width,top)
        self.minus_button.setGeometry(self.width()-width-1,top+1,width,self.height()-top-2)
        self.lineEdit().setGeometry(9,1,max(1,self.width()-width-14),self.height()-2)
        self.plus_button.raise_();self.minus_button.raise_();self.update_steps()

    def showEvent(self,event):
        super().showEvent(event);self.update_steps()


class TimeSpinBox(_StepButtons,QSpinBox):
    pass


class ThresholdSpinBox(_StepButtons,QDoubleSpinBox):
    pass


class PreviewCanvas(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(420,180)
        self.image=None;self.observation=None;self.mirrored=True
        self.message='开启摄像头后，画面会显示在这里。'
        self.setAccessibleName('本地视觉预览')

    def clear(self,message='摄像头已关闭'):
        self.image=None;self.observation=None;self.message=message;self.update()

    def set_frame(self,item):
        self.image=QImage(item['rgb'],item['width'],item['height'],item['width']*3,QImage.Format.Format_RGB888).copy()
        self.observation=item.get('observation',self.observation);self.update()

    def paintEvent(self,event):
        p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(),QColor('#202D2C'))
        if self.image is None:
            p.setPen(QColor('#D1DBD4'))
            p.drawText(self.rect().adjusted(20,20,-20,-20),Qt.AlignmentFlag.AlignCenter|Qt.TextFlag.TextWordWrap,self.message)
            return
        size=self.image.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
        target=QRectF((self.width()-size.width())/2,(self.height()-size.height())/2,size.width(),size.height())
        p.drawImage(target,self.image.mirrored(True,False) if self.mirrored else self.image)
        def point(x,y):return QPointF(target.x()+(1-x if self.mirrored else x)*target.width(),target.y()+y*target.height())
        def box_rect(box):
            left=1-box.x2 if self.mirrored else box.x1
            return QRectF(target.x()+left*target.width(),target.y()+box.y1*target.height(),
                          (box.x2-box.x1)*target.width(),(box.y2-box.y1)*target.height())
        o=self.observation
        if o is None:return
        o=o.freshened(time.monotonic())
        for index,face in enumerate(o.faces if o.face_fresh else ()):
            excluded=index in o.filtered_faces
            primary=o.has_primary and (index==o.primary_face or o.face_state is None)
            p.setPen(QPen(QColor('#89948D' if excluded else '#A3D7B5' if primary else '#E8BC70'),
                2.5 if primary else 1.5,Qt.PenStyle.DashLine if excluded else Qt.PenStyle.SolidLine))
            p.drawRoundedRect(box_rect(face),5,5)
        for hand in o.hands if o.face_fresh else ():
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#7DD7CE'))
            for x,y in hand:p.drawEllipse(point(x,y),2,2)
        for phone in o.phones if o.phone_fresh else ():
            rect=box_rect(phone);p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor('#FFD36A'),2.5));p.drawRect(rect)
            label=QRectF(rect.left(),max(target.top(),rect.top()-24),100,23)
            p.fillRect(label,QColor('#FFD36A'));p.setPen(QColor('#3B3016'))
            p.drawText(label,Qt.AlignmentFlag.AlignCenter,f'手机 {phone.score:.0%}')


class CameraPanel(QWidget):
    settings_changed=Signal(object)
    feedback_requested=Signal(object)

    def __init__(self,controller,settings=None,context=None,parent=None,gate=None):
        super().__init__(parent)
        self.controller=controller;self.settings=settings or VisionSettings()
        self.context=context or (lambda:(False,True))
        self.policy=ReminderPolicy(self.settings);self.calibration=None
        self.face_diagnostics=FaceDiagnostics()
        self.gate=gate or ReminderGate()
        self._last_notice_at=0.;self._video_mode=False
        self._observation=None;self._last_preview_at=None;self._preview_fps=0.;self._preview_delay=0.
        self._last_diagnostics_at=0.
        self.setWindowTitle('雨衣皮卡丘 · 视觉陪伴')
        self.setObjectName('panel');self.resize(970,680);self.setMinimumSize(860,620)
        outer=QVBoxLayout(self);outer.setContentsMargins(22,20,22,20);outer.setSpacing(13)
        title=QLabel('视觉陪伴');title.setObjectName('title');outer.addWidget(title)
        subtitle=QLabel('画面只在本机处理，不保存视频。开启后，皮卡丘会留意手机与眉部变化。')
        subtitle.setObjectName('muted');subtitle.setWordWrap(True);outer.addWidget(subtitle)
        devices=QHBoxLayout()
        self.devices=QComboBox();self.devices.setMinimumWidth(230)
        self.devices.addItem('正在查找摄像头…',None)
        self.refresh=QPushButton('刷新设备');self.refresh.clicked.connect(self.scan)
        self.start=QPushButton('开启摄像头');self.start.setObjectName('primary');self.start.clicked.connect(self.toggle_capture)
        self.start.setEnabled(False)
        self.video=QPushButton('视频测试');self.video.setToolTip('使用本地视频验证识别；测试视频不会自动触发桌宠提醒。')
        self.video.clicked.connect(self.open_video)
        devices.addWidget(self.devices,1);devices.addWidget(self.refresh);devices.addWidget(self.start);devices.addWidget(self.video)
        outer.addLayout(devices)
        columns=QHBoxLayout();columns.setSpacing(18)
        preview_col=QVBoxLayout();preview_col.setSpacing(6)
        self.preview=PreviewCanvas();preview_col.addWidget(self.preview,1)
        self.status=QLabel('摄像头已关闭');self.status.setWordWrap(True);preview_col.addWidget(self.status)
        self.details=QLabel('手机：—    手部：—    面部：—');self.details.setWordWrap(True);self.details.setObjectName('muted')
        preview_col.addWidget(self.details)
        self.performance=QLabel('预览帧率：— · 面部延迟：—');self.performance.setWordWrap(True)
        self.performance.setObjectName('muted');preview_col.addWidget(self.performance)
        self.mirror=QCheckBox('镜像预览');self.mirror.setChecked(True)
        self.mirror.toggled.connect(self.set_mirror);preview_col.addWidget(self.mirror)
        columns.addLayout(preview_col,1)
        settings_body=QWidget()
        side=QVBoxLayout(settings_body);side.setContentsMargins(0,0,0,0);side.setSpacing(12)
        side.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self.settings_scroll=QScrollArea();self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setMinimumWidth(280);self.settings_scroll.setMaximumWidth(320)
        self.settings_scroll.setStyleSheet('QScrollArea{border:0;background:transparent;} QScrollArea>QWidget>QWidget{background:transparent;}')
        self.settings_scroll.setWidget(settings_body)
        group=QGroupBox('提醒设置');form=QFormLayout(group);form.setSpacing(10)
        group.setStyleSheet('''
            QSpinBox,QDoubleSpinBox { background:white; border:1px solid #DCE4DD;
                border-radius:8px; padding:0 31px 0 9px; min-height:36px; }
            QSpinBox QLineEdit,QDoubleSpinBox QLineEdit {
                border:0; padding:0; min-height:0; background:transparent; }
        ''')
        self.phone=QCheckBox('手机提醒');self.phone.setChecked(self.settings.phone_enabled)
        self.care=QCheckBox('眉部关怀');self.care.setChecked(self.settings.care_enabled)
        self.focus_only=QCheckBox('仅在专注计时中提醒');self.focus_only.setChecked(self.settings.focus_only)
        form.addRow(self.phone);form.addRow(self.care);form.addRow(self.focus_only)
        self.phone_duration=TimeSpinBox();self.phone_duration.setRange(3,60);self.phone_duration.setSuffix(' 秒');self.phone_duration.setValue(self.settings.phone_seconds)
        self.care_duration=TimeSpinBox();self.care_duration.setRange(2,30);self.care_duration.setSuffix(' 秒');self.care_duration.setValue(self.settings.care_seconds)
        self.cooldown=TimeSpinBox();self.cooldown.setRange(30,600);self.cooldown.setSuffix(' 秒');self.cooldown.setValue(self.settings.cooldown_seconds)
        self.brow=ThresholdSpinBox();self.brow.setRange(.10,.95);self.brow.setSingleStep(.01);self.brow.setDecimals(2);self.brow.setValue(self.settings.brow_threshold)
        for control,label in ((self.phone_duration,'手机持续时间（秒）'),(self.care_duration,'眉部持续时间（秒）'),
                              (self.cooldown,'提醒间隔（秒）'),(self.brow,'眉部阈值')):
            control.setMinimumHeight(38);control.setMinimumWidth(130)
            control.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Fixed)
            control.setAccessibleName(label)
            control.plus_button.setAccessibleName('增加'+label);control.minus_button.setAccessibleName('减少'+label)
            control.lineEdit().setAlignment(Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter)
        self.brow.setToolTip('范围 0.10～0.95，越低越敏感。按这里的数值实际判断，校准不会暗中抬高阈值。')
        form.addRow('手机持续',self.phone_duration);form.addRow('眉部持续',self.care_duration)
        form.addRow('提醒间隔',self.cooldown);form.addRow('眉部阈值',self.brow)
        side.addWidget(group)
        self.calibrate=QPushButton('校准自然表情 · 3 秒');self.calibrate.clicked.connect(self.begin_calibration);self.calibrate.setEnabled(False)
        side.addWidget(self.calibrate)
        self.baseline_label=QLabel();self.baseline_label.setWordWrap(True);self.baseline_label.setObjectName('muted');side.addWidget(self.baseline_label)
        self.apply_recommended=QPushButton('使用校准推荐值');self.apply_recommended.clicked.connect(self.use_recommended_threshold)
        side.addWidget(self.apply_recommended)
        self.update_baseline_label()
        self.diagnostics=QLabel('等待识别结果。');self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextFormat(Qt.TextFormat.PlainText)
        self.diagnostics.setStyleSheet('background:#EEF2EB;border-radius:6px;padding:6px;color:#3B5148;')
        preview_col.insertWidget(3,self.diagnostics)
        self.snooze=QPushButton('暂停提醒 10 分钟');self.snooze.clicked.connect(self.toggle_snooze);side.addWidget(self.snooze)
        self.pause_status=QLabel('');self.pause_status.setWordWrap(True);self.pause_status.setObjectName('muted');side.addWidget(self.pause_status)
        self._control_timer=QTimer(self);self._control_timer.timeout.connect(self.update_reminder_controls);self._control_timer.start(1000)
        hint=QLabel('检测到手机仅表示画面里有手机。\n手机靠近手部并持续出现时，才考虑提醒。\n\n额外人脸待确认时暂停累计，确认多人后暂停提醒。灰色虚框为已排除的手机相关候选。眉部变化只用于温和关怀。')
        hint.setWordWrap(True);hint.setObjectName('muted');side.addWidget(hint);side.addStretch()
        columns.addWidget(self.settings_scroll);outer.addLayout(columns,1)
        self.notice=QLabel('等待开启。你可以随时关闭摄像头或暂停提醒。');self.notice.setWordWrap(True)
        self.notice.setStyleSheet('background:#FFF2CD;border-radius:8px;padding:10px;color:#71501D;')
        outer.addWidget(self.notice)
        for control in (self.phone,self.care,self.focus_only):control.toggled.connect(self.save_settings)
        for control in (self.phone_duration,self.care_duration,self.cooldown,self.brow):control.valueChanged.connect(self.save_settings)
        controller.state_changed.connect(self.on_state)
        controller.devices_changed.connect(self.on_devices)
        controller.frame_ready.connect(self.on_frame)
        controller.observation_ready.connect(self.on_observation)

    def scan(self):
        self.refresh.setEnabled(False);self.devices.setEnabled(False)
        self.controller.refresh_devices()

    def on_devices(self,items):
        old=self.devices.currentData();self.devices.clear()
        for item in items:self.devices.addItem(item['name'],item)
        if not items:
            self.devices.addItem('未发现摄像头',None)
            if not self.controller.active:self.status.setText('未发现摄像头。连接后点击“刷新设备”，也可先用本地视频测试识别。')
        elif old:
            for index in range(self.devices.count()):
                item=self.devices.itemData(index)
                if item['index']==old['index'] and item['backend']==old['backend']:self.devices.setCurrentIndex(index);break
        self.refresh.setEnabled(not self.controller.active);self.devices.setEnabled(not self.controller.active)
        self.start.setEnabled(self.controller.active or bool(items))

    def toggle_capture(self):
        if self.controller.active:self.controller.stop();return
        device=self.devices.currentData()
        if device:
            self._video_mode=False;self.policy.reset_evidence()
            self.controller.start(device['index'],device['backend'])

    def open_video(self):
        if self.controller.active:return
        path,_=QFileDialog.getOpenFileName(self,'选择本地视频进行识别测试','','视频文件 (*.mp4 *.avi *.mov *.mkv *.webm)')
        if path:
            self._video_mode=True;self.policy.reset_evidence();self.controller.start(path)

    def on_state(self,state,text):
        active=state in {'starting','running','stopping'}
        self.status.setText(text)
        self.start.setText('关闭视频' if self._video_mode and active else '关闭摄像头' if active else '开启摄像头')
        self.start.setEnabled(state!='stopping' and (active or self.devices.currentData() is not None))
        self.video.setEnabled(not active);self.refresh.setEnabled(not active);self.devices.setEnabled(not active)
        self.calibrate.setEnabled(state=='running' and not self._video_mode)
        if state!='running':
            self.preview.clear(text);self.details.setText('手机：—    手部：—    面部：—')
            self.performance.setText('预览帧率：— · 面部延迟：—');self.diagnostics.setText('等待识别结果。')
            self._observation=None;self._last_preview_at=None;self._preview_fps=0.
            self._last_diagnostics_at=0.
            self.policy.reset_evidence();self.calibration=None
        if state in {'off','error'}:self.notice.setText(text)
        elif state=='running':self.notice.setText('视频测试中：仅显示识别结果，不自动提醒。' if self._video_mode else '已开启本地识别，等待稳定的观察结果。')

    def save_settings(self,*args):
        s=self.settings
        s.phone_enabled=self.phone.isChecked();s.care_enabled=self.care.isChecked();s.focus_only=self.focus_only.isChecked()
        s.phone_seconds=self.phone_duration.value();s.care_seconds=self.care_duration.value()
        s.cooldown_seconds=self.cooldown.value();s.brow_threshold=self.brow.value()
        self.policy.reset_evidence();self.settings_changed.emit(s.as_dict())
        self.update_baseline_label();self.update_diagnostics(force=True)

    def set_mirror(self,checked):self.preview.mirrored=checked;self.preview.update()

    def update_baseline_label(self):
        value=self.settings.baseline
        recommendation=self.settings.recommended_brow_threshold
        text='尚未校准。' if value is None else f'自然基线 {value:.2f} · 推荐阈值 {recommendation:.2f}。'
        self.baseline_label.setText(text+f'\n实际生效阈值：{self.settings.brow_threshold:.2f}，以输入框为准。')
        self.apply_recommended.setEnabled(recommendation is not None)

    def use_recommended_threshold(self):
        value=self.settings.recommended_brow_threshold
        if value is not None:self.brow.setValue(value)

    def begin_calibration(self):
        if self.controller.state!='running' or self._video_mode:return
        self.calibration=BrowCalibration();self.policy.reset_evidence()
        self.notice.setText('请独自正对摄像头，保持自然表情约 3 秒。')

    def toggle_snooze(self):
        self.gate.toggle_snooze()
        self.policy.reset_evidence()
        paused=self.gate.snoozed
        self.update_reminder_controls()
        self.notice.setText('提醒已暂停 10 分钟，预览继续。' if paused else '提醒已恢复。')

    def update_reminder_controls(self):
        gate=self.gate;now=gate.clock()
        self.snooze.setText('恢复提醒' if gate.snoozed else '暂停提醒 10 分钟')
        parts=[]
        for label,deadline in [('全部提醒',gate.snooze_until),('手机提醒',gate.phone_until),('眉部关怀',gate.care_until)]:
            if deadline>now:parts.append(f'{label}暂停，剩余 {max(1,round((deadline-now)/60))} 分钟')
        self.pause_status.setText('\n'.join(parts))
        self.update_diagnostics()
        if self._observation is not None:self.preview.update()

    def on_frame(self,item):
        if self.controller.state!='running':return
        now=time.monotonic()
        if self._last_preview_at is not None and now>self._last_preview_at:
            current=1/(now-self._last_preview_at)
            self._preview_fps=current if not self._preview_fps else .8*self._preview_fps+.2*current
        self._last_preview_at=now
        self._preview_delay=max(0.,(now-item.get('captured_at',now))*1000)
        self.preview.set_frame(item)
        self.update_diagnostics()

    def on_observation(self,o):
        if self.controller.state!='running':return
        self.face_diagnostics.record(o)
        self._observation=o;self.preview.observation=o;self.preview.update()
        if self.calibration is not None:
            value=self.calibration.add(o) if o.face_fresh else None
            if not o.face_fresh:self.calibration=BrowCalibration()
            if value is not None:
                self.settings.baseline=value;self.calibration=None
                self.settings_changed.emit(self.settings.as_dict());self.update_baseline_label()
                self.notice.setText('自然表情校准完成。当前阈值保持不变，可点击“使用校准推荐值”或手动调整。')
            elif not o.faces:self.notice.setText('校准中：请让面部进入画面。')
            elif o.user_state=='multiple':self.notice.setText('校准中：请保持只有一人入镜。')
            elif not o.brow_reliable:self.notice.setText('校准中：等待稳定主用户与可靠的眉部特征。')
            self.update_diagnostics()
            return
        paused=self.gate.snoozed
        focus_active,visible=self.context()
        event=self.policy.update(o,focus_active=focus_active,pet_visible=visible,snoozed=paused or self._video_mode,
            phone_paused=self.gate.phone_paused,care_paused=self.gate.care_paused)
        if event:
            self._last_notice_at=o.timestamp
            self.notice.setText('刚刚提醒：'+event.text.replace('\n',' '));self.feedback_requested.emit(event)
        elif o.timestamp-self._last_notice_at>8:
            if self._video_mode:message='视频测试中：仅显示识别结果，不自动提醒。'
            elif paused:message='提醒已暂停，预览继续。'
            elif not visible:message='桌宠已隐藏，自动提醒暂停。'
            elif self.settings.focus_only and not focus_active:message='预览中。开始专注计时后，才会触发自动提醒。'
            elif o.user_state=='multiple':message='已确认多人入镜，自动提醒暂停。'
            elif not o.faces:message='等待面部进入画面。'
            elif not o.face_fresh:message='面部结果已过期，等待新的识别结果。'
            elif not o.has_primary:message='人脸暂不确定，暂停累计：'+FACE_REASONS.get(o.face_reason,'等待稳定主用户')
            elif self.gate.phone_paused:message='手机提醒暂时暂停，眉部关怀仍按设置工作。'
            elif self.policy.phone_duration>0:message=f'手机靠近手部：{self.policy.phone_duration:.0f} / {self.settings.phone_seconds} 秒'
            elif self.policy.care_duration>0:message=f'眉部变化：{self.policy.care_duration:.0f} / {self.settings.care_seconds} 秒'
            else:message='正在安静陪伴，提醒之间会保留冷却时间。'
            self.notice.setText(message)
        self.update_diagnostics()

    def update_diagnostics(self,force=False):
        now=time.monotonic()
        if not force and now-self._last_diagnostics_at<.2:return
        o=self._observation
        if o is None:
            self.performance.setText(f'预览 {self._preview_fps:.0f} 帧/秒 · 等待识别结果')
            return
        self._last_diagnostics_at=now;o=o.freshened(now)
        phone_text=('等待更新' if not o.phone_fresh else
            f'已识别 {max(p.score for p in o.phones):.0%}' if o.phones else '未识别')
        brow_text=f'{o.brow_score:.2f}' if o.brow_reliable else '等待确认'
        face_text=FACE_REASONS.get(o.face_reason,'单人' if o.has_primary else '等待确认') if o.face_fresh else '已过期'
        self.details.setText(f'手机：{phone_text} · 手部 {len(o.hands) if o.face_fresh else 0} · 人脸候选 {len(o.faces)}（{face_text}）\n'
            f'手部关联：{"满足" if o.phone_near_hand else "不满足"} · 眉部分值 {brow_text} / 阈值 {self.settings.brow_threshold:.2f}')
        age=max(0.,(now-o.timestamp)*1000) if o.asynchronous else o.inference_ms
        self.performance.setText(f'预览 {self._preview_fps:.0f} 帧/秒 · 显示延迟 {self._preview_delay:.0f} ms · 面部结果 {age:.0f} ms\n'
            f'面部 {o.face_ms:.0f} / 手部 {o.hand_ms:.0f} / 手机 {o.phone_ms:.0f} ms · 检测 {o.face_fps:.1f} / {o.phone_fps:.1f} 次/秒')
        self.performance.setToolTip('显示延迟：应用读取画面到界面接收，不含摄像头硬件内部延迟。\n'
            '面部结果：对应画面被读取到现在的时间。\n模型耗时依次为面部、手部、手机；检测频率依次为面部/手部、手机。')
        focus,visible=self.context();s=self.settings
        common=None
        if self._video_mode:common='视频测试，仅显示结果'
        elif self.calibration is not None:common='正在校准，暂停提醒'
        elif self.gate.snoozed:common='全部提醒已暂停'
        elif not visible:common='桌宠已隐藏'
        elif s.focus_only and not focus:common='尚未开始专注计时'
        elif not o.face_fresh:common='面部结果过期，等待更新'
        elif o.user_state=='multiple':common='已确认多人，暂停累计'
        elif not o.faces:common='没有检测到面部'
        elif not o.has_primary:common='暂不确定，暂停累计：'+FACE_REASONS.get(o.face_reason,'等待稳定主用户')
        cooldown=self.policy.cooldown_remaining(o.timestamp)
        def reason(kind):
            phone=kind=='phone'
            if not (s.phone_enabled if phone else s.care_enabled):return '开关已关闭'
            if common:return common
            if self.gate.phone_paused if phone else self.gate.care_paused:return '此类提醒已暂缓'
            if phone:
                if not o.phone_fresh:return '手机结果未就绪或过期'
                if not o.phones:return '未识别到手机'
                if not o.hands:return '已识别手机，未检测到手部'
                if not o.phone_near_hand:return '已识别手机，手部关联不满足'
                progress=f'{self.policy.phone_duration:.1f} / {s.phone_seconds} 秒'
            else:
                if not o.brow_reliable:return '等待主用户的可靠眉部特征'
                if o.brow_score<s.brow_threshold:return f'分值 {o.brow_score:.2f}，未达到 {s.brow_threshold:.2f}'
                progress=f'{self.policy.care_duration:.1f} / {s.care_seconds} 秒'
            if cooldown>0:return f'冷却剩余 {cooldown:.0f} 秒；累计 {progress}'
            return '持续累计 '+progress
        self.diagnostics.setText(f'手机提醒：{reason("phone")}\n眉部关怀：{reason("care")}')

    def closeEvent(self,event):
        self.controller.stop();self.preview.clear();self.calibration=None
        self.hide();event.ignore()
