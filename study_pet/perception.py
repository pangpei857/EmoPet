"""Media-free observations and conservative, time-based companion feedback."""
from dataclasses import dataclass, field, replace
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
class FaceFeatures:
    """Scores remain paired with their own face; never average across users."""
    box: Box
    blendshapes: tuple[tuple[str, float], ...] = ()
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    quality_ok: bool = True
    quality_reason: str = ''
    brow_geometry: float | None = None
    left_visibility: float = 1.
    right_visibility: float = 1.

    @property
    def brow_valid(self):
        values=dict(self.blendshapes)
        return all(name in values and math.isfinite(values[name]) and 0<=values[name]<=1
            for name in ('browDownLeft','browDownRight'))

    @property
    def brow_score(self):
        values=dict(self.blendshapes)
        if not self.brow_valid:return 0.
        # A side camera compresses the far eye/brow; don't average a hidden
        # brow as if it had the same reliability as the visible one.
        left=max(0.,self.left_visibility);right=max(0.,self.right_visibility)
        if min(left,right)<max(left,right)*.45:
            return values['browDownLeft' if left>right else 'browDownRight']
        return (values['browDownLeft']*left+values['browDownRight']*right)/max(.001,left+right)

    @property
    def eyes_down(self):
        values=dict(self.blendshapes)
        return (values.get('eyeLookDownLeft',0.)+values.get('eyeLookDownRight',0.))/2


@dataclass(frozen=True)
class Observation:
    timestamp: float
    phones: tuple[Box, ...] = ()
    hands: tuple[tuple[tuple[float, float], ...], ...] = ()
    faces: tuple[Box, ...] = ()
    brow_score: float = 0.0
    eyes_down: float = 0.0
    inference_ms: float = 0.0
    phone_timestamp: float | None = None
    face_ms: float = 0.0
    hand_ms: float = 0.0
    phone_ms: float = 0.0
    face_fps: float = 0.0
    phone_fps: float = 0.0
    asynchronous: bool = False
    face_fresh: bool = True
    phone_fresh: bool = True
    face_features: tuple[FaceFeatures, ...] = ()
    primary_face: int | None = None
    primary_id: int | None = None
    face_state: str | None = None
    face_reason: str = ''
    filtered_faces: tuple[int, ...] = ()
    brow_valid: bool = True
    persons: tuple[Box, ...] = ()
    person_fresh: bool = False
    frame_ok: bool = True
    brow_active: bool | None = None

    @property
    def user_state(self):
        if self.face_state is not None:return self.face_state
        # Older/offline observations have no tracker metadata. Stay conservative.
        return 'single' if len(self.faces)==1 else 'multiple' if self.faces else 'absent'

    @property
    def has_primary(self):
        return (self.face_fresh and self.user_state=='single' and
            (len(self.faces)==1 if self.face_state is None else
             self.primary_face is not None and 0<=self.primary_face<len(self.faces)))

    @property
    def primary_features(self):
        index=self.primary_face if self.face_state is not None else 0
        return (self.face_features[index] if self.has_primary and index is not None
            and 0<=index<len(self.face_features) else None)

    @property
    def brow_reliable(self):
        feature=self.primary_features
        return self.has_primary and self.brow_valid and (feature is None or feature.quality_ok)

    def freshened(self, now):
        """Never reuse old detections as evidence on a newer preview frame."""
        if not self.asynchronous:return self
        face_fresh=self.face_fresh and 0<=now-self.timestamp<=.75
        phone_fresh=(self.phone_fresh and self.phone_timestamp is not None
            and 0<=now-self.phone_timestamp<=.9
            and abs(self.timestamp-self.phone_timestamp)<=.75)
        return replace(self,face_fresh=face_fresh,phone_fresh=phone_fresh,
            person_fresh=self.person_fresh and phone_fresh,
            brow_valid=self.brow_valid and face_fresh,
            brow_score=self.brow_score if face_fresh else 0.,
            eyes_down=self.eyes_down if face_fresh else 0.)

    @property
    def phone_near_hand(self):
        # Require several hand landmarks next to a phone; a phone on the desk
        # alone is insufficient. This is still a spatial heuristic, not proof.
        if not self.frame_ok or not self.face_fresh or not self.phone_fresh:return False
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
    frown_baseline: float | None = None
    neutral_geometry: float | None = None
    frown_geometry: float | None = None
    neutral_yaw: float | None = None
    neutral_pitch: float | None = None
    baseline_noise: float = 0.
    head_enabled: bool = True
    head_seconds: int = 30
    learning_mode: str = 'mixed'
    presence_seconds: int = 12
    record_behaviors: bool = True

    @classmethod
    def from_dict(cls,data):
        data=data if isinstance(data,dict) else {}
        result=cls()
        for key in ('phone_enabled','care_enabled','focus_only','head_enabled','record_behaviors'):
            if isinstance(data.get(key),bool):setattr(result,key,data[key])
        for key,lo,hi in (('phone_seconds',3,60),('care_seconds',2,30),('cooldown_seconds',30,600),('head_seconds',10,180),('presence_seconds',5,60)):
            value=data.get(key)
            if isinstance(value,(int,float)) and math.isfinite(value):setattr(result,key,max(lo,min(hi,int(value))))
        for key,lo,hi in (('brow_threshold',.10,.95),('baseline',0.,1.),('frown_baseline',0.,1.),
            ('neutral_geometry',0.,3.),('frown_geometry',0.,3.),('neutral_yaw',-90.,90.),
            ('neutral_pitch',-90.,90.),('baseline_noise',0.,1.)):
            value=data.get(key)
            if isinstance(value,(int,float)) and math.isfinite(value):setattr(result,key,max(lo,min(hi,float(value))))
        if data.get('learning_mode') in {'computer','paper','mixed'}:result.learning_mode=data['learning_mode']
        return result

    def as_dict(self):return dict(vars(self))

    @property
    def recommended_brow_threshold(self):
        if self.baseline is None:return None
        if self.frown_baseline is not None and self.frown_baseline-self.baseline>=max(.08,self.baseline_noise*3):
            return round(max(.10,min(.95,(self.baseline+self.frown_baseline)/2)),2)
        return round(max(.10,min(.95,self.baseline+.18)),2)


