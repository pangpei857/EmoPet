"""Conservative geometry tracking; no identity recognition or image retention."""
from dataclasses import dataclass,field,replace
import logging
import math

from .perception import Box,Observation

log=logging.getLogger(__name__)
# Keep these compact state-change diagnostics in the existing application log.
log.setLevel(logging.INFO)


def area(box):return max(0.,box.x2-box.x1)*max(0.,box.y2-box.y1)


def center(box):return ((box.x1+box.x2)/2,(box.y1+box.y2)/2)


def overlap(a,b):
    return max(0.,min(a.x2,b.x2)-max(a.x1,b.x1))*max(0.,min(a.y2,b.y2)-max(a.y1,b.y1))


def valid(box):
    return all(math.isfinite(v) for v in (box.x1,box.y1,box.x2,box.y2)) and area(box)>0


def match_score(previous,current):
    if not valid(previous) or not valid(current) or not .5<=area(current)/area(previous)<=2.:return -1.
    intersection=overlap(previous,current)
    iou=intersection/(area(previous)+area(current)-intersection)
    distance=math.dist(center(previous),center(current))
    diagonal=math.hypot(previous.x2-previous.x1,previous.y2-previous.y1)
    if iou<.25 or distance>diagonal*.5:return -1.
    return iou-distance/max(diagonal,.001)*.2


@dataclass
class _Extra:
    box: Box
    last_seen: float
    samples: list = field(default_factory=list)
    away_since: float | None = None
    established_away: bool = False
    attached: bool = False
    ever_attached: bool = False
    suspected: bool = False
    last_aligned: float | None = None


class FaceDiagnostics:
    """Called in the GUI process, whose logging handler owns momo.log."""
    def __init__(self):self._last=-math.inf;self._key=None

    def record(self,o):
        if o.face_state is None or not math.isfinite(o.timestamp):return
        key=(o.face_state,o.face_reason,len(o.filtered_faces))
        if key==self._key or o.timestamp-self._last<1.:return
        skew=None if o.phone_timestamp is None or not math.isfinite(o.phone_timestamp) else round((o.timestamp-o.phone_timestamp)*1000)
        log.info('face_state=%s reason=%s candidates=%d filtered=%d primary=%s phone_skew_ms=%s',
            o.face_state,o.face_reason,len(o.faces),len(o.filtered_faces),o.primary_id,skew)
        self._last=o.timestamp;self._key=key


