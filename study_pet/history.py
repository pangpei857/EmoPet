"""Transactional local learning records. No images, landmarks or audio stored."""
from contextlib import closing
from datetime import datetime, timedelta, timezone, date
import hashlib
import json
import logging
import math
from pathlib import Path
import sqlite3
from uuid import uuid4

LOCAL_ZONE=timezone(timedelta(hours=8))
FINAL_STATES={'completed','stopped','exited','replaced','interrupted'}
STATE_LABELS={'running':'进行中','paused':'已暂停','completed':'已完成','stopped':'提前结束',
              'exited':'退出时结束','replaced':'切换任务','interrupted':'意外中断'}
RESPONSE_LABELS={'research':'我在查资料','false_positive':'这次识别错了','snooze':'稍后提醒',
    'rest_now':'现在休息','later':'再学10分钟','dismiss':'知道了','help':'帮我拆解',
    'thinking':'我在思考','paper':'我在看书写字'}
KIND_LABELS={'phone':'手机提醒','care':'眉部关怀','head_down':'低头关怀','break_due':'休息关怀'}
BEHAVIOR_LABELS={'presence':'在位','away':'离位','unknown':'无法判断','phone':'疑似手机使用',
    'care':'持续眉部动作','head_down':'持续低头'}


def response_allowed(kind,response):
    if response not in RESPONSE_LABELS:return False
    if response=='research':return kind=='phone'
    if response in {'rest_now','later'}:return kind=='break_due'
    if response in {'help','thinking'}:return kind=='care'
    if response=='paper':return kind=='head_down'
    return True


def utc_now():return datetime.now(timezone.utc)
def stamp(value):return value.astimezone(timezone.utc).isoformat(timespec='microseconds')
def parse(value):return datetime.fromisoformat(value)
def local_day(value=None):return (value or utc_now()).astimezone(LOCAL_ZONE).date().isoformat()
def display_time(value):return parse(value).astimezone(LOCAL_ZONE).strftime('%m-%d %H:%M:%S') if value else '—'


def allocate_seconds(start,end,seconds):
    """Split active elapsed seconds over local calendar days, including midnight."""
    if seconds<=0:return {}
    if end<=start:return {local_day(end):seconds}
    total=(end-start).total_seconds();cursor=start;parts={}
    while cursor<end:
        next_day=cursor.astimezone(LOCAL_ZONE).date()+timedelta(days=1)
        boundary=datetime.combine(next_day,datetime.min.time(),LOCAL_ZONE).astimezone(timezone.utc)
        edge=min(boundary,end)
        parts[local_day(cursor)]=seconds*(edge-cursor).total_seconds()/total
        cursor=edge
    return parts


