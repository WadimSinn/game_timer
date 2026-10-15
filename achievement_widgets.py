"""
Файл: achievement_widgets.py

Виджеты карточек достижений и отдельное окно "Мои достижения".
Поддерживает отображение полученных (цветных) и ещё не полученных (серых) достижений.
В будущем легко расширяется добавлением иконок/картинок.
"""
from typing import Optional
from PyQt6 import QtWidgets


class AchievementCard(QtWidgets.QGroupBox):
    """Карточка достижения с заголовком, описанием и прогрессом.
    Если достижение не получено, оформление серое.
    """

    def __init__(self, title: str, description: str, progress: int, total: int, completed: bool, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(title, parent)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Minimum
        )

        v = QtWidgets.QVBoxLayout(self)
        v.addWidget(QtWidgets.QLabel(description))

        pb = QtWidgets.QProgressBar()
        pb.setRange(0, max(1, total))
        pb.setValue(max(0, min(progress, total)))
        v.addWidget(pb)

        status = "Получено" if completed else f"Прогресс: {progress}/{total}"
        status_lbl = QtWidgets.QLabel(status)
        v.addWidget(status_lbl)

        if not completed:
            # Серое оформление для ещё не полученных
            self.setStyleSheet("QGroupBox { color: gray; } QLabel { color: gray; }")


class AchievementsWindow(QtWidgets.QDialog):
    """Отдельное окно с достижениями (цветные полученные, серые — ещё нет)."""

    def __init__(self, achievement_manager, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Мои достижения")
        self.resize(520, 640)

        layout = QtWidgets.QVBoxLayout(self)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        self.vbox = QtWidgets.QVBoxLayout(container)
        self.vbox.setContentsMargins(8, 8, 8, 8)
        self.vbox.setSpacing(8)
        self.vbox.addStretch(1)
        scroll.setWidget(container)
        layout.addWidget(scroll)

        # Наполнение карточками
        try:
            for ach in achievement_manager.get_all_achievements():
                progress, total = achievement_manager.get_achievement_progress(ach.id)
                card = AchievementCard(ach.title, ach.description, progress, total, ach.completed)
                self.vbox.insertWidget(self.vbox.count() - 1, card)
        except Exception:
            pass

        # Кнопка закрытия
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Close
        )
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
