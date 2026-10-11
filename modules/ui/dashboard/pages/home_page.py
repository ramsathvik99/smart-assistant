"""
Home / Dashboard Page
======================
First page the user sees. Presents:
  • Animated assistant visual (orb)
  • Greeting with real username + assistant name
  • Assistant state chip
  • Main command interface (text + voice)
  • Current activity (task)
  • Recent interactions (from DB)
  • Attention required (reminders, email count)
  • Quick actions (common tasks: new chat, calendar, compose, doc generate)
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGridLayout, QScrollArea, QLineEdit, QMessageBox, QSizePolicy,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, HoverLift, rgba_str, get_contrast_color,
)
from ..service_adapters import (
    get_identity, send_command, load_recent_history,
    load_reminders, load_calendar_events, load_user_preferences,
)
from ..workers import DashboardWorker
from ._assistant_orb import AssistantOrbWidget


def _time_greeting(hour: Optional[int] = None) -> str:
    h = hour if hour is not None else datetime.now().hour
    if 3 <= h < 12:
        return "Good morning"
    if 12 <= h < 17:
        return "Good afternoon"
    if 17 <= h < 21:
        return "Good evening"
    return "Good night"


class QuickActionCard(QFrame):
    def __init__(self, icon_name: str, title: str, subtitle: str, accent: str,
                 on_click, parent=None):
        super().__init__(parent)
        self.setProperty("class", "CardInner")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(88)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        lay.setSpacing(Spacing.MD)
        # accent icon tile
        tile = QLabel()
        tile.setFixedSize(44, 44)
        try:
            h = accent.lstrip("#")
            if len(h) >= 6:
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                tile.setStyleSheet(
                    f"background: rgba({r},{g},{b},0.14); "
                    f"border-radius: {Radius.MD}px;"
                )
            else:
                tile.setStyleSheet(
                    f"background: rgba(0,212,255,0.14); "
                    f"border-radius: {Radius.MD}px;"
                )
        except Exception:
            tile.setStyleSheet(
                f"background: rgba(0,212,255,0.14); "
                f"border-radius: {Radius.MD}px;"
            )
        tile_l = QVBoxLayout(tile)
        tile_l.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(icon_pixmap(icon_name, accent, 22))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tile_l.addWidget(ic)
        lay.addWidget(tile, 0)
        # labels
        col = QVBoxLayout()
        col.setSpacing(2)
        t = QLabel(title)
        t.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {C.TEXT};")
        s = QLabel(subtitle)
        s.setStyleSheet(f"font-size: 12px; color: {C.TEXT_MED};")
        col.addWidget(t)
        col.addWidget(s)
        lay.addLayout(col, 1)
        # arrow
        ar = QLabel("›")
        ar.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 20px; font-weight: 700;")
        lay.addWidget(ar)
        # click: install event filter
        self._cb = on_click

    def mousePressEvent(self, ev):
        super().mousePressEvent(ev)
        try:
            if self._cb:
                self._cb()
        except Exception:
            pass

    def enterEvent(self, ev):
        super().enterEvent(ev)
        self.setStyleSheet(f".QuickActionCard {{ border: 1px solid {rgba_str(C.SEC_DASHBOARD, 0.40)}; background: {C.PANEL3}; border-radius: {Radius.LG}px; }}")

    def leaveEvent(self, ev):
        super().leaveEvent(ev)
        self.setStyleSheet("")


class HomePage(QWidget):
    navigate = None  # will be set by shell to lambda page_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._identity: Dict = {}
        self._state: Dict = {}
        self._reminders: List[Dict] = []
        self._events: List[Dict] = []
        self._history: List[Dict] = []
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        outer.setSpacing(Spacing.LG)

        scroller = QScrollArea()
        scroller.setWidgetResizable(True)
        scroller.setFrameShape(QFrame.Shape.NoFrame)
        scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sw = QWidget()
        root = QVBoxLayout(sw)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(Spacing.LG)

        # -------- Hero section: greeting + orb + command (more compact)
        hero = QHBoxLayout()
        hero.setSpacing(Spacing.LG)

        # Left: greeting + status + command
        left = QVBoxLayout()
        left.setSpacing(Spacing.SM)

        self._greeting_lbl = QLabel("Good morning")
        self._greeting_lbl.setStyleSheet(
            f"font-size: 24px; font-weight: 700; letter-spacing: -0.5px; color: {C.TEXT};"
        )
        left.addWidget(self._greeting_lbl)

        self._name_row = QHBoxLayout()
        self._name_row.setSpacing(Spacing.SM)
        self._user_lbl = QLabel("User")
        self._user_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {C.SEC_DASHBOARD}; letter-spacing: -0.3px;")
        self._dot = QLabel("·")
        self._dot.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 18px; padding: 0 2px;")
        self._asst_lbl = QLabel("Assistant")
        self._asst_lbl.setStyleSheet(f"font-size: 16px; font-weight: 500; color: {C.TEXT_MED}; letter-spacing: -0.1px;")
        self._name_row.addWidget(self._user_lbl)
        self._name_row.addWidget(self._dot)
        self._name_row.addWidget(self._asst_lbl)
        self._name_row.addStretch(1)
        self._state_chip = StatusChip("IDLE", "online")
        self._state_chip.setCursor(Qt.CursorShape.PointingHandCursor)
        self._name_row.addWidget(self._state_chip)
        left.addLayout(self._name_row)

        self._sub_lbl = QLabel("What would you like to do today?")
        self._sub_lbl.setStyleSheet(f"font-size: 13px; color: {C.TEXT_MED}; letter-spacing: 0.05px;")
        left.addWidget(self._sub_lbl)

        left.addSpacing(Spacing.SM)

        # Command input (more compact)
        cmd_card = QFrame()
        cmd_card.setProperty("class", "CardInner")
        cmd_lay = QVBoxLayout(cmd_card)
        cmd_lay.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        cmd_row = QHBoxLayout()
        cmd_row.setSpacing(Spacing.SM)
        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("Ask anything…")
        self._cmd_input.setCursor(Qt.CursorShape.IBeamCursor)
        self._cmd_input.setStyleSheet(
            f"QLineEdit {{ border: none; background: transparent; padding: 8px 4px; font-size: 14px; color: {C.TEXT}; }}"
        )
        self._cmd_input.returnPressed.connect(self._on_send)
        cmd_row.addWidget(self._cmd_input, 1)

        self._mic_btn = QPushButton()
        self._mic_btn.setObjectName("IconBtn")
        self._mic_btn.setIcon(icon(ICONS.MIC, C.SEC_DASHBOARD, 16))
        self._mic_btn.setToolTip("Voice input")
        self._mic_btn.setFixedSize(36, 36)
        self._mic_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mic_btn.clicked.connect(lambda: self._send_as_command("Toggle voice listening"))
        cmd_row.addWidget(self._mic_btn)

        self._send_btn = QPushButton()
        self._send_btn.setObjectName("PrimaryBtn")
        self._send_btn.setIcon(icon(ICONS.SEND, get_contrast_color(C.SEC_DASHBOARD), 16))
        self._send_btn.setToolTip("Send")
        self._send_btn.setFixedSize(40, 40)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.clicked.connect(self._on_send)
        cmd_row.addWidget(self._send_btn)
        cmd_lay.addLayout(cmd_row)
        left.addWidget(cmd_card)
        left.addStretch(1)

        # Right: orb (smaller, more compact)
        self._orb = AssistantOrbWidget(200)
        right = QVBoxLayout()
        right.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right.addWidget(self._orb)
        self._orb_sub = QLabel("READY")
        self._orb_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._orb_sub.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 10px; font-weight: 600; letter-spacing: 2px;")
        right.addWidget(self._orb_sub)
        right_w = QWidget()
        right_w.setLayout(right)
        right_w.setMinimumWidth(240)
        right_w.setMaximumWidth(280)

        hero.addLayout(left, 1)
        hero.addWidget(right_w, 0)

        hero_w = QWidget()
        hero_w.setLayout(hero)
        root.addWidget(hero_w)

        # -------- Quick actions (horizontal chips for better space utilization) --------
        root.addWidget(SectionHeader("Quick Actions", "Jump straight into what you need", accent=C.SEC_DASHBOARD))
        qa_row = QHBoxLayout()
        qa_row.setSpacing(Spacing.SM)
        actions = [
            (ICONS.ASSISTANT,     "Conversation", C.SEC_ASSISTANT,     lambda: self._go("assistant")),
            (ICONS.COMMUNICATIONS, "Email",        C.SEC_COMMUNICATIONS, lambda: self._go_quick("communications", "compose")),
            (ICONS.SCHEDULE,       "Schedule",     C.SEC_SCHEDULE,       lambda: self._go("schedule")),
            (ICONS.FILE_PDF,     "Document",     C.SEC_WORKSPACE,      lambda: self._go("workspace")),
            (ICONS.CONNECTED_WORLD, "Devices",      C.SEC_CONNECTED,      lambda: self._go("connected_world")),
            (ICONS.INTELLIGENCE,    "Memory",       C.SEC_INTELLIGENCE,   lambda: self._go("intelligence")),
        ]
        for icn, title, acc_col, cb in actions:
            btn = QPushButton(title)
            btn.setObjectName("GhostBtn")
            btn.setIcon(icon(icn, acc_col, 14))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(cb)
            qa_row.addWidget(btn, 1)
        root.addLayout(qa_row)

        # -------- Two columns: Attention required / Recent --------
        cols = QHBoxLayout()
        cols.setSpacing(Spacing.MD)

        # --- Attention column
        col_left = Card(title="Attention Required", accent=C.STATUS_WARNING)
        col_left.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._attn_stack = QVBoxLayout()
        self._attn_stack.setSpacing(Spacing.SM)
        self._attn_loading = LoadingState("Checking reminders and events…")
        self._attn_stack.addWidget(self._attn_loading)
        col_left.body.addLayout(self._attn_stack)
        cols.addWidget(col_left, 1)

        # --- Recent column
        col_right = Card(title="Recent Interactions", accent=C.SEC_INTELLIGENCE)
        col_right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._hist_stack = QVBoxLayout()
        self._hist_stack.setSpacing(Spacing.SM)
        self._hist_loading = LoadingState("Loading conversation history…")
        self._hist_stack.addWidget(self._hist_loading)
        col_right.body.addLayout(self._hist_stack)
        cols.addWidget(col_right, 1)

        cols_w = QWidget(); cols_w.setLayout(cols)
        cols_w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(cols_w, 2)

        # Current activity strip
        act = Card(title="Current Activity", accent=C.STATUS_ACTIVE)
        act.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._act_stack = QVBoxLayout()
        self._act_stack.setSpacing(Spacing.SM)
        self._act_empty = EmptyState(ICONS.POWER, "All systems idle",
                                    "Assistant isn't doing anything right now.",
                                    accent=C.STATUS_ACTIVE)
        self._act_stack.addWidget(self._act_empty)
        act.body.addLayout(self._act_stack)
        root.addWidget(act, 1)

        scroller.setWidget(sw)
        outer.addWidget(scroller, 1)

        # Initial refresh timers
        QTimer.singleShot(0, self._refresh_attention)
        QTimer.singleShot(100, self._refresh_history)

    # ---------------------- helpers --------------------------------------
    def _go(self, page_id: str):
        mw = self.window()
        if hasattr(mw, "_on_nav"):
            mw._on_nav(page_id)
        elif HomePage.navigate:
            HomePage.navigate(page_id)

    def _go_quick(self, page_id: str, action: str):
        self._go(page_id)
        if page_id == "communications" and action == "compose":
            mw = self.window()
            if hasattr(mw, "_page_map") and "communications" in mw._page_map:
                comm_page = mw._page_map["communications"]
                if hasattr(comm_page, "_open_compose"):
                    QTimer.singleShot(150, comm_page._open_compose)

    def _on_send(self):
        txt = self._cmd_input.text().strip()
        if not txt:
            return
        self._send_as_command(txt)
        self._cmd_input.clear()

    def _send_as_command(self, txt: str):
        self._cmd_input.clear()
        w = DashboardWorker(send_command, txt)
        w.result_sig.connect(lambda r: self._refresh_history())
        self._workers.append(w)
        w.start()

    # ---------------------- identity / state ------------------------------
    def on_identity(self, ident: Dict):
        self._identity = ident
        uname = (ident.get("username") or "User").capitalize()
        aname = ident.get("assistant_name") or "Trevon"
        self._greeting_lbl.setText(_time_greeting() + ",")
        self._user_lbl.setText(uname)
        self._asst_lbl.setText(f"I'm your assistant {aname}")

    def on_assistant_state(self, data: Dict):
        self._state = data
        s = (data.get("state") or "idle").lower()
        self._orb.on_assistant_state(data)
        self._state_chip.set_state(s)
        self._state_chip.setText(s.upper())
        labels = {
            "idle": "Ready",
            "listening": "Listening…",
            "thinking": "Thinking…",
            "speaking": "Speaking…",
            "executing": "Executing…",
            "working": "Working…",
            "processing": "Processing…",
            "error": "Error",
            "offline": "Offline",
        }
        self._orb_sub.setText(labels.get(s, "Ready"))
        # current activity
        task = data.get("active_operation") or data.get("task")
        prog = data.get("progress") or 0
        from ..ds import clear_layout
        clear_layout(self._act_stack)
        if task:
            # Build activity widget
            row_w = QWidget()
            rl = QHBoxLayout(row_w); rl.setContentsMargins(0, 0, 0, 0); rl.setSpacing(Spacing.MD)
            chip = StatusChip("RUNNING", "executing")
            rl.addWidget(chip)
            lbl = QLabel(str(task))
            lbl.setStyleSheet(f"font-weight: 600; color: {C.TEXT};")
            rl.addWidget(lbl)
            rl.addStretch(1)
            if prog:
                from PyQt6.QtWidgets import QProgressBar
                bar = QProgressBar()
                bar.setFixedWidth(200)
                bar.setFixedHeight(8)
                bar.setValue(int(prog))
                bar.setTextVisible(False)
                rl.addWidget(bar)
            self._act_stack.addWidget(row_w)
        else:
            self._act_stack.addWidget(self._act_empty)

    # ---------------------- attention ---------------------------------------------
    def _refresh_attention(self):
        w1 = DashboardWorker(load_reminders)
        w1.result_sig.connect(self._on_reminders)
        self._workers.append(w1)
        w1.start()
        w2 = DashboardWorker(load_calendar_events)
        w2.result_sig.connect(self._on_events)
        self._workers.append(w2)
        w2.start()

    def _on_reminders(self, rems):
        self._reminders = list(rems or [])
        self._refresh_attn_ui()

    def _on_events(self, evs):
        self._events = list(evs or [])
        self._refresh_attn_ui()

    def _refresh_attn_ui(self):
        from ..ds import clear_layout
        clear_layout(self._attn_stack)
        items = []
        for r in self._reminders[:5]:
            if not r.get("is_notified"):
                items.append(("⏰", "Reminder", r.get("task_text", "")[:60],
                              str(r.get("due_at") or "")[:16]))
        for e in self._events[:5]:
            items.append(("📅", "Event", (e.get("title") or "")[:60],
                         f"{e.get('date') or ''} {e.get('time') or ''}".strip()))
        if not items:
            empty = EmptyState(ICONS.CHECK, "Nothing urgent",
                              "No upcoming reminders or events require your attention.",
                              accent=C.STATUS_SUCCESS)
            self._attn_stack.addWidget(empty)
            return
        for icon_ch, kind, text, when in items:
            w = QFrame(); w.setProperty("class", "CardInner")
            l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
            l.setSpacing(Spacing.MD)
            ic = QLabel(icon_ch); ic.setStyleSheet("font-size: 18px; background: transparent;")
            l.addWidget(ic)
            c = QVBoxLayout(); c.setSpacing(2)
            t = QLabel(text); t.setStyleSheet(f"font-weight: 500; color: {C.TEXT}; background: transparent;")
            k = QLabel(f"{kind} · {when}"); k.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px; background: transparent;")
            c.addWidget(t); c.addWidget(k)
            l.addLayout(c, 1)
            self._attn_stack.addWidget(w)

    # ---------------------- history -----------------------------------------
    def _refresh_history(self):
        w = DashboardWorker(load_recent_history, 8)
        w.result_sig.connect(self._on_history)
        self._workers.append(w)
        w.start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def _on_history(self, items):
        self._history = list(items or [])
        from ..ds import clear_layout
        clear_layout(self._hist_stack)
        msgs = [m for m in self._history if m.get("role") == "user"]
        if not msgs:
            empty = EmptyState(ICONS.ASSISTANT, "No conversations yet",
                          "Start by typing above or open Assistant page.",
                          accent=C.SEC_INTELLIGENCE)
            self._hist_stack.addWidget(empty)
            return
        for m in msgs[-6:]:
            w = QFrame(); w.setProperty("class", "CardInner")
            l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
            l.setSpacing(Spacing.MD)
            av = QLabel("U"); av.setFixedSize(28, 28)
            av.setAlignment(Qt.AlignmentFlag.AlignCenter)
            av.setStyleSheet(f"border-radius: 14px; background: {rgba_str(C.SEC_DASHBOARD, 0.15)}; color: {C.SEC_DASHBOARD}; font-weight: 700; font-size: 11px;")
            l.addWidget(av)
            col = QVBoxLayout(); col.setSpacing(0)
            t = QLabel((m.get("content") or "")[:90])
            t.setStyleSheet(f"color: {C.TEXT}; font-size: 12px; background: transparent;")
            t.setWordWrap(True)
            col.addWidget(t)
            sub = QLabel(str(m.get("created_at") or "")[:16])
            sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; background: transparent;")
            col.addWidget(sub)
            l.addLayout(col, 1)
            self._hist_stack.addWidget(w)

    def on_visible(self):
        self._refresh_attention()
        self._refresh_history()
