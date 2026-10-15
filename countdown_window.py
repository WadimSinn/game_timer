"""
Файл: countdown_window.py

Модуль с реализацией окна обратного отсчёта времени перед блокировкой (CountdownWindow) для Game Timer.
"""

from PyQt6 import QtWidgets, QtCore
import sys

class CountdownWindow(QtWidgets.QDialog):
    countdown_finished = QtCore.pyqtSignal()

    def __init__(self, delay_seconds, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Предупреждение")
        self.setWindowFlags(
            self.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(True)
        self.resize(350, 120)

        self.remaining_time = delay_seconds
        self.label = QtWidgets.QLabel(f"Игра будет заблокирована через {self.remaining_time} секунд", self)
        self.label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.label)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._update_countdown)
        self.timer.start(1000)

    def _update_countdown(self):
        self.remaining_time -= 1
        if self.remaining_time <= 0:
            self.label.setText("Время вышло!")
            self.timer.stop()
            QtCore.QTimer.singleShot(1000, self._finish)
        else:
            self.label.setText(f"Игра будет заблокирована через {self.remaining_time} секунд")

    def _finish(self):
        self.accept()  # Закрыть окно
        self.countdown_finished.emit()

# Тестирование окна отдельно
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = CountdownWindow(10)
    window.exec()
