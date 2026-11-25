"""Opt-in local memory for explicit responses to learning support."""

from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
import re
import sqlite3

from .history import KIND_LABELS, response_allowed, utc_now


_ID = re.compile(r'[a-fA-F0-9]{32}\Z')
_MODES = {'computer': '电脑学习', 'paper': '纸质学习', 'mixed': '混合学习', 'unknown': '学习'}
_EXTRA_KINDS = {'sigh': '声音关怀'}
_EXTRA_RESPONSES = {'helpful', 'unhelpful', 'no_need'}
_OUTCOMES = {'helpful', 'unhelpful', 'resumed', 'rested'}
_DECLINED = {'research', 'thinking', 'paper', 'false_positive', 'dismiss', 'no_need', 'unhelpful'}
_REQUESTED = {'help', 'talk', 'rest_now', 'helpful'}
_DELAYED = {'snooze', 'later'}
_ACTIVE_DAYS = 30
_RETENTION_DAYS = 90
_ROW_LIMIT = 2000


@dataclass(frozen=True)
class SupportRecord:
    reminder_id: str
    session_id: str
    kind: str
    mode: str
    response: str
    observed_at: datetime
    updated_at: datetime
    outcome: str | None


@dataclass(frozen=True)
class SupportPreference:
    reduce_interruptions: bool
    feedback_count: int
    session_count: int
    declined_count: int
    requested_count: int
    delayed_count: int


