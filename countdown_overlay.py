from PyQt6 import QtWidgets, QtCore, QtGui
try:
    import win32gui, win32con
except Exception:
    win32gui = None
    win32con = None

class CountdownOverlay(QtWidgets.QWidget):
    """
    Полупрозрачный оверлей с крупным обратным отсчетом.
    Не перехватывает клики (сквозной), всегда поверх всех окон.
    """
    closed = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # Без рамки, поверх всех окон, прозрачный фон, не фокусируемый
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        # Прозрачен для ввода (клики проходят сквозь)
        if hasattr(QtCore.Qt.WindowType, 'WindowTransparentForInput'):
            self.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )
            self.setWindowFlag(
                QtCore.Qt.WindowType.WindowTransparentForInput, True
            )
        else:
            self.setAttribute(
                QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
            )

        self._seconds_left = 0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)

        # Контент: большой текст с тенью
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        self.label = QtWidgets.QLabel("")
        font = QtGui.QFont(
            "Montserrat", 72, QtGui.QFont.Weight.Black
        )
        self.label.setFont(font)
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("color: white;")

        # Тень под текст
        effect = QtWidgets.QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(24)
        effect.setColor(QtGui.QColor(0, 0, 0, 200))
        effect.setOffset(2, 6)
        self.label.setGraphicsEffect(effect)
        layout.addWidget(self.label)

        # На весь экран (активный дисплей под курсором; фоллбек — основной)
        self._apply_screen_geometry()

    def start(self, seconds: int):
        self._seconds_left = max(0, int(seconds or 0))
        self._update_text()
        # Перед показом убедимся, что на нужном экране
        self._apply_screen_geometry()
        self.show()
        try:
            # Принудительный подъём и TOPMOST над полноэкранными окнами
            self.raise_()
            # Не активируем фокус (оверлей прозрачный для кликов), но поднимаем
            if win32gui and win32con:
                hwnd = int(self.winId())
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOPMOST,
                    0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                )
        except Exception:
            pass
        if self._seconds_left > 0:
            self._timer.start(1000)
        else:
            self._finish()

    def stop(self):
        if self._timer.isActive():
            self._timer.stop()
        self.hide()
        self.closed.emit()

    def _on_tick(self):
        if self._seconds_left > 0:
            self._seconds_left -= 1
            self._update_text()
        if self._seconds_left <= 0:
            self._finish()

    def _finish(self):
        if self._timer.isActive():
            self._timer.stop()
        self.hide()
        self.closed.emit()

    def _update_text(self):
        if self._seconds_left > 0:
            self.label.setText(f"{self._seconds_left}")
        else:
            self.label.setText("")

    def _apply_screen_geometry(self):
        try:
            pos = QtGui.QCursor.pos()
            screen = None
            if hasattr(QtWidgets.QApplication, 'screenAt'):
                screen = QtWidgets.QApplication.screenAt(pos)
            if screen is None:
                screen = QtWidgets.QApplication.primaryScreen()
            if screen:
                # Используем полную геометрию экрана, чтобы перекрыть даже панели
                geo = screen.geometry()
                self.setGeometry(geo)
        except Exception:
            pass
