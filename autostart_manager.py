"""
Файл: autostart_manager.py

Модуль для управления автозапуском приложения Game Timer при старте системы (Windows).
"""

import os
import sys
import winreg
from logger import Logger
from typing import Optional

class AutostartManager:
    """Менеджер автозапуска приложения"""
    
    def __init__(self):
        self.logger = Logger("AutostartManager")
        self.key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        self.app_name = "GameTimer"
        
    def set_autostart(self, enable: bool = True) -> bool:
        """Включение/выключение автозапуска"""
        try:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                self.key_path,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                if enable:
                    executable = sys.executable
                    if not getattr(sys, "frozen", False):
                        if os.path.basename(executable).lower() == "python.exe":
                            pythonw = os.path.join(
                                os.path.dirname(executable), "pythonw.exe"
                            )
                            if os.path.isfile(pythonw):
                                executable = pythonw
                        script = os.path.abspath(sys.argv[0])
                        command = f'"{executable}" "{script}"'
                    else:
                        command = f'"{executable}"'
                    winreg.SetValueEx(
                        key,
                        self.app_name,
                        0,
                        winreg.REG_SZ,
                        command,
                    )
                    self.logger.info("Autostart enabled")
                else:
                    try:
                        winreg.DeleteValue(key, self.app_name)
                    except FileNotFoundError:
                        pass
                    self.logger.info("Autostart disabled")
            return True
        except Exception as e:
            self.logger.error(f"Error configuring autostart: {str(e)}")
            return False
            
    def is_autostart_enabled(self) -> bool:
        """Проверяет, включен ли автозапуск"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, 
                self.key_path, 
                0, 
                winreg.KEY_READ
            )
            
            try:
                value, _ = winreg.QueryValueEx(key, self.app_name)
                winreg.CloseKey(key)
                return True
            except FileNotFoundError:
                winreg.CloseKey(key)
                return False
                
        except Exception as e:
            self.logger.error(f"Error checking autostart status: {str(e)}")
            return False
            
    def get_autostart_path(self) -> Optional[str]:
        """Возвращает путь к исполняемому файлу в автозапуске"""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, 
                self.key_path, 
                0, 
                winreg.KEY_READ
            )
            
            try:
                value, _ = winreg.QueryValueEx(key, self.app_name)
                winreg.CloseKey(key)
                return value
            except FileNotFoundError:
                winreg.CloseKey(key)
                return None
                
        except Exception as e:
            self.logger.error(f"Error getting autostart path: {str(e)}")
            return None
