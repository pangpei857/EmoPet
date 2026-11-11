"""Interaction regressions for hit areas, click-vs-drag and persistent view settings."""
from pathlib import Path
import tempfile
import unittest
import time
from unittest.mock import patch
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from study_pet.pikachu import ART_WIDTH, ART_HEIGHT, draw_pikachu
from study_pet.gaze import EYE_MID_X, EYE_MID_Y, gaze_direction
from study_pet.raincoat import EYES
from study_pet.storage import Store
from study_pet.ui import Companion, STYLE

APP=QApplication.instance() or QApplication([])
APP.setQuitOnLastWindowClosed(False);APP.setStyleSheet(STYLE)


class PetInteractions(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="pikachu-test-")
        self.c=Companion(Store(Path(self.temp.name)),tray_enabled=False)
        self.c.panel.hide();APP.processEvents()

    def tearDown(self):
        c=self.c
        for timer in (c.timer,c.pet.canvas._animation,c.pet.canvas._click_timer,c.pet._bubble_timer,c.pet._mood_timer,c.pet._screen_timer):timer.stop()
        c.pet.hide();c.panel.hide();c.pet.deleteLater();c.panel.deleteLater()
        APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        APP.processEvents();self.temp.cleanup()

    def point(self,x,y):
        w=self.c.pet.canvas
        return QPoint(round(x/ART_WIDTH*w.width()),round(y/ART_HEIGHT*w.height()))

    def click_canvas(self,point):
        canvas=self.c.pet.canvas
        local=QPointF(point);global_point=QPointF(canvas.mapToGlobal(point))
        for kind,buttons in ((QMouseEvent.Type.MouseButtonPress,Qt.MouseButton.LeftButton),
                             (QMouseEvent.Type.MouseButtonRelease,Qt.MouseButton.NoButton)):
            event=QMouseEvent(kind,local,global_point,Qt.MouseButton.LeftButton,buttons,Qt.KeyboardModifier.NoModifier)
            APP.sendEvent(canvas,event)

    def test_different_body_parts_and_scaled_hits(self):
        for scale in (70,125):
            self.c.pet.set_scale(scale);APP.processEvents()
            for x,y,mood in ((138,100,"pet"),(142,233,"poke"),(230,224,"tail")):
                self.assertTrue(self.c.pet.canvas._shape.contains(QPointF(x,y)),(x,y))
                self.click_canvas(self.point(x,y))
                QTest.qWait(APP.doubleClickInterval()+65)
                self.assertEqual(self.c.pet.canvas.mood,mood,(scale,x,y,self.c.pet.canvas._touch_region,self.c.pet.canvas.size()))
                self.assertTrue(self.c.pet.bubble.isVisible())

    def test_drag_does_not_trigger_touch(self):
        pet=self.c.pet;canvas=pet.canvas;before=pet.pos()
        local=QPointF(self.point(140,210));global_point=QPointF(canvas.mapToGlobal(local.toPoint()))
        press=QMouseEvent(QMouseEvent.Type.MouseButtonPress,local,global_point,Qt.MouseButton.LeftButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        APP.sendEvent(canvas,press)
        move=QMouseEvent(QMouseEvent.Type.MouseMove,local+QPointF(-60,-30),global_point+QPointF(-60,-30),Qt.MouseButton.NoButton,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier)
        APP.sendEvent(canvas,move)
        release=QMouseEvent(QMouseEvent.Type.MouseButtonRelease,local,global_point+QPointF(-60,-30),Qt.MouseButton.LeftButton,Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
        APP.sendEvent(canvas,release);QTest.qWait(APP.doubleClickInterval()+60)
        self.assertNotEqual(before,pet.pos())
        self.assertEqual(canvas.mood,"idle")
        self.assertEqual(self.c.store.get("position"),[pet.x(),pet.y()])

    def test_startup_is_pet_only_and_panel_settings_open_same_menu(self):
        self.assertTrue(self.c.pet.isVisible())
        self.assertFalse(self.c.panel.isVisible())
        self.assertIs(self.c.panel.pet_settings.menu(),self.c.tray_menu)

    def test_hide_cancels_pending_touch_and_passive_feedback_stays_hidden(self):
        canvas=self.c.pet.canvas
        self.click_canvas(self.point(138,100))
        self.assertTrue(canvas._click_timer.isActive())
        self.c.pet.hide()
        QTest.qWait(APP.doubleClickInterval()+70)
        self.c.feedback('提醒内容','remind',notify=True)
        self.assertFalse(self.c.pet.isVisible())
        self.assertFalse(canvas._click_timer.isActive())
        self.assertFalse(canvas._animation.isActive())
        self.assertIsNone(canvas._origin)
        self.c.perform_action('care')
        self.assertTrue(self.c.pet.isVisible())
        self.assertEqual(canvas.mood,'care')

    def test_position_lock_still_allows_clicks_and_zoom(self):
        self.c.toggle_locked(True)
        canvas=self.c.pet.canvas;pet=self.c.pet;before=pet.pos()
        local=QPointF(self.point(140,210));global_point=QPointF(canvas.mapToGlobal(local.toPoint()))
        for kind,point,buttons in ((QMouseEvent.Type.MouseButtonPress,global_point,Qt.MouseButton.LeftButton),
                                  (QMouseEvent.Type.MouseMove,global_point+QPointF(-80,-40),Qt.MouseButton.LeftButton),
                                  (QMouseEvent.Type.MouseButtonRelease,global_point+QPointF(-80,-40),Qt.MouseButton.NoButton)):
            button=Qt.MouseButton.NoButton if kind==QMouseEvent.Type.MouseMove else Qt.MouseButton.LeftButton
            APP.sendEvent(canvas,QMouseEvent(kind,local,point,button,buttons,Qt.KeyboardModifier.NoModifier))
        QTest.qWait(APP.doubleClickInterval()+60)
        self.assertEqual(before,pet.pos())
        self.assertEqual(canvas.mood,'idle')
        self.click_canvas(self.point(138,100));QTest.qWait(APP.doubleClickInterval()+60)
        self.assertEqual(canvas.mood,'pet')
        pet.set_scale(110)
        self.assertEqual(pet.scale_percent,110)
        self.assertTrue(self.c.store.get('locked'))

    def test_long_bubble_keeps_character_anchor_and_text_clear_of_close(self):
        pet=self.c.pet
        text='这是一段较长的陪伴提示，需要在小尺寸下完整折行，避免被关闭按钮遮挡。'*12
        for scale in (70,100,160):
            pet.set_scale(scale);before=pet.foot_anchor()
            pet.say(text,'care');APP.processEvents()
            self.assertAlmostEqual(before.x(),pet.foot_anchor().x(),delta=1)
            self.assertAlmostEqual(before.y(),pet.foot_anchor().y(),delta=1)
            self.assertLessEqual(len(pet.bubble.label.text().splitlines()),6)
            self.assertTrue(pet.bubble.label.text().endswith('…'))
            self.assertEqual(pet.bubble.label.toolTip(),text)
            self.assertFalse(pet.bubble.label.geometry().intersects(pet.bubble.close_button.geometry()))
            self.assertGreaterEqual(pet.bubble.label.height(),pet.bubble.label.fontMetrics().lineSpacing()*len(pet.bubble.label.text().splitlines()))
            pet.dismiss_bubble()

    def test_bubble_hover_pauses_timeout_and_bubble_setting_keeps_action(self):
        pet=self.c.pet;pet.say('等你读完再收起','care')
        APP.sendEvent(pet.bubble,QEvent(QEvent.Type.Enter))
        self.assertFalse(pet._bubble_timer.isActive())
        APP.sendEvent(pet.bubble,QEvent(QEvent.Type.Leave))
        self.assertTrue(pet._bubble_timer.isActive())
        self.c.toggle_bubbles(False);self.c.perform_action('encourage')
        self.assertFalse(pet.bubble.isVisible())
        self.assertEqual(pet.canvas.mood,'encourage')
        self.assertFalse(self.c.store.get('bubbles'))

    def test_expired_long_bubble_compacts_without_moving_character(self):
        pet=self.c.pet;pet.dismiss_bubble();compact_height=pet.height()
        pet.say('这是一段需要多行显示的陪伴提示。'*30,'care')
        self.assertGreater(pet.height(),compact_height)
        anchor=pet.foot_anchor()
        pet.bubble.hovering=False;pet._bubble_timer.start(15)
        QTest.qWait(70)
        self.assertFalse(pet.bubble.isVisible())
        self.assertEqual(pet.height(),compact_height)
        self.assertEqual(pet.bubble.raw_text,'')
        self.assertAlmostEqual(anchor.x(),pet.foot_anchor().x(),delta=1)
        self.assertAlmostEqual(anchor.y(),pet.foot_anchor().y(),delta=1)

    def test_topmost_change_preserves_character_anchor(self):
        pet=self.c.pet;pet.say('长一点的提示文字，切换置顶时应保持脚下的位置。'*5,'care')
        before=pet.foot_anchor()
        self.c.toggle_topmost(False);APP.processEvents()
        self.assertAlmostEqual(before.x(),pet.foot_anchor().x(),delta=1)
        self.assertAlmostEqual(before.y(),pet.foot_anchor().y(),delta=1)
        self.assertTrue(pet.isVisible())

    def test_recovery_and_screen_repair_do_not_reset_task(self):
        self.c.session.start(1,'原来的任务')
        self.c.pet.move(-100000,-100000)
        self.c.pet.schedule_screen_repair();QTest.qWait(200)
        self.assertTrue(self.c.pet.screen().availableGeometry().contains(self.c.pet.geometry()))
        self.c.pet.hide();self.c.recover_pet()
        self.assertTrue(self.c.pet.isVisible())
        self.assertEqual(self.c.session.task,'原来的任务')
        self.assertEqual(self.c.session.status.value,'running')
        anchor=self.c.store.get('anchor')
        self.assertEqual(anchor,[self.c.pet.foot_anchor().x(),self.c.pet.foot_anchor().y()])

    def test_single_tray_click_restores_only_pet(self):
        self.c.pet.hide();self.c.panel.hide()
        self.c.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertTrue(self.c.pet.isVisible());self.assertFalse(self.c.panel.isVisible())
        self.c.tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertTrue(self.c.panel.isVisible())

    def test_wheel_zoom_limits_and_settings(self):
        pet=self.c.pet;canvas=pet.canvas;local=QPointF(self.point(140,210))
        wheel=QWheelEvent(local,QPointF(canvas.mapToGlobal(local.toPoint())),QPoint(),QPoint(0,120),
                          Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.NoScrollPhase,False)
        APP.sendEvent(canvas,wheel)
        self.assertEqual(pet.scale_percent,110)
        self.assertEqual(self.c.store.get("scale"),110)
        pet.set_scale(999);self.assertLessEqual(pet.scale_percent,160)
        pet.set_scale(-10);self.assertEqual(pet.scale_percent,70)
        self.assertTrue(pet.screen().availableGeometry().contains(pet.geometry()))

    def test_double_click_has_no_delayed_single_click(self):
        pet=self.c.pet
        QTest.mouseDClick(pet.canvas,Qt.MouseButton.LeftButton,pos=self.point(140,110))
        QTest.qWait(APP.doubleClickInterval()+65)
        self.assertTrue(self.c.panel.isVisible())
        self.assertEqual(pet.canvas.mood,"idle")

    def test_cursor_below_widget_updates_gaze_at_each_scale(self):
        canvas=self.c.pet.canvas
        for scale in (70,100,150):
            self.c.pet.set_scale(scale);APP.processEvents()
            canvas.gaze=(0.,0.)
            below=QPoint(round(EYE_MID_X/ART_WIDTH*canvas.width()),canvas.height()*2)
            with patch("study_pet.pikachu.QCursor.pos",return_value=canvas.mapToGlobal(below)):
                canvas._last_frame=time.monotonic()-.2
                canvas.advance()
            self.assertGreater(canvas.gaze[1],.6)
            self.assertLess(abs(canvas.gaze[0]),.02)

    def test_visible_pupils_move_up_and_down(self):
        centers=[]
        for y in (-300,EYE_MID_Y,600):
            image=QImage(280,300,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
            painter=QPainter(image)
            draw_pikachu(painter,QRectF(0,0,280,300),0.,"idle",gaze_direction(EYE_MID_X,y))
            painter.end()
            highlight_y=[]
            eye=EYES[0][0]
            for row in range(round((eye.top()+4)*300/800),round((eye.bottom()-4)*300/800)):
                for col in range(round((eye.left()+4)*280/736),round((eye.right()-4)*280/736)):
                    color=image.pixelColor(col,row)
                    channels=(color.red(),color.green(),color.blue())
                    if color.alpha()>200 and channels[0]>225 and channels[1]>180 and channels[2]>140:highlight_y.append(row)
            self.assertTrue(highlight_y)
            centers.append(sum(highlight_y)/len(highlight_y))
        self.assertGreater(centers[1]-centers[0],.5)
        self.assertGreater(centers[2]-centers[1],.5)

    def test_reference_background_and_leaf_are_not_rendered(self):
        image=QImage(280,300,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);draw_pikachu(p,QRectF(0,0,280,300),0.,'idle');p.end()
        for x,y in ((0,0),(25,135),(240,140),(20,280)):
            self.assertEqual(image.pixelColor(x,y).alpha(),0,(x,y))
        self.assertEqual(image.pixelColor(115,235).alpha(),255)

    def test_four_actions_have_distinct_frames_and_return_to_idle(self):
        frames=set()
        for key in ("idle","care","remind","encourage"):
            self.c.perform_action(key);APP.processEvents()
            self.assertEqual(self.c.pet.canvas.mood,key)
            frame=self.c.pet.canvas.grab().toImage()
            frames.add(bytes(frame.constBits()))
        self.assertEqual(len(frames),4)
        self.c.pet.canvas.set_action("care",15);QTest.qWait(80)
        self.assertEqual(self.c.pet.canvas.mood,"idle")

    def test_transparency_bubble_close_and_tray_menu_restore(self):
        pet=self.c.pet;self.c.sync_menu()
        self.assertTrue(pet.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        image=pet.grab().toImage()
        self.assertEqual(image.pixelColor(0,0).alpha(),0)
        QTest.mouseClick(pet.bubble.close_button,Qt.MouseButton.LeftButton)
        self.assertFalse(pet.bubble.isVisible())
        self.c.visibility_action.trigger();self.assertFalse(pet.isVisible())
        self.c.sync_menu();self.assertEqual(self.c.visibility_action.text(),"显示桌宠")
        self.c.visibility_action.trigger();self.assertTrue(pet.isVisible())
        self.c.scale_actions[125].trigger();self.assertEqual(pet.scale_percent,125)
        self.c.top_action.setChecked(False);self.c.top_action.trigger()
        self.c.toggle_topmost(False)
        self.assertFalse(pet.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        self.assertFalse(self.c.store.get("topmost"))


if __name__=="__main__":unittest.main()
