"""User-controlled local vision preview and reminder settings."""
import time

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox,QComboBox,QDoubleSpinBox,QFileDialog,QFormLayout,
    QHBoxLayout,QLabel,QPushButton,QSpinBox,QVBoxLayout,QWidget,QGroupBox)

from .perception import BrowCalibration, ReminderPolicy, VisionSettings


class PreviewCanvas(QWidget):
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(420,300)
        self.image=None;self.observation=None;self.mirrored=True
        self.message='开启摄像头后，画面会显示在这里。'
        self.setAccessibleName('本地视觉预览')

    def clear(self,message='摄像头已关闭'):
        self.image=None;self.observation=None;self.message=message;self.update()

    def set_frame(self,item):
        self.image=QImage(item['rgb'],item['width'],item['height'],item['width']*3,QImage.Format.Format_RGB888).copy()
        self.observation=item['observation'];self.update()

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
        for face in o.faces:
            p.setPen(QPen(QColor('#A3D7B5'),1.5));p.drawRoundedRect(box_rect(face),5,5)
        for hand in o.hands:
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(QColor('#7DD7CE'))
            for x,y in hand:p.drawEllipse(point(x,y),2,2)
        for phone in o.phones:
            rect=box_rect(phone);p.setBrush(Qt.BrushStyle.NoBrush);p.setPen(QPen(QColor('#FFD36A'),2.5));p.drawRect(rect)
            label=QRectF(rect.left(),max(target.top(),rect.top()-24),100,23)
            p.fillRect(label,QColor('#FFD36A'));p.setPen(QColor('#3B3016'))
            p.drawText(label,Qt.AlignmentFlag.AlignCenter,f'手机 {phone.score:.0%}')


