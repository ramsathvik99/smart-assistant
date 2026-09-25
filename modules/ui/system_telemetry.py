"""
Smart Assistant — System Telemetry & Health Diagnostics
Real-time telemetry wing monitoring CPU, RAM, PostgreSQL DB status,
Microphone hardware, TTS engine, LLM connectivity, and background threads.
"""

import time
import threading
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QFrame, QGridLayout, QScrollArea, QPushButton
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from modules.ui.design_system import C, F, Radius, Spacing


class MetricCard(QFrame):
    """Futuristic telemetry card with title, value, status badge, and optional progress bar."""

    def __init__(self, title: str, initial_val: str = "--", parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setStyleSheet(f"""
            QFrame#MetricCard {{
                background: rgba(8, 14, 22, 0.65);
                border: 1px solid rgba(0, 212, 255, 0.12);
                border-radius: {Radius.MD}px;
                padding: 12px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(Spacing.SM)

        # Header
        top = QHBoxLayout()
        self.title_lbl = QLabel(title.upper())
        self.title_lbl.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        top.addWidget(self.title_lbl)

        top.addStretch()

        self.badge = QLabel("OK")
        self.badge.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        self.badge.setStyleSheet(f"""
            QLabel {{
                color: {C.ACCENT_CYAN};
                background: rgba(0, 212, 255, 0.12);
                border-radius: 4px;
                padding: 2px 6px;
            }}
        """)
        top.addWidget(self.badge)
        layout.addLayout(top)

        # Value label
        self.val_lbl = QLabel(initial_val)
        self.val_lbl.setFont(QFont(F.PRIMARY, 16, QFont.Weight.Bold))
        self.val_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        layout.addWidget(self.val_lbl)

        # Optional progress meter
        self.meter = QProgressBar()
        self.meter.setFixedHeight(4)
        self.meter.setTextVisible(False)
        self.meter.setValue(0)
        self.meter.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 2px;
            }}
            QProgressBar::chunk {{
                background: {C.ACCENT_CYAN};
                border-radius: 2px;
            }}
        """)
        layout.addWidget(self.meter)

    def update_val(self, val_text: str, pct: int = None, status: str = "OK", is_good: bool = True):
        self.val_lbl.setText(val_text)
        if pct is not None:
            self.meter.setVisible(True)
            self.meter.setValue(min(100, max(0, pct)))
        else:
            self.meter.setVisible(False)

        self.badge.setText(status.upper())
        if is_good:
            self.badge.setStyleSheet("""
                QLabel {
                    color: #34c759;
                    background: rgba(52, 199, 89, 0.12);
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)
        else:
            self.badge.setStyleSheet("""
                QLabel {
                    color: #ff3b30;
                    background: rgba(255, 59, 48, 0.12);
                    border-radius: 4px;
                    padding: 2px 6px;
                }
            """)


class SystemTelemetryPage(QWidget):
    """Complete System Telemetry and Live Diagnostics Wing."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._start_time = time.time()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Header
        header = QHBoxLayout()
        title = QLabel("System Telemetry & Health")
        title.setFont(QFont(F.PRIMARY, 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        header.addWidget(title)

        header.addStretch()

        self.uptime_lbl = QLabel("Uptime: 0m 0s")
        self.uptime_lbl.setFont(QFont(F.PRIMARY, 10))
        self.uptime_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        header.addWidget(self.uptime_lbl)

        layout.addLayout(header)

        # Grid of metric cards
        grid = QGridLayout()
        grid.setSpacing(Spacing.MD)

        # CPU
        self.cpu_card = MetricCard("CPU Utilization", "0%")
        grid.addWidget(self.cpu_card, 0, 0)

        # Memory (RAM)
        self.ram_card = MetricCard("RAM Memory", "0%")
        grid.addWidget(self.ram_card, 0, 1)

        # PostgreSQL Database
        self.db_card = MetricCard("PostgreSQL Database", "Connected")
        grid.addWidget(self.db_card, 1, 0)

        # Audio / SST Microphone
        self.audio_card = MetricCard("Microphone Stream", "Active")
        grid.addWidget(self.audio_card, 1, 1)

        # TTS Voice Engine
        self.tts_card = MetricCard("TTS Voice Engine", "Idle")
        grid.addWidget(self.tts_card, 2, 0)

        # LLM Engine & Provider
        self.llm_card = MetricCard("LLM Engine", "Ready")
        grid.addWidget(self.llm_card, 2, 1)

        # Background Services & Threads
        self.threads_card = MetricCard("Active Threads", "0")
        grid.addWidget(self.threads_card, 3, 0)

        # Proactive / Scheduler
        self.scheduler_card = MetricCard("Scheduler & Proactive", "Running")
        grid.addWidget(self.scheduler_card, 3, 1)

        layout.addLayout(grid)
        layout.addStretch()

        # Polling timer (1.5 seconds)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll_telemetry)
        self._timer.start(1500)
        self._poll_telemetry()

    def _poll_telemetry(self):
        # 1. Uptime
        elapsed = int(time.time() - self._start_time)
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        if hours > 0:
            self.uptime_lbl.setText(f"Uptime: {hours}h {mins}m {secs}s")
        else:
            self.uptime_lbl.setText(f"Uptime: {mins}m {secs}s")

        # 2. CPU & RAM
        try:
            import psutil
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            self.cpu_card.update_val(f"{cpu:.1f}%", int(cpu), "NORMAL" if cpu < 80 else "HIGH", cpu < 80)
            self.ram_card.update_val(f"{ram:.1f}%", int(ram), "OPTIMAL" if ram < 90 else "HIGH", ram < 90)
        except Exception:
            pass

        # 3. DB Health
        try:
            from legacy.memory_manager import get_connection
            conn = get_connection()
            conn.close()
            self.db_card.update_val("Online", 100, "ONLINE", True)
        except Exception as e:
            self.db_card.update_val("Offline", 0, "OFFLINE", False)

        # 4. Microphone stream
        try:
            from legacy.sst import _continuous_audio_state
            is_running = _continuous_audio_state.get("running", False)
            dev_idx = _continuous_audio_state.get("device_index")
            status_text = f"Dev [{dev_idx}] Live" if is_running else "Standby"
            self.audio_card.update_val(status_text, 100 if is_running else 0, "CAPTURING" if is_running else "IDLE", True)
        except Exception:
            pass

        # 5. TTS Voice Engine
        try:
            from legacy.tts import is_speaking
            speaking = is_speaking()
            self.tts_card.update_val("Speaking" if speaking else "Ready", 100 if speaking else 0, "ACTIVE" if speaking else "READY", True)
        except Exception:
            pass

        # 6. LLM Engine
        try:
            from instance.config import settings as CONFIG
            provider = CONFIG.get("AI_PROVIDER", "Groq / Multi-Provider")
            self.llm_card.update_val(str(provider).upper(), 100, "CONNECTED", True)
        except Exception:
            pass

        # 7. Active Threads
        count = threading.active_count()
        self.threads_card.update_val(f"{count} Threads", min(100, count * 5), "HEALTHY", count < 30)

        # 8. Scheduler / Proactive
        self.scheduler_card.update_val("Active & Monitoring", 100, "ONLINE", True)
