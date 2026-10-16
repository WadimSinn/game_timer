"""
Файл: settings_manager.py

Модуль для загрузки, сохранения и управления настройками пользователя в приложении Game Timer.
"""

import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from logger import Logger
from app_paths import get_data_path

class SettingsManager:
    def __init__(self, filename=None):
        self.filename = filename or get_data_path("settings.json")
        if filename is None:
            legacy_candidates = [
                Path(os.path.dirname(os.path.abspath(self.filename)))
                / "timer_settings.json"
            ]
            if getattr(sys, "frozen", False):
                legacy_candidates.append(
                    Path(sys.executable).resolve().parent / "timer_settings.json"
                )
            else:
                legacy_candidates.append(
                    Path(__file__).resolve().parent / "timer_settings.json"
                )
            self.legacy_candidates = list(dict.fromkeys(legacy_candidates))
        else:
            self.legacy_candidates = [
                Path(os.path.dirname(os.path.abspath(filename)))
                / "timer_settings.json"
            ]
        self.legacy_filename = next(
            (str(path) for path in self.legacy_candidates if path.is_file()),
            str(self.legacy_candidates[0]),
        )
        self._legacy_migration_marker = (
            os.path.abspath(self.filename) + ".legacy-migrated"
        )
        self._old_legacy_markers = [
            str(path) + ".migrated" for path in self.legacy_candidates
        ]
        self.settings = {}
        self.logger = Logger("SettingsManager")
        self.default_settings = {
            "mode": "timer",
            "hours": 2,
            "minutes": 0,
            "processes": ["game.exe", "minecraft.exe", "CorelDRW.exe"],
            "presets": {
                "6 минут": {"hours": 0, "minutes": 6, "seconds": 0},
                "10 минут": {"hours": 0, "minutes": 10},
                "1 час": {"hours": 1, "minutes": 0},
                "2 часа": {"hours": 2, "minutes": 0}
            },
            "theme": "light",
            "check_interval": 5,
            # Интервалы/задержки в миллисекундах
            "periodic_tasks_interval_ms": 1000,
            "process_check_interval_ms": 5000,
            "notification_check_delay_ms": 10000,
            "notification_countdown_seconds": 15,
            "passive_logging_interval_ms": 600000,
            "autostart": False,
            "block_delay": 30,
            "notification_sound": True,
            "start_minimized": False,
            "block_screen_message": "Время игры истекло!\nПожалуйста, сделайте перерыв.",
            # Параметры логирования
            "logging": {
                "file_level": "DEBUG",
                "console_level": "WARNING",
                "max_bytes": 1000000,
                "backup_count": 5,
                "log_dir": "logs",
                "log_file": "game_timer.log"
            },
            # Горячие клавиши
            "hotkeys": {
                "start": "ctrl+alt+s",
                "pause_resume": "ctrl+alt+p",
                "reset": "ctrl+alt+r",
                "add_5_min": "ctrl+alt+plus"
            },
            # Лимиты и перерывы (cooldown)
            "daily_limit_hours": 6,
            "enforced_rest_minutes": 60,
            "enforce_play_session_limit": True,
            "play_session_limit_hours": 2,
            "play_since_rest_seconds": 0,
            "parent_extension": {
                "date": "",
                "daily_seconds": 0,
                "session_seconds": 0,
            },
            "limit_warning_seconds": 300,
            "block_until_next_day_on_limit": True,
            "enforce_cooldown_between_sessions": True,
            # Конец текущего перерыва в ISO-формате (локальное время). Пусто, если перерыва нет
            "rest_until": "",
            # Авто-запуск таймера при обнаружении игры
            "auto_start_on_game_detect": True,
            "auto_start_mode": "countup",  # 'countup' или 'countdown'
            "auto_countdown_seconds": 3600,  # если выбран countdown
            "auto_prompt_text": "Игра обнаружена. Время уже учитывается — не забудь про перерыв.",
            "auto_prompt_dialog_timeout_sec": 8,
            # Подписи к ключевым настройкам (для удобства редактирования в settings.json)
            "settings_descriptions": {
                "mode": "Режим работы таймера: 'timer' — отсчет вниз, может быть и другие режимы при расширении",
                "hours": "Стартовые часы таймера для сессии (целое число)",
                "minutes": "Стартовые минуты таймера для сессии (целое число)",
                "processes": "Список исполняемых файлов игр/приложений для мониторинга (можно добавлять/удалять строки)",
                "presets": "Набор пресетов на главном экране. Можно добавлять/удалять. Формат: имя: {hours, minutes, seconds}",
                "theme": "Тема интерфейса: 'light' или 'dark' (если поддерживается)",
                "check_interval": "Интервал (сек) для некоторых проверок в приложении",
                "periodic_tasks_interval_ms": "Период (мс) запуска фоновых задач UI (1 000 = 1 сек)",
                "process_check_interval_ms": "Период (мс) сканирования запущенных процессов (5 000 = каждые 5 сек)",
                "notification_check_delay_ms": "Через сколько мс после уведомления проверить, закрыта ли игра (по умолчанию 10 000)",
                "notification_countdown_seconds": "Сколько секунд показывать обратный отсчёт перед блокировкой",
                "passive_logging_interval_ms": "Раз в сколько мс писать пассивные записи логов (600 000 = 10 минут)",
                "autostart": "Автозапуск приложения при старте системы (true/false)",
                "hotkeys": "Горячие клавиши приложения. Можно менять сочетания (например 'ctrl+alt+s')",
                "block_delay": "Задержка (сек) перед началом принудительной блокировки после уведомления",
                "notification_sound": "Включить звук уведомления (true/false)",
                "start_minimized": "Запускать свернутым (true/false)",
                "block_screen_message": "Текст сообщения на экране блокировки",
                "daily_limit_hours": "Дневной лимит игрового времени (часы). Пример: 4 или 6",
                "daily_limits_by_weekday": "Дневные лимиты по дням недели, в часах (ключи 0=понедельник ... 6=воскресенье)",
                "enforce_play_session_limit": "Включить обязательный перерыв после заданного времени игры",
                "play_session_limit_hours": "Сколько фактических часов игры можно играть до обязательного перерыва",
                "enforced_rest_minutes": "Длительность обязательного перерыва после лимита игры или принудительной блокировки (минуты). Пример: 60",
                "block_until_next_day_on_limit": "Если true — при достижении дневного лимита блокируем до следующего дня",
                "enforce_cooldown_between_sessions": "Если true — после принудительной блокировки включается перерыв (cooldown)",
                "rest_until": "Техническое поле: время окончания текущего перерыва в ISO-формате. Лучше не менять вручную",
                "auto_start_on_game_detect": "Если true — при запуске отслеживаемой игры таймер включается автоматически",
                "auto_start_mode": "Режим авто-таймера: 'countup' — прямой отсчет, 'countdown' — обратный",
                "auto_countdown_seconds": "Длительность (сек), если выбран режим 'countdown' (по умолчанию 3600 = 1 час)",
                "auto_prompt_text": "Текст уведомления при обнаружении игры",
                "auto_prompt_dialog_timeout_sec": "Через сколько секунд автоматически закрыть уведомление об обнаружении игры"
            }
        }
        self.load()

    def load(self):
        """Загружает настройки из файла"""
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r', encoding='utf-8') as f:
                    self.settings = json.load(f)
                    if not isinstance(self.settings, dict):
                        raise ValueError("Settings root must be a JSON object")
                    self.logger.info("Settings loaded successfully")
            else:
                self.settings = self._convert_sets_to_lists(
                    deepcopy(self.default_settings)
                )
                self.save()
                self.logger.info("Created default settings")
        except json.JSONDecodeError as e:
            self.logger.error(f"Error loading settings: Invalid JSON format. {e}")
            self.settings = self._convert_sets_to_lists(
                deepcopy(self.default_settings)
            )
        except Exception as e:
            self.logger.error(f"Error loading settings: {e}")
            self.settings = self._convert_sets_to_lists(
                deepcopy(self.default_settings)
            )
        self._import_legacy_settings()
        if self.settings.get("auto_prompt_text") == "Обнаружена игра. Начать таймер?":
            self.settings["auto_prompt_text"] = self.default_settings[
                "auto_prompt_text"
            ]
            if not self.save():
                self.logger.error("Could not update the old auto-start prompt text")

    def _import_legacy_settings(self):
        """Merges older timer_settings.json values without overriding current settings."""
        if os.path.exists(self._legacy_migration_marker) or any(
            os.path.exists(marker) for marker in self._old_legacy_markers
        ):
            return
        if not os.path.isfile(self.legacy_filename):
            return
        try:
            with open(self.legacy_filename, "r", encoding="utf-8") as legacy_file:
                legacy = json.load(legacy_file)
            if not isinstance(legacy, dict):
                raise ValueError("Legacy settings root must be a JSON object")

            changed = False
            for key, value in legacy.items():
                if key == "processes" and isinstance(value, list):
                    current = self.settings.get(key, [])
                    if not isinstance(current, list):
                        current = []
                    known = {
                        item.strip().casefold()
                        for item in current
                        if isinstance(item, str)
                    }
                    for item in value:
                        if (
                            isinstance(item, str)
                            and item.strip()
                            and item.strip().casefold() not in known
                        ):
                            current.append(item)
                            known.add(item.strip().casefold())
                            changed = True
                    self.settings[key] = current
                elif key in {"presets", "hotkeys"} and isinstance(value, dict):
                    current = self.settings.get(key, {})
                    if not isinstance(current, dict):
                        current = {}
                    for item_key, item_value in value.items():
                        if item_key not in current:
                            current[item_key] = item_value
                            changed = True
                    self.settings[key] = current
                elif key not in self.settings:
                    self.settings[key] = value
                    changed = True

            if changed and not self.save():
                return
            with open(self._legacy_migration_marker, "w", encoding="utf-8") as marker:
                marker.write(f"Imported {self.legacy_filename}")
            self.logger.info(
                f"Imported legacy settings from {self.legacy_filename}"
            )
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self.logger.error(f"Could not import legacy settings: {e}")

    def save(self):
        """Сохраняет настройки в файл"""
        try:
            # Преобразуем объекты типа set в list перед сохранением
            settings_to_save = self._convert_sets_to_lists(self.settings)
            target = os.path.abspath(self.filename)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode='w',
                    encoding='utf-8',
                    dir=os.path.dirname(target),
                    prefix='.settings-',
                    suffix='.tmp',
                    delete=False
                ) as f:
                    temp_path = f.name
                    json.dump(settings_to_save, f, indent=4, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, target)
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
            self.logger.debug("Settings saved successfully")
            return True
        except Exception as e:
            self.logger.error(f"Error saving settings: {e}")
            return False

    def _convert_sets_to_lists(self, data):
        """Рекурсивно преобразует все объекты типа set в list"""
        if isinstance(data, set):
            return list(data)
        elif isinstance(data, dict):
            return {key: self._convert_sets_to_lists(value) for key, value in data.items()}
        elif isinstance(data, (list, tuple)):
            return [self._convert_sets_to_lists(item) for item in data]
        return data

    def get(self, key, default=None):
        """Получает значение настройки"""
        return self.settings.get(key, default)

    def set(self, key, value):
        """Устанавливает значение настройки"""
        self.settings[key] = value
        return self.save()