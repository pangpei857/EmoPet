"""Latest-frame scheduling. No Qt, camera access, or model imports."""
from dataclasses import dataclass, replace
import logging
import threading
import time


@dataclass(frozen=True)
class CapturedFrame:
    sequence: int
    timestamp: float
    image: object


class LatestFrames:
    """One shared frame, overwritten by capture while inference is busy."""
    def __init__(self):
        self.condition=threading.Condition();self.frame=None;self.sequence=0

    def publish(self,image,timestamp):
        with self.condition:
            self.sequence+=1
            self.frame=CapturedFrame(self.sequence,timestamp,image)
            self.condition.notify_all()

    def next(self,after,stop):
        with self.condition:
            self.condition.wait_for(lambda:stop.is_set() or
                (self.frame is not None and self.frame.sequence>after),timeout=.1)
            if stop.is_set() or self.frame is None or self.frame.sequence<=after:return None
            return self.frame

    def wake(self):
        with self.condition:self.condition.notify_all()


class RateMeter:
    def __init__(self):self.previous=None;self.value=0.

    def tick(self,now):
        if self.previous is not None and now>self.previous:
            current=1/(now-self.previous)
            self.value=current if not self.value else .8*self.value+.2*current
        self.previous=now
        return self.value


class ParallelAnalysis:
    """Independent face/hand (15 Hz) and phone (3 Hz) consumers."""
    def __init__(self,frames,features,phone,stop,emit):
        self.frames=frames;self.features=features;self.phone=phone
        self.stop=stop;self.emit=emit;self.phone_lock=threading.Lock()
        self.phone_result=None;self.threads=[]

    def start(self):
        for name,target in (('vision-face-hand',self.face_loop),('vision-phone',self.phone_loop)):
            thread=threading.Thread(target=self.guard,args=(target,),name=name,daemon=True)
            self.threads.append(thread);thread.start()

    def guard(self,target):
        try:target()
        except Exception:
            logging.exception('Local analysis thread failed')
            self.emit({'type':'error','text':'识别模块运行中断，请关闭后重新开启摄像头。'})
            self.stop.set();self.frames.wake()

    def phone_loop(self):
        sequence=0;rate=RateMeter()
        while not self.stop.is_set():
            frame=self.frames.next(sequence,self.stop)
            if frame is None:continue
            sequence=frame.sequence;started=time.monotonic()
            phones=self.phone.detect(frame.image)
            result=(frame.timestamp,phones,(time.monotonic()-started)*1000,rate.tick(started))
            with self.phone_lock:self.phone_result=result
            self.stop.wait(max(0.,1/3-(time.monotonic()-started)))

    def face_loop(self):
        sequence=0;rate=RateMeter()
        while not self.stop.is_set():
            frame=self.frames.next(sequence,self.stop)
            if frame is None:continue
            sequence=frame.sequence;started=time.monotonic()
            _,observation=self.features.analyze_features(frame.image,frame.timestamp)
            with self.phone_lock:phone=self.phone_result
            values={'asynchronous':True,'face_fps':rate.tick(started),'phone_fresh':phone is not None}
            if phone is not None:
                values.update(phone_timestamp=phone[0],phones=phone[1],phone_ms=phone[2],phone_fps=phone[3])
            observation=replace(observation,**values).freshened(time.monotonic())
            if not self.stop.is_set():self.emit({'type':'observation','observation':observation})
            self.stop.wait(max(0.,1/15-(time.monotonic()-started)))

    def close(self):
        self.stop.set();self.frames.wake()
        for thread in self.threads:thread.join(1.)
        return not any(thread.is_alive() for thread in self.threads)
