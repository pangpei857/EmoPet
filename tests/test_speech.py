import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from study_pet.chat_ui import ChatPanel
from study_pet.speech import LocalSpeech
from study_pet.storage import Store


APP = QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False)


def wait_until(predicate):
    for _ in range(250):
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError("Timed out waiting for the local speech process")


def child(script):
    return sys.executable, ["-u", "-c", script]


class LocalSpeechTests(unittest.TestCase):
    def setUp(self):
        self.speech = LocalSpeech()
        self.addCleanup(self.speech.shutdown)

    def test_recognition_waits_for_stop_and_preserves_chinese(self):
        transcript = "请解释一下这道题。"
        encoded = base64.b64encode(transcript.encode("utf-8")).decode("ascii")
        script = f"import sys\nprint('READY')\nassert sys.stdin.readline().strip()=='stop'\nprint('TEXT {encoded}')"
        states, results, errors = [], [], []
        self.speech.state_changed.connect(states.append)
        self.speech.recognized.connect(results.append)
        self.speech.failed.connect(errors.append)
        with patch.object(self.speech, "_command", return_value=child(script)):
            self.assertTrue(self.speech.start_recognition())
            wait_until(lambda: self.speech.state == "listening")
            self.assertFalse(self.speech.speak("cannot play while recording"))
            self.assertEqual(results, [])
            self.assertTrue(self.speech.stop_recognition())
            wait_until(lambda: not self.speech.busy)
        self.assertEqual(results, [transcript])
        self.assertEqual(errors, [])
        self.assertEqual(states, ["starting", "listening", "finishing", "idle"])

    def test_synthesis_receives_runtime_payload_over_stdin(self):
        text = '书名《红楼梦》，引号 " 和反斜杠 \\ 均为朗读文本。'
        script = ("import base64, sys\n"
                  f"assert base64.b64decode(sys.stdin.readline()).decode('utf-8')=={ascii(text)}\n"
                  "print('DONE')")
        errors = []
        self.speech.failed.connect(errors.append)
        with patch.object(self.speech, "_command", return_value=child(script)):
            self.assertTrue(self.speech.speak(text))
            wait_until(lambda: not self.speech.busy)
        self.assertEqual(errors, [])

    def test_missing_chinese_engine_returns_actionable_failure(self):
        errors = []
        self.speech.failed.connect(errors.append)
        with patch.object(self.speech, "_command", return_value=child("print('ERROR NO_CHINESE_RECOGNIZER')")):
            self.assertTrue(self.speech.start_recognition())
            wait_until(lambda: not self.speech.busy)
        self.assertEqual(len(errors), 1)
        self.assertIn("中文听写引擎", errors[0])


class SpeechAndMemoryChatTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="momo-speech-test-")
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name))
        self.speech = LocalSpeech()
        self.addCleanup(self.speech.shutdown)
        self.memory = ""
        self.panel = ChatPanel(self.store, speech=self.speech, memory_context=lambda:self.memory)
        self.addCleanup(self.panel.close)
        self.panel.show()

    def test_recognition_only_adds_editable_draft_and_never_sends(self):
        self.panel.composer.setPlainText("我正在学习")
        encoded = base64.b64encode("线性代数。".encode()).decode("ascii")
        script = f"import sys\nprint('READY')\nsys.stdin.readline()\nprint('TEXT {encoded}')"
        with patch.object(self.speech, "_command", return_value=child(script)), \
                patch.object(self.panel.client, "start") as send:
            self.panel.dictate_button.click()
            wait_until(lambda: self.speech.state == "listening")
            self.assertFalse(self.panel.send_button.isEnabled())
            self.panel.dictate_button.click()
            wait_until(lambda: not self.speech.busy)
            send.assert_not_called()
        self.assertEqual(self.panel.composer.toPlainText(), "我正在学习\n线性代数。")
        self.assertTrue(self.panel.send_button.isEnabled())
        self.assertEqual(self.panel.chats.conversations(), [])

    def test_closing_chat_releases_recognition_and_preserves_draft(self):
        self.panel.composer.setPlainText("已经输入的草稿")
        with patch.object(self.speech, "_command", return_value=child("import sys\nprint('READY')\nsys.stdin.readline()")):
            self.panel.dictate_button.click()
            wait_until(lambda: self.speech.state == "listening")
            self.panel.close()
            wait_until(lambda: not self.speech.busy)
        self.assertEqual(self.panel.composer.toPlainText(), "已经输入的草稿")

    def test_memory_share_requires_new_consent_if_preview_changed(self):
        self.assertFalse(self.panel.memory_check.isEnabled())
        self.memory = "偏好一"
        self.panel.update_context_label()
        self.assertIn(self.memory, self.panel.memory_check.toolTip())
        self.assertTrue(self.panel.memory_check.isEnabled())
        self.assertFalse(self.panel.memory_check.isChecked())
        self.panel.memory_check.setChecked(True)
        self.panel.composer.setPlainText("继续学习")
        self.memory = "偏好二"
        with patch.object(self.panel.vault, "load", return_value="test-key"), \
                patch.object(self.panel.client, "start") as send:
            self.assertFalse(self.panel.send())
            send.assert_not_called()
            self.assertFalse(self.panel.memory_check.isChecked())
            self.panel.memory_check.setChecked(True)
            self.assertTrue(self.panel.send())
            messages = send.call_args.args[2]
            self.assertIn(self.memory, messages[0]["content"])
            self.assertFalse(self.panel.memory_check.isChecked())
