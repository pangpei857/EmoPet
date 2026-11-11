"""DeepSeek learning chat, local conversation history and editable task plans."""
import html
import json
import re

from PySide6.QtCore import Qt,QTimer,Signal
from PySide6.QtGui import QKeySequence,QShortcut
from PySide6.QtWidgets import (QAbstractItemView,QCheckBox,QComboBox,QFormLayout,QHBoxLayout,QLabel,
    QLineEdit,QListWidget,QListWidgetItem,QPlainTextEdit,QPushButton,QScrollArea,QTableWidget,
    QTableWidgetItem,QTabWidget,QTextBrowser,QVBoxLayout,QWidget,QHeaderView)

from .chat_core import ChatConfig,MAX_INPUT,build_messages,parse_plan,plan_text
from .chat_network import ChatClient
from .chat_store import ChatStore
from .secrets import KeyVault
from .camera_ui import TimeSpinBox


class ChatPanel(QWidget):
    reply_for_pet=Signal(str)
    task_selected=Signal(str,int)

    def __init__(self,store,context=None,can_apply=None):
        super().__init__();self.store=store;self.context=context or (lambda:{})
        self.can_apply=can_apply or (lambda:True)
        self.config=ChatConfig.from_dict(store.get('chat',{}))
        self.vault=KeyVault(store.path.parent);self.chats=ChatStore(store.path.parent)
        self.client=ChatClient(self);self.conversation_id=None;self._turns=[];self._turn_id=None
        self._answer='';self._testing=False;self._purpose='chat';self._plan_id=None;self._plan=None
        self.setObjectName('panel');self.setWindowTitle('雨衣皮卡丘 · 学习对话');self.resize(1040,750);self.setMinimumSize(760,520)
        outer=QVBoxLayout(self);outer.setContentsMargins(22,20,22,18);outer.setSpacing(10)
        header=QHBoxLayout();title=QLabel('和皮卡丘聊聊');title.setObjectName('title');header.addWidget(title);header.addStretch()
        self.model_badge=QLabel('DeepSeek · '+self.config.model);self.model_badge.setTextFormat(Qt.TextFormat.PlainText);header.addWidget(self.model_badge);outer.addLayout(header)
        self.tabs=QTabWidget();outer.addWidget(self.tabs,1)
        self._build_chat();self._build_plan();self._build_config()
        self.status=QLabel('先在“模型配置”填写DeepSeek API Key，再开始对话。')
        self.status.setWordWrap(True);self.status.setTextFormat(Qt.TextFormat.PlainText);outer.addWidget(self.status)
        self.render_timer=QTimer(self);self.render_timer.setSingleShot(True);self.render_timer.timeout.connect(self.render)
        self.save_timer=QTimer(self);self.save_timer.setInterval(1000);self.save_timer.timeout.connect(self.save_partial)
        self.client.chunk.connect(self.on_chunk);self.client.thinking.connect(lambda:self.status.setText('DeepSeek正在思考…'))
        self.client.completed.connect(self.on_complete);self.client.failed.connect(self.on_error);self.client.stopped.connect(self.on_stopped)
        self.refresh_conversations()
        conversations=self.chats.conversations()
        if conversations:self.load_conversation(conversations[0]['id'])
        else:self.render()
        self.update_config_status();self.update_buttons()
        self.context_timer=QTimer(self);self.context_timer.setInterval(1000);self.context_timer.timeout.connect(self.update_context_label)

    def _build_chat(self):
        page=QWidget();layout=QHBoxLayout(page);layout.setContentsMargins(8,10,8,6)
        sidebar=QVBoxLayout();self.new_button=QPushButton('新对话');self.new_button.clicked.connect(self.new_conversation);sidebar.addWidget(self.new_button)
        self.conversations=QListWidget();self.conversations.setMaximumWidth(195);self.conversations.setMinimumWidth(150)
        self.conversations.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.conversations.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.conversations.currentItemChanged.connect(self.select_conversation);sidebar.addWidget(self.conversations,1);layout.addLayout(sidebar)
        main=QVBoxLayout();self.transcript=QTextBrowser();self.transcript.setOpenLinks(False);self.transcript.setOpenExternalLinks(False)
        self.transcript.setMinimumHeight(120);main.addWidget(self.transcript,1)
        self.context_check=QCheckBox('附带当前学习任务和计时状态');self.context_check.setChecked(self.config.include_context)
        self.context_check.toggled.connect(self.save_context_choice);main.addWidget(self.context_check)
        self.context_label=QLabel('');self.context_label.setObjectName('muted');self.context_label.setWordWrap(True);main.addWidget(self.context_label)
        quick=QHBoxLayout();self.quick_buttons=[]
        for title,prompt,purpose in [('拆分当前任务','请把我的学习目标拆成可执行的小步骤。','plan'),
            ('给我一个提示','我在当前学习任务上卡住了，请先给我一个思路提示。','chat'),
            ('我有点累了','我有点学不下去了，请结合当前任务帮我找到一个更轻松的下一步。','chat')]:
            button=QPushButton(title);button.clicked.connect(lambda checked=False,t=prompt,p=purpose:self.prepare_prompt(t,p))
            quick.addWidget(button);self.quick_buttons.append(button)
        main.addLayout(quick)
        self.composer=QPlainTextEdit();self.composer.setPlaceholderText('告诉我你正在学什么，或者贴出卡住的问题。Ctrl+Enter 发送，Enter 换行。')
        self.composer.setMinimumHeight(75);self.composer.setMaximumHeight(115);self.composer.textChanged.connect(self.update_buttons)
        main.addWidget(self.composer)
        send_row=QHBoxLayout();self.purpose=QComboBox();self.purpose.addItem('学习交流','chat');self.purpose.addItem('拆解任务','plan')
        send_row.addWidget(self.purpose);self.counter=QLabel('0 / 6000');self.counter.setObjectName('muted');send_row.addWidget(self.counter);send_row.addStretch()
        self.stop_button=QPushButton('停止生成');self.stop_button.clicked.connect(self.client.stop);send_row.addWidget(self.stop_button)
        self.send_button=QPushButton('发送');self.send_button.setObjectName('primary');self.send_button.clicked.connect(self.send);send_row.addWidget(self.send_button)
        main.addLayout(send_row);layout.addLayout(main,1);self.tabs.addTab(page,'学习对话')
        self.send_shortcut=QShortcut(QKeySequence('Ctrl+Return'),self.composer)
        self.send_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.send_shortcut.activated.connect(self.send)

    def _build_plan(self):
        page=QWidget();layout=QVBoxLayout(page)
        self.plan_summary=QLabel('在聊天中选择“拆解任务”，把学习目标变成可执行的小步骤。')
        self.plan_summary.setWordWrap(True);self.plan_summary.setTextFormat(Qt.TextFormat.PlainText);layout.addWidget(self.plan_summary)
        self.steps=QTableWidget(0,2);self.steps.setHorizontalHeaderLabels(['学习步骤（可修改）','预计分钟'])
        self.steps.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeMode.Stretch)
        self.steps.setColumnWidth(1,130);self.steps.verticalHeader().setDefaultSectionSize(46)
        self.steps.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.steps.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.steps.itemSelectionChanged.connect(self.update_buttons);layout.addWidget(self.steps,1)
        buttons=QHBoxLayout();self.save_steps=QPushButton('保存步骤修改');self.save_steps.clicked.connect(self.save_edited_plan);buttons.addWidget(self.save_steps)
        buttons.addStretch();self.apply_step=QPushButton('放到学习面板');self.apply_step.setObjectName('primary');self.apply_step.clicked.connect(self.apply_selected_step)
        buttons.addWidget(self.apply_step);layout.addLayout(buttons)
        hint=QLabel('选中一步后可放到学习面板。开始计时由你点击；当前一轮未结束时，不覆盖正在学习的任务。')
        hint.setWordWrap(True);hint.setObjectName('muted');layout.addWidget(hint);self.tabs.addTab(page,'学习步骤')

    def _build_config(self):
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        page=QWidget();page.setObjectName('panel');layout=QVBoxLayout(page);layout.setContentsMargins(20,20,20,20);layout.setSpacing(14)
        info=QLabel('DeepSeek文字对话。发送时会将本轮对话及勾选的学习状态交给配置的模型服务；对话历史保存在本机。')
        info.setWordWrap(True);layout.addWidget(info)
        self.config_fields=QWidget();form=QFormLayout(self.config_fields);form.setSpacing(12)
        self.base_edit=QLineEdit(self.config.base_url);self.base_edit.setMinimumHeight(40);self.base_edit.setMaxLength(1000)
        self.model_edit=QComboBox();self.model_edit.setEditable(True);self.model_edit.addItems(['deepseek-flash','deepseek-v4-pro'])
        self.model_edit.setCurrentText(self.config.model);self.model_edit.setMinimumHeight(36)
        self.model_edit.lineEdit().setMaxLength(120)
        self.key_edit=QLineEdit();self.key_edit.setEchoMode(QLineEdit.EchoMode.Password);self.key_edit.setMinimumHeight(40);self.key_edit.setMaxLength(1000)
        self.key_edit.setPlaceholderText('填写你自己的DeepSeek API Key')
        self.show_key=QCheckBox('显示本次输入的密钥');self.show_key.toggled.connect(lambda checked:self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password))
        self.thinking_check=QCheckBox('启用深度思考');self.thinking_check.setChecked(self.config.thinking)
        form.addRow('服务地址',self.base_edit);form.addRow('模型名称',self.model_edit);form.addRow('API Key',self.key_edit)
        form.addRow('',self.show_key);form.addRow('',self.thinking_check);layout.addWidget(self.config_fields)
        self.key_status=QLabel('');self.key_status.setWordWrap(True);layout.addWidget(self.key_status)
        buttons=QHBoxLayout();self.save_config_button=QPushButton('保存配置');self.save_config_button.clicked.connect(self.save_config)
        self.test_button=QPushButton('保存并测试连接');self.test_button.setObjectName('primary');self.test_button.clicked.connect(self.test_connection)
        self.remove_key=QPushButton('移除已保存密钥');self.remove_key.clicked.connect(self.remove_saved_key)
        buttons.addWidget(self.save_config_button);buttons.addWidget(self.test_button);buttons.addWidget(self.remove_key);layout.addLayout(buttons)
        note=QLabel('密钥使用Windows本机加密保存，换电脑后需要重新填写。连接测试只发送一条短消息，不附带学习任务或历史。')
        note.setWordWrap(True);note.setObjectName('muted');layout.addWidget(note)
        link=QLabel('<a href="https://platform.deepseek.com/api_keys">打开DeepSeek控制台获取API Key</a>')
        link.setOpenExternalLinks(True);layout.addWidget(link);layout.addStretch();scroll.setWidget(page);self.tabs.addTab(scroll,'模型配置')
        self.base_edit.textChanged.connect(self.update_config_status)

    def save_context_choice(self,checked):
        self.config.include_context=checked;self.store.save(chat=self.config.as_dict());self.update_context_label()

    def update_context_label(self):
        context=self.context() if self.context_check.isChecked() else {}
        self.context_label.setText(('当前任务：'+str(context.get('task') or '尚未设置')+' · '+str(context.get('state') or '未开始')) if context else '仅发送对话文字。')

    def update_config_status(self,*args):
        try:present=bool(self.vault.load(self.base_edit.text()))
        except ValueError:present=False
        self.key_status.setText(self.vault.error or ('已保存此服务的加密密钥；留空则保留。' if present else '尚未保存此服务的API Key。'))
        self.key_edit.setPlaceholderText('已保存，留空则保留原密钥' if present else '填写你自己的DeepSeek API Key')

    def save_config(self):
        try:
            config=ChatConfig(self.base_edit.text().strip(),self.model_edit.currentText().strip(),self.thinking_check.isChecked(),self.context_check.isChecked())
            config.validate()
            if self.key_edit.text().strip():self.vault.save(self.key_edit.text(),config.base_url)
            self.config=config;self.store.save(chat=config.as_dict());self.key_edit.clear();self.show_key.setChecked(False)
            self.model_badge.setText('DeepSeek · '+config.model);self.update_config_status()
            self.status.setText('模型配置已保存。');return True
        except (OSError,ValueError):
            self.status.setText('配置无法保存，请检查服务地址、模型名称、密钥与本地目录权限。');return False

    def remove_saved_key(self):
        try:self.vault.remove();self.key_edit.clear();self.update_config_status();self.status.setText('已移除本机保存的密钥。')
        except OSError:self.status.setText('无法移除密钥，请检查本地目录权限。')

    def test_connection(self):
        if self.client.busy or not self.save_config():return False
        key=self.vault.load(self.config.base_url)
        if not key:self.status.setText(self.vault.error or '请先填写并保存DeepSeek API Key。');return False
        self._testing=True
        try:self.client.start(self.config,key,[{'role':'user','content':'请只回复：连接成功'}],probe=True)
        except ValueError as error:self._testing=False;self.status.setText(str(error));return False
        self.status.setText('正在测试DeepSeek连接…');self.update_buttons();return True

    def refresh_conversations(self):
        self.conversations.blockSignals(True);self.conversations.clear()
        for conversation in self.chats.conversations():
            item=QListWidgetItem(conversation['title']);item.setToolTip(conversation['title']);item.setData(Qt.ItemDataRole.UserRole,conversation['id']);self.conversations.addItem(item)
            if conversation['id']==self.conversation_id:self.conversations.setCurrentItem(item)
        self.conversations.blockSignals(False)

    def select_conversation(self,item,previous=None):
        if item and not self.client.busy:self.load_conversation(item.data(Qt.ItemDataRole.UserRole))

    def load_conversation(self,identifier):
        self.conversation_id=identifier;self._turns=self.chats.turns(identifier);self._turn_id=None
        latest=self.chats.latest_plan(identifier)
        self.load_plan(*latest) if latest else self.load_plan(None,None)
        self.refresh_conversations();self.render();self.update_buttons()

    def new_conversation(self):
        if self.client.busy:return
        self.conversation_id=None;self._turns=[];self._turn_id=None;self.composer.clear();self.load_plan(None,None)
        self.refresh_conversations();self.render();self.status.setText('新对话准备好了。')

    def prepare_prompt(self,text,purpose):
        if self.client.busy:return
        context=self.context();task=str(context.get('task') or '')
        if purpose=='plan' and task:text='请帮我拆分这个学习目标：'+task
        self.composer.setPlainText(text);self.purpose.setCurrentIndex(1 if purpose=='plan' else 0);self.composer.setFocus()

    def send(self):
        if self.client.busy:return False
        text=self.composer.toPlainText().strip();purpose=self.purpose.currentData()
        try:
            self.config.validate();key=self.vault.load(self.config.base_url)
            if not key:self.tabs.setCurrentIndex(2);self.status.setText(self.vault.error or '请在这里填写并保存DeepSeek API Key。');return False
            messages=build_messages(self._turns,text,self.context() if self.context_check.isChecked() else None,purpose)
        except ValueError as error:self.status.setText(str(error));return False
        if not self.conversation_id:self.conversation_id=self.chats.new_conversation(text)
        if not self.conversation_id:self.status.setText(self.chats.error);return False
        identifier=self.chats.start_turn(self.conversation_id,text,purpose,self.config.model)
        if not identifier:self.status.setText(self.chats.error);return False
        self._turn_id=identifier;self._answer='';self._purpose=purpose;self._testing=False
        self._turns=self.chats.turns(self.conversation_id)
        try:self.client.start(self.config,key,messages,purpose)
        except ValueError as error:self.on_error(str(error));return False
        self.composer.clear();self.save_timer.start();self.status.setText('正在整理学习步骤…' if purpose=='plan' else 'DeepSeek正在回答…')
        self.refresh_conversations();self.render();self.update_buttons();return True

    def update_buttons(self):
        if not hasattr(self,'send_button'):return
        busy=self.client.busy;length=len(self.composer.toPlainText().strip())
        self.counter.setText(f'{length} / {MAX_INPUT}');self.send_button.setEnabled(not busy and 0<length<=MAX_INPUT)
        self.stop_button.setEnabled(busy);self.new_button.setEnabled(not busy);self.conversations.setEnabled(not busy)
        self.composer.setReadOnly(busy);self.purpose.setEnabled(not busy)
        for button in self.quick_buttons:button.setEnabled(not busy)
        if hasattr(self,'config_fields'):
            for widget in (self.config_fields,self.save_config_button,self.test_button,self.remove_key):widget.setEnabled(not busy)
        if hasattr(self,'save_steps'):
            self.save_steps.setEnabled(not busy and bool(self._plan_id))
            self.apply_step.setEnabled(not busy and bool(self._plan_id) and self.steps.currentRow()>=0)
        self.update_context_label()

    def on_chunk(self,part):
        if self._testing:return
        self._answer+=part
        if not self.render_timer.isActive():self.render_timer.start(70)

    def save_partial(self):
        if self._turn_id:self.chats.update_turn(self._turn_id,self._answer,'pending')

    def finish_turn(self,status,answer,error=''):
        self.save_timer.stop();self.render_timer.stop()
        if self._turn_id:self.chats.update_turn(self._turn_id,answer,status,error)
        self._answer=answer;self._turn_id=None
        if self.conversation_id:self._turns=self.chats.turns(self.conversation_id)
        self.render();self.refresh_conversations();self.update_buttons()

    def on_complete(self,answer,reason):
        if self._testing:
            self._testing=False;self.status.setText('DeepSeek连接成功，可以开始聊天了。');self.update_buttons();return
        if self._purpose=='plan':
            try:plan=parse_plan(answer)
            except ValueError as error:self.on_error(str(error));return
            if not self.chats.save_plan(self._turn_id,plan):self.on_error(self.chats.error);return
            identifier=self._turn_id;self.finish_turn('complete',answer);self.load_plan(identifier,plan);self.tabs.setCurrentIndex(1)
            self.reply_for_pet.emit(f'已整理好{len(plan["steps"])}个学习步骤，\n可以先从一个小目标开始。')
            self.status.setText('步骤已保存，可以修改后选择一项放到学习面板。')
        else:
            self.finish_turn('complete',answer)
            brief=re.sub(r'^[\s#*\-\d.]+','',answer.strip()).split('\n')[0][:85]
            self.reply_for_pet.emit(brief or '我把建议写在聊天面板里啦。')
            self.status.setText('回答已达到本次长度上限，可以继续追问。' if reason=='length' else '回答已保存。')

    def on_error(self,message):
        if self._testing:self._testing=False;self.update_buttons()
        else:self.finish_turn('error',self._answer,message)
        self.status.setText(message)

    def on_stopped(self,answer):
        if self._testing:self._testing=False;self.update_buttons()
        else:self.finish_turn('stopped',answer)
        self.status.setText('已停止生成，收到的文字已保留。')

    def render(self):
        scroll=self.transcript.verticalScrollBar();previous_scroll=scroll.value();near_bottom=previous_scroll>=scroll.maximum()-30
        pieces=[]
        for turn in self._turns:
            answer=self._answer if turn['id']==self._turn_id else turn['answer'];state='pending' if turn['id']==self._turn_id else turn['status']
            if turn['purpose']=='plan':
                if state=='complete':
                    try:answer=plan_text(parse_plan(answer))
                    except ValueError:answer='已保存的步骤无法解析。'
                else:answer='正在整理可执行的学习步骤…' if state=='pending' else '步骤未完整生成。'
            if not answer:answer='正在等待回答…' if state=='pending' else '没有收到回答。'
            if state=='stopped':answer+='\n［已停止］'
            elif state=='error':answer+='\n［'+turn.get('error','生成失败')+'］'
            for role,text,color in [('你',turn['user_text'],'#F9EDC9'),('皮卡丘',answer,'#EEF3EC')]:
                escaped=html.escape(text).replace('\n','<br>')
                pieces.append(f'<p style="color:#79591E;font-weight:600">{role}</p><table width="100%" bgcolor="{color}" cellpadding="10"><tr><td>{escaped}</td></tr></table><br>')
        if not pieces:pieces=['<p style="color:#71501D;font-size:17px">今天想一起完成什么？</p><p>可以聊学习问题、拆分目标，或告诉我你卡在哪一步。<br>先到“模型配置”填写你自己的DeepSeek API Key。</p>']
        self.transcript.setHtml(''.join(pieces))
        if near_bottom:scroll.setValue(scroll.maximum())
        else:scroll.setValue(previous_scroll)

    def load_plan(self,identifier,plan):
        self._plan_id=identifier;self._plan=plan;self.steps.setRowCount(0)
        if not plan:self.plan_summary.setText('在聊天中选择“拆解任务”，把学习目标变成可执行的小步骤。');return
        self.plan_summary.setText(plan['summary']);self.steps.setRowCount(len(plan['steps']))
        for index,step in enumerate(plan['steps']):
            self.steps.setItem(index,0,QTableWidgetItem(step['title']))
            spin=TimeSpinBox();spin.setRange(1,120);spin.setValue(step['minutes']);spin.setMinimumHeight(38)
            spin.setStyleSheet('QSpinBox{padding:0;border:1px solid #DCE4DD;background:white;} QSpinBox QLineEdit{padding:0;border:0;}')
            self.steps.setCellWidget(index,1,spin)
        self.steps.selectRow(0);self.update_buttons()

    def edited_plan(self):
        steps=[]
        for row in range(self.steps.rowCount()):
            item=self.steps.item(row,0);steps.append({'title':item.text().strip() if item else '',
                'minutes':self.steps.cellWidget(row,1).value()})
        return parse_plan(json.dumps({'summary':self._plan['summary'],'steps':steps},ensure_ascii=False))

    def save_edited_plan(self):
        if not self._plan_id:return False
        try:plan=self.edited_plan()
        except ValueError as error:self.status.setText(str(error));return False
        if not self.chats.save_plan(self._plan_id,plan):self.status.setText(self.chats.error);return False
        self._plan=plan;self.status.setText('步骤修改已保存。');return True

    def apply_selected_step(self):
        if not self.can_apply():self.status.setText('请先完成或结束当前一轮，再选择下一项学习任务。');return
        row=self.steps.currentRow()
        if row<0 or not self.save_edited_plan():return
        step=self._plan['steps'][row];self.task_selected.emit(step['title'],step['minutes'])
        self.update_context_label()
        self.status.setText('已放到学习面板，准备好后点击“开始专注”。')

    def shutdown(self):
        self.client.stop();self.save_timer.stop();self.render_timer.stop()
        if self._turn_id:self.finish_turn('stopped',self._answer)

    def showEvent(self,event):
        self.update_context_label();self.update_config_status();self.context_timer.start()
    def hideEvent(self,event):self.context_timer.stop()
    def closeEvent(self,event):self.shutdown();self.hide();event.ignore()
