import unittest
from study_pet.focus import FocusSession, Status


class FocusTests(unittest.TestCase):
    def setUp(self):
        self.now=1000.0
        self.s=FocusSession(lambda:self.now)

    def test_delayed_tick_does_not_slow_countdown(self):
        self.s.start(1)
        self.now+=19.4
        self.assertEqual(self.s.display_seconds,41)
        self.now+=41
        self.assertTrue(self.s.tick())
        self.assertEqual(self.s.status,Status.COMPLETED)
        self.assertFalse(self.s.tick())

    def test_paused_time_is_not_counted(self):
        self.s.start(1)
        self.now+=10
        self.s.pause()
        self.now+=300
        self.assertEqual(self.s.remaining,50)
        self.s.resume()
        self.now+=20
        self.assertEqual(self.s.remaining,30)
        self.assertEqual(self.s.elapsed,30)

    def test_expired_session_cannot_be_paused_and_resumed(self):
        self.s.start(1)
        self.now+=61
        self.s.pause()
        self.s.resume()
        self.assertEqual(self.s.status,Status.COMPLETED)
        self.assertEqual(self.s.remaining,0)

    def test_restart_after_completion_clears_old_deadline(self):
        self.s.start(1,"旧任务")
        self.now+=60
        self.s.tick()
        self.s.start(25,"新任务")
        self.assertEqual(self.s.task,"新任务")
        self.assertEqual(self.s.remaining,1500)
        self.assertEqual(self.s.progress,0)

    def test_reset_does_not_continue_time(self):
        self.s.start(1)
        self.now+=10
        self.s.reset()
        self.now+=80
        self.assertEqual(self.s.status,Status.IDLE)
        self.assertFalse(self.s.tick())
        self.assertEqual(self.s.elapsed,0)

    def test_invalid_duration(self):
        for minutes in [0,-1,121]:
            with self.assertRaises(ValueError):self.s.start(minutes)


if __name__=="__main__":unittest.main()
