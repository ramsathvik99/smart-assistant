"""
Workspace (Files / Documents) Page
====================================
  • Recent files table (Desktop, Documents, Downloads, workspace)
  • File type icons
  • Document generation card (PDF/DOCX/XLSX/PPTX)
  • Generated files list
  • Open / reveal in folder / delete
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, List, Optional

from PyQt6.QtCore import Qt, QSize, QTimer, QUrl
from PyQt6.QtGui import QDesktopServices, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QMessageBox, QComboBox, QInputDialog,
    QFileDialog, QSplitter, QGridLayout, QSpinBox,
)

from ..ds import (
    C, F, Spacing, Radius, ICONS, icon, icon_pixmap,
    HLine, VLine, Card, StatusChip, SectionHeader,
    LoadingState, EmptyState, ErrorState, get_contrast_color,
)
from ..service_adapters import (
    list_recent_files, generate_document,
)
from ..workers import DashboardWorker


EXT_ICON = {
    "pdf": ICONS.FILE_PDF, "docx": ICONS.FILE_WORD, "doc": ICONS.FILE_WORD,
    "xlsx": ICONS.FILE_EXCEL, "xls": ICONS.FILE_EXCEL,
    "pptx": ICONS.FILE_POWERPOINT, "ppt": ICONS.FILE_POWERPOINT,
    "txt": ICONS.FILE, "md": ICONS.FILE, "py": ICONS.FILE,
    "js": ICONS.FILE, "json": ICONS.FILE, "png": ICONS.CAMERA, "jpg": ICONS.CAMERA,
    "jpeg": ICONS.CAMERA, "gif": ICONS.CAMERA,
}


def _fmt_size(n: int) -> str:
    n = int(n or 0)
    for unit, step in [("KB", 1024), ("MB", 1024), ("GB", 1024)]:
        if n < step:
            return f"{n} B" if unit == "KB" else f"{n:.1f} {unit}"
        n /= step
    return f"{n:.1f} TB"


class WorkspacePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._files: List[Dict] = []
        self._generated: List[str] = []
        self._workers = []  # Track worker threads for cleanup
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(Spacing.LG2, Spacing.LG2, Spacing.LG2, Spacing.LG2)
        root.setSpacing(Spacing.LG)

        # Header
        head = QHBoxLayout(); head.setSpacing(Spacing.MD)
        sh = SectionHeader("Workspace", "Recent files and on-demand document generation", accent=C.SEC_WORKSPACE)
        head.addWidget(sh, 1); head.addStretch(1)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search files…")
        self._search.addAction(icon(ICONS.SEARCH, C.TEXT_DIM, 14),
                               QLineEdit.ActionPosition.LeadingPosition)
        self._search.setCursor(Qt.CursorShape.IBeamCursor)
        self._search.setMinimumWidth(180)
        self._search.setMaximumWidth(320)
        self._search.returnPressed.connect(self._reload_files)
        head.addWidget(self._search)
        refresh = QPushButton(); refresh.setObjectName("IconBtn")
        refresh.setIcon(icon(ICONS.REFRESH, C.TEXT, 14)); refresh.setFixedSize(34, 34)
        refresh.setToolTip("Refresh files")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self._reload_files)
        head.addWidget(refresh)
        upload = QPushButton("Open File"); upload.setObjectName("GhostBtn")
        upload.setIcon(icon(ICONS.UPLOAD, C.TEXT, 14))
        upload.setCursor(Qt.CursorShape.PointingHandCursor)
        upload.clicked.connect(self._open_any)
        head.addWidget(upload)
        hw = QWidget(); hw.setLayout(head)
        root.addWidget(hw)

        # Document Studio: Generate Documents (form) + Generated Documents (list)
        studio_row = QHBoxLayout()
        studio_row.setSpacing(Spacing.LG)

        # Generate Documents
        gen_card = Card(title="Generate Documents", accent=C.SEC_WORKSPACE)
        gen_grid = QGridLayout(); gen_grid.setHorizontalSpacing(Spacing.MD); gen_grid.setVerticalSpacing(Spacing.SM)
        gen_grid.setColumnStretch(0, 0)
        gen_grid.setColumnStretch(1, 1)

        t_lbl = QLabel("Document type"); t_lbl.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px; font-weight: 500;")
        t_lbl.setMinimumWidth(95)
        gen_grid.addWidget(t_lbl, 0, 0)
        self._doc_type = QComboBox()
        self._doc_type.setFixedHeight(36)
        self._doc_type.setCursor(Qt.CursorShape.PointingHandCursor)
        self._doc_type.addItem("PDF Report",        "pdf")
        self._doc_type.addItem("Word (DOCX)",        "docx")
        self._doc_type.addItem("Excel (XLSX)",       "xlsx")
        self._doc_type.addItem("PowerPoint (PPTX)",  "pptx")
        self._doc_type.setMaximumWidth(280)
        gen_grid.addWidget(self._doc_type, 0, 1, Qt.AlignmentFlag.AlignLeft)

        t2_lbl = QLabel("Topic / title"); t2_lbl.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px; font-weight: 500;")
        t2_lbl.setMinimumWidth(95)
        gen_grid.addWidget(t2_lbl, 1, 0)
        self._doc_topic = QLineEdit()
        self._doc_topic.setFixedHeight(36)
        self._doc_topic.setCursor(Qt.CursorShape.IBeamCursor)
        self._doc_topic.setPlaceholderText("E.g. Q3 Project Status Report")
        gen_grid.addWidget(self._doc_topic, 1, 1)

        t3_lbl = QLabel("Sections (optional)"); t3_lbl.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px; font-weight: 500;")
        t3_lbl.setMinimumWidth(95)
        gen_grid.addWidget(t3_lbl, 2, 0)
        self._doc_sections = QLineEdit()
        self._doc_sections.setFixedHeight(36)
        self._doc_sections.setCursor(Qt.CursorShape.IBeamCursor)
        self._doc_sections.setPlaceholderText("Intro, Scope, Timeline, Risks, Budget")
        gen_grid.addWidget(self._doc_sections, 2, 1)

        btn_row = QHBoxLayout(); btn_row.setSpacing(Spacing.SM)
        btn_row.addStretch(1)
        self._gen_status = QLabel("")
        self._gen_status.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 11px;")
        btn_row.addWidget(self._gen_status)
        self._gen_btn = QPushButton("Generate Document")
        self._gen_btn.setObjectName("PrimaryBtn")
        self._gen_btn.setIcon(icon(ICONS.WAND_MAGIC, get_contrast_color(C.SEC_WORKSPACE), 14))
        self._gen_btn.setFixedHeight(36)
        self._gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gen_btn.clicked.connect(self._generate)
        btn_row.addWidget(self._gen_btn)
        gen_grid.addLayout(btn_row, 3, 1)

        gen_card.body.addLayout(gen_grid)
        gen_card.setFixedHeight(260)
        studio_row.addWidget(gen_card, 3)

        # Generated files card
        gen_list_card = Card(title="Generated Documents", accent=C.SEC_WORKSPACE)
        gen_scroll = QScrollArea()
        gen_scroll.setWidgetResizable(True)
        gen_scroll.setFrameShape(QFrame.Shape.NoFrame)
        gen_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._gen_list = QVBoxLayout(); self._gen_list.setSpacing(Spacing.SM)
        self._gen_list.setContentsMargins(0, 0, 0, 0)
        self._gen_empty = EmptyState(ICONS.FILE_PDF, "No generated documents yet",
                                     "Use the form on the left to generate PDFs, DOCX, XLSX or PPTX files.",
                                     accent=C.SEC_WORKSPACE, compact=True)
        self._gen_list.addWidget(self._gen_empty)
        gw = QWidget(); gw.setLayout(self._gen_list)
        gen_scroll.setWidget(gw)
        gen_list_card.body.addWidget(gen_scroll, 1)
        gen_list_card.setFixedHeight(260)
        studio_row.addWidget(gen_list_card, 2)

        root.addLayout(studio_row)

        # Recent files table
        files_card = Card(title="Recent Files", accent=C.SEC_WORKSPACE)
        files_card.setMinimumHeight(280)
        self._files_loading = LoadingState("Indexing recent files…")
        files_card.body.addWidget(self._files_loading)
        self._files_empty = EmptyState(ICONS.WORKSPACE, "No recent files",
                                        "No files found in your workspace.",
                                        accent=C.SEC_WORKSPACE)
        self._files_empty.setVisible(False)
        files_card.body.addWidget(self._files_empty)
        self._files_table = QTableWidget(0, 5)
        self._files_table.setHorizontalHeaderLabels(["", "Name", "Location", "Size", "Modified"])
        self._files_table.verticalHeader().setVisible(False)
        self._files_table.verticalHeader().setDefaultSectionSize(40)
        self._files_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._files_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._files_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._files_table.customContextMenuRequested.connect(self._files_menu)
        self._files_table.setFrameShape(QFrame.Shape.NoFrame)
        self._files_table.setShowGrid(False)
        self._files_table.doubleClicked.connect(lambda _: self._open_selected())
        hh = self._files_table.horizontalHeader()
        hh.setStretchLastSection(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        files_card.body.addWidget(self._files_table, 1)
        root.addWidget(files_card, 1)

        QTimer.singleShot(0, self._reload_files)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)

    # ----------------------- recent files ------------------------------
    def _reload_files(self):
        self._files_loading.setVisible(True)
        w = DashboardWorker(list_recent_files, None, 80)
        w.result_sig.connect(self._apply_files)
        self._workers.append(w)
        w.start()

    def _apply_files(self, files: List[Dict]):
        self._files_loading.setVisible(False)
        # Filter by search
        q = (self._search.text() or "").lower().strip()
        all_files = list(files or [])
        if q:
            all_files = [f for f in all_files if q in (f.get("name") or "").lower()
                         or q in (f.get("extension") or "").lower()]
        self._files = all_files
        
        if not all_files:
            self._files_table.setVisible(False)
            self._files_empty.setVisible(True)
            self._files_table.setRowCount(0)
            return
        else:
            self._files_table.setVisible(True)
            self._files_empty.setVisible(False)
            self._files_table.setRowCount(len(all_files))
        for i, f in enumerate(all_files):
            name = f.get("name") or ""
            ext = (f.get("extension") or "").lower()
            ic_name = EXT_ICON.get(ext, ICONS.FILE)
            folder = f.get("folder") or ""
            size = _fmt_size(f.get("size") or 0)
            mt = f.get("modified") or 0
            mt_str = ""
            try:
                mt_str = datetime.fromtimestamp(mt).strftime("%Y-%m-%d %H:%M")
            except Exception:
                mt_str = ""
            items = [
                QTableWidgetItem(icon(ic_name, self._ext_color(ext), 14), ""),
                QTableWidgetItem(name),
                QTableWidgetItem(folder),
                QTableWidgetItem(size),
                QTableWidgetItem(mt_str),
            ]
            for j, it in enumerate(items):
                self._files_table.setItem(i, j, it)

    def _ext_color(self, ext: str) -> str:
        return {
            "pdf": C.STATUS_ERROR,
            "docx": C.SEC_COMMUNICATIONS, "doc": C.SEC_COMMUNICATIONS,
            "xlsx": C.STATUS_SUCCESS, "xls": C.STATUS_SUCCESS,
            "pptx": C.STATUS_WARNING, "ppt": C.STATUS_WARNING,
            "png": C.SEC_SCHEDULE, "jpg": C.SEC_SCHEDULE, "jpeg": C.SEC_SCHEDULE, "gif": C.SEC_SCHEDULE,
        }.get((ext or "").lower(), C.TEXT_MED)

    def _selected_path(self) -> Optional[str]:
        rows = list({it.row() for it in self._files_table.selectedItems()})
        if not rows:
            return None
        idx = rows[0]
        if idx < len(self._files):
            return self._files[idx].get("path")
        return None

    def _open_selected(self):
        p = self._selected_path()
        if p: self._open_path(p)

    def _open_any(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open file")
        if p: self._open_path(p)

    def _open_path(self, path: str):
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "File not found", path)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _reveal_folder(self):
        p = self._selected_path()
        if not p: return
        folder = os.path.dirname(p)
        if folder and os.path.isdir(folder):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _files_menu(self, pos):
        p = self._selected_path()
        if not p: return
        menu = QMenu(self)
        a1 = menu.addAction(icon(ICONS.FILE, C.TEXT, 14), "Open")
        a1.triggered.connect(lambda: self._open_path(p))
        a2 = menu.addAction(icon(ICONS.FOLDER_OPEN, C.TEXT, 14), "Reveal in folder")
        a2.triggered.connect(self._reveal_folder)
        menu.exec(self._files_table.viewport().mapToGlobal(pos))

    # ----------------------- doc gen ------------------------------
    def _generate(self):
        kind = self._doc_type.currentData() or "pdf"
        topic = self._doc_topic.text().strip()
        if not topic:
            QMessageBox.information(self, "Topic required", "Please enter a topic or document title.")
            return
        sections = [s.strip() for s in self._doc_sections.text().split(",") if s.strip()] or None
        self._gen_btn.setEnabled(False)
        self._gen_status.setText("Generating… (this may take a few seconds)")
        extra = {"sections": sections} if sections else {}
        w = DashboardWorker(generate_document, kind, topic, extra)
        w.result_sig.connect(self._on_generated)
        w.error_sig.connect(self._on_generate_error)
        self._workers.append(w)
        w.start()

    def _cleanup_workers(self):
        """Clean up all worker threads when the page is destroyed."""
        for worker in self._workers:
            if worker and worker.isRunning():
                worker.quit()
                worker.wait()
        self._workers.clear()

    def _on_generated(self, result: Dict):
        self._gen_btn.setEnabled(True)
        ok = bool(result and result.get("success"))
        msg = (result or {}).get("message") or ""
        self._gen_status.setText(msg if ok else "Failed")
        if ok:
            path = result.get("path")
            if path:
                self._generated.insert(0, path)
                self._rebuild_gen_list()
                dlg = QMessageBox(self)
                dlg.setIcon(QMessageBox.Icon.Information)
                dlg.setWindowTitle("Document ready")
                dlg.setText(f"Your document has been generated:\n{path}")
                opn = dlg.addButton("Open", QMessageBox.ButtonRole.AcceptRole)
                fol = dlg.addButton("Show in folder", QMessageBox.ButtonRole.ActionRole)
                dlg.addButton(QMessageBox.StandardButton.Close)
                dlg.exec()
                rb = dlg.clickedButton()
                if rb is opn: self._open_path(path)
                elif rb is fol:
                    folder = os.path.dirname(path)
                    if folder and os.path.isdir(folder):
                        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def _on_generate_error(self, err: str):
        self._gen_btn.setEnabled(True)
        self._gen_status.setText(f"Error: {err[:60]}")
        QMessageBox.critical(self, "Generation failed", err)

    def _rebuild_gen_list(self):
        try:
            from ..ds import clear_layout
            clear_layout(self._gen_list)
            if not self._generated:
                empty = EmptyState(ICONS.FILE_PDF, "No generated documents yet",
                                   "Use the form on the left to generate PDFs, DOCX, XLSX or PPTX files.",
                                   accent=C.SEC_WORKSPACE, compact=True)
                self._gen_list.addWidget(empty)
                return
            for p in self._generated[:15]:
                w = QFrame(); w.setProperty("class", "CardInner")
                l = QHBoxLayout(w); l.setContentsMargins(Spacing.MD, 8, Spacing.MD, 8)
                l.setSpacing(Spacing.MD)
                ext = os.path.splitext(p)[1].lower().lstrip(".")
                ic = QLabel(); ic.setPixmap(icon_pixmap(EXT_ICON.get(ext, ICONS.FILE),
                                                       self._ext_color(ext), 16))
                l.addWidget(ic)
                col = QVBoxLayout(); col.setSpacing(0)
                nm = QLabel(os.path.basename(p)); nm.setStyleSheet("font-weight: 500;")
                loc = QLabel(os.path.dirname(p)); loc.setStyleSheet(f"color: {C.TEXT_DIM}; font-size: 11px;")
                col.addWidget(nm); col.addWidget(loc)
                l.addLayout(col, 1)
                opn = QPushButton(); opn.setObjectName("IconBtn")
                opn.setIcon(icon(ICONS.EYE, C.TEXT_MED, 13))
                opn.setFixedSize(30, 30); opn.setToolTip("Open")
                opn.clicked.connect(lambda _=False, x=p: self._open_path(x))
                l.addWidget(opn)
                self._gen_list.addWidget(w)
            self._gen_list.addStretch(1)
        except Exception as e:
            print(f"[WORKSPACE_PAGE] Error rebuilding gen list: {e}")

    def on_visible(self):
        self._reload_files()
