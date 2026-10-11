"""
Intelligence Page
==================
Surface the assistant's actual memory and learned behavior:
  • Learned preferences / rules (from skills/learning)
  • Conversational memory (last N interactions)
  • Context / active memory items
  • User facts / preferences (DB-backed user_preferences)
  • Controls: add / delete / disable / search
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QTextEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMenu, QMessageBox,
    QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QSplitter,
    QListWidget, QListWidgetItem, QInputDialog,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState,
    rgba_str, get_contrast_color,
)
from ..service_adapters import (
    load_learned_rules, add_learned_rule, delete_learned_rule,
    load_recent_history, load_user_preferences, save_user_preference,
)
from ..workers import DashboardWorker


class AddRuleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Remember a Preference")
        self.resize(520, 260)
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)
        t = QLabel("Teach the assistant something new"); t.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(t)
        tip = QLabel("Examples: 'I prefer concise responses', 'Always schedule in the morning', 'Use metric units'")
        tip.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 12px;"); tip.setWordWrap(True)
        root.addWidget(tip)
        self._rule = QLineEdit(); self._rule.setPlaceholderText("Remember that I prefer…")
        root.addWidget(self._rule)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryBtn")
        btns.accepted.connect(self._accept); btns.rejected.connect(self.reject)
        root.addWidget(btns)
        self.rule_text = None

    def _accept(self):
        if len(self._rule.text().strip()) < 4:
            QMessageBox.warning(self, "Too short", "Please enter a more detailed description.")
            return
        self.rule_text = self._rule.text().strip()
        self.accept()


class IntelligencePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: List[Dict] = []
        self._history: List[Dict] = []
        self._prefs: Dict[str, Any] = {}
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        head = QHBoxLayout(); head.setSpacing(Spacing.MD)
        sh = SectionHeader("Intelligence",
                          "What the assistant knows, remembers, and has learned about you.",
                          accent=C.SEC_INTELLIGENCE)
        head.addWidget(sh, 1); head.addStretch(1)
        self._search = QLineEdit(); self._search.setPlaceholderText("Search memory, rules, and history…")
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 14), QLineEdit.ActionPosition.LeadingPosition)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        self._search.setMinimumWidth(280)
        self._search.setMaximumWidth(420)
        self._search.returnPressed.connect(self._reload)
        head.addWidget(self._search)
        refresh = QPushButton(); refresh.setObjectName("IconBtn")
        refresh.setIcon(icon(ICONS.REFRESH, C.TEXT, 14)); refresh.setFixedSize(34, 34)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self._reload)
        head.addWidget(refresh)
        self._new_btn = QPushButton("  New Preference")
        self._new_btn.setObjectName("PrimaryBtn"); self._new_btn.setIcon(icon(ICONS.LIGHTBULB, get_contrast_color(C.ACCENT), 14))
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.clicked.connect(self._new_rule)
        head.addWidget(self._new_btn)
        hw = QWidget(); hw.setLayout(head)
        root.addWidget(hw)

        # Stats: Purple primary, green for learned/saved, cyan for active context
        sr = QHBoxLayout(); sr.setSpacing(Spacing.MD)
        self._s_rules = self._stat("Learned Rules",   "0", ICONS.LIGHTBULB,   C.SEC_INTELLIGENCE)
        self._s_hist  = self._stat("Recent Interactions", "0", ICONS.ASSISTANT, C.SEC_INTELLIGENCE)
        self._s_prefs = self._stat("Saved Preferences", "0", ICONS.STAR,       C.STATUS_SUCCESS)
        self._s_ctx   = self._stat("Active Context",  "—", ICONS.BRAIN,       C.STATUS_ACTIVE)
        for s in (self._s_rules, self._s_hist, self._s_prefs, self._s_ctx):
            sr.addWidget(s, 1)
        sw = QWidget(); sw.setLayout(sr)
        root.addWidget(sw)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- Rules + learned preferences ---
        rules_card = Card(title="Learned Rules / Preferences", accent=C.SEC_INTELLIGENCE)
        self._loading_rules = LoadingState("Loading rules…")
        rules_card.body.addWidget(self._loading_rules)
        self._rules_empty = EmptyState(ICONS.LIGHTBULB, "No learned rules yet",
                                       "The assistant will build preferences as it learns about you.",
                                       accent=C.SEC_INTELLIGENCE)
        rules_card.body.addWidget(self._rules_empty)
        self._rules_empty.setVisible(False)
        rules_scroller = QScrollArea()
        rules_scroller.setWidgetResizable(True)
        rules_scroller.setFrameShape(QFrame.Shape.NoFrame)
        self._rules_list = QVBoxLayout()
        self._rules_list.setSpacing(Spacing.SM)
        self._rules_list.setContentsMargins(0, 0, 0, 0)
        rlw = QWidget()
        rlw.setLayout(self._rules_list)
        rules_scroller.setWidget(rlw)
        rules_card.body.addWidget(rules_scroller, 1)
        rules_card.setMinimumWidth(340)
        splitter.addWidget(rules_card)

        # --- Right: Preferences + Conversation memory ---
        right = QSplitter(Qt.Orientation.Vertical)

        prefs_card = Card(title="Stored Preferences (user_preferences)", accent=C.SEC_INTELLIGENCE)
        self._loading_prefs = LoadingState("Loading preferences…")
        prefs_card.body.addWidget(self._loading_prefs)
        self._prefs_empty = EmptyState(ICONS.STAR, "No saved preferences",
                                       "Customize assistant behavior through the Settings page.",
                                       accent=C.SEC_INTELLIGENCE)
        self._prefs_empty.setVisible(False)
        prefs_card.body.addWidget(self._prefs_empty)
        self._prefs_table = QTableWidget(0, 2)
        self._prefs_table.setHorizontalHeaderLabels(["Key", "Value"])
        self._prefs_table.verticalHeader().setVisible(False)
        self._prefs_table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked |
                                          QAbstractItemView.EditTrigger.EditKeyPressed)
        self._prefs_table.setFrameShape(QFrame.Shape.NoFrame); self._prefs_table.setShowGrid(False)
        hh = self._prefs_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._prefs_table.itemChanged.connect(self._on_pref_edit)
        prefs_card.body.addWidget(self._prefs_table, 1)
        right.addWidget(prefs_card)

        hist_card = Card(title="Recent Interactions", accent=C.SEC_INTELLIGENCE)
        self._loading_hist = LoadingState("Loading recent interactions…")
        hist_card.body.addWidget(self._loading_hist)
        self._hist_empty = EmptyState(ICONS.ASSISTANT, "No conversation history",
                                      "Recent interactions will appear here as you use the assistant.",
                                      accent=C.SEC_INTELLIGENCE)
        self._hist_empty.setVisible(False)
        hist_card.body.addWidget(self._hist_empty)
        self._hist_table = QTableWidget(0, 3)
        self._hist_table.setHorizontalHeaderLabels(["Role", "Content", "Time"])
        self._hist_table.verticalHeader().setVisible(False)
        self._hist_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._hist_table.setFrameShape(QFrame.Shape.NoFrame); self._hist_table.setShowGrid(False)
        hh2 = self._hist_table.horizontalHeader()
        hh2.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh2.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh2.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hist_card.body.addWidget(self._hist_table, 1)
        right.addWidget(hist_card)

        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        QTimer.singleShot(0, self._reload)

    # ----------------------------- data --------------------------------
    def _stat(self, title, value, icon_name, color) -> QFrame:
        w = QFrame(); w.setProperty("class", "CardPanel")
        l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        l.setSpacing(Spacing.MD)
        tile = QLabel(); tile.setFixedSize(38, 38)
        tile.setStyleSheet(
            f"background: {rgba_str(color, 0.14)}; "
            f"border-radius: {Radius.MD}px;"
        )
        tl = QVBoxLayout(tile); tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel(); ic.setPixmap(icon_pixmap(icon_name, color, 16)); ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(ic)
        l.addWidget(tile)
        col = QVBoxLayout(); col.setSpacing(0)
        t = QLabel(str(value)); t.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C.TEXT};")
        s = QLabel(title); s.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM}; letter-spacing: 0.4px;")
        col.addWidget(t); col.addWidget(s)
        l.addLayout(col, 1)
        w._val_lbl = t
        return w

    def _reload(self):
        self._loading_rules.setVisible(True)
        self._loading_prefs.setVisible(True)
        self._loading_hist.setVisible(True)
        w1 = DashboardWorker(load_learned_rules)
        w1.result_sig.connect(self._on_rules); self._workers.append(w1); w1.start()
        w2 = DashboardWorker(load_user_preferences)
        w2.result_sig.connect(self._on_prefs); self._workers.append(w2); w2.start()
        w3 = DashboardWorker(load_recent_history, 60)
        w3.result_sig.connect(self._on_hist); self._workers.append(w3); w3.start()

    def _on_rules(self, rules):
        self._loading_rules.setVisible(False)
        self._rules = list(rules or [])
        q = (self._search.text() or "").lower()
        if q:
            self._rules = [r for r in self._rules if q in (str(r.get("rule") or "") + str(r.get("id") or "")).lower()]
        self._s_rules._val_lbl.setText(str(len(self._rules)))
        from ..ds import clear_layout
        clear_layout(self._rules_list)
        if not self._rules:
            self._rules_empty.setVisible(True)
            return
        else:
            self._rules_empty.setVisible(False)
        for r in self._rules:
            w = QFrame(); w.setProperty("class", "CardInner")
            l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, 8, Spacing.MD, 8)
            l.setSpacing(Spacing.MD)
            chip = StatusChip("ACTIVE", "active"); l.addWidget(chip)
            col = QVBoxLayout(); col.setSpacing(0)
            t = QLabel(str(r.get("rule") or "")); t.setStyleSheet("font-weight: 500;")
            t.setWordWrap(True)
            s = QLabel(f"ID: {r.get('id')}  ·  Created {str(r.get('created_at') or r.get('timestamp') or '')[:16]}")
            s.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
            col.addWidget(t); col.addWidget(s)
            l.addLayout(col, 1)
            copy = QPushButton(); copy.setObjectName("IconBtn")
            copy.setIcon(icon(ICONS.COPY, C.TEXT_MED, 12)); copy.setFixedSize(28, 28)
            copy.setToolTip("Copy")
            copy.clicked.connect(lambda _=False, x=r.get("rule"): self._copy(str(x or "")))
            l.addWidget(copy)
            dele = QPushButton(); dele.setObjectName("IconBtn")
            dele.setIcon(icon(ICONS.TRASH, C.STATUS_ERROR, 12)); dele.setFixedSize(28, 28)
            dele.clicked.connect(lambda _=False, rid=r.get("id"): self._del_rule(rid))
            l.addWidget(dele)
            self._rules_list.addWidget(w)
        self._rules_list.addStretch(1)

    def _on_prefs(self, prefs: Dict):
        self._loading_prefs.setVisible(False)
        self._prefs = dict(prefs or {})
        self._s_prefs._val_lbl.setText(str(len(self._prefs)))
        
        if not self._prefs:
            self._prefs_table.setVisible(False)
            self._prefs_empty.setVisible(True)
            self._prefs_table.setRowCount(0)
            return
        else:
            self._prefs_table.setVisible(True)
            self._prefs_empty.setVisible(False)
        
        self._prefs_table.blockSignals(True)
        items = list(self._prefs.items())
        q = (self._search.text() or "").lower()
        if q:
            items = [(k, v) for k, v in items
                     if q in (str(k) + " " + str(v)).lower()]
        self._prefs_table.setRowCount(len(items))
        for i, (k, v) in enumerate(items):
            ki = QTableWidgetItem(str(k)); ki.setForeground(QColor(C.SEC_INTELLIGENCE))
            vi = QTableWidgetItem(str(v)[:200])
            vi.setFlags(vi.flags() | Qt.ItemFlag.ItemIsEditable)
            vi.setData(Qt.ItemDataRole.UserRole, k)  # store key for save
            self._prefs_table.setItem(i, 0, ki)
            self._prefs_table.setItem(i, 1, vi)
        self._prefs_table.blockSignals(False)

    def _on_hist(self, hist):
        self._loading_hist.setVisible(False)
        self._history = list(hist or [])
        self._s_hist._val_lbl.setText(str(len(self._history)))
        # Update context chip
        self._s_ctx._val_lbl.setText(f"{len(self._history)} items")
        q = (self._search.text() or "").lower()
        filtered = self._history
        if q:
            filtered = [m for m in self._history
                        if q in (str(m.get("content") or "") + str(m.get("role") or "")).lower()]
        
        if not filtered:
            self._hist_table.setVisible(False)
            self._hist_empty.setVisible(True)
            self._hist_table.setRowCount(0)
        else:
            self._hist_table.setVisible(True)
            self._hist_empty.setVisible(False)
            self._hist_table.setRowCount(len(filtered))
        for i, m in enumerate(filtered):
            role = str(m.get("role") or "user")
            content = (m.get("content") or "")[:200]
            when = str(m.get("created_at") or "")[:19]
            ri = QTableWidgetItem(role.upper())
            ri.setForeground(QColor(C.SEC_INTELLIGENCE if role == "user" else C.STATUS_ACTIVE))
            self._hist_table.setItem(i, 0, ri)
            self._hist_table.setItem(i, 1, QTableWidgetItem(content))
            self._hist_table.setItem(i, 2, QTableWidgetItem(when))

    # ------------------------- actions ----------------------------------
    def _copy(self, text: str):
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _new_rule(self):
        dlg = AddRuleDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.rule_text:
            w = DashboardWorker(add_learned_rule, dlg.rule_text)
            w.result_sig.connect(lambda ok: self._reload())
            self._workers.append(w)
            w.start()

    def _del_rule(self, rid):
        if not rid: return
        if QMessageBox.question(self, "Forget?", "Delete this preference / rule permanently?") != QMessageBox.StandardButton.Yes:
            return
        w = DashboardWorker(delete_learned_rule, str(rid))
        w.result_sig.connect(lambda ok: self._reload())
        self._workers.append(w)
        w.start()

    def _on_pref_edit(self, item):
        if item.column() != 1: return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key: return
        new_val = item.text()
        w = DashboardWorker(save_user_preference, None, str(key), new_val)
        w.result_sig.connect(lambda ok: self._reload())
        self._workers.append(w)
        w.start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def on_visible(self):
        self._reload()
