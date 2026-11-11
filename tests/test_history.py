from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
import sqlite3
from contextlib import closing

from study_pet.history import HistoryStore,LOCAL_ZONE,local_day,stamp
from study_pet.focus import FocusSession
from study_pet.storage import Store


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pet-history-');self.directory=Path(self.temp.name)
        self.wall=datetime(2026,11,11,10,0,tzinfo=LOCAL_ZONE);self.mono=1000.
        self.h=HistoryStore(self.directory,clock=lambda:self.wall)
        self.s=FocusSession(lambda:self.mono,lambda:self.wall)

    def tearDown(self):self.temp.cleanup()

    def advance(self,seconds):self.mono+=seconds;self.wall+=timedelta(seconds=seconds)

    def begin(self,kind='focus'):
        self.s.start(1,'读完这一节',kind);self.h.ensure_session(self.s)
        self.h.checkpoint(self.s.round_id,0,'running',now=self.wall)

    def sync(self,status=None):
        self.h.checkpoint(self.s.round_id,self.s.elapsed,status or self.s.status.value,self.s.pause_count,now=self.wall)

    def test_pause_excluded_completion_idempotent_and_persistent(self):
        self.begin();identifier=self.s.round_id
        self.advance(10);self.s.pause();self.sync()
        self.advance(300);self.s.resume();self.sync()
        self.advance(50);self.s.tick();self.sync();self.sync()
        row=self.h.session(identifier)
        self.assertEqual(row['status'],'completed');self.assertEqual(row['elapsed'],60.)
        self.assertEqual(row['pause_count'],1)
        reopened=HistoryStore(self.directory,clock=lambda:self.wall)
        summary=reopened.summary('2026-11-11','2026-11-11')
        self.assertEqual((summary['seconds'],summary['completed']),(60,1))

    def test_daily_split_at_midnight(self):
        self.wall=datetime(2026,11,11,23,59,50,tzinfo=LOCAL_ZONE)
        self.begin();self.advance(20);self.sync('stopped')
        self.assertEqual(self.h.summary('2026-11-11','2026-11-11')['seconds'],10)
        self.assertEqual(self.h.summary('2026-11-12','2026-11-12')['seconds'],10)

    def test_legacy_aggregate_imported_once_without_fabricated_rounds(self):
        other=self.directory/'legacy';data={'date':'2026-11-11','seconds':1500,'completed':1}
        h=HistoryStore(other,data);h=HistoryStore(other,data)
        self.assertEqual(h.summary()['seconds'],1500);self.assertEqual(h.summary()['completed'],1)
        self.assertEqual(h.sessions(),[])

    def test_break_record_does_not_inflate_study_total(self):
        self.begin('break');self.advance(60);self.s.tick();self.sync()
        self.assertEqual(self.h.session(self.s.round_id)['elapsed'],60)
        self.assertEqual(self.h.summary()['seconds'],0);self.assertEqual(self.h.summary()['completed'],0)

    def test_abnormal_restart_retains_only_last_checkpoint(self):
        self.begin();self.advance(14);self.sync();saved=self.h.session(self.s.round_id)['updated_at']
        self.advance(7200)
        self.assertEqual(self.h.recover_incomplete(),1);self.assertEqual(self.h.recover_incomplete(),0)
        row=self.h.session(self.s.round_id)
        self.assertEqual((row['status'],row['elapsed'],row['ended_at']),('interrupted',14,saved))

    def test_reminders_link_to_round_and_example_is_separate(self):
        self.begin()
        real=self.h.add_reminder('phone','手机提示','vision',self.s.round_id)
        example=self.h.add_reminder('phone','示例','example',self.s.round_id)
        self.assertTrue(self.h.respond(real,'false_positive'));self.assertFalse(self.h.respond(real,'snooze'))
        self.assertTrue(self.h.respond(example,'research'))
        summary=self.h.summary();self.assertEqual((summary['reminders'],summary['corrections']),(1,1))
        self.assertIsNone(self.h.reminder(example)['session_id'])
        self.assertEqual(len(self.h.reminders(session_id=self.s.round_id)),1)
        row=self.h.sessions()[0];self.assertEqual((row['reminder_count'],row['correction_count']),(1,1))

    def test_care_does_not_accept_research_and_store_cache_updates(self):
        event=self.h.add_reminder('care','关怀')
        self.assertFalse(self.h.respond(event,'research'))
        store=Store(self.directory/'store');store.history.clock=lambda:self.wall
        store.record(30,False);self.assertEqual(store.today()['seconds'],30)
        store.record(20,True);self.assertEqual(store.today()['seconds'],50)
        self.assertEqual(store.today()['completed'],1)

    def test_summary_counts_full_history_beyond_visible_list_limit(self):
        with closing(sqlite3.connect(self.h.path)) as conn:
            with conn:
                conn.executemany('INSERT INTO reminders(id,kind,source,text,created_at,response) VALUES(?,?,?,?,?,?)',
                    [(str(i),'phone','vision','提示',stamp(self.wall),'false_positive' if i%2==0 else None) for i in range(1005)])
        summary=self.h.summary()
        self.assertEqual(summary['reminders'],1005);self.assertEqual(summary['corrections'],503)
        self.assertEqual(len(self.h.reminders()),1000)

    def test_corrupt_database_is_preserved_and_reported(self):
        folder=self.directory/'corrupt';folder.mkdir();path=folder/'study_history.sqlite3'
        path.write_bytes(b'not a sqlite database')
        with self.assertLogs(level='ERROR'):
            h=HistoryStore(folder);self.assertEqual(h.sessions(),[])
        self.assertTrue(h.error);self.assertEqual(path.read_bytes(),b'not a sqlite database')


if __name__=='__main__':unittest.main()
