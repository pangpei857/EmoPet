"""UI-independent countdown using a monotonic clock, without accumulating timer drift."""

from enum import Enum
import math
import time
from collections.abc import Callable


class Status(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class FocusSession:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self.clock = clock
        self.status = Status.IDLE
        self.task = ""
        self.kind = "focus"
        self.duration = 25 * 60
        self._remaining = float(self.duration)
        self._deadline = 0.0

    @property
    def remaining(self) -> float:
        if self.status == Status.RUNNING:
            return max(0.0, self._deadline - self.clock())
        return self._remaining

    @property
    def display_seconds(self) -> int:
        return math.ceil(self.remaining)

    @property
    def elapsed(self) -> float:
        return self.duration - self.remaining

    @property
    def progress(self) -> float:
        return self.elapsed / self.duration

    def start(self, minutes: int, task: str = "", kind: str = "focus") -> None:
        if minutes < 1 or minutes > 120:
            raise ValueError("时长应在1到120分钟之间")
        if kind not in {"focus", "break"}:
            raise ValueError("Unknown session kind")
        self.duration = minutes * 60
        self._remaining = float(self.duration)
        self.task = task.strip() or ("专心做一件事" if kind == "focus" else "休息一下")
        self.kind = kind
        self._deadline = self.clock() + self._remaining
        self.status = Status.RUNNING

    def pause(self) -> None:
        if self.status == Status.RUNNING:
            if self.tick():
                return
            self._remaining = self.remaining
            self.status = Status.PAUSED

    def resume(self) -> None:
        if self.status == Status.PAUSED:
            self._deadline = self.clock() + self._remaining
            self.status = Status.RUNNING

    def tick(self) -> bool:
        """Return True exactly once on completion, including after a delayed UI tick."""
        if self.status == Status.RUNNING and self.remaining <= 0:
            self._remaining = 0
            self.status = Status.COMPLETED
            return True
        return False

    def reset(self) -> None:
        self.status = Status.IDLE
        self._remaining = float(self.duration)

