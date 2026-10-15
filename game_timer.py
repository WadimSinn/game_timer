"""
Главный модуль приложения Game Timer.
"""
import sys
import os
import logging
import ctypes
import time
import typing
from datetime import date, datetime, timedelta
from PyQt6 import QtWidgets, QtCore, QtGui
from notification_window import NotificationWindow
from countdown_overlay import CountdownOverlay
from achievement_widgets import AchievementsWindow, AchievementCard
from settings_manager import SettingsManager
from game_blocker import GameBlocker
from timer_manager import TimerManager
from process_manager import ProcessManager
from hotkey_manager import HotkeyManager
from activity_monitor import ActivityMonitor
from achievement_manager import AchievementManager
from autostart_manager import AutostartManager
from sound_manager import SoundManager
from tray_manager import TrayManager
from corner_toast import CornerToast

# --- Single instance helper (Windows named mutex) ---
def _acquire_single_instance_mutex():
    """Возвращает (handle, acquired). Если уже запущено — acquired=False."""
    try:
        kernel32 = ctypes.windll.kernel32
        mutex = kernel32.CreateMutexW(None, False, "Global\\GameTimerMutex")
        last_error = kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if mutex == 0:
            return None, True  # не удалось создать — не блокируем запуск
        if last_error == ERROR_ALREADY_EXISTS:
            return mutex, False
        return mutex, True
    except Exception:
        return None, True


class HotkeyDispatcher(QtCore.QObject):
    """Moves global hotkey callbacks from keyboard's worker thread to Qt's UI thread."""

    requested = QtCore.pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.requested.connect(
            self._run_callback, QtCore.Qt.ConnectionType.QueuedConnection
        )

    def dispatch(self, callback):
        self.requested.emit(callback)

    @QtCore.pyqtSlot(object)
    def _run_callback(self, callback):
        callback()


# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

