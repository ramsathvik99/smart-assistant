"""
Assistant (Conversation) Page
==============================
Full conversation workspace:
  • Message feed (user + assistant)
  • New conversation / search history
  • Text + voice input
  • Attachments button
  • Web search toggle (if enabled)
  • Regenerate / copy / retry actions
  • Tool execution status display
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QSplitter, QListWidget, QListWidgetItem,
    QTextEdit, QComboBox, QMessageBox, QFileDialog, QMenu,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap, hex_to_rgb, rgba_str, get_contrast_color,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState,
)
from ..service_adapters import (
    get_identity, send_command, load_recent_history,
)
from ..workers import DashboardWorker


class MessageBubble(QFrame):
    def __init__(self, role: str, text: str, timestamp: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.role = role
        is_user = (role == "user")
        bg = rgba_str(C.SEC_ASSISTANT, 0.10) if is_user else C.CARD_BG
        if is_user:
            border = rgba_str(C.SEC_ASSISTANT, 0.26)
            top_left, top_right = (Radius.LG, Radius.SM) if False else (Radius.LG, Radius.LG)
        else:
            border = C.BORDER
            top_left, top_right = (Radius.LG, Radius.LG)
        self.setStyleSheet(
            f"MessageBubble {{ background: {bg}; border: 1px solid {border}; "
            f"border-top-left-radius: {Radius.SM if not is_user else Radius.LG}px; "
            f"border-top-right-radius: {Radius.LG if not is_user else Radius.SM}px; "
            f"border-bottom-left-radius: {Radius.LG}px; "
            f"border-bottom-right-radius: {Radius.LG}px; }}"
        )
        root = QHBoxLayout(self)
        root.setContentsMargins(Spacing.MD + 2, Spacing.MD + 2, Spacing.MD + 2, Spacing.MD + 2)
        root.setSpacing(Spacing.MD + 2)
        # Avatar with subtle border
        av = QLabel("U" if is_user else "A")
        av.setFixedSize(32, 32)
        av.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col = C.SEC_ASSISTANT if is_user else C.STATUS_SUCCESS
        av.setStyleSheet(
            f"border-radius: 16px; background: {rgba_str(col, 0.12)}; "
            f"color: {col}; font-weight: 700; font-size: 12px;"
            f"border: 1px solid {rgba_str(col, 0.20)};"
        )
        if not is_user:
            root.addStretch(1)
            root.addWidget(av, 0, Qt.AlignmentFlag.AlignTop)
        else:
            root.addWidget(av, 0, Qt.AlignmentFlag.AlignTop)
        # Text column
        col_wid = QWidget()
        cv = QVBoxLayout(col_wid)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(5)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {C.TEXT}; font-size: 13.5px; line-height: 1.6;"
        )
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse |
                                     Qt.TextInteractionFlag.TextSelectableByKeyboard)
        cv.addWidget(lbl)
        if timestamp:
            ts = QLabel(str(timestamp)[:16])
            ts.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10.5px;")
            cv.addWidget(ts)
        root.addWidget(col_wid, 1)
        col_wid.setMaximumWidth(960)
        if is_user:
            root.addStretch(1)


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
        root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG2)

        # Page header
        sh = SectionHeader("Assistant", "Conversations, voice, and control interface", accent=C.SEC_ASSISTANT)
        root.addWidget(sh)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)

        # ---- Left: Conversation list ----
        left = QFrame(); left.setProperty("class", "CardPanel")
        left.setMinimumWidth(260)
        left.setMaximumWidth(360)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        ll.setSpacing(Spacing.SM)
        head = QHBoxLayout(); head.setSpacing(Spacing.SM)
        t = QLabel("Conversations")
        t.setStyleSheet("font-weight: 700; font-size: 13px; letter-spacing: -0.1px;")
        head.addWidget(t); head.addStretch(1)
        new_btn = QPushButton(); new_btn.setObjectName("IconBtn")
        new_btn.setIcon(icon(ICONS.PLUS, C.SEC_ASSISTANT, 14))
        new_btn.setFixedSize(28, 28)
        new_btn.setToolTip("New conversation")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self.new_conversation)
        head.addWidget(new_btn)
        ll.addLayout(head)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.setFixedHeight(32)
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 12),
                               QLineEdit.ActionPosition.LeadingPosition)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        ll.addWidget(self._search)

        self._conv_list = QListWidget()
        self._conv_list.setFrameShape(QFrame.Shape.NoFrame)
        self._conv_list.setCursor(Qt.CursorShape.PointingHandCursor)
        self._conv_list.setStyleSheet(
            "QListWidget { background: transparent; border: none; padding: 2px; }"
        )
        ll.addWidget(self._conv_list, 1)

        splitter.addWidget(left)

        # ---- Right: conversation view (CardPanel) ----
        right = QFrame()
        right.setProperty("class", "CardPanel")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        right_l.setSpacing(Spacing.SM)

        # Header
        hdr = QHBoxLayout(); hdr.setSpacing(Spacing.SM)
        self._asst_chip = StatusChip("OFFLINE", "offline")
        hdr.addWidget(self._asst_chip)
        self._hdr_title = QLabel("New Conversation")
        self._hdr_title.setStyleSheet(
            "font-weight: 700; font-size: 15px; letter-spacing: -0.2px;"
        )
        hdr.addWidget(self._hdr_title, 1)
        self._web_search_toggle = QPushButton(" Web Search")
        self._web_search_toggle.setObjectName("GhostBtn")
        self._web_search_toggle.setIcon(icon(ICONS.SEARCH, C.TEXT_MED, 13))
        self._web_search_toggle.setFixedHeight(30)
        self._web_search_toggle.setCheckable(True)
        self._web_search_toggle.setToolTip("Toggle web search for the next message")
        self._web_search_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        hdr.addWidget(self._web_search_toggle)
        rename_btn = QPushButton(); rename_btn.setObjectName("IconBtn")
        rename_btn.setIcon(icon(ICONS.EDIT, C.TEXT_MED, 13))
        rename_btn.setFixedSize(30, 30)
        rename_btn.setToolTip("Rename conversation")
        rename_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rename_btn.clicked.connect(self._rename_conversation)
        hdr.addWidget(rename_btn)
        del_btn = QPushButton(); del_btn.setObjectName("IconBtn")
        del_btn.setIcon(icon(ICONS.TRASH, C.RED, 13))
        del_btn.setFixedSize(30, 30)
        del_btn.setToolTip("Clear conversation")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(self._clear_conversation)
        hdr.addWidget(del_btn)
        right_l.addLayout(hdr)

        right_l.addWidget(HLine(C.DIVIDER, 1))

        # Feed
        feed_scroll = QScrollArea(); feed_scroll.setWidgetResizable(True)
        feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_widget = QWidget()
        self._feed = QVBoxLayout(self._feed_widget)
        self._feed.setContentsMargins(Spacing.SM, Spacing.MD, Spacing.SM, Spacing.MD)
        self._feed.setSpacing(Spacing.MD)
        self._feed.addStretch(1)
        self._feed_empty = EmptyState(ICONS.ASSISTANT, "Start a conversation",
                                     "Send a message below or ask a question.",
                                     "Send first message", lambda: self._input.setFocus(),
                                     accent=C.SEC_ASSISTANT)
        self._feed.insertWidget(0, self._feed_empty)
        feed_scroll.setWidget(self._feed_widget)
        self._feed_scroll = feed_scroll
        right_l.addWidget(feed_scroll, 1)

        # Status / working bar
        self._working_row = QFrame(); self._working_row.setVisible(False)
        self._working_row.setStyleSheet(
            f"QFrame {{ background: {rgba_str(C.STATUS_WARNING, 0.06)}; "
            f"border: 1px solid {rgba_str(C.STATUS_WARNING, 0.22)}; border-radius: 6px; }}"
        )
        wl = QHBoxLayout(self._working_row)
        wl.setContentsMargins(Spacing.SM, 6, Spacing.SM, 6)
        wl.setSpacing(Spacing.SM)
        self._working_chip = StatusChip("WORKING", "executing")
        wl.addWidget(self._working_chip)
        self._working_lbl = QLabel("")
        self._working_lbl.setStyleSheet(f"color: {C.STATUS_WARNING}; font-size: 11px; font-weight: 500;")
        wl.addWidget(self._working_lbl, 1)
        right_l.addWidget(self._working_row)

        # Input card
        inp_card = QFrame(); inp_card.setProperty("class", "CardInner")
        inp_l = QVBoxLayout(inp_card)
        inp_l.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        inp_l.setSpacing(Spacing.SM)

        self._input = QTextEdit()
        self._input.setPlaceholderText("Message your assistant…  (Shift+Enter for newline)")
        self._input.setMinimumHeight(70)
        self._input.setMaximumHeight(140)
        self._input.setCursor(Qt.CursorShape.IBeamCursor)
        self._input.setStyleSheet(
            f"QTextEdit {{ border: none; background: transparent; padding: 4px; "
            f"color: {C.TEXT}; font-size: 13px; line-height: 1.5; }}"
        )
        inp_l.addWidget(self._input)

        act_row = QHBoxLayout(); act_row.setSpacing(Spacing.SM)

        attach = QPushButton(); attach.setObjectName("IconBtn")
        attach.setIcon(icon(ICONS.UPLOAD, C.TEXT_MED, 13))
        attach.setFixedSize(32, 30)
        attach.setToolTip("Attach files")
        attach.setCursor(Qt.CursorShape.PointingHandCursor)
        attach.clicked.connect(self._attach_file)
        act_row.addWidget(attach)

        web = QPushButton(); web.setObjectName("IconBtn")
        web.setIcon(icon(ICONS.SEARCH, C.TEXT_MED, 13))
        web.setFixedSize(32, 30)
        web.setToolTip("Search web")
        web.setCursor(Qt.CursorShape.PointingHandCursor)
        web.clicked.connect(lambda: self._web_search_toggle.toggle())
        act_row.addWidget(web)

        act_row.addStretch(1)

        mic = QPushButton(); mic.setObjectName("IconBtn")
        mic.setIcon(icon(ICONS.MIC, C.SEC_ASSISTANT, 13))
        mic.setFixedSize(32, 30)
        mic.setToolTip("Voice input")
        mic.setCursor(Qt.CursorShape.PointingHandCursor)
        mic.clicked.connect(lambda: self._dispatch_toggle_voice())
        act_row.addWidget(mic)

        self._send_btn = QPushButton("  Send")
        self._send_btn.setObjectName("PrimaryBtn")
        self._send_btn.setIcon(icon(ICONS.SEND, get_contrast_color(C.SEC_ASSISTANT), 13))
        self._send_btn.setFixedHeight(30)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        self._send_btn.setShortcut("Ctrl+Return")
        act_row.addWidget(self._send_btn)

        inp_l.addLayout(act_row)
        right_l.addWidget(inp_card)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        QTimer.singleShot(50, self._reload_feed)

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

    def on_assistant_state(self, data: Dict):
        self._state = data
        s = (data.get("state") or "idle").lower()
        self._asst_chip.set_state(s); self._asst_chip.setText(s.upper())
        task = data.get("active_operation") or data.get("task")
        if s in ("thinking", "executing", "working", "processing", "listening", "speaking"):
            self._working_row.setVisible(True)
            self._working_chip.set_state(s)
            self._working_chip.setText(s.upper())
            self._working_lbl.setText(task or "")
        else:
            self._working_row.setVisible(False)

    def on_visible(self):
        self._reload_feed()
        # Refresh conversation list
        self._conv_list.clear()
        item = QListWidgetItem("Current Conversation")
        item.setIcon(icon(ICONS.ASSISTANT, C.TEXT_MED, 14))
        self._conv_list.addItem(item)

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
                    self._feed.removeItem(item); continue
                if w is self._feed_empty:
                    self._feed.removeWidget(w); w.setParent(None); continue
                self._feed.removeWidget(w); w.setParent(None); w.deleteLater()
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
        # remove empty state
        if self._feed_empty and self._feed_empty.parent():
            self._feed.removeWidget(self._feed_empty)
            self._feed_empty.setParent(None)
        ts = datetime.now().isoformat()
        bubble = MessageBubble(role, text, ts)
        # insert before stretch
        self._feed.insertWidget(self._feed.count() - 1, bubble)
        QTimer.singleShot(40, lambda: self._feed_scroll.verticalScrollBar().setValue(
            self._feed_scroll.verticalScrollBar().maximum()
        ))

    def _dispatch(self, txt: str):
        self._asst_chip.set_state("thinking"); self._asst_chip.setText("THINKING")
        w = DashboardWorker(send_command, txt)
        w.result_sig.connect(lambda r: self._on_dispatched(txt, r))
        w.error_sig.connect(lambda e: self._on_error(e))
        self._workers.append(w)
        w.start()

    def _on_dispatched(self, txt, result):
        # result is (success, response_text) from send_command
        ok = bool(result[0]) if isinstance(result, tuple) else bool(result)
        response_text = result[1] if isinstance(result, tuple) else ""
        self._asst_chip.set_state("idle"); self._asst_chip.setText("IDLE")
        if response_text:
            # Render the real response immediately — no need to wait for DB reload
            self._append_message("assistant", response_text)
        # Still do a delayed reload to sync any messages persisted to DB
        QTimer.singleShot(1200, self._reload_feed)

    def _on_error(self, err: str):
        self._append_message("assistant", f"⚠  Error: {err}")

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
        # remove all widgets except stretch
        while self._feed.count() > 1:
            item = self._feed.itemAt(0)
            w = item.widget()
            if w is None:
                self._feed.removeItem(item); continue
            if w is self._feed_empty:
                self._feed.removeWidget(w); w.setParent(None); continue
            self._feed.removeWidget(w); w.setParent(None); w.deleteLater()
        if not self._history:
            self._feed.insertWidget(0, self._feed_empty)
            return
        user_msgs = [m for m in self._history if m.get("role") == "user"]
        if user_msgs:
            title = (user_msgs[-1].get("content") or "Conversation")[:48]
            if len(title) == 48: title += "…"
            self._hdr_title.setText(title)
        for m in self._history:
            role = m.get("role") or "user"
            if role not in ("user", "assistant"):
                role = "user" if role in ("human", "User") else "assistant"
            self._append_message(role, m.get("content") or "")
