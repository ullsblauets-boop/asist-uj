"""Nombres de archivo seguros para Windows y utilidades de URLs de Moodle."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_COMPONENT = 80  # margen para no superar MAX_PATH (260) en Windows


def safe_name(name: str, fallback: str = "sin nombre", max_len: int = MAX_COMPONENT) -> str:
    """Convierte un texto en un nombre válido de archivo/carpeta en Windows."""
    name = _INVALID.sub("_", name or "")
    name = re.sub(r"\s+", " ", name).strip().rstrip(". ")
    if not name:
        name = fallback
    stem, dot, ext = name.rpartition(".")
    if stem.upper() in _RESERVED or name.upper() in _RESERVED:
        name = "_" + name
    if len(name) > max_len:
        if dot and 0 < len(ext) <= 10:
            name = name[: max_len - len(ext) - 1].rstrip(". ") + "." + ext
        else:
            name = name[:max_len].rstrip(". ")
    return name


def is_pluginfile(url: str) -> bool:
    return "/pluginfile.php/" in urlsplit(url).path


def _pluginfile_parts(url: str) -> list[str]:
    """Segmentos tras /pluginfile.php/: contextid, component, filearea, ..."""
    path = urlsplit(url).path
    _, _, rest = path.partition("/pluginfile.php/")
    return [unquote(p) for p in rest.split("/") if p]


def _has_revision(parts: list[str]) -> bool:
    # mod_resource y mod_folder guardan un número de revisión tras "content"
    # que cambia cuando el profesor sustituye el archivo.
    return (
        len(parts) >= 5
        and parts[1] in ("mod_resource", "mod_folder")
        and parts[2] == "content"
        and parts[3].isdigit()
    )


def pluginfile_key(url: str) -> str:
    """Identificador estable de un archivo de Moodle (sin revisión ni parámetros)."""
    parts = _pluginfile_parts(url)
    if _has_revision(parts):
        parts = parts[:3] + parts[4:]
    return "pluginfile:" + "/".join(parts)


def pluginfile_filename(url: str) -> str:
    parts = _pluginfile_parts(url)
    return parts[-1] if parts else ""


def folder_subpath(url: str) -> list[str]:
    """Subcarpetas dentro de una Carpeta de Moodle (sin el nombre de archivo)."""
    parts = _pluginfile_parts(url)
    if not _has_revision(parts):
        return []
    return parts[4:-1]


def strip_query(url: str) -> str:
    s = urlsplit(url)
    return s._replace(query="", fragment="").geturl()


def relpath_str(path: PurePosixPath | str) -> str:
    return str(PurePosixPath(path))