@dataclass(frozen=True)
class FeedbackEvent:
    kind: str
    text: str
    mood: str
    behavior_id: str | None = None


class ReminderGate:
    """Temporary user choices; monotonic deadlines do not change saved settings."""
    def __init__(self,clock=time.monotonic):
        self.clock=clock;self.snooze_until=0.;self.phone_until=0.;self.care_until=0.;self.head_until=0.

    @property
    def snoozed(self):return self.clock()<self.snooze_until
    @property
    def phone_paused(self):return self.clock()<self.phone_until
    @property
    def care_paused(self):return self.clock()<self.care_until
    @property
    def head_paused(self):return self.clock()<self.head_until

    def apply(self,response,kind):
        now=self.clock()
        if response=='research' and kind=='phone':self.phone_until=max(self.phone_until,now+300)
        elif response=='thinking' and kind=='care':self.care_until=max(self.care_until,now+600)
        elif response=='paper' and kind=='head_down':self.head_until=max(self.head_until,now+600)
        elif response=='snooze':self.snooze_until=max(self.snooze_until,now+600)
        elif response=='false_positive':
            name={'phone':'phone_until','head_down':'head_until'}.get(kind,'care_until')
            setattr(self,name,max(getattr(self,name),now+60))

    def toggle_snooze(self):self.snooze_until=0. if self.snoozed else self.clock()+600

    def reset_round(self):
        # 'Looking something up' belongs to the current learning round.
        self.phone_until=0.;self.care_until=0.;self.head_until=0.


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
    UNCERTAIN_RETENTION=1.25

    def __init__(self,settings=None):
        self.settings=settings or VisionSettings()
        self._last=None;self._phone=_Evidence();self._care=_Evidence()
        self._last_reminder=-math.inf
        self._last_by_kind={}
        self.last_kind=''
        self._uncertain_since=None;self._primary_id=None

    @property
    def phone_duration(self):return self._phone.duration

    @property
    def care_duration(self):return self._care.duration

    def reset_evidence(self):
        self._last=None;self._phone=_Evidence();self._care=_Evidence()
        self._uncertain_since=None

    def cooldown_remaining(self,now,kind=None):
        global_remaining=max(0.,min(30,self.settings.cooldown_seconds)-(now-self._last_reminder))
        if kind is None:return global_remaining
        return max(global_remaining,self.settings.cooldown_seconds-(now-self._last_by_kind.get(kind,-math.inf)))

    def update(self,observation,*,focus_active,pet_visible=True,snoozed=False,phone_paused=False,care_paused=False):
        now=observation.timestamp
        if not math.isfinite(now):self.reset_evidence();return None
        previous=self._last
        # No evidence may bridge paused capture, long inference gaps or clocks
        # from a previous camera session.
        max_gap=.75 if observation.asynchronous else 2.
        if previous is not None and (now<=previous or now-previous>max_gap):
            self.reset_evidence();previous=None
        dt=0. if previous is None else now-previous
        self._last=now
        s=self.settings
        if snoozed or not pet_visible or (s.focus_only and not focus_active):
            self.reset_evidence();self._last=now;return None
        if observation.primary_id is not None and observation.primary_id!=self._primary_id:
            self.reset_evidence();self._last=now;dt=0.
            self._primary_id=observation.primary_id
        if phone_paused:self._phone=_Evidence()
        if care_paused:self._care=_Evidence()
        if observation.user_state=='uncertain' and observation.face_fresh:
            if self._uncertain_since is None:self._uncertain_since=now
            # Freeze, never add this interval (or the first interval on return).
            self._phone.active=False;self._care.active=False
            if now-self._uncertain_since>self.UNCERTAIN_RETENTION:
                self._phone=_Evidence();self._care=_Evidence()
            return None
        if not observation.has_primary:
            self.reset_evidence();self._last=now;return None
        if self._uncertain_since is not None:
            if now-self._uncertain_since>self.UNCERTAIN_RETENTION:
                self._phone=_Evidence();self._care=_Evidence()
            else:
                # Preserve only already measured evidence, not time spent in
                # uncertainty; keep the old dropout rule for other failures.
                if self._phone.duration:self._phone.last_seen=now
                if self._care.duration:self._care.last_seen=now
            self._uncertain_since=None;dt=0.
        phone=s.phone_enabled and not phone_paused and observation.phone_near_hand
        care=s.care_enabled and not care_paused and observation.brow_reliable and (
            observation.brow_active if observation.brow_active is not None else observation.brow_score>=s.brow_threshold)
        self._phone.update(phone,now,dt);self._care.update(care,now,dt)
        if self.cooldown_remaining(now)>0:return None
        event=None
        # Never act on a stale positive during a detection dropout.
        if care and self._care.duration>=s.care_seconds and self.cooldown_remaining(now,'care')<=0:
            event=FeedbackEvent('care','刚才似乎皱了会儿眉。\n需要我帮你拆解一下问题，还是休息一会？','care')
        elif phone and self._phone.duration>=s.phone_seconds and self.cooldown_remaining(now,'phone')<=0:
            event=FeedbackEvent('phone','手机好像在手边停留一会儿啦。\n是在查资料，还是需要我提醒你继续？','remind')
        if event:
            self._last_reminder=now;self.last_kind=event.kind
            self._last_by_kind[event.kind]=now
            self._phone=_Evidence();self._care=_Evidence()
        return event


