# -*- mode: python ; coding: utf-8 -*-
# ============================================================
# Smart Assistant — Production Desktop Client Spec
# Thin client build — UI only, communicates via HTTPS REST API
# Entry: client_main.py → modules/ui/client_app.py → core/api_client.py
# Note: 'python_dotenv' hidden import warning is harmless — package is 'dotenv'
# ============================================================

block_cipher = None

# ── Packages that MUST NOT enter the client binary ──────────────────────────
EXCLUDE_MODULES = [
    # ── Database / backend (server-side ONLY) ────────────────────────────── #
    'psycopg2', 'psycopg2.pool', 'psycopg2.extras', 'psycopg2.extensions',
    'pgvector', 'pgvector.psycopg2',
    'core.db_pool', 'core.migration_runner',
    'sqlalchemy', 'alembic',

    # ── ML / AI frameworks (server-side ONLY) ────────────────────────────── #
    'torch', 'torchvision', 'torchaudio',
    'tensorflow', 'tensorflow_core', 'keras',
    'sklearn', 'scikit_learn',
    'scipy',
    'transformers', 'tokenizers', 'accelerate',
    'sentence_transformers',
    'openai',

    # ── Data science (not needed in UI client) ───────────────────────────── #
    'pandas', 'pandas.core',
    'numpy',                        # pulled by PyQt6 multimedia — remove if safe
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.backends',
    'PIL', 'Pillow',
    'cv2', 'opencv', 'skimage',
    'seaborn', 'plotly', 'bokeh',

    # ── Testing / dev tools ──────────────────────────────────────────────── #
    'pytest', '_pytest', 'py', 'unittest',
    'IPython', 'ipykernel', 'ipython_genutils',
    'coverage', 'hypothesis',

    # ── Server-side backend modules ──────────────────────────────────────── #
    'flask', 'flask_cors', 'flask_jwt_extended', 'werkzeug',
    'dashboard.server',
    'legacy.assistant', 'legacy.memory_manager', 'legacy.auth_helpers',
    'extensions.assistant_orchestrator',
    'extensions.system',
    'extensions.reminder_engine',
    'extensions.database_manager',
    'extensions.proactive_interaction',

    # ── Build / packaging ────────────────────────────────────────────────── #
    'setuptools', 'pkg_resources', 'distutils',
    'pygments',
    'docutils', 'sphinx',
    'jinja2',
    'anyio', 'trio',
    'jupyter', 'nbformat', 'nbconvert',
]

a = Analysis(
    ['client_main.py'],          # ← thin-client entry point only
    pathex=['.'],
    binaries=[],
    datas=[
        ('dashboard/static', 'dashboard/static'),
        ('legacy/icon.ico',  'legacy'),
    ],
    hiddenimports=[
        # ── Client-side API layer ──────────────────────────────────────── #
        'core.api_client',
        'instance.config',

        # ── UI modules ─────────────────────────────────────────────────── #
        'modules.ui.client_app',
        'modules.ui.client_worker_threads',
        'modules.ui.design_system',
        'modules.ui.login_window',
        'modules.ui.floating_launcher',
        'modules.ui.dashboard.main_window',
        'modules.ui.dashboard.service_adapters',
        'modules.ui.dashboard.workers',
        'modules.ui.dashboard.ds',
        'modules.ui.dashboard.pages.home_page',
        'modules.ui.dashboard.pages.assistant_page',
        'modules.ui.dashboard.pages.communications_page',
        'modules.ui.dashboard.pages.workspace_page',
        'modules.ui.dashboard.pages.schedule_page',
        'modules.ui.dashboard.pages.automation_page',
        'modules.ui.dashboard.pages.connected_world_page',
        'modules.ui.dashboard.pages.intelligence_page',
        'modules.ui.dashboard.pages.settings_page',
        'modules.ui.notification_toast',
        'modules.ui.visual_response_surface',

        # ── PyQt6 ──────────────────────────────────────────────────────── #
        'PyQt6',
        'PyQt6.sip',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.QtMultimedia',
        'PyQt6.QtMultimediaWidgets',

        # ── Network ────────────────────────────────────────────────────── #
        'requests',
        'urllib3',
        'certifi',
        'charset_normalizer',
        'idna',

        # ── Audio / TTS (local — optional) ─────────────────────────────── #
        'pyttsx3',
        'pyttsx3.drivers',
        'pyttsx3.drivers.sapi5',
        'pyttsx3.drivers.dummy',
        'comtypes',
        'pythoncom',
        'pywintypes',

        # ── Dotenv / config ────────────────────────────────────────────── #
        'dotenv',
        'python_dotenv',
        'cryptography',
        'cryptography.fernet',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDE_MODULES,
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
    console=False,           # windowless GUI application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='legacy/icon.ico',
    version_file=None,
)
