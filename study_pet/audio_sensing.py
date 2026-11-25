"""Opt-in, local microphone analysis for a conservative sigh candidate.

Raw audio lives briefly in bounded capture buffers and is never persisted.
The detector classifies sounds, not the user's emotion or need for help.
"""
from dataclasses import dataclass
import math
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
import time

import numpy as np
from PySide6.QtCore import QObject, Qt, Signal, Slot


MODEL_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'models' / 'yamnet.tflite'
WINDOW_SECONDS = 0.975
HOP_SECONDS = 0.48
COMPETING_LABELS = (
    'Speech', 'Child speech, kid speaking', 'Speech synthesizer',
    'Hubbub, speech noise, speech babble', 'Singing', 'Music',
    'Breathing', 'Wheeze', 'Snoring', 'Sniff', 'Cough', 'Throat clearing',
    'Sneeze', 'Computer keyboard', 'Wind', 'Silence',
)


@dataclass(frozen=True)
class SighCandidate:
    timestamp: float
    score: float


def usable_signal(samples):
    """Discard silence, negligible variation, and saturated PCM."""
    return (samples.size > 0 and np.isfinite(samples).all()
            and np.std(samples) >= 0.003
            and np.mean(np.abs(samples) >= 0.995) < 0.025)


class SighGate:
    """Require overlapping confirmations and deduplicate sustained sounds."""

    def __init__(self):
        self._previous = None
        self._last_emission = -math.inf
        self._in_event = False

    def interrupt(self):
        self._previous = None
        self._in_event = False

    def observe(self, scores, timestamp):
        score = scores.get('Sigh', 0.0)
        competitor = max(scores.get(label, 0.0) for label in COMPETING_LABELS)
        if not (0.45 <= score <= 1.0 and score >= competitor + 0.12):
            self.interrupt()
            return None
        previous = self._previous
        self._previous = SighCandidate(timestamp, score)
        if previous is None or not 0 < timestamp - previous.timestamp <= 1.2:
            self._in_event = False
            return None
        if self._in_event:
            return None
        self._in_event = True
        if timestamp - self._last_emission >= 15.0:
            self._last_emission = timestamp
            return SighCandidate(timestamp, min(score, previous.score))
        return None


class YAMNet:
    def __init__(self, model_path=MODEL_PATH):
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.audio import AudioClassifier, AudioClassifierOptions
        from mediapipe.tasks.python.components.containers.audio_data import AudioData

        self._audio_data = AudioData
        options = AudioClassifierOptions(
            base_options=BaseOptions(model_asset_buffer=Path(model_path).read_bytes()),
            category_allowlist=['Sigh', *COMPETING_LABELS],
        )
        self._classifier = AudioClassifier.create_from_options(options)

    def scores(self, samples, rate):
        audio = self._audio_data.create_from_array(samples, rate)
        results = self._classifier.classify(audio)
        if not results or not results[0].classifications:
            return {}
        return {category.category_name: category.score
                for category in results[0].classifications[0].categories}

    def close(self):
        self._classifier.close()


def _input_format(sounddevice):
    device = sounddevice.query_devices(kind='input')
    rate = round(device['default_samplerate'])
    channels = min(2, device['max_input_channels'])
    for candidate_rate, candidate_channels in dict.fromkeys(((16000, 1), (rate, 1), (rate, channels))):
        try:
            sounddevice.check_input_settings(channels=candidate_channels, dtype='float32',
                                             samplerate=candidate_rate)
        except sounddevice.PortAudioError:
            continue
        return candidate_rate, candidate_channels
    raise RuntimeError('Unsupported microphone input format')


