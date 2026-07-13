# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

from app.core.version import APP_NAME, APP_VERSION


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
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app\\assets', 'app\\assets')],
    hiddenimports=['sqlite3', 'requests', 'pyttsx3', 'pyttsx3.drivers', 'pyttsx3.drivers.sapi5'],
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
    icon=['app\\assets\\app_icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='电商打包发货监控溯源系统',
)
