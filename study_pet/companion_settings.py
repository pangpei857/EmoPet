"""Controls for local sensing, delivery and explicitly enabled memory."""

from datetime import timezone, timedelta

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout)

from .care_strategy import MODE_LABELS
from .history import KIND_LABELS, RESPONSE_LABELS


class CompanionSettings(QDialog):
    mode_changed = Signal(str)
    audio_changed = Signal(bool)
    reading_changed = Signal(bool)

    def __init__(self, memory, *, mode, audio, reading, learning_mode, parent=None):
        super().__init__(parent)
        self.memory = memory
        self.learning_mode = learning_mode
        self.setWindowTitle('陪伴设置')
        self.resize(470, 420)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        for key, label in MODE_LABELS.items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        form.addRow('陪伴模式', self.mode)
        layout.addLayout(form)
        guide = QLabel('安静陪伴关闭主动关怀。适时关心使用默认间隔。主动支持允许更早询问，但仍尊重勿扰和反馈。')
        guide.setWordWrap(True)
        layout.addWidget(guide)
        self.audio = QCheckBox('学习中使用麦克风检测叹气候选（实验）')
        self.audio.setChecked(audio)
        self.audio.setToolTip('仅在专注计时运行时本地分析。音频不保存、不上传。')
        self.reading = QCheckBox('朗读主动关怀')
        self.reading.setChecked(reading)
        self.audio_status = QLabel('')
        self.audio_status.setWordWrap(True)
        layout.addWidget(self.audio)
        layout.addWidget(self.audio_status)
        layout.addWidget(self.reading)
        self.remember = QCheckBox('在本机记住我的陪伴反馈')
        layout.addWidget(self.remember)
        note = QLabel('助手可根据不同学习轮次中的反馈减少同类打扰。关闭后暂停记录和使用。已有反馈可在此查看或清除。')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.preferences = QLabel('')
        self.preferences.setWordWrap(True)
        layout.addWidget(self.preferences)
        self.records = QPlainTextEdit()
        self.records.setReadOnly(True)
        self.records.setMinimumHeight(100)
        layout.addWidget(self.records, 1)
        actions = QHBoxLayout()
        clear = QPushButton('清除陪伴记忆')
        refresh = QPushButton('刷新')
        close = QPushButton('完成')
        for button in (clear, refresh, close):
            actions.addWidget(button)
        layout.addLayout(actions)
        self.mode.currentIndexChanged.connect(lambda _: self.mode_changed.emit(self.mode.currentData()))
        self.audio.toggled.connect(self.audio_changed)
        self.reading.toggled.connect(self.reading_changed)
        self.remember.toggled.connect(self.set_memory_enabled)
        clear.clicked.connect(self.clear_memory)
        refresh.clicked.connect(self.refresh_memory)
        close.clicked.connect(self.hide)
        self.refresh_memory()

    def set_memory_enabled(self, enabled):
        error = '' if self.memory.set_enabled(enabled) else self.memory.error
        self.refresh_memory()
        if error:
            self.records.setPlainText(error)

    def refresh_memory(self):
        self.remember.blockSignals(True)
        self.remember.setChecked(self.memory.enabled)
        self.remember.blockSignals(False)
        reduced = [KIND_LABELS[kind] for kind, preference in self.memory.preferences(self.learning_mode()).items()
                   if kind in KIND_LABELS and kind!='break_due' and preference.reduce_interruptions]
        self.preferences.setText('当前学习方式已减少：'+'、'.join(reduced) if reduced else '')
        self.preferences.setVisible(bool(reduced))
        zone = timezone(timedelta(hours=8))
        rows = [f'{row.observed_at.astimezone(zone):%m-%d %H:%M}  '
                f'{KIND_LABELS.get(row.kind, row.kind)} · {RESPONSE_LABELS.get(row.response, row.response)}'
                for row in self.memory.recent(limit=30)]
        self.records.setPlainText(self.memory.error or '\n'.join(rows) or '还没有保存陪伴反馈。')

    def clear_memory(self):
        confirm = QMessageBox.question(self, '清除陪伴记忆', '清除用于调整关怀的反馈记忆？学习记录和对话仍会保留。')
        if confirm == QMessageBox.StandardButton.Yes:
            error = '' if self.memory.clear() else self.memory.error
            self.refresh_memory()
            if error:
                self.records.setPlainText(error)
