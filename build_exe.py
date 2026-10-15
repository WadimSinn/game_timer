"""
Файл: build_exe.py

Скрипт сборки и упаковки приложения Game Timer с помощью PyInstaller.
Делает устойчивой сборку: выбирает иконку по наличию, добавляет существующие ресурсы,
и использует актуальные скрытые импорты под текущий стек (PyQt6, psutil, keyboard, win32*).

Запуск:
    python build_exe.py
Результат: dist/GameTimer.exe
"""

import os
import PyInstaller.__main__


def exist(path: str) -> bool:
    return os.path.exists(path)


def add_data_arg(src: str, dst: str = '.') -> str:
    return f"--add-data={src};{dst}"


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    app_name = "GameTimer"

    # Динамический выбор иконки: prefer .ico
    icon_candidates = [
        os.path.join(base_dir, 'timer.ico'),
        os.path.join(base_dir, 'Icon_game_timer.png'),
    ]
    icon_arg = None
    for ico in icon_candidates:
        if exist(ico):
            icon_arg = f"--icon={ico}"
            break

    # Ресурсы (добавляем только существующие)
    maybe_data = [
        ('Icon_game_timer.png', '.'),
        ('timer.ico', '.'),
        ('achievements.json', '.'),
        ('settings.json', '.'),
        ('README.md', '.'),
        ('requirements.txt', '.'),
    ]
    data_files = []
    for src, dst in maybe_data:
        full = os.path.join(base_dir, src)
        if exist(full):
            data_files.append(add_data_arg(full, dst))

    # Скрытые импорты под текущие зависимости
    hidden_imports = [
        '--hidden-import=keyboard',
        '--hidden-import=psutil',
        '--hidden-import=PyQt6.sip',
        '--hidden-import=win32gui',
        '--hidden-import=win32con',
        '--hidden-import=win32api',
        '--hidden-import=win32com.client',
        '--hidden-import=winreg',
        '--hidden-import=sqlite3',
    ]

    build_args = [
        f'--name={app_name}',
        '--onefile',
        '--noconsole',
        '--noconfirm',
        '--clean',
        f"--distpath={os.path.join(base_dir, 'dist')}",
        f"--workpath={os.path.join(base_dir, 'build')}",
        f"--specpath={os.path.join(base_dir, 'build')}",
        # Надёжнее подтянуть плагины и ресурсы PyQt6
        '--collect-submodules=PyQt6',
        '--collect-data=PyQt6',
    ]

    if icon_arg:
        build_args.append(icon_arg)

    build_args.extend(data_files)
    build_args.extend(hidden_imports)

    # Главный модуль
    build_args.append(os.path.join(base_dir, 'game_timer.py'))

    # Версия/метаданные (опционально, если есть файл)
    version_file = os.path.join(base_dir, 'version_info.txt')
    if exist(version_file):
        build_args.append(f"--version-file={version_file}")

    # Печать аргументов для отладки (опционально)
    # print('PyInstaller args:', build_args)

    PyInstaller.__main__.run(build_args)
