"""Isolated end-to-end checks for responses and SQLite learning rounds."""
from datetime import timedelta
import json
from pathlib import Path


def run(companion,preview=None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage,QColor,QPainter
    from PySide6.QtTest import QTest
    from .history import utc_now,LOCAL_ZONE
    from .perception import FeedbackEvent
    from .storage import Store

    c=companion;c.timer.stop()
    mono=[1000.];wall=[utc_now().astimezone(LOCAL_ZONE).replace(hour=10,minute=0,second=0,microsecond=0)]
    c.session.clock=lambda:mono[0];c.session.wall_clock=lambda:wall[0]
    c.history.clock=lambda:wall[0];c.reminder_gate.clock=lambda:mono[0]
    def advance(seconds):mono[0]+=seconds;wall[0]+=timedelta(seconds=seconds)
    c.panel.task.setText('读完这一节，整理三个要点');c.panel.duration.setValue(1);c.begin()
    advance(20);c.toggle();advance(90);c.toggle();advance(40);c.on_tick();c.on_tick()
    completed=c.history.sessions()[0]
    assert completed['elapsed']==60 and completed['pause_count']==1 and completed['status']=='completed'
    c.panel.task.setText('练习两道题，写下思路');c.panel.duration.setValue(25);c.begin();advance(30);c.on_tick()
    event=c.receive_vision_event(FeedbackEvent('phone','手机好像在手边停留一会儿啦。\n如果正在学习，我们先完成眼前这一小步？','remind'))
    QTest.mouseClick(c.pet.bubble.action_buttons['false_positive'],Qt.MouseButton.LeftButton)
    assert c.history.reminder(event)['response']=='false_positive'
    care=c.receive_vision_event(FeedbackEvent('care','辛苦啦，要不要放松一下眉头？','care'))
    assert c.respond_to_reminder(care,'snooze') and c.reminder_gate.snoozed
    example=c.send_sample('phone')
    assert c.vision_controller is None,'Examples must not start a camera or scanner'
    c.show_history();QTest.qWait(120)
    if preview:
        path=Path(preview);path.parent.mkdir(parents=True,exist_ok=True)
        history=c.history_panel.grab();pet=c.pet.grab()
        image=QImage(history.width()+pet.width()+100,max(history.height(),pet.height())+60,QImage.Format.Format_ARGB32)
        image.fill(QColor('#F0EDE2'));painter=QPainter(image)
        painter.drawPixmap(25,30,history);painter.drawPixmap(history.width()+65,image.height()-pet.height()-25,pet);painter.end()
        assert image.save(str(path))
        c.history_panel.reveal_reminder(example)
        assert c.history_panel.grab().save(str(path.with_name(path.stem+'-feedback.png')))
    before=c.reminder_gate.phone_until
    QTest.mouseClick(c.pet.bubble.action_buttons['research'],Qt.MouseButton.LeftButton)
    assert c.history.reminder(example)['response']=='research' and c.reminder_gate.phone_until==before
    summary=c.history.summary();assert (summary['seconds'],summary['completed'],summary['reminders'],summary['corrections'])==(90,1,2,1)
    assert not c.respond_to_reminder(event,'snooze'),'Duplicate response must be ignored'
    reopened=Store(c.store.path.parent)
    assert len(reopened.history.sessions())==2
    assert reopened.history.summary()['seconds']==90
    c.account('exited');assert c.history.session(c.session.round_id)['status']=='exited'
    c.history_panel.hide()
    if preview:
        Path(preview).with_suffix('.json').write_text(json.dumps({'passed':True,'rounds':2,
            'study_seconds':90,'completed':1,'real_reminders':2,'corrections':1,
            'example_feedback_separate':True,'camera_started':False},indent=2),encoding='utf-8')
    print('PASS: reminder buttons, sample isolation, pause exclusion, round completion, history persistence, exit finalization',flush=True)
