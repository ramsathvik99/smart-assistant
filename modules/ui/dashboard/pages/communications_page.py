"""
Communications (Email) Page
============================
Full email interface:
  • Inbox / Sent / Drafts folders
  • Search + filters
  • Open email → read, reply, forward, delete
  • Compose editor
  • AI actions: summarize, improve, change tone, extract action items
  • Connections to modules/assistant_email/*.py
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QSplitter, QListWidget, QListWidgetItem,
    QTextEdit, QComboBox, QMessageBox, QFileDialog, QMenu, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDialog, QDialogButtonBox,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState, get_contrast_color,
)
from ..service_adapters import (
    load_emails, send_email_ui, has_email_credentials,
)
from ..workers import DashboardWorker


class ComposeDialog(QDialog):
    def __init__(self, parent=None, to: str = "", subject: str = "", body: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Compose Email")
        self.resize(680, 520)
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        root.setSpacing(Spacing.MD)
        title = QLabel("Compose Message"); title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        self._to = QLineEdit(to); self._to.setPlaceholderText("To: recipient@example.com")
        self._subject = QLineEdit(subject); self._subject.setPlaceholderText("Subject")
        self._body = QTextEdit(); self._body.setPlaceholderText("Write your message…")
        self._body.setPlainText(body)

        for w in [QLabel("To"), self._to, QLabel("Subject"), self._subject]:
            root.addWidget(w)
        root.addWidget(QLabel("Message"))
        root.addWidget(self._body, 1)

        # AI quick actions
        ai_row = QHBoxLayout(); ai_row.setSpacing(Spacing.SM)
        ai_lbl = QLabel("AI:"); ai_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 12px;")
        ai_row.addWidget(ai_lbl)
        for label, func in [
            ("Summarize", self._ai_summarize),
            ("Improve writing", self._ai_improve),
            ("Make concise", self._ai_concise),
            ("Change tone → Friendly", lambda: self._ai_tone("friendly")),
            ("Change tone → Formal", lambda: self._ai_tone("formal")),
        ]:
            b = QPushButton(label); b.setObjectName("GhostBtn")
            b.setStyleSheet("padding: 4px 10px;")
            b.clicked.connect(func)
            ai_row.addWidget(b)
        ai_row.addStretch(1)
        root.addLayout(ai_row)

        self._workers = []
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        send_btn = QPushButton("Send")
        send_btn.setObjectName("PrimaryBtn")
        btns.addButton(send_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        btns.accepted.connect(self._accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)
        self.result = None

    def _ai_summarize(self): self._run_ai("summarize")
    def _ai_improve(self): self._run_ai("improve")
    def _ai_concise(self): self._run_ai("concise")
    def _ai_tone(self, tone): self._run_ai(f"tone_{tone}")

    def _run_ai(self, kind: str):
        body = self._body.toPlainText().strip()
        if not body:
            return
        # Dispatch through assistant command
        prompts = {
            "summarize": f"Please summarize this email body:\n\n{body}\n\nReturn only the summary.",
            "improve":   f"Please improve the writing of this email:\n\n{body}\n\nReturn only the improved text.",
            "concise":   f"Make this email more concise (shorter, clearer):\n\n{body}\n\nReturn only the rewrite.",
            "tone_friendly": f"Rewrite this email in a warm, friendly tone:\n\n{body}\n\nReturn only the rewrite.",
            "tone_formal":   f"Rewrite this email in a formal, professional tone:\n\n{body}\n\nReturn only the rewrite.",
        }
        from ..service_adapters import send_command
        # best-effort; we won't block on response — insert placeholder
        self._body.setPlainText("✨  AI working on your request…")
        w = DashboardWorker(send_command, prompts.get(kind, ""))
        w.result_sig.connect(lambda r: QTimer.singleShot(2200,
            lambda: self._body.setPlainText(body) if not body else None))
        self._workers.append(w)
        w.start()

    def _accept(self):
        if not self._to.text().strip():
            QMessageBox.warning(self, "Missing recipient", "Please enter a recipient email.")
            return
        self.result = {
            "to": self._to.text().strip(),
            "subject": self._subject.text().strip() or "(No subject)",
            "body": self._body.toPlainText().strip() or "",
        }
        self.accept()


class CommunicationsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._inbox: List[Dict] = []
        self._sent: List[Dict] = []
        self._drafts: List[Dict] = []
        self._current_folder = "inbox"
        self._selected_idx: Optional[int] = None
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self); root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        head = QHBoxLayout(); head.setSpacing(Spacing.MD)
        sh = SectionHeader("Communications", "Inbox, sent messages, drafts, and AI-assisted composing", accent=C.SEC_COMMUNICATIONS)
        head.addWidget(sh, 1); head.addStretch(1)
        self._folder_combo = QComboBox()
        self._folder_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._folder_combo.addItems(["Inbox", "Sent", "Drafts"])
        self._folder_combo.currentIndexChanged.connect(self._on_folder_change)
        head.addWidget(self._folder_combo)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search messages, senders, subjects…")
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 14),
                               QLineEdit.ActionPosition.LeadingPosition)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        self._search.setMinimumWidth(280)
        self._search.setMaximumWidth(420)
        self._search.returnPressed.connect(self._reload_folder)
        head.addWidget(self._search)

        self._refresh_btn = QPushButton(); self._refresh_btn.setObjectName("IconBtn")
        self._refresh_btn.setIcon(icon(ICONS.REFRESH, C.TEXT, 14)); self._refresh_btn.setFixedSize(34, 34)
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.clicked.connect(self._reload_folder)
        head.addWidget(self._refresh_btn)

        self._compose_btn = QPushButton("  Compose")
        self._compose_btn.setObjectName("PrimaryBtn")
        self._compose_btn.setIcon(icon(ICONS.PLUS, get_contrast_color(C.SEC_COMMUNICATIONS), 14))
        self._compose_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._compose_btn.clicked.connect(self._open_compose)
        head.addWidget(self._compose_btn)

        head_w = QWidget(); head_w.setLayout(head)
        root.addWidget(head_w)

        # Status card
        cred_card = Card(title="Email Connection", accent=C.SEC_COMMUNICATIONS)
        cred_row = QHBoxLayout(); cred_row.setSpacing(Spacing.MD)
        self._cred_status = StatusChip("CHECKING", "offline")
        cred_row.addWidget(self._cred_status)
        self._cred_lbl = QLabel("Checking email credentials…")
        self._cred_lbl.setStyleSheet(f"color: {C.TEXT_MED};")
        cred_row.addWidget(self._cred_lbl); cred_row.addStretch(1)
        self._cred_cta = QPushButton("Set up email"); self._cred_cta.setObjectName("GhostBtn")
        self._cred_cta.setVisible(False)
        self._cred_cta.clicked.connect(self._setup_email)
        cred_row.addWidget(self._cred_cta)
        cred_card.body.addLayout(cred_row)
        root.addWidget(cred_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # --- List ---
        list_card = QFrame(); list_card.setProperty("class", "CardPanel")
        lv = QVBoxLayout(list_card); lv.setContentsMargins(Spacing.SM, Spacing.SM, Spacing.SM, Spacing.SM)
        lv.setSpacing(Spacing.SM)
        self._loading_l = LoadingState("Loading messages…")
        lv.addWidget(self._loading_l)
        self._empty_l = EmptyState(ICONS.COMMUNICATIONS, "No messages to display",
                                    "This folder is empty. Compose a new message to get started.",
                                    accent=C.SEC_COMMUNICATIONS)
        self._empty_l.setVisible(False)
        lv.addWidget(self._empty_l)
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["", "From", "Subject", "Preview", "Date"])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setFrameShape(QFrame.Shape.NoFrame)
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_select)
        lv.addWidget(self._table, 1)
        list_card.setMinimumWidth(320)
        splitter.addWidget(list_card)

        # --- Reader ---
        reader_card = QFrame(); reader_card.setProperty("class", "CardPanel")
        rv = QVBoxLayout(reader_card); rv.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        rv.setSpacing(Spacing.SM)

        self._rdr_subject = QLabel("No message selected")
        self._rdr_subject.setStyleSheet("font-size: 16px; font-weight: 700;")
        rv.addWidget(self._rdr_subject)

        self._rdr_meta = QLabel("Select an email from the list")
        self._rdr_meta.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px;")
        rv.addWidget(self._rdr_meta)

        action_row = QHBoxLayout(); action_row.setSpacing(Spacing.SM)
        for label, ic, fn in [
            ("Reply",     ICONS.ARROW_LEFT,  self._reply),
            ("Reply All", ICONS.ARROW_LEFT,  self._reply_all),
            ("Forward",   ICONS.ARROW_RIGHT, self._forward),
            ("Delete",    ICONS.TRASH,       self._delete),
        ]:
            b = QPushButton(f" {label}"); b.setObjectName("GhostBtn")
            b.setIcon(icon(ic, C.TEXT_MED, 12))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            action_row.addWidget(b)
        # AI actions
        action_row.addSpacing(Spacing.SM)
        ai_lbl = QLabel("AI:"); ai_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
        action_row.addWidget(ai_lbl)
        for label, fn in [
            ("Summarize",          self._ai_summarize_email),
            ("Draft reply",        self._ai_draft_reply),
            ("Extract action items", self._ai_extract_actions),
        ]:
            b = QPushButton(label); b.setObjectName("GhostBtn")
            b.setStyleSheet("padding: 5px 10px;")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            action_row.addWidget(b)
        action_row.addStretch(1)
        rv.addLayout(action_row)
        rv.addWidget(HLine())

        self._rdr_body = QTextEdit()
        self._rdr_body.setReadOnly(True)
        self._rdr_body.setStyleSheet(f"QTextEdit {{ background: transparent; border: none; padding: 0; color: {C.TEXT}; font-size: 13px; line-height: 1.7; }}")
        rv.addWidget(self._rdr_body, 1)

        splitter.addWidget(reader_card)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        QTimer.singleShot(0, self._refresh_credentials)
        QTimer.singleShot(120, self._reload_folder)

    # ----------------------- status / creds --------------------------------
    def _refresh_credentials(self):
        w = DashboardWorker(has_email_credentials)
        w.result_sig.connect(self._apply_cred_status)
        self._workers.append(w)
        w.start()

    def _apply_cred_status(self, ok: bool):
        if ok:
            self._cred_status.set_state("online"); self._cred_status.setText("CONNECTED")
            self._cred_lbl.setText("Email credentials are configured for this user.")
            self._cred_cta.setVisible(False)
        else:
            self._cred_status.set_state("offline"); self._cred_status.setText("NOT CONNECTED")
            self._cred_lbl.setText("No email account connected. Set up credentials to read and send messages.")
            self._cred_cta.setVisible(True)

    def _setup_email(self):
        # Trigger the existing email UI popup through modules/assistant_email
        try:
            from modules.assistant_email.email_controller import get_credentials
            res = get_credentials()
            if res and res[0]:
                self._refresh_credentials()
                QTimer.singleShot(500, self._reload_folder)
        except Exception as e:
            QMessageBox.warning(self, "Setup failed", str(e))

    # ----------------------- folder switching / loading -------------------
    def _on_folder_change(self, idx: int):
        self._current_folder = ["inbox", "sent", "drafts"][idx]
        self._reload_folder()

    def _reload_folder(self):
        self._table.setRowCount(0)
        self._loading_l.setVisible(True)
        w = DashboardWorker(load_emails, self._current_folder, 50)
        w.result_sig.connect(self._apply_emails)
        w.error_sig.connect(self._on_folder_error)
        self._workers.append(w)
        w.start()

    def _apply_emails(self, result: Dict):
        self._loading_l.setVisible(False)
        self._empty_l.setVisible(False)
        self._table.setVisible(True)
        success = bool(result and result.get("success"))
        emails = list((result or {}).get("emails") or [])
        if not success:
            msg = (result or {}).get("message") or "Couldn't load email."
            # If not connected, show empty placeholder table
            if "No email" in msg:
                emails = []
            else:
                self._table.setRowCount(0)
                return
        if not emails:
            # Show empty state
            self._table.setVisible(False)
            self._empty_l.setVisible(True)
            self._table.setRowCount(0)
            return
        self._table.setRowCount(len(emails))
        for i, em in enumerate(emails):
            # email dicts may vary — try sensible keys
            unread = bool(em.get("unread") if "unread" in em else (i < 2))
            sender = str(em.get("sender") or em.get("from") or "Unknown Sender")
            subject = str(em.get("subject") or "No Subject")
            preview = str((em.get("body") or em.get("preview") or "…")[:80])
            date = str(em.get("date") or em.get("sent_at") or em.get("received_at") or "")[:16]
            items = [
                QTableWidgetItem("●" if unread else " "),
                QTableWidgetItem(sender),
                QTableWidgetItem(subject),
                QTableWidgetItem(preview),
                QTableWidgetItem(date),
            ]
            for j, it in enumerate(items):
                if j == 0:
                    it.setForeground(QColor(C.SEC_COMMUNICATIONS if unread else C.TEXT_DIM))
                if unread:
                    f = it.font(); f.setBold(True); it.setFont(f)
                self._table.setItem(i, j, it)
        # Cache raw list
        if self._current_folder == "inbox": self._inbox = emails
        if self._current_folder == "sent": self._sent = emails
        if self._current_folder == "drafts": self._drafts = emails

    def _on_folder_error(self, err: str):
        self._loading_l.setVisible(False)
        self._table.setRowCount(0)
        self._rdr_subject.setText("Error loading messages")
        self._rdr_body.setPlainText(err or "Unknown error.")

    # ------------------------ row selection / reader ----------------------
    def _on_select(self):
        sel = self._table.selectedItems()
        if not sel:
            self._selected_idx = None
            return
        row = sel[0].row()
        self._selected_idx = row
        folder_list = {"inbox": self._inbox, "sent": self._sent, "drafts": self._drafts}[self._current_folder]
        if folder_list and row < len(folder_list):
            em = folder_list[row]
            self._show_email(em)
        else:
            self._rdr_subject.setText(self._table.item(row, 2).text() if self._table.item(row, 2) else "")
            from_cell = self._table.item(row, 1).text() if self._table.item(row, 1) else ""
            self._rdr_meta.setText(f"From: {from_cell}")
            self._rdr_body.setPlainText(self._table.item(row, 3).text() if self._table.item(row, 3) else "")

    def _show_email(self, em: Dict):
        sender = str(em.get("sender") or em.get("from") or "")
        subject = str(em.get("subject") or "(No subject)")
        date = str(em.get("date") or em.get("sent_at") or em.get("received_at") or "")
        body = str(em.get("body") or em.get("html") or em.get("text") or "(empty)")
        self._rdr_subject.setText(subject)
        self._rdr_meta.setText(f"From: {sender} · {date[:19]}")
        self._rdr_body.setPlainText(body)
        self._current_email = em

    def _current(self) -> Dict:
        return getattr(self, "_current_email", {}) or {}

    # ------------------------ reader actions -------------------------------
    def _open_compose(self):
        dlg = ComposeDialog(self)
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result:
            r = dlg.result
            self._send(r["to"], r["subject"], r["body"])

    def _reply(self):
        em = self._current()
        dlg = ComposeDialog(self,
            to=em.get("sender") or em.get("from", ""),
            subject=f"Re: {em.get('subject','')}".lstrip("Re: Re: "),
            body="\n\n---\n> " + (em.get("body") or "").replace("\n", "\n> "))
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result:
            r = dlg.result; self._send(r["to"], r["subject"], r["body"])

    def _reply_all(self): self._reply()
    def _forward(self):
        em = self._current()
        dlg = ComposeDialog(self,
            subject=f"Fwd: {em.get('subject','')}",
            body="\n\n--- Forwarded ---\n" + (em.get("body") or ""))
        if dlg.exec() == dlg.DialogCode.Accepted and dlg.result:
            r = dlg.result; self._send(r["to"], r["subject"], r["body"])

    def _delete(self):
        if self._selected_idx is None:
            return
        if QMessageBox.question(self, "Delete?", "Delete this message?") == QMessageBox.StandardButton.Yes:
            self._table.removeRow(self._selected_idx)
            self._selected_idx = None

    def _send(self, to: str, subject: str, body: str):
        self._rdr_subject.setText("Sending…")
        self._rdr_body.setPlainText(f"To: {to}\nSubject: {subject}\n\n{body}")
        w = DashboardWorker(send_email_ui, to, subject, body)
        w.result_sig.connect(self._on_sent)
        w.error_sig.connect(lambda e: QMessageBox.critical(self, "Send failed", e))
        self._workers.append(w)
        w.start()

    def _on_sent(self, result):
        ok = bool(result and result.get("success"))
        if ok:
            self._rdr_subject.setText("✅ Message sent")
            self._rdr_body.setPlainText(result.get("message") or "Message sent successfully.")
            QTimer.singleShot(800, self._reload_folder)
        else:
            self._rdr_subject.setText("❌ Failed to send")
            self._rdr_body.setPlainText(result.get("message") or "Unknown send error.")

    # ------------------------ AI actions ------------------------------------
    def _ai_cmd(self, prompt: str):
        em = self._current()
        if not em:
            QMessageBox.information(self, "Select a message", "Select an email first.")
            return
        from ..service_adapters import send_command
        w = DashboardWorker(send_command, prompt)
        self._workers.append(w)
        w.start()
        self._rdr_subject.setText("⏳ AI working…")
        self._rdr_body.setPlainText(prompt + "\n\n(Processing — results appear in Assistant conversation.)")

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def _ai_summarize_email(self):
        em = self._current()
        self._ai_cmd(f"Summarize the following email in 3 bullet points:\n\n"
                      f"Subject: {em.get('subject','')}\n\n{em.get('body','')}")
    def _ai_draft_reply(self):
        em = self._current()
        self._ai_cmd(f"Draft a polite reply to the following email:\n\n"
                      f"From: {em.get('sender') or em.get('from','')}\n"
                      f"Subject: {em.get('subject','')}\n\n{em.get('body','')}")
    def _ai_extract_actions(self):
        em = self._current()
        self._ai_cmd(f"Extract all action items, deadlines, and decisions from the following email "
                      f"(as a list):\n\nSubject: {em.get('subject','')}\n\n{em.get('body','')}")

    def on_visible(self):
        self._refresh_credentials()
        self._reload_folder()
