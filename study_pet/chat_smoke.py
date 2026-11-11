"""Packaged chat protocol check using a loopback fixture, never a paid model."""
import json
from pathlib import Path
import time


def run(companion,preview=None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor,QImage,QPainter
    from PySide6.QtNetwork import QSslSocket
    from PySide6.QtTest import QTest
    from .chat_core import DEFAULT_BASE
    from .chat_fixture import local_model,ANSWER
    from .chat_store import ChatStore

    def wait_for(predicate,seconds=12):
        deadline=time.monotonic()+seconds
        while not predicate() and time.monotonic()<deadline:QTest.qWait(25)
        assert predicate(),'Chat protocol check timed out'

    c=companion;c.panel.task.setText('复习第三章，弄懂三个关键概念');c.panel.duration.setValue(30)
    c.show_chat();p=c.chat_panel
    assert c.vision_controller is None
    assert QSslSocket.supportsSsl(),'Qt HTTPS backend missing'
    with local_model() as (server,base):
        p.base_edit.setText(base);p.key_edit.setText('test-key-not-a-real-secret');assert p.save_config()
        assert p.test_connection();wait_for(lambda:not p.client.busy)
        assert not p.chats.conversations(),'Connection probe must not create a conversation'
        p.composer.setPlainText('我准备复习第三章，应该从哪里开始？');assert p.send();wait_for(lambda:not p.client.busy)
        assert ANSWER in p.transcript.toPlainText()
        assert 'TEST_REASONING' not in p.transcript.toPlainText()
        p.purpose.setCurrentIndex(1);p.composer.setPlainText('帮我把这30分钟拆成几个学习步骤。')
        assert p.send();wait_for(lambda:not p.client.busy);assert p.steps.rowCount()==3
        p.steps.item(0,0).setText('先梳理第三章的三个核心概念');p.steps.cellWidget(0,1).setValue(8)
        QTest.mouseClick(p.apply_step,Qt.MouseButton.LeftButton)
        assert c.panel.task.text()=='先梳理第三章的三个核心概念' and c.panel.duration.value()==8
        assert c.session.status.value=='idle','Selecting a task must not start a timer'
        if preview:
            path=Path(preview);path.parent.mkdir(parents=True,exist_ok=True)
            p.tabs.setCurrentIndex(0);p.status.setText('本地接口模拟验证：此预览未调用DeepSeek真实模型。');QTest.qWait(90)
            chat=p.grab();pet=c.pet.grab()
            image=QImage(chat.width()+pet.width()+100,max(chat.height(),pet.height())+60,QImage.Format.Format_ARGB32)
            image.fill(QColor('#F0EDE2'));paint=QPainter(image);paint.drawPixmap(25,30,chat)
            paint.drawPixmap(chat.width()+65,image.height()-pet.height()-25,pet);paint.end();assert image.save(str(path))
            p.tabs.setCurrentIndex(1);assert p.grab().save(str(path.with_name(path.stem+'-steps.png')))
            p.base_edit.setText(DEFAULT_BASE);p.tabs.setCurrentIndex(2)
            assert p.grab().save(str(path.with_name(path.stem+'-config.png')))
            p.base_edit.setText(base);assert p.save_config()
        server.mode='slow';p.purpose.setCurrentIndex(0);p.composer.setPlainText('给我一个小提示。')
        assert p.send();wait_for(lambda:bool(p._answer));p.client.stop();wait_for(lambda:not p.client.busy)
        turns=p.chats.turns(p.conversation_id);assert turns[-1]['status']=='stopped' and turns[-1]['answer']
        reopened=ChatStore(c.store.path.parent)
        assert reopened.latest_plan(p.conversation_id)[1]['steps'][0]['minutes']==8
        assert b'test-key-not-a-real-secret' not in p.vault.path.read_bytes()
        assert 'test-key-not-a-real-secret' not in c.store.path.read_text(encoding='utf-8')
        assert c.vision_controller is None
    c.shutdown_chat();c.panel.hide()
    if preview:
        Path(preview).with_suffix('.json').write_text(json.dumps({'passed':True,'transport':'local DeepSeek-compatible fixture',
            'streaming':True,'stop_preserves_partial':True,'plan_edit_and_handoff':True,
            'credentials_encrypted':True,'https_backend':True,'real_deepseek_model_called':False},indent=2),encoding='utf-8')
    print('PASS: chat streaming, encrypted key, probe, plan editing, explicit task handoff, stop, local persistence, TLS backend',flush=True)
