import os
from PyQt6.QtCore import QUrl, QObject
from PyQt6.QtMultimedia import QSoundEffect

class SoundManager(QObject):
    """
    Управляет воспроизведением звуков для различных событий приложения.
    """
    def __init__(self, settings_manager, parent=None):
        """
        Инициализирует SoundManager.
        :param settings_manager: Экземпляр SettingsManager.
        """
        super().__init__(parent)
        self.settings = settings_manager
        self.sound_effects = {}
        # Предполагается, что звуки находятся в папке 'sounds'
        self.base_path = "sounds"

    def _get_sound_effect(self, sound_name):
        """
        Загружает и извлекает объект QSoundEffect.
        Кэширует звуковые эффекты, чтобы избежать их повторной загрузки.
        """
        if sound_name in self.sound_effects:
            return self.sound_effects[sound_name]

        sound_path = os.path.join(self.base_path, f"{sound_name}.wav")
        if not os.path.exists(sound_path):
            print(f"Звуковой файл не найден: {sound_path}")
            return None

        sound_effect = QSoundEffect(self)
        sound_effect.setSource(QUrl.fromLocalFile(sound_path))
        self.sound_effects[sound_name] = sound_effect
        return sound_effect

    def play(self, sound_name):
        """
        Воспроизводит указанный звук, если звук включен в настройках.
        """
        if self.settings.get("sound_enabled", True):
            effect = self._get_sound_effect(sound_name)
            if effect:
                effect.play()
