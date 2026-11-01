"""
Schedule Page (Calendar + Reminders)
=====================================
  • Tabs: Day / Week / Month / Upcoming / Reminders
  • Calendar events: create / edit / delete
  • Reminders: create / edit / delete / mark notified
  • Connects to calendar_storage and reminders table
"""

from __future__ import annotations

import calendar as _cal
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QSize, QTimer, QRect
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMenu, QMessageBox, QComboBox,
    QDateTimeEdit, QDialog, QDialogButtonBox, QTextEdit, QDateEdit,
    QFormLayout, QTimeEdit, QListWidget, QListWidgetItem, QGridLayout,
    QCheckBox, QSizePolicy,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState, rgba_str, get_contrast_color,
    hex_to_rgb,
)


class EventChip(QWidget):
    """Event chip that elides text smoothly via QFontMetrics instead of clipping."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        r, g, b = hex_to_rgb(C.ACC)
        p.setPen(QPen(QColor(r, g, b, 70), 1))
        p.setBrush(QColor(r, g, b, 32))
        p.drawRoundedRect(0, 0, w - 1, h - 1, 3, 3)

        fm = p.fontMetrics()
        avail_w = max(10, w - 10)
        elided = fm.elidedText(self._text, Qt.TextElideMode.ElideRight, avail_w)
        p.setPen(QColor(C.TEXT))
        p.drawText(QRect(5, 0, avail_w, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        p.end()

from ..service_adapters import (
    load_calendar_events, create_calendar_event, delete_calendar_event,
    load_reminders, create_reminder_ui, delete_reminder,
)
from ..workers import DashboardWorker


class EventDialog(QDialog):
    def __init__(self, parent=None, preset_date: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("New Calendar Event")
        self.resize(480, 380)
        self.setStyleSheet(f"""
            QDialog {{
                background: #0d1522;
                color: {C.TEXT};
            }}
            QLabel {{
                color: {C.TEXT};
                font-size: 13px;
            }}
            QLineEdit, QDateEdit, QTimeEdit, QDateTimeEdit, QTextEdit {{
                background: rgba(0, 0, 0, 0.40);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 6px 10px;
                color: {C.TEXT};
                font-size: 13px;
            }}
            QLineEdit:focus, QDateEdit:focus, QTimeEdit:focus, QDateTimeEdit:focus, QTextEdit:focus {{
                border: 1px solid {C.ACC};
            }}
            QCheckBox {{
                color: {C.TEXT_MED};
                font-size: 12px;
            }}
        """)
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)
        t = QLabel("New Calendar Event"); t.setStyleSheet("font-size: 18px; font-weight: 700; color: " + C.TEXT + ";")
        root.addWidget(t)

        form = QFormLayout(); form.setSpacing(Spacing.MD)
        self._title = QLineEdit(); self._title.setPlaceholderText("Event title")
        form.addRow("Title", self._title)
        self._date = QDateEdit()
        self._date.setCalendarPopup(True)
        self._date.setDisplayFormat("yyyy-MM-dd")
        try:
            if preset_date:
                from PyQt6.QtCore import QDate
                y, m, d = preset_date.split("-")
                self._date.setDate(QDate(int(y), int(m), int(d)))
            else:
                self._date.setDate(self._date.date().currentDate())
        except Exception:
            pass
        form.addRow("Date", self._date)
        self._time = QTimeEdit()
        self._time.setDisplayFormat("HH:mm")
        self._all_day = QCheckBox("All day")
        self._all_day.toggled.connect(lambda b: self._time.setEnabled(not b))
        form.addRow("", self._all_day)
        form.addRow("Time", self._time)
        self._desc = QTextEdit(); self._desc.setFixedHeight(80)
        self._desc.setPlaceholderText("Optional description, location, notes…")
        form.addRow("Description", self._desc)
        root.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryBtn")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)
        self.result_data = None

    def _accept(self):
        if not self._title.text().strip():
            QMessageBox.warning(self, "Title required", "Please enter an event title.")
            return
        date_s = self._date.date().toString("yyyy-MM-dd")
        time_s = "" if self._all_day.isChecked() else self._time.time().toString("HH:mm")
        self.result_data = {
            "title": self._title.text().strip(),
            "date": date_s,
            "time": time_s,
            "description": self._desc.toPlainText().strip(),
        }
        self.accept()


class ReminderDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Reminder")
        self.resize(480, 340)
        self.setStyleSheet(f"""
            QDialog {{
                background: #0d1522;
                color: {C.TEXT};
            }}
            QLabel {{
                color: {C.TEXT};
                font-size: 13px;
            }}
            QLineEdit, QDateTimeEdit, QTextEdit {{
                background: rgba(0, 0, 0, 0.40);
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 6px;
                padding: 6px 10px;
                color: {C.TEXT};
                font-size: 13px;
            }}
            QLineEdit:focus, QDateTimeEdit:focus, QTextEdit:focus {{
                border: 1px solid {C.ACC};
            }}
        """)
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)
        t = QLabel("New Reminder"); t.setStyleSheet("font-size: 18px; font-weight: 700; color: " + C.TEXT + ";")
        root.addWidget(t)
        form = QFormLayout(); form.setSpacing(Spacing.MD)
        self._task = QLineEdit(); self._task.setPlaceholderText("E.g. Call accountant at 5 PM")
        form.addRow("Remind me to", self._task)
        self._when = QDateTimeEdit()
        self._when.setDisplayFormat("yyyy-MM-dd HH:mm")
        self._when.setCalendarPopup(True)
        try:
            from PyQt6.QtCore import QDateTime
            self._when.setDateTime(QDateTime.currentDateTime().addSecs(3600))
        except Exception:
            pass
        form.addRow("When", self._when)
        self._notes = QTextEdit(); self._notes.setFixedHeight(60)
        self._notes.setPlaceholderText("Optional notes")
        form.addRow("Notes", self._notes)
        root.addLayout(form)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.button(QDialogButtonBox.StandardButton.Save).setObjectName("PrimaryBtn")
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)
        self.result_data = None

    def _accept(self):
        if not self._task.text().strip():
            QMessageBox.warning(self, "Task required", "Please enter what you want to be reminded about.")
            return
        iso = self._when.dateTime().toString(Qt.DateFormat.ISODate)
        self.result_data = {
            "task": self._task.text().strip(),
            "due_at_iso": iso,
            "notes": self._notes.toPlainText().strip(),
        }
        self.accept()


class SchedulePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._events: List[Dict] = []
        self._reminders: List[Dict] = []
        self._view_month = date.today()
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        head = QHBoxLayout(); head.setSpacing(Spacing.MD)
        sh = SectionHeader("Schedule", "Calendar events and time-based reminders", accent=C.ACC)
        head.addWidget(sh, 1); head.addStretch(1)

        self._new_event_btn = QPushButton("  New Event")
        self._new_event_btn.setObjectName("GhostBtn")
        self._new_event_btn.setIcon(icon(ICONS.SCHEDULE, C.TEXT, 14))
        self._new_event_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_event_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                color: {C.TEXT};
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
                background: rgba(255, 255, 255, 0.08);
            }}
        """)
        self._new_event_btn.clicked.connect(self._new_event)
        head.addWidget(self._new_event_btn)

        self._new_reminder_btn = QPushButton("  New Reminder")
        self._new_reminder_btn.setObjectName("PrimaryBtn")
        self._new_reminder_btn.setIcon(icon(ICONS.CLOCK, get_contrast_color(C.ACC), 14))
        self._new_reminder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_reminder_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.ACC};
                color: {get_contrast_color(C.ACC)};
                border: none;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {rgba_str(C.ACC, 0.88)};
            }}
        """)
        self._new_reminder_btn.clicked.connect(self._new_reminder)
        head.addWidget(self._new_reminder_btn)
        hw = QWidget(); hw.setLayout(head)
        root.addWidget(hw)

        tabs = QTabWidget()
        self._tabs = tabs
        tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-top: 1px solid rgba(255, 255, 255, 0.18);
                background: rgba(10, 16, 26, 0.45);
                border-radius: 10px;
                padding: 14px;
            }}
            QTabBar::tab {{
                background: rgba(255, 255, 255, 0.03);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-bottom: none;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                color: {C.TEXT_MED};
                padding: 8px 18px;
                font-size: 12px;
                font-weight: 600;
                margin-right: 4px;
            }}
            QTabBar::tab:selected {{
                background: rgba(255, 255, 255, 0.08);
                border-bottom: 2px solid {C.ACC};
                color: {C.TEXT};
            }}
            QTabBar::tab:hover {{
                color: {C.TEXT};
            }}
        """)

        # ---- Month calendar tab ----
        month_widget = QWidget()
        ml = QVBoxLayout(month_widget); ml.setContentsMargins(0, Spacing.MD, 0, 0)
        ml.setSpacing(Spacing.MD)

        mnav = QHBoxLayout(); mnav.setSpacing(Spacing.MD)
        prev = QPushButton(); prev.setObjectName("IconBtn")
        prev.setIcon(icon(ICONS.CHEVRON_LEFT, C.TEXT, 14)); prev.setFixedSize(30, 30)
        prev.setCursor(Qt.CursorShape.PointingHandCursor)
        prev.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
            }}
        """)
        prev.clicked.connect(lambda: self._shift_month(-1))
        mnav.addWidget(prev)
        self._month_lbl = QLabel(""); self._month_lbl.setStyleSheet("font-size: 17px; font-weight: 700; letter-spacing: -0.2px; color: " + C.TEXT + ";")
        self._month_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mnav.addWidget(self._month_lbl, 1)
        nxt = QPushButton(); nxt.setObjectName("IconBtn")
        nxt.setIcon(icon(ICONS.CHEVRON_RIGHT, C.TEXT, 14)); nxt.setFixedSize(30, 30)
        nxt.setCursor(Qt.CursorShape.PointingHandCursor)
        nxt.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
            }}
        """)
        nxt.clicked.connect(lambda: self._shift_month(1))
        mnav.addWidget(nxt)
        today = QPushButton("Today"); today.setObjectName("GhostBtn")
        today.setCursor(Qt.CursorShape.PointingHandCursor)
        today.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 6px;
                padding: 4px 12px;
                font-size: 12px;
                color: {C.TEXT};
            }}
            QPushButton:hover {{
                border: 1px solid {C.ACC};
            }}
        """)
        today.clicked.connect(lambda: self._go_today())
        mnav.addWidget(today)
        ml.addLayout(mnav)

        self._month_grid = QGridLayout(); self._month_grid.setSpacing(Spacing.XS)
        self._month_grid.setContentsMargins(0, 0, 0, 0)
        for c in range(7):
            self._month_grid.setColumnStretch(c, 1)
            self._month_grid.setColumnMinimumWidth(c, 84)
        weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        for i, wd in enumerate(weekdays):
            l = QLabel(wd)
            l.setStyleSheet(
                f"font-size: 11px; font-weight: 700; color: {C.TEXT_MED}; text-transform: uppercase; letter-spacing: 0.5px; padding: 4px;"
            )
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._month_grid.addWidget(l, 0, i)
        self._calendar_cells: List[QWidget] = []
        mw = QWidget(); mw.setLayout(self._month_grid)
        cal_scroll = QScrollArea()
        cal_scroll.setWidgetResizable(True)
        cal_scroll.setFrameShape(QFrame.Shape.NoFrame)
        cal_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cal_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        cal_scroll.setWidget(mw)
        ml.addWidget(cal_scroll, 1)
        tabs.addTab(month_widget, "  Month  ")

        # ---- Upcoming tab ----
        upcoming = QWidget()
        ul = QVBoxLayout(upcoming); ul.setContentsMargins(0, Spacing.MD, 0, 0)
        self._upcoming_loading = LoadingState("Loading events and reminders…")
        ul.addWidget(self._upcoming_loading)
        up_scroll = QScrollArea()
        up_scroll.setWidgetResizable(True)
        up_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._upcoming_stack = QVBoxLayout()
        self._upcoming_stack.setSpacing(Spacing.SM)
        uw = QWidget(); uw.setLayout(self._upcoming_stack)
        up_scroll.setWidget(uw)
        ul.addWidget(up_scroll, 1)
        tabs.addTab(upcoming, "  Upcoming  ")

        # ---- Reminders tab ----
        rem_tab = QWidget()
        rl = QVBoxLayout(rem_tab); rl.setContentsMargins(0, Spacing.MD, 0, 0)
        self._rem_loading = LoadingState("Loading reminders…")
        rl.addWidget(self._rem_loading)
        rem_scroll = QScrollArea()
        rem_scroll.setWidgetResizable(True)
        rem_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rem_list = QVBoxLayout(); self._rem_list.setSpacing(Spacing.SM)
        rlw = QWidget(); rlw.setLayout(self._rem_list)
        rem_scroll.setWidget(rlw)
        rl.addWidget(rem_scroll, 1)
        tabs.addTab(rem_tab, "  Reminders  ")

        root.addWidget(tabs, 1)

        QTimer.singleShot(0, self._reload)
        self._render_month()

    # ------------------------------- month ----------------------------
    def _shift_month(self, delta: int):
        y, m = self._view_month.year, self._view_month.month + delta
        while m < 1: m += 12; y -= 1
        while m > 12: m -= 12; y += 1
        self._view_month = date(y, m, 1)
        self._render_month()
        self._reload_events_for_view()

    def _go_today(self):
        self._view_month = date.today()
        self._render_month()
        self._reload_events_for_view()

    def _render_month(self):
        # Remove old cell widgets
        while self._month_grid.count() > 7:
            item = self._month_grid.itemAt(7)
            w = item.widget()
            if w is not None:
                w.setParent(None); w.deleteLater()
            else:
                self._month_grid.removeItem(item)
        self._calendar_cells = []
        self._month_lbl.setText(self._view_month.strftime("%B %Y"))
        # Start with Monday as first weekday
        y, m = self._view_month.year, self._view_month.month
        first_day = date(y, m, 1)
        # weekday(): Monday=0 ... Sunday=6
        start_col = first_day.weekday()
        days_in_month = _cal.monthrange(y, m)[1]
        today = date.today()
        # Build cells for 6 rows
        idx = 0
        for row in range(6):
            self._month_grid.setRowStretch(row + 1, 0)
            for col in range(7):
                d_num = idx - start_col + 1
                row_widget = QFrame()
                row_widget.setFixedHeight(68)
                row_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
                is_this_month = 1 <= d_num <= days_in_month
                day_date = date(y, m, d_num) if is_this_month else None
                if is_this_month:
                    bg = "rgba(255, 255, 255, 0.02)" if day_date != today else rgba_str(C.ACC, 0.10)
                    border = "rgba(255, 255, 255, 0.08)" if day_date != today else C.ACC
                    row_widget.setStyleSheet(f"""
                        QFrame {{
                            background: {bg};
                            border: 1px solid {border};
                            border-radius: 6px;
                        }}
                        QFrame:hover {{
                            background: rgba(255, 255, 255, 0.05);
                            border: 1px solid {C.ACC};
                        }}
                    """)
                else:
                    row_widget.setStyleSheet("""
                        QFrame {{
                            background: rgba(0, 0, 0, 0.20);
                            border: 1px solid rgba(255, 255, 255, 0.03);
                            border-radius: 6px;
                        }}
                    """)
                lay = QVBoxLayout(row_widget); lay.setContentsMargins(6, 4, 6, 4)
                lay.setSpacing(2)
                nr_lbl = QLabel(str(d_num) if is_this_month else "")
                nr_lbl.setStyleSheet(
                    f"font-size: 11px; font-weight: {'700' if day_date == today else '600'}; color: "
                    f"{'rgba(155, 188, 204, 0.25)' if not is_this_month else C.ACC if day_date == today else C.TEXT};"
                )
                lay.addWidget(nr_lbl)
                event_stack = QVBoxLayout(); event_stack.setSpacing(2); event_stack.setContentsMargins(0, 0, 0, 0)
                # Populate events if in month
                if is_this_month:
                    s = day_date.strftime("%Y-%m-%d")
                    evs = [e for e in self._events if str(e.get("date") or "") == s]
                    for ev in evs[:2]:
                        chip = EventChip(ev.get("title") or "Event")
                        event_stack.addWidget(chip)
                    if len(evs) > 2:
                        more_lbl = QLabel(f"+{len(evs) - 2} more")
                        more_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 10px; padding-left: 2px;")
                        event_stack.addWidget(more_lbl)
                lay.addLayout(event_stack, 1)
                # Click handler for creating events on date
                if is_this_month:
                    row_widget.setCursor(Qt.CursorShape.PointingHandCursor)
                    row_widget.mousePressEvent = lambda ev, d=s: self._new_event(d)
                self._month_grid.addWidget(row_widget, row + 1, col)
                self._calendar_cells.append(row_widget)
                idx += 1

    # ------------------------------- data ------------------------------
    def _track_worker(self, w: DashboardWorker) -> DashboardWorker:
        self._workers.append(w)
        try:
            w.finished.connect(lambda: self._workers.remove(w) if w in self._workers else None)
        except Exception:
            pass
        return w

    def _reload(self):
        self._reload_events_for_view()
        self._reload_reminders()

    def _reload_events_for_view(self):
        # Load ~6 weeks around month center
        y, m = self._view_month.year, self._view_month.month
        start = date(y, m, 1) - timedelta(days=7)
        days = 56
        w = DashboardWorker(load_calendar_events, start.strftime("%Y-%m-%d"), days)
        w.result_sig.connect(self._on_events)
        self._track_worker(w).start()

    def _reload_reminders(self):
        self._rem_loading.setVisible(True)
        w = DashboardWorker(load_reminders)
        w.result_sig.connect(self._on_reminders)
        self._track_worker(w).start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in list(self._workers):
            if worker and worker.isRunning():
                try:
                    worker.quit()
                    worker.wait(500)
                except Exception:
                    pass
        self._workers.clear()

    def _on_events(self, evs):
        try:
            self._events = list(evs or [])
            self._render_month()
            self._render_upcoming()
        except Exception as e:
            print(f"[SCHEDULE_PAGE] Error updating calendar events: {e}")

    def _on_reminders(self, rems):
        try:
            self._rem_loading.setVisible(False)
            self._reminders = list(rems or [])
            self._render_reminders()
            self._render_upcoming()
        except Exception as e:
            print(f"[SCHEDULE_PAGE] Error updating reminders: {e}")

    # ------------------------- renders ---------------------------
    def _render_upcoming(self):
        try:
            from ..ds import clear_layout
            clear_layout(self._upcoming_stack)
            items = []
            for e in self._events:
                ts = f"{e.get('date') or ''} {e.get('time') or ''}".strip()
                items.append((ts, "event", e.get("title") or "", e.get("description") or "", e))
            for r in self._reminders:
                ts = str(r.get("due_at") or "")[:16]
                items.append((ts, "reminder", r.get("task_text") or "", "", r))
            items.sort(key=lambda x: x[0] or "9")
            self._upcoming_loading.setVisible(False)
            if not items:
                empty = QLabel("No upcoming events or reminders")
                empty.setStyleSheet(f"font-size: 13px; color: {rgba_str(C.TEXT_DIM, 0.70)}; padding: 32px 16px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._upcoming_stack.addWidget(empty)
                return
            for ts, kind, title, desc, payload in items[:30]:
                w = QFrame()
                w.setStyleSheet(
                    "QFrame {"
                    "  background: rgba(255, 255, 255, 0.02);"
                    "  border-bottom: 1px solid rgba(255, 255, 255, 0.06);"
                    "  border-radius: 4px;"
                    "}"
                    "QFrame:hover {"
                    "  background: rgba(255, 255, 255, 0.04);"
                    "}"
                )
                l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
                l.setSpacing(Spacing.MD)
                icn = ICONS.SCHEDULE if kind == "event" else ICONS.CLOCK
                av = QLabel(); av.setPixmap(icon_pixmap(icn, C.ACC, 14)); av.setFixedWidth(24)
                l.addWidget(av)
                col2 = QVBoxLayout(); col2.setSpacing(2)
                t = QLabel(title); t.setStyleSheet("font-weight: 600; font-size: 13px; color: " + C.TEXT + ";")
                sub = QLabel(f"{'Event' if kind=='event' else 'Reminder'} · {ts}")
                sub.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
                col2.addWidget(t); col2.addWidget(sub)
                l.addLayout(col2, 1)
                self._upcoming_stack.addWidget(w)
        except Exception as e:
            print(f"[SCHEDULE_PAGE] Error rendering upcoming: {e}")

    def _render_reminders(self):
        try:
            from ..ds import clear_layout
            clear_layout(self._rem_list)
            if not self._reminders:
                empty = QLabel("No reminders set")
                empty.setStyleSheet(f"font-size: 13px; color: {rgba_str(C.TEXT_DIM, 0.70)}; padding: 32px 16px;")
                empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._rem_list.addWidget(empty)
                return
            for r in self._reminders:
                w = QFrame()
                w.setStyleSheet(
                    "QFrame {"
                    "  background: rgba(255, 255, 255, 0.02);"
                    "  border-bottom: 1px solid rgba(255, 255, 255, 0.06);"
                    "  border-radius: 4px;"
                    "}"
                    "QFrame:hover {"
                    "  background: rgba(255, 255, 255, 0.04);"
                    "}"
                )
                l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
                l.setSpacing(Spacing.MD)
                notified = bool(r.get("is_notified"))
                chip = StatusChip("NOTIFIED" if notified else "PENDING",
                                  "online" if notified else "pending")
                l.addWidget(chip)
                col = QVBoxLayout(); col.setSpacing(2)
                t = QLabel(r.get("task_text") or ""); t.setStyleSheet("font-weight: 600; font-size: 13px; color: " + C.TEXT + ";")
                s = QLabel("Due " + str(r.get("due_at") or "No date")[:19])
                s.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
                col.addWidget(t); col.addWidget(s)
                l.addLayout(col, 1)
                del_btn = QPushButton(); del_btn.setObjectName("IconBtn")
                del_btn.setStyleSheet(
                    "QPushButton { border: none; background: transparent; border-radius: 4px; }"
                    "QPushButton:hover { background: rgba(244, 63, 94, 0.18); }"
                )
                del_btn.setIcon(icon(ICONS.TRASH, C.STATUS_ERROR, 13)); del_btn.setFixedSize(28, 28)
                del_btn.clicked.connect(lambda _=False, rid=r.get("id"): self._delete_reminder(rid))
                l.addWidget(del_btn)
                self._rem_list.addWidget(w)
        except Exception as e:
            print(f"[SCHEDULE_PAGE] Error rendering reminders: {e}")

    # --------------------------- actions ------------------------------
    def _new_event(self, preset_date: Optional[str] = None):
        def _do():
            dlg = EventDialog(self, preset_date=preset_date or "")
            if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_data:
                r = dlg.result_data
                w = DashboardWorker(create_calendar_event, r["title"], r["date"], r["time"], r["description"])
                w.result_sig.connect(lambda ok: self._reload_events_for_view())
                self._track_worker(w).start()
        QTimer.singleShot(0, _do)

    def _new_reminder(self):
        dlg = ReminderDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result_data:
            r = dlg.result_data
            w = DashboardWorker(create_reminder_ui, r["task"], r["due_at_iso"])
            w.result_sig.connect(lambda ok: self._reload_reminders())
            self._track_worker(w).start()

    def _delete_reminder(self, rid):
        if rid is None: return
        if QMessageBox.question(self, "Delete?", "Delete this reminder?") != QMessageBox.StandardButton.Yes:
            return
        w = DashboardWorker(delete_reminder, rid)
        w.result_sig.connect(lambda ok: self._reload_reminders())
        self._track_worker(w).start()

    def on_visible(self):
        self._reload()
