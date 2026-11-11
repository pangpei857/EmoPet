"""Learning rounds and reminder responses, without attention scores."""
from datetime import date,timedelta

from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtWidgets import (QAbstractItemView,QComboBox,QHBoxLayout,QHeaderView,QLabel,QMenu,
    QPlainTextEdit,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget)

from .history import KIND_LABELS,RESPONSE_LABELS,STATE_LABELS,display_time,local_day


def duration_text(seconds):
    seconds=max(0,int(seconds));minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return f'{hours}时 {minutes}分 {seconds}秒' if hours else f'{minutes}分 {seconds}秒'


class HistoryPanel(QWidget):
    response_requested=Signal(str,str)
    sample_requested=Signal(str)

    def __init__(self,history,before_refresh=None,can_control=None):
        super().__init__();self.history=history
        self.before_refresh=before_refresh or (lambda:None)
        self.can_control=can_control or (lambda event:True)
        self._sessions=[];self._reminders=[]
        self.setWindowTitle('雨衣皮卡丘 · 学习记录');self.setObjectName('panel')
        self.resize(1000,700);self.setMinimumSize(680,480)
        outer=QVBoxLayout(self);outer.setContentsMargins(24,22,24,20);outer.setSpacing(12)
        header=QHBoxLayout();title=QLabel('学习记录');title.setObjectName('title');header.addWidget(title);header.addStretch()
        self.period=QComboBox()
        for label,key in [('今天','today'),('近 7 天','week'),('全部记录','all')]:self.period.addItem(label,key)
        self.period.currentIndexChanged.connect(self.refresh_data);header.addWidget(self.period)
        self.refresh_button=QPushButton('刷新');self.refresh_button.clicked.connect(self.refresh_data);header.addWidget(self.refresh_button)
        self.example_button=QPushButton('发送示例提醒');menu=QMenu(self)
        menu.addAction('示例：手机提醒',lambda:self.sample_requested.emit('phone'))
        menu.addAction('示例：眉部关怀',lambda:self.sample_requested.emit('care'))
        self.example_button.setMenu(menu);header.addWidget(self.example_button);outer.addLayout(header)
        cards=QHBoxLayout();self.time_card=QLabel();self.round_card=QLabel();self.reminder_card=QLabel()
        for card in (self.time_card,self.round_card,self.reminder_card):
            card.setStyleSheet('background:#FFF2CD;color:#71501D;border-radius:10px;padding:14px;font-size:16px;')
            card.setWordWrap(True);cards.addWidget(card,1)
        outer.addLayout(cards)
        self.tabs=QTabWidget();outer.addWidget(self.tabs,1)
        sessions_page=QWidget();sessions_layout=QVBoxLayout(sessions_page)
        self.sessions_table=self.table(['开始时间','任务','类型','计划时长','实际投入','状态','真实提醒'])
        self.sessions_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch)
        self.sessions_table.itemSelectionChanged.connect(self.select_session)
        sessions_layout.addWidget(self.sessions_table,3)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMinimumHeight(120)
        self.details.setPlaceholderText('选择一轮学习，查看用时和相关提醒。')
        sessions_layout.addWidget(self.details,1);self.tabs.addTab(sessions_page,'每轮学习')
        reminders_page=QWidget();reminders_layout=QVBoxLayout(reminders_page)
        self.reminders_table=self.table(['提醒时间','类型','来源','所属任务','你的回应'])
        self.reminders_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.ResizeMode.Stretch)
        self.reminders_table.itemSelectionChanged.connect(self.select_reminder);reminders_layout.addWidget(self.reminders_table,1)
        self.reminder_detail=QLabel('选择一条提醒，可以补充反馈。');self.reminder_detail.setWordWrap(True)
        self.reminder_detail.setTextFormat(Qt.TextFormat.PlainText);reminders_layout.addWidget(self.reminder_detail)
        responses=QHBoxLayout();self.response_buttons={}
        for key,text in RESPONSE_LABELS.items():
            button=QPushButton(text);button.setEnabled(False)
            button.clicked.connect(lambda checked=False,k=key:self.respond_selected(k))
            responses.addWidget(button);self.response_buttons[key]=button
        reminders_layout.addLayout(responses);self.tabs.addTab(reminders_page,'提醒与反馈')
        self.note=QLabel('示例提醒不计入真实提醒数量；提醒次数不代表不专注次数。')
        self.note.setObjectName('muted');self.note.setWordWrap(True);outer.addWidget(self.note)
        self.message=QLabel('');self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);outer.addWidget(self.message)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh_data);self.timer.setInterval(5000)

    @staticmethod
    def table(headers):
        table=QTableWidget(0,len(headers));table.setHorizontalHeaderLabels(headers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setAlternatingRowColors(True);table.verticalHeader().hide();table.verticalHeader().setDefaultSectionSize(36)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        return table

    def range(self):
        today=date.fromisoformat(local_day(self.history.clock()))
        key=self.period.currentData()
        return (None,None) if key=='all' else ((today-timedelta(days=6)).isoformat() if key=='week' else today.isoformat(),today.isoformat())

    @staticmethod
    def selected(table,rows):
        index=table.currentRow()
        return rows[index] if 0<=index<len(rows) else None

    @staticmethod
    def fill(table,rows,values,selected_id=None):
        table.blockSignals(True);table.setRowCount(len(rows));selection=-1
        for row,record in enumerate(rows):
            for column,text in enumerate(values(record)):
                item=QTableWidgetItem(str(text));item.setToolTip(str(text));table.setItem(row,column,item)
            if record['id']==selected_id:selection=row
        if rows:table.selectRow(selection if selection>=0 else 0)
        table.blockSignals(False)

    def refresh_data(self,*args):
        self.before_refresh()
        selected=self.selected(self.sessions_table,self._sessions);selected_event=self.selected(self.reminders_table,self._reminders)
        start,end=self.range();summary=self.history.summary(start,end)
        self.time_card.setText('学习投入\n'+duration_text(summary['seconds']))
        self.round_card.setText(f"完成学习\n{summary['completed']} 轮")
        self.reminder_card.setText(f"真实提醒 {summary['reminders']} 次\n已标误报 {summary['corrections']} 次")
        self._sessions=self.history.sessions(start,end)
        self.fill(self.sessions_table,self._sessions,lambda s:[display_time(s['started_at']),s['task'],
            '学习' if s['kind']=='focus' else '休息',duration_text(s['planned_seconds']),duration_text(s['elapsed']),
            STATE_LABELS.get(s['status'],s['status']),f"{s['reminder_count']} 次 · 误报 {s['correction_count']}"],selected['id'] if selected else None)
        self._reminders=self.history.reminders(start,end)
        self.fill(self.reminders_table,self._reminders,lambda r:[display_time(r['created_at']),KIND_LABELS[r['kind']],
            '示例' if r['source']=='example' else '视觉识别',r['task'] or ('示例体验' if r['source']=='example' else '未关联学习轮次'),
            RESPONSE_LABELS.get(r['response'],'尚未回应')],selected_event['id'] if selected_event else None)
        self.select_session();self.select_reminder()
        legacy='旧版当日汇总已保留；旧版轮次没有详细记录。' if summary['legacy_seconds'] or summary['legacy_completed'] else ''
        self.note.setText('示例不计入真实提醒；提醒次数不代表不专注次数。列表显示最近500轮、1000条提醒，汇总包含所选范围全部记录。'+legacy)
        if self.history.error:self.message.setText(self.history.error)

    def select_session(self):
        s=self.selected(self.sessions_table,self._sessions)
        if not s:self.details.setPlainText('这个范围内还没有学习记录。开始一轮专注后，会自动保存。');return
        lines=[s['task'],f"开始：{display_time(s['started_at'])}    结束：{display_time(s['ended_at'])}",
            f"实际投入：{duration_text(s['elapsed'])}    暂停：{s['pause_count']} 次    状态：{STATE_LABELS.get(s['status'],s['status'])}"]
        events=self.history.reminders(session_id=s['id'])
        if not events:lines.append('本轮没有视觉提醒记录。')
        for event in reversed(events):
            lines.append(f"{display_time(event['created_at'])}  {KIND_LABELS[event['kind']]} · {RESPONSE_LABELS.get(event['response'],'尚未回应')}")
        if s['status']=='interrupted':lines.append('上次运行意外中断，用时保留到最后一次自动保存。')
        self.details.setPlainText('\n'.join(lines))

    def select_reminder(self):
        event=self.selected(self.reminders_table,self._reminders)
        for key,button in self.response_buttons.items():
            button.setEnabled(bool(event and event['response'] is None and
                (key=='false_positive' or (self.can_control(event) and (key!='research' or event['kind']=='phone')))))
        if event:
            prefix='示例体验，回应不会改变真实提醒设置。\n' if event['source']=='example' else ''
            self.reminder_detail.setText(prefix+event['text']+'\n'+RESPONSE_LABELS.get(event['response'],'尚未回应'))
        else:self.reminder_detail.setText('这个范围内还没有提醒。可以发送示例提醒体验。')

    def respond_selected(self,response):
        event=self.selected(self.reminders_table,self._reminders)
        if event:self.response_requested.emit(event['id'],response)

    def reveal_reminder(self,event_id):
        self.period.setCurrentIndex(0);self.refresh_data();self.tabs.setCurrentIndex(1)
        for index,event in enumerate(self._reminders):
            if event['id']==event_id:self.reminders_table.selectRow(index);break

    def showEvent(self,event):self.refresh_data();self.timer.start()
    def hideEvent(self,event):self.timer.stop()
    def closeEvent(self,event):self.hide();event.ignore()
