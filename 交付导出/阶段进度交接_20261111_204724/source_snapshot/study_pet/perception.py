"""Media-free observations and conservative, time-based companion feedback."""
from dataclasses import dataclass, field
import math
import statistics
import time


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float
    score: float = 1.0

    def contains(self, x, y, margin=0.0):
        return self.x1-margin <= x <= self.x2+margin and self.y1-margin <= y <= self.y2+margin


@dataclass(frozen=True)
class Observation:
    timestamp: float
    phones: tuple[Box, ...] = ()
    hands: tuple[tuple[tuple[float, float], ...], ...] = ()
    faces: tuple[Box, ...] = ()
    brow_score: float = 0.0
    eyes_down: float = 0.0
    inference_ms: float = 0.0

    @property
    def phone_near_hand(self):
        # Require several hand landmarks next to a phone; a phone on the desk
        # alone is insufficient. This is still a spatial heuristic, not proof.
        for phone in self.phones:
            margin=min(.055,max(.018,(phone.x2-phone.x1)*.2))
            for hand in self.hands:
                if sum(phone.contains(x,y,margin) for x,y in hand)>=3:
                    return True
        return False


@dataclass
class VisionSettings:
    phone_enabled: bool = True
    care_enabled: bool = True
    focus_only: bool = True
    phone_seconds: int = 12
    care_seconds: int = 5
    cooldown_seconds: int = 120
    brow_threshold: float = .45
    baseline: float | None = None

    @classmethod
    def from_dict(cls,data):
        data=data if isinstance(data,dict) else {}
        result=cls()
        for key in ('phone_enabled','care_enabled','focus_only'):
            if isinstance(data.get(key),bool):setattr(result,key,data[key])
        for key,lo,hi in (('phone_seconds',3,60),('care_seconds',2,30),('cooldown_seconds',30,600)):
            value=data.get(key)
            if isinstance(value,(int,float)) and math.isfinite(value):setattr(result,key,max(lo,min(hi,int(value))))
        for key,lo,hi in (('brow_threshold',.15,.95),('baseline',0.,1.)):
            value=data.get(key)
            if isinstance(value,(int,float)) and math.isfinite(value):setattr(result,key,max(lo,min(hi,float(value))))
        return result

    def as_dict(self):return dict(vars(self))


@dataclass(frozen=True)
class FeedbackEvent:
    kind: str
    text: str
    mood: str


class ReminderGate:
    """Temporary user choices; monotonic deadlines do not change saved settings."""
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.snooze_until=0.;self.phone_until=0.;self.care_until=0.

    @property
    def snoozed(self):return self.clock()<self.snooze_until
    @property
    def phone_paused(self):return self.clock()<self.phone_until
    @property
    def care_paused(self):return self.clock()<self.care_until

    def apply(self,response,kind):
        now=self.clock()
        if response=='research' and kind=='phone':self.phone_until=max(self.phone_until,now+300)
        elif response=='snooze':self.snooze_until=max(self.snooze_until,now+600)
        elif response=='false_positive':
            name='phone_until' if kind=='phone' else 'care_until'
            setattr(self,name,max(getattr(self,name),now+60))

    def toggle_snooze(self):self.snooze_until=0. if self.snoozed else self.clock()+600

    def reset_round(self):
        # 'Looking something up' belongs to the current learning round.
        self.phone_until=0.;self.care_until=0.


@dataclass
class _Evidence:
    duration: float = 0.
    last_seen: float | None = None
    active: bool = False

    def update(self, positive, now, dt):
        if positive:
            if self.active:self.duration+=dt
            elif self.last_seen is None or now-self.last_seen>1.:self.duration=0.
            self.last_seen=now
        elif self.last_seen is None or now-self.last_seen>1.:self.duration=0.
        self.active=positive


class ReminderPolicy:
    def __init__(self,settings=None):
        self.settings=settings or VisionSettings()
        self._last=None;self._phone=_Evidence();self._care=_Evidence()
        self._last_reminder=-math.inf
        self.last_kind=''

    @property
    def phone_duration(self):return self._phone.duration

    @property
    def care_duration(self):return self._care.duration

    def reset_evidence(self):
        self._last=None;self._phone=_Evidence();self._care=_Evidence()

    def update(self,observation,*,focus_active,pet_visible=True,snoozed=False,phone_paused=False,care_paused=False):
        now=observation.timestamp
        previous=self._last
        # No evidence may bridge paused capture, long inference gaps or clocks
        # from a previous camera session.
        if previous is not None and (now<=previous or now-previous>2.):
            self.reset_evidence();previous=None
        dt=0. if previous is None else now-previous
        self._last=now
        s=self.settings
        if snoozed or not pet_visible or (s.focus_only and not focus_active):
            self.reset_evidence();self._last=now;return None
        single_face=len(observation.faces)==1
        if not single_face:
            self.reset_evidence();self._last=now;return None
        phone=s.phone_enabled and not phone_paused and single_face and observation.phone_near_hand
        threshold=s.brow_threshold
        if s.baseline is not None:threshold=max(threshold,min(.95,s.baseline+.18))
        care=s.care_enabled and not care_paused and single_face and observation.brow_score>=threshold
        if phone_paused:self._phone=_Evidence()
        if care_paused:self._care=_Evidence()
        self._phone.update(phone,now,dt);self._care.update(care,now,dt)
        if now-self._last_reminder<s.cooldown_seconds:return None
        event=None
        # Never act on a stale positive during a detection dropout.
        if phone and self._phone.duration>=s.phone_seconds:
            event=FeedbackEvent('phone','手机好像在手边停留一会儿啦。\n如果正在学习，我们先完成眼前这一小步？','remind')
        elif care and self._care.duration>=s.care_seconds:
            event=FeedbackEvent('care','辛苦啦，要不要放松一下眉头？\n喝口水，慢慢来也可以。','care')
        if event:
            self._last_reminder=now;self.last_kind=event.kind
            self._phone=_Evidence();self._care=_Evidence()
        return event


class BrowCalibration:
    """A short neutral-expression baseline, without storing any face images."""
    def __init__(self):self.samples=[];self.started=None

    def add(self,observation):
        if len(observation.faces)!=1:
            self.samples=[];self.started=None;return None
        if self.started is None:self.started=observation.timestamp
        self.samples.append(observation.brow_score)
        if observation.timestamp-self.started>=3. and len(self.samples)>=8:
            return float(statistics.median(self.samples))
        return None
