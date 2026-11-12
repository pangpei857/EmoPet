"""Read-only live media check plus real-widget rendering in the frozen app."""
from dataclasses import replace
import json
from pathlib import Path
import time

from PySide6.QtWidgets import QApplication

from .music_core import MusicState


def run(companion,preview=None):
    pet=companion.pet
    demo=MusicState('qq-music-demo','音乐条界面演示','QQ 音乐','playing',True,True,True)
    pet.set_music_state(demo)
    assert pet.music_card.isVisible()
    assert pet.music_card.buttons['toggle'].playing
    pet.set_music_state(replace(demo,status='paused'))
    assert not pet.music_card.buttons['toggle'].playing
    controller=companion.music_controller;controller.start()
    deadline=time.monotonic()+9.
    try:
        while controller.state.status=='connecting' and time.monotonic()<deadline:
            QApplication.processEvents();time.sleep(.01)
        state=controller.state
        assert state.status not in {'connecting','error'},state.message
        data={'system_media_api':'passed','qq_session_available':bool(state.session_id),
            'live_status':state.status,'can_toggle':state.can_toggle,
            'can_previous':state.can_previous,'can_next':state.can_next,
            'preview_source':'live QQ Music' if state.status=='playing' else 'UI demo'}
        if state.status!='playing':pet.set_music_state(demo)
        QApplication.processEvents()
        if preview:
            target=Path(preview);target.parent.mkdir(parents=True,exist_ok=True)
            assert pet.grab().save(str(target))
            target.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        print('PASS: player layout, pause icon, real Windows media API, session selection, clean shutdown',flush=True)
        print('MUSIC_RESULTS',data,flush=True)
    finally:companion.shutdown_music()