class GUIManager(QtWidgets.QWidget):
    """Управляет всеми элементами пользовательского интерфейса."""
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.logger = logging.getLogger(self.__class__.__name__)
        self.process_manager = None  # Будет установлен позже
        self._build_ui()

    def _build_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)

        # Вкладки
        self.tabs = QtWidgets.QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- Вкладка Главная ---
        main_tab = QtWidgets.QWidget()
        main_tab_layout = QtWidgets.QVBoxLayout(main_tab)

        # --- Статистика (сводка) ---
        stats_group = QtWidgets.QGroupBox("Статистика")
        stats_layout = QtWidgets.QVBoxLayout()
        self.stats_today = QtWidgets.QLabel("Сегодня сыграно: 00:00:00")
        self.stats_left = QtWidgets.QLabel("Осталось: 02:00:00")
        self.stats_week = QtWidgets.QLabel("За неделю: 00:00:00")
        self.play_session_progress_label = QtWidgets.QLabel(
            "До перерыва: 00:00 из 02:00"
        )
        self.play_session_progress_bar = QtWidgets.QProgressBar()
        self.play_session_progress_bar.setRange(0, 1000)
        self.play_session_progress_bar.setTextVisible(False)
        self.rest_info = QtWidgets.QLabel("")
        self.rest_info.hide()
        stats_layout.addWidget(self.stats_today)
        stats_layout.addWidget(self.stats_left)
        stats_layout.addWidget(self.stats_week)
        stats_layout.addWidget(self.play_session_progress_label)
        stats_layout.addWidget(self.play_session_progress_bar)
        stats_layout.addWidget(self.rest_info)
        stats_group.setLayout(stats_layout)
        main_tab_layout.addWidget(stats_group)

        # --- Заголовок ---
        title = QtWidgets.QLabel("Game Timer")
        title.setFont(QtGui.QFont("Helvetica", 22, QtGui.QFont.Weight.Bold))
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        main_tab_layout.addWidget(title)

        # --- Таймер ---
        self.time_display = QtWidgets.QLabel("00:00:00")
        font = self.time_display.font()
        font.setFamily("Helvetica")
        font.setPointSize(48)
        self.time_display.setFont(font)
        self.time_display.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        main_tab_layout.addWidget(self.time_display)

        # --- Ввод времени ---
        time_group = QtWidgets.QGroupBox("Время")
        time_layout = QtWidgets.QHBoxLayout()
        self.hours = QtWidgets.QLineEdit('0')
        self.minutes = QtWidgets.QLineEdit('0')
        self.seconds = QtWidgets.QLineEdit('0')
        for widget, label in zip([self.hours, self.minutes, self.seconds], ["Часы:", "Минуты:", "Секунды:"]):
            time_layout.addWidget(QtWidgets.QLabel(label))
            widget.setMaximumWidth(40)
            widget.setValidator(QtGui.QIntValidator(0, 99))
            time_layout.addWidget(widget)
        time_group.setLayout(time_layout)
        main_tab_layout.addWidget(time_group)

        # --- Режим таймера ---
        mode_group = QtWidgets.QGroupBox("Режим таймера")
        mode_layout = QtWidgets.QHBoxLayout()
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['Обратный отсчет', 'Прямой отсчет'])
        mode_layout.addWidget(self.mode)
        mode_group.setLayout(mode_layout)
        main_tab_layout.addWidget(mode_group)

        # --- Кнопки управления ---
        control_group = QtWidgets.QGroupBox("Управление")
        btn_layout = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton('Старт')
        self.pause_button = QtWidgets.QPushButton('Пауза')
        self.reset_button = QtWidgets.QPushButton('Сброс')
        self.my_ach_button = QtWidgets.QPushButton("Мои достижения")
        btn_layout.addWidget(self.start_button)
        btn_layout.addWidget(self.pause_button)
        btn_layout.addWidget(self.reset_button)
        btn_layout.addWidget(self.my_ach_button)
        control_group.setLayout(btn_layout)
        main_tab_layout.addWidget(control_group)

        # --- Пресеты ---
        presets_group = QtWidgets.QGroupBox("Пресеты")
        presets_layout = QtWidgets.QHBoxLayout()
        presets_cfg = self.app.settings.get('presets', {}) or {}
        # Формат: имя: {hours, minutes, seconds}
        for name, spec in presets_cfg.items():
            try:
                h = int(spec.get('hours', 0))
                m = int(spec.get('minutes', 0))
                s = int(spec.get('seconds', 0))
            except Exception:
                h, m, s = 0, 0, 0
            btn = QtWidgets.QPushButton(name)
            btn.clicked.connect(lambda _, h=h, m=m, s=s: self.app.apply_preset(h, m, s))
            presets_layout.addWidget(btn)
        presets_group.setLayout(presets_layout)
        main_tab_layout.addWidget(presets_group)

        # --- Список процессов ---
        apps_group = QtWidgets.QGroupBox("Отслеживаемые приложения")
        apps_layout = QtWidgets.QVBoxLayout()
        self.apps_list = QtWidgets.QListWidget()
        apps_layout.addWidget(self.apps_list)
        proc_btn_layout = QtWidgets.QHBoxLayout()
        self.add_proc_button = QtWidgets.QPushButton("Добавить")
        self.remove_proc_button = QtWidgets.QPushButton("Удалить")
        proc_btn_layout.addWidget(self.add_proc_button)
        proc_btn_layout.addWidget(self.remove_proc_button)
        apps_layout.addLayout(proc_btn_layout)
        apps_group.setLayout(apps_layout)
        main_tab_layout.addWidget(apps_group)

        # Подключение сигналов к кнопкам
        self.start_button.clicked.connect(self.app.start_timer)
        self.pause_button.clicked.connect(self.app.pause_timer)
        self.reset_button.clicked.connect(self.app.reset_timer)
        self.add_proc_button.clicked.connect(self.add_process)
        self.remove_proc_button.clicked.connect(self.remove_process)
        self.my_ach_button.clicked.connect(self.show_my_achievements)

        self.tabs.addTab(main_tab, "Главная")

        # --- Вкладка Статистика игр ---
        stats_tab = QtWidgets.QWidget()
        stats_tab_layout = QtWidgets.QVBoxLayout(stats_tab)
        period_layout = QtWidgets.QHBoxLayout()
        self.btn_today = QtWidgets.QPushButton("Сегодня")
        self.btn_week = QtWidgets.QPushButton("Неделя")
        period_layout.addWidget(self.btn_today)
        period_layout.addWidget(self.btn_week)
        stats_tab_layout.addLayout(period_layout)

        self.games_table = QtWidgets.QTableWidget(0, 4)
        self.games_table.setHorizontalHeaderLabels(["Игра", "Сегодня", "Неделя", "Сессий/Последний запуск"])
        self.games_table.horizontalHeader().setStretchLastSection(True)
        self.games_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        stats_tab_layout.addWidget(self.games_table)

        self.btn_today.clicked.connect(lambda: self.update_per_game_stats(self.process_manager, period='today'))
        self.btn_week.clicked.connect(lambda: self.update_per_game_stats(self.process_manager, period='week'))

        self.tabs.addTab(stats_tab, "Статистика игр")

        # --- Вкладка Достижения ---
        ach_tab = QtWidgets.QScrollArea()
        ach_tab.setWidgetResizable(True)
        ach_container = QtWidgets.QWidget()
        self.ach_layout = QtWidgets.QVBoxLayout(ach_container)
        ach_tab.setWidget(ach_container)
        self.tabs.addTab(ach_tab, "Достижения")

        # --- Вкладка лимитов и отдыха ---
        limits_tab = QtWidgets.QWidget()
        limits_layout = QtWidgets.QVBoxLayout(limits_tab)
        limits_layout.addWidget(QtWidgets.QLabel(
            "Время учитывается, только когда окно отслеживаемой игры активно "
            "на переднем плане."
        ))

        daily_group = QtWidgets.QGroupBox("Дневные лимиты по дням недели")
        daily_layout = QtWidgets.QGridLayout(daily_group)
        daily_layout.addWidget(QtWidgets.QLabel("День"), 0, 0)
        daily_layout.addWidget(QtWidgets.QLabel("Разрешено играть"), 0, 1)
        self.daily_limit_spins = {}
        weekdays = (
            "Понедельник", "Вторник", "Среда", "Четверг",
            "Пятница", "Суббота", "Воскресенье",
        )
        today_weekday = datetime.now().weekday()
        for weekday, day_name in enumerate(weekdays):
            label = day_name + (" (сегодня)" if weekday == today_weekday else "")
            daily_layout.addWidget(QtWidgets.QLabel(label), weekday + 1, 0)
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0, 24)
            spin.setSingleStep(0.25)
            spin.setDecimals(2)
            spin.setSuffix(" ч")
            spin.setKeyboardTracking(False)
            spin.setValue(self.app._daily_limit_hours_for_weekday(weekday))
            daily_layout.addWidget(spin, weekday + 1, 1)
            self.daily_limit_spins[weekday] = spin
            spin.valueChanged.connect(self._save_daily_limits)
        limits_layout.addWidget(daily_group)

        cycle_group = QtWidgets.QGroupBox("Цикл игры и отдыха")
        cycle_layout = QtWidgets.QFormLayout(cycle_group)
        self.play_limit_enabled = QtWidgets.QCheckBox(
            "Включить обязательные перерывы"
        )
        self.play_limit_enabled.setChecked(
            bool(self.app.settings.get("enforce_play_session_limit", True))
        )
        self.play_limit_hours = QtWidgets.QDoubleSpinBox()
        self.play_limit_hours.setRange(0.25, 24)
        self.play_limit_hours.setSingleStep(0.25)
        self.play_limit_hours.setDecimals(2)
        self.play_limit_hours.setSuffix(" ч")
        self.play_limit_hours.setKeyboardTracking(False)
        self.play_limit_hours.setValue(float(
            self.app.settings.get("play_session_limit_hours", 2) or 2
        ))
        self.rest_duration_minutes = QtWidgets.QSpinBox()
        self.rest_duration_minutes.setRange(1, 1440)
        self.rest_duration_minutes.setSuffix(" мин")
        self.rest_duration_minutes.setValue(int(
            self.app.settings.get("enforced_rest_minutes", 60) or 60
        ))
        self.cycle_summary = QtWidgets.QLabel()
        cycle_layout.addRow(self.play_limit_enabled)
        cycle_layout.addRow("Играть до перерыва:", self.play_limit_hours)
        cycle_layout.addRow("Длительность перерыва:", self.rest_duration_minutes)
        cycle_layout.addRow("Правило:", self.cycle_summary)
        limits_layout.addWidget(cycle_group)

        self.limits_save_status = QtWidgets.QLabel(
            "Изменения сохраняются автоматически."
        )
        limits_layout.addWidget(self.limits_save_status)
        limits_layout.addStretch(1)
        self.play_limit_enabled.toggled.connect(
            self._save_play_limit_enabled
        )
        self.play_limit_hours.valueChanged.connect(
            lambda value: self._save_limit_value(
                "play_session_limit_hours", value
            )
        )
        self.rest_duration_minutes.valueChanged.connect(
            lambda value: self._save_limit_value(
                "enforced_rest_minutes", value
            )
        )
        self.play_limit_enabled.toggled.connect(
            self._update_cycle_summary
        )
        self.play_limit_hours.valueChanged.connect(
            self._update_cycle_summary
        )
        self.rest_duration_minutes.valueChanged.connect(
            self._update_cycle_summary
        )
        self._update_cycle_summary()
        self._update_cycle_controls()
        self.tabs.addTab(limits_tab, "Лимиты и отдых")

    def _show_limit_save_result(self, saved):
        if saved:
            self.limits_save_status.setText("Настройки сохранены.")
            self.limits_save_status.setStyleSheet("")
        else:
            self.limits_save_status.setText(
                "Не удалось сохранить настройки. Проверьте доступ к файлу settings.json."
            )
            self.limits_save_status.setStyleSheet("color: #b00020;")
            self.logger.error("Could not save play-limit settings")

    def _save_daily_limits(self, _value=None):
        limits = {
            str(weekday): spin.value()
            for weekday, spin in self.daily_limit_spins.items()
        }
        saved = self.app.settings.set("daily_limits_by_weekday", limits)
        self.app.daily_limit_seconds = self.app._daily_limit_seconds_for_today()
        self.app.update_stats()
        self._show_limit_save_result(saved)

    def _save_play_limit_enabled(self, enabled):
        saved = self.app.settings.set("enforce_play_session_limit", enabled)
        self._update_cycle_controls()
        self._show_limit_save_result(saved)

    def _save_limit_value(self, key, value):
        saved = self.app.settings.set(key, value)
        self._show_limit_save_result(saved)

    def _update_cycle_controls(self, _value=None):
        enabled = self.play_limit_enabled.isChecked()
        self.play_limit_hours.setEnabled(enabled)
        self.rest_duration_minutes.setEnabled(enabled)

    def _update_cycle_summary(self, _value=None):
        if self.play_limit_enabled.isChecked():
            self.cycle_summary.setText(
                f"{self.play_limit_hours.value():g} ч игры → "
                f"{self.rest_duration_minutes.value()} мин отдыха"
            )
        else:
            self.cycle_summary.setText("Обязательные перерывы отключены.")

    def set_rest_info(self, text: str, visible: bool):
        if visible:
            self.rest_info.setText(text)
            self.rest_info.show()
        else:
            self.rest_info.hide()
            self.rest_info.setText("")

    def show_my_achievements(self):
        try:
            dlg = AchievementsWindow(self.app.achievement_manager, self)
            dlg.exec()
        except Exception as e:
            self.logger.error(f"Не удалось открыть окно достижений: {e}")

    def update_per_game_stats(self, process_manager, period='today'):
        if not process_manager:
            return
        try:
            today = datetime.now().date()
            daily = process_manager.get_usage_by_process(today)
            start_week = today - timedelta(days=6)
            weekly = process_manager.get_usage_by_process_range(start_week, today + timedelta(days=1))
            meta = process_manager.get_last_seen_and_sessions(start_week, today + timedelta(days=1))

            names = sorted(
                set(daily) | set(weekly)
                | set(process_manager.get_running_monitored_processes())
            )
            self.games_table.setRowCount(len(names))
            for row, name in enumerate(names):
                t_day = daily.get(name, 0)
                t_week = weekly.get(name, 0)
                info = meta.get(name, {})
                last_seen = info.get('last_seen', '-')
                sessions = info.get('sessions', 0)
                def fmt(sec):
                    return f"{sec//3600:02d}:{(sec%3600)//60:02d}:{sec%60:02d}"
                self.games_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
                self.games_table.setItem(row, 1, QtWidgets.QTableWidgetItem(fmt(t_day)))
                self.games_table.setItem(row, 2, QtWidgets.QTableWidgetItem(fmt(t_week)))
                self.games_table.setItem(row, 3, QtWidgets.QTableWidgetItem(f"{sessions} / {last_seen}"))
        except Exception as e:
            self.logger.error(f"Ошибка обновления пер-игровой статистики: {e}")

    def refresh_achievements(self, achievement_manager):
        try:
            # Очистить предыдущие карточки (кроме stretch)
            while self.ach_layout.count() > 1:
                item = self.ach_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
            for ach in achievement_manager.get_all_achievements():
                progress, total = achievement_manager.get_achievement_progress(ach.id)
                card = AchievementCard(ach.title, ach.description, progress, total, ach.completed)
                self.ach_layout.addWidget(card)
            self.ach_layout.addStretch(1)
        except Exception as e:
            self.logger.error(f"Ошибка обновления вкладки достижений: {e}")

    def start_process_monitoring(self, process_manager):
        self.process_manager = process_manager
        self.update_process_list()
        self.process_timer = QtCore.QTimer(self)
        self.process_timer.timeout.connect(self.update_process_list)
        self.process_timer.start(self.app.settings.get('process_check_interval_ms', 5000))  # Настраиваемый интервал проверки

    def update_process_list(self):
        if self.process_manager is None: return
        try:
            self.apps_list.clear()
            monitored_apps = self.process_manager.get_monitored_processes()
            running_apps = {
                os.path.basename(name).lower()
                for name in self.process_manager.get_running_monitored_processes()
            }
            foreground_process = (
                self.process_manager.get_foreground_process_name() or ""
            )
            for app_name in monitored_apps:
                process_name = os.path.basename(app_name).lower()
                if process_name == foreground_process:
                    status = "на переднем плане"
                elif process_name in running_apps:
                    status = "запущена в фоне"
                else:
                    status = "не запущена"
                item_text = f"{app_name} — {status}"
                self.apps_list.addItem(item_text)
            self.app.update_stats()
        except Exception as e:
            self.logger.error(f"Ошибка при обновлении списка процессов: {e}")

    def add_process(self):
        proc_name, ok = QtWidgets.QInputDialog.getText(self, "Добавить процесс", "Имя процесса (например, 'game.exe'):")
        if ok and proc_name:
            self.process_manager.add_process_to_monitor(proc_name)
            self.update_process_list()

    def remove_process(self):
        selected = self.apps_list.currentItem()
        if not selected: return
        proc_name = selected.text().split(" — ")[0]
        self.process_manager.remove_process_from_monitor(proc_name)
        self.update_process_list()

