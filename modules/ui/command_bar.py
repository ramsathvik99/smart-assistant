"""
Smart Assistant — Floating Command Bar
Translucent command input bar with voice button, send button,
attachment picker, and quick action chips matching Brahma CommandBar.
"""

import os
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QPushButton,
    QFrame, QLabel, QVBoxLayout, QSizePolicy, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor

from modules.ui.design_system import C, F, Radius, Spacing, hex_to_rgb


class CommandBar(QWidget):
    """
    Command bar with text input, voice trigger, file attachment,
    quick action chips, and state-aware styling.
    """

    submitted      = pyqtSignal(str)       # text command submitted
    mic_clicked    = pyqtSignal()          # mic button clicked
    chip_clicked   = pyqtSignal(str)       # quick chip action clicked
    file_attached  = pyqtSignal(str)       # file attached path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CommandBar")
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._attached_file = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── Quick Action Chips ──────────────────────────────────────
        self.chips_box = QHBoxLayout()
        self.chips_box.setSpacing(8)
        self.chips_box.setContentsMargins(4, 0, 4, 0)

        chips = [
            ("📝 Note", "note: "),
            ("⏰ Reminder", "set reminder for "),
            ("📊 Diagnostics", "system diagnostics"),
            ("🧠 Memory", "show memory"),
            ("🧹 Clear Chat", "__clear_chat__")
        ]
        self._chips = []
        for label, action in chips:
            btn = QPushButton(label)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Medium))
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0, 212, 255, 0.06);
                    color: {C.TEXT_MUTED};
                    border: 1px solid rgba(0, 212, 255, 0.18);
                    border-radius: 12px;
                    padding: 3px 10px;
                }}
                QPushButton:hover {{
                    background: rgba(0, 212, 255, 0.15);
                    color: {C.ACCENT_CYAN};
                    border: 1px solid {C.ACCENT_CYAN};
                }}
            """)
            btn.clicked.connect(lambda _, a=action: self._on_chip(a))
            self.chips_box.addWidget(btn)
            self._chips.append((btn, action))

        self.chips_box.addStretch()
        root.addLayout(self.chips_box)

        # ── Attachment Pill (Hidden by default) ────────────────────
        self.attach_pill = QFrame()
        self.attach_pill.setVisible(False)
        self.attach_pill.setStyleSheet(f"""
            QFrame {{
                background: rgba(0, 212, 255, 0.12);
                border: 1px solid rgba(0, 212, 255, 0.3);
                border-radius: 6px;
                padding: 2px 8px;
            }}
        """)
        pill_layout = QHBoxLayout(self.attach_pill)
        pill_layout.setContentsMargins(6, 2, 6, 2)
        pill_layout.setSpacing(6)

        self.attach_name_lbl = QLabel()
        self.attach_name_lbl.setFont(QFont(F.PRIMARY, 9))
        self.attach_name_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        pill_layout.addWidget(self.attach_name_lbl)

        remove_attach_btn = QPushButton("✕")
        remove_attach_btn.setFixedSize(16, 16)
        remove_attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_attach_btn.setStyleSheet("color: #ff3b30; background: transparent; border: none; font-weight: bold;")
        remove_attach_btn.clicked.connect(self.clear_attachment)
        pill_layout.addWidget(remove_attach_btn)
        pill_layout.addStretch()

        root.addWidget(self.attach_pill)

        # ── Main Input Frame ────────────────────────────────────────
        self._cmd_frame = QFrame()
        self._cmd_frame.setObjectName("CmdBarFrame")
        self._cmd_frame.setStyleSheet(f"""
            QFrame#CmdBarFrame {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0  rgba(6, 10, 15, 248),
                    stop:0.5 rgba(10, 16, 22, 248),
                    stop:1  rgba(6, 10, 15, 248));
                border: 1px solid rgba(0, 212, 255, 0.22);
                border-radius: {Radius.XL}px;
            }}
        """)
        lay = QHBoxLayout(self._cmd_frame)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        # Assistant mini-orb indicator
        self._orb = QFrame()
        self._orb.setFixedSize(32, 32)
        self._orb.setStyleSheet(f"""
            QFrame {{
                background: rgba(0, 212, 255, 0.07);
                border: 1.5px solid rgba(0, 212, 255, 0.30);
                border-radius: 16px;
            }}
        """)
        orb_lay = QVBoxLayout(self._orb)
        orb_lay.setContentsMargins(0, 0, 0, 0)
        self._orb_icon = QLabel("✦")
        self._orb_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._orb_icon.setFont(QFont(F.PRIMARY, 11, QFont.Weight.Bold))
        self._orb_icon.setStyleSheet(f"color: {C.ACC}; background: transparent; border: none;")
        orb_lay.addWidget(self._orb_icon)
        lay.addWidget(self._orb)

        # Input field
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command, ask a question, or drop a file…")
        self._input.setFont(QFont(F.PRIMARY, 13))
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                color: {C.TEXT};
                border: none;
                padding: 4px 6px;
                font-family: '{F.PRIMARY}';
                font-size: 13px;
                selection-background-color: rgba(0, 212, 255, 0.20);
            }}
            QLineEdit::placeholder {{
                color: {C.TEXT_DIM};
            }}
        """)
        self._input.returnPressed.connect(self._on_submit)
        lay.addWidget(self._input, 1)

        # Attach file button
        self._attach_btn = QPushButton("📎")
        self._attach_btn.setFixedSize(36, 36)
        self._attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_btn.setToolTip("Attach a file (or drag and drop into window)")
        self._attach_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT_MUTED};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: rgba(0, 212, 255, 0.15);
                color: {C.ACCENT_CYAN};
                border: 1px solid {C.ACCENT_CYAN};
            }}
        """)
        self._attach_btn.clicked.connect(self._choose_file)
        lay.addWidget(self._attach_btn)

        # Mic button
        self._mic_btn = QPushButton("🎤")
        self._mic_btn.setFixedSize(36, 36)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.setToolTip("Microphone (always listening via VAD)")
        self._mic_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 212, 255, 0.08);
                color: {C.ACC};
                border: 1px solid rgba(0, 212, 255, 0.22);
                border-radius: 18px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background: rgba(0, 212, 255, 0.16);
                border: 1px solid rgba(0, 212, 255, 0.45);
            }}
        """)
        self._mic_btn.clicked.connect(self.mic_clicked)
        lay.addWidget(self._mic_btn)

        # Send button
        self._send_btn = QPushButton("➤")
        self._send_btn.setFixedSize(36, 36)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setToolTip("Send command (Enter)")
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(0, 170, 220, 0.75), stop:1 rgba(0, 212, 255, 0.80));
                color: white;
                border: 1px solid rgba(0, 212, 255, 0.45);
                border-radius: 18px;
                font-size: 13px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 rgba(0, 190, 240, 0.90), stop:1 rgba(0, 230, 255, 0.90));
            }}
            QPushButton:pressed {{
                background: rgba(0, 140, 180, 0.70);
            }}
            QPushButton:disabled {{
                background: rgba(0, 50, 70, 0.40);
                color: rgba(255,255,255,0.25);
                border: 1px solid rgba(0, 212, 255, 0.08);
            }}
        """)
        self._send_btn.clicked.connect(self._on_submit)
        lay.addWidget(self._send_btn)

        root.addWidget(self._cmd_frame)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Attach File for Assistant", "", "All Files (*.*)")
        if path:
            self.attach_file(path)

    def attach_file(self, filepath: str):
        self._attached_file = filepath
        basename = os.path.basename(filepath)
        self.attach_name_lbl.setText(f"📄 {basename} ({filepath})")
        self.attach_pill.setVisible(True)
        self.file_attached.emit(filepath)

    def clear_attachment(self):
        self._attached_file = None
        self.attach_pill.setVisible(False)

    def _on_chip(self, action: str):
        if action == "__clear_chat__":
            self.chip_clicked.emit(action)
        elif action.endswith(" ") or action.endswith(": "):
            self._input.setText(action)
            self._input.setFocus()
        else:
            self.submitted.emit(action)

    def _on_submit(self):
        text = self._input.text().strip()
        if not text and not self._attached_file:
            return
        if self._attached_file:
            if text:
                text = f"{text} [File: {self._attached_file}]"
            else:
                text = f"Process file: {self._attached_file}"
            self.clear_attachment()

        self._input.clear()
        self.submitted.emit(text)

    def set_enabled_input(self, enabled: bool):
        self._input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)
        if not enabled:
            self._input.setPlaceholderText("Processing…")
        else:
            self._input.setPlaceholderText("Type a command, ask a question, or drop a file…")
            self._input.setFocus()

    def set_listening(self, active: bool):
        """Update mic button to show listening state."""
        accent = getattr(self, '_accent', C.ACC)
        r, g, b = hex_to_rgb(accent) if hasattr(self, '_accent') else (0, 212, 255)
        if active:
            self._mic_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({r}, {g}, {b}, 0.25);
                    color: {accent};
                    border: 1.5px solid {accent};
                    border-radius: 18px;
                    font-size: 14px;
                }}
            """)
        else:
            self._mic_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({r}, {g}, {b}, 0.08);
                    color: {accent};
                    border: 1px solid rgba({r}, {g}, {b}, 0.22);
                    border-radius: 18px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background: rgba({r}, {g}, {b}, 0.16);
                    border: 1px solid rgba({r}, {g}, {b}, 0.45);
                }}
            """)

    def set_accent_color(self, hex_color: str):
        """Update CommandBar styles to match the Dashboard accent color."""
        self._accent = hex_color
        r, g, b = hex_to_rgb(hex_color)

        # Chips
        for btn, _ in getattr(self, '_chips', []):
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({r}, {g}, {b}, 0.06);
                    color: {C.TEXT_MUTED};
                    border: 1px solid rgba({r}, {g}, {b}, 0.20);
                    border-radius: 12px;
                    padding: 3px 10px;
                }}
                QPushButton:hover {{
                    background: rgba({r}, {g}, {b}, 0.16);
                    color: {hex_color};
                    border: 1px solid {hex_color};
                }}
            """)

        # Attachment pill
        if hasattr(self, 'attach_pill'):
            self.attach_pill.setStyleSheet(f"""
                QFrame {{
                    background: rgba({r}, {g}, {b}, 0.12);
                    border: 1px solid rgba({r}, {g}, {b}, 0.35);
                    border-radius: 6px;
                    padding: 2px 8px;
                }}
            """)

        # Main input frame
        if hasattr(self, '_cmd_frame'):
            self._cmd_frame.setStyleSheet(f"""
                QFrame#CmdBarFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0  rgba(6, 10, 15, 248),
                        stop:0.5 rgba(10, 16, 22, 248),
                        stop:1  rgba(6, 10, 15, 248));
                    border: 1px solid rgba({r}, {g}, {b}, 0.28);
                    border-radius: {Radius.XL}px;
                }}
            """)

        # Orb
        if hasattr(self, '_orb'):
            self._orb.setStyleSheet(f"""
                QFrame {{
                    background: rgba({r}, {g}, {b}, 0.08);
                    border: 1.5px solid rgba({r}, {g}, {b}, 0.35);
                    border-radius: 16px;
                }}
            """)
        if hasattr(self, '_orb_icon'):
            self._orb_icon.setStyleSheet(f"color: {hex_color}; background: transparent; border: none;")

        # Selection in input
        if hasattr(self, '_input'):
            self._input.setStyleSheet(f"""
                QLineEdit {{
                    background: transparent;
                    color: {C.TEXT};
                    border: none;
                    padding: 4px 6px;
                    font-family: '{F.PRIMARY}';
                    font-size: 13px;
                    selection-background-color: rgba({r}, {g}, {b}, 0.25);
                }}
                QLineEdit::placeholder {{
                    color: {C.TEXT_DIM};
                }}
            """)

        # Attach button hover
        if hasattr(self, '_attach_btn'):
            self._attach_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(255, 255, 255, 0.05);
                    color: {C.TEXT_MUTED};
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 18px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background: rgba({r}, {g}, {b}, 0.16);
                    color: {hex_color};
                    border: 1px solid {hex_color};
                }}
            """)

        # Mic button
        if hasattr(self, '_mic_btn'):
            self._mic_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba({r}, {g}, {b}, 0.08);
                    color: {hex_color};
                    border: 1px solid rgba({r}, {g}, {b}, 0.25);
                    border-radius: 18px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background: rgba({r}, {g}, {b}, 0.18);
                    border: 1px solid rgba({r}, {g}, {b}, 0.50);
                }}
            """)

        # Send button
        if hasattr(self, '_send_btn'):
            r2, g2, b2 = min(255, int(r * 1.15)), min(255, int(g * 1.15)), min(255, int(b * 1.15))
            self._send_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba({r}, {g}, {b}, 0.75), stop:1 rgba({r2}, {g2}, {b2}, 0.85));
                    color: white;
                    border: 1px solid rgba({r}, {g}, {b}, 0.45);
                    border-radius: 18px;
                    font-size: 13px;
                    font-weight: bold;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba({r}, {g}, {b}, 0.90), stop:1 rgba({r2}, {g2}, {b2}, 0.95));
                }}
                QPushButton:pressed {{
                    background: rgba({int(r*0.8)}, {int(g*0.8)}, {int(b*0.8)}, 0.80);
                }}
                QPushButton:disabled {{
                    background: rgba(0, 50, 70, 0.40);
                    color: rgba(255,255,255,0.25);
                    border: 1px solid rgba({r}, {g}, {b}, 0.10);
                }}
            """)

    def focus_input(self):
        self._input.setFocus()
