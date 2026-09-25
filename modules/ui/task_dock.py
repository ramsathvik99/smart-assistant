"""
Smart Assistant — Task Dock
Multi-step task progress visualizer and execution monitor.
Displays real-time planner steps, active tool status, progress bar,
and control actions (cancel, retry).
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QScrollArea, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QFont

from modules.ui.design_system import C, F, Radius, Spacing


class TaskStepCard(QFrame):
    """Visual card for a single step in a multi-step task."""

    def __init__(self, step_num: int, title: str, tool: str = "", status: str = "pending", parent=None):
        super().__init__(parent)
        self.step_num = step_num
        self.status = status
        self.setObjectName("TaskStepCard")

        self._apply_style()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(Spacing.MD)

        # Step indicator icon
        self.status_icon = QLabel()
        self.status_icon.setFont(QFont(F.PRIMARY, 12, QFont.Weight.Bold))
        self.status_icon.setFixedSize(24, 24)
        self.status_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_icon)

        # Info layout
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self.title_lbl = QLabel(f"Step {step_num}: {title}")
        self.title_lbl.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Medium))
        self.title_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        info_layout.addWidget(self.title_lbl)

        self.tool_lbl = QLabel(f"Tool: {tool}" if tool else "Action")
        self.tool_lbl.setFont(QFont(F.PRIMARY, 9))
        self.tool_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        info_layout.addWidget(self.tool_lbl)

        layout.addLayout(info_layout, 1)

        # Status badge
        self.badge = QLabel(status.upper())
        self.badge.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        self.badge.setStyleSheet(self._badge_style())
        layout.addWidget(self.badge)

        self.set_status(status)

    def set_status(self, status: str):
        self.status = status.lower()
        if self.status == "pending":
            self.status_icon.setText("○")
            self.status_icon.setStyleSheet(f"color: {C.TEXT_MUTED};")
        elif self.status == "running":
            self.status_icon.setText("▶")
            self.status_icon.setStyleSheet(f"color: {C.ACCENT_CYAN};")
        elif self.status == "success":
            self.status_icon.setText("✓")
            self.status_icon.setStyleSheet("color: #34c759;")
        elif self.status == "failed":
            self.status_icon.setText("✕")
            self.status_icon.setStyleSheet("color: #ff3b30;")
        self.badge.setText(self.status.upper())
        self.badge.setStyleSheet(self._badge_style())
        self._apply_style()

    def _badge_style(self) -> str:
        color_map = {
            "pending": (C.TEXT_MUTED, "rgba(255,255,255,0.05)"),
            "running": (C.ACCENT_CYAN, "rgba(0,212,255,0.15)"),
            "success": ("#34c759", "rgba(52,199,89,0.15)"),
            "failed":  ("#ff3b30", "rgba(255,59,48,0.15)")
        }
        text_col, bg_col = color_map.get(self.status, (C.TEXT_MUTED, "rgba(255,255,255,0.05)"))
        return f"""
            QLabel {{
                color: {text_col};
                background: {bg_col};
                border-radius: 4px;
                padding: 3px 8px;
            }}
        """

    def _apply_style(self):
        border_col = "rgba(0, 212, 255, 0.4)" if self.status == "running" else "rgba(255, 255, 255, 0.08)"
        bg_col = "rgba(0, 212, 255, 0.04)" if self.status == "running" else "rgba(8, 14, 22, 0.6)"
        self.setStyleSheet(f"""
            QFrame#TaskStepCard {{
                background: {bg_col};
                border: 1px solid {border_col};
                border-radius: {Radius.MD}px;
            }}
        """)


class TaskDock(QWidget):
    """Complete Task and Execution monitor dock widget."""

    cancel_requested = pyqtSignal()
    retry_requested  = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._steps = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(Spacing.MD)

        self.title_lbl = QLabel("Task Execution Monitor")
        self.title_lbl.setFont(QFont(F.PRIMARY, 14, QFont.Weight.Bold))
        self.title_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        header.addWidget(self.title_lbl)

        header.addStretch()

        self.state_badge = QLabel("IDLE")
        self.state_badge.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
        self.state_badge.setStyleSheet(f"""
            QLabel {{
                color: {C.TEXT_MUTED};
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 4px 10px;
            }}
        """)
        header.addWidget(self.state_badge)

        self.cancel_btn = QPushButton("Stop Task")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Medium))
        self.cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 59, 48, 0.15);
                color: #ff3b30;
                border: 1px solid rgba(255, 59, 48, 0.3);
                border-radius: 6px;
                padding: 4px 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 59, 48, 0.3);
            }}
        """)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        header.addWidget(self.cancel_btn)

        layout.addLayout(header)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255, 255, 255, 0.08);
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {C.ACCENT_CYAN}, stop:1 #7000ff);
                border-radius: 3px;
            }}
        """)
        layout.addWidget(self.progress_bar)

        # Description label
        self.desc_lbl = QLabel("No active task. Spoken or typed multi-step operations will be tracked here.")
        self.desc_lbl.setFont(QFont(F.PRIMARY, 11))
        self.desc_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        self.desc_lbl.setWordWrap(True)
        layout.addWidget(self.desc_lbl)

        # Scrollable steps area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        self.steps_container = QWidget()
        self.steps_container.setStyleSheet("background: transparent;")
        self.steps_layout = QVBoxLayout(self.steps_container)
        self.steps_layout.setContentsMargins(0, 0, 0, 0)
        self.steps_layout.setSpacing(Spacing.SM)
        self.steps_layout.addStretch()

        scroll.setWidget(self.steps_container)
        layout.addWidget(scroll, 1)

    def set_task(self, title: str, description: str, steps: list):
        """Configure a new active multi-step task."""
        self.clear_steps()
        self.title_lbl.setText(title or "Executing Task")
        self.desc_lbl.setText(description or "")
        self.state_badge.setText("RUNNING")
        self.state_badge.setStyleSheet(f"""
            QLabel {{
                color: {C.ACCENT_CYAN};
                background: rgba(0, 212, 255, 0.15);
                border: 1px solid rgba(0, 212, 255, 0.3);
                border-radius: 6px;
                padding: 4px 10px;
            }}
        """)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        for i, s in enumerate(steps):
            step_title = s if isinstance(s, str) else s.get("title", f"Step {i+1}")
            tool = "" if isinstance(s, str) else s.get("tool", "")
            card = TaskStepCard(i + 1, step_title, tool=tool, status="pending")
            self._steps.append(card)
            self.steps_layout.insertWidget(len(self._steps) - 1, card)

    def update_step_status(self, step_idx: int, status: str):
        """Update the status of a specific step (0-indexed)."""
        if 0 <= step_idx < len(self._steps):
            self._steps[step_idx].set_status(status)

            # Update overall progress
            completed = sum(1 for c in self._steps if c.status == "success")
            pct = int((completed / len(self._steps)) * 100) if self._steps else 0
            self.progress_bar.setValue(pct)

            if completed == len(self._steps):
                self.complete_task(success=True)

    def complete_task(self, success: bool = True, message: str = ""):
        self.cancel_btn.setEnabled(False)
        if success:
            self.state_badge.setText("COMPLETED")
            self.state_badge.setStyleSheet("""
                QLabel {
                    color: #34c759;
                    background: rgba(52, 199, 89, 0.15);
                    border: 1px solid rgba(52, 199, 89, 0.3);
                    border-radius: 6px;
                    padding: 4px 10px;
                }
            """)
            self.progress_bar.setValue(100)
            if message:
                self.desc_lbl.setText(message)
        else:
            self.state_badge.setText("FAILED")
            self.state_badge.setStyleSheet("""
                QLabel {
                    color: #ff3b30;
                    background: rgba(255, 59, 48, 0.15);
                    border: 1px solid rgba(255, 59, 48, 0.3);
                    border-radius: 6px;
                    padding: 4px 10px;
                }
            """)
            if message:
                self.desc_lbl.setText(message)

    def clear_steps(self):
        for card in self._steps:
            self.steps_layout.removeWidget(card)
            card.deleteLater()
        self._steps.clear()
        self.progress_bar.setValue(0)
        self.state_badge.setText("IDLE")
        self.state_badge.setStyleSheet(f"""
            QLabel {{
                color: {C.TEXT_MUTED};
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 4px 10px;
            }}
        """)
        self.cancel_btn.setEnabled(False)
