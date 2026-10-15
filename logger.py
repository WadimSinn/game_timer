"""
Файл: logger.py

Модуль-обёртка для логирования событий приложения Game Timer.
"""

import logging
import os
from datetime import datetime
import getpass
import sys
import uuid
import json
from logging.handlers import RotatingFileHandler
from app_paths import get_data_path

# Генерируем session_id при первом импорте
SESSION_ID = uuid.uuid4().hex[:8]
USER = getpass.getuser()
PID = os.getpid()

class ContextFormatter(logging.Formatter):
    def format(self, record):
        record.user = USER
        record.pid = PID
        record.session = SESSION_ID
        record.func = record.funcName
        record.lineno = record.lineno
        return super().format(record)

class Logger:
    def __init__(self, name="game_timer", log_file=None):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # Close prior handlers before replacing them; each owns an open log file.
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()
        
        # Загружаем конфиг логирования напрямую из settings.json (без импорта SettingsManager)
        cfg = self._load_logging_config()

        # Создаем директорию для логов если её нет
        log_dir = cfg.get("log_dir", "logs")
        if not os.path.isabs(log_dir):
            log_dir = os.path.join(os.path.dirname(get_data_path("settings.json")), log_dir)
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Определяем путь к лог-файлу
        if log_file is None:
            log_file = os.path.join(log_dir, cfg.get("log_file", "game_timer.log"))
        elif not os.path.isabs(log_file):
            log_file = os.path.join(log_dir, os.path.basename(log_file))

        # Уровни
        file_level = getattr(logging, str(cfg.get("file_level", "DEBUG")).upper(), logging.DEBUG)
        console_level = getattr(logging, str(cfg.get("console_level", "WARNING")).upper(), logging.WARNING)

        # Rotating file handler
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=int(cfg.get("max_bytes", 1_000_000)),
            backupCount=int(cfg.get("backup_count", 5)),
            encoding='utf-8'
        )
        file_handler.setLevel(file_level)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(console_level)
        
        # Формат логов
        fmt = (
            "%(asctime)s | user=%(user)s | pid=%(pid)s | session=%(session)s | "
            "%(name)s.%(func)s:%(lineno)d | %(levelname)s | %(message)s"
        )
        formatter = ContextFormatter(fmt)
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def _load_logging_config(self):
        """Читает настройки логирования из settings.json, возвращает dict лог-конфига."""
        try:
            settings_path = get_data_path('settings.json')
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data.get('logging', {}) or {}
        except Exception:
            # В случае любой ошибки используем значения по умолчанию ниже
            pass
        return {
            "file_level": "DEBUG",
            "console_level": "WARNING",
            "max_bytes": 1_000_000,
            "backup_count": 5,
            "log_dir": "logs",
            "log_file": "game_timer.log",
        }

    def debug(self, message):
        self.logger.debug(message, stacklevel=2)

    def info(self, message):
        self.logger.info(message, stacklevel=2)

    def warning(self, message):
        self.logger.warning(message, stacklevel=2)

    def error(self, message, exc_info=True):
        self.logger.error(message, exc_info=exc_info, stacklevel=2)

    def critical(self, message, exc_info=True):
        self.logger.critical(message, exc_info=exc_info, stacklevel=2)
