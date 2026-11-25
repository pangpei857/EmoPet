from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from study_pet.support_memory import SupportMemory


class SupportMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='pet-support-memory-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.now = datetime(2026, 11, 19, 10, tzinfo=timezone.utc)
        self.memory = SupportMemory(self.directory, clock=lambda: self.now)

    def record(self, session, response='thinking', *, kind='care', mode='computer', reminder=None):
        reminder = reminder or uuid4().hex
        return self.memory.record_feedback(reminder, session, kind, mode, response)

    def test_opt_in_is_local_and_persists_across_instances(self):
        session = uuid4().hex
        self.assertFalse(self.memory.enabled)
        self.assertFalse(self.record(session))
        self.assertFalse(self.memory.path.exists())
        self.assertTrue(self.memory.set_enabled(True))
        self.assertTrue(self.record(session, 'talk', kind='sigh'))
        other = SupportMemory(self.directory, clock=lambda: self.now)
        self.assertTrue(other.enabled)
        self.assertIn('声音关怀', other.prompt_context('computer'))
        self.assertNotIn(session, other.prompt_context('computer'))
        self.assertTrue(other.set_enabled(False))
        self.assertFalse(self.record(session))
        self.assertFalse(self.memory.enabled)
        self.assertEqual(self.memory.preferences('computer'), {})
        self.assertEqual(self.memory.prompt_context('computer'), '')
        self.assertEqual(len(self.memory.recent()), 1)
        self.assertTrue(self.memory.clear())
        self.assertEqual(other.recent(), [])
        self.assertFalse(other.enabled)

    def test_do_not_learn_preferences_from_duplicate_or_one_round(self):
        self.memory.set_enabled(True)
        first_session, second_session, reminder = (uuid4().hex for _ in range(3))
        for _ in range(3):
            self.assertTrue(self.record(first_session, reminder=reminder))
        self.assertEqual(self.memory.preferences('computer')['care'].feedback_count, 1)
        self.record(first_session)
        self.record(first_session, response='snooze')
        self.assertFalse(self.memory.preferences('computer')['care'].reduce_interruptions)
        self.record(second_session, mode='paper')
        self.assertFalse(self.memory.preferences('computer')['care'].reduce_interruptions)
        self.record(second_session, response='false_positive')
        preference = self.memory.preferences('computer')['care']
        self.assertTrue(preference.reduce_interruptions)
        self.assertEqual(preference.session_count, 2)
        self.assertEqual(preference.declined_count, 3)
        self.assertEqual(preference.delayed_count, 1)
        self.assertIn('宜减少主动打扰', self.memory.prompt_context('computer'))

    def test_correction_and_separate_outcome_by_id(self):
        self.memory.set_enabled(True)
        session, reminder = (uuid4().hex for _ in range(2))
        self.assertTrue(self.record(session, 'rest_now', kind='break_due', reminder=reminder))
        original = self.memory.recent()[0]
        self.assertIsNone(original.outcome)
        self.now += timedelta(minutes=5)
        self.assertFalse(self.memory.record_outcome(reminder, 'rested', expected_response='help'))
        self.assertTrue(self.memory.record_outcome(reminder, 'rested', expected_response='rest_now'))
        self.assertTrue(self.record(session, 'rest_now', kind='break_due', reminder=reminder))
        self.assertEqual(self.memory.recent()[0].outcome, 'rested')
        self.now += timedelta(minutes=1)
        self.assertTrue(self.record(session, 'later', kind='break_due', reminder=reminder))
        revised, = self.memory.recent()
        self.assertEqual(revised.response, 'later')
        self.assertEqual(revised.observed_at, original.observed_at)
        self.assertGreater(revised.updated_at, original.updated_at)
        self.assertIsNone(revised.outcome)
        self.assertFalse(self.memory.record_outcome(reminder, 'rested', expected_response='rest_now'))
        self.assertTrue(self.memory.forget(reminder))
        self.assertEqual(self.memory.recent(), [])

    def test_expired_or_unstructured_inputs_do_not_turn_into_memory(self):
        self.memory.set_enabled(True)
        session, reminder = (uuid4().hex for _ in range(2))
        self.assertTrue(self.record(session, reminder=reminder))
        self.assertFalse(self.record('arbitrary task text'))
        self.assertFalse(self.record(session, 'arbitrary feedback text'))
        self.assertFalse(self.record(session, 'talk', kind='phone'))
        self.now += timedelta(days=31)
        self.assertEqual(self.memory.preferences('computer'), {})
        self.assertEqual(len(self.memory.recent()), 1)
        self.now += timedelta(days=60)
        self.assertEqual(self.memory.recent(), [])
        self.assertFalse(self.memory.record_outcome(reminder, 'helpful'))
        self.assertFalse(self.memory.record_feedback(uuid4().hex, session, 'care', 'computer', 'help',
                                                    observed_at=self.now - timedelta(days=91)))

    def test_parallel_writes_of_one_reminder_do_not_duplicate_it(self):
        self.memory.set_enabled(True)
        session, reminder = (uuid4().hex for _ in range(2))

        def write_response(response):
            memory = SupportMemory(self.directory, clock=lambda: self.now)
            return memory.record_feedback(reminder, session, 'care', 'mixed', response)

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertTrue(all(pool.map(write_response, ['help', 'talk', 'thinking', 'snooze'])))
        self.assertEqual(len(self.memory.recent()), 1)


if __name__ == '__main__':
    unittest.main()
