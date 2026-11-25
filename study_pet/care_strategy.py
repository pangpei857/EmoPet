"""Conservative support policy for local, observable study context."""

from collections import deque
from dataclasses import dataclass
import math


MODE_LABELS = {'quiet': '安静陪伴', 'balanced': '适时关心', 'supportive': '主动支持'}


@dataclass(frozen=True)
class CareTiming:
    mode: str = 'balanced'
    presence: str = 'unobserved'
    occupied: bool = False

    @property
    def available(self):
        return (self.mode != 'quiet' and self.presence not in {'away', 'unknown'}
                and not self.occupied)

    def wants_automatic_support(self, kind, *, reduced=False):
        """Apply remembered declines only to the matching optional support."""
        return kind == 'break_due' or not reduced


class SighEvidence:
    """Repeated audio candidates can support a tentative check-in."""

    def __init__(self):
        self.reset()

    def reset(self):
        self._recent = deque(maxlen=8)

    def observe(self, timestamp, now, mode):
        if (not math.isfinite(timestamp) or timestamp > now + .2 or now - timestamp > 5
                or (self._recent and timestamp - self._recent[-1] < 5)):
            return False
        self._recent.append(timestamp)
        while self._recent and timestamp - self._recent[0] > 90:
            self._recent.popleft()
        return mode == 'supportive' or len(self._recent) >= 2

    def near(self, now):
        return bool(self._recent and 0 <= now - self._recent[-1] <= 10)
