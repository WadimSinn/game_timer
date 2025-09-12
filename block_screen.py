"""
Файл: block_screen.py

Модуль с реализацией полноэкранного окна блокировки (BlockScreen) для ограничения доступа к играм по истечении лимита времени.
Используется в приложении Game Timer.
"""

from PyQt5 import QtWidgets, QtCore, QtGui
import sys
from settings_manager import SettingsManager

class BlockScreen(QtWidgets.QDialog):
    def __init__(self, settings, countdown_seconds=10, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._seconds_left = max(0, int(countdown_seconds or 0))
        self.setWindowTitle("Блокировка игры")
        self.setWindowFlags(QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.FramelessWindowHint)
        self.setWindowState(QtCore.Qt.WindowFullScreen)
        self.setModal(True)
        self.setStyleSheet("background-color: black;")

        layout = QtWidgets.QVBoxLayout(self)
        self.message_label = QtWidgets.QLabel(
            self.settings.get("block_screen_message", "Время игры истекло! Пожалуйста, сделайте перерыв."),
            self
        )
        self.message_label.setStyleSheet("color: white; font-size: 32px; padding: 40px;")
        self.message_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.message_label)

        # Видимый обратный отсчет до полной блокировки
        self.countdown_label = QtWidgets.QLabel("", self)
        self.countdown_label.setStyleSheet("color: #cccccc; font-size: 24px; padding: 10px;")
        self.countdown_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.countdown_label)

        # Таймер обратного отсчета (только визуальный, окно всё равно остаётся заблокированным)
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        if self._seconds_left > 0:
            self._update_countdown_text()
            self._timer.start(1000)
        else:
            self._update_countdown_text()

    def closeEvent(self, event):
        # Блокируем закрытие окна
        event.ignore()

    def _on_tick(self):
        if self._seconds_left > 0:
            self._seconds_left -= 1
            self._update_countdown_text()
        if self._seconds_left <= 0 and self._timer.isActive():
            # Оставляем экран заблокированным, просто прекращаем тики
            self._timer.stop()

    def _update_countdown_text(self):
        if self._seconds_left > 0:
            self.countdown_label.setText(f"Блокировка через: {self._seconds_left} сек")
        else:
            self.countdown_label.setText("Блокировка активна")

