"""
Assistant (Conversation) Page - Spatial Intelligence Redesign
=============================================================
Full conversation workspace:
  • Open typographic message feed (speaker label + timestamp, no bubble cards)
  • Translucent spatial conversation sidebar with hairline rules
  • Docked Omni Command Bar (matching Home command-bar aesthetic)
  • Real-time assistant state integration & telemetry
  • Web search toggle, attachments, voice command dispatch
  • Quiet single-line empty state
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal, QEvent
from PyQt6.QtGui import QColor, QPalette, QKeyEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QSplitter, QListWidget, QListWidgetItem,
    QTextEdit, QComboBox, QMessageBox, QFileDialog, QMenu, QSizePolicy,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap, hex_to_rgb, rgba_str, get_contrast_color,
    HLine, VLine, Card, StatusChip, SectionHeader,
)
from ..service_adapters import (
    get_identity, send_command, load_recent_history,
)
from ..workers import DashboardWorker


class OpenMessageRow(QWidget):
    """
    Open, typographic message row.
    Replaces rounded message bubble boxes with pure architectural typography:
      • Monospace speaker indicator ([ USER ] or [ ASSISTANT ]) + ISO timestamp
      • Crisp, high-contrast selectable message body
      • Hairline bottom divider separating turns
    """
    def __init__(self, role: str, text: str, timestamp: Optional[str] = None, assistant_name: str = "Assistant", parent=None):
        super().__init__(parent)
        self.role = role
        is_user = (role == "user")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(Spacing.MD, 8, Spacing.MD, 10)
        lay.setSpacing(6)

        # Meta line: speaker tag + timestamp
        meta_lay = QHBoxLayout()
        meta_lay.setSpacing(Spacing.SM)

        display_name = "You" if is_user else (assistant_name if assistant_name else "Assistant")
        tag_color = rgba_str(C.TEXT_MED, 0.90) if is_user else C.ACC
        speaker_tag = QLabel(display_name)
        speaker_tag.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {tag_color};"
        )
        meta_lay.addWidget(speaker_tag)

        if timestamp:
            clean_ts = str(timestamp).replace("T", " ")[:16]
            ts_lbl = QLabel(f"·  {clean_ts}")
            ts_lbl.setStyleSheet(f"font-size: 11px; color: {rgba_str(C.TEXT_DIM, 0.75)};")
            meta_lay.addWidget(ts_lbl)

        meta_lay.addStretch(1)
        lay.addLayout(meta_lay)

        # Body text
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                     Qt.TextInteractionFlag.TextSelectableByKeyboard)
        body_color = C.TEXT if not is_user else rgba_str(C.TEXT, 0.95)
        body.setStyleSheet(
            f"font-size: 13.5px; line-height: 1.6; color: {body_color}; "
            f"padding-left: 2px; padding-bottom: 4px;"
        )
        lay.addWidget(body)

        # Hairline bottom divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {rgba_str(C.TEXT_DIM, 0.12)};")
        lay.addWidget(div)


# Maintain backward compatibility
MessageBubble = OpenMessageRow


class AssistantPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._history: List[Dict] = []
        self._identity: Dict = {}
        self._state: Dict = {}
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)

        # Page header
        sh = SectionHeader("Assistant", "Conversations, voice, and real-time execution interface", accent=C.ACC)
        root.addWidget(sh)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.setStyleSheet("""
            QSplitter::handle {
                background: rgba(255, 255, 255, 0.06);
            }
        """)

        # ──── Left: Conversation Sidebar (Translucent spatial panel) ────
        left = QFrame()
        left.setMinimumWidth(240)
        left.setMaximumWidth(340)
        left.setStyleSheet(f"""
            QFrame {{
                background: rgba(10, 16, 26, 0.45);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-top: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 12px;
            }}
        """)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        ll.setSpacing(Spacing.SM)

        head = QHBoxLayout()
        head.setSpacing(Spacing.SM)
        caption = QLabel("Conversations")
        caption.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {C.TEXT_MED}; text-transform: uppercase; letter-spacing: 0.5px;"
        )
        head.addWidget(caption)
        head.addStretch(1)

        new_btn = QPushButton()
        new_btn.setObjectName("IconBtn")
        new_btn.setIcon(icon(ICONS.PLUS, C.ACC, 14))
        new_btn.setFixedSize(26, 26)
        new_btn.setToolTip("New conversation")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
                background: rgba(255, 255, 255, 0.08);
            }}
        """)
        new_btn.clicked.connect(self.new_conversation)
        head.addWidget(new_btn)
        ll.addLayout(head)

        ll.addWidget(HLine(rgba_str(C.TEXT_DIM, 0.18), 1))

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter history…")
        self._search.setFixedHeight(30)
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 12),
                               QLineEdit.ActionPosition.LeadingPosition)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(0, 0, 0, 0.35);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 15px;
                padding: 4px 10px;
                color: {C.TEXT};
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C.ACC};
            }}
        """)
        ll.addWidget(self._search)

        self._conv_list = QListWidget()
        self._conv_list.setFrameShape(QFrame.Shape.NoFrame)
        self._conv_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self._conv_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                padding: 4px 0px;
            }}
            QListWidget::item {{
                color: {C.TEXT_MED};
                font-size: 12.5px;
                padding: 8px 10px;
                border-radius: 6px;
                border: 1px solid transparent;
            }}
            QListWidget::item:hover {{
                background: rgba(255, 255, 255, 0.04);
                color: {C.TEXT};
            }}
            QListWidget::item:selected {{
                background: rgba(255, 255, 255, 0.07);
                border-left: 2px solid {C.ACC};
                color: {C.TEXT};
                font-weight: 600;
            }}
        """)
        ll.addWidget(self._conv_list, 1)

        splitter.addWidget(left)

        # ──── Right: Conversation Workspace ────
        right = QFrame()
        right.setStyleSheet(f"""
            QFrame {{
                background: rgba(10, 16, 26, 0.50);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-top: 1px solid rgba(255, 255, 255, 0.18);
                border-radius: 12px;
            }}
        """)
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        right_l.setSpacing(Spacing.SM)

        # Header bar
        hdr = QHBoxLayout()
        hdr.setSpacing(Spacing.SM)

        hdr_info = QVBoxLayout()
        hdr_info.setSpacing(2)

        top_caption = QLabel("Active Conversation")
        top_caption.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {C.TEXT_MED}; text-transform: uppercase; letter-spacing: 0.5px;"
        )
        hdr_info.addWidget(top_caption)

        self._hdr_title = QLabel("New Conversation")
        self._hdr_title.setStyleSheet(
            f"font-weight: 700; font-size: 15px; letter-spacing: -0.2px; color: {C.TEXT};"
        )
        hdr_info.addWidget(self._hdr_title)
        hdr.addLayout(hdr_info, 1)

        self._asst_chip = StatusChip("ONLINE", "online")
        hdr.addWidget(self._asst_chip)

        self._web_search_toggle = QPushButton(" Web Search")
        self._web_search_toggle.setObjectName("GhostBtn")
        self._web_search_toggle.setIcon(icon(ICONS.SEARCH, C.TEXT_MED, 13))
        self._web_search_toggle.setFixedHeight(28)
        self._web_search_toggle.setCheckable(True)
        self._web_search_toggle.setToolTip("Toggle web search for the next message")
        self._web_search_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._web_search_toggle.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                color: {C.TEXT_MED};
                padding: 0 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: rgba(255, 255, 255, 0.08);
                color: {C.TEXT};
            }}
            QPushButton:checked {{
                background: rgba(255, 255, 255, 0.12);
                border: 1px solid {C.ACC};
                color: {C.ACC};
            }}
        """)
        hdr.addWidget(self._web_search_toggle)

        rename_btn = QPushButton()
        rename_btn.setObjectName("IconBtn")
        rename_btn.setIcon(icon(ICONS.EDIT, C.TEXT_MED, 13))
        rename_btn.setFixedSize(28, 28)
        rename_btn.setToolTip("Rename session")
        rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rename_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
            }}
        """)
        rename_btn.clicked.connect(self._rename_conversation)
        hdr.addWidget(rename_btn)

        del_btn = QPushButton()
        del_btn.setObjectName("IconBtn")
        del_btn.setIcon(icon(ICONS.TRASH, rgba_str(C.TEXT_DIM, 0.85), 13))
        del_btn.setFixedSize(28, 28)
        del_btn.setToolTip("Clear conversation messages")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.RED};
            }}
        """)
        del_btn.clicked.connect(self._clear_conversation)
        hdr.addWidget(del_btn)

        right_l.addLayout(hdr)
        right_l.addWidget(HLine(rgba_str(C.TEXT_DIM, 0.18), 1))

        # Message Feed Scroller
        feed_scroll = QScrollArea()
        feed_scroll.setWidgetResizable(True)
        feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        feed_scroll.setStyleSheet("background: transparent;")

        self._feed_widget = QWidget()
        self._feed_widget.setStyleSheet("background: transparent;")
        self._feed = QVBoxLayout(self._feed_widget)
        self._feed.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        self._feed.setSpacing(Spacing.XS)
        self._feed.addStretch(1)

        # Quiet single-line empty state
        self._feed_empty = QWidget()
        el = QVBoxLayout(self._feed_empty)
        el.setContentsMargins(Spacing.LG, Spacing.XL, Spacing.LG, Spacing.XL)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lbl = QLabel("No messages yet")
        empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_lbl.setStyleSheet(
            f"font-size: 13px; color: {rgba_str(C.TEXT_DIM, 0.70)};"
        )
        el.addWidget(empty_lbl)

        self._feed.insertWidget(0, self._feed_empty)
        feed_scroll.setWidget(self._feed_widget)
        self._feed_scroll = feed_scroll
        right_l.addWidget(feed_scroll, 1)

        # Real-time Execution Telemetry strip
        self._working_row = QFrame()
        self._working_row.setVisible(False)
        self._working_row.setStyleSheet(f"""
            QFrame {{
                background: rgba(10, 16, 26, 0.60);
                border: 1px solid rgba_str(C.ACC, 0.25);
                border-left: 2px solid {C.ACC};
                border-radius: 6px;
            }}
        """)
        wl = QHBoxLayout(self._working_row)
        wl.setContentsMargins(Spacing.MD, 6, Spacing.MD, 6)
        wl.setSpacing(Spacing.SM)

        self._working_chip = StatusChip("WORKING", "executing")
        wl.addWidget(self._working_chip)

        self._working_lbl = QLabel("")
        self._working_lbl.setStyleSheet(
            f"font-family: monospace; font-size: 11px; font-weight: 600; color: {C.ACC};"
        )
        wl.addWidget(self._working_lbl, 1)
        right_l.addWidget(self._working_row)

        # ──── Docked Omni Command Bar (Same style as Home) ────
        cmd_card = QFrame()
        cmd_card.setStyleSheet(f"""
            QFrame {{
                background: rgba(10, 16, 26, 0.72);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-top: 1px solid rgba(255, 255, 255, 0.22);
                border-radius: 18px;
            }}
            QFrame:focus-within {{
                border: 1px solid {C.ACC};
                background: rgba(12, 20, 34, 0.88);
            }}
        """)
        cmd_lay = QVBoxLayout(cmd_card)
        cmd_lay.setContentsMargins(Spacing.MD, 8, Spacing.MD, 8)
        cmd_lay.setSpacing(6)

        ident = get_identity() or {}
        self._identity = ident
        asst_name = (ident.get("assistant_name") or "Assistant").strip()

        self._input = QTextEdit()
        self._input.setPlaceholderText(f"Message {asst_name}…  (Enter to send, Shift+Enter for newline)")
        self._input.setMinimumHeight(44)
        self._input.setMaximumHeight(120)
        self._input.setCursor(Qt.CursorShape.IBeamCursor)
        self._input.setStyleSheet(f"""
            QTextEdit {{
                border: none;
                background: transparent;
                padding: 2px 4px;
                color: {C.TEXT};
                font-size: 13.5px;
                line-height: 1.5;
            }}
        """)
        # Install event filter to handle Enter key
        self._input.installEventFilter(self)
        cmd_lay.addWidget(self._input)

        # Action button tray inside command bar
        act_row = QHBoxLayout()
        act_row.setSpacing(Spacing.SM)

        attach = QPushButton()
        attach.setObjectName("IconBtn")
        attach.setIcon(icon(ICONS.UPLOAD, C.TEXT_MED, 13))
        attach.setFixedSize(28, 28)
        attach.setToolTip("Attach file")
        attach.setCursor(Qt.CursorShape.PointingHandCursor)
        attach.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
            }}
        """)
        attach.clicked.connect(self._attach_file)
        act_row.addWidget(attach)

        web = QPushButton()
        web.setObjectName("IconBtn")
        web.setIcon(icon(ICONS.SEARCH, C.TEXT_MED, 13))
        web.setFixedSize(28, 28)
        web.setToolTip("Toggle Web Search")
        web.setCursor(Qt.CursorShape.PointingHandCursor)
        web.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
            }}
        """)
        web.clicked.connect(lambda: self._web_search_toggle.toggle())
        act_row.addWidget(web)

        act_row.addStretch(1)

        mic = QPushButton()
        mic.setObjectName("IconBtn")
        mic.setIcon(icon(ICONS.MIC, C.ACC, 14))
        mic.setFixedSize(30, 30)
        mic.setToolTip("Voice Input")
        mic.setCursor(Qt.CursorShape.PointingHandCursor)
        mic.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba_str(C.ACC, 0.30);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                background: rgba_str(C.ACC, 0.15);
                border: 1px solid {C.ACC};
            }}
        """)
        mic.clicked.connect(lambda: self._dispatch_toggle_voice())
        act_row.addWidget(mic)

        self._send_btn = QPushButton("  Send")
        self._send_btn.setObjectName("PrimaryBtn")
        self._send_btn.setIcon(icon(ICONS.SEND, get_contrast_color(C.ACC), 12))
        self._send_btn.setFixedHeight(30)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.ACC};
                color: {get_contrast_color(C.ACC)};
                border: none;
                border-radius: 15px;
                padding: 0 14px;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {rgba_str(C.ACC, 0.88)};
            }}
        """)
        self._send_btn.clicked.connect(self._on_send)
        act_row.addWidget(self._send_btn)

        cmd_lay.addLayout(act_row)
        right_l.addWidget(cmd_card)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        QTimer.singleShot(50, self._reload_feed)

    def eventFilter(self, obj, event):
        if obj is self._input and event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event
            if key_event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if not (key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                    self._on_send()
                    return True
        return super().eventFilter(obj, event)

    # --------------------------- API helpers -------------------------
    def new_conversation(self):
        self._input.setFocus()
        self._input.clear()
        self._hdr_title.setText("New Conversation")

    def prefill_input(self, text: str):
        self._input.setPlainText(text)
        self._input.setFocus()

    def on_identity(self, ident: Dict):
        self._identity = ident
        asst_name = (ident.get("assistant_name") or "Assistant").strip()
        self._input.setPlaceholderText(f"Message {asst_name}…  (Enter to send, Shift+Enter for newline)")

    def on_assistant_state(self, data: Dict):
        self._state = data
        s = (data.get("state") or "idle").lower()
        self._asst_chip.set_state(s)
        self._asst_chip.setText(s.upper())
        task = data.get("active_operation") or data.get("task")
        if s in ("thinking", "executing", "working", "processing", "listening", "speaking"):
            self._working_row.setVisible(True)
            self._working_chip.set_state(s)
            self._working_chip.setText(s.upper())
            self._working_lbl.setText(task.upper() if task else "PROCESSING")
        else:
            self._working_row.setVisible(False)

    def on_visible(self):
        self._reload_feed()
        self._conv_list.clear()
        item = QListWidgetItem("Current Conversation")
        item.setIcon(icon(ICONS.ASSISTANT, C.ACC, 14))
        self._conv_list.addItem(item)
        self._conv_list.setCurrentRow(0)

    # --------------------------- send ---------------------------
    def _attach_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Attach file")
        if path:
            cur = self._input.toPlainText()
            self._input.setPlainText((cur + "\n" if cur else "") + f"[Attached: {path}]")

    def _dispatch_toggle_voice(self):
        self._dispatch("toggle voice listening")

    def _rename_conversation(self):
        from PyQt6.QtWidgets import QInputDialog
        cur = self._hdr_title.text()
        text, ok = QInputDialog.getText(self, "Rename Conversation", "Conversation title:", text=cur)
        if ok and text.strip():
            self._hdr_title.setText(text.strip())

    def _clear_conversation(self):
        if QMessageBox.question(self, "Clear conversation?", "Are you sure you want to clear the conversation messages?") == QMessageBox.StandardButton.Yes:
            while self._feed.count() > 1:
                item = self._feed.itemAt(0)
                w = item.widget()
                if w is None:
                    self._feed.removeItem(item)
                    continue
                if w is self._feed_empty:
                    self._feed.removeWidget(w)
                    w.setParent(None)
                    continue
                self._feed.removeWidget(w)
                w.setParent(None)
                w.deleteLater()
            self._feed.insertWidget(0, self._feed_empty)
            self._hdr_title.setText("New Conversation")

    def _on_send(self):
        txt = self._input.toPlainText().strip()
        if not txt:
            return
        if hasattr(self, "_web_search_toggle") and self._web_search_toggle.isChecked():
            txt = f"Search the web: {txt}"
            self._web_search_toggle.setChecked(False)
        self._append_message("user", txt)
        self._input.clear()
        self._dispatch(txt)

    def _append_message(self, role: str, text: str):
        if self._feed_empty and self._feed_empty.parent():
            self._feed.removeWidget(self._feed_empty)
            self._feed_empty.setParent(None)
        ts = datetime.now().isoformat()
        asst_name = (self._identity.get("assistant_name") or "Assistant").strip()
        bubble = OpenMessageRow(role, text, ts, assistant_name=asst_name)
        self._feed.insertWidget(self._feed.count() - 1, bubble)
        QTimer.singleShot(40, lambda: self._feed_scroll.verticalScrollBar().setValue(
            self._feed_scroll.verticalScrollBar().maximum()
        ))

    def _dispatch(self, txt: str):
        self._asst_chip.set_state("thinking")
        self._asst_chip.setText("THINKING")
        w = DashboardWorker(send_command, txt)
        w.result_sig.connect(lambda r: self._on_dispatched(txt, r))
        w.error_sig.connect(lambda e: self._on_error(e))
        self._workers.append(w)
        w.start()

    def _on_dispatched(self, txt, result):
        ok = bool(result[0]) if isinstance(result, tuple) else bool(result)
        response_text = result[1] if isinstance(result, tuple) else ""
        self._asst_chip.set_state("idle")
        self._asst_chip.setText("ONLINE")
        if response_text:
            self._append_message("assistant", response_text)
        QTimer.singleShot(1200, self._reload_feed)

    def _on_error(self, err: str):
        self._append_message("assistant", f"Error: {err}")

    # --------------------------- load history ---------------------------
    def _reload_feed(self):
        w = DashboardWorker(load_recent_history, 50)
        w.result_sig.connect(self._apply_history)
        self._workers.append(w)
        w.start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def _apply_history(self, hist):
        self._history = list(hist or [])
        while self._feed.count() > 1:
            item = self._feed.itemAt(0)
            w = item.widget()
            if w is None:
                self._feed.removeItem(item)
                continue
            if w is self._feed_empty:
                self._feed.removeWidget(w)
                w.setParent(None)
                continue
            self._feed.removeWidget(w)
            w.setParent(None)
            w.deleteLater()
        if not self._history:
            self._feed.insertWidget(0, self._feed_empty)
            return
        user_msgs = [m for m in self._history if m.get("role") == "user"]
        if user_msgs:
            title = (user_msgs[-1].get("content") or "Active Session")[:48]
            if len(title) == 48:
                title += "…"
            self._hdr_title.setText(title)
        for m in self._history:
            role = m.get("role") or "user"
            if role not in ("user", "assistant"):
                role = "user" if role in ("human", "User") else "assistant"
            self._append_message(role, m.get("content") or "")