class PrimaryFaceTracker:
    ACQUIRE_SECONDS=.35
    MULTI_CONFIRM_SECONDS=1.
    TRACK_TTL=.75
    PHONE_SKEW=.35

    def __init__(self):
        self._next_id=0
        self.reset()

    def reset(self):
        self._box=None;self._seen=None;self._started=None;self._matches=0
        self._id=None;self._last=None;self._extras=[];self._multiple_since=None
        self._recover_since=None;self._state='uncertain';self._phone_time=None
        self._multi_confirmed=False

    def _finish(self,o,state,reason,index=None,filtered=()):
        self._state=state
        feature=(o.face_features[index] if state=='single' and index is not None
            and index<len(o.face_features) and o.face_features[index].box==o.faces[index] else None)
        result=replace(o,face_state=state,face_reason=reason,primary_face=index,
            primary_id=self._id,filtered_faces=tuple(filtered),
            brow_score=feature.brow_score if feature is not None else 0.,
            eyes_down=feature.eyes_down if feature is not None else 0.,
            brow_valid=feature is not None and feature.brow_valid)
        return result

    def _phone_aligned(self,o):
        stamp=o.phone_timestamp
        if not o.phone_fresh or stamp is None or not math.isfinite(stamp):return False
        if self._phone_time is not None and stamp<self._phone_time:return False
        self._phone_time=stamp
        # A result from a future capture cannot explain this face frame.
        return 0<=o.timestamp-stamp<=self.PHONE_SKEW

    @staticmethod
    def _inside_phone(face,phones):
        return [p for p in phones if valid(p) and p.score>=.45 and
            overlap(face,p)/area(face)>=.85 and p.contains(*center(face))]

    def _attached(self,track,face,o,aligned):
        now=o.timestamp
        if not o.phone_fresh or (aligned and not o.phones):
            track.attached=False;track.samples.clear()
        if not aligned:return False
        candidates=self._inside_phone(face,o.phones)
        small=(area(face)<=area(self._box)*.20 and
            face.x2-face.x1<=(self._box.x2-self._box.x1)*.5 and
            face.y2-face.y1<=(self._box.y2-self._box.y1)*.6)
        if not candidates or not small:
            if o.phones:
                if track.away_since is None:track.away_since=now
                if now-track.away_since>=.35:track.established_away=True
            track.attached=False;track.samples.clear()
            return False
        track.away_since=None
        if track.established_away:return False
        track.suspected=True
        phone=max(candidates,key=lambda p:overlap(face,p))
        px,py=center(phone);fx,fy=center(face)
        relative=((fx-phone.x1)/(phone.x2-phone.x1),(fy-phone.y1)/(phone.y2-phone.y1))
        sample=(o.phone_timestamp,px,py,fx,fy,relative)
        if track.last_aligned is not None and now-track.last_aligned>.6:
            track.attached=False;track.samples.clear()
        track.last_aligned=now
        if track.samples and math.dist(relative,track.samples[-1][5])>.12:
            track.attached=False;track.samples.clear()
        if not track.samples or o.phone_timestamp>track.samples[-1][0]:track.samples.append(sample)
        track.samples[:]=track.samples[-8:]
        if track.attached:return True
        # Containment alone is ambiguous. Require three independent phone
        # captures plus measurable co-motion of the phone and extra face.
        for first in track.samples[:-2]:
            delta_phone=(px-first[1],py-first[2]);delta_face=(fx-first[3],fy-first[4])
            if (o.phone_timestamp-first[0]>=.5 and math.hypot(*delta_phone)>=.02
                and math.dist(delta_phone,delta_face)<=.015
                and math.dist(relative,first[5])<=.12):
                track.attached=True;track.ever_attached=True;return True
        return False

    def update(self,o: Observation):
        now=o.timestamp
        if not math.isfinite(now):
            self.reset();return self._finish(o,'uncertain','invalid_timestamp')
        if self._last is not None and (now<=self._last or now-self._last>self.TRACK_TTL):self.reset()
        self._last=now
        if not o.face_fresh:
            self.reset();return self._finish(o,'uncertain','stale_face')
        aligned=self._phone_aligned(o)
        if self._seen is not None and now-self._seen>self.TRACK_TTL:
            self._box=None;self._matches=0
        index=None
        if self._box is not None:
            ranked=sorted(((match_score(self._box,b),i) for i,b in enumerate(o.faces)),reverse=True)
            if ranked and ranked[0][0]>=0 and (len(ranked)==1 or ranked[0][0]-ranked[1][0]>.15):index=ranked[0][1]
        else:
            ranked=sorted(((area(b),i) for i,b in enumerate(o.faces) if valid(b) and
                area(b)>=.008 and .45<=(b.x2-b.x1)/(b.y2-b.y1)<=1.8 and
                not any(t.ever_attached and now-t.last_seen<=.5 and match_score(t.box,b)>=0 for t in self._extras) and
                not (aligned and self._inside_phone(b,o.phones))),reverse=True)
            if ranked and (len(ranked)==1 or ranked[0][0]>=ranked[1][0]*2.5):
                index=ranked[0][1];self._next_id+=1;self._id=self._next_id
                self._started=now;self._matches=0
        if index is not None:
            self._box=o.faces[index];self._seen=now;self._matches+=1
        stable=index is not None and self._matches>=3 and now-self._started>=self.ACQUIRE_SECONDS
        extras=[(i,b) for i,b in enumerate(o.faces) if i!=index]
        old_tracks=[t for t in self._extras if now-t.last_seen<=.5];new_tracks=[];filtered=[]
        for i,box in extras:
            ranked=sorted(((match_score(t.box,box),j) for j,t in enumerate(old_tracks)),reverse=True)
            track=old_tracks.pop(ranked[0][1]) if ranked and ranked[0][0]>=0 else _Extra(box,now)
            track.box=box;track.last_seen=now;track.suspected=False;new_tracks.append(track)
            attached=index is not None and valid(box) and self._attached(track,box,o,aligned)
            if stable and attached:filtered.append(i)
        self._extras=new_tracks+old_tracks
        unresolved=len(extras)>len(filtered)
        if unresolved and len(o.faces)>1:
            self._recover_since=None
            if self._multiple_since is None:self._multiple_since=now
            self._multi_confirmed=self._multi_confirmed or now-self._multiple_since>=self.MULTI_CONFIRM_SECONDS
            state='multiple' if self._multi_confirmed else 'uncertain'
            reason='confirmed_multiple' if state=='multiple' else 'extra_face_pending'
            if state=='uncertain':
                if not aligned and o.phones:reason='phone_unaligned'
                elif any(t.suspected for t in new_tracks):reason='phone_candidate_pending'
            return self._finish(o,state,reason,index,filtered)
        self._multiple_since=None
        if not stable:
            self._recover_since=None
            return self._finish(o,'uncertain','primary_missing' if index is None else 'acquiring_primary',index)
        # An attachment proof already spans >=3 phone captures and >=0.5 s.
        # Do not require an additional uninterrupted phone-alignment window:
        # 3-Hz phone results naturally age between fresh captures.
        if self._multi_confirmed and not filtered:
            if self._recover_since is None:self._recover_since=now
            if now-self._recover_since<self.ACQUIRE_SECONDS:
                return self._finish(o,'uncertain','single_recovery',index,filtered)
        self._multi_confirmed=False;self._recover_since=None
        return self._finish(o,'single','phone_attached_filtered' if filtered else 'stable_primary',index,filtered)
