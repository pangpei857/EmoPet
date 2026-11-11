# -*- mode: python ; coding: utf-8 -*-
from pathlib import PurePath
import sys

a = Analysis(
    ['main.py'], pathex=[], binaries=[], datas=[('assets/raincoat-reference.png','assets')], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
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
