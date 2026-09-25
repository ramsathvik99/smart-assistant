"""
Smart Assistant — Ephemeral Visual Response Surface
Cybernetic dark glass panel for displaying ephemeral information
(pairing codes, IP addresses, URLs, file paths, lists, tables, status).

Features:
- Anchored to the Floating Assistant UI
- Click anywhere outside to dismiss
- Interactive actions: [Copy] via canonical system clipboard, [Open] via browser/OS
- High-contrast dominant value with clear hierarchy
- Strict user-scoped presentation and non-intrusive lifecycle
"""

import os
import webbrowser
from typing import Optional, Dict, Any, List

from PyQt6.QtWidgets import (
    QWidget, QApplication, QLabel, QVBoxLayout, QHBoxLayout,
    QPushButton, QFrame, QGraphicsDropShadowEffect, QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, pyqtSignal, QEvent, QPointF
from PyQt6.QtGui import (
    QColor, QFont, QPainter, QPen, QBrush, QLinearGradient
)

from modules.ui.design_system import (
    C, F, Radius, hex_to_rgb, rgba_str, ensure_visible_accent
)
from core.visual_response import VisualResponse, VisualResponseType


class VisualResponsePanel(QWidget):
    """
    Ephemeral visual response surface.
    Displays information that is substantially easier to consume visually.
    Dismisses on outside click, explicit close, or next command.
    """

    panel_dismissed = pyqtSignal()
    action_performed = pyqtSignal(str, str)  # (action_type, payload)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, False)
        self.setFixedWidth(380)

        self._custom_hex = C.ACC
        self._current_response: Optional[VisualResponse] = None
        self._filter_installed = False

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(0)

        # Outer card frame
        self._card = QFrame()
        self._card.setObjectName("VisualCard")
        self._card.setStyleSheet(f"""
            QFrame#VisualCard {{
                background: rgba(6, 12, 20, 248);
                border: 1px solid rgba(0, 212, 255, 0.45);
                border-radius: {Radius.LG}px;
            }}
        """)

        self._shadow = QGraphicsDropShadowEffect(self._card)
        self._shadow.setBlurRadius(28)
        self._shadow.setColor(QColor(0, 212, 255, 80))
        self._shadow.setOffset(0, 0)
        self._card.setGraphicsEffect(self._shadow)

        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(16, 14, 16, 14)
        self._card_layout.setSpacing(8)

        # Header row: Title badge + Close button
        header_box = QHBoxLayout()
        header_box.setContentsMargins(0, 0, 0, 0)

        self._title_lbl = QLabel("PAIRING CODE")
        self._title_lbl.setFont(F.mono(9))
        self._title_lbl.setStyleSheet(f"color: {self._custom_hex}; font-weight: 700; letter-spacing: 1.5px; background: transparent;")
        header_box.addWidget(self._title_lbl)

        header_box.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                color: #6d8e9e;
                background: transparent;
                border: none;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton:hover {
                color: #ff4757;
            }
        """)
        close_btn.clicked.connect(self.dismiss)
        header_box.addWidget(close_btn)

        self._card_layout.addLayout(header_box)

        # Separator line
        self._sep = QFrame()
        self._sep.setFixedHeight(1)
        self._sep.setStyleSheet(f"background: {rgba_str(self._custom_hex, 0.22)};")
        self._card_layout.addWidget(self._sep)

        # Scroll area for primary value (allows reading long knowledge answers without screen overflow)
        self._scroll_area = QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll_area.setMaximumHeight(260)
        self._scroll_area.setStyleSheet("""
            QScrollArea {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                background: rgba(0, 0, 0, 0.25);
                width: 5px;
                margin: 0;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical {
                background: rgba(0, 212, 255, 0.4);
                min-height: 20px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(0, 212, 255, 0.7);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        # Primary value label (visually dominant)
        self._primary_lbl = QLabel("")
        self._primary_lbl.setFont(QFont(F.MONO, 24, QFont.Weight.Bold))
        self._primary_lbl.setStyleSheet("color: #ffffff; background: transparent; padding: 4px 0px;")
        self._primary_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._primary_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._primary_lbl.setWordWrap(True)
        self._scroll_area.setWidget(self._primary_lbl)
        self._card_layout.addWidget(self._scroll_area)

        # Secondary text / explanation
        self._secondary_lbl = QLabel("")
        self._secondary_lbl.setFont(QFont(F.PRIMARY, 9))
        self._secondary_lbl.setStyleSheet("color: #9bbccc; background: transparent;")
        self._secondary_lbl.setWordWrap(True)
        self._card_layout.addWidget(self._secondary_lbl)

        # Action buttons row container
        self._actions_widget = QWidget()
        self._actions_layout = QHBoxLayout(self._actions_widget)
        self._actions_layout.setContentsMargins(0, 6, 0, 0)
        self._actions_layout.setSpacing(8)
        self._card_layout.addWidget(self._actions_widget)

        root.addWidget(self._card)

    def set_accent_color(self, hex_color: str):
        """Update border, title, and shadow accent color."""
        safe_hex = ensure_visible_accent(hex_color)
        self._custom_hex = safe_hex
        self._card.setStyleSheet(f"""
            QFrame#VisualCard {{
                background: rgba(6, 12, 20, 248);
                border: 1px solid {rgba_str(safe_hex, 0.45)};
                border-radius: {Radius.LG}px;
            }}
        """)
        r, g, b = hex_to_rgb(safe_hex)
        self._shadow.setColor(QColor(r, g, b, 80))
        self._title_lbl.setStyleSheet(f"color: {safe_hex}; font-weight: 700; letter-spacing: 1.5px; background: transparent;")
        self._sep.setStyleSheet(f"background: {rgba_str(safe_hex, 0.22)};")
        # Update any action button styling
        self._restyle_action_buttons()

    def show_response(self, response: VisualResponse, anchor_widget: Optional[QWidget] = None):
        """Populate and display the visual response."""
        self._current_response = response

        # Set title
        self._title_lbl.setText(response.title.upper())

        # Set primary value typography based on type
        val = response.primary_value or ""
        self._primary_lbl.setText(val)

        if response.response_type in (
            VisualResponseType.PAIRING_CODE,
            VisualResponseType.VERIFICATION_CODE,
            VisualResponseType.CODE
        ):
            self._primary_lbl.setFont(QFont(F.MONO, 26, QFont.Weight.Bold))
            self._primary_lbl.setStyleSheet(f"color: {self._custom_hex}; font-weight: 800; letter-spacing: 3px; padding: 4px 0;")
            self._primary_lbl.setTextFormat(Qt.TextFormat.PlainText)
            self._scroll_area.setMaximumHeight(54)
        elif response.response_type == VisualResponseType.IP_ADDRESS:
            self._primary_lbl.setFont(QFont(F.MONO, 20, QFont.Weight.Bold))
            self._primary_lbl.setStyleSheet(f"color: #ffffff; letter-spacing: 1px; padding: 4px 0;")
            self._primary_lbl.setTextFormat(Qt.TextFormat.PlainText)
            self._scroll_area.setMaximumHeight(44)
        elif response.response_type in (VisualResponseType.URL, VisualResponseType.FILE_PATH, VisualResponseType.DOCUMENT_INFO):
            self._primary_lbl.setFont(QFont(F.MONO, 11))
            self._primary_lbl.setStyleSheet(f"color: {C.ACC2}; padding: 2px 0;")
            self._primary_lbl.setTextFormat(Qt.TextFormat.PlainText)
            self._primary_lbl.setWordWrap(True)
            self._scroll_area.setMaximumHeight(90)
        elif response.response_type in (VisualResponseType.LIST, VisualResponseType.SEARCH_RESULTS, VisualResponseType.SEARCH_RESULT):
            self._primary_lbl.setFont(QFont(F.PRIMARY, 10))
            self._primary_lbl.setStyleSheet("color: #e8f4f8; padding: 2px 0; line-height: 1.4;")
            self._primary_lbl.setTextFormat(Qt.TextFormat.MarkdownText)
            self._primary_lbl.setWordWrap(True)
            self._scroll_area.setMaximumHeight(260)
        elif response.response_type == VisualResponseType.KNOWLEDGE:
            self._primary_lbl.setFont(QFont(F.PRIMARY, 10))
            self._primary_lbl.setStyleSheet("color: #e2f1f8; padding: 2px 0; line-height: 1.5;")
            self._primary_lbl.setTextFormat(Qt.TextFormat.MarkdownText)
            self._primary_lbl.setWordWrap(True)
            self._scroll_area.setMaximumHeight(260)
        else:
            self._primary_lbl.setFont(QFont(F.PRIMARY, 11, QFont.Weight.DemiBold))
            self._primary_lbl.setStyleSheet("color: #ffffff; padding: 2px 0;")
            self._primary_lbl.setTextFormat(Qt.TextFormat.MarkdownText)
            self._primary_lbl.setWordWrap(True)
            self._scroll_area.setMaximumHeight(200)

        # Set secondary description
        if response.secondary_text:
            self._secondary_lbl.setText(response.secondary_text)
            self._secondary_lbl.setVisible(True)
        else:
            self._secondary_lbl.setVisible(False)

        # Build action buttons
        self._build_action_buttons(response)

        # Adjust geometry
        self.adjustSize()

        # Position adjacent to anchor widget or bottom-right
        self._position_panel(anchor_widget)

        # Show panel
        self.show()
        self.raise_()

        # Install outside-click event filter on application
        self._install_outside_click_filter()

    def display_response(self, response: VisualResponse, anchor_widget: Optional[QWidget] = None):
        """Convenience alias for show_response."""
        return self.show_response(response, anchor_widget)

    def _build_action_buttons(self, response: VisualResponse):
        """Construct interactive action buttons (Copy, Open) if supported."""
        # Clear existing buttons
        while self._actions_layout.count():
            item = self._actions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not response.actions:
            self._actions_widget.setVisible(False)
            return

        self._actions_widget.setVisible(True)
        for act in response.actions:
            btn = QPushButton(act.label)
            btn.setFixedHeight(28)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: {rgba_str(self._custom_hex, 0.15)};
                    border: 1px solid {rgba_str(self._custom_hex, 0.40)};
                    border-radius: 4px;
                    color: {self._custom_hex};
                    font-size: 10px;
                    font-weight: 700;
                    padding: 0 14px;
                }}
                QPushButton:hover {{
                    background: {rgba_str(self._custom_hex, 0.28)};
                    border: 1px solid {self._custom_hex};
                    color: #ffffff;
                }}
                QPushButton:pressed {{
                    background: {rgba_str(self._custom_hex, 0.40)};
                }}
            """)
            btn.clicked.connect(lambda checked=False, a=act, b=btn: self._execute_action(a, b))
            self._actions_layout.addWidget(btn)

        self._actions_layout.addStretch()

    def _restyle_action_buttons(self):
        """Apply current custom hex color to all action buttons."""
        for i in range(self._actions_layout.count()):
            item = self._actions_layout.itemAt(i)
            if item and item.widget() and isinstance(item.widget(), QPushButton):
                btn = item.widget()
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {rgba_str(self._custom_hex, 0.15)};
                        border: 1px solid {rgba_str(self._custom_hex, 0.40)};
                        border-radius: 4px;
                        color: {self._custom_hex};
                        font-size: 10px;
                        font-weight: 700;
                        padding: 0 14px;
                    }}
                    QPushButton:hover {{
                        background: {rgba_str(self._custom_hex, 0.28)};
                        border: 1px solid {self._custom_hex};
                        color: #ffffff;
                    }}
                    QPushButton:pressed {{
                        background: {rgba_str(self._custom_hex, 0.40)};
                    }}
                """)

    def _trigger_action(self, action, button: Optional[QPushButton] = None):
        """Trigger action button."""
        self._execute_action(action, button)

    def _execute_action(self, action, button: Optional[QPushButton] = None):
        """Execute action button with real system facilities."""
        act_type = action.action_type.lower()
        payload = action.payload

        if act_type == "copy":
            # Requirement 17: Use existing clipboard system
            try:
                from modules.system_controller import set_clipboard_text
                set_clipboard_text(payload)
            except Exception:
                try:
                    import pyperclip
                    pyperclip.copy(payload)
                except Exception:
                    pass

            if button:
                button.setText("✓ Copied")
                button.setStyleSheet("""
                    QPushButton {
                        background: rgba(0, 229, 107, 0.20);
                        border: 1px solid #00e56b;
                        border-radius: 4px;
                        color: #00e56b;
                        font-size: 10px;
                        font-weight: 700;
                        padding: 0 14px;
                    }
                """)
                QTimer.singleShot(1600, lambda: self._restore_button_text(button, action.label))

        elif act_type == "open_url":
            try:
                webbrowser.open(payload)
            except Exception as e:
                print(f"[VISUAL_SURFACE] Error opening URL: {e}")

        elif act_type in ("open_file", "open_document", "open"):
            try:
                if os.path.exists(payload):
                    os.startfile(payload)
                else:
                    webbrowser.open(payload)
            except Exception as e:
                print(f"[VISUAL_SURFACE] Error opening file: {e}")

        self.action_performed.emit(action.action_type, action.payload)

    def _restore_button_text(self, button: Optional[QPushButton], label: str):
        if button:
            button.setText(label)
            self._restyle_action_buttons()

    def _position_panel(self, anchor_widget: Optional[QWidget] = None):
        """Position the panel cleanly adjacent to anchor widget or bottom-right."""
        screen = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = self.height()

        if anchor_widget and anchor_widget.isVisible():
            ax = anchor_widget.x()
            ay = anchor_widget.y()
            aw = anchor_widget.width()
            ah = anchor_widget.height()

            # Place to the left of the button if room, else right
            px = ax - w - 12
            if px < screen.left() + 10:
                px = ax + aw + 12
            if px + w > screen.right() - 10:
                px = screen.right() - w - 10
            px = max(screen.left() + 10, px)

            # Center vertically with anchor
            py = ay + (ah - h) // 2
            py = min(max(screen.top() + 10, py), screen.bottom() - h - 10)
            self.move(px, py)
        else:
            # Default bottom-right corner
            px = screen.right() - w - 24
            py = screen.bottom() - h - 120
            self.move(max(screen.left() + 10, px), max(screen.top() + 10, py))

    # ── Dismissal & Outside-Click Handling ───────────────────────────────────
    def _install_outside_click_filter(self):
        if not self._filter_installed:
            app = QApplication.instance()
            if app:
                app.installEventFilter(self)
                self._filter_installed = True

    def _remove_outside_click_filter(self):
        if self._filter_installed:
            app = QApplication.instance()
            if app:
                app.removeEventFilter(self)
                self._filter_installed = False

    def eventFilter(self, watched, event):
        """
        Requirement 7: Click anywhere outside the panel -> dismiss visual response panel.
        Does not terminate assistant, does not cancel active goal/task.
        """
        if self.isVisible() and event.type() == QEvent.Type.MouseButtonPress:
            pos = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
            # If clicked outside this panel's global geometry
            if not self.geometry().contains(pos):
                self.dismiss()
        return super().eventFilter(watched, event)

    def dismiss(self):
        """
        Hide panel safely without canceling any assistant operation,
        goal, or continuous listening.
        """
        if self.isVisible():
            self._remove_outside_click_filter()
            self.hide()
            self.panel_dismissed.emit()
