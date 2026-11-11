"""Local conversations and editable learning plans; no API credentials."""
from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3
from uuid import uuid4
from .history import stamp,utc_now
from .chat_core import parse_plan


class ChatStore:
    def __init__(self,directory):
        self.path=Path(directory)/'chat_history.sqlite3';self.error=''
        self._run(lambda c:c.executescript('''
          CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS turns(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),
            user_text TEXT NOT NULL,answer TEXT NOT NULL DEFAULT '',status TEXT NOT NULL,purpose TEXT NOT NULL,
            model TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,error TEXT NOT NULL DEFAULT '');
          CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id,created_at);
          CREATE TABLE IF NOT EXISTS plans(turn_id TEXT PRIMARY KEY REFERENCES turns(id),data TEXT NOT NULL);
        '''))
        self._run(lambda c:c.execute("UPDATE turns SET status='stopped',error='上次生成中断' WHERE status='pending'"))

    def _run(self,operation,default=None):
        try:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.path,timeout=3)) as conn:
                conn.row_factory=sqlite3.Row;conn.execute('PRAGMA foreign_keys=ON')
                with conn:result=operation(conn)
            self.error='';return result
        except (sqlite3.Error,OSError):
            logging.exception('Could not save local chat history')
            self.error='对话记录暂时无法读写，请检查本地应用数据目录。';return default

    def new_conversation(self,title):
        identifier=uuid4().hex;now=stamp(utc_now())
        def apply(conn):
            conn.execute('INSERT INTO conversations VALUES(?,?,?,?)',(identifier,' '.join(str(title).split())[:28] or '新的学习对话',now,now));return identifier
        return self._run(apply)

    def conversations(self):
        return self._run(lambda c:[dict(row) for row in c.execute('SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100')],[])

    def turns(self,conversation_id,limit=300):
        def read(conn):
            rows=conn.execute('SELECT * FROM turns WHERE conversation_id=? ORDER BY created_at DESC,rowid DESC LIMIT ?',(conversation_id,limit)).fetchall()
            return [dict(row) for row in reversed(rows)]
        return self._run(read,[])

    def start_turn(self,conversation_id,text,purpose,model):
        identifier=uuid4().hex;now=stamp(utc_now())
        def apply(conn):
            conn.execute('INSERT INTO turns(id,conversation_id,user_text,status,purpose,model,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)',
                (identifier,conversation_id,text,'pending',purpose,model,now,now))
            conn.execute('UPDATE conversations SET updated_at=? WHERE id=?',(now,conversation_id));return identifier
        return self._run(apply)

    def update_turn(self,identifier,answer,status,error=''):
        now=stamp(utc_now())
        def apply(conn):
            conn.execute('UPDATE turns SET answer=?,status=?,error=?,updated_at=? WHERE id=?',(answer,status,error[:500],now,identifier))
            conn.execute('UPDATE conversations SET updated_at=? WHERE id=(SELECT conversation_id FROM turns WHERE id=?)',(now,identifier))
            return True
        return self._run(apply,False)

    def save_plan(self,turn_id,plan):
        plan=parse_plan(json.dumps(plan,ensure_ascii=False))
        def apply(conn):
            conn.execute('INSERT INTO plans VALUES(?,?) ON CONFLICT(turn_id) DO UPDATE SET data=excluded.data',
                (turn_id,json.dumps(plan,ensure_ascii=False)));return True
        return self._run(apply,False)

    def latest_plan(self,conversation_id):
        def read(conn):
            row=conn.execute('''SELECT p.turn_id,p.data FROM plans p JOIN turns t ON t.id=p.turn_id
                WHERE t.conversation_id=? ORDER BY t.created_at DESC,t.rowid DESC LIMIT 1''',(conversation_id,)).fetchone()
            if row:return row['turn_id'],json.loads(row['data'])
        return self._run(read)
