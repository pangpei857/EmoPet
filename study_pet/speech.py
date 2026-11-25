"""Windows-local dictation and read-aloud without recording files or cloud calls."""

import base64
import binascii
import os
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QProcess, QTimer, Signal


# The .NET event handlers run independently of PowerShell's input loop.
_DICTATION = r"""
using System;
using System.Linq;
using System.Speech.Recognition;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

public static class MomoDictation {
    public static void Run() {
        var recognizers = SpeechRecognitionEngine.InstalledRecognizers();
        var recognizer = recognizers.FirstOrDefault(r => r.Culture.Name == "zh-CN")
            ?? recognizers.FirstOrDefault(r => r.Culture.TwoLetterISOLanguageName == "zh");
        if (recognizer == null) {
            Console.WriteLine("ERROR NO_CHINESE_RECOGNIZER");
            return;
        }
        using (var engine = new SpeechRecognitionEngine(recognizer))
        using (var completed = new ManualResetEvent(false)) {
            try {
                engine.LoadGrammar(new DictationGrammar());
            } catch (Exception) {
                Console.WriteLine("ERROR DICTATION_UNAVAILABLE");
                return;
            }
            try {
                engine.SetInputToDefaultAudioDevice();
            } catch (Exception) {
                Console.WriteLine("ERROR MICROPHONE_UNAVAILABLE");
                return;
            }
            var words = new StringBuilder();
            Exception failure = null;
            engine.SpeechRecognized += (sender, e) => {
                if (words.Length < 6000 && !String.IsNullOrWhiteSpace(e.Result.Text))
                    words.Append(e.Result.Text.Trim());
            };
            engine.RecognizeCompleted += (sender, e) => {
                failure = e.Error;
                completed.Set();
            };
            engine.RecognizeAsync(RecognizeMode.Multiple);
            Console.WriteLine("READY");
            Console.Out.Flush();
            var stop = Task.Factory.StartNew(() => Console.ReadLine(), TaskCreationOptions.LongRunning);
            int ended = WaitHandle.WaitAny(new WaitHandle[] { completed, ((IAsyncResult)stop).AsyncWaitHandle });
            if (ended == 1 && !completed.WaitOne(0)) {
                engine.RecognizeAsyncStop();
                if (!completed.WaitOne(4000)) {
                    Console.WriteLine("ERROR DICTATION_TIMEOUT");
                    return;
                }
            }
            if (failure != null) {
                Console.WriteLine("ERROR MICROPHONE_UNAVAILABLE");
                return;
            }
            if (words.Length == 0) {
                Console.WriteLine("ERROR NO_SPEECH");
                return;
            }
            Console.WriteLine("TEXT " + Convert.ToBase64String(Encoding.UTF8.GetBytes(words.ToString())));
        }
    }
}
"""

_RECOGNIZE_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try {
    Add-Type -AssemblyName System.Speech
    $definition = @'
""" + _DICTATION + r"""
'@
    $speech = [System.Speech.Recognition.SpeechRecognitionEngine].Assembly.Location
    Add-Type -TypeDefinition $definition -ReferencedAssemblies @('System.dll', 'System.Core.dll', $speech)
    [MomoDictation]::Run()
} catch {
    [Console]::WriteLine('ERROR DICTATION_UNAVAILABLE')
}
"""

_SPEAK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$synthesizer = $null
try {
    Add-Type -AssemblyName System.Speech
    $encoded = [Console]::ReadLine()
    if (-not $encoded) { return }
    $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
    $synthesizer = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if ($text -match '\p{IsCJKUnifiedIdeographs}') {
        $voice = $synthesizer.GetInstalledVoices() | Where-Object {
            $_.Enabled -and $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'zh'
        } | Select-Object -First 1
        if ($null -eq $voice) {
            [Console]::WriteLine('ERROR NO_CHINESE_VOICE')
            return
        }
        $synthesizer.SelectVoice($voice.VoiceInfo.Name)
    }
    $synthesizer.SetOutputToDefaultAudioDevice()
    $synthesizer.Speak($text)
    [Console]::WriteLine('DONE')
} catch {
    [Console]::WriteLine('ERROR PLAYBACK_UNAVAILABLE')
} finally {
    if ($null -ne $synthesizer) { $synthesizer.Dispose() }
}
"""

_MESSAGES = {
    "NO_CHINESE_RECOGNIZER": "未找到 Windows 中文听写引擎。请在系统中安装可用于桌面应用的中文语音识别组件，或使用文字输入。",
    "DICTATION_UNAVAILABLE": "Windows 本地听写无法启动。请检查中文语音识别组件，或使用文字输入。",
    "MICROPHONE_UNAVAILABLE": "无法读取麦克风。请检查 Windows 默认输入设备、麦克风权限和设备占用状态。",
    "DICTATION_TIMEOUT": "本地听写未能及时结束，请重试。",
    "NO_SPEECH": "这次没有识别到文字，请靠近麦克风再试一次。",
    "NO_CHINESE_VOICE": "未找到可用的 Windows 中文播报语音。请在系统中安装中文朗读语音。",
    "PLAYBACK_UNAVAILABLE": "Windows 语音播报失败。请检查系统的朗读语音和输出设备。",
}