class GameTimerApp(QtWidgets.QMainWindow):
    """Основной класс приложения."""
    def __init__(self, app):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.setWindowTitle("Game Timer")
        self.setMinimumSize(500, 800)
        self.app = app
        self.settings = SettingsManager()
        self._session_limit_warning_shown = False
        self._daily_limit_warning_date = None
        self._active_limit_warning_text = None
        self._parent_controls_dialog = None
        self._play_since_rest_seconds = max(
            0, int(self.settings.get('play_since_rest_seconds', 0) or 0)
        )
        self._last_session_progress_save_ts = time.monotonic()
        self._session_progress_dirty = False
        self.autostart_manager = AutostartManager()
        if not self.autostart_manager.set_autostart(
            self.settings.get('autostart', False) is True
        ):
            self.logger.warning("Не удалось применить настройку автозапуска")
        self.process_manager = ProcessManager(self.settings)
        self._last_usage_account_ts = time.monotonic()
        self.sound_manager = SoundManager(self.settings)
        self.gui_manager = GUIManager(self)
        self.setCentralWidget(self.gui_manager)
        self.game_blocker = GameBlocker(
            self.settings, self.process_manager.close_monitored_game_windows
        )
        self.timer_manager = TimerManager(self, self.game_blocker, self.gui_manager, self.settings)
        self.hotkey_manager = HotkeyManager()
        self.hotkey_dispatcher = HotkeyDispatcher(self)
        # Менеджер системного трея (иконка и меню)
        self.tray_manager = TrayManager(self)
        self.activity_monitor = ActivityMonitor(self.settings)
        self.achievement_manager = AchievementManager(self.settings, notification_callback=self.tray_manager.show_message)
        self.daily_limit_seconds = int(self.settings.get(
            'daily_limit_seconds',
            self.settings.get('daily_limit_hours', 2) * 3600
        ))
        self.daily_limit_seconds = self._daily_limit_seconds_for_today()
        self.timestamp = time.time()
        # Оверлей обратного отсчета (не мешает кликам)
        self.countdown_overlay = CountdownOverlay()
        # Плашка предварительного предупреждения об окончании времени
        self.pre_expiry_toast = CornerToast()

        # Сброс флага истечения таймера
        self.game_blocker.update_timer_state(False)
        # Флаг ручного запуска таймера
        self.manual_start = False

        # Перерыв (rest/cooldown)
        self.rest_until = None  # type: typing.Optional[datetime]
        try:
            _rest_str = self.settings.get('rest_until', '') or ''
            if _rest_str:
                self.rest_until = datetime.fromisoformat(_rest_str)
        except Exception:
            self.rest_until = None
        self._last_rest_notice_ts = 0.0
        self.rest_reason = None  # 'limit' | 'cooldown' | None

        self.setup_connections()
        self.gui_manager.start_process_monitoring(self.process_manager)
        self.update_stats()
        self.check_achievements()

        self.periodic_timer = QtCore.QTimer(self)
        self.periodic_timer.timeout.connect(self.run_periodic_tasks)
        self.periodic_timer.start(self.settings.get('periodic_tasks_interval_ms', 1000))

        self.app.aboutToQuit.connect(self._shutdown)

        # Анти-спам авто-приглашения к запуску таймера
        self._next_auto_prompt_ts = 0.0
        # Флаг: уже был показан один раз «грайс» после истечения таймера
        self._expire_grace_used = False
        # Ожидается отложенный показ диалога авто-старта
        self._auto_prompt_pending = False
        # Повторные автоспосы: счётчик попыток
        self._auto_prompt_retries = 0
        # Текущее окно авто-спроса
        self._auto_prompt_box = None
        self._auto_prompt_open = False
        self._block_dismissed_until_game_exit = False

    def setup_connections(self):
        self._init_hotkeys()
        # Хоткей для полного сброса данных (только для тестирования)
        try:
            # ВАЖНО: keyboard вызывает коллбеки в фоновой нити.
            # Все UI-операции перенаправляем в главный поток через singleShot.
            self.hotkey_manager.add_hotkey(
                'ctrl+alt+shift+r',
                lambda: self.hotkey_dispatcher.dispatch(self.reset_all_data)
            )
            self.logger.info("Registered reset-all hotkey: Ctrl+Alt+Shift+R")
        except Exception as e:
            self.logger.error(f"Не удалось зарегистрировать хоткей сброса: {e}")

    def run_periodic_tasks(self):
        self._account_active_usage()
        self.update_play_session_progress()
        self.daily_limit_seconds = self._daily_limit_seconds_for_today()
        # 1) Проверка активности
        self.check_activity()
        # 2) Обслуживание перерыва
        self.clear_rest_if_elapsed()
        in_rest = self.is_in_rest()
        # 3) Проверка дневного лимита -> если превышен, устанавливаем перерыв до следующего дня
        try:
            if self.settings.get('block_until_next_day_on_limit', True):
                today_used = self.process_manager.get_daily_usage()
                if today_used >= int(self.daily_limit_seconds or 0):
                    # До полуночи
                    now = datetime.now()
                    next_midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    # Если уже не стоит более длинный перерыв
                    if (not self.rest_until) or (self.rest_until < next_midnight):
                        # Устанавливаем перерыв до полуночи как следствие дневного лимита
                        self.rest_reason = 'limit'
                        self.start_rest_until(next_midnight)
                        self._notify_daily_limit_exceeded()
                        # Ачивки: отметим превышение лимита на сегодня
                        try:
                            self.achievement_manager.set_limit_exceeded_today()
                        except Exception:
                            pass
        except Exception as e:
            self.logger.error(f"Ошибка проверки дневного лимита: {e}")
        try:
            today_used = self.process_manager.get_daily_usage()
            self._check_limit_warnings(today_used)
        except Exception as e:
            self.logger.error(f"Ошибка проверки предупреждений лимитов: {e}")
        # 4) Если во время перерыва запущены игры — немедленная блокировка + уведомление
        try:
            if in_rest and self.process_manager.is_any_monitored_process_running():
                self._notify_rest()
                # Ачивки: попытка запуска во время перерыва
                try:
                    self.achievement_manager.on_attempt_during_rest()
                except Exception:
                    pass
                if not self._block_dismissed_until_game_exit:
                    self.game_blocker.update_timer_state(True)
                    self.game_blocker.start_blocking_sequence()
        except Exception as e:
            self.logger.error(f"Ошибка блокировки во время перерыва: {e}")
        # 4.1) Обновить индикатор перерыва в UI
        try:
            if in_rest and self.rest_until:
                until_str = self.rest_until.strftime('%H:%M')
                self.gui_manager.set_rest_info(f"Перерыв до {until_str} (осталось {self.rest_remaining_str()})", True)
            else:
                self.gui_manager.set_rest_info("", False)
        except Exception:
            pass
        # 5) При обнаружении игры — предложить запустить таймер (если не идёт и нет перерыва)
        try:
            if self.settings.get('auto_start_on_game_detect', True):
                any_game = self.process_manager.is_any_monitored_process_running()
                timer_running = self.timer_manager.is_running()
                # Дополнительные условия подавления авто-старта:
                # - таймер уже истёк (идёт grace или после него),
                # - уже показано уведомление о конце времени.
                suppress_auto_prompt = self.timer_manager.is_expired() or hasattr(self, 'notification_shown')
                if not in_rest and any_game and not timer_running and not suppress_auto_prompt:
                    # Запланировать отложенный показ, если ещё не запланирован
                    if not self._auto_prompt_pending:
                        delay_sec = int(self.settings.get('auto_prompt_initial_delay_sec', 20) or 20)
                        self._auto_prompt_pending = True
                        QtCore.QTimer.singleShot(max(0, delay_sec) * 1000, self._auto_prompt_after_delay)
                else:
                    # Условие не выполняется — сбросим ожидание
                    self._auto_prompt_pending = False
                    self._auto_prompt_retries = 0
        except Exception:
            pass

        # 6) Обычный мониторинг авто-таймера и достижения
        self._autocountup_monitor()
        if self.timer_manager.is_running() and not self.timer_manager.is_paused():
            self.achievement_manager.on_timer_tick(
                self.timer_manager.get_elapsed_time()
            )
        self.check_achievements()
        # 7) Обновление плашки обратного отсчета до конца
        self._update_pre_expiry_toast()

    def start_timer(self):
        try:
            # Запрет запуска таймера во время перерыва
            if self.is_in_rest():
                self._notify_rest()
                return
            if self._active_limit_warning_text:
                self.pre_expiry_toast.show_text(
                    self._active_limit_warning_text
                )
                return
            mode_text = self.gui_manager.mode.currentText()
            mode = 'countdown' if 'Обратный' in mode_text else 'countup'
            if mode == 'countdown':
                h = int(self.gui_manager.hours.text() or 0)
                m = int(self.gui_manager.minutes.text() or 0)
                s = int(self.gui_manager.seconds.text() or 0)
                started = self.timer_manager.start_timer(
                    h * 3600 + m * 60 + s, mode
                )
                if not started:
                    QtWidgets.QMessageBox.information(
                        self, "Таймер", "Укажи время больше нуля."
                    )
                    return
            else:
                if not self.timer_manager.start_timer(0, mode):
                    return
            self.achievement_manager.on_timer_start()
            # Установка флага ручного запуска
            # Сброс показать-один-раз уведомления и таймера проверки, если были
            if hasattr(self, 'post_notification_timer'):
                self.post_notification_timer.stop()
            if hasattr(self, 'notification_shown'):
                del self.notification_shown
            self.manual_start = True
            # Новый запуск таймера — сбрасываем флаг грайса
            self._expire_grace_used = False
            self._block_dismissed_until_game_exit = False
        except Exception as e:
            self.logger.error(f"Ошибка авто-приглашения к запуску таймера: {e}")

    def _auto_prompt_after_delay(self):
        """Отложенный показ окна авто-старта: проверяет условия повторно и вызывает диалог."""
        try:
            # Сброс pending независимо от результата, чтобы можно было планировать далее
            self._auto_prompt_pending = False
            # Повторная проверка условий
            # Подавление авто-диалога во время/после истечения таймера и в период grace
            if self.timer_manager.is_expired() or hasattr(self, 'notification_shown'):
                self._auto_prompt_retries = 0
                return
            if self.is_in_rest():
                self._auto_prompt_retries = 0
                return
            if not self.settings.get('auto_start_on_game_detect', True):
                self._auto_prompt_retries = 0
                return
            # Дебаунс: если игра "мигнула" и пропала < 2 сек, повторы не сбрасываем
            if not self.process_manager.is_any_monitored_process_running():
                now_ts = time.time()
                since = getattr(self, '_auto_prompt_game_not_running_since', None)
                if since is None:
                    self._auto_prompt_game_not_running_since = now_ts
                    return
                if (now_ts - since) < 2.0:
                    # Меньше 2 сек отсутствия — считаем флапом, не сбрасываем повторы
                    return
                # Долго нет игры — сбрасываем повторы и таймер отметки
                self._auto_prompt_retries = 0
                self._auto_prompt_game_not_running_since = None
                return
            else:
                # Игра снова есть — сбрасываем отметку отсутствия
                if hasattr(self, '_auto_prompt_game_not_running_since'):
                    self._auto_prompt_game_not_running_since = None
            if self.timer_manager.is_running():
                self._auto_prompt_retries = 0
                return
            self._maybe_prompt_auto_start()
        except Exception:
            pass

    def _maybe_prompt_auto_start(self):
        """Показывает неблокирующее окно 'Начать таймер?' с повторами и таймаутом.
        Улучшено для детского UX: крупные кнопки, эмодзи, центрирование, логирование путей закрытия.
        Есть защита от флапа условий в первые 3 секунды.
        """
        try:
            # Подавление авто-диалога во время/после истечения таймера и в период grace
            if self.timer_manager.is_expired() or hasattr(self, 'notification_shown'):
                return
            now = time.time()
            if now < self._next_auto_prompt_ts:
                return
            # Если окно уже открыто — поднимем и выйдем
            if self._auto_prompt_open and self._auto_prompt_box and self._auto_prompt_box.isVisible():
                try:
                    self._auto_prompt_box.raise_()
                    self._auto_prompt_box.activateWindow()
                except Exception:
                    pass
                return

            text = self.settings.get('auto_prompt_text', 'Обнаружена игра. Начать таймер?')
            timeout_sec = int(self.settings.get('auto_prompt_dialog_timeout_sec', 8) or 8)
            timeout_sec = max(3, timeout_sec)  # Минимум 3 секунды показа
            retry_sec = int(self.settings.get('auto_prompt_retry_seconds', 30) or 30)
            max_retries = int(self.settings.get('auto_prompt_max_retries', 3) or 3)
            snooze_min = int(self.settings.get('auto_prompt_snooze_minutes', 5) or 5)

            box = QtWidgets.QMessageBox(self)
            self._auto_prompt_box = box
            self._auto_prompt_open = True
            box.setWindowTitle('⏱️ Таймер')
            box.setText(f"🎮 {text}")
            box.setIcon(QtWidgets.QMessageBox.Icon.Question)
            box.setStandardButtons(QtWidgets.QMessageBox.StandardButton.NoButton)
            yes_btn = box.addButton(QtWidgets.QMessageBox.StandardButton.Yes)
            no_btn = box.addButton(QtWidgets.QMessageBox.StandardButton.No)
            try:
                yes_btn.setText('Да, начать! 🚀')
                no_btn.setText('Нет, позже')
            except Exception:
                pass
            box.setDefaultButton(yes_btn)
            box.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
            box.setWindowFlag(QtCore.Qt.WindowType.Tool, True)
            box.setWindowModality(QtCore.Qt.WindowModality.NonModal)
            # Крупный шрифт и удобные кнопки
            try:
                box.setStyleSheet(
                    "QLabel{font-size:18px;} "
                    "QPushButton{font-size:18px; padding:10px 18px; border-radius:8px;}"
                )
                yes_btn.setStyleSheet(
                    "QPushButton{background-color:#28a745; color:white;}"
                    "QPushButton:hover{background-color:#2ecc71;}"
                )
                no_btn.setStyleSheet(
                    "QPushButton{background-color:#6c757d; color:white;}"
                    "QPushButton:hover{background-color:#95a5a6;}"
                )
            except Exception:
                pass

            shown_at = time.time()
            self.logger.info("Auto-prompt: show dialog (retries=%s)" % self._auto_prompt_retries)

            def on_yes():
                try:
                    mode = str(self.settings.get('auto_start_mode', 'countup') or 'countup')
                    if mode == 'countdown':
                        secs = int(self.settings.get('auto_countdown_seconds', 3600) or 3600)
                        secs = max(0, secs)
                        started = self.timer_manager.start_timer(secs, 'countdown')
                    else:
                        started = self.timer_manager.start_timer(0, 'countup')
                    if not started:
                        self.tray_manager.show_message(
                            "Таймер",
                            "Автоматическая длительность должна быть больше нуля."
                        )
                        return
                    self.achievement_manager.on_timer_start()
                    self.manual_start = False
                    self._expire_grace_used = False
                    self._block_dismissed_until_game_exit = False
                    self._auto_prompt_retries = 0
                    self.logger.info("Auto-prompt: clicked YES -> timer started")
                finally:
                    self._auto_prompt_open = False
                    self._auto_prompt_box = None
                    box.close()

            def on_no():
                try:
                    if self._auto_prompt_retries < max_retries:
                        self._auto_prompt_retries += 1
                        self._auto_prompt_pending = True
                        self.logger.info("Auto-prompt: clicked NO -> schedule retry in %ss" % retry_sec)
                        QtCore.QTimer.singleShot(max(0, retry_sec) * 1000, self._auto_prompt_after_delay)
                    else:
                        self.logger.info("Auto-prompt: clicked NO -> snooze %s min" % snooze_min)
                        self._next_auto_prompt_ts = time.time() + snooze_min * 60
                finally:
                    self._auto_prompt_open = False
                    self._auto_prompt_box = None
                    box.close()

            yes_btn.clicked.connect(on_yes)
            no_btn.clicked.connect(on_no)
            box.show()
            box.raise_()
            box.activateWindow()
            # Принудительный TOPMOST через WinAPI (поверх полноэкранных окон)
            try:
                import win32gui, win32con  # type: ignore
                hwnd = int(box.winId())
                win32gui.SetWindowPos(
                    hwnd,
                    win32con.HWND_TOPMOST,
                    0, 0, 0, 0,
                    win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
                )
            except Exception:
                pass
            # Центрирование диалога по активному экрану (под курсором), с учетом DPI
            try:
                pos = QtGui.QCursor.pos()
                screen = None
                if hasattr(QtWidgets.QApplication, 'screenAt'):
                    screen = QtWidgets.QApplication.screenAt(pos)
                if screen is None:
                    # Фоллбек: найти экран, который содержит курсор
                    for s in QtWidgets.QApplication.screens():
                        if s.geometry().contains(pos):
                            screen = s
                            break
                if screen is None:
                    screen = QtWidgets.QApplication.primaryScreen()
                if screen:
                    box.adjustSize()
                    geo = screen.availableGeometry()
                    bx = box.frameGeometry()
                    bx.moveCenter(geo.center())
                    box.move(bx.topLeft())
            except Exception:
                pass

            # Таймаут авто-повтора при отсутствии ответа
            def on_timeout():
                try:
                    if not self._auto_prompt_open or not box.isVisible():
                        return
                    # Проверим актуальность условий (с защитой от флапа первые 3с)
                    if (time.time() - shown_at) >= 3:
                        if self.is_in_rest():
                            self.logger.info("Auto-prompt timeout: conditions invalidated -> rest active")
                            self._auto_prompt_retries = 0
                            return
                        if not self.process_manager.is_any_monitored_process_running():
                            self.logger.info("Auto-prompt timeout: conditions invalidated -> game closed")
                            self._auto_prompt_retries = 0
                            return
                        if self.timer_manager.is_running():
                            self.logger.info("Auto-prompt timeout: conditions invalidated -> timer already running")
                            self._auto_prompt_retries = 0
                            return
                    if self._auto_prompt_retries < max_retries:
                        self._auto_prompt_retries += 1
                        self._auto_prompt_open = False
                        self._auto_prompt_box = None
                        box.close()
                        self._auto_prompt_pending = True
                        self.logger.info("Auto-prompt timeout: schedule retry in %ss (retry #%s)" % (retry_sec, self._auto_prompt_retries))
                        QtCore.QTimer.singleShot(max(0, retry_sec) * 1000, self._auto_prompt_after_delay)
                    else:
                        self._auto_prompt_open = False
                        self._auto_prompt_box = None
                        box.close()
                        self.logger.info("Auto-prompt timeout: snooze %s min" % snooze_min)
                        self._next_auto_prompt_ts = time.time() + snooze_min * 60
                except Exception:
                    pass

            QtCore.QTimer.singleShot(max(1, timeout_sec) * 1000, on_timeout)
        except Exception as e:
            self.logger.error(f"Ошибка авто-приглашения к запуску таймера: {e}")

    def _format_mmss(self, total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        m = total_seconds // 60
        s = total_seconds % 60
        return f"{m:02d}:{s:02d}"

    def _update_pre_expiry_toast(self):
        """Показывает/скрывает плашку внизу справа, когда до конца осталось <= порога."""
        try:
            if self.is_in_rest():
                self.pre_expiry_toast.hide_toast()
                return
            if self._active_limit_warning_text:
                self.pre_expiry_toast.show_text(
                    self._active_limit_warning_text
                )
                return
            if not self.timer_manager.is_running():
                self.pre_expiry_toast.hide_toast()
                return
            if self.timer_manager.get_mode() != 'countdown':
                self.pre_expiry_toast.hide_toast()
                return
            remaining = int(getattr(self.timer_manager, 'remaining_time', 0) or 0)
            if remaining <= 0 or self.timer_manager.is_expired():
                self.pre_expiry_toast.hide_toast()
                return
            threshold = int(self.settings.get('pre_expiry_toast_seconds', 300) or 300)
            if remaining <= threshold:
                text = f"Скоро закончится время: {self._format_mmss(remaining)}"
                self.pre_expiry_toast.show_text(text)
            else:
                self.pre_expiry_toast.hide_toast()
        except Exception:
            # Не мешаем основному циклу
            pass

    def pause_timer(self): self.timer_manager.pause_timer()
    def reset_timer(self): 
        self.timer_manager.reset_timer()
        # Сброс флага истечения таймера
        self.game_blocker.update_timer_state(False)
        # Сброс флага ручного запуска
        self.manual_start = False
        # Сброс грайса
        self._expire_grace_used = False
        self._block_dismissed_until_game_exit = False
        # Остановка таймера проверки после уведомления и сброс метки показа уведомления
        if hasattr(self, 'post_notification_timer'):
            self.post_notification_timer.stop()
        if hasattr(self, 'notification_shown'):
            del self.notification_shown

    def reset_all_data(self):
        """Полный сброс статистики и пользовательских данных (для тестирования)."""
        try:
            # Подтверждение
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            box.setWindowTitle('Сброс данных')
            box.setText('Сбросить статистику, достижения и таймер? Это действие нельзя отменить.')
            box.setStandardButtons(
                QtWidgets.QMessageBox.StandardButton.Yes
                | QtWidgets.QMessageBox.StandardButton.No
            )
            box.setDefaultButton(QtWidgets.QMessageBox.StandardButton.No)
            box.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
            box.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
            box.activateWindow(); box.raise_()
            if box.exec() != QtWidgets.QMessageBox.StandardButton.Yes:
                return

            # 1) Остановить и сбросить таймер/флаги
            try:
                self.timer_manager.pause_timer()
            except Exception:
                pass
            self.reset_timer()
            self._reset_play_since_rest()
            self._next_auto_prompt_ts = 0.0
            self._expire_grace_used = False
            self.rest_reason = None

            # 2) Снять перерыв и очистить в настройках
            self.rest_until = None
            try:
                self.settings.set('rest_until', '')
            except Exception:
                pass

            # 3) Удалить БД статистики использования
            try:
                self.process_manager.reset_usage_data()
            except Exception as e:
                self.logger.error(f"Ошибка удаления БД статистики: {e}")

            # 4) Сбросить достижения и их статистику
            try:
                self.settings.set('achievements', {})
                self.settings.set('achievement_stats', {})
                self.settings.save()
                # Переинициализировать менеджер достижений
                self.achievement_manager = AchievementManager(self.settings, notification_callback=self.tray_manager.show_message)
            except Exception as e:
                self.logger.error(f"Ошибка сброса достижений: {e}")

            # 5) Обновить UI
            try:
                self.gui_manager.set_rest_info("", False)
                self.update_stats()
                self.check_achievements()
            except Exception:
                pass

            # 6) Сообщение пользователю
            try:
                self.tray_manager.show_message('Сброс', 'Статистика и данные сброшены')
            except Exception:
                pass

            self.logger.info("Выполнен полный сброс статистики и данных")
        except Exception as e:
            self.logger.error(f"Ошибка полного сброса данных: {e}")

    def check_activity(self):
        """Проверяет активность пользователя и при необходимости ставит таймер на паузу."""
        try:
            is_active, _ = self.activity_monitor.check_activity()
            if not is_active and self.timer_manager.is_running():
                self.timer_manager.pause_timer()
                self.logger.info("Таймер поставлен на паузу из-за неактивности пользователя.")
        except Exception as e:
            self.logger.error(f"Ошибка при проверке активности: {e}")

    def start_timer_from_ui(self):
        """Запускает таймер с параметрами, установленными в UI."""
        try:
            # Запрет запуска таймера во время перерыва
            if self.is_in_rest():
                self._notify_rest()
                return
            mode_text = self.gui_manager.mode.currentText()
            mode = 'countdown' if 'Обратный' in mode_text else 'countup'
            if mode == 'countdown':
                h = int(self.gui_manager.hours.text() or 0)
                m = int(self.gui_manager.minutes.text() or 0)
                s = int(self.gui_manager.seconds.text() or 0)
                if not self.timer_manager.start_timer(
                    h * 3600 + m * 60 + s, mode
                ):
                    return
                self.achievement_manager.on_timer_start()
                self._block_dismissed_until_game_exit = False
                self.logger.info(f"Игра запущена, таймер запущен в режиме countdown на {h:02d}:{m:02d}:{s:02d}.")
            else:
                if not self.timer_manager.start_timer(0, mode):
                    return
                self.achievement_manager.on_timer_start()
                self._block_dismissed_until_game_exit = False
                self.logger.info("Игра запущена, таймер запущен в режиме countup.")
        except Exception as e:
            self.logger.error(f"Ошибка при запуске таймера из UI: {e}")

    def _autocountup_monitor(self):
        """Мониторинг процессов для авто-таймера"""
        block_screen = getattr(
            getattr(self, 'game_blocker', None), 'block_screen', None
        )
        warning_active = (
            hasattr(self, 'notification_shown')
            or (
                hasattr(self, 'post_notification_timer')
                and self.post_notification_timer.isActive()
            )
            or (block_screen is not None and block_screen.isVisible())
        )
        any_game_running = self.process_manager.is_any_monitored_process_running(
            force_refresh=warning_active
        )
        timer_running = self.timer_manager.is_running()
        is_countup = self.timer_manager.get_mode() == 'countup'

        if not any_game_running:
            self._cancel_game_warning()
            if self.game_blocker.unblock():
                self.logger.info("Игра закрыта — окно блокировки снято.")
            self._block_dismissed_until_game_exit = False
            self._expire_grace_used = False
            if (
                timer_running
                and is_countup
                and not self.manual_start
            ):
                self.timer_manager.pause_timer()
                self.logger.info("Все игры закрыты, авто-таймер на паузе.")
            return

        if self._block_dismissed_until_game_exit:
            return
        
        # Проверяем, не истек ли таймер
        timer_expired = self.timer_manager.is_expired()
        
        # Если таймер уже истек ранее и «грайс» использован — сразу блокируем без уведомления
        if any_game_running and timer_expired and getattr(self, '_expire_grace_used', False):
            try:
                self.logger.info("Таймер просрочен, повторный запуск игры — немедленная блокировка.")
                self._hide_countdown_overlay()
                self.game_blocker.update_timer_state(True)
                self.game_blocker.start_blocking_sequence()
                return
            except Exception:
                pass

        # Если таймер истек, но игра все еще запущена, показываем уведомление
        if any_game_running and timer_expired and not hasattr(self, 'notification_shown'):
            self.notification_window = NotificationWindow(
                message="Время истекло!\nТы молодец, пора сделать перерыв.",
                on_close_callback=self._on_notification_closed
            )
            self.notification_window.show(duration=0)
            # Достижения: показ уведомления
            try:
                self.achievement_manager.on_notification_shown()
            except Exception:
                pass
            self.notification_shown = True
            # Запускаем единый grace-период: показываем оверлей отсчета и планируем единственную проверку
            self._start_grace_period()
    def _cancel_game_warning(self):
        """Stops the grace countdown and notification once all monitored games exit."""
        timer = getattr(self, 'post_notification_timer', None)
        if timer is not None and timer.isActive():
            timer.stop()
        if hasattr(self, 'notification_shown'):
            delattr(self, 'notification_shown')
        notification = getattr(self, 'notification_window', None)
        if notification is not None and notification.isVisible():
            notification.accept()
        self._hide_countdown_overlay()

    def _on_notification_closed(self):
        """Callback when notification window is closed by user. В едином сценарии ничего не
        пере-планируем: проверка уже назначена на момент показа уведомления."""
        try:
            pass
        except Exception as e:
            self.logger.error(f"Ошибка в _on_notification_closed: {e}")

    def _check_game_after_notification(self):
        """Проверяет, завершена ли игра по окончании grace-периода после уведомления"""
        try:
            any_game_running = (
                self.process_manager.is_any_monitored_process_running(
                    force_refresh=True
                )
            )
            if any_game_running:
                self.logger.info("Игра не завершена в течение grace-периода после уведомления. Запускаем блокировку.")
                self._hide_countdown_overlay()
                # Отмечаем, что grace уже был использован — повторные попытки запустить игру будут блокироваться сразу
                self._expire_grace_used = True
                self.game_blocker.update_timer_state(True)
                self.game_blocker.start_blocking_sequence()
                # Ачивки: зафиксировать принудительную блокировку
                try:
                    self.achievement_manager.on_forced_block()
                except Exception:
                    pass
                # Устанавливаем обязательный перерыв после принудительной блокировки
                if self.settings.get('enforce_cooldown_between_sessions', True):
                    minutes = int(self.settings.get('enforced_rest_minutes', 60) or 60)
                    self.start_rest(minutes)
            else:
                self.logger.info("Игра завершена в течение grace-периода после уведомления.")
                self._hide_countdown_overlay()
                # Достижения: сделал перерыв вовремя
                try:
                    self.achievement_manager.on_break_taken()
                    # Обновить UI вкладки достижений
                    self.gui_manager.refresh_achievements(self.achievement_manager)
                except Exception:
                    pass
            # Сбрасываем флаг, чтобы следующее истечение снова показало уведомление
            if hasattr(self, 'notification_shown'):
                delattr(self, 'notification_shown')
        except Exception as e:
            self.logger.error(f"Ошибка в _check_game_after_notification: {e}")

    # --- Единый сценарий grace-периода после уведомления ---
    def _start_grace_period(self):
        try:
            delay_ms = int(self.settings.get('notification_check_delay_ms', 10000) or 10000)
            grace_sec = max(0, delay_ms // 1000)
            # Показать поверх игры визуальный обратный отсчет на весь grace-период
            self._hide_countdown_overlay()
            self._show_countdown_overlay(grace_sec)
            # Перепланировать одиночную проверку
            try:
                if hasattr(self, 'post_notification_timer') and self.post_notification_timer:
                    self.post_notification_timer.stop()
            except Exception:
                pass
            self.post_notification_timer = QtCore.QTimer(self)
            self.post_notification_timer.setSingleShot(True)
            self.post_notification_timer.timeout.connect(self._check_game_after_notification)
            self.post_notification_timer.start(delay_ms)
            # Сноузим авто-диалоги на время grace-периода
            try:
                self._auto_prompt_pending = False
                self._auto_prompt_retries = 0
                self._next_auto_prompt_ts = time.time() + grace_sec + 2
            except Exception:
                pass
            self.logger.info(f"Grace-период запущен на {grace_sec} сек")
        except Exception as e:
            self.logger.error(f"Не удалось запустить grace-период: {e}")

    def check_achievements(self):
        """Проверяет ежедневные достижения при запуске."""
        self.achievement_manager.on_daily_check()
        self.achievement_manager.check_time_achievements()
        try:
            self.gui_manager.refresh_achievements(self.achievement_manager)
        except Exception:
            pass

    # --- Перерывы (rest/cooldown) ---
    def is_in_rest(self) -> bool:
        try:
            return bool(self.rest_until and datetime.now() < self.rest_until)
        except Exception:
            return False

    def _set_rest_until(self, until_dt: datetime):
        try:
            self.rest_until = until_dt
            self.settings.set('rest_until', until_dt.isoformat())
        except Exception as e:
            self.logger.error(f"Не удалось сохранить rest_until: {e}")

    def start_rest(self, minutes: int):
        try:
            minutes = int(minutes or 0)
            if minutes <= 0:
                return
            self._session_limit_warning_shown = False
            self._active_limit_warning_text = None
            self._reset_play_since_rest()
            self._set_rest_until(datetime.now() + timedelta(minutes=minutes))
            self.rest_reason = 'cooldown'
            self._notify_rest(initial=True)
        except Exception as e:
            self.logger.error(f"Ошибка запуска перерыва: {e}")

    def start_rest_until(self, until_dt: datetime):
        try:
            self._session_limit_warning_shown = False
            self._active_limit_warning_text = None
            self._reset_play_since_rest()
            self._set_rest_until(until_dt)
            self._notify_rest(initial=True)
        except Exception as e:
            self.logger.error(f"Ошибка установки перерыва до даты: {e}")

    def clear_rest_if_elapsed(self):
        try:
            if self.rest_until and datetime.now() >= self.rest_until:
                self.rest_until = None
                self.settings.set('rest_until', "")
        except Exception as e:
            self.logger.error(f"Ошибка очистки перерыва: {e}")

    def rest_remaining_str(self) -> str:
        try:
            if not self.is_in_rest():
                return "00:00"
            delta = self.rest_until - datetime.now()
            total = int(delta.total_seconds())
            if total < 0:
                total = 0
            h = total // 3600
            m = (total % 3600) // 60
            s = total % 60
            if h > 0:
                return f"{h:02d}:{m:02d}:{s:02d}"
            return f"{m:02d}:{s:02d}"
        except Exception:
            return "00:00"

    def _notify_rest(self, initial: bool = False):
        try:
            now_ts = time.time()
            # Не спамим уведомления чаще, чем раз в 15 секунд, если это не первичное уведомление
            if not initial and (now_ts - self._last_rest_notice_ts) < 15:
                return
            self._last_rest_notice_ts = now_ts
            remaining = self.rest_remaining_str()
            title = "Перерыв"
            if self.rest_reason == 'limit':
                title = "Дневной лимит исчерпан — до завтра"
            self.tray_manager.show_message(title, f"Осталось: {remaining}")
        except Exception:
            pass

    def _notify_daily_limit_exceeded(self):
        try:
            remaining = self.rest_remaining_str()
            self.tray_manager.show_message("Дневной лимит исчерпан — до завтра", f"Осталось до 00:00: {remaining}")
        except Exception:
            pass

    def _account_active_usage(self):
        """Accounts time only while a monitored game's window is in the foreground."""
        try:
            now = time.monotonic()
            elapsed = now - self._last_usage_account_ts
            self._last_usage_account_ts = now
            max_interval = max(
                1,
                int(self.settings.get('periodic_tasks_interval_ms', 1000) / 1000)
            )
            duration = min(max_interval, int(elapsed))
            if duration <= 0:
                return
            active = set(self.process_manager.get_active_processes())
            monitored = {
                os.path.basename(name.strip()).lower()
                for name in (self.process_manager.get_monitored_processes() or [])
                if isinstance(name, str) and name.strip()
            }
            foreground = (
                self.process_manager.get_foreground_process_name() or ""
            )
            foreground = os.path.basename(foreground).lower()
            if foreground not in active or foreground not in monitored:
                return
            self.process_manager.record_active_processes({foreground}, duration)
            self._account_play_session({foreground}, duration)
        except Exception as e:
            self.logger.error(f"Ошибка учёта времени активных игр: {e}")

    def _daily_limit_hours_for_weekday(self, weekday):
        limits = self.settings.get('daily_limits_by_weekday', {})
        if isinstance(limits, dict):
            value = limits.get(str(weekday), limits.get(weekday))
            if value is not None:
                try:
                    return min(24.0, max(0.0, float(value)))
                except (TypeError, ValueError):
                    self.logger.warning(
                        f"Некорректный дневной лимит для дня недели {weekday}"
                    )
        legacy_seconds = self.settings.get('daily_limit_seconds')
        try:
            if legacy_seconds is not None:
                return min(24.0, max(0.0, float(legacy_seconds) / 3600))
            legacy_hours = self.settings.get('daily_limit_hours', 6)
            return min(24.0, max(0.0, float(legacy_hours)))
        except (TypeError, ValueError):
            self.logger.warning("Некорректный общий дневной лимит; используется 6 часов")
            return 6.0

    def _daily_limit_seconds_for_today(self):
        return int(round(
            self._daily_limit_hours_for_weekday(datetime.now().weekday()) * 3600
        )) + self._parent_extension_seconds_today("daily_seconds")

    def _parent_extension_seconds_today(self, field="daily_seconds"):
        extension = self.settings.get('parent_extension', {})
        today = date.today().isoformat()
        if not isinstance(extension, dict) or extension.get('date') != today:
            return 0
        try:
            return max(0, int(extension.get(field, 0)))
        except (TypeError, ValueError):
            self.logger.warning("Некорректное значение родительского продления")
            return 0

    def _check_limit_warnings(self, today_used):
        try:
            warning_seconds = max(
                0, int(self.settings.get('limit_warning_seconds', 300) or 0)
            )
            if warning_seconds <= 0:
                return

            if self.settings.get('enforce_play_session_limit', True):
                session_limit = (
                    int(float(self.settings.get('play_session_limit_hours', 2) or 0) * 3600)
                    + self._parent_extension_seconds_today("session_seconds")
                )
                session_remaining = session_limit - self._play_since_rest_seconds
                if (
                    0 < session_remaining <= warning_seconds
                    and not self._session_limit_warning_shown
                ):
                    minutes_left = max(1, (session_remaining + 59) // 60)
                    warning_text = (
                        f"Перерыв начнётся примерно через {minutes_left} мин. "
                        "Сохрани игру."
                    )
                    self.tray_manager.show_message(
                        "Скоро перерыв",
                        warning_text,
                        QtWidgets.QSystemTrayIcon.MessageIcon.Warning,
                        10000,
                    )
                    self._active_limit_warning_text = warning_text
                    self._session_limit_warning_shown = True

            today_key = date.today().isoformat()
            daily_remaining = self.daily_limit_seconds - int(today_used)
            if (
                self.settings.get('block_until_next_day_on_limit', True)
                and 0 < daily_remaining <= warning_seconds
                and self._daily_limit_warning_date != today_key
            ):
                minutes_left = max(1, (daily_remaining + 59) // 60)
                warning_text = (
                    f"Дневной лимит закончится примерно через {minutes_left} мин. "
                    "Сохрани игру."
                )
                self.tray_manager.show_message(
                    "Скоро дневной лимит",
                    warning_text,
                    QtWidgets.QSystemTrayIcon.MessageIcon.Warning,
                    10000,
                )
                self._active_limit_warning_text = warning_text
                self._daily_limit_warning_date = today_key
        except Exception as e:
            self.logger.error(f"Ошибка проверки предупреждений лимитов: {e}")

    def grant_parent_extension(self, minutes):
        minutes = int(minutes)
        if minutes not in {15, 30, 60}:
            self.logger.error(f"Недопустимая длительность продления: {minutes}")
            return False

        today = date.today().isoformat()
        previous_extension = self.settings.get('parent_extension', {})
        current_daily_seconds = self._parent_extension_seconds_today("daily_seconds")
        current_session_seconds = self._parent_extension_seconds_today("session_seconds")
        updated = {
            "date": today,
            "daily_seconds": current_daily_seconds + minutes * 60,
            "session_seconds": current_session_seconds + minutes * 60,
        }
        if not self.settings.set('parent_extension', updated):
            self.logger.error("Не удалось сохранить родительское продление")
            return False

        self.daily_limit_seconds = self._daily_limit_seconds_for_today()
        if self.is_in_rest():
            if not self.settings.set('rest_until', ''):
                if not self.settings.set('parent_extension', previous_extension):
                    self.logger.error(
                        "Не удалось откатить продление после ошибки сохранения rest_until"
                    )
                self.logger.error("Не удалось снять сохранённый перерыв")
                return False
            self.rest_until = None
            self.rest_reason = None
        if hasattr(self, 'game_blocker'):
            self.game_blocker.unblock()
        self._block_dismissed_until_game_exit = False
        if hasattr(self, 'timer_manager') and self.timer_manager.is_expired():
            self.timer_manager.reset_timer()
        self._session_limit_warning_shown = False
        self._active_limit_warning_text = None
        self.update_stats()
        self.tray_manager.show_message(
            "Родительское продление",
            f"Добавлено {minutes} минут игрового времени на сегодня.",
            QtWidgets.QSystemTrayIcon.MessageIcon.Information,
            8000,
        )
        self.logger.info(
            f"Родитель добавил {minutes} минут игрового времени на {today}"
        )
        return True

    def show_parent_controls(self):
        if self._parent_controls_dialog is not None:
            self._parent_controls_dialog.raise_()
            self._parent_controls_dialog.activateWindow()
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Родительское управление")
        dialog.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(QtWidgets.QLabel(
            "Разовое продление действует только до конца сегодняшнего дня "
            "и не меняет обычное расписание."
        ))

        for minutes in (15, 30, 60):
            button = QtWidgets.QPushButton(f"Продлить на {minutes} минут")
            button.clicked.connect(
                lambda _checked=False, amount=minutes: self._apply_parent_extension(
                    dialog, amount
                )
            )
            layout.addWidget(button)

        blocker = getattr(self, 'game_blocker', None)
        screen = getattr(blocker, 'block_screen', None)
        if screen is not None and screen.isVisible():
            dismiss_button = QtWidgets.QPushButton(
                "Снять текущую блокировку до закрытия игры"
            )
            dismiss_button.clicked.connect(
                lambda: self._dismiss_current_block(dialog)
            )
            layout.addWidget(dismiss_button)

        close_button = QtWidgets.QPushButton("Закрыть")
        close_button.clicked.connect(dialog.close)
        layout.addWidget(close_button)
        dialog.finished.connect(
            lambda: setattr(self, '_parent_controls_dialog', None)
        )
        self._parent_controls_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _apply_parent_extension(self, dialog, minutes):
        if self.grant_parent_extension(minutes):
            dialog.close()

    def _dismiss_current_block(self, dialog):
        self._unblock_and_suppress_until_game_exit()
        dialog.close()

    def _account_play_session(self, running_processes, duration):
        if (
            not self.settings.get('enforce_play_session_limit', True)
            or not running_processes
            or duration <= 0
            or self.is_in_rest()
        ):
            return

        limit_hours = float(self.settings.get('play_session_limit_hours', 2) or 0)
        limit_seconds = (
            int(limit_hours * 3600)
            + self._parent_extension_seconds_today("session_seconds")
        )
        if limit_seconds <= 0:
            return

        self._play_since_rest_seconds += duration
        self._session_progress_dirty = True
        if self._play_since_rest_seconds >= limit_seconds:
            minutes = max(
                1,
                int(self.settings.get('enforced_rest_minutes', 60) or 60),
            )
            self.logger.info(
                f"Игровой лимит {limit_hours:g} ч достигнут; "
                f"начинается перерыв на {minutes} мин."
            )
            self.start_rest(minutes)
            return

        if time.monotonic() - self._last_session_progress_save_ts >= 60:
            self._persist_play_since_rest()

    def _persist_play_since_rest(self):
        if not self._session_progress_dirty:
            return
        if not self.settings.set(
            'play_since_rest_seconds', self._play_since_rest_seconds
        ):
            self.logger.error("Не удалось сохранить время игры после перерыва")
            return
        self._session_progress_dirty = False
        self._last_session_progress_save_ts = time.monotonic()

    def _reset_play_since_rest(self):
        self._play_since_rest_seconds = 0
        self._session_progress_dirty = True
        self._persist_play_since_rest()
        extension = self.settings.get('parent_extension', {})
        if (
            isinstance(extension, dict)
            and extension.get('date') == date.today().isoformat()
            and extension.get('session_seconds', 0)
        ):
            extension = dict(extension)
            extension['session_seconds'] = 0
            if not self.settings.set('parent_extension', extension):
                self.logger.error(
                    "Не удалось очистить продление текущего цикла игры"
                )

    def _shutdown(self):
        """Flushes pending usage records and unregisters global hotkeys."""
        try:
            self.hotkey_manager.stop()
            self._persist_play_since_rest()
            self.process_manager.flush_pending_usage()
        except Exception as e:
            self.logger.error(f"Ошибка завершения приложения: {e}")

    # --- Overlay helpers ---
    def _show_countdown_overlay(self, seconds: int):
        try:
            secs = int(seconds or 0)
            if secs <= 0:
                return
            self.countdown_overlay.start(secs)
        except Exception as e:
            self.logger.error(f"Не удалось показать оверлей обратного отсчета: {e}")


    def _hide_countdown_overlay(self):
        try:
            self.countdown_overlay.stop()
        except Exception:
            pass

    def update_stats(self):
        try:
            today = self.process_manager.get_daily_usage()
            week = self.process_manager.get_weekly_usage()
            self.daily_limit_seconds = self._daily_limit_seconds_for_today()
            left = max(0, self.daily_limit_seconds - today)
            limit = self.daily_limit_seconds
            self.gui_manager.stats_today.setText(
                f"Сегодня: {today//3600:02d}:{(today%3600)//60:02d}:{today%60:02d} "
                f"/ лимит {limit//3600:02d}:{(limit%3600)//60:02d}"
            )
            self.gui_manager.stats_left.setText(f"Осталось: {left//3600:02d}:{(left%3600)//60:02d}:{left%60:02d}")
            self.gui_manager.stats_week.setText(f"За неделю: {week//3600:02d}:{(week%3600)//60:02d}:{week%60:02d}")
            self.update_play_session_progress()
            # Обновить пер-игровую таблицу и достижения
            self.gui_manager.update_per_game_stats(self.process_manager, period='today')
            self.gui_manager.refresh_achievements(self.achievement_manager)
        except Exception as e:
            self.logger.error(f"Ошибка обновления статистики: {e}")

    def update_play_session_progress(self):
        label = self.gui_manager.play_session_progress_label
        bar = self.gui_manager.play_session_progress_bar
        if not self.settings.get('enforce_play_session_limit', True):
            label.setText("Обязательные перерывы отключены")
            bar.setValue(0)
            return

        limit_seconds = int(
            float(self.settings.get('play_session_limit_hours', 2) or 0) * 3600
        )
        if limit_seconds <= 0:
            label.setText("Лимит до перерыва должен быть больше нуля")
            bar.setValue(0)
            return

        if self.is_in_rest():
            label.setText(f"Перерыв: осталось {self.rest_remaining_str()}")
            bar.setValue(1000)
            return

        played = min(self._play_since_rest_seconds, limit_seconds)
        bar.setValue(int(played * 1000 / limit_seconds))
        label.setText(
            f"До перерыва: {self._format_duration(played)} из "
            f"{self._format_duration(limit_seconds)}"
        )

    @staticmethod
    def _format_duration(total_seconds):
        total_minutes = max(0, int(total_seconds)) // 60
        hours, minutes = divmod(total_minutes, 60)
        if hours:
            return f"{hours} ч {minutes:02d} мин"
        return f"{minutes} мин"

    def _init_hotkeys(self):
        dispatch = self.hotkey_dispatcher.dispatch
        # Встроенные хоткеи изменения лимита и разблокировки (оставляем)
        self.hotkey_manager.register_limit_hotkeys(
            lambda: dispatch(self.increase_daily_limit),
            lambda: dispatch(self.decrease_daily_limit)
        )
        self.hotkey_manager.register_blocker_hotkey(
            lambda: dispatch(self.show_parent_controls)
        )

        # Регистрация хоткеев из настроек
        self.hotkey_manager.register_from_settings(
            self.settings,
            callbacks={
                "start": lambda: dispatch(self.start_timer),
                "pause_resume": lambda: dispatch(self.pause_resume),
                "reset": lambda: dispatch(self.reset_timer),
                "add_5_min": lambda: dispatch(self.add_5_minutes),
                "add_30_min": lambda: dispatch(self.add_30_minutes),
            }
        )

    def pause_resume(self):
        """Тоггл паузы/продолжения для хоткея."""
        self.timer_manager.toggle_pause()

    def _unblock_and_suppress_until_game_exit(self):
        """Unblocks once and avoids immediately reopening while the same game remains."""
        if self.game_blocker.unblock():
            self._block_dismissed_until_game_exit = True

    def add_5_minutes(self):
        """Быстро добавляет +5 минут к таймеру (если запущен)."""
        self.timer_manager.add_minutes(5)

    def add_30_minutes(self):
        """Быстро добавляет +30 минут к таймеру (если запущен)."""
        self.timer_manager.add_minutes(30)

    def increase_daily_limit(self):
        self._adjust_today_daily_limit(600)

    def decrease_daily_limit(self):
        self._adjust_today_daily_limit(-600)

    def _adjust_today_daily_limit(self, delta_seconds):
        weekday = datetime.now().weekday()
        limits = self.settings.get('daily_limits_by_weekday', {})
        limits = dict(limits) if isinstance(limits, dict) else {}
        hours = self._daily_limit_hours_for_weekday(weekday)
        limits[str(weekday)] = min(
            24.0, max(0.0, hours + delta_seconds / 3600)
        )
        if not self.settings.set('daily_limits_by_weekday', limits):
            self.logger.error("Не удалось сохранить дневной лимит")
            return
        self.daily_limit_seconds = self._daily_limit_seconds_for_today()
        if hasattr(self.gui_manager, "daily_limit_spins"):
            spin = self.gui_manager.daily_limit_spins.get(weekday)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(limits[str(weekday)])
                spin.blockSignals(False)
        self.update_stats()

    def show_main_window(self):
        """Показывает главное окно приложения."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self):
        """Корректно завершает работу приложения."""
        self.tray_manager.tray_icon.hide()
        self.app.quit()

    def closeEvent(self, event): self.hide(); event.ignore()

    def apply_preset(self, hours, minutes, seconds):
        self.gui_manager.hours.setText(str(hours))
        self.gui_manager.minutes.setText(str(minutes))
        self.gui_manager.seconds.setText(str(seconds))

if __name__ == "__main__":
    # Гарантия единственного экземпляра через именованный mutex
    _mutex_handle, _acquired = _acquire_single_instance_mutex()
    if not _acquired:
        try:
            ctypes.windll.user32.MessageBoxW(
                None,
                "Приложение уже запущено.",
                "Game Timer",
                0x10  # MB_ICONHAND
            )
        except Exception:
            pass
        sys.exit(0)

    app = QtWidgets.QApplication(sys.argv)
    if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        QtWidgets.QMessageBox.critical(None, "Критическая ошибка", "Системный трей не поддерживается.")
        sys.exit(1)
    app.setQuitOnLastWindowClosed(False)
    window = GameTimerApp(app)
    if not window.settings.get('start_minimized', False):
        window.show()
    try:
        rc = app.exec()
    finally:
        try:
            if _mutex_handle:
                ctypes.windll.kernel32.CloseHandle(_mutex_handle)
        except Exception:
            pass
    sys.exit(rc)
