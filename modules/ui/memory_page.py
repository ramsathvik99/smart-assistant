"""
Smart Assistant — Memory & Notes Inspector Page
Interactive interface for viewing and managing long-term PostgreSQL user memory
and stored notes, matching Brahma MemoryInspector capabilities.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QScrollArea, QFrame, QTabWidget,
    QMessageBox, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSlot
from PyQt6.QtGui import QColor, QFont

from modules.ui.design_system import C, F, Radius, Spacing


class MemoryLoaderThread(QThread):
    """Background worker to fetch memory and notes without freezing UI."""
    data_loaded = pyqtSignal(dict, list)  # memory_dict, notes_list

    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id

    def run(self):
        try:
            from legacy.memory_manager import load_user_memory, get_notes_with_ids_db
            mem = load_user_memory(self.user_id) if self.user_id else {}
            notes = get_notes_with_ids_db(self.user_id) if self.user_id else []
            self.data_loaded.emit(mem, notes)
        except Exception as e:
            print(f"[MEMORY PAGE] Loader error: {e}")
            self.data_loaded.emit({}, [])


class MemoryCard(QFrame):
    """Card displaying a single key-value memory item with delete option."""
    delete_clicked = pyqtSignal(str)

    def __init__(self, key: str, value: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("MemoryCard")
        self.setStyleSheet(f"""
            QFrame#MemoryCard {{
                background: rgba(8, 14, 22, 0.6);
                border: 1px solid rgba(0, 212, 255, 0.15);
                border-radius: {Radius.MD}px;
                padding: 4px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(Spacing.MD)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)

        key_lbl = QLabel(key.upper())
        key_lbl.setFont(QFont(F.PRIMARY, 9, QFont.Weight.Bold))
        key_lbl.setStyleSheet(f"color: {C.ACCENT_CYAN}; background: transparent;")
        info_layout.addWidget(key_lbl)

        val_lbl = QLabel(str(value))
        val_lbl.setFont(QFont(F.PRIMARY, 11))
        val_lbl.setWordWrap(True)
        val_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        info_layout.addWidget(val_lbl)

        layout.addLayout(info_layout, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(26, 26)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        del_btn.setToolTip("Delete this memory entry")
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 59, 48, 0.12);
                color: #ff3b30;
                border: 1px solid rgba(255, 59, 48, 0.25);
                border-radius: 13px;
            }}
            QPushButton:hover {{
                background: rgba(255, 59, 48, 0.35);
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.key))
        layout.addWidget(del_btn)


