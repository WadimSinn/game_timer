import logging
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu
from PyQt6.QtGui import QAction, QIcon
from PyQt6 import QtCore
import os

class TrayManager:
    """
    Управляет иконкой приложения в системном трее с использованием PyQt6.
    """
    def __init__(self, app_window):
        """
        Инициализация менеджера трея.
        :param app_window: Экземпляр главного окна приложения (GameTimerApp).
        """
        self.logger = logging.getLogger(self.__class__.__name__)
        self.app = app_window.app
        self.main_window = app_window

        self.tray_icon = QSystemTrayIcon(self.get_icon(), self.main_window)
        self.tray_icon.setToolTip("Game Timer")

        menu = QMenu()
        show_action = QAction("Показать", self.main_window)
        self.start_action = QAction("Старт", self.main_window)
        self.pause_action = QAction("Пауза", self.main_window)
        self.reset_action = QAction("Сброс", self.main_window)
        parent_action = QAction("Родительское управление…", self.main_window)
        quit_action = QAction("Выход", self.main_window)

        show_action.triggered.connect(self.main_window.show_main_window)
        self.start_action.triggered.connect(self.main_window.start_timer)
        self.pause_action.triggered.connect(self.main_window.pause_resume)
        self.reset_action.triggered.connect(self.main_window.reset_timer)
        parent_action.triggered.connect(self.main_window.show_parent_controls)
        quit_action.triggered.connect(self.main_window.quit_app)

        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(self.start_action)
        menu.addAction(self.pause_action)
        menu.addAction(self.reset_action)
        menu.addAction(parent_action)
        menu.addSeparator()
        # Подменю с горячими клавишами (read-only)
        self.hotkeys_menu = menu.addMenu("Горячие клавиши")
        self._populate_hotkeys_menu()

        menu.addAction(quit_action)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        self.logger.info("Tray Manager initialized.")

        # Таймер для обновления пунктов меню по состоянию таймера
        self._menu_update_timer = QtCore.QTimer(self.main_window)
        self._menu_update_timer.timeout.connect(self.update_menu_state)
        self._menu_update_timer.start(1000)

    def _populate_hotkeys_menu(self):
        """Заполняет подменю 'Горячие клавиши' текущими комбинациями."""
        try:
            self.hotkeys_menu.clear()
            # Настраиваемые хоткеи из settings
            titles = {
                'start': 'Старт',
                'pause_resume': 'Пауза/Продолжить',
                'reset': 'Сброс',
                'add_5_min': '+5 минут',
                'add_30_min': '+30 минут',
            }
            hotkeys = {}
            try:
                hotkeys = self.main_window.settings.get('hotkeys') or {}
            except Exception:
                hotkeys = {}

            for key, title in titles.items():
                combo = hotkeys.get(key)
                if key == 'pause_resume' and not combo:
                    combo = hotkeys.get('pause')
                if combo:
                    act = QAction(f"{title} — {combo}", self.main_window)
                    act.setEnabled(False)
                    self.hotkeys_menu.addAction(act)

            # Встроенные фиксированные хоткеи
            self.hotkeys_menu.addSeparator()
            fixed = [
                "Увеличить лимит — Ctrl+Alt+Up",
                "Уменьшить лимит — Ctrl+Alt+Down",
                "Родительское управление — Ctrl+Alt+B",
            ]
            for label in fixed:
                act = QAction(label, self.main_window)
                act.setEnabled(False)
                self.hotkeys_menu.addAction(act)
        except Exception as e:
            self.logger.error(f"Failed to populate hotkeys menu: {e}")

    def get_icon(self, icon_name="icon.png"):
        """Загружает иконку из файла.
        Порядок поиска: timer.ico -> Icon_game_timer.png -> icon.png -> стандартная.
        """
        base_dir = os.path.dirname(__file__)
        candidates = [
            os.path.join(base_dir, 'timer.ico'),
            os.path.join(base_dir, 'Icon_game_timer.png'),
            os.path.join(base_dir, icon_name),
        ]
        for path in candidates:
            if os.path.exists(path):
                return QIcon(path)
        self.logger.warning("No tray icon found (timer.ico/Icon_game_timer.png/icon.png). Using default icon.")
        default_icon = self.main_window.style().standardIcon(
        self.main_window.style().StandardPixmap.SP_ComputerIcon
        )
        return default_icon

    def on_tray_icon_activated(self, reason):
        """Обрабатывает клики по иконке в трее."""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.main_window.show_main_window()

    def update_menu_state(self):
        """Обновляет текст и доступность пунктов меню в зависимости от состояния таймера."""
        try:
            tm = getattr(self.main_window, 'timer_manager', None)
            if tm is None:
                # Без таймера: всё выключаем кроме Старт и Показать/Выход
                self.start_action.setEnabled(True)
                self.pause_action.setEnabled(False)
                self.reset_action.setEnabled(False)
                self.pause_action.setText("Пауза")
                return

            running = tm.is_running()
            paused = tm.is_paused()

            # Старт доступен, если таймер не запущен
            self.start_action.setEnabled(not running)

            # Пауза/Продолжить доступна, если таймер запущен
            self.pause_action.setEnabled(running)
            self.pause_action.setText("Продолжить" if paused else "Пауза")

            # Сброс доступен, если таймер запущен
            self.reset_action.setEnabled(running)
        except Exception as e:
            self.logger.error(f"Failed to update tray menu state: {e}")

    def set_icon(self, icon_name):
        """Меняет иконку в трее."""
        self.tray_icon.setIcon(self.get_icon(icon_name))

    def show_message(
        self, title, message,
        icon=QSystemTrayIcon.MessageIcon.Information, msecs=5000
    ):
        """Показывает уведомление из трея."""
        self.tray_icon.showMessage(title, message, icon, msecs)