class CameraPanel(QWidget):
    settings_changed=Signal(object)
    feedback_requested=Signal(object)

    def __init__(self,controller,settings=None,context=None,parent=None):
        super().__init__(parent)
        self.controller=controller;self.settings=settings or VisionSettings()
        self.context=context or (lambda:(False,True))
        self.policy=ReminderPolicy(self.settings);self.calibration=None
        self._snooze_until=0.;self._last_notice_at=0.;self._video_mode=False
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
        self.video=QPushButton('视频测试');self.video.setToolTip('使用本地视频验证识别；测试视频不会自动触发桌宠提醒。')
        self.video.clicked.connect(self.open_video)
        devices.addWidget(self.devices,1);devices.addWidget(self.refresh);devices.addWidget(self.start);devices.addWidget(self.video)
        outer.addLayout(devices)
        columns=QHBoxLayout();columns.setSpacing(18)
        preview_col=QVBoxLayout()
        self.preview=PreviewCanvas();preview_col.addWidget(self.preview,1)
        self.status=QLabel('摄像头已关闭');self.status.setWordWrap(True);preview_col.addWidget(self.status)
        self.details=QLabel('手机：—    手部：—    面部：—');self.details.setWordWrap(True);self.details.setObjectName('muted')
        preview_col.addWidget(self.details)
        self.mirror=QCheckBox('镜像预览');self.mirror.setChecked(True)
        self.mirror.toggled.connect(self.set_mirror);preview_col.addWidget(self.mirror)
        columns.addLayout(preview_col,1)
        side=QVBoxLayout();side.setSpacing(12)
        group=QGroupBox('提醒设置');form=QFormLayout(group);form.setSpacing(10)
        self.phone=QCheckBox('手机提醒');self.phone.setChecked(self.settings.phone_enabled)
        self.care=QCheckBox('眉部关怀');self.care.setChecked(self.settings.care_enabled)
        self.focus_only=QCheckBox('仅在专注计时中提醒');self.focus_only.setChecked(self.settings.focus_only)
        form.addRow(self.phone);form.addRow(self.care);form.addRow(self.focus_only)
        self.phone_duration=QSpinBox();self.phone_duration.setRange(3,60);self.phone_duration.setSuffix(' 秒');self.phone_duration.setValue(self.settings.phone_seconds)
        self.care_duration=QSpinBox();self.care_duration.setRange(2,30);self.care_duration.setSuffix(' 秒');self.care_duration.setValue(self.settings.care_seconds)
        self.cooldown=QSpinBox();self.cooldown.setRange(30,600);self.cooldown.setSuffix(' 秒');self.cooldown.setValue(self.settings.cooldown_seconds)
        self.brow=QDoubleSpinBox();self.brow.setRange(.15,.95);self.brow.setSingleStep(.05);self.brow.setDecimals(2);self.brow.setValue(self.settings.brow_threshold)
        self.brow.setToolTip('分数越高，触发越谨慎。可先校准自然表情，再按自己的情况调整。')
        form.addRow('手机持续',self.phone_duration);form.addRow('眉部持续',self.care_duration)
        form.addRow('提醒间隔',self.cooldown);form.addRow('眉部阈值',self.brow)
        side.addWidget(group)
        self.calibrate=QPushButton('校准自然表情 · 3 秒');self.calibrate.clicked.connect(self.begin_calibration);self.calibrate.setEnabled(False)
        side.addWidget(self.calibrate)
        self.baseline_label=QLabel();self.baseline_label.setWordWrap(True);self.baseline_label.setObjectName('muted');side.addWidget(self.baseline_label)
        self.update_baseline_label()
        self.snooze=QPushButton('暂停提醒 10 分钟');self.snooze.clicked.connect(self.toggle_snooze);side.addWidget(self.snooze)
        hint=QLabel('检测到手机仅表示画面里有手机。\n手机靠近手部并持续出现时，才考虑提醒。\n\n眉部变化只用于温和关怀。多人入镜时暂停自动提醒。')
        hint.setWordWrap(True);hint.setObjectName('muted');side.addWidget(hint);side.addStretch()
        columns.addLayout(side);outer.addLayout(columns,1)
        self.notice=QLabel('等待开启。你可以随时关闭摄像头或暂停提醒。');self.notice.setWordWrap(True)
        self.notice.setStyleSheet('background:#FFF2CD;border-radius:8px;padding:10px;color:#71501D;')
        outer.addWidget(self.notice)
        for control in (self.phone,self.care,self.focus_only):control.toggled.connect(self.save_settings)
        for control in (self.phone_duration,self.care_duration,self.cooldown,self.brow):control.valueChanged.connect(self.save_settings)
        controller.state_changed.connect(self.on_state)
        controller.devices_changed.connect(self.on_devices)
        controller.frame_ready.connect(self.on_frame)

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
            self.policy.reset_evidence();self.calibration=None
        if state in {'off','error'}:self.notice.setText(text)
        elif state=='running':self.notice.setText('视频测试中：仅显示识别结果，不自动提醒。' if self._video_mode else '已开启本地识别，等待稳定的观察结果。')

    def save_settings(self,*args):
        s=self.settings
        s.phone_enabled=self.phone.isChecked();s.care_enabled=self.care.isChecked();s.focus_only=self.focus_only.isChecked()
        s.phone_seconds=self.phone_duration.value();s.care_seconds=self.care_duration.value()
        s.cooldown_seconds=self.cooldown.value();s.brow_threshold=self.brow.value()
        self.policy.reset_evidence();self.settings_changed.emit(s.as_dict())

    def set_mirror(self,checked):self.preview.mirrored=checked;self.preview.update()

    def update_baseline_label(self):
        value=self.settings.baseline
        self.baseline_label.setText('尚未校准；使用默认阈值。' if value is None else f'自然眉部基线：{value:.2f}')

    def begin_calibration(self):
        if self.controller.state!='running' or self._video_mode:return
        self.calibration=BrowCalibration();self.policy.reset_evidence()
        self.notice.setText('请独自正对摄像头，保持自然表情约 3 秒。')

    def toggle_snooze(self):
        self._snooze_until=0. if time.monotonic()<self._snooze_until else time.monotonic()+600
        self.policy.reset_evidence()
        paused=time.monotonic()<self._snooze_until
        self.snooze.setText('恢复提醒' if paused else '暂停提醒 10 分钟')
        self.notice.setText('提醒已暂停 10 分钟，预览继续。' if paused else '提醒已恢复。')

    def on_frame(self,item):
        if self.controller.state!='running':return
        self.preview.set_frame(item);o=item['observation']
        phone_text='疑似手机靠近手部' if o.phone_near_hand else '画面中有手机' if o.phones else '未检测到手机'
        self.details.setText(f'{phone_text} · 手部 {len(o.hands)} · 面部 {len(o.faces)}\n眉部变化 {o.brow_score:.2f} · 推理 {o.inference_ms:.0f} ms')
        if self.calibration is not None:
            value=self.calibration.add(o)
            if value is not None:
                self.settings.baseline=value;self.calibration=None
                self.settings_changed.emit(self.settings.as_dict());self.update_baseline_label()
                self.notice.setText('自然表情校准完成。可按实际体验调整眉部阈值。')
            elif not o.faces:self.notice.setText('校准中：请让面部进入画面。')
            elif len(o.faces)>1:self.notice.setText('校准中：请保持只有一人入镜。')
            return
        paused=time.monotonic()<self._snooze_until
        if not paused:self.snooze.setText('暂停提醒 10 分钟')
        focus_active,visible=self.context()
        event=self.policy.update(o,focus_active=focus_active,pet_visible=visible,snoozed=paused or self._video_mode)
        if event:
            self._last_notice_at=o.timestamp
            self.notice.setText('刚刚提醒：'+event.text.replace('\n',' '));self.feedback_requested.emit(event)
        elif o.timestamp-self._last_notice_at>8:
            if self._video_mode:message='视频测试中：仅显示识别结果，不自动提醒。'
            elif paused:message='提醒已暂停，预览继续。'
            elif not visible:message='桌宠已隐藏，自动提醒暂停。'
            elif self.settings.focus_only and not focus_active:message='预览中。开始专注计时后，才会触发自动提醒。'
            elif len(o.faces)>1:message='多人入镜，自动提醒暂停。'
            elif not o.faces:message='等待面部进入画面。'
            elif self.policy.phone_duration>0:message=f'手机靠近手部：{self.policy.phone_duration:.0f} / {self.settings.phone_seconds} 秒'
            elif self.policy.care_duration>0:message=f'眉部变化：{self.policy.care_duration:.0f} / {self.settings.care_seconds} 秒'
            else:message='正在安静陪伴，提醒之间会保留冷却时间。'
            self.notice.setText(message)

    def closeEvent(self,event):
        self.controller.stop();self.preview.clear();self.calibration=None
        self.hide();event.ignore()
