from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def open_video(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def open_folder(path: Path) -> None:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_file_manager(path: Path) -> None:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(str(path))

    if os.name == "nt":
        subprocess.Popen(["explorer", "/select,", str(path)])
        return

    open_folder(path.parent)
