"""
Smart Assistant — Conversation Feed
Chat bubble scroll area showing real message history.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QSizePolicy
)
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QColor, QFont, QPainter, QBrush, QPainterPath, QPen

from modules.ui.design_system import C, F, Radius, Spacing, hex_to_rgb


# ─────────────────────────────────────────────────────────────────────────────
# CHAT BUBBLE
# ─────────────────────────────────────────────────────────────────────────────
class ChatBubble(QFrame):
    """Single chat message bubble."""

    def __init__(self, role: str, content: str,
                 assistant_name: str = "Assistant", parent=None, accent_hex: str = None):
        super().__init__(parent)
        self._role = role
        is_user = (role == "user")
        self._accent = accent_hex or "#00d4ff"

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 2, 8, 2)
        outer.setSpacing(0)

        if is_user:
            outer.addStretch(1)

        # Bubble container
        self.bubble = QFrame()
        self.bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Minimum)
        self.bubble.setMaximumWidth(520)

        r, g, b = hex_to_rgb(self._accent)
        if is_user:
            self.bubble.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba({r}, {g}, {b}, 0.22), stop:1 rgba({r}, {g}, {b}, 0.16));
                    border: 1px solid rgba({r}, {g}, {b}, 0.30);
                    border-radius: {Radius.LG}px;
                    border-bottom-right-radius: 4px;
                }}
            """)
        else:
            self.bubble.setStyleSheet(f"""
                QFrame {{
                    background: rgba(14, 20, 27, 200);
                    border: 1px solid rgba({r}, {g}, {b}, 0.14);
                    border-radius: {Radius.LG}px;
                    border-bottom-left-radius: 4px;
                }}
            """)

        b_lay = QVBoxLayout(self.bubble)
        b_lay.setContentsMargins(14, 10, 14, 10)
        b_lay.setSpacing(4)

        # Role label
        self.role_label = QLabel("You" if is_user else assistant_name)
        self.role_label.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        role_color = self._accent if is_user else C.TEXT_MED
        self.role_label.setStyleSheet(
            f"color: {role_color}; background: transparent; border: none; padding: 0;"
        )
        b_lay.addWidget(self.role_label)

        # Content
        text_label = QLabel(content)
        text_label.setFont(QFont(F.PRIMARY, 13))
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text_label.setStyleSheet(
            f"color: {C.TEXT}; background: transparent; border: none; padding: 0;"
        )
        b_lay.addWidget(text_label)

        outer.addWidget(self.bubble)

        if not is_user:
            outer.addStretch(1)

    def set_accent_color(self, hex_color: str):
        self._accent = hex_color
        r, g, b = hex_to_rgb(hex_color)
        if self._role == "user":
            self.bubble.setStyleSheet(f"""
                QFrame {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 rgba({r}, {g}, {b}, 0.22), stop:1 rgba({r}, {g}, {b}, 0.16));
                    border: 1px solid rgba({r}, {g}, {b}, 0.35);
                    border-radius: {Radius.LG}px;
                    border-bottom-right-radius: 4px;
                }}
            """)
            self.role_label.setStyleSheet(
                f"color: {hex_color}; background: transparent; border: none; padding: 0;"
            )
        else:
            self.bubble.setStyleSheet(f"""
                QFrame {{
                    background: rgba(14, 20, 27, 200);
                    border: 1px solid rgba({r}, {g}, {b}, 0.14);
                    border-radius: {Radius.LG}px;
                    border-bottom-left-radius: 4px;
                }}
            """)


