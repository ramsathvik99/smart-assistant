"""
Automation Page
================
  • Shows learned behavioral rules (from skills/learning)
  • Rules = lightweight automation (condition → behavior preference)
  • Create / enable / disable / delete rules
  • Last run / history (best effort from reminders + logs)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QTextEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMenu, QMessageBox,
    QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QSplitter,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState, HoverLift,
    rgba_str, get_contrast_color,
)
from ..service_adapters import (
    load_learned_rules, add_learned_rule, delete_learned_rule,
    load_reminders,
)
from ..workers import DashboardWorker


class NewRuleDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Rule")
        self.resize(520, 360)
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)
        t = QLabel("New Automation Rule"); t.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(t)
        tip = QLabel("Teach the assistant a preference. Examples:\n"
                     "• Always reply in bullet points for technical questions\n"
                     "• Use short, concise messages unless I ask for detail\n"
                     "• Prefer Google Calendar for scheduling")
        tip.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 12px;")
        tip.setWordWrap(True)
        root.addWidget(tip)
        form = QFormLayout(); form.setSpacing(Spacing.MD)
        self._rule = QTextEdit(); self._rule.setPlaceholderText("Remember that I prefer…")
        self._rule.setFixedHeight(110)
        form.addRow("Rule / Preference", self._rule)
        self._enabled = QCheckBox("Enabled"); self._enabled.setChecked(True)
        form.addRow("", self._enabled)
        root.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryBtn")
        btns.accepted.connect(self._accept); btns.rejected.connect(self.reject)
        root.addWidget(btns)
        self.rule_text = None

    def _accept(self):
        txt = self._rule.toPlainText().strip()
        if len(txt) < 4:
            QMessageBox.warning(self, "Too short", "Please enter a more descriptive rule.")
            return
        self.rule_text = txt
        self.accept()


class AutomationPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rules: List[Dict] = []
        self._rems: List[Dict] = []
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        head = QHBoxLayout(); head.setSpacing(Spacing.MD)
        sh = SectionHeader("Automation", "Learned preferences, behavioral rules, and scheduled reminders", accent=C.SEC_AUTOMATION)
        head.addWidget(sh, 1); head.addStretch(1)
        self._refresh_btn = QPushButton(); self._refresh_btn.setObjectName("IconBtn")
        self._refresh_btn.setIcon(icon(ICONS.REFRESH, C.TEXT, 14)); self._refresh_btn.setFixedSize(34, 34)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._reload)
        head.addWidget(self._refresh_btn)
        self._new_btn = QPushButton("  New Rule")
        self._new_btn.setObjectName("PrimaryBtn")
        self._new_btn.setIcon(icon(ICONS.PLUS, get_contrast_color(C.ACCENT), 14))
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.clicked.connect(self._new_rule)
        head.addWidget(self._new_btn)
        hw = QWidget(); hw.setLayout(head)
        root.addWidget(hw)

        stats_row = QHBoxLayout(); stats_row.setSpacing(Spacing.MD)
        self._sc1 = self._stat_card("Total Rules",  "0", ICONS.AUTOMATION, C.SEC_AUTOMATION)
        self._sc2 = self._stat_card("Enabled",      "0", ICONS.POWER,      C.STATUS_SUCCESS)
        self._sc3 = self._stat_card("Reminders",    "0", ICONS.CLOCK,      C.SEC_AUTOMATION)
        self._sc4 = self._stat_card("Last trigger", "—", ICONS.BOLT,       C.SEC_AUTOMATION)
        for s in (self._sc1, self._sc2, self._sc3, self._sc4):
            stats_row.addWidget(s, 1)
        srw = QWidget(); srw.setLayout(stats_row)
        root.addWidget(srw)

        # Rules table
        rules_card = Card(title="Learned Rules / Preferences", accent=C.SEC_AUTOMATION)
        self._loading = LoadingState("Loading rules…")
        rules_card.body.addWidget(self._loading)
        self._empty = EmptyState(ICONS.AUTOMATION, "No rules defined yet",
                                  "Create a new rule to define assistant behavior preferences.",
                                  accent=C.SEC_AUTOMATION)
        self._empty.setVisible(False)
        rules_card.body.addWidget(self._empty)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["", "ID", "Rule", "Created", "Actions"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setFrameShape(QFrame.Shape.NoFrame)
        self._table.setShowGrid(False)
        hh = self._table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._ctx_menu)
        rules_card.body.addWidget(self._table, 1)

        # Recent reminder runs
        history_card = Card(title="Recent Triggers (Reminder Notifications)", accent=C.SEC_AUTOMATION)
        hist_scroll = QScrollArea()
        hist_scroll.setWidgetResizable(True)
        hist_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._hist_stack = QVBoxLayout(); self._hist_stack.setSpacing(Spacing.SM)
        self._hist_empty = EmptyState(ICONS.BARS, "No recent triggers",
                                     "The reminder engine will show its most recent activity here.",
                                     accent=C.SEC_AUTOMATION)
        self._hist_stack.addWidget(self._hist_empty)
        hw_w = QWidget(); hw_w.setLayout(self._hist_stack)
        hist_scroll.setWidget(hw_w)
        history_card.body.addWidget(hist_scroll, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(rules_card)
        splitter.addWidget(history_card)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        QTimer.singleShot(0, self._reload)

    def _stat_card(self, title: str, value: str, icon_name: str, color: str) -> QFrame:
        w = QFrame(); w.setProperty("class", "CardPanel")
        l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        l.setSpacing(Spacing.MD)
        tile = QLabel(); tile.setFixedSize(42, 42)
        tile.setStyleSheet(
            f"background: {rgba_str(color, 0.14)}; "
            f"border-radius: {Radius.MD}px;"
        )
        tl = QVBoxLayout(tile); tl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel(); ic.setPixmap(icon_pixmap(icon_name, color, 18)); ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tl.addWidget(ic)
        l.addWidget(tile)
        col = QVBoxLayout(); col.setSpacing(0)
        t = QLabel(value); t.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C.TEXT};")
        s = QLabel(title); s.setStyleSheet(f"font-size: 11px; color: {C.TEXT_DIM}; letter-spacing: 0.4px;")
        col.addWidget(t); col.addWidget(s)
        l.addLayout(col, 1)
        # keep reference
        w._val_lbl = t
        HoverLift.install_on(w, accent=color)
        return w

    # ----------------------------- data --------------------------------
    def _reload(self):
        self._loading.setVisible(True)
        w = DashboardWorker(load_learned_rules)
        w.result_sig.connect(self._on_rules)
        self._workers.append(w)
        w.start()
        w2 = DashboardWorker(load_reminders)
        w2.result_sig.connect(self._on_rems)
        self._workers.append(w2)
        w2.start()

    def _on_rules(self, rules):
        self._loading.setVisible(False)
        self._rules = list(rules or [])
        
        if not self._rules:
            self._table.setVisible(False)
            self._empty.setVisible(True)
            self._table.setRowCount(0)
        else:
            self._table.setVisible(True)
            self._empty.setVisible(False)
            self._table.setRowCount(len(self._rules))
        enabled_count = 0
        for i, r in enumerate(self._rules):
            rid = str(r.get("id") or "")
            rule_text = str(r.get("rule") or "")
            created = str(r.get("created_at") or r.get("timestamp") or "")[:16].replace("T", " ")
            enabled = not str(r.get("disabled", "")).lower() in ("1", "true", "yes")
            if enabled: enabled_count += 1
            rule_ic_color = C.SEC_AUTOMATION if enabled else C.STATUS_DISABLED
            items = [
                QTableWidgetItem(icon(ICONS.LIGHTBULB, rule_ic_color, 13), ""),
                QTableWidgetItem(rid),
                QTableWidgetItem(rule_text),
                QTableWidgetItem(created),
                QTableWidgetItem(""),
            ]
            for j, it in enumerate(items):
                self._table.setItem(i, j, it)

            # Action buttons in Column 4
            act_w = QWidget()
            act_lay = QHBoxLayout(act_w)
            act_lay.setContentsMargins(4, 2, 4, 2)
            act_lay.setSpacing(4)
            copy_b = QPushButton()
            copy_b.setObjectName("IconBtn")
            copy_b.setIcon(icon(ICONS.COPY, C.TEXT_MED, 12))
            copy_b.setFixedSize(28, 28)
            copy_b.setToolTip("Copy rule text")
            copy_b.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_b.clicked.connect(lambda _=False, txt=rule_text: self._copy_rule(txt))
            act_lay.addWidget(copy_b)

            del_b = QPushButton()
            del_b.setObjectName("IconBtn")
            del_b.setIcon(icon(ICONS.TRASH, C.STATUS_ERROR, 12))
            del_b.setFixedSize(28, 28)
            del_b.setToolTip("Delete rule")
            del_b.setCursor(Qt.CursorShape.PointingHandCursor)
            del_b.clicked.connect(lambda _=False, x=r.get("id"): self._delete_rule_by_id(x))
            act_lay.addWidget(del_b)
            self._table.setCellWidget(i, 4, act_w)

        self._table.resizeRowsToContents()

        # Update stat cards
        self._sc1._val_lbl.setText(str(len(self._rules)))
        self._sc2._val_lbl.setText(str(enabled_count))
        # Last trigger from reminders
        last = ""
        for r in (self._rems or []):
            if r.get("created_at"):
                last = str(r["created_at"])[:16].replace("T", " ")
                break
        self._sc4._val_lbl.setText(last or "—")
        if len(last) > 10:
            self._sc4._val_lbl.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C.TEXT};")
        else:
            self._sc4._val_lbl.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C.TEXT};")

    def _on_rems(self, rems):
        try:
            self._rems = list(rems or [])
            self._sc3._val_lbl.setText(str(len(self._rems)))
            # Update stat last trigger
            last = ""
            for r in (self._rems or []):
                if r.get("created_at"):
                    last = str(r["created_at"])[:16].replace("T", " ")
                    break
            self._sc4._val_lbl.setText(last or "—")
            if len(last) > 10:
                self._sc4._val_lbl.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {C.TEXT};")
            else:
                self._sc4._val_lbl.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {C.TEXT};")

            # Render history
            from ..ds import clear_layout
            clear_layout(self._hist_stack)
            rems_sorted = sorted(self._rems,
                                 key=lambda x: (x.get("created_at") or ""), reverse=True)
            if not rems_sorted:
                empty = EmptyState(ICONS.BARS, "No recent triggers",
                                   "The reminder engine will show its most recent activity here.",
                                   accent=C.SEC_AUTOMATION)
                self._hist_stack.addWidget(empty)
                return
            for r in rems_sorted[:8]:
                w = QFrame(); w.setProperty("class", "CardInner")
                w.setMinimumHeight(44)
                w.setMaximumHeight(54)
                l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, 6, Spacing.MD, 6)
                l.setSpacing(Spacing.MD)
                state = "NOTIFIED" if r.get("is_notified") else "SCHEDULED"
                col = "success" if r.get("is_notified") else "pending"
                chip = StatusChip(state, col); l.addWidget(chip)
                col2 = QVBoxLayout(); col2.setSpacing(2)
                t = QLabel(r.get("task_text") or ""); t.setStyleSheet("font-weight: 500;")
                t.setWordWrap(True)
                c_date = str(r.get('created_at') or '')[:16].replace('T', ' ')
                d_date = str(r.get('due_at') or '')[:16].replace('T', ' ')
                sub = QLabel(f"Created {c_date}  ·  Due {d_date}")
                sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
                col2.addWidget(t); col2.addWidget(sub)
                l.addLayout(col2, 1)
                self._hist_stack.addWidget(w)
            self._hist_stack.addStretch(1)
        except Exception as e:
            print(f"[AUTOMATION_PAGE] Error updating reminders: {e}")

    # ------------------------------ actions ----------------------------
    def _copy_rule(self, text: str):
        try:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
        except Exception:
            pass

    def _delete_rule_by_id(self, rid):
        if rid and QMessageBox.question(self, "Delete?", "Delete this rule / preference?") == QMessageBox.StandardButton.Yes:
            w = DashboardWorker(delete_learned_rule, str(rid))
            w.result_sig.connect(lambda ok: self._reload())
            self._workers.append(w)
            w.start()

    # ------------------------------ actions ----------------------------
    def _new_rule(self):
        dlg = NewRuleDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.rule_text:
            w = DashboardWorker(add_learned_rule, dlg.rule_text)
            w.result_sig.connect(lambda ok: self._reload())
            self._workers.append(w)
            w.start()

    def _ctx_menu(self, pos):
        rows = list({it.row() for it in self._table.selectedItems()})
        if not rows:
            return
        idx = rows[0]
        if idx >= len(self._rules):
            return
        r = self._rules[idx]
        menu = QMenu(self)
        a_copy = menu.addAction(icon(ICONS.COPY, C.TEXT, 13), "Copy rule text")
        a_del = menu.addAction(icon(ICONS.TRASH, C.RED, 13), "Delete rule")
        choice = menu.exec(self._table.viewport().mapToGlobal(pos))
        if choice is a_copy:
            try:
                from PyQt6.QtWidgets import QApplication
                QApplication.clipboard().setText(str(r.get("rule") or ""))
            except Exception:
                pass
        elif choice is a_del:
            rid = r.get("id")
            if rid and QMessageBox.question(self, "Delete?", "Delete this rule / preference?") == QMessageBox.StandardButton.Yes:
                w = DashboardWorker(delete_learned_rule, str(rid))
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