class LocalSpeech(QObject):
    """One local speech operation at a time, with bounded subprocess lifetimes."""

    state_changed = Signal(str)
    recognized = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.state = "idle"
        self.mode = None
        self._process = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._timed_out)

    @property
    def busy(self):
        return self.mode is not None

    def start_recognition(self):
        return self._start("capture", "starting", 12000)

    def stop_recognition(self):
        if self.mode != "capture" or self.state == "finishing":
            return False
        if self.state == "starting":
            self.cancel()
            return True
        self._set_state("finishing")
        self._process.write(b"stop\n")
        self._process.closeWriteChannel()
        self._timer.start(7000)
        return True

    def speak(self, text):
        text = str(text).strip()
        if not text:
            return False
        text = text[:1500] + ("……" if len(text) > 1500 else "")
        return self._start("speech", "speaking", 120000, base64.b64encode(text.encode("utf-8")) + b"\n")

    def cancel(self):
        if self._process is not None:
            self._cancelled = True
            self._timer.stop()
            self._process.kill()

    def shutdown(self):
        if self._process is not None:
            process = self._process
            self.cancel()
            # A quitting application must not leave a microphone or voice worker behind.
            process.waitForFinished(500)

    def _set_state(self, state):
        self.state = state
        self.state_changed.emit(state)

    @staticmethod
    def _command(mode):
        root = os.environ.get("SystemRoot")
        if sys.platform != "win32" or not root:
            return None
        executable = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if not executable.is_file():
            return None
        script = _RECOGNIZE_SCRIPT if mode == "capture" else _SPEAK_SCRIPT
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        return str(executable), ["-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                                 "-EncodedCommand", encoded]

    def _start(self, mode, state, deadline, payload=b""):
        if self.busy:
            return False
        command = self._command(mode)
        if not command:
            self.failed.emit("本地语音需要 Windows PowerShell 和 Windows 语音组件。")
            return False
        self._process = process = QProcess(self)
        self.mode = mode
        self._output = bytearray()
        self._terminal = None
        self._cancelled = False
        self._timed_out_message = ""
        process.readyReadStandardOutput.connect(lambda: self._read(process))
        process.finished.connect(lambda _code, _status: self._finished(process))
        process.errorOccurred.connect(lambda error: self._process_error(process, error))
        if payload:
            process.started.connect(lambda: self._write_payload(process, payload))
        self._set_state(state)
        self._timer.start(deadline)
        process.start(*command)
        return True

    def _write_payload(self, process, payload):
        if self._process is process and not self._cancelled:
            process.write(payload)
            process.closeWriteChannel()

    def _process_error(self, process, error):
        if self._process is process and error == QProcess.ProcessError.FailedToStart:
            self._terminal = ("ERROR", "DICTATION_UNAVAILABLE" if self.mode == "capture" else "PLAYBACK_UNAVAILABLE")
            self._finished(process)

    def _read(self, process):
        if self._process is not process:
            return
        self._output.extend(bytes(process.readAllStandardOutput()))
        while b"\n" in self._output:
            raw_line, _, remaining = self._output.partition(b"\n")
            self._output = bytearray(remaining)
            line = raw_line.decode("ascii", errors="replace").strip()
            if line == "READY" and self.state == "starting" and not self._cancelled:
                self._set_state("listening")
                self._timer.start(45000)
            elif line == "DONE":
                self._terminal = ("DONE", "")
            elif line.startswith(("TEXT ", "ERROR ")):
                self._terminal = tuple(line.split(" ", 1))

    def _timed_out(self):
        if self.state == "listening":
            self.stop_recognition()
        elif self._process is not None:
            self._timed_out_message = "本地语音操作超时，请重试。"
            self._process.kill()

    def _finished(self, process):
        if self._process is not process:
            return
        self._read(process)
        self._timer.stop()
        terminal, data = self._terminal or ("ERROR", "DICTATION_UNAVAILABLE" if self.mode == "capture" else "PLAYBACK_UNAVAILABLE")
        cancelled = self._cancelled
        timeout_message = self._timed_out_message
        self._process = None
        self.mode = None
        process.deleteLater()
        if not cancelled:
            if timeout_message:
                self.failed.emit(timeout_message)
            elif terminal == "TEXT":
                try:
                    result = base64.b64decode(data, validate=True).decode("utf-8").strip()
                except (UnicodeError, binascii.Error):
                    result = ""
                if result:
                    self.recognized.emit(result)
                else:
                    self.failed.emit(_MESSAGES["NO_SPEECH"])
            elif terminal == "ERROR":
                self.failed.emit(_MESSAGES.get(data, "本地语音操作失败，请重试。"))
        self._set_state("idle")
