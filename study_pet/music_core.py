"""Small, media-free models for QQ Music remote control."""
from dataclasses import dataclass
import re
import time


def is_qq_music(source):
    value=str(source).casefold().replace('/','\\')
    return bool(re.search(r'(^|[\\!_])qqmusic(?:\.exe)?($|[!_])',value))


def clean_text(value,limit=256):
    return ' '.join(str(value or '').replace('\x00','').split())[:limit]


@dataclass(frozen=True)
class MusicState:
    session_id: str = ''
    title: str = ''
    artist: str = ''
    status: str = 'unavailable'
    can_toggle: bool = False
    can_previous: bool = False
    can_next: bool = False
    message: str = '等待 QQ 音乐播放'


class MusicVisibility:
    """Pause grace is fixed at transition time, never extended by polling."""
    def __init__(self,clock=time.monotonic,pause_seconds=30.):
        self.clock=clock;self.pause_seconds=pause_seconds
        self.session='';self.was_playing=False;self.paused_until=None

    def visible(self,state):
        if not state.session_id or state.session_id!=self.session:
            self.session=state.session_id;self.was_playing=False;self.paused_until=None
        if state.status=='playing':
            self.was_playing=True;self.paused_until=None;return True
        if state.status=='paused' and self.was_playing:
            if self.paused_until is None:self.paused_until=self.clock()+self.pause_seconds
            return self.clock()<self.paused_until
        self.was_playing=False;self.paused_until=None
        return False
