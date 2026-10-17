# -*- mode: python ; coding: utf-8 -*-
# Smart Assistant Desktop Client (.exe) Production Spec

block_cipher = None

a = Analysis(
    ['assistant.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('dashboard/static', 'dashboard/static'),
        ('legacy/icon.ico', 'legacy'),
    ],
    hiddenimports=[
        'core.api_client',
        'core.credential_manager',
        'instance.config',
        'modules.ui.pyqt_app',
        'modules.ui.login_window',
        'modules.ui.floating_launcher',
        'modules.ui.dashboard.main_window',
        'modules.ui.dashboard.service_adapters',
        'modules.ui.dashboard.workers',
        'modules.ui.dashboard.ds',
        'modules.ui.design_system',
        'modules.ui.visual_response_surface',
        'modules.ui.notification_toast',
        'modules.ui.worker_threads',
        'PyQt6',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'requests',
        'urllib3',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'psycopg2',
        'psycopg2.pool',
        'pgvector',
        'core.db_pool',
        'core.migration_runner',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SmartAssistant',
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
    icon='legacy/icon.ico',
)
