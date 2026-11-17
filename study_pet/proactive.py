"""Local proactive coaching with observed time and bounded interruptions.

The clock measures timer activity, not a student's attention.  A missing camera
or a short pause never proves that a restorative break happened.
"""
from dataclasses import asdict, dataclass
import math
import time

from .perception import FeedbackEvent


@dataclass
class ProactiveSettings:
    enabled: bool = True
    interval_minutes: int = 60
    rest_minutes: int = 5
    global_cooldown_seconds: int = 90
    kind_cooldown_seconds: int = 180

    @classmethod
    def from_dict(cls, values):
        values = values if isinstance(values, dict) else {}
        result = cls()
        if isinstance(values.get('enabled'), bool):
            result.enabled = values['enabled']
        for key, lower, upper in (
            ('interval_minutes', 1, 240), ('rest_minutes', 1, 30),
            ('global_cooldown_seconds', 0, 600),
            ('kind_cooldown_seconds', 0, 3600),
        ):
            value = values.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
                setattr(result, key, max(lower, min(upper, int(value))))
        return result

    def as_dict(self):
        return asdict(self)


class ProactiveCoach:
    """Track study across rounds and choose one current reminder at a time.

    ``update`` should run on the UI timer and at activity transitions.  Only
    intervals up to MAX_GAP_SECONDS are accounted for; process suspension is
    not evidence of either studying or taking a break.  Reminder gates affect
    delivery only, so hiding the pet never changes the recorded study streak.

    ``choose`` accepts a fresh visual candidate and gives a due break reminder
    priority.  No visual queue is kept: a candidate blocked now must be observed
    again before it can be delivered later.
    """
    MAX_GAP_SECONDS = 5.0

    def __init__(self, settings=None, clock=time.monotonic):
        self.settings = ProactiveSettings.from_dict(
            settings.as_dict() if isinstance(settings, ProactiveSettings) else settings)
        self.clock = clock
        self.streak_seconds = 0.0
        self.rest_seconds = 0.0
        self._last_update = None
        self._focus_active = False
        self._rest_active = False
        self._rest_verified = False
        self._last_global = -math.inf
        self._last_kind = {}
        self._deferred_until = -math.inf
        self._break_notified = False

    def as_dict(self):
        """Persist preferences, never process-specific monotonic timestamps."""
        return self.settings.as_dict()

    def configure(self, **values):
        previous_interval = self.settings.interval_minutes
        self.settings = ProactiveSettings.from_dict({**self.as_dict(), **values})
        if self.settings.interval_minutes != previous_interval:
            self._break_notified = False
        return self.as_dict()

    def _now(self, now):
        value = self.clock() if now is None else now
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            return None
        return float(value)

    def _clear_streak(self):
        self.streak_seconds = 0.0
        self._deferred_until = -math.inf
        self._break_notified = False
        self._last_kind.pop('break_due', None)

    def reset_after_rest(self):
        """Explicitly acknowledge a completed break, e.g. its final UI tick."""
        self._clear_streak()
        self.rest_seconds = 0.0
        self._rest_verified = True

    def defer(self, seconds=600, now=None):
        value = self._now(now)
        if value is None or not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not math.isfinite(seconds):
            return False
        self._deferred_until = value + max(0.0, min(float(seconds), 24 * 3600.0))
        self._break_notified = False
        return True

    def _deliverable(self, kind, now):
        return (now - self._last_global + 1e-6 >= self.settings.global_cooldown_seconds
                and now - self._last_kind.get(kind, -math.inf) + 1e-6 >= self.settings.kind_cooldown_seconds)

    def _break_ready(self, now):
        return (self._focus_active and not self._break_notified
                and self.streak_seconds + 1e-6 >= self.settings.interval_minutes * 60
                and now >= self._deferred_until)

    def _break_event(self):
        minutes = max(1, int(self.streak_seconds // 60))
        return FeedbackEvent(
            'break_due',
            f'已经累计计时学习约 {minutes} 分钟了。\n要不要休息 {self.settings.rest_minutes} 分钟，再回来继续？',
            'care',
        )

    def _record_delivery(self, event, now):
        self._last_global = now
        self._last_kind[event.kind] = now
        if event.kind == 'break_due':
            self._break_notified = True
        return event

    def choose(self, event, *, now=None, enabled=True, visible=True, snoozed=False):
        value = self._now(now)
        if (value is None or not self.settings.enabled or not enabled
                or not visible or snoozed):
            return None
        # Re-evaluate a due break rather than retaining stale camera evidence.
        if self._break_ready(value) and self._deliverable('break_due', value):
            return self._record_delivery(self._break_event(), value)
        if event is None or not getattr(event, 'kind', None):
            return None
        if event.kind == 'break_due':
            # A cached caller-created break candidate cannot bypass this clock.
            return None
        if not self._deliverable(event.kind, value):
            return None
        return self._record_delivery(event, value)

    def update(self, *, focus_active, rest_active=False, enabled=True,
               visible=True, snoozed=False, now=None):
        value = self._now(now)
        if value is None:
            self._last_update = None
            self._focus_active = False
            self._rest_active = False
            self.rest_seconds = 0.0
            self._rest_verified = False
            return None
        previous = self._last_update
        delta = None if previous is None else value - previous
        focus = bool(focus_active)
        rest = bool(rest_active) and not focus
        if delta is not None and 0 <= delta <= self.MAX_GAP_SECONDS:
            if self._focus_active:
                self.streak_seconds += delta
            elif self._rest_active:
                self.rest_seconds += delta
                if not self._rest_verified and self.rest_seconds + 1e-6 >= self.settings.rest_minutes * 60:
                    self._clear_streak()
                    self._rest_verified = True
        elif delta is not None:
            # Sleep, a stalled event loop, or clock reset cannot prove a break.
            self.rest_seconds = 0.0
            self._rest_verified = False

        if rest and not self._rest_active:
            self.rest_seconds = 0.0
            self._rest_verified = False
        elif not rest:
            self.rest_seconds = 0.0
            self._rest_verified = False
        self._last_update = value
        self._focus_active = focus
        self._rest_active = rest
        return self.choose(None, now=value, enabled=enabled, visible=visible, snoozed=snoozed)
