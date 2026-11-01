# -*- mode: python ; coding: utf-8 -*-
# Smart Assistant Desktop Client (.exe) Production Spec

import os

block_cipher = None

datas = [
    ('dashboard/static', 'dashboard/static'),
    ('modules/reverse_engineering/rea_runtime', 'modules/reverse_engineering/rea_runtime'),
    ('modules/reverse_engineering/bin/PROVENANCE.md', 'modules/reverse_engineering/bin'),
]
if os.path.exists('skills/device_management/resources'):
    datas.append(('skills/device_management/resources', 'skills/device_management/resources'))
if os.path.exists('legacy/icon.ico'):
    datas.append(('legacy/icon.ico', 'legacy'))

a = Analysis(
    ['assistant.py'],
    pathex=['.'],
    binaries=[
        ('modules/reverse_engineering/bin/node.exe', 'modules/reverse_engineering/bin'),
    ],
    datas=datas,
    hiddenimports=[
        'core.api_client',
        'core.credential_manager',
        'instance.config',
        'modules.reverse_engineering',
        'modules.reverse_engineering.rea_service',
        'modules.reverse_engineering.mcp_client',
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
        'skills.device_management',
        'skills.device_management.adb_adapter',
        'skills.device_management.platform_adapter',
        'skills.device_management.device_controller',
        'skills.device_management.device_registry',
        'skills.device_management.device_pairing',
        'skills.device_management.device_dispatcher',
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
    upx=False,
    upx_exclude=['node.exe'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='legacy/icon.ico' if os.path.exists('legacy/icon.ico') else None,
)
