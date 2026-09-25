"""
Smart Assistant — Notification Toast
Non-intrusive slide-in notification component.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QApplication
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRect, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QLinearGradient, QBrush, QPen, QFont

from modules.ui.design_system import C, F, Radius


ICONS = {
    "info":    ("◈", C.ACC),
    "success": ("✓", C.GREEN),
    "warning": ("⚠", C.YELLOW),
    "error":   ("✕", C.RED),
    "reminder": ("◷", C.ORANGE),
}


class NotificationToast(QWidget):
    """Slide-in toast notification. Auto-dismisses after `duration` ms."""

    dismissed = pyqtSignal()

    def __init__(self, message: str, kind: str = "info",
                 duration: int = 4000, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        icon_char, icon_color = ICONS.get(kind, ICONS["info"])
        self._icon_color = QColor(icon_color)
        self._kind = kind

        self.setFixedHeight(52)
        self.setMinimumWidth(280)
        self.setMaximumWidth(420)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(10)

        icon_lbl = QLabel(icon_char)
        icon_lbl.setFont(QFont(F.PRIMARY, 14, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {icon_color}; background: transparent; border: none;")
        icon_lbl.setFixedWidth(20)
        lay.addWidget(icon_lbl)

        msg_lbl = QLabel(message)
        msg_lbl.setFont(QFont(F.PRIMARY, 12))
        msg_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
        msg_lbl.setWordWrap(False)
        lay.addWidget(msg_lbl, 1)

        # Position
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        w = max(self.minimumWidth(), min(self.sizeHint().width() + 28, self.maximumWidth()))
        self.setFixedWidth(w)
        self._target_x = screen.width() - w - 20
        self._target_y = screen.height() - 200
        self.move(self._target_x + w + 30, self._target_y)  # start off-screen right
        self.show()

        # Slide in
        self._slide_in = QPropertyAnimation(self, b"geometry")
        self._slide_in.setDuration(300)
        self._slide_in.setStartValue(QRect(self._target_x + w + 30, self._target_y, w, 52))
        self._slide_in.setEndValue(QRect(self._target_x, self._target_y, w, 52))
        self._slide_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_in.start()

        # Auto-dismiss
        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self._slide_out)
        self._dismiss_timer.start(duration)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(10, 16, 22, 235))
        grad.setColorAt(1.0, QColor(14, 20, 28, 235))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad))

        from PyQt6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, Radius.MD, Radius.MD)
        p.drawPath(path)

        # Border
        pen = QPen(self._icon_color)
        pen.setWidth(1)
        pen.setColor(QColor(self._icon_color.red(), self._icon_color.green(),
                            self._icon_color.blue(), 100))
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # Left accent bar
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._icon_color.red(), self._icon_color.green(),
                                 self._icon_color.blue(), 200)))
        bar_path = QPainterPath()
        bar_path.addRoundedRect(0, 0, 3, h, 2, 2)
        p.drawPath(bar_path)

        p.end()

    def _slide_out(self):
        w = self.width()
        self._slide_out_anim = QPropertyAnimation(self, b"geometry")
        self._slide_out_anim.setDuration(280)
        self._slide_out_anim.setStartValue(self.geometry())
        self._slide_out_anim.setEndValue(
            QRect(self._target_x + w + 30, self._target_y, w, 52))
        self._slide_out_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._slide_out_anim.finished.connect(self.close)
        self._slide_out_anim.finished.connect(self.dismissed.emit)
        self._slide_out_anim.start()

    def mousePressEvent(self, _e):
        self._dismiss_timer.stop()
        self._slide_out()


class ToastManager:
    """Manages a stack of active toasts, offsetting them vertically."""

    def __init__(self):
        self._toasts: list[NotificationToast] = []

    def show(self, message: str, kind: str = "info", duration: int = 4000):
        offset = len(self._toasts) * 62
        toast = NotificationToast(message, kind, duration)
        # Adjust vertical position
        screen = QApplication.primaryScreen().availableGeometry()
        w = toast.width()
        toast.move(screen.width() - w - 20, screen.height() - 200 - offset)
        self._toasts.append(toast)
        toast.dismissed.connect(lambda: self._remove(toast))
        return toast

    def _remove(self, toast: NotificationToast):
        if toast in self._toasts:
            self._toasts.remove(toast)
        # Re-stack remaining
        screen = QApplication.primaryScreen().availableGeometry()
        for i, t in enumerate(self._toasts):
            w = t.width()
            t.move(screen.width() - w - 20, screen.height() - 200 - i * 62)
