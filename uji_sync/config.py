"""Rutas y preferencias locales. Nunca se guardan credenciales."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

BASE_URL = "https://aulavirtual.uji.es"


def app_dir() -> Path:
    """Carpeta de datos de la aplicación (%LOCALAPPDATA%\\UJISync en Windows)."""
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "UJISync"
    return Path.home() / ".uji-sync"


def browser_profile_dir() -> Path:
    """Perfil del navegador (cookies de sesión). Borrarlo = cerrar sesión."""
    return app_dir() / "browser-profile"


def default_dest_dir() -> Path:
    return Path.home() / "UJI"


@dataclass
class Settings:
    dest_dir: str = field(default_factory=lambda: str(default_dest_dir()))
    selected_course_ids: list[int] = field(default_factory=list)
    include_past: bool = False

    @classmethod
    def load(cls) -> "Settings":
        path = app_dir() / "config.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = app_dir() / "config.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
