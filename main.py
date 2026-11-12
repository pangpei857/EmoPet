"""Run with python main.py or double-click 启动桌宠.cmd."""
import argparse
import logging
from pathlib import Path
import sys
import tempfile

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()

from PySide6.QtCore import QStandardPaths, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from study_pet.pikachu import pet_icon
from study_pet.storage import Store
from study_pet.ui import Companion, STYLE


def smoke_test(companion, preview):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtTest import QTest
    from study_pet.focus import Status
    p=companion.panel
    companion.show_panel()
    p.task.setText("读完第三章，整理三个要点")
    p.duration.setValue(25)
    QTest.mouseClick(p.start,Qt.MouseButton.LeftButton)
    assert companion.session.status==Status.RUNNING
    QTest.mouseClick(p.start,Qt.MouseButton.LeftButton)
    assert companion.session.status==Status.PAUSED
    frozen=companion.session.remaining;QTest.qWait(300)
    assert companion.session.remaining==frozen
    QTest.mouseClick(p.start,Qt.MouseButton.LeftButton)
    assert companion.session.status==Status.RUNNING
    p.close();assert not p.isVisible()
    companion.show_panel();assert p.isVisible()
    companion.session._deadline=companion.session.clock()-1
    companion.on_tick()
    assert companion.session.status==Status.COMPLETED
    assert companion.store.today()["completed"]==1
    companion.on_tick();assert companion.store.today()["completed"]==1
    QTest.mouseClick(p.rest,Qt.MouseButton.LeftButton)
    assert companion.session.kind=="break"
    QTest.mouseClick(p.stop,Qt.MouseButton.LeftButton)
    QTest.mouseClick(p.start,Qt.MouseButton.LeftButton)
    companion.feedback("你专心，我陪你。\n慢慢来就好。","idle")
    QTest.qWait(150)
    if preview:
        panel=p.grab();pet=companion.pet.grab()
        # Composite the two actual widgets onto a neutral desktop for preview.
        width=p.width()+companion.pet.width()+110
        height=max(p.height()+60,companion.pet.height()+150)
        image=QImage(width,height,QImage.Format.Format_ARGB32);image.fill(QColor("#F0EDE2"))
        painter=QPainter(image);painter.drawPixmap(30,30,panel)
        painter.drawPixmap(p.width()+70,height-companion.pet.height()-35,pet);painter.end()
        Path(preview).parent.mkdir(parents=True,exist_ok=True)
        if not image.save(str(preview)):raise RuntimeError("Could not save preview")
    print("PASS: start, pause, resume, panel hide/restore, completion, no duplicate credit, break, restart")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--smoke-test",action="store_true")
    parser.add_argument('--vision-smoke-test',action='store_true')
    parser.add_argument('--companion-smoke-test',action='store_true')
    parser.add_argument('--chat-smoke-test',action='store_true')
    parser.add_argument('--music-smoke-test',action='store_true')
    parser.add_argument('--open-chat',action='store_true',help='Open the DeepSeek chat panel')
    parser.add_argument('--vision-fixtures',type=Path)
    parser.add_argument("--preview-path",type=Path)
    parser.add_argument("--quit",action="store_true",help="Gracefully close the running companion")
    parser.add_argument("--profile-dir",type=Path,help="Use a separate local profile for desktop interaction testing")
    args=parser.parse_args()
    app=QApplication(sys.argv);app.setApplicationName("MomoStudyPet")
    app.setOrganizationName("Momo");app.setApplicationDisplayName("雨衣皮卡丘学习搭子")
    app.setQuitOnLastWindowClosed(False);app.setStyle("Fusion");app.setStyleSheet(STYLE)
    app_font=QFont("Microsoft YaHei UI",10)
    app_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(app_font)
    app.setWindowIcon(pet_icon())
    testing=args.smoke_test or args.vision_smoke_test or args.companion_smoke_test or args.chat_smoke_test or args.music_smoke_test
    temporary=tempfile.TemporaryDirectory(prefix="momo-smoke-") if testing else None
    directory=Path(temporary.name) if temporary else (args.profile_dir.resolve() if args.profile_dir else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)))
    directory.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=directory/"momo.log",encoding="utf-8",level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")
    server=None
    if not testing:
        server_name="MomoStudyPet-"+str(directory).replace("\\","-").replace(":","")
        socket=QLocalSocket();socket.connectToServer(server_name)
        if socket.waitForConnected(500):
            socket.write(b"quit" if args.quit else b"chat" if args.open_chat else b"show");socket.waitForBytesWritten(500);socket.disconnectFromServer()
            return 0
        if args.quit:return 0
        server=QLocalServer()
        if not server.listen(server_name):
            QLocalServer.removeServer(server_name)
            if not server.listen(server_name):raise RuntimeError("Unable to create the local app instance")
    companion=Companion(Store(directory),tray_enabled=not testing)
    if args.open_chat and not testing:companion.show_chat()
    if server:
        def activate():
            while server.hasPendingConnections():
                connection=server.nextPendingConnection()
                def receive(c=connection):
                    message=bytes(c.readAll()).decode("utf-8",errors="replace")
                    if not message:return
                    if message.strip()=="quit":companion.quit()
                    elif message.strip()=='chat':companion.show_chat()
                    else:companion.restore()
                    c.close();c.deleteLater()
                connection.readyRead.connect(receive)
                if connection.bytesAvailable():receive()
        server.newConnection.connect(activate)
    if testing:
        result={"code":0}
        def run_test():
            try:
                if args.music_smoke_test:
                    from study_pet.music_smoke import run
                    run(companion,args.preview_path)
                elif args.chat_smoke_test:
                    from study_pet.chat_smoke import run
                    run(companion,args.preview_path)
                elif args.companion_smoke_test:
                    from study_pet.companion_smoke import run
                    run(companion,args.preview_path)
                elif args.vision_smoke_test:
                    from study_pet.vision_smoke import run
                    run(companion,args.preview_path,args.vision_fixtures)
                else:smoke_test(companion,args.preview_path)
            except Exception:
                import traceback;traceback.print_exc();result["code"]=1
                if args.preview_path:
                    args.preview_path.parent.mkdir(parents=True,exist_ok=True)
                    args.preview_path.with_suffix('.error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            finally:
                companion.shutdown_chat()
                companion.shutdown_vision()
                companion.shutdown_music()
                companion.timer.stop()
                companion.pet.canvas._animation.stop()
                companion.pet.canvas._click_timer.stop()
                companion.pet._bubble_timer.stop()
                companion.pet._mood_timer.stop()
                companion.pet._screen_timer.stop()
                companion.panel.hide()
                if companion.history_panel is not None:companion.history_panel.hide()
                companion.pet.hide()
                app.quit()
        QTimer.singleShot(250,run_test)
        app.exec();logging.shutdown();temporary.cleanup()
        return result["code"]
    return app.exec()


if __name__=="__main__":
    try:sys.exit(main())
    except Exception:
        if any(flag in sys.argv for flag in ('--smoke-test','--vision-smoke-test','--companion-smoke-test','--chat-smoke-test','--music-smoke-test')):
            raise
        logging.exception("皮卡丘启动失败")
        from PySide6.QtWidgets import QMessageBox
        app=QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None,"皮卡丘启动失败","程序遇到了问题，请查看本地应用数据中的 momo.log，或从终端运行 main.py。")
        raise
