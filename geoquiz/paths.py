"""Where bundled files and the save file live (works inside a PyInstaller exe)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def app_dir():
    """Folder of the .exe when frozen, otherwise the project folder."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resource_path(relative):
    """Path of a bundled read-only file such as data/tasks.json.

    A file placed next to the .exe wins over the copy packed inside it, so the
    tasks and strings stay editable even with the single-file build.
    """
    if getattr(sys, "frozen", False):
        external = app_dir() / relative
        if external.exists():
            return external
        return Path(getattr(sys, "_MEIPASS", app_dir())) / relative
    return app_dir() / relative


def resource_dirs(relative):
    """Every existing folder a bundled directory may live in (beside the
    .exe and inside it), for listing files rather than opening one."""
    candidates = [app_dir() / relative]
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", app_dir())) / relative)
    return [c for c in candidates if c.is_dir()]


def _writable(folder):
    """Can a file really be created here? (os.access cannot tell on Windows:
    it only looks at the read-only attribute, so it says yes for Program Files.)"""
    # Not tempfile: on Windows it retries a refused create millions of times,
    # which would hang the game at startup in exactly the case being tested.
    probe = Path(folder) / f".write-test-{os.getpid()}"
    try:
        os.close(os.open(probe, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def progress_path():
    """Writable location for progress.json: beside the app if possible."""
    folder = app_dir()
    if _writable(folder):
        return folder / "progress.json"
    base = Path(os.environ.get("APPDATA") or Path.home()) / "KidsGeoQuiz"
    base.mkdir(parents=True, exist_ok=True)
    return base / "progress.json"