# ─────────────────────────────────────────────────────────────────────────────
# THINKING INDICATOR
# ─────────────────────────────────────────────────────────────────────────────
class ThinkingBubble(QFrame):
    """Animated "thinking" dots indicator shown while processing."""

    def __init__(self, assistant_name: str = "Assistant", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 2, 8, 2)

        bubble = QFrame()
        bubble.setMaximumWidth(160)
        bubble.setFixedHeight(44)
        bubble.setStyleSheet(f"""
            QFrame {{
                background: rgba(14, 20, 27, 200);
                border: 1px solid rgba(0, 212, 255, 0.14);
                border-radius: {Radius.LG}px;
                border-bottom-left-radius: 4px;
            }}
        """)
        b_lay = QHBoxLayout(bubble)
        b_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._dots = [QLabel("●") for _ in range(3)]
        for dot in self._dots:
            dot.setFont(QFont(F.PRIMARY, 9))
            dot.setStyleSheet(f"color: {C.ACC}; background: transparent; border: none;")
            b_lay.addWidget(dot)

        lay.addWidget(bubble)
        lay.addStretch(1)

        # Animate dots opacity
        self._phase = 0
        self._dot_timer = QTimer(self)
        self._dot_timer.timeout.connect(self._tick_dots)
        self._dot_timer.start(400)

    def _tick_dots(self):
        for i, dot in enumerate(self._dots):
            active = (i == self._phase % 3)
            dot.setStyleSheet(
                f"color: {'rgba(0,212,255,255)' if active else 'rgba(0,212,255,80)'};"
                f"background: transparent; border: none;"
            )
        self._phase += 1


# ─────────────────────────────────────────────────────────────────────────────
# CONVERSATION FEED
# ─────────────────────────────────────────────────────────────────────────────
class ConversationFeed(QScrollArea):
    """Scrollable conversation feed. Call add_message() to append bubbles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                border: none;
                margin: 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0, 212, 255, 0.30);
                border-radius: 3px;
                min-height: 18px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba(0, 212, 255, 0.50);
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._layout = QVBoxLayout(self._content)
        self._layout.setContentsMargins(4, 8, 4, 8)
        self._layout.setSpacing(6)
        self._layout.addStretch(1)
        self.setWidget(self._content)

        self._assistant_name = "Assistant"
        self._accent_color = "#00d4ff"
        self._thinking_bubble: ThinkingBubble | None = None

    def set_assistant_name(self, name: str):
        self._assistant_name = name or "Assistant"

    def set_accent_color(self, hex_color: str):
        """Update scrollbar styling and all existing message bubbles with new accent."""
        self._accent_color = hex_color
        r, g, b = hex_to_rgb(hex_color)
        self.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 6px;
                border: none;
                margin: 4px 0;
            }}
            QScrollBar::handle:vertical {{
                background: rgba({r}, {g}, {b}, 0.30);
                border-radius: 3px;
                min-height: 18px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: rgba({r}, {g}, {b}, 0.55);
            }}
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        # Update existing message bubbles
        for child in self._content.findChildren(ChatBubble):
            child.set_accent_color(hex_color)

    def add_message(self, role: str, content: str):
        """Append a user or assistant message bubble."""
        self.hide_thinking()
        if not content or not content.strip():
            return

        import time
        # Deduplication: avoid appending the identical assistant message twice within 3.0s
        if role == "assistant" and hasattr(self, "_last_assistant_msg"):
            last_text, last_time = self._last_assistant_msg
            if last_text.strip() == content.strip() and (time.time() - last_time) < 3.0:
                return
        if role == "assistant":
            self._last_assistant_msg = (content.strip(), time.time())

        bubble = ChatBubble(role, content, self._assistant_name, accent_hex=self._accent_color)
        self._layout.insertWidget(self._layout.count() - 1, bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def show_thinking(self):
        """Show animated thinking indicator."""
        if self._thinking_bubble is not None:
            return
        self._thinking_bubble = ThinkingBubble(self._assistant_name)
        self._layout.insertWidget(self._layout.count() - 1, self._thinking_bubble)
        QTimer.singleShot(50, self._scroll_to_bottom)

    def hide_thinking(self):
        if self._thinking_bubble:
            self._thinking_bubble.hide()
            self._layout.removeWidget(self._thinking_bubble)
            self._thinking_bubble.deleteLater()
            self._thinking_bubble = None

    def load_history(self, history: list):
        """Load a list of {role, content} dicts from DB."""
        for msg in history:
            self.add_message(msg.get("role", "user"), msg.get("content", ""))

    def clear(self):
        # Remove all bubbles
        while self._layout.count() > 1:  # keep the stretch
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._thinking_bubble = None

    def _scroll_to_bottom(self):
        vbar = self.verticalScrollBar()
        vbar.setValue(vbar.maximum())
