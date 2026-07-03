# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('packaging/app_icon.ico', 'packaging')],
    hiddenimports=['novel_app', 'novel_app.agents', 'novel_app.analysis', 'novel_app.audit', 'novel_app.core', 'novel_app.db', 'novel_app.rag', 'novel_app.state', 'novel_app.structured_templates', 'novel_app.theme', 'novel_app.truth', 'lingshu_api', 'qdrant_client', 'fastapi', 'uvicorn', 'slowapi', 'bcrypt'],
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
    a.binaries,
    a.datas,
    [],
    name='灵枢',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
