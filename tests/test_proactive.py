import math
import unittest

from study_pet.perception import FeedbackEvent
from study_pet.proactive import ProactiveCoach, ProactiveSettings


PHONE = FeedbackEvent('phone', '手机好像在手边。', 'remind')
CARE = FeedbackEvent('care', '需要我帮忙吗？', 'care')


class ProactiveTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.0
        self.coach = ProactiveCoach({'interval_minutes': 1, 'rest_minutes': 1}, lambda: self.now)

    def advance(self, seconds, *, focus=False, rest=False, **gates):
        events = []
        for _ in range(seconds):
            self.now += 1
            event = self.coach.update(focus_active=focus, rest_active=rest, **gates)
            if event:
                events.append(event)
        return events

    def test_study_accumulates_across_rounds_and_short_pause(self):
        self.coach.update(focus_active=True)
        self.assertEqual(self.advance(35, focus=True), [])
        self.coach.update(focus_active=False)
        self.advance(10)
        self.coach.update(focus_active=True)
        events = self.advance(25, focus=True)
        self.assertEqual([event.kind for event in events], ['break_due'])
        self.assertEqual(self.coach.streak_seconds, 60)
        self.assertEqual(self.advance(240, focus=True), [])

    def test_default_threshold_is_one_hour(self):
        self.coach.configure(interval_minutes=60)
        self.coach.update(focus_active=True)
        self.assertEqual(self.advance(3599, focus=True), [])
        self.assertEqual([event.kind for event in self.advance(1, focus=True)], ['break_due'])

    def test_only_continuous_explicit_rest_resets_streak(self):
        self.coach.update(focus_active=True)
        self.advance(30, focus=True)
        self.coach.update(focus_active=False, rest_active=True)
        self.advance(40, rest=True)
        self.assertEqual(self.coach.streak_seconds, 30)
        self.coach.update(focus_active=False)
        self.advance(10)
        self.coach.update(focus_active=False, rest_active=True)
        self.advance(59, rest=True)
        self.assertEqual(self.coach.streak_seconds, 30)
        self.advance(1, rest=True)
        self.assertEqual(self.coach.streak_seconds, 0)
        self.coach.update(focus_active=True)
        self.advance(1, focus=True)
        self.assertEqual(self.coach.streak_seconds, 1)

    def test_last_rest_interval_can_complete_at_state_transition(self):
        self.coach.update(focus_active=True)
        self.advance(30, focus=True)
        self.coach.update(focus_active=False, rest_active=True)
        self.advance(59, rest=True)
        self.now += 1
        self.coach.update(focus_active=False)
        self.assertEqual(self.coach.streak_seconds, 0)

    def test_large_update_gaps_are_neither_study_nor_rest(self):
        self.coach.update(focus_active=True)
        self.advance(10, focus=True)
        self.now += 3600
        self.assertIsNone(self.coach.update(focus_active=True))
        self.assertEqual(self.coach.streak_seconds, 10)
        self.coach.update(focus_active=False, rest_active=True)
        self.advance(30, rest=True)
        self.now += 3600
        self.coach.update(focus_active=False, rest_active=True)
        self.assertEqual(self.coach.rest_seconds, 0)
        self.advance(31, rest=True)
        self.assertEqual(self.coach.streak_seconds, 10)

    def test_hidden_snoozed_and_disabled_reminders_do_not_consume_due_event(self):
        self.coach.update(focus_active=True)
        self.advance(60, focus=True, visible=False)
        self.assertIsNone(self.coach.update(focus_active=True, snoozed=True))
        self.assertIsNone(self.coach.update(focus_active=True, enabled=False))
        event = self.coach.update(focus_active=True)
        self.assertEqual(event.kind, 'break_due')

    def test_defer_reopens_one_reminder_at_requested_time(self):
        self.coach.update(focus_active=True)
        self.advance(60, focus=True)
        self.coach.defer(600)
        self.assertEqual(self.advance(599, focus=True), [])
        self.assertEqual([e.kind for e in self.advance(1, focus=True)], ['break_due'])
        self.assertEqual(self.advance(300, focus=True), [])

    def test_global_and_kind_cooldowns_are_independent(self):
        self.assertEqual(self.coach.choose(PHONE), PHONE)
        self.now += 89
        self.assertIsNone(self.coach.choose(CARE))
        self.now += 1
        self.assertEqual(self.coach.choose(CARE), CARE)
        self.now += 89
        self.assertIsNone(self.coach.choose(PHONE))
        self.now += 1
        self.assertEqual(self.coach.choose(PHONE), PHONE)

    def test_due_break_has_priority_over_current_visual_candidate(self):
        self.coach.update(focus_active=True)
        self.advance(60, focus=True, visible=False)
        event = self.coach.choose(PHONE)
        self.assertEqual(event.kind, 'break_due')
        self.assertIsNone(self.coach.choose(PHONE))

    def test_global_cooldown_delays_but_does_not_discard_due_break(self):
        self.coach.update(focus_active=True)
        self.advance(59, focus=True)
        self.assertEqual(self.coach.choose(PHONE), PHONE)
        self.assertEqual(self.advance(1, focus=True), [])
        self.assertEqual([e.kind for e in self.advance(89, focus=True)], ['break_due'])

    def test_blocked_visual_candidates_are_not_queued(self):
        self.coach.choose(PHONE)
        self.assertIsNone(self.coach.choose(CARE))
        self.now += 100
        self.assertIsNone(self.coach.update(focus_active=False))

    def test_invalid_clock_does_not_create_duration_or_suppress_future_tracking(self):
        self.coach.update(focus_active=True)
        self.advance(20, focus=True)
        self.assertIsNone(self.coach.update(focus_active=True, now=math.nan))
        self.assertIsNone(self.coach.choose(PHONE, now=math.inf))
        self.coach.update(focus_active=True)
        self.advance(1, focus=True)
        self.assertEqual(self.coach.streak_seconds, 21)

    def test_preferences_validate_and_never_persist_clock_state(self):
        settings = ProactiveSettings.from_dict({'interval_minutes': -10, 'rest_minutes': 999,
            'global_cooldown_seconds': math.nan, 'enabled': 'yes', 'kind_cooldown_seconds': True})
        self.assertEqual(settings.interval_minutes, 1)
        self.assertEqual(settings.rest_minutes, 30)
        self.assertEqual(settings.global_cooldown_seconds, 90)
        self.assertEqual(settings.kind_cooldown_seconds, 180)
        self.assertTrue(settings.enabled)
        self.coach.configure(interval_minutes=45, enabled=False)
        self.assertEqual(self.coach.as_dict()['interval_minutes'], 45)
        self.assertFalse(self.coach.as_dict()['enabled'])
        self.assertNotIn('streak_seconds', self.coach.as_dict())


if __name__ == '__main__':
    unittest.main()
