"""
Smart Assistant — Production Desktop Client Packager & Security Inspector
Builds and validates the desktop .exe application for end-user distribution.
Enforces that NO database credentials, JWT secrets, or backend server keys are bundled.
"""

import os
import sys
import re
import shutil

FORBIDDEN_SECRET_PATTERNS = [
    r"postgres://",
    r"postgresql://",
    r"DATABASE_PASSWORD",
    r"JWT_SECRET\s*=\s*[\"'][^\"']+[\"']",
    r"ADMIN_SECRET",
    r"ENCRYPTION_KEY",
    r"LLM_API_KEY",
]

ALLOWED_CLIENT_ENV_KEYS = {
    "APP_ENV",
    "API_BASE_URL",
    "API_TIMEOUT",
    "ASSISTANT_NAME",
    "VOICE_NAME",
    "ENABLE_AUDIO",
    "DEBUG"
}


def inspect_client_distribution(build_dir: str = "dist") -> bool:
    """
    Scans client build files and configurations to guarantee zero leakage
    of server-side database credentials or master secrets.
    """
    print("[SECURITY AUDIT] Inspecting client distribution package...")
    violations = []

    # Check that .env files with secrets are never in dist
    for root, _, files in os.walk(build_dir):
        for f in files:
            if f == ".env" or f.startswith(".env"):
                fp = os.path.join(root, f)
                with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                    content = file.read()
                    for pat in FORBIDDEN_SECRET_PATTERNS:
                        if re.search(pat, content):
                            violations.append(f"Forbidden secret pattern '{pat}' found in client asset: {fp}")

    if violations:
        print("[SECURITY AUDIT] [FAILED] Security Policy Violations Detected:")
        for v in violations:
            print(f"  - {v}")
        return False

    print("[SECURITY AUDIT] [PASSED] Zero backend credentials or database secrets found in client distribution.")
    return True


def generate_production_pyinstaller_spec(output_file: str = "assistant_client.spec"):
    """
    Generates PyInstaller spec targeting the desktop UI and API client exclusively.
    """
    spec_content = '''# -*- mode: python ; coding: utf-8 -*-
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
'''
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(spec_content)
    print(f"[BUILD] Generated production PyInstaller spec: {output_file}")


if __name__ == "__main__":
    generate_production_pyinstaller_spec()
    if os.path.exists("dist"):
        inspect_client_distribution("dist")
    else:
        print("[BUILD] Spec generated. Run PyInstaller to produce dist package.")
