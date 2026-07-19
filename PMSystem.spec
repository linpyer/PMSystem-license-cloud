# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)
from PyInstaller.utils.hooks import collect_submodules

from app.core.version import APP_NAME, APP_VERSION


PROJECT_ROOT = Path(SPECPATH).resolve()
APP_ICON = PROJECT_ROOT / 'app' / 'assets' / 'app_icon.ico'
ASSETS_DIR = PROJECT_ROOT / 'app' / 'assets'
FFMPEG_DIR = PROJECT_ROOT / 'tools' / 'ffmpeg'
FFMPEG_EXE = FFMPEG_DIR / 'ffmpeg.exe'
FFPROBE_EXE = FFMPEG_DIR / 'ffprobe.exe'
if not APP_ICON.is_file():
    raise FileNotFoundError(f'正式应用图标不存在，停止构建：{APP_ICON}')
for required_tool in (FFMPEG_EXE, FFPROBE_EXE):
    if not required_tool.is_file():
        raise FileNotFoundError(f'正式录制工具不存在，停止构建：{required_tool}')

version_parts = tuple(int(part) for part in APP_VERSION.split("."))
version_tuple = (version_parts + (0, 0, 0, 0))[:4]
version_resource = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=version_tuple,
        prodvers=version_tuple,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo([
            StringTable("080404b0", [
                StringStruct("CompanyName", "JsonLin"),
                StringStruct("FileDescription", APP_NAME),
                StringStruct("FileVersion", f"{APP_VERSION}.0"),
                StringStruct("InternalName", APP_NAME),
                StringStruct("LegalCopyright", "Copyright (C) JsonLin"),
                StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", f"{APP_VERSION}.0"),
            ])
        ]),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)


a = Analysis(
    [str(PROJECT_ROOT / 'main.py')],
    pathex=[str(PROJECT_ROOT)],
    binaries=[
        (str(FFMPEG_EXE), 'tools\\ffmpeg'),
        (str(FFPROBE_EXE), 'tools\\ffmpeg'),
    ],
    datas=[(str(ASSETS_DIR), 'app\\assets')],
    hiddenimports=[
        'sqlite3',
        'requests',
        'pyttsx3',
        'pyttsx3.drivers',
        'pyttsx3.drivers.sapi5',
        *collect_submodules('cryptography'),
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
    name='电商打包发货监控溯源系统',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_resource,
    icon=[str(APP_ICON)],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['ffmpeg.exe', 'ffprobe.exe'],
    name='电商打包发货监控溯源系统',
)