def _listen(stop, report):
    """Run on a worker; the PortAudio callback only moves bounded PCM chunks."""
    try:
        import sounddevice
        model = YAMNet()
    except (ImportError, OSError, RuntimeError, ValueError):
        report('error', '音频感知无法加载本地模型。请检查程序安装。')
        return

    chunks = Queue(maxsize=8)
    interrupted = Event()

    def captured(data, _frames, _clock_info, status):
        if stop.is_set():
            raise sounddevice.CallbackAbort
        if status:
            interrupted.set()
            return
        try:
            chunks.put_nowait((time.monotonic(), bytes(data)))
        except Full:
            interrupted.set()

    try:
        if stop.is_set():
            return
        rate, channels = _input_format(sounddevice)
        window_frames = round(rate * WINDOW_SECONDS)
        hop_frames = round(rate * HOP_SECONDS)
        samples = np.empty(0, dtype=np.float32)
        gate = SighGate()
        try:
            with sounddevice.RawInputStream(samplerate=rate, channels=channels, dtype='float32',
                                            blocksize=round(rate * 0.1), callback=captured):
                report('listening', None)
                last_audio = time.monotonic()
                while not stop.is_set():
                    if interrupted.is_set():
                        interrupted.clear()
                        samples = np.empty(0, dtype=np.float32)
                        gate.interrupt()
                        # Drop contaminated continuity and let fresh chunks start a new window.
                        for _ in range(chunks.maxsize):
                            try:
                                chunks.get_nowait()
                            except Empty:
                                break
                    try:
                        timestamp, data = chunks.get(timeout=0.15)
                    except Empty:
                        if time.monotonic() - last_audio > 4:
                            report('error', '麦克风暂未提供音频。请检查设备后重新开启音频感知。')
                            return
                        continue
                    last_audio = timestamp
                    if stop.is_set():
                        break
                    block = np.frombuffer(data, dtype=np.float32).reshape(-1, channels)
                    mono = block[:, 0] if channels == 1 else block.mean(axis=1)
                    samples = np.concatenate((samples, mono))
                    if samples.size < window_frames:
                        continue
                    window = samples[:window_frames]
                    samples = samples[hop_frames:]
                    scores = model.scores(window, rate) if usable_signal(window) else {}
                    candidate = gate.observe(scores, timestamp)
                    if candidate and not stop.is_set() and not interrupted.is_set():
                        report('candidate', candidate)
        except (sounddevice.PortAudioError, OSError, RuntimeError, ValueError):
            report('error', '本地音频感知已停止。请检查麦克风权限和设备后重试。')
    except (sounddevice.PortAudioError, OSError, RuntimeError, ValueError):
        report('error', '找不到可用麦克风。请检查设备和 Windows 麦克风权限。')
    finally:
        model.close()


class AudioSensing(QObject):
    """Coordinate an opt-in listening session from the GUI thread."""
    candidate = Signal(object)
    status_changed = Signal(str)
    _worker_message = Signal(int, str, object)
    MAX_CANDIDATE_AGE_SECONDS = 2.0

    def __init__(self, parent=None, *, listener=None):
        super().__init__(parent)
        self.status = '音频感知已关闭'
        self._listener = listener or _listen
        self._wanted = False
        self._closed = False
        self._failed = False
        self._serial = 0
        self._thread = None
        self._stop = None
        self._worker_message.connect(self._handle_message, Qt.ConnectionType.QueuedConnection)

    def update(self, *, enabled, studying, inhibited=False):
        """Call after consent, activity, playback or dictation state changes."""
        if self._closed:
            return
        wanted = bool(enabled and studying and not inhibited)
        if wanted != self._wanted:
            self._failed = False
        self._wanted = wanted
        if not self._wanted:
            if self._stop is not None:
                self._stop.set()
            if not enabled:
                self._set_status('音频感知已关闭')
            elif inhibited:
                self._set_status('语音输入或播报期间暂停感知')
            else:
                self._set_status('开始学习后启用本地音频感知')
        elif self._thread is None and not self._failed:
            self._start()

    def _set_status(self, value):
        if self.status != value:
            self.status = value
            self.status_changed.emit(value)

    def _start(self):
        self._serial += 1
        serial = self._serial
        stop = self._stop = Event()
        self._set_status('正在启动本地音频感知…')

        def report(kind, data=None):
            if not stop.is_set() or kind == 'finished':
                try:
                    self._worker_message.emit(serial, kind, data)
                except RuntimeError:
                    pass  # The GUI was destroyed during application shutdown.

        def run():
            try:
                self._listener(stop, report)
            except Exception:
                report('error', '音频感知遇到问题。请重新开启该功能。')
            finally:
                report('finished')

        self._thread = Thread(target=run, name='momo-audio-sensing', daemon=True)
        self._thread.start()

    @Slot(int, str, object)
    def _handle_message(self, serial, kind, data):
        if self._closed or serial != self._serial or self._stop is None:
            return
        if kind == 'finished':
            stopped = self._stop.is_set()
            self._stop = self._thread = None
            if self._wanted and not self._failed:
                if stopped:
                    self._start()
                else:
                    self._failed = True
                    self._set_status('音频感知已停止。请重新开启该功能。')
            return
        if self._stop.is_set() or not self._wanted:
            return
        if kind == 'listening':
            self._set_status('本地音频感知中 · 实验性叹气候选')
        elif kind == 'error':
            self._failed = True
            self._set_status(data)
        elif kind == 'candidate' and 0 <= time.monotonic() - data.timestamp <= self.MAX_CANDIDATE_AGE_SECONDS:
            self.candidate.emit(data)

    def shutdown(self):
        self._closed = True
        self._wanted = False
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
