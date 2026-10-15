from PyQt6 import QtWidgets, QtCore

class CornerToast(QtWidgets.QWidget):
    """
    Небольшая плашка (тост) в правом нижнем углу экрана, не перехватывает клики.
    Показывает произвольный текст, например обратный отсчёт до окончания времени.
    """
    def __init__(self, parent=None):
        super().__init__(
            parent,
            flags=QtCore.Qt.WindowType.Tool
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        # Не перехватывать клики мыши
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowModality(QtCore.Qt.WindowModality.NonModal)

        self._padding = 12
        self._radius = 10

        self.label = QtWidgets.QLabel(self)
        self.label.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft
            | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        font = self.label.font()
        font.setPointSize(11)
        font.setBold(True)
        self.label.setFont(font)
        self.label.setStyleSheet("color: white;")

        self.setStyleSheet(
            "background-color: rgba(0, 0, 0, 180);"
            "border-radius: 10px;"
        )

        self._layout = QtWidgets.QHBoxLayout(self)
        self._layout.setContentsMargins(self._padding, self._padding, self._padding, self._padding)
        self._layout.addWidget(self.label)
        self.hide()

    def set_text(self, text: str):
        self.label.setText(text)
        self.label.adjustSize()
        self.adjustSize()
        self._place_bottom_right()

    def _place_bottom_right(self):
        # Размещаем у правого нижнего края основного экрана (без перекрытия панелей — best effort)
        screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            return
        geom: QtCore.QRect = screen.availableGeometry()
        self.adjustSize()
        x = geom.right() - self.width() - 20
        y = geom.bottom() - self.height() - 20
        self.move(x, y)

    def show_text(self, text: str):
        self.set_text(text)
        if not self.isVisible():
            self.show()
            self.raise_()

    def hide_toast(self):
        if self.isVisible():
            self.hide()
