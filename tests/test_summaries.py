from datetime import datetime,timedelta
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject,Signal,QEvent
from PySide6.QtWidgets import QApplication

from study_pet.chat_store import ChatStore
from study_pet.focus import FocusSession
from study_pet.history import HistoryStore,LOCAL_ZONE,stamp
from study_pet.history_ui import HistoryPanel
from study_pet.storage import Store
from study_pet.summary_core import build_facts,local_summary,summary_messages,parse_ai_summary
from study_pet.summary_service import SummaryService

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


class FakeClient(QObject):
    completed=Signal(str,str)
    failed=Signal(str)
    stopped=Signal(str)
    def __init__(self):super().__init__();self.busy=False;self.requests=[]
    def start(self,config,key,messages,purpose='chat'):
        self.requests.append((messages,purpose));self.busy=True;return True
    def stop(self):self.busy=False;self.stopped.emit('')
    def complete(self,value):self.busy=False;self.completed.emit(json.dumps(value,ensure_ascii=False),'stop')


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pet-summary-test-');self.directory=Path(self.temp.name)
        self.store=Store(self.directory);self.h=self.store.history
        self.wall=datetime(2026,11,17,10,0,tzinfo=LOCAL_ZONE);self.h.clock=lambda:self.wall
        self.mono=100.;self.session=FocusSession(lambda:self.mono,lambda:self.wall)
        self.session.start(2,'动态规划');self.h.ensure_session(self.session)
        self.chats=ChatStore(self.directory);self.conversation=self.chats.new_conversation('学习')

    def tearDown(self):self.temp.cleanup()

    def elapsed(self,seconds):
        self.mono+=seconds;self.wall+=timedelta(seconds=seconds)
        self.h.checkpoint(self.session.round_id,self.session.elapsed,'stopped',now=self.wall)

    def event(self,kind,seconds=10,identifier=None,start=None):
        begin=start or self.session.started_at
        return {'id':identifier or kind,'type':kind,'started_at':stamp(begin),
            'ended_at':stamp(begin+timedelta(seconds=seconds)),'duration':seconds,
            'status':'closed','evidence':{'reason':'test'}}

    def facts(self):return build_facts(self.h,self.chats,'session',self.session.round_id)

    def test_intervals_idempotent_feedback_and_reminders_are_distinct(self):
        self.elapsed(60);event=self.event('phone',10);event['status']='ongoing'
        self.h.upsert_behavior(self.session.round_id,event)
        event['ended_at']=stamp(self.session.started_at+timedelta(seconds=20));event['duration']=20;event['status']='closed'
        self.h.upsert_behavior(self.session.round_id,event);self.h.upsert_behavior(self.session.round_id,event)
        a=self.h.add_reminder('phone','提示','vision',self.session.round_id,behavior_id='phone')
        self.h.add_reminder('phone','另一条提示','vision',self.session.round_id,behavior_id='phone')
        facts=self.facts();self.assertEqual(facts['reminder_count'],2)
        self.assertEqual((facts['behaviors']['phone']['count'],facts['behaviors']['phone']['seconds']),(1,20))
        self.assertTrue(self.h.respond(a,'false_positive'))
        corrected=self.facts()['behaviors']['phone']
        self.assertEqual((corrected['count'],corrected['seconds'],corrected['corrected']),(0,0,1))
        late=dict(event,status='ongoing',duration=50)
        self.h.upsert_behavior(self.session.round_id,late)
        self.assertEqual(self.h.behaviors(self.session.round_id)[0]['status'],'closed')

    def test_unknown_coverage_not_absence_and_clock_upper_bound(self):
        self.elapsed(30)
        self.h.upsert_behavior(self.session.round_id,self.event('presence',10))
        self.h.upsert_behavior(self.session.round_id,self.event('unknown',5,start=self.session.started_at+timedelta(seconds=10)))
        facts=self.facts();self.assertEqual(facts['away_count'],0)
        self.assertEqual(facts['visual']['known_seconds'],10)
        self.assertEqual(facts['visual']['unknown'],5)
        self.assertEqual(facts['visual']['unobserved_seconds'],15)
        self.h.upsert_behavior(self.session.round_id,self.event('away',80))
        visual=self.facts()['visual']
        self.assertLessEqual(visual['known_seconds'],30)
        self.assertAlmostEqual(visual['presence']+visual['away']+visual['unknown']+visual['unobserved_seconds'],30,places=2)

    def test_behavior_duration_split_across_midnight_count_by_start_day(self):
        other=FocusSession(lambda:self.mono,lambda:datetime(2026,11,17,23,59,50,tzinfo=LOCAL_ZONE))
        other.start(1,'跨日学习');self.h.ensure_session(other)
        self.h.checkpoint(other.round_id,20,'stopped',now=other.started_at+timedelta(seconds=20))
        self.h.upsert_behavior(other.round_id,self.event('away',20,'cross',other.started_at))
        first=build_facts(self.h,self.chats,'day','2026-11-17')
        second=build_facts(self.h,self.chats,'day','2026-11-18')
        self.assertEqual((first['away_count'],second['away_count']),(1,0))
        self.assertEqual((first['visual']['away'],second['visual']['away']),(10,10))

    def test_chat_association_is_per_turn_and_snapshot_is_frozen(self):
        context={'task':'原任务','state':'进行中','raw_image':'must-not-store'}
        first=self.chats.start_turn(self.conversation,'问题一','chat','test',self.session.round_id,context)
        context['task']='新任务'
        self.chats.start_turn(self.conversation,'问题二','chat','test','next-session',context)
        self.chats.start_turn(self.conversation,'学习前问题','chat','test')
        related=self.chats.related_turns(session_id=self.session.round_id)
        self.assertEqual([t['id'] for t in related],[first])
        self.assertEqual(json.loads(related[0]['context_snapshot'])['task'],'原任务')
        self.assertNotIn('raw_image',related[0]['context_snapshot'])
        service=SummaryService(self.store,client=FakeClient());service.ensure_session(self.session.round_id)
        self.assertEqual(self.chats.turns(self.conversation)[0]['status'],'pending')

    def test_schema_upgrade_keeps_unassociated_old_messages(self):
        folder=self.directory/'old';folder.mkdir();path=folder/'chat_history.sqlite3'
        with closing(sqlite3.connect(path)) as c:
            c.executescript('''CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,updated_at TEXT);
              CREATE TABLE turns(id TEXT PRIMARY KEY,conversation_id TEXT,user_text TEXT,answer TEXT,status TEXT,purpose TEXT,model TEXT,created_at TEXT,updated_at TEXT,error TEXT);
              INSERT INTO conversations VALUES('c','old','2026-11-17','2026-11-17');
              INSERT INTO turns VALUES('t','c','old question','answer','complete','chat','old','2026-11-17','2026-11-17','');''')
        migrated=ChatStore(folder);old=migrated.turns('c')[0]
        self.assertIsNone(old['session_id']);self.assertEqual(json.loads(old['context_snapshot']),{})
        self.assertEqual(old['answer'],'answer')

    def test_coach_is_real_reminder_and_example_stays_separate(self):
        real=self.h.add_reminder('break_due','休息','coach',self.session.round_id)
        self.h.add_reminder('break_due','示例','example',self.session.round_id)
        self.assertEqual(self.h.summary()['reminders'],1)
        self.assertEqual(self.h.reminder(real)['session_id'],self.session.round_id)
        self.assertFalse(self.h.respond(real,'research'))
        self.assertTrue(self.h.respond(real,'later'))

    def test_restart_closes_last_observed_intervals_and_recovers_pending_ai(self):
        event=self.event('phone',10);event['status']='ongoing'
        self.h.upsert_behavior(self.session.round_id,event)
        self.h.checkpoint(self.session.round_id,10,'running',now=self.wall+timedelta(seconds=10))
        service=SummaryService(self.store,client=FakeClient())
        record=service.ensure_session(self.session.round_id)
        self.h.save_ai_summary('session',self.session.round_id,record['facts_hash'],status='pending')
        self.wall+=timedelta(hours=2)
        self.assertEqual(self.h.recover_incomplete(),1)
        recovered=self.h.behaviors(self.session.round_id)[0]
        self.assertEqual(recovered['status'],'closed')
        self.assertEqual(recovered['ended_at'],event['ended_at']);self.assertEqual(recovered['duration'],10)
        summary=self.h.learning_summary('session',self.session.round_id)
        self.assertEqual(summary['ai_status'],'failed');self.assertIn('上次生成中断',summary['ai_error'])
        self.assertEqual(summary['local_text'],record['local_text']);self.assertEqual(summary['facts'],record['facts'])
        self.assertEqual(self.h.recover_incomplete(),0)
        # Also close an orphaned ongoing interval whose parent had already ended.
        other=FocusSession(lambda:self.mono,lambda:self.wall);other.start(1,'已完成任务')
        self.h.ensure_session(other)
        closed_parent_event=self.event('presence',5,'finished-parent',self.wall);closed_parent_event['status']='ongoing'
        self.h.upsert_behavior(other.round_id,closed_parent_event)
        self.h.checkpoint(other.round_id,5,'stopped',now=self.wall+timedelta(seconds=5))
        self.assertEqual(self.h.recover_incomplete(),0)
        self.assertEqual(self.h.behaviors(other.round_id)[0]['status'],'closed')

    def test_no_remote_generation_without_explicit_consent_and_stale_response_guard(self):
        self.elapsed(30);client=FakeClient();service=SummaryService(self.store,client=client)
        record=service.ensure_session(self.session.round_id)
        self.assertEqual(client.requests,[]);self.assertIn('视觉覆盖不足',record['local_text'])
        self.assertFalse(service.request_ai('session',self.session.round_id));self.assertEqual(client.requests,[])
        with patch('study_pet.summary_service.KeyVault') as vault:
            vault.return_value.load.return_value='test-only'
            self.assertTrue(service.request_ai('session',self.session.round_id,consent=True))
        self.h.save_note('session',self.session.round_id,'完成了一道题')
        client.complete({'learning_points':[],'open_questions':[],'suggestions':['复习边界条件']})
        result=self.h.learning_summary('session',self.session.round_id)
        self.assertNotEqual(result['ai_status'],'complete');self.assertEqual(result['ai_text'],'')
        self.assertIn('完成了一道题',result['local_text'])

    def test_ai_sources_only_complete_answers_and_reject_invented_ids(self):
        first=self.chats.start_turn(self.conversation,'状态如何定义','chat','test',self.session.round_id)
        self.chats.update_turn(first,'先定义子问题','complete')
        second=self.chats.start_turn(self.conversation,'不完整问题','chat','test',self.session.round_id)
        self.chats.update_turn(second,'残缺内容','stopped')
        messages,ids=summary_messages(self.facts())
        self.assertEqual(ids,{first});self.assertNotIn('残缺内容',str(messages))
        valid={'learning_points':[{'text':'讨论状态定义','turn_ids':[first]}],'open_questions':[],'suggestions':[]}
        self.assertEqual(parse_ai_summary(json.dumps(valid),ids),valid)
        valid['learning_points'][0]['turn_ids']=['invented']
        with self.assertRaises(ValueError):parse_ai_summary(json.dumps(valid),ids)
        with self.assertRaises(ValueError):parse_ai_summary('',ids)

    def test_history_panel_local_note_and_event_correction(self):
        self.elapsed(30);self.h.upsert_behavior(self.session.round_id,self.event('phone',10))
        service=SummaryService(self.store,client=FakeClient());panel=HistoryPanel(self.h,store=self.store,summary_service=service)
        try:
            panel.refresh_data();self.assertFalse(panel.ai_consent.isChecked())
            self.assertIn('动态规划',panel.summary_text.toPlainText())
            panel.self_note.setPlainText('做完第一题');panel.save_summary_note()
            self.assertIn('做完第一题',panel.summary_text.toPlainText())
            panel.behavior_table.selectRow(0);panel.correct_selected_behavior('false_positive')
            self.assertIn('已排除误报 1 段',panel.summary_text.toPlainText())
        finally:
            panel.timer.stop();panel.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)


if __name__=='__main__':unittest.main()
