# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for the one-file, no-console Chopped executable.
#
#   python tools/make_icon.py                          # icon + version resource -> build/gen/
#   python -m PyInstaller --noconfirm --clean Chopped.spec
#
# build_windows.bat, build_linux.sh and the GitHub Actions workflow all do
# exactly this, so there is one recipe instead of three slightly different ones.
import os

from PyInstaller.utils.hooks import collect_submodules

gen = os.path.join(SPECPATH, 'build', 'gen')
icon = os.path.join(gen, 'chopped.ico')
version = os.path.join(gen, 'version_info.txt')

hiddenimports = collect_submodules('chopped')
try:
    import miniupnpc  # noqa: F401  -- optional; the game shrugs and says "forward UDP 27015" without it
    hiddenimports.append('miniupnpc')
except ImportError:
    print('!! miniupnpc not installed: building without UPnP (the game still works)')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # stdlib bits we never touch; smaller exe, fewer things for antivirus to squint at
    excludes=['tkinter', 'unittest', 'pydoc', 'test', 'lib2to3'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Chopped',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # UPX-packed exes are antivirus bait. 20 MB is fine.
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,   # a crash shows a traceback dialog instead of vanishing
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[icon] if os.path.exists(icon) else None,
    version=version if (os.path.exists(version) and os.name == 'nt') else None,
)
