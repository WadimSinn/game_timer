"""
Файл: hotkey_manager.py

Модуль для управления глобальными горячими клавишами (hotkeys) в приложении Game Timer.
"""

import keyboard
import logging
from typing import Callable

class HotkeyManager:
    def __init__(self):
        """Инициализация менеджера горячих клавиш"""
        self.logger = logging.getLogger('HotkeyManager')
        self.hotkeys = {}
        self.named_hotkeys = {}  # action_key -> combo
        
    def add_hotkey(self, hotkey: str, callback: Callable):
        """Добавляет горячую клавишу"""
        try:
            keyboard.add_hotkey(hotkey, callback)
            self.hotkeys[hotkey] = callback
            self.logger.info(f"Added hotkey: {hotkey}")
        except Exception as e:
            self.logger.error(f"Failed to add hotkey {hotkey}: {str(e)}")
            
    def remove_hotkey(self, hotkey: str):
        """Удаляет горячую клавишу"""
        try:
            if hotkey in self.hotkeys:
                keyboard.remove_hotkey(hotkey)
                del self.hotkeys[hotkey]
                self.logger.info(f"Removed hotkey: {hotkey}")
        except Exception as e:
            self.logger.error(f"Failed to remove hotkey {hotkey}: {str(e)}")

    def register_limit_hotkeys(self, increase_cb: Callable, decrease_cb: Callable):
        """Регистрирует горячие клавиши для изменения лимита времени (Ctrl+Alt+Up/Down)"""
        try:
            self.add_hotkey('ctrl+alt+up', increase_cb)
            self.add_hotkey('ctrl+alt+down', decrease_cb)
            self.logger.info("Registered limit hotkeys: Ctrl+Alt+Up/Down")
        except Exception as e:
            self.logger.error(f"Failed to register limit hotkeys: {str(e)}")

    def register_blocker_hotkey(self, unblock_cb: Callable):
        """Регистрирует горячую клавишу для быстрого выключения блокировки (Ctrl+Alt+B)"""
        try:
            self.add_hotkey('ctrl+alt+b', unblock_cb)
            self.logger.info("Registered blocker hotkey: Ctrl+Alt+B")
        except Exception as e:
            self.logger.error(f"Failed to register blocker hotkey: {str(e)}")
            
    def stop(self):
        """Останавливает все горячие клавиши"""
        try:
            for hotkey in list(self.hotkeys.keys()):
                self.remove_hotkey(hotkey)
            self.logger.info("All hotkeys stopped")
        except Exception as e:
            self.logger.error(f"Failed to stop hotkeys: {str(e)}")

    # --- Новое: регистрация из настроек и выдача текущего списка ---
    def register_from_settings(self, settings, callbacks: dict):
        """Регистрирует хоткеи из settings["hotkeys"].
        callbacks: {
          "start": cb,
          "pause_resume": cb,
          "reset": cb,
          "add_5_min": cb,
        }
        """
        try:
            hk = (settings.get("hotkeys") or {})
            for key, cb in callbacks.items():
                combo = hk.get(key)
                if key == "pause_resume" and not combo:
                    combo = hk.get("pause")
                if combo and callable(cb):
                    self.add_hotkey(combo, cb)
                    self.named_hotkeys[key] = combo
        except Exception as e:
            self.logger.error(f"Failed register_from_settings: {e}")

    def get_hotkeys_list(self):
        """Возвращает список строк вида 'Действие — Комбинация'."""
        try:
            return list(self.hotkeys.keys())
        except Exception:
            return []

    def get_named_hotkeys(self):
        """Возвращает словарь {action_key: combo} только для настраиваемых хоткеев."""
        return dict(self.named_hotkeys)
