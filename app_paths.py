"""Application resource and writable-data paths."""

import os
import shutil
import sys
from pathlib import Path


def resource_path(name):
    """Returns a bundled resource path or its source-tree equivalent."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return str(root / name)


def get_data_directory():
    """Returns a stable writable directory for user-specific application data."""
    if not getattr(sys, "frozen", False):
        return str(Path(__file__).resolve().parent)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    directory = Path(base) / "GameTimer"
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory)


def get_data_path(name):
    """Returns a writable data path and migrates known legacy files if needed."""
    directory = Path(get_data_directory())
    target = directory / name
    if target.exists() or not getattr(sys, "frozen", False):
        return str(target)

    legacy_candidates = [
        Path(sys.executable).resolve().parent / name,
        Path.cwd() / name,
    ]
    for candidate in legacy_candidates:
        if candidate.is_file() and candidate.resolve() != target.resolve():
            shutil.copy2(candidate, target)
            return str(target)

    bundled = Path(resource_path(name))
    if bundled.is_file():
        shutil.copy2(bundled, target)
    return str(target)
