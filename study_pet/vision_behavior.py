"""Personal view calibration and media-free, reminder-independent intervals.

The signals describe observable actions. Missing faces never prove absence.
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import math
from uuid import uuid4


class BrowSignal:
    """Smooth only the current reliable user's score; keep hidden time unknown."""
    def __init__(self,settings):self.settings=settings;self.reset()

    def reset(self):self.last=None;self.value=None;self.active=False;self.primary=None

    def apply(self,o):
        f=o.primary_features
        if f is None:
            # Legacy/offline observations keep their old explicit score.
            self.reset()
            return o
        now=o.timestamp;s=self.settings
        gap=self.last is None or not 0<now-self.last<=.75 or self.primary!=o.primary_id
        if gap:self.value=None;self.active=False
        dt=0. if gap else now-self.last
        self.last=now;self.primary=o.primary_id
        pose_ok=(f.yaw is not None and f.pitch is not None and abs(f.yaw)<=72 and abs(f.pitch)<=65)
        # Calibration supports a side camera, but does not legitimise a newly
        # occluded brow or a large turn away from the calibrated view.
        if s.neutral_yaw is not None and f.yaw is not None:
            pose_ok=pose_ok and abs(f.yaw-s.neutral_yaw)<=28
        if not o.frame_ok or not o.brow_reliable or not pose_ok:
            self.value=None;self.active=False
            return replace(o,brow_valid=False,brow_active=False)
        raw=f.brow_score
        if (s.baseline is not None and s.frown_baseline is not None
            and s.neutral_geometry is not None and s.frown_geometry is not None
            and f.brow_geometry is not None):
            span=s.neutral_geometry-s.frown_geometry
            # Geometry is a supporting cue only if the two calibration states
            # really separate. Fusing correlated cues is not a probability.
            if span>.015 and s.frown_baseline-s.baseline>=.08:
                level=max(0.,min(1.,(s.neutral_geometry-f.brow_geometry)/span))
                geometric=s.baseline+level*(s.frown_baseline-s.baseline)
                raw=.75*raw+.25*geometric
        alpha=1. if self.value is None else 1-math.exp(-dt/.35)
        self.value=raw if self.value is None else self.value+alpha*(raw-self.value)
        threshold=s.brow_threshold
        self.active=self.value>=threshold if not self.active else self.value>=max(.02,threshold-.04)
        return replace(o,brow_score=self.value,brow_active=self.active)


def head_down(o,settings):
    f=o.primary_features
    if (not o.frame_ok or not o.has_primary or f is None or not f.quality_ok or f.pitch is None
        or settings.neutral_pitch is None):return None
    if f.yaw is None or abs(f.yaw)>72:return None
    if settings.neutral_yaw is not None and abs(f.yaw-settings.neutral_yaw)>28:return None
    return f.pitch-settings.neutral_pitch>=18.


