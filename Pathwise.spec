# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for Pathwise.exe. Sidecar secrets are never baked in."""

from PyInstaller.utils.hooks import collect_all, collect_submodules

from pathwise.packaging import filter_pyinstaller_datas

arcade_datas, arcade_binaries, arcade_hidden = collect_all("arcade")
pyglet_datas, pyglet_binaries, pyglet_hidden = collect_all("pyglet")

hiddenimports = []
hiddenimports += arcade_hidden
hiddenimports += pyglet_hidden
hiddenimports += collect_submodules("pathwise")
hiddenimports += collect_submodules("analytics")
hiddenimports += collect_submodules("map_generation")
hiddenimports += ["argon2", "argon2.low_level", "main"]

datas = [
    ("pathwise/recruiter_schema.sql", "pathwise"),
    ("pathwise.env.example", "."),
    (".env.example", "."),
    ("docs/RECRUITER.md", "."),
]
datas += filter_pyinstaller_datas(arcade_datas)
datas += pyglet_datas

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=arcade_binaries + pyglet_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# Arcade's bundled hook adds dest ./arcade/VERSION as a directory after Analysis.
a.datas = filter_pyinstaller_datas(a.datas)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Pathwise",
    debug=False,
    bootloader_ignore_signals=False,
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
    name="Pathwise",
)
