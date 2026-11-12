import asyncio
from dataclasses import replace
from types import SimpleNamespace
import unittest

from PySide6.QtCore import QEvent,QPointF,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from study_pet.music_core import MusicState,MusicVisibility,clean_text,is_qq_music
from study_pet.music_service import MusicController,_MusicWorker
from study_pet.ui import PetWindow,STYLE

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False);APP.setStyleSheet(STYLE)
PLAYING=MusicState('QQMusic.exe:1','很长的歌曲名称 · 测试曲目','测试歌手','playing',True,True,True)


class MusicCoreTests(unittest.TestCase):
    def test_only_qq_music_application_ids_match(self):
        for value in ('QQMusic.exe',r'C:\Program Files\Tencent\QQMusic\QQMusic.exe','Tencent.QQMusic_abc!QQMusic'):
            self.assertTrue(is_qq_music(value),value)
        for value in ('chrome.exe','msedge.exe','NotQQMusic.exe','https://y.qq.com','QQMusicHelper.exe'):
            self.assertFalse(is_qq_music(value),value)

    def test_pause_grace_cannot_be_extended_by_repeated_updates(self):
        clock=[0.];display=MusicVisibility(lambda:clock[0])
        paused=replace(PLAYING,status='paused')
        self.assertFalse(display.visible(paused));self.assertTrue(display.visible(PLAYING))
        self.assertTrue(display.visible(paused))
        clock[0]=29.;self.assertTrue(display.visible(paused))
        clock[0]=31.;self.assertFalse(display.visible(paused))
        self.assertTrue(display.visible(PLAYING));self.assertFalse(display.visible(MusicState()))

    def test_new_paused_session_does_not_reuse_old_visibility(self):
        display=MusicVisibility();display.visible(PLAYING)
        self.assertFalse(display.visible(replace(PLAYING,session_id='QQMusic.exe:2',status='paused')))

    def test_metadata_control_characters_and_length_are_bounded(self):
        self.assertEqual(clean_text(' a\x00\n b\t c '),'a b c')
        self.assertEqual(len(clean_text('x'*1000)),256)


class FakeWorker:
    def __init__(self,publish,complete):self.publish=publish;self.complete=complete;self.sent=[];self.stopped=False
    def start(self):self.publish(PLAYING)
    def stop(self):self.stopped=True
    def send(self,*request):self.sent.append(request);return True


class MusicControllerTests(unittest.TestCase):
    def setUp(self):self.controller=MusicController(worker_factory=FakeWorker);self.controller.start()
    def tearDown(self):self.controller.shutdown();self.controller.deleteLater();APP.processEvents()

    def test_commands_are_targeted_and_serialized(self):
        c=self.controller
        self.assertFalse(c.command('toggle','old-session'))
        self.assertTrue(c.command('toggle',PLAYING.session_id))
        self.assertFalse(c.command('next',PLAYING.session_id))
        request=c._worker.sent[-1];self.assertEqual(request[1:],('toggle',PLAYING.session_id))
        c._worker.complete(request[0],True,'')
        self.assertIsNone(c._pending);self.assertTrue(c.command('next',PLAYING.session_id))

    def test_disabled_controls_are_not_sent(self):
        c=self.controller;c._worker.publish(replace(PLAYING,can_next=False))
        self.assertFalse(c.command('next',PLAYING.session_id));self.assertEqual(c._worker.sent,[])

    def test_old_worker_cannot_restore_music_after_disable_or_retry(self):
        c=self.controller;old=c._worker;c.stop();old.publish(PLAYING)
        self.assertEqual(c.state.status,'unavailable');self.assertTrue(old.stopped)
        c.start();current=c._worker;old.publish(replace(PLAYING,title='stale'))
        self.assertEqual(c.state.title,PLAYING.title);self.assertIs(c._worker,current)