class SupportMemory:
    """Keep a bounded, separate history of category codes and explicit feedback.

    Reads never import existing learning or chat records. App callers decide
    which reminder supplied the response and when to show or share the summary.
    """

    def __init__(self, directory, clock=utc_now):
        self.path = Path(directory) / 'support_memory.sqlite3'
        self.clock = clock
        self.error = ''

    @staticmethod
    def _schema(conn):
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS settings(
                id INTEGER PRIMARY KEY CHECK (id = 1),
                enabled INTEGER NOT NULL CHECK (enabled IN (0, 1))
            );
            CREATE TABLE IF NOT EXISTS feedback(
                reminder_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                mode TEXT NOT NULL,
                response TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                outcome TEXT
            );
            CREATE INDEX IF NOT EXISTS feedback_time ON feedback(observed_at, reminder_id);
        ''')

    def _run(self, operation, default, *, write=False, create=False):
        try:
            if not create and not self.path.is_file():
                self.error = ''
                return default
            if create:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path, timeout=0.7)) as conn:
                conn.row_factory = sqlite3.Row
                if write:
                    conn.execute('PRAGMA secure_delete=ON')
                if create:
                    self._schema(conn)
                with conn:
                    conn.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
                    result = operation(conn)
            self.error = ''
            return result
        except (OSError, sqlite3.Error):
            logging.exception('Could not read or write local support memory')
            self.error = '陪伴记忆暂时无法读写，请检查本地应用数据目录。'
            return default

    @staticmethod
    def _enabled(conn):
        row = conn.execute('SELECT enabled FROM settings WHERE id = 1').fetchone()
        return bool(row and row['enabled'])

    @property
    def enabled(self):
        return self._run(self._enabled, False)

    def set_enabled(self, enabled):
        def change(conn):
            conn.execute('''INSERT INTO settings(id, enabled) VALUES (1, ?)
                            ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled''', (int(bool(enabled)),))
            self._prune(conn, self.clock())
            return True

        return self._run(change, not enabled, write=True, create=bool(enabled))

    @staticmethod
    def _id_ok(value):
        return isinstance(value, str) and bool(_ID.fullmatch(value))

    @staticmethod
    def _stamp(value):
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError('Support memory timestamps must include a timezone')
        return value.astimezone(timezone.utc).isoformat(timespec='microseconds')

    @classmethod
    def _prune(cls, conn, now):
        conn.execute('DELETE FROM feedback WHERE observed_at < ?', (cls._stamp(now - timedelta(days=_RETENTION_DAYS)),))
        conn.execute('''DELETE FROM feedback WHERE reminder_id IN (
            SELECT reminder_id FROM feedback ORDER BY observed_at DESC, reminder_id DESC LIMIT -1 OFFSET ?
        )''', (_ROW_LIMIT,))

    @staticmethod
    def _valid_response(kind, response):
        if kind not in KIND_LABELS and kind not in _EXTRA_KINDS:
            return False
        if response in _EXTRA_RESPONSES:
            return True
        if response == 'talk':
            return kind in {'care', 'sigh'}
        return response_allowed('care' if kind == 'sigh' else kind, response)

    def record_feedback(self, reminder_id, session_id, kind, mode, response, *, observed_at=None, outcome=None):
        """Save a response by reminder ID. Later edits replace response and outcome."""
        if not self._id_ok(reminder_id) or not self._id_ok(session_id):
            return False
        if not all(isinstance(value, str) for value in (kind, mode, response)):
            return False
        if mode not in _MODES or not self._valid_response(kind, response):
            return False
        if outcome is not None and (not isinstance(outcome, str) or outcome not in _OUTCOMES):
            return False
        now = self.clock()
        observed_at = now if observed_at is None else observed_at
        try:
            observed_stamp, updated_stamp = self._stamp(observed_at), self._stamp(now)
        except (TypeError, ValueError, OverflowError):
            return False
        if not now - timedelta(days=_RETENTION_DAYS) <= observed_at <= now + timedelta(minutes=5):
            return False

        def record(conn):
            if not self._enabled(conn):
                return False
            cursor = conn.execute('''INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(reminder_id) DO UPDATE SET response = excluded.response,
                    updated_at = excluded.updated_at, outcome = CASE
                        WHEN excluded.outcome IS NOT NULL THEN excluded.outcome
                        WHEN feedback.response = excluded.response THEN feedback.outcome
                        ELSE NULL END
                WHERE feedback.session_id = excluded.session_id AND feedback.kind = excluded.kind
                    AND excluded.updated_at >= feedback.updated_at''',
                (reminder_id.lower(), session_id.lower(), kind, mode, response, observed_stamp, updated_stamp, outcome))
            self._prune(conn, now)
            return cursor.rowcount == 1

        return self._run(record, False, write=True)

    def record_outcome(self, reminder_id, outcome, *, expected_response=None):
        """Attach or clear an observation without changing the original feedback."""
        if not self._id_ok(reminder_id):
            return False
        if outcome is not None and (not isinstance(outcome, str) or outcome not in _OUTCOMES):
            return False
        now = self.clock()
        updated = self._stamp(now)
        cutoff = self._stamp(now - timedelta(days=_RETENTION_DAYS))

        def record(conn):
            if not self._enabled(conn):
                return False
            cursor = conn.execute('''UPDATE feedback SET outcome = ?, updated_at = ?
                WHERE reminder_id = ? AND observed_at >= ? AND updated_at <= ?
                    AND (? IS NULL OR response = ?)''',
                (outcome, updated, reminder_id.lower(), cutoff, updated, expected_response, expected_response))
            return cursor.rowcount == 1

        return self._run(record, False, write=True)

    def forget(self, reminder_id):
        if not self._id_ok(reminder_id):
            return False
        return self._run(lambda conn: conn.execute('DELETE FROM feedback WHERE reminder_id = ?',
                                                     (reminder_id.lower(),)).rowcount == 1,
                         False, write=True)

    def clear(self):
        def remove(conn):
            conn.execute('DELETE FROM feedback')
            return True

        return self._run(remove, True, write=True)

    @staticmethod
    def _read_record(row):
        return SupportRecord(row['reminder_id'], row['session_id'], row['kind'], row['mode'], row['response'],
                             datetime.fromisoformat(row['observed_at']), datetime.fromisoformat(row['updated_at']),
                             row['outcome'])

    def recent(self, limit=30):
        """Return a small reviewable view, including while memory is disabled."""
        limit = min(100, max(0, int(limit)))
        cutoff = self._stamp(self.clock() - timedelta(days=_RETENTION_DAYS))

        def read(conn):
            rows = conn.execute('''SELECT * FROM feedback WHERE observed_at >= ?
                                  ORDER BY observed_at DESC, reminder_id DESC LIMIT ?''', (cutoff, limit))
            return [self._read_record(row) for row in rows]

        return self._run(read, [])

    def preferences(self, mode='unknown'):
        """Summarize only recent feedback from the exact learning mode."""
        if mode not in _MODES:
            return {}
        cutoff = self._stamp(self.clock() - timedelta(days=_ACTIVE_DAYS))

        def read(conn):
            if not self._enabled(conn):
                return {}
            rows_by_kind = defaultdict(list)
            rows = conn.execute('''SELECT session_id, kind, response FROM feedback
                                  WHERE mode = ? AND observed_at >= ?''', (mode, cutoff))
            for row in rows:
                rows_by_kind[row['kind']].append(row)
            result = {}
            for kind, rows in rows_by_kind.items():
                sessions = {row['session_id'] for row in rows}
                declined = sum(row['response'] in _DECLINED for row in rows)
                requested = sum(row['response'] in _REQUESTED for row in rows)
                delayed = sum(row['response'] in _DELAYED for row in rows)
                quiet_sessions = {row['session_id'] for row in rows if row['response'] in _DECLINED | _DELAYED}
                quiet_choices = declined + delayed
                reduce = len(quiet_sessions) >= 2 and quiet_choices >= 3 and quiet_choices * 3 >= len(rows) * 2
                result[kind] = SupportPreference(reduce, len(rows), len(sessions), declined, requested, delayed)
            return result

        return self._run(read, {})

    def prompt_context(self, mode='unknown'):
        """Make a fixed-format excerpt for an explicit per-message share choice."""
        preferences = self.preferences(mode)
        if not preferences:
            return ''
        lines = [f'近 {_ACTIVE_DAYS} 天「{_MODES[mode]}」中的用户反馈。只是此前的选择，请以当前意愿为准。']
        for kind, label in (KIND_LABELS | _EXTRA_KINDS).items():
            preference = preferences.get(kind)
            if preference is None:
                continue
            report = (f'{label}（{preference.session_count} 轮学习）：不需要或校正 '
                      f'{preference.declined_count} 次，延后 {preference.delayed_count} 次，'
                      f'接受或请求帮助 {preference.requested_count} 次。')
            if preference.reduce_interruptions:
                report += '类似情境宜减少主动打扰。'
            lines.append(report)
        return '\n'.join(lines)