class HistoryStore:
    def __init__(self,directory,legacy_daily=None,clock=utc_now):
        self.path=Path(directory)/'study_history.sqlite3';self.clock=clock
        self.error='';self.revision=0
        self._run(self._schema,write=True)
        self._migrate_daily(legacy_daily)

    def _run(self,operation,default=None,*,write=False):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.path,timeout=3)) as conn:
                conn.row_factory=sqlite3.Row
                conn.execute('PRAGMA foreign_keys=ON')
                with conn:result=operation(conn)
            self.error=''
            if write:self.revision+=1
            return result
        except (sqlite3.Error,OSError):
            logging.exception('Could not read or save local learning records')
            self.error='学习记录暂时无法读写，请检查本地应用数据目录的权限与剩余空间。'
            return default

    @staticmethod
    def _schema(conn):
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS legacy_daily(day TEXT PRIMARY KEY,seconds REAL NOT NULL,completed INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(
          id TEXT PRIMARY KEY,task TEXT NOT NULL,kind TEXT NOT NULL,planned_seconds INTEGER NOT NULL,
          started_at TEXT NOT NULL,updated_at TEXT NOT NULL,ended_at TEXT,
          elapsed REAL NOT NULL DEFAULT 0,status TEXT NOT NULL,pause_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS session_days(
          session_id TEXT NOT NULL REFERENCES sessions(id),day TEXT NOT NULL,
          seconds REAL NOT NULL DEFAULT 0,completed INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(session_id,day));
        CREATE TABLE IF NOT EXISTS reminders(
          id TEXT PRIMARY KEY,session_id TEXT REFERENCES sessions(id),kind TEXT NOT NULL,
          source TEXT NOT NULL,text TEXT NOT NULL,created_at TEXT NOT NULL,
          response TEXT,responded_at TEXT);
        CREATE INDEX IF NOT EXISTS session_started ON sessions(started_at);
        CREATE INDEX IF NOT EXISTS reminder_session ON reminders(session_id,created_at);
        CREATE INDEX IF NOT EXISTS reminder_created ON reminders(created_at);
        CREATE TABLE IF NOT EXISTS behavior_events(
          id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),kind TEXT NOT NULL,
          started_at TEXT NOT NULL,ended_at TEXT NOT NULL,duration REAL NOT NULL,
          evidence TEXT NOT NULL DEFAULT '{}',status TEXT NOT NULL,feedback TEXT);
        CREATE INDEX IF NOT EXISTS behavior_session ON behavior_events(session_id,started_at);
        CREATE INDEX IF NOT EXISTS behavior_start ON behavior_events(started_at);
        CREATE TABLE IF NOT EXISTS learning_summaries(
          scope TEXT NOT NULL,target TEXT NOT NULL,facts TEXT NOT NULL,facts_hash TEXT NOT NULL,
          local_text TEXT NOT NULL,ai_text TEXT NOT NULL DEFAULT '',ai_status TEXT NOT NULL DEFAULT 'local',
          ai_error TEXT NOT NULL DEFAULT '',model TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,
          PRIMARY KEY(scope,target));
        CREATE TABLE IF NOT EXISTS summary_notes(
          scope TEXT NOT NULL,target TEXT NOT NULL,note TEXT NOT NULL,PRIMARY KEY(scope,target));
        ''')
        if 'behavior_id' not in {r[1] for r in conn.execute('PRAGMA table_info(reminders)')}:
            conn.execute('ALTER TABLE reminders ADD COLUMN behavior_id TEXT')

    def _migrate_daily(self,value):
        def apply(conn):
            if conn.execute("SELECT 1 FROM metadata WHERE key='legacy_daily_imported'").fetchone():return
            if isinstance(value,dict):
                try:
                    day=date.fromisoformat(value['date']).isoformat()
                    seconds=max(0,int(value.get('seconds',0)));completed=max(0,int(value.get('completed',0)))
                    conn.execute('INSERT OR IGNORE INTO legacy_daily VALUES(?,?,?)',(day,seconds,completed))
                except (ValueError,TypeError,KeyError,OverflowError):pass
            conn.execute("INSERT INTO metadata VALUES('legacy_daily_imported','1')")
        self._run(apply,write=True)

    def recover_incomplete(self):
        def apply(conn):
            cursor=conn.execute("UPDATE sessions SET status='interrupted',ended_at=updated_at WHERE status IN ('running','paused')")
            recovered=cursor.rowcount
            # Close only at the last observed endpoint; process downtime is not
            # evidence of continued presence, absence or any other behaviour.
            conn.execute('''UPDATE behavior_events SET status='closed' WHERE status='ongoing'
                AND session_id IN (SELECT id FROM sessions WHERE status IN
                    ('completed','stopped','exited','replaced','interrupted'))''')
            conn.execute("""UPDATE learning_summaries SET ai_status='failed',
                ai_error='上次生成中断，已保留本地统计版，可重新生成。' WHERE ai_status='pending'""")
            return recovered
        return self._run(apply,0,write=True)

    def ensure_session(self,session):
        if not session.round_id:return None
        def apply(conn):
            conn.execute('''INSERT OR IGNORE INTO sessions
                (id,task,kind,planned_seconds,started_at,updated_at,status)
                VALUES(?,?,?,?,?,?,?)''',(session.round_id,session.task,session.kind,session.duration,
                    stamp(session.started_at),stamp(session.started_at),'running'))
            return session.round_id
        return self._run(apply,write=True)

    def checkpoint(self,session_id,elapsed,status,pause_count=0,now=None):
        now=now or self.clock()
        def apply(conn):
            row=conn.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()
            if row is None:return None
            if row['status'] in FINAL_STATES:return float(row['elapsed'])
            value=max(float(row['elapsed']),min(float(row['planned_seconds']),max(0.,float(elapsed))))
            delta=value-float(row['elapsed']);previous=parse(row['updated_at']);end=now
            if status=='completed' and delta>0 and (now-previous).total_seconds()>=delta:
                end=previous+timedelta(seconds=delta)
            if row['kind']=='focus':
                for day,seconds in allocate_seconds(previous,end,delta).items():
                    conn.execute('''INSERT INTO session_days(session_id,day,seconds) VALUES(?,?,?)
                        ON CONFLICT(session_id,day) DO UPDATE SET seconds=seconds+excluded.seconds''',(session_id,day,seconds))
                if status=='completed':
                    conn.execute('''INSERT INTO session_days(session_id,day,completed) VALUES(?,?,1)
                        ON CONFLICT(session_id,day) DO UPDATE SET completed=1''',(session_id,local_day(end)))
            conn.execute('UPDATE sessions SET elapsed=?,status=?,pause_count=?,updated_at=?,ended_at=? WHERE id=?',
                (value,status,pause_count,stamp(now),stamp(end) if status in FINAL_STATES else None,session_id))
            return value
        return self._run(apply,write=True)

    def add_legacy_credit(self,seconds,completed,day=None):
        day=day or local_day(self.clock())
        def apply(conn):
            conn.execute('''INSERT INTO legacy_daily VALUES(?,?,?) ON CONFLICT(day) DO UPDATE
                SET seconds=seconds+excluded.seconds,completed=completed+excluded.completed''',
                (day,max(0,int(seconds)),int(bool(completed))))
        self._run(apply,write=True)

    def summary(self,start_day=None,end_day=None):
        clauses=[];args=[]
        if start_day:clauses.append('day>=?');args.append(start_day)
        if end_day:clauses.append('day<=?');args.append(end_day)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        def read(conn):
            result={'seconds':0,'completed':0,'legacy_seconds':0,'legacy_completed':0,'reminders':0,'corrections':0}
            for table in ('session_days','legacy_daily'):
                row=conn.execute(f'SELECT COALESCE(SUM(seconds),0),COALESCE(SUM(completed),0) FROM {table}'+where,args).fetchone()
                result['seconds']+=float(row[0]);result['completed']+=int(row[1])
                if table=='legacy_daily':result['legacy_seconds']=float(row[0]);result['legacy_completed']=int(row[1])
            start,end=self._utc_range(start_day,end_day)
            conditions=["source!='example'"];event_args=[]
            if start:conditions.append('created_at>=?');event_args.append(start)
            if end:conditions.append('created_at<?');event_args.append(end)
            counts=conn.execute("SELECT COUNT(*),COALESCE(SUM(response='false_positive'),0) FROM reminders WHERE "+' AND '.join(conditions),event_args).fetchone()
            result['reminders']=int(counts[0]);result['corrections']=int(counts[1])
            result['seconds']=int(result['seconds']+1e-6)
            return result
        return self._run(read,{'seconds':0,'completed':0,'legacy_seconds':0,'legacy_completed':0,'reminders':0,'corrections':0})

    @staticmethod
    def _utc_range(start_day,end_day):
        start=stamp(datetime.combine(date.fromisoformat(start_day),datetime.min.time(),LOCAL_ZONE)) if start_day else None
        end=stamp(datetime.combine(date.fromisoformat(end_day)+timedelta(days=1),datetime.min.time(),LOCAL_ZONE)) if end_day else None
        return start,end

    def sessions(self,start_day=None,end_day=None,limit=500):
        start,end=self._utc_range(start_day,end_day)
        def read(conn):
            clauses=[];args=[]
            if start:clauses.append('(s.started_at>=? OR EXISTS(SELECT 1 FROM session_days d WHERE d.session_id=s.id AND d.day>=?))');args.extend([start,start_day])
            if end:clauses.append('s.started_at<?');args.append(end)
            where=' WHERE '+' AND '.join(clauses) if clauses else ''
            rows=conn.execute('''SELECT s.*,
                (SELECT COUNT(*) FROM reminders r WHERE r.session_id=s.id AND source!='example') AS reminder_count,
                (SELECT COUNT(*) FROM reminders r WHERE r.session_id=s.id AND source!='example' AND response='false_positive') AS correction_count
                FROM sessions s'''+where+' ORDER BY started_at DESC LIMIT ?',[*args,limit]).fetchall()
            return [dict(row) for row in rows]
        return self._run(read,[])

    def session(self,session_id):
        return self._run(lambda conn:(dict(row) if (row:=conn.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()) else None))

    def add_reminder(self,kind,text,source='vision',session_id=None,behavior_id=None):
        if kind not in KIND_LABELS or source not in {'vision','example','coach'}:raise ValueError('Unknown reminder type')
        event_id=uuid4().hex
        def apply(conn):
            linked=session_id if source!='example' and session_id and conn.execute('SELECT 1 FROM sessions WHERE id=?',(session_id,)).fetchone() else None
            behavior=conn.execute('SELECT id FROM behavior_events WHERE id=? AND session_id=?',(behavior_id,linked)).fetchone() if behavior_id and linked else None
            conn.execute('INSERT INTO reminders(id,session_id,kind,source,text,created_at,behavior_id) VALUES(?,?,?,?,?,?,?)',
                (event_id,linked,kind,source,str(text)[:2000],stamp(self.clock()),behavior_id if behavior else None))
            return event_id
        return self._run(apply,write=True)

    def reminder(self,event_id):
        return self._run(lambda conn:(dict(row) if (row:=conn.execute('SELECT * FROM reminders WHERE id=?',(event_id,)).fetchone()) else None))

    def respond(self,event_id,response):
        if response not in RESPONSE_LABELS:raise ValueError('Unknown response')
        def apply(conn):
            event=conn.execute('SELECT * FROM reminders WHERE id=?',(event_id,)).fetchone()
            if not event or event['response'] is not None or not response_allowed(event['kind'],response):return False
            changed=conn.execute('UPDATE reminders SET response=?,responded_at=? WHERE id=? AND response IS NULL',
                (response,stamp(self.clock()),event_id)).rowcount==1
            if changed and event['behavior_id'] and response in {'false_positive','research','thinking','paper'}:
                conn.execute('UPDATE behavior_events SET feedback=? WHERE id=?',(response,event['behavior_id']))
            return changed
        return self._run(apply,False,write=True)

    def _reminders_query(self,conn,start_day=None,end_day=None,source=None,session_id=None,limit=1000):
        start,end=self._utc_range(start_day,end_day);clauses=[];args=[]
        for expression,value in [('r.created_at>=?',start),('r.created_at<?',end),('r.source=?',source),('r.session_id=?',session_id)]:
            if value is not None:clauses.append(expression);args.append(value)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        return [dict(row) for row in conn.execute('''SELECT r.*,s.task FROM reminders r
            LEFT JOIN sessions s ON s.id=r.session_id'''+where+' ORDER BY r.created_at DESC LIMIT ?',[*args,limit])]

    def reminders(self,start_day=None,end_day=None,session_id=None):
        return self._run(lambda conn:self._reminders_query(conn,start_day,end_day,session_id=session_id),[])

    def reminder_counts(self,session_id=None,day=None):
        clauses=["source!='example'"];args=[]
        if session_id:clauses.append('session_id=?');args.append(session_id)
        if day:
            start,end=self._utc_range(day,day);clauses.extend(['created_at>=?','created_at<?']);args.extend([start,end])
        def read(c):
            row=c.execute("SELECT COUNT(*),COALESCE(SUM(response='false_positive'),0) FROM reminders WHERE "+' AND '.join(clauses),args).fetchone()
            return {'count':int(row[0]),'corrected':int(row[1])}
        return self._run(read,{'count':0,'corrected':0})

    def upsert_behavior(self,session_id,event):
        """Persist measured intervals, never raw frames or landmark vectors."""
        if not isinstance(event,dict) or event.get('type') not in BEHAVIOR_LABELS:return None
        try:
            identifier=str(event['id']);start=parse(event['started_at']);end=parse(event['ended_at'])
            seconds=float(event['duration'])
            if not identifier or start.tzinfo is None or end.tzinfo is None or end<start or not math.isfinite(seconds) or seconds<0:return None
            seconds=min(seconds,max(0.,(end-start).total_seconds()))
            evidence=json.dumps(event.get('evidence',{}),ensure_ascii=False,allow_nan=False)
            if len(evidence)>8000:return None
        except (KeyError,TypeError,ValueError,OverflowError):return None
        status=event.get('status','closed')
        if status not in {'ongoing','closed'}:return None
        def apply(conn):
            session=conn.execute('SELECT * FROM sessions WHERE id=?',(session_id,)).fetchone()
            if not session or session['kind']!='focus':return None
            prior=conn.execute('SELECT * FROM behavior_events WHERE id=?',(identifier,)).fetchone()
            if prior and (prior['session_id']!=session_id or prior['kind']!=event['type']):return None
            if prior and prior['started_at']!=stamp(start):return None
            # Finalized intervals cannot be reopened by delayed IPC updates.
            if prior and (parse(prior['ended_at'])>end or seconds<float(prior['duration']) or (prior['status']=='closed' and status=='ongoing')):return identifier
            conn.execute('''INSERT INTO behavior_events(id,session_id,kind,started_at,ended_at,duration,evidence,status)
                VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET ended_at=excluded.ended_at,
                duration=excluded.duration,evidence=excluded.evidence,status=excluded.status''',
                (identifier,session_id,event['type'],stamp(start),stamp(end),seconds,evidence,status))
            return identifier
        return self._run(apply,write=True)

    def behaviors(self,session_id=None,start_day=None,end_day=None):
        start,end=self._utc_range(start_day,end_day);clauses=[];args=[]
        for expression,value in [('session_id=?',session_id),('ended_at>?',start),('started_at<?',end)]:
            if value is not None:clauses.append(expression);args.append(value)
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        def read(conn):
            result=[]
            for row in conn.execute('SELECT * FROM behavior_events'+where+' ORDER BY started_at,id',args):
                item=dict(row)
                try:item['evidence']=json.loads(item['evidence'])
                except (TypeError,ValueError):item['evidence']={}
                result.append(item)
            return result
        return self._run(read,[])

    def correct_behavior(self,identifier,feedback):
        if feedback not in {None,'false_positive','research','thinking','paper'}:return False
        return self._run(lambda c:c.execute('UPDATE behavior_events SET feedback=? WHERE id=?',
            (feedback,identifier)).rowcount==1,False,write=True)

    def session_day_seconds(self,session_id,day):
        return self._run(lambda c:float(r[0]) if (r:=c.execute('SELECT seconds FROM session_days WHERE session_id=? AND day=?',
            (session_id,day)).fetchone()) else 0.,0.)

    def save_note(self,scope,target,note):
        if scope not in {'session','day'}:raise ValueError('Unknown summary scope')
        return self._run(lambda c:c.execute('''INSERT INTO summary_notes VALUES(?,?,?) ON CONFLICT(scope,target)
            DO UPDATE SET note=excluded.note''',(scope,str(target),str(note).strip()[:2000])).rowcount==1,False,write=True)

    def note(self,scope,target):
        return self._run(lambda c:r[0] if (r:=c.execute('SELECT note FROM summary_notes WHERE scope=? AND target=?',
            (scope,str(target))).fetchone()) else '','')

    def save_learning_summary(self,scope,target,facts,local_text):
        payload=json.dumps(facts,ensure_ascii=False,sort_keys=True,allow_nan=False)
        digest=hashlib.sha256(payload.encode('utf-8')).hexdigest()
        def apply(conn):
            prior=conn.execute('SELECT facts_hash FROM learning_summaries WHERE scope=? AND target=?',(scope,target)).fetchone()
            if prior and prior[0]==digest:return digest
            conn.execute('''INSERT INTO learning_summaries(scope,target,facts,facts_hash,local_text,updated_at)
              VALUES(?,?,?,?,?,?) ON CONFLICT(scope,target) DO UPDATE SET facts=excluded.facts,
              facts_hash=excluded.facts_hash,local_text=excluded.local_text,
              ai_status=CASE WHEN learning_summaries.ai_text!='' THEN 'stale' ELSE 'local' END,
              ai_error='',updated_at=excluded.updated_at''',(scope,target,payload,digest,local_text,stamp(self.clock())))
            return digest
        return self._run(apply,write=True)

    def learning_summary(self,scope,target):
        def read(conn):
            row=conn.execute('SELECT * FROM learning_summaries WHERE scope=? AND target=?',(scope,str(target))).fetchone()
            if row:
                result=dict(row);result['facts']=json.loads(result['facts']);return result
        return self._run(read)

    def save_ai_summary(self,scope,target,facts_hash,text='',status='complete',error='',model=''):
        return self._run(lambda c:c.execute('''UPDATE learning_summaries SET ai_text=?,ai_status=?,ai_error=?,model=?,updated_at=?
            WHERE scope=? AND target=? AND facts_hash=?''',(text,status,str(error)[:500],model,stamp(self.clock()),
                scope,str(target),facts_hash)).rowcount==1,False,write=True)
