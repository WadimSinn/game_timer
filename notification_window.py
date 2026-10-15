from PyQt6 import QtWidgets, QtCore, QtGui
try:
    import win32gui, win32con
except Exception:
    win32gui = None
    win32con = None
import winsound
import time
import random
from logger import Logger

"""
Файл: notification_window.py

Модуль для отображения всплывающих уведомлений пользователю в приложении Game Timer.
"""

class NotificationWindow(QtWidgets.QDialog):
    def __init__(self, title="Уведомление", message="", on_close_callback=None):
        super().__init__()
        self.on_close_callback = on_close_callback
        self.logger = Logger("NotificationWindow", "notifications.log")

        self.setWindowTitle(title)
        self.setWindowFlags(
            self.windowFlags()
            | QtCore.Qt.WindowType.FramelessWindowHint
            | QtCore.Qt.WindowType.WindowStaysOnTopHint
            | QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)

        # Основной контейнер с тенью
        shadow_widget = QtWidgets.QWidget(self)
        shadow_widget.setObjectName("shadow_widget")
        shadow_widget.setStyleSheet("""
            QWidget#shadow_widget {
                background-color: #4A90E2;
                border-radius: 20px;
            }
        """)
        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(32)
        shadow.setColor(QtGui.QColor(0, 0, 0, 160))
        shadow.setOffset(0, 8)
        shadow_widget.setGraphicsEffect(shadow)

        layout = QtWidgets.QVBoxLayout(shadow_widget)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(18)

        # Заголовок
        title_label = QtWidgets.QLabel("ЕГОР!")
        title_label.setFont(
            QtGui.QFont("Montserrat", 32, QtGui.QFont.Weight.Bold)
        )
        title_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("color: white;")
        layout.addWidget(title_label)

        # Сообщение
        messages = [
            "Давай сделаем перерыв!\nТвои глазки устали 👀",
            "Время отдохнуть!\nПобегай немного 🏃",
            "Пора размяться!\nПоиграем в игрушки или порисуй? 🎯",
            "Перерыв!\nПора подвигаться 🌟"
        ]
        msg = message if message else random.choice(messages)
        self.message_label = QtWidgets.QLabel(msg)
        self.message_label.setFont(QtGui.QFont("Montserrat", 18))
        self.message_label.setWordWrap(True)
        self.message_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.message_label.setStyleSheet("color: #f5f6fa;")
        layout.addWidget(self.message_label)

        # (Отсчет перенесен в отдельный оверлей CountdownOverlay)

        # Кнопка закрытия
        close_btn = QtWidgets.QPushButton("Закрыть")
        close_btn.setFont(QtGui.QFont("Montserrat", 14))
        close_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #357ABD;
                color: white;
                border-radius: 12px;
                padding: 10px 36px;
                font-weight: bold;
                letter-spacing: 1px;
            }
            QPushButton:hover {
                background-color: #285a8c;
            }
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(
            close_btn, alignment=QtCore.Qt.AlignmentFlag.AlignCenter
        )

        # Основной layout окна
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(shadow_widget)
        self.setLayout(outer_layout)
        self.resize(500, 250)
        self.setModal(False)

        # Размещение в правом нижнем углу
        self._move_to_bottom_right()
        # Анимация появления
        self._animate_show()
        # Без внутреннего обратного отсчета: управление только через кнопку "Закрыть"

    def _move_to_bottom_right(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return
        screen_geo = screen.availableGeometry()
        self.move(
            screen_geo.right() - self.width() - 20,
            screen_geo.bottom() - self.height() - 20
        )

    def _animate_show(self):
        self.anim = QtCore.QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(500)
        self.anim.setStartValue(0)
        self.anim.setEndValue(1)
        self.anim.start()

    def closeEvent(self, event):
        if self.on_close_callback:
            self.on_close_callback()
        super().closeEvent(event)

    def show(self, duration=0):
        """Показать уведомление (без авто-закрытия по умолчанию)"""
        super().show()
        try:
            # Принудительный TOPMOST поверх полноэкранных окон
            self.raise_()
            self.activateWindow()
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
        winsound.PlaySound("SystemExclamation", winsound.SND_ASYNC)
        # Если передана продолжительность > 0, закроем окно по таймеру
        duration = int(duration or 0)
        if duration > 0:
            QtCore.QTimer.singleShot(duration * 1000, self.accept)

    def update_message(self, message: str):
        """
        Обновляет текст сообщения
        
        Args:
            message: Новый текст сообщения
        """
        self.message_label.setText(message)
            
    def update_theme(self, is_dark: bool = False):
        """
        Обновляет тему окна
        
        Args:
            is_dark: True для темной темы, False для светлой
        """
        # Эта функция больше не нужна, так как стили задаются через QSS
        # Но оставим ее для совместимости, если будет вызываться
        self.logger.info(f"Theme update called with is_dark={is_dark}. No visual change will occur.")