class Session:
    def __init__(self,source='QQMusic.exe',status=4):self.source_app_user_model_id=source;self.status=status;self.actions=[]
    def get_playback_info(self):
        return SimpleNamespace(playback_status=self.status,controls=SimpleNamespace(
            is_play_pause_toggle_enabled=True,is_pause_enabled=self.status==4,is_play_enabled=self.status==5,
            is_previous_enabled=True,is_next_enabled=True))
    def add_media_properties_changed(self,callback):return 1
    def remove_media_properties_changed(self,token):pass
    def add_playback_info_changed(self,callback):return 2
    def remove_playback_info_changed(self,token):pass
    async def try_pause_async(self):self.actions.append('pause');self.status=5;return True
    async def try_play_async(self):self.actions.append('play');self.status=4;return True
    async def try_skip_next_async(self):self.actions.append('next');return True
    async def try_skip_previous_async(self):self.actions.append('previous');return True


class MusicBackendTests(unittest.TestCase):
    def test_browser_media_is_never_selected(self):
        qq=Session();browser=Session('msedge.exe')
        worker=_MusicWorker(lambda state:None,lambda *args:None)
        worker.manager=SimpleNamespace(get_sessions=lambda:[browser,qq]);worker.select_session()
        self.assertIs(worker.session,qq)
        worker.manager=SimpleNamespace(get_sessions=lambda:[browser]);worker.sessions_dirty=True;worker.select_session()
        self.assertIsNone(worker.session)

    def test_stale_target_is_rejected_and_valid_controls_use_qq_session(self):
        results=[];qq=Session();worker=_MusicWorker(lambda state:None,lambda *args:results.append(args));worker.bind(qq)
        asyncio.run(worker.execute(1,'next','old-session'));self.assertEqual(qq.actions,[])
        self.assertFalse(results[-1][1])
        for request,action in enumerate(('toggle','toggle','next','previous'),2):
            asyncio.run(worker.execute(request,action,worker.session_id))
            self.assertTrue(results[-1][1])
        self.assertEqual(qq.actions,['pause','play','next','previous'])


class MusicUiTests(unittest.TestCase):
    def setUp(self):
        self.pet=PetWindow();self.pet.move(50,20);self.pet.show();APP.processEvents()
    def tearDown(self):
        self.pet.hide();self.pet.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete);APP.processEvents()

    def test_expand_and_collapse_keep_character_anchor_when_space_allows(self):
        pet=self.pet;before=pet.foot_anchor();base_height=pet.height()
        pet.set_music_state(PLAYING);APP.processEvents()
        self.assertTrue(pet.music_card.isVisible());self.assertGreater(pet.height(),base_height)
        self.assertAlmostEqual(pet.foot_anchor().y(),before.y(),delta=1)
        self.assertGreaterEqual(pet.music_card.y(),pet.badge.geometry().bottom())
        pet.set_music_state(MusicState());self.assertFalse(pet.music_card.isVisible())
        self.assertAlmostEqual(pet.foot_anchor().y(),before.y(),delta=1)

    def test_player_clicks_do_not_touch_the_character(self):
        self.pet.set_music_state(PLAYING);commands=[];touches=[]
        self.pet.music_command.connect(lambda *args:commands.append(args));self.pet.touched.connect(touches.append)
        QTest.mouseClick(self.pet.music_card.buttons['toggle'],Qt.MouseButton.LeftButton)
        self.assertEqual(commands,[('toggle',PLAYING.session_id)]);self.assertEqual(touches,[])
        self.pet.music_card.set_busy(True);self.assertFalse(self.pet.music_card.buttons['next'].isEnabled())

    def test_hidden_pet_stays_hidden_when_a_song_starts(self):
        self.pet.hide();self.pet.set_music_state(PLAYING);self.assertFalse(self.pet.isVisible())

    def test_music_controls_fit_supported_scales_and_stay_on_screen(self):
        pet=self.pet;pet.set_music_state(PLAYING)
        for scale in (70,100,160):
            pet.set_scale(scale);pet.reset_position();APP.processEvents()
            card=pet.music_card
            for label in (card.title,card.artist):self.assertGreaterEqual(label.height(),label.fontMetrics().height())
            self.assertLess(card.artist.geometry().bottom(),card.buttons['toggle'].y())
            for button in card.buttons.values():self.assertTrue(card.rect().contains(button.geometry()))
            self.assertTrue(pet.screen().availableGeometry().contains(pet.geometry()))


if __name__=='__main__':unittest.main()