class BrowCalibration:
    """A short neutral-expression baseline, without storing any face images."""
    def __init__(self):
        self.samples=[];self.started=None;self.features=[];self.last=None;self.primary=None

    def add(self,observation):
        if not observation.brow_reliable or not observation.face_fresh:
            self.samples=[];self.features=[];self.started=None
            self.last=observation.timestamp;return None
        if self.last is not None and not 0<observation.timestamp-self.last<=.9:
            self.samples=[];self.features=[];self.started=None
        if self.primary is not None and observation.primary_id is not None and self.primary!=observation.primary_id:
            self.samples=[];self.features=[];self.started=None
        self.primary=observation.primary_id
        self.last=observation.timestamp
        if self.started is None:self.started=observation.timestamp
        self.samples.append(observation.brow_score)
        if observation.primary_features is not None:self.features.append(observation.primary_features)
        if observation.timestamp-self.started>=3. and len(self.samples)>=8:
            return float(statistics.median(self.samples))
        return None

    def median_feature(self,name):
        values=[getattr(f,name) for f in self.features if getattr(f,name,None) is not None]
        return float(statistics.median(values)) if values else None

    @property
    def noise(self):
        if not self.samples:return 0.
        median=statistics.median(self.samples)
        return float(statistics.median(abs(v-median) for v in self.samples))*1.4826

    @property
    def stable(self):
        for name in ('yaw','pitch'):
            values=[getattr(f,name) for f in self.features if getattr(f,name,None) is not None]
            if len(values)>2 and statistics.pstdev(values)>5.:return False
        return self.noise<=.12