class BehaviorTracker:
    """Interval events independent of bubbles, cool-downs and reminder snooze.

    Duration integrates adjacent valid observations, not wall time through an
    occlusion. Call flush/reset at a study-round boundary before changing IDs.
    """
    def __init__(self,settings):self.settings=settings;self.reset()

    def reset(self):
        self.last=None;self.segments={};self.state='unknown';self.reason='未观测'
        self.no_person_since=None;self.person_anchor=None;self.primary=None
        self.wall_anchor=None;self.mono_anchor=None;self._output=[]
        self.person_anchor_seen=None;self.away_confirmed=False;self.unknown_since=None

    def wall(self,t):
        if self.wall_anchor is None:
            self.wall_anchor=datetime.now(timezone.utc);self.mono_anchor=t
        return (self.wall_anchor+timedelta(seconds=t-self.mono_anchor)).isoformat(timespec='microseconds')

    def _emit(self,segment,closed=False):
        if not segment['confirmed']:return
        self._output.append({'id':segment['id'],'type':segment['type'],
            'started_at':self.wall(segment['start']),'ended_at':self.wall(segment['end']),
            'duration':round(segment['duration'],4),'status':'closed' if closed else 'ongoing',
            'evidence':dict(segment['evidence'])})
        segment['emitted']=segment['end']

    def _close(self,kind):
        segment=self.segments.pop(kind,None)
        if segment:self._emit(segment,True)

    def _track(self,kind,positive,now,dt,threshold=0.,evidence=None):
        segment=self.segments.get(kind)
        if positive is None:
            if segment:
                segment['active']=False
                if now-segment['last_positive']>.8:self._close(kind)
            return
        if positive:
            if segment is not None and not segment['active'] and now-segment['last_positive']>.8:
                self._close(kind);segment=None
            if segment is None:
                segment={'id':uuid4().hex,'type':kind,'start':now,'end':now,'duration':0.,
                    'last_positive':now,'active':True,'confirmed':False,'emitted':-math.inf,
                    'evidence':evidence or {}}
                self.segments[kind]=segment
            elif segment['active']:segment['duration']+=dt
            segment['end']=now;segment['last_positive']=now;segment['active']=True
            segment['confirmed']=segment['duration']>=threshold
            if segment['confirmed'] and now-segment['emitted']>=1.:self._emit(segment)
        elif segment:
            segment['active']=False
            if now-segment['last_positive']>=.8:self._close(kind)

    def _presence(self,o):
        if not o.frame_ok or not o.face_fresh:
            self.no_person_since=None;return 'unknown','画面质量不足或结果过期'
        if o.user_state=='multiple':
            self.no_person_since=None;self.person_anchor=None;self.person_anchor_seen=None;self.away_confirmed=False
            return 'unknown','多人入镜，无法归属主用户'
        if o.person_fresh and len(o.persons)>1:
            self.no_person_since=None;self.person_anchor=None;self.person_anchor_seen=None;self.away_confirmed=False
            return 'unknown','多个人体候选，暂停工位关联'
        if o.has_primary:
            face=o.faces[o.primary_face if o.primary_face is not None else 0]
            candidates=[p for p in o.persons if p.contains((face.x1+face.x2)/2,(face.y1+face.y2)/2)]
            if o.person_fresh and len(candidates)==1:
                self.person_anchor=candidates[0];self.person_anchor_seen=o.timestamp
            self.away_confirmed=False;self.no_person_since=None;return 'present','可靠主用户在画面内'
        if o.person_fresh and o.persons:
            self.no_person_since=None;self.away_confirmed=False
            if self.person_anchor_seen is None or o.timestamp-self.person_anchor_seen>6.:
                self.person_anchor=None;self.person_anchor_seen=None
            if len(o.persons)==1 and self.person_anchor is not None:
                p=o.persons[0];a=self.person_anchor
                if abs((p.x1+p.x2-a.x1-a.x2)/2)<.22 and abs((p.y1+p.y2-a.y1-a.y2)/2)<.25:
                    return 'present','面部不可见，原工位人体仍可关联'
            return 'unknown','检测到人体但无法确认是原工位用户'
        if o.person_fresh and not o.persons and not o.faces and (self.person_anchor is not None or self.away_confirmed):
            if self.away_confirmed:return 'away','持续确认原工位无人'
            if self.no_person_since is None:self.no_person_since=o.timestamp
            if o.timestamp-self.no_person_since>=self.settings.presence_seconds:
                self.away_confirmed=True;self.person_anchor=None;self.person_anchor_seen=None
                return 'away','连续未检测到原工位的人脸和人体'
            return 'unknown','正在确认是否离位'
        self.no_person_since=None
        return 'unknown','面部暂不可见，不能直接判断离位'

    def update(self,o,*,active=True):
        self._output=[];now=o.timestamp
        if not math.isfinite(now):return []
        if not active:
            result=self.flush();self.last=None;return result
        if self.last is not None and now<=self.last:return []
        gap=self.last is not None and now-self.last>.9
        dt=now-self.last if self.last is not None and not gap else 0.
        if gap:
            for kind in list(self.segments):self._close(kind)
            self.no_person_since=None;self.person_anchor=None;self.person_anchor_seen=None;self.away_confirmed=False
        if self.primary is not None and o.primary_id is not None and self.primary!=o.primary_id:
            for kind in list(self.segments):self._close(kind)
            self.person_anchor=None;self.person_anchor_seen=None;self.away_confirmed=False;self.no_person_since=None;dt=0.
        if o.primary_id is not None:self.primary=o.primary_id
        self.wall(now);self.last=now
        state,reason=self._presence(o);self.state=state;self.reason=reason
        if state=='unknown':
            if self.unknown_since is None:self.unknown_since=now
            if now-self.unknown_since>6. and self.no_person_since is None:
                self.person_anchor=None;self.person_anchor_seen=None;self.away_confirmed=False
        else:self.unknown_since=None
        presence_type={'present':'presence','away':'away','unknown':'unknown'}[state]
        for kind in ('presence','away','unknown'):
            previous = self.segments.get(kind)
            if kind != presence_type and previous is not None:
                # Consecutive observations share a transition boundary. A gap
                # or primary-user change has already closed the old interval.
                previous['end'] = now
                previous['duration'] += dt
                self._close(kind)
        self._track(presence_type,True,now,dt if presence_type in self.segments else 0.,evidence={'reason':reason})
        phone=o.phone_near_hand if o.has_primary and o.phone_fresh and o.face_fresh else None
        care=(o.brow_active if o.brow_active is not None else o.brow_score>=self.settings.brow_threshold) if o.brow_reliable else None
        self._track('phone',phone,now,dt,self.settings.phone_seconds,{'basis':'手机与手部空间关联，用途未确认'})
        self._track('care',care,now,dt,self.settings.care_seconds,{'basis':'持续眉部动作，不推断情绪'})
        self._track('head_down',head_down(o,self.settings),now,dt,self.settings.head_seconds,
            {'basis':'相对于已校准学习姿态的持续低头','mode':self.settings.learning_mode})
        return list(self._output)

    def event_id(self,kind):
        segment=self.segments.get(kind)
        return segment['id'] if segment and segment['confirmed'] else None

    def flush(self):
        self._output=[]
        for kind in list(self.segments):self._close(kind)
        return list(self._output)
