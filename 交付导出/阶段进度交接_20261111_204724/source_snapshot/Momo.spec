# -*- mode: python ; coding: utf-8 -*-
from pathlib import PurePath
import sys
from PyInstaller.utils.hooks import collect_all, copy_metadata

mp_datas, mp_binaries, mp_hidden = collect_all('mediapipe')
camera_datas, camera_binaries, camera_hidden = collect_all('cv2_enumerate_cameras')
# delvewheel stores the enumeration helper's DLL next to the package.
from pathlib import Path
import cv2_enumerate_cameras
camera_libs = Path(cv2_enumerate_cameras.__file__).parent.parent/'cv2_enumerate_cameras.libs'
if camera_libs.is_dir():
    camera_binaries += [(str(path),'cv2_enumerate_cameras.libs') for path in camera_libs.glob('*.dll')]
model_files = ['face_landmarker.task','hand_landmarker.task','phone_yolov8s.onnx','manifest.json','NOTICE.md','ULTRALYTICS-LICENSE.txt']
model_datas = [(str(Path('assets/models')/name),'assets/models') for name in model_files]

a = Analysis(
    ['main.py'], pathex=[], binaries=mp_binaries+camera_binaries,
    datas=[('assets/raincoat-reference.png','assets')]+model_datas+mp_datas+camera_datas+copy_metadata('mediapipe')+copy_metadata('onnxruntime'),
    hiddenimports=mp_hidden+camera_hidden,
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['torch','torchvision','ultralytics','IPython','pytest','tkinter'],
    noarchive=False, optimize=0,
)
if sys.platform == 'win32':
    # Qt's Windows wheel uses the ICU API shipped by Windows. Some build hosts
    # expose a different ICU with version-suffixed symbols on PATH; bundling that
    # library shadows the system DLL and causes QtCore to fail on import.
    a.binaries = [entry for entry in a.binaries
                  if PurePath(entry[0]).name.lower() not in {'icuuc.dll', 'icudt78.dll'}]

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name='Momo',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, icon='assets/pikachu.ico',
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Momo')