class NoteCard(QFrame):
    """Card displaying a user note with delete option."""
    delete_clicked = pyqtSignal(int)

    def __init__(self, note_id: int, note_text: str, parent=None):
        super().__init__(parent)
        self.note_id = note_id
        self.setObjectName("NoteCard")
        self.setStyleSheet(f"""
            QFrame#NoteCard {{
                background: rgba(8, 14, 22, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: {Radius.MD}px;
                padding: 4px;
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(Spacing.MD)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)

        id_lbl = QLabel(f"NOTE #{note_id}")
        id_lbl.setFont(QFont(F.PRIMARY, 8, QFont.Weight.Bold))
        id_lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent;")
        info_layout.addWidget(id_lbl)

        text_lbl = QLabel(note_text)
        text_lbl.setFont(QFont(F.PRIMARY, 11))
        text_lbl.setWordWrap(True)
        text_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        info_layout.addWidget(text_lbl)

        layout.addLayout(info_layout, 1)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(26, 26)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFont(QFont(F.PRIMARY, 10, QFont.Weight.Bold))
        del_btn.setToolTip("Delete this note")
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(255, 59, 48, 0.12);
                color: #ff3b30;
                border: 1px solid rgba(255, 59, 48, 0.25);
                border-radius: 13px;
            }}
            QPushButton:hover {{
                background: rgba(255, 59, 48, 0.35);
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.note_id))
        layout.addWidget(del_btn)


class MemoryPage(QWidget):
    """Complete Memory & Notes management surface."""

    def __init__(self, user_id: int = None, parent=None):
        super().__init__(parent)
        self._user_id = user_id
        self._memory_cache = {}
        self._notes_cache = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LG, Spacing.LG, Spacing.LG, Spacing.LG)
        layout.setSpacing(Spacing.MD)

        # Header bar
        header = QHBoxLayout()
        header.setSpacing(Spacing.MD)

        title = QLabel("Memory & Knowledge Hub")
        title.setFont(QFont(F.PRIMARY, 15, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        header.addWidget(title)

        header.addStretch()

        self.refresh_btn = QPushButton("↻ Refresh")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_btn.setFont(QFont(F.PRIMARY, 10))
        self.refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 212, 255, 0.12);
                color: {C.ACCENT_CYAN};
                border: 1px solid rgba(0, 212, 255, 0.25);
                border-radius: 6px;
                padding: 5px 14px;
            }}
            QPushButton:hover {{
                background: rgba(0, 212, 255, 0.25);
            }}
        """)
        self.refresh_btn.clicked.connect(self.reload_data)
        header.addWidget(self.refresh_btn)

        layout.addLayout(header)

        # Search bar
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search stored memory or notes…")
        self.search_input.setFont(QFont(F.PRIMARY, 11))
        self.search_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(8, 14, 22, 0.8);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: {Radius.SM}px;
                padding: 8px 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {C.ACCENT_CYAN};
            }}
        """)
        self.search_input.textChanged.connect(self._filter_views)
        layout.addWidget(self.search_input)

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: {Radius.MD}px;
                background: rgba(4, 7, 12, 0.4);
            }}
            QTabBar::tab {{
                background: transparent;
                color: {C.TEXT_MUTED};
                font-family: '{F.PRIMARY}';
                font-size: 11px;
                font-weight: bold;
                padding: 8px 18px;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {C.ACCENT_CYAN};
                border-bottom: 2px solid {C.ACCENT_CYAN};
            }}
        """)

        # Tab 1: Long-term Memory
        self.mem_tab = QWidget()
        mem_layout = QVBoxLayout(self.mem_tab)
        mem_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        mem_layout.setSpacing(Spacing.MD)

        # Add memory inline
        add_mem_box = QHBoxLayout()
        self.mem_key_input = QLineEdit()
        self.mem_key_input.setPlaceholderText("Key (e.g. favorite_color)")
        self.mem_key_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 10px;
            }}
        """)
        add_mem_box.addWidget(self.mem_key_input, 1)

        self.mem_val_input = QLineEdit()
        self.mem_val_input.setPlaceholderText("Value (e.g. cyan)")
        self.mem_val_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 10px;
            }}
        """)
        add_mem_box.addWidget(self.mem_val_input, 2)

        add_mem_btn = QPushButton("+ Remember")
        add_mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_mem_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 212, 255, 0.15);
                color: {C.ACCENT_CYAN};
                border: 1px solid rgba(0, 212, 255, 0.3);
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(0, 212, 255, 0.3);
            }}
        """)
        add_mem_btn.clicked.connect(self._save_memory)
        add_mem_box.addWidget(add_mem_btn)

        mem_layout.addLayout(add_mem_box)

        # Scroll for memory cards
        mem_scroll = QScrollArea()
        mem_scroll.setWidgetResizable(True)
        mem_scroll.setFrameShape(QFrame.Shape.NoFrame)
        mem_scroll.setStyleSheet("background: transparent;")
        self.mem_container = QWidget()
        self.mem_container.setStyleSheet("background: transparent;")
        self.mem_cards_layout = QVBoxLayout(self.mem_container)
        self.mem_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.mem_cards_layout.setSpacing(Spacing.SM)
        self.mem_cards_layout.addStretch()
        mem_scroll.setWidget(self.mem_container)
        mem_layout.addWidget(mem_scroll, 1)

        self.tabs.addTab(self.mem_tab, "User Memory (PostgreSQL)")

        # Tab 2: Notes & Clippings
        self.notes_tab = QWidget()
        notes_layout = QVBoxLayout(self.notes_tab)
        notes_layout.setContentsMargins(Spacing.MD, Spacing.MD, Spacing.MD, Spacing.MD)
        notes_layout.setSpacing(Spacing.MD)

        # Add note inline
        add_note_box = QHBoxLayout()
        self.note_text_input = QLineEdit()
        self.note_text_input.setPlaceholderText("Write a note to remember…")
        self.note_text_input.setStyleSheet(f"""
            QLineEdit {{
                background: rgba(255, 255, 255, 0.05);
                color: {C.TEXT};
                border: 1px solid rgba(255, 255, 255, 0.1);
                border-radius: 6px;
                padding: 6px 10px;
            }}
        """)
        self.note_text_input.returnPressed.connect(self._save_note)
        add_note_box.addWidget(self.note_text_input, 1)

        add_note_btn = QPushButton("+ Save Note")
        add_note_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_note_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(0, 212, 255, 0.15);
                color: {C.ACCENT_CYAN};
                border: 1px solid rgba(0, 212, 255, 0.3);
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: rgba(0, 212, 255, 0.3);
            }}
        """)
        add_note_btn.clicked.connect(self._save_note)
        add_note_box.addWidget(add_note_btn)

        notes_layout.addLayout(add_note_box)

        # Scroll for notes cards
        notes_scroll = QScrollArea()
        notes_scroll.setWidgetResizable(True)
        notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        notes_scroll.setStyleSheet("background: transparent;")
        self.notes_container = QWidget()
        self.notes_container.setStyleSheet("background: transparent;")
        self.notes_cards_layout = QVBoxLayout(self.notes_container)
        self.notes_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.notes_cards_layout.setSpacing(Spacing.SM)
        self.notes_cards_layout.addStretch()
        notes_scroll.setWidget(self.notes_container)
        notes_layout.addWidget(notes_scroll, 1)

        self.tabs.addTab(self.notes_tab, "Notes & Clippings")

        layout.addWidget(self.tabs, 1)

        self._cards = []
        self._note_cards = []

    def set_user_id(self, user_id: int):
        self._user_id = user_id
        self.reload_data()

    def reload_data(self):
        if not self._user_id:
            return
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("Loading…")
        self._loader = MemoryLoaderThread(self._user_id)
        self._loader.data_loaded.connect(self._on_data_loaded)
        self._loader.start()

    @pyqtSlot(dict, list)
    def _on_data_loaded(self, memory_dict: dict, notes_list: list):
        self._memory_cache = memory_dict
        self._notes_cache = notes_list
        self._render_memory_cards()
        self._render_note_cards()
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("↻ Refresh")

    def _render_memory_cards(self, filter_text: str = ""):
        # Clear existing
        for c in self._cards:
            self.mem_cards_layout.removeWidget(c)
            c.deleteLater()
        self._cards.clear()

        flt = filter_text.lower()
        items = [(k, v) for k, v in self._memory_cache.items() if flt in k.lower() or flt in str(v).lower()]

        if not items:
            lbl = QLabel("No memory entries found." if filter_text else "No long-term memories saved yet.")
            lbl.setFont(QFont(F.PRIMARY, 11))
            lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent; padding: 12px;")
            self.mem_cards_layout.insertWidget(0, lbl)
            self._cards.append(lbl)
            return

        for i, (k, v) in enumerate(items):
            card = MemoryCard(k, v)
            card.delete_clicked.connect(self._delete_memory)
            self.mem_cards_layout.insertWidget(i, card)
            self._cards.append(card)

    def _render_note_cards(self, filter_text: str = ""):
        for c in self._note_cards:
            self.notes_cards_layout.removeWidget(c)
            c.deleteLater()
        self._note_cards.clear()

        flt = filter_text.lower()
        # notes_list is rows from DB: (id, note)
        items = [n for n in self._notes_cache if flt in str(n[1]).lower()]

        if not items:
            lbl = QLabel("No notes found." if filter_text else "No notes saved yet.")
            lbl.setFont(QFont(F.PRIMARY, 11))
            lbl.setStyleSheet(f"color: {C.TEXT_MUTED}; background: transparent; padding: 12px;")
            self.notes_cards_layout.insertWidget(0, lbl)
            self._note_cards.append(lbl)
            return

        for i, row in enumerate(items):
            nid = row[0]
            text = row[1]
            card = NoteCard(nid, text)
            card.delete_clicked.connect(self._delete_note)
            self.notes_cards_layout.insertWidget(i, card)
            self._note_cards.append(card)

    def _filter_views(self, text: str):
        self._render_memory_cards(text)
        self._render_note_cards(text)

    def _save_memory(self):
        k = self.mem_key_input.text().strip()
        v = self.mem_val_input.text().strip()
        if not k or not v or not self._user_id:
            return
        try:
            from legacy.memory_manager import update_user_memory
            update_user_memory(self._user_id, k, v)
            self.mem_key_input.clear()
            self.mem_val_input.clear()
            self.reload_data()
        except Exception as e:
            print(f"[MEMORY PAGE] Save memory error: {e}")

    def _delete_memory(self, key: str):
        if not self._user_id:
            return
        try:
            from legacy.memory_manager import delete_memory_key
            delete_memory_key(self._user_id, key)
            self.reload_data()
        except Exception as e:
            print(f"[MEMORY PAGE] Delete memory error: {e}")

    def _save_note(self):
        txt = self.note_text_input.text().strip()
        if not txt or not self._user_id:
            return
        try:
            from legacy.memory_manager import add_note_db
            add_note_db(self._user_id, txt)
            self.note_text_input.clear()
            self.reload_data()
        except Exception as e:
            print(f"[MEMORY PAGE] Save note error: {e}")

    def _delete_note(self, note_id: int):
        if not self._user_id:
            return
        try:
            from legacy.memory_manager import delete_note_db
            delete_note_db(self._user_id, note_id)
            self.reload_data()
        except Exception as e:
            print(f"[MEMORY PAGE] Delete note error: {e}")
