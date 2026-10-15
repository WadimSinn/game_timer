"""
Файл: block_screen.py

Модуль с реализацией полноэкранного окна блокировки (BlockScreen) для ограничения доступа к играм по истечении лимита времени.
Используется в приложении Game Timer.
"""

from PyQt6 import QtWidgets, QtCore

class BlockScreen(QtWidgets.QDialog):
    def __init__(
        self,
        settings,
        countdown_seconds=10,
        parent=None,
        close_game_callback=None,
    ):
        super().__init__(parent)
        self.settings = settings
        self.close_game_callback = close_game_callback
        self._seconds_left = max(0, int(countdown_seconds or 0))
        self.setWindowTitle("Блокировка игры")
        self.setWindowFlags(
            QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.FramelessWindowHint
        )
        self.setWindowState(QtCore.Qt.WindowState.WindowFullScreen)
        self.setModal(True)
        self.setStyleSheet("background-color: black;")

        layout = QtWidgets.QVBoxLayout(self)
        self.message_label = QtWidgets.QLabel(
            self.settings.get("block_screen_message", "Время игры истекло! Пожалуйста, сделайте перерыв."),
            self
        )
        self.message_label.setStyleSheet("color: white; font-size: 32px; padding: 40px;")
        self.message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.message_label)

        # Видимый обратный отсчет до полной блокировки
        self.countdown_label = QtWidgets.QLabel("", self)
        self.countdown_label.setStyleSheet("color: #cccccc; font-size: 24px; padding: 10px;")
        self.countdown_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.countdown_label)

        self.close_game_button = QtWidgets.QPushButton("Закрыть игру", self)
        self.close_game_button.setStyleSheet(
            "QPushButton{font-size:20px; padding:12px 24px; "
            "background-color:#b02a37; color:white; border-radius:8px;}"
            "QPushButton:hover{background-color:#dc3545;}"
        )
        self.close_game_button.clicked.connect(self._request_game_close)
        layout.addWidget(
            self.close_game_button, alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )

        self.close_game_status = QtWidgets.QLabel("", self)
        self.close_game_status.setStyleSheet(
            "color: #cccccc; font-size: 16px; padding: 8px;"
        )
        self.close_game_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.close_game_status)

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

    def _request_game_close(self):
        if self.close_game_callback is None:
            self.close_game_status.setText(
                "Закрытие игры недоступно. Попросите родителя."
            )
            return
        try:
            requested_windows = self.close_game_callback()
        except Exception:
            self.close_game_status.setText(
                "Не удалось отправить запрос. Попросите родителя."
            )
            return

        if requested_windows is None:
            self.close_game_status.setText(
                "Не удалось отправить запрос. Попросите родителя."
            )
        elif requested_windows:
            self.close_game_status.setText(
                "Запрос отправлен. Подождите, пока игра закроется."
            )
        else:
            self.close_game_status.setText(
                "Окно игры не найдено. Попросите родителя проверить список игр."
            )
