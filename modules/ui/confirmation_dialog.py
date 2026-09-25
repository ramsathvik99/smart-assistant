"""
Smart Assistant — Confirmation Dialog
Futuristic modal overlay for sensitive/destructive actions
(e.g., shutdown, restart, clear memory, bulk file operations).
"""

from PyQt6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

from modules.ui.design_system import C, F, Radius, Spacing


class ConfirmationDialog(QDialog):
    """Futuristic modal dialog confirming sensitive operations."""

    confirmed = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(
        self,
        title: str = "Confirm Action",
        message: str = "Are you sure you want to execute this operation?",
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
        is_destructive: bool = True,
        parent=None
    ):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.resize(440, 220)

        accent_color = "#ff3b30" if is_destructive else C.ACCENT_CYAN

        # Root layout
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)

        # Container card
        card = QFrame()
        card.setObjectName("ConfirmCard")
        card.setStyleSheet(f"""
            QFrame#ConfirmCard {{
                background: rgba(8, 14, 22, 248);
                border: 1px solid {accent_color};
                border-radius: {Radius.LG}px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(32)
        shadow.setColor(QColor(accent_color))
        shadow.setOffset(0, 0)
        card.setGraphicsEffect(shadow)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        layout.setSpacing(Spacing.MD)

        # Header with icon
        header_layout = QHBoxLayout()
        header_layout.setSpacing(Spacing.SM)

        icon_lbl = QLabel("⚠" if is_destructive else "ℹ")
        icon_lbl.setFont(QFont(F.PRIMARY, 20, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {accent_color}; background: transparent;")
        header_layout.addWidget(icon_lbl)

        title_lbl = QLabel(title)
        title_lbl.setFont(QFont(F.PRIMARY, 15, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        header_layout.addWidget(title_lbl, 1)

        layout.addLayout(header_layout)

        # Message
        msg_lbl = QLabel(message)
        msg_lbl.setWordWrap(True)
        msg_lbl.setFont(QFont(F.PRIMARY, 12))
        msg_lbl.setStyleSheet(f"color: {C.TEXT_SECONDARY}; background: transparent; line-height: 140%;")
        layout.addWidget(msg_lbl, 1)

        # Action buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(Spacing.MD)
        btn_layout.addStretch()

        cancel_btn = QPushButton(cancel_label)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setFont(QFont(F.PRIMARY, 12, QFont.Weight.Medium))
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.06);
                color: {C.TEXT_MUTED};
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: {Radius.SM}px;
                padding: 8px 18px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.12);
                color: {C.TEXT};
            }}
        """)
        cancel_btn.clicked.connect(self._on_cancel)
        btn_layout.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_label)
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.setFont(QFont(F.PRIMARY, 12, QFont.Weight.Bold))
        btn_bg = "rgba(255, 59, 48, 0.25)" if is_destructive else "rgba(0, 212, 255, 0.22)"
        btn_hover = "rgba(255, 59, 48, 0.45)" if is_destructive else "rgba(0, 212, 255, 0.40)"
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {btn_bg};
                color: {C.TEXT};
                border: 1px solid {accent_color};
                border-radius: {Radius.SM}px;
                padding: 8px 22px;
            }}
            QPushButton:hover {{
                background: {btn_hover};
            }}
        """)
        confirm_btn.clicked.connect(self._on_confirm)
        btn_layout.addWidget(confirm_btn)

        layout.addLayout(btn_layout)
        root.addWidget(card)

    def _on_confirm(self):
        self.confirmed.emit()
        self.accept()

    def _on_cancel(self):
        self.cancelled.emit()
        self.reject()
