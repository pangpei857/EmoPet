"""Learning rounds and reminder responses, without attention scores."""
from datetime import date,timedelta

from PySide6.QtCore import Qt,QTimer,Signal,QDate
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QComboBox,QDateEdit,QGridLayout,QHBoxLayout,QHeaderView,QLabel,QMenu,
    QPlainTextEdit,QPushButton,QTableWidget,QTableWidgetItem,QTabWidget,QVBoxLayout,QWidget)

from .history import BEHAVIOR_LABELS,KIND_LABELS,RESPONSE_LABELS,STATE_LABELS,display_time,local_day,response_allowed


def duration_text(seconds):
    seconds=max(0,int(seconds));minutes,seconds=divmod(seconds,60);hours,minutes=divmod(minutes,60)
    return f'{hours}时 {minutes}分 {seconds}秒' if hours else f'{minutes}分 {seconds}秒'


class HistoryPanel(QWidget):
    response_requested=Signal(str,str)
    sample_requested=Signal(str)

    def __init__(self,history,before_refresh=None,can_control=None,*,store=None,summary_service=None):
        super().__init__();self.history=history
        self.summary_service=summary_service
        if self.summary_service is None and store is not None:
            from .summary_service import SummaryService
            self.summary_service=SummaryService(store,self)
        self._summary_target=None;self._behaviors=[]
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
        responses=QGridLayout();self.response_layout=responses;self.response_buttons={}
        for key,text in RESPONSE_LABELS.items():
            button=QPushButton(text);button.setEnabled(False)
            button.clicked.connect(lambda checked=False,k=key:self.respond_selected(k))
            index=len(self.response_buttons);responses.addWidget(button,index//4,index%4);self.response_buttons[key]=button
        reminders_layout.addLayout(responses);self.tabs.addTab(reminders_page,'提醒与反馈')
        self._build_summaries();self._build_behaviors()
        self.note=QLabel('示例提醒不计入真实提醒数量；提醒次数不代表不专注次数。')
        self.note.setObjectName('muted');self.note.setWordWrap(True);outer.addWidget(self.note)
        self.message=QLabel('');self.message.setWordWrap(True);self.message.setTextFormat(Qt.TextFormat.PlainText);outer.addWidget(self.message)
        self.timer=QTimer(self);self.timer.timeout.connect(self.refresh_data);self.timer.setInterval(5000)
        if self.summary_service is not None:
            self.summary_service.updated.connect(lambda *_:self.refresh_summary())
            self.summary_service.status_changed.connect(self.message.setText)

    def _build_summaries(self):
        page=QWidget();layout=QVBoxLayout(page)
        row=QHBoxLayout();self.summary_scope=QComboBox();self.summary_scope.addItem('选中学习轮次','session');self.summary_scope.addItem('指定日期汇总','day')
        row.addWidget(self.summary_scope)
        self.summary_date=QDateEdit();self.summary_date.setCalendarPopup(True);self.summary_date.setDisplayFormat('yyyy-MM-dd')
        self.summary_date.setDate(QDate.fromString(local_day(self.history.clock()),'yyyy-MM-dd'));row.addWidget(self.summary_date)
        self.summary_local=QPushButton('更新本地小结');self.summary_local.clicked.connect(self.refresh_summary);row.addWidget(self.summary_local)
        self.summary_ai=QPushButton('生成 DeepSeek 复盘');self.summary_ai.clicked.connect(self.generate_ai_summary);row.addWidget(self.summary_ai)
        layout.addLayout(row)
        self.ai_consent=QCheckBox('本次允许发送所选任务、统计和相关文字给 DeepSeek')
        self.ai_consent.setToolTip('点击生成后才发送当前范围的任务、统计、你的补充及相关完整问答；不发送画面。可先在“相关问答与依据”查看。')
        self.ai_consent.setChecked(False);self.ai_consent.toggled.connect(self.update_summary_buttons);layout.addWidget(self.ai_consent)
        self.summary_views=QTabWidget();self.summary_text=QPlainTextEdit();self.summary_text.setReadOnly(True)
        self.summary_sources=QPlainTextEdit();self.summary_sources.setReadOnly(True)
        self.summary_views.addTab(self.summary_text,'学习复盘');self.summary_views.addTab(self.summary_sources,'相关问答与依据')
        layout.addWidget(self.summary_views,1)
        self.self_note=QPlainTextEdit();self.self_note.setMaximumHeight(70)
        self.self_note.setPlaceholderText('可选：这轮／这一天完成了什么？还有哪里没弄懂？');layout.addWidget(self.self_note)
        self.save_note_button=QPushButton('保存我的补充');self.save_note_button.clicked.connect(self.save_summary_note);layout.addWidget(self.save_note_button)
        self.summary_scope.currentIndexChanged.connect(self.refresh_summary)
        self.summary_date.dateChanged.connect(self.refresh_summary)
        self.tabs.addTab(page,'学习小结')

    def _build_behaviors(self):
        page=QWidget();layout=QVBoxLayout(page)
        hint=QLabel('显示选中学习轮次的观测片段。行为记录独立于提醒；未知不算离位，手机用途由你确认。')
        hint.setWordWrap(True);layout.addWidget(hint)
        self.behavior_table=self.table(['开始','结束','行为','有效时长','状态','你的标记'])
        self.behavior_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.ResizeMode.Stretch)
        self.behavior_table.itemSelectionChanged.connect(self.select_behavior);layout.addWidget(self.behavior_table,1)
        row=QHBoxLayout();self.behavior_buttons={}
        for key,label in [('false_positive','标记误报'),('research','用于查资料'),('thinking','正在思考'),('paper','看书写字'),(None,'恢复未确认')]:
            button=QPushButton(label);button.clicked.connect(lambda checked=False,k=key:self.correct_selected_behavior(k))
            row.addWidget(button);self.behavior_buttons[key]=button
        layout.addLayout(row);self.tabs.addTab(page,'行为时间线')

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
        self.fill(self.reminders_table,self._reminders,lambda r:[display_time(r['created_at']),KIND_LABELS.get(r['kind'],r['kind']),
            {'example':'示例','coach':'学习计时'}.get(r['source'],'视觉识别'),r['task'] or ('示例体验' if r['source']=='example' else '未关联学习轮次'),
            RESPONSE_LABELS.get(r['response'],'尚未回应')],selected_event['id'] if selected_event else None)
        self.select_session();self.select_reminder()
        legacy='旧版当日汇总已保留；旧版轮次没有详细记录。' if summary['legacy_seconds'] or summary['legacy_completed'] else ''
        self.note.setText('示例不计入真实提醒；提醒次数不代表不专注次数。列表显示最近500轮、1000条提醒，汇总包含所选范围全部记录。'+legacy)
        if self.history.error:self.message.setText(self.history.error)

    def select_session(self):
        s=self.selected(self.sessions_table,self._sessions)
        if not s:
            self.details.setPlainText('这个范围内还没有学习记录。开始一轮专注后，会自动保存。')
            self.refresh_summary();self.refresh_behaviors();return
        lines=[s['task'],f"开始：{display_time(s['started_at'])}    结束：{display_time(s['ended_at'])}",
            f"实际投入：{duration_text(s['elapsed'])}    暂停：{s['pause_count']} 次    状态：{STATE_LABELS.get(s['status'],s['status'])}"]
        events=self.history.reminders(session_id=s['id'])
        if not events:lines.append('本轮没有视觉提醒记录。')
        for event in reversed(events):
            lines.append(f"{display_time(event['created_at'])}  {KIND_LABELS[event['kind']]} · {RESPONSE_LABELS.get(event['response'],'尚未回应')}")
        if s['status']=='interrupted':lines.append('上次运行意外中断，用时保留到最后一次自动保存。')
        self.details.setPlainText('\n'.join(lines))
        self.refresh_summary();self.refresh_behaviors()

    def select_reminder(self):
        event=self.selected(self.reminders_table,self._reminders)
        visible_index=0
        for key,button in self.response_buttons.items():
            allowed=bool(event and response_allowed(event['kind'],key))
            button.setVisible(allowed)
            self.response_layout.removeWidget(button)
            if allowed:
                self.response_layout.addWidget(button,visible_index//4,visible_index%4);visible_index+=1
            button.setEnabled(bool(event and event['response'] is None and
                allowed and (key=='false_positive' or self.can_control(event))))
        if event:
            prefix='示例体验，回应不会改变真实提醒设置。\n' if event['source']=='example' else ''
            self.reminder_detail.setText(prefix+event['text']+'\n'+RESPONSE_LABELS.get(event['response'],'尚未回应'))
        else:self.reminder_detail.setText('这个范围内还没有提醒。可以发送示例提醒体验。')

    def respond_selected(self,response):
        event=self.selected(self.reminders_table,self._reminders)
        if event:self.response_requested.emit(event['id'],response)

    def summary_selection(self):
        scope=self.summary_scope.currentData()
        if scope=='day':return scope,self.summary_date.date().toString('yyyy-MM-dd')
        session=self.selected(self.sessions_table,self._sessions)
        return scope,session['id'] if session and session['kind']=='focus' else None

    def update_summary_buttons(self,*args):
        _,target=self.summary_selection()
        available=self.summary_service is not None and target is not None
        self.summary_ai.setEnabled(bool(available and self.ai_consent.isChecked() and not self.summary_service.client.busy))
        self.save_note_button.setEnabled(available);self.summary_local.setEnabled(available)

    def refresh_summary(self,*args):
        if not hasattr(self,'summary_text'):return
        scope,target=self.summary_selection();self.summary_date.setEnabled(scope=='day');self.update_summary_buttons()
        if self.summary_service is None:
            self.summary_text.setPlainText('学习小结将在应用的学习记录入口中提供。');return
        if target is None:
            self.summary_text.setPlainText('请在“每轮学习”选择一轮学习，或切换为指定日期汇总。')
            self.summary_sources.clear();return
        record=self.summary_service.ensure(scope,target)
        if not record:return
        if self._summary_target!=(scope,target):
            self.self_note.setPlainText(self.history.note(scope,target));self._summary_target=(scope,target)
            self.ai_consent.setChecked(False)
        lines=[record['local_text']]
        if record['ai_status']=='complete' and record['ai_text']:lines.extend(['',record['ai_text']])
        elif record['ai_status']=='stale':lines.extend(['','记录或反馈已更新，旧的DeepSeek复盘已隐藏，可重新生成。'])
        elif record['ai_status']=='pending':lines.extend(['','DeepSeek正在生成；本地统计版已保存。'])
        elif record['ai_status']=='failed':lines.extend(['','DeepSeek复盘未生成：'+record['ai_error']])
        self.summary_text.setPlainText('\n'.join(lines))
        sources=['关联问答（中断回答仅保留记录，不作为复盘依据）：']
        for index,turn in enumerate(record['facts']['chats'],1):
            state={'complete':'已完整回答','pending':'正在回答','stopped':'回答中断','error':'生成失败'}.get(turn['status'],'未完整回答')
            sources.extend(['',f"问答 {index} · {display_time(turn['created_at'])} · {state}",'你：'+turn['question'],'助手：'+(turn['answer'] or '未完整生成')])
        if not record['facts']['chats']:sources.append('这个范围没有关联对话。')
        sources.extend(['',f"统计依据：{len(record['facts']['source_behavior_ids'])} 个行为片段，具体起止时间见“行为时间线”。",
            '数字来自本地统计；事件不等于情绪或专注程度。'])
        self.summary_sources.setPlainText('\n'.join(sources));self.update_summary_buttons()

    def generate_ai_summary(self):
        scope,target=self.summary_selection()
        if self.summary_service is not None and target:
            self.summary_service.request_ai(scope,target,consent=self.ai_consent.isChecked())
            self.update_summary_buttons()

    def save_summary_note(self):
        scope,target=self.summary_selection()
        if target and self.history.save_note(scope,target,self.self_note.toPlainText()):
            self.refresh_summary();self.message.setText('补充已保存，本地小结已更新。')

    def refresh_behaviors(self):
        if not hasattr(self,'behavior_table'):return
        current=self.selected(self.behavior_table,self._behaviors);session=self.selected(self.sessions_table,self._sessions)
        self._behaviors=self.history.behaviors(session_id=session['id']) if session else []
        self.fill(self.behavior_table,self._behaviors,lambda b:[display_time(b['started_at']),display_time(b['ended_at']),
            BEHAVIOR_LABELS.get(b['kind'],b['kind']),duration_text(b['duration']),
            '进行中' if b['status']=='ongoing' else '已结束',RESPONSE_LABELS.get(b['feedback'],'未确认')],current['id'] if current else None)
        self.select_behavior()

    def select_behavior(self):
        event=self.selected(self.behavior_table,self._behaviors)
        for key,button in self.behavior_buttons.items():
            valid=bool(event and event['kind'] not in {'presence','unknown'})
            if key=='research':valid=bool(event and event['kind']=='phone')
            elif key=='thinking':valid=bool(event and event['kind']=='care')
            elif key=='paper':valid=bool(event and event['kind']=='head_down')
            button.setEnabled(valid)

    def correct_selected_behavior(self,feedback):
        event=self.selected(self.behavior_table,self._behaviors)
        if event and self.history.correct_behavior(event['id'],feedback):
            self.refresh_behaviors();self.refresh_summary();self.message.setText('行为标记已保存，小结统计已更新。')

    def reveal_reminder(self,event_id):
        self.period.setCurrentIndex(0);self.refresh_data();self.tabs.setCurrentIndex(1)
        for index,event in enumerate(self._reminders):
            if event['id']==event_id:self.reminders_table.selectRow(index);break

    def showEvent(self,event):self.refresh_data();self.timer.start()
    def hideEvent(self,event):self.timer.stop()
    def closeEvent(self,event):self.hide();event.ignore()
