# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for RadioMaster — portable --onedir build (no --onefile: that
# extracts to %TEMP% on every launch, which breaks portability).

import os
import pycountry

# pycountry's language/country lookups (used for canonical "By Language"
# grouping) read their data from JSON files under its own package directory
# at runtime — PyInstaller's import analysis doesn't pick these up
# automatically since they're not imported as Python modules. Only the
# ~1.5MB `databases` dir is needed (the actual ISO tables); the ~20MB
# `locales` dir is gettext translations of language/country display names
# that nothing in this app ever requests, so it's deliberately excluded.
_pycountry_dir = os.path.dirname(pycountry.__file__)

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('radiomaster/resources/ffmpeg/ffmpeg.exe', 'radiomaster/resources/ffmpeg'),
        ('radiomaster/resources/ffmpeg/ffprobe.exe', 'radiomaster/resources/ffmpeg'),
        ('radiomaster/resources/ffmpeg/FFMPEG-LICENSE.txt', 'radiomaster/resources/ffmpeg'),
        ('radiomaster/resources/fpcalc/fpcalc.exe', 'radiomaster/resources/fpcalc'),
        ('radiomaster/resources/fpcalc/CHROMAPRINT-LICENSE.md', 'radiomaster/resources/fpcalc'),
        ('radiomaster/resources/bass/bass.dll', 'radiomaster/resources/bass'),
        ('radiomaster/resources/bass/bass_fx.dll', 'radiomaster/resources/bass'),
        ('radiomaster/resources/bass/bassmix.dll', 'radiomaster/resources/bass'),
        ('radiomaster/resources/bass/BASS-LICENSE.txt', 'radiomaster/resources/bass'),
        (os.path.join(_pycountry_dir, 'databases'), 'pycountry/databases'),
    ],
    hiddenimports=[
        'wx.adv',
        'apscheduler.triggers.cron',
        'apscheduler.triggers.date',
        'apscheduler.triggers.interval',
        'apscheduler.schedulers.background',
        'acoustid',
        'audioread',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RadioMaster',
    debug=False,
    bootloader_ignore_signals=False,
    contents_directory='.',
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RadioMaster',
)
