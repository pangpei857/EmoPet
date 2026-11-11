import json
import os
from pathlib import Path
import tempfile
import unittest

from PySide6.QtCore import QEvent,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from study_pet.chat_core import ChatConfig,CompletionParser,build_messages,chat_endpoint,parse_plan
from study_pet.chat_fixture import local_model,PLAN,ANSWER
from study_pet.chat_network import ChatClient
from study_pet.chat_store import ChatStore
from study_pet.chat_ui import ChatPanel
from study_pet.secrets import KeyVault
from study_pet.storage import Store
from study_pet.ui import STYLE,Companion

APP=QApplication.instance() or QApplication([]);APP.setQuitOnLastWindowClosed(False);APP.setStyleSheet(STYLE)

def wait_until(predicate,milliseconds=8000):
    elapsed=0
    while not predicate() and elapsed<milliseconds:QTest.qWait(20);elapsed+=20
    if not predicate():raise AssertionError('Timed out waiting for chat state')


class ChatCoreTests(unittest.TestCase):
    def test_endpoint_normalizes_bases_and_rejects_embedded_credentials(self):
        self.assertEqual(chat_endpoint('https://api.deepseek.com/'),'https://api.deepseek.com/chat/completions')
        self.assertEqual(chat_endpoint('https://api.deepseek.com/v1/chat/completions'),'https://api.deepseek.com/v1/chat/completions')
        for value in ('file:///tmp/a','https://key@example.com','https://example.com?key=x'):
            with self.assertRaises(ValueError):chat_endpoint(value)

    def test_sse_handles_fragmented_utf8_and_discards_reasoning(self):
        parser=CompletionParser()
        events=[{'choices':[{'delta':{'reasoning_content':'PRIVATE_TEST_REASONING'}}]},
            {'choices':[{'delta':{'content':'你好，皮卡丘。'},'finish_reason':'stop'}]}]
        payload=''.join('data: '+json.dumps(e,ensure_ascii=False)+'\r\n\r\n' for e in events).encode()+b'data: [DONE]\n\n'
        received=''.join(parser.feed(bytes([byte])) for byte in payload)
        self.assertEqual(received,'你好，皮卡丘。');self.assertTrue(parser.done);self.assertTrue(parser.reasoning)
        self.assertNotIn('PRIVATE',parser.answer)

    def test_context_is_bounded_and_failed_turns_are_not_sent(self):
        turns=[{'status':'complete','user_text':'问题','answer':'回答'},{'status':'error','user_text':'失败问题','answer':'残缺'}]
        messages=build_messages(turns,'下一步',{'task':'读第三章','state':'进行中','raw_image':'never send'})
        self.assertNotIn('never send',str(messages));self.assertNotIn('失败问题',str(messages))
        self.assertIn('读第三章',messages[0]['content'])
        with self.assertRaises(ValueError):build_messages([],'x'*6001)

    def test_plan_validates_actions_and_minute_ranges(self):
        self.assertEqual(parse_plan(json.dumps(PLAN,ensure_ascii=False)),PLAN)
        for value in ({'steps':[{'title':'','minutes':10}]},{'steps':[{'title':'任务','minutes':999}]},{'steps':[{'title':'任务','minutes':True}]}):
            with self.assertRaises(ValueError):parse_plan(json.dumps(value))

    @unittest.skipUnless(os.name=='nt','Windows credential encryption')
    def test_key_vault_is_encrypted_and_bound_to_service(self):
        with tempfile.TemporaryDirectory() as directory:
            vault=KeyVault(directory);vault.save('test-only-not-a-real-key','https://api.deepseek.com')
            self.assertEqual(vault.load('https://api.deepseek.com/v1'),'test-only-not-a-real-key')
            self.assertEqual(vault.load('https://other.example'),'')
            self.assertNotIn(b'test-only-not-a-real-key',vault.path.read_bytes())

    def test_chat_history_and_edited_plan_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            history=ChatStore(directory);conversation=history.new_conversation('目标')
            turn=history.start_turn(conversation,'拆分目标','plan','deepseek-flash')
            history.update_turn(turn,json.dumps(PLAN,ensure_ascii=False),'complete');history.save_plan(turn,PLAN)
            pending=history.start_turn(conversation,'另一个问题','chat','deepseek-flash');history.update_turn(pending,'收到一部分','pending')
            history=ChatStore(directory)
            self.assertEqual(history.latest_plan(conversation)[1],PLAN)
            self.assertEqual(history.turns(conversation)[-1]['status'],'stopped')


class ChatNetworkTests(unittest.TestCase):
    def test_stream_probe_error_cancel_and_truncated_response(self):
        with local_model() as (server,base):
            client=ChatClient();completed=[];failed=[];stopped=[];chunks=[]
            client.completed.connect(lambda *args:completed.append(args));client.failed.connect(failed.append)
            client.stopped.connect(stopped.append);client.chunk.connect(chunks.append)
            config=ChatConfig(base_url=base)
            client.start(config,'test-key',[{'role':'user','content':'你好'}]);wait_until(lambda:not client.busy)
            self.assertEqual(completed[-1][0],ANSWER);self.assertEqual(''.join(chunks),ANSWER)
            client.start(config,'test-key',[{'role':'user','content':'测试'}],probe=True);wait_until(lambda:not client.busy)
            self.assertEqual(completed[-1][0],'连接成功')
            server.mode='auth';client.start(config,'test-key',[{'role':'user','content':'测试'}]);wait_until(lambda:not client.busy)
            self.assertIn('API Key',failed[-1]);self.assertNotIn('do-not-echo',failed[-1])
            server.mode='slow';chunks.clear();client.start(config,'test-key',[{'role':'user','content':'测试'}]);wait_until(lambda:bool(chunks))
            client.stop();wait_until(lambda:not client.busy);self.assertTrue(stopped[-1])
            server.mode='disconnect';client.start(config,'test-key',[{'role':'user','content':'测试'}]);wait_until(lambda:not client.busy)
            self.assertIn('中断',failed[-1])
            server.mode='slow';client.start(config,'test-key',[{'role':'user','content':'测试'}]);client.timeout.start(30)
            wait_until(lambda:not client.busy);self.assertIn('超时',failed[-1])
            client.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


class ChatUiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pet-chat-test-')
        self.store=Store(Path(self.temp.name));self.panel=ChatPanel(self.store,lambda:{'task':'复习第三章','state':'未开始','planned_minutes':30})
        self.panel.show();APP.processEvents()
    def tearDown(self):
        self.panel.close();self.panel.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents();self.temp.cleanup()

    def configure(self,base):
        self.panel.base_edit.setText(base);self.panel.key_edit.setText('test-key');self.assertTrue(self.panel.save_config())

    def test_missing_key_keeps_text_and_creates_no_fake_chat(self):
        self.panel.composer.setPlainText('你好');self.assertFalse(self.panel.send())
        self.assertEqual(self.panel.composer.toPlainText(),'你好');self.assertEqual(self.panel.chats.conversations(),[])

    def test_chat_plan_edit_apply_and_persistence(self):
        with local_model() as (server,base):
            self.configure(base);self.assertNotIn('test-key',self.store.path.read_text())
            self.assertTrue(self.panel.test_connection());wait_until(lambda:not self.panel.client.busy)
            self.assertEqual(self.panel.chats.conversations(),[])
            self.panel.composer.setPlainText('我有点卡住了');self.assertTrue(self.panel.send());wait_until(lambda:not self.panel.client.busy)
            self.assertIn(ANSWER,self.panel.transcript.toPlainText())
            self.assertNotIn('TEST_REASONING',self.panel.transcript.toPlainText())
            self.assertIn('复习第三章',server.requests[-1]['messages'][0]['content'])
            self.panel.context_check.setChecked(False);self.panel.composer.setPlainText('请拆分目标');self.panel.purpose.setCurrentIndex(1)
            self.assertTrue(self.panel.send());wait_until(lambda:not self.panel.client.busy)
            self.assertEqual(self.panel.steps.rowCount(),3)
            self.assertNotIn('复习第三章',server.requests[-1]['messages'][0]['content'])
            self.panel.steps.item(0,0).setText('先做一题');self.panel.steps.cellWidget(0,1).setValue(8)
            selected=[];self.panel.task_selected.connect(lambda *args:selected.append(args));self.panel.apply_selected_step()
            self.assertEqual(selected,[('先做一题',8)])
            reopened=ChatStore(self.store.path.parent)
            self.assertEqual(reopened.latest_plan(self.panel.conversation_id)[1]['steps'][0],{'title':'先做一题','minutes':8})

    def test_stop_preserves_partial_and_ui_remains_usable(self):
        with local_model() as (server,base):
            self.configure(base);server.mode='slow';self.panel.composer.setPlainText('慢一点回答');self.panel.send()
            wait_until(lambda:bool(self.panel._answer));self.panel.client.stop();wait_until(lambda:not self.panel.client.busy)
            turn=self.panel.chats.turns(self.panel.conversation_id)[-1]
            self.assertEqual(turn['status'],'stopped');self.assertTrue(turn['answer'])
            self.assertFalse(self.panel.composer.isReadOnly())

    def test_config_shortcut_does_not_send_draft_and_quick_prompt_only_prepares(self):
        with local_model() as (server,base):
            self.configure(base)
            QTest.mouseClick(self.panel.quick_buttons[0],Qt.MouseButton.LeftButton)
            self.assertTrue(self.panel.composer.toPlainText());self.assertEqual(server.requests,[])
            self.panel.tabs.setCurrentIndex(2);self.panel.key_edit.setFocus();APP.processEvents()
            QTest.keyClick(self.panel.key_edit,Qt.Key.Key_Return,Qt.KeyboardModifier.ControlModifier);QTest.qWait(80)
            self.assertEqual(server.requests,[]);self.assertFalse(self.panel.client.busy)


class ChatCompanionTests(unittest.TestCase):
    def test_applying_task_is_explicit_and_never_overwrites_running_round(self):
        with tempfile.TemporaryDirectory() as directory:
            c=Companion(Store(Path(directory)),tray_enabled=False)
            try:
                c.show_chat();self.assertIsNone(c.vision_controller)
                c.chat_panel.load_plan('test-plan',PLAN)
                self.assertTrue(c.apply_chat_task('先做一道例题',8))
                self.assertEqual(c.panel.task.text(),'先做一道例题');self.assertEqual(c.panel.duration.value(),8)
                self.assertEqual(c.session.status.value,'idle')
                c.begin();original=c.session.task
                self.assertFalse(c.apply_chat_task('另一项任务',20));self.assertEqual(c.session.task,original)
                self.assertFalse(c.chat_panel.can_apply())
                c.session._deadline=c.session.clock()-1;c.on_tick()
                self.assertTrue(c.apply_chat_task('下一项学习',12))
                self.assertEqual(c.session.status.value,'idle');self.assertEqual(c.panel.clock.seconds,720)
                self.assertEqual(c.history.summary()['completed'],1)
            finally:
                c.timer.stop();c.shutdown_chat();c.pet.hide();c.panel.hide()
                c.chat_panel.deleteLater();c.pet.deleteLater();c.panel.deleteLater()
                APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()


if __name__=='__main__':unittest.main()
