"""Isolated desktop regression for proactive coaching and source-linked records.

Synthetic observations verify integration, not real-camera recognition accuracy.
No camera, microphone, API key, or remote service is used.
"""
from datetime import timedelta
import json
from pathlib import Path
from unittest.mock import patch


def run(c,preview=None):
    from PySide6.QtTest import QTest
    import numpy as np
    import sounddevice
    from .audio_sensing import YAMNet
    from .focus import Status
    from .history import utc_now,stamp,local_day
    from .perception import FeedbackEvent
    assert sounddevice.InputStream
    audio_model=YAMNet()
    try:
        assert audio_model.scores(np.zeros(16000,dtype=np.float32),16000).get('Silence',0)>.5
    finally:audio_model.close()
    c.timer.stop();mono=[1000.];wall=[utc_now()]
    c.session.clock=lambda:mono[0];c.session.wall_clock=lambda:wall[0]
    c.history.clock=lambda:wall[0];c.reminder_gate.clock=lambda:mono[0]
    c.coach.configure(interval_minutes=1,global_cooldown_seconds=0,kind_cooldown_seconds=0)

    def advance(seconds):
        for _ in range(seconds):
            mono[0]+=1;wall[0]+=timedelta(seconds=1);c.on_tick()

    c.panel.task.setText('测试：学习状态转移，整理练习思路');c.panel.duration.setValue(25);c.begin()
    original=c.session.round_id;start=wall[0]
    assert not c.memory.enabled and c.memory.set_enabled(True)
    advance(20)
    c.receive_behavior({'id':'smoke-presence','type':'presence','started_at':stamp(start),
        'ended_at':stamp(wall[0]),'duration':20.,'status':'closed','evidence':{'synthetic':True}})
    phone=c.receive_behavior({'id':'smoke-phone','type':'phone','started_at':stamp(start+timedelta(seconds=5)),
        'ended_at':stamp(wall[0]),'duration':15.,'status':'closed','evidence':{'synthetic':True}})
    assert phone
    reminder=c.present_reminder(FeedbackEvent('phone','测试：手机线索需要用户确认。','remind',behavior_id='smoke-phone'),'vision')
    assert c.respond_to_reminder(reminder,'research')
    advance(40)
    due=[r for r in c.history.reminders(session_id=original) if r['kind']=='break_due']
    assert len(due)==1
    if preview:
        path=Path(preview);path.parent.mkdir(parents=True,exist_ok=True)
        c.show_panel();QTest.qWait(80)
        assert c.panel.grab().save(str(path))
        assert c.pet.grab().save(str(path.with_name(path.stem+'-pet.png')))
    before=c.session.remaining
    assert c.respond_to_reminder(due[0]['id'],'rest_now')
    assert c._suspended_focus.round_id==original and c.session.kind=='break'
    advance(300)
    assert c.session.status==Status.COMPLETED and c.coach.streak_seconds==0
    assert any(r.reminder_id==due[0]['id'] and r.outcome=='rested' for r in c.memory.recent())
    c.toggle()
    assert c.session.round_id==original and c.session.remaining==before
    advance(10)
    turn=c.summary_service.chats.start_turn(c.summary_service.chats.new_conversation('测试学习对话'),
        '为什么要明确状态定义？','chat','local-fixture',session_id=original,context_snapshot={'task':c.session.task})
    c.summary_service.chats.update_turn(turn,'状态定义明确后，才能推导转移条件和边界。','complete')
    c.stop()
    summary=c.history.learning_summary('session',original)
    assert summary and summary['facts']['study_seconds']==70
    assert summary['facts']['behaviors']['phone']['research']==1
    assert turn in summary['facts']['source_turn_ids']
    assert c.history.learning_summary('day',local_day(wall[0]))
    c.show_history();QTest.qWait(80)
    if preview:
        assert c.history_panel.grab().save(str(path.with_name(path.stem+'-history.png')))
        with patch('study_pet.camera.VisionController.refresh_devices'):c.show_camera()
        QTest.qWait(80)
        assert c.camera_panel.grab().save(str(path.with_name(path.stem+'-camera.png')))
        path.with_suffix('.json').write_text(json.dumps({'passed':True,'study_seconds':70,
            'rest_seconds':300,'original_round_restored':True,'behavior_feedback_linked':True,
            'dialogue_linked':True,'local_summary_saved':True,'camera_started':False,
            'network_called':False,'offline_audio_model':True,'memory_rest_outcome':True,
            'observations':'synthetic; does not measure camera or microphone accuracy'},
            ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS: proactive rest, task recovery, support memory, study summaries and offline audio model; no live sensors or network',flush=True)
