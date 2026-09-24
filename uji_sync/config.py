"""Rutas y preferencias locales. Nunca se guardan credenciales."""

from __future__ import annotations

import hashlib
import json
import os
import string
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .fsutils import safe_name

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


def registry_path(dest_dir: Path) -> Path:
    """Registro SQLite de una carpeta de destino, guardado en este PC.

    No se guarda dentro de la carpeta de destino para que Google Drive (u otro
    servicio de sincronización) no suba ni bloquee la base de datos mientras se usa.
    """
    key = str(Path(dest_dir).expanduser().resolve()).lower()  # Windows no distingue mayúsculas
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
    name = safe_name(Path(dest_dir).name or "destino", max_len=40)
    return app_dir() / "registros" / f"{name}-{digest}.db"


# Nombre de la carpeta raíz de Google Drive para ordenadores según el idioma.
DRIVE_ROOT_NAMES = ("Mi unidad", "My Drive", "La meva unitat")


def find_google_drive(candidates: list[Path] | None = None) -> Path | None:
    """Carpeta "Mi unidad" de Google Drive para ordenadores, si está instalado.

    En modo streaming aparece como una unidad (normalmente G:\\Mi unidad); en modo
    duplicación, dentro de la carpeta del usuario.
    """
    if candidates is None:
        candidates = []
        if os.name == "nt":
            candidates += [Path(f"{letter}:\\") for letter in string.ascii_uppercase[2:]]
        candidates.append(Path.home())
    for base in candidates:
        for name in DRIVE_ROOT_NAMES:
            try:
                if (base / name).is_dir():
                    return base / name
            except OSError:
                continue
    return None


@dataclass
class Settings:
    dest_dir: str = field(default_factory=lambda: str(default_dest_dir()))
    selected_course_ids: list[int] = field(default_factory=list)
    include_past: bool = False
    ai_enabled: bool = False          # resumir con IA los archivos nuevos
    ai_model: str = "claude-opus-5"
    ai_consent: bool = False          # el usuario aceptó enviar materiales a Anthropic

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
