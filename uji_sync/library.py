"""Lo que hay en la carpeta UJI: asignaturas, temas y materiales."""

from __future__ import annotations

from pathlib import Path

NOTES_DIR = "Mis apuntes"            # apuntes propios dentro de cada asignatura
INBOX_DIR = "_Bandeja de apuntes"    # donde el usuario deja apuntes para organizar
IGNORED_SUFFIXES = {".part", ".url", ".ini", ".db", ".tmp"}


def _visible(p: Path) -> bool:
    return not p.name.startswith(("_", ".", "~$"))


def list_courses(root: Path) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir() and _visible(p))


def list_sections(root: Path, course: str) -> list[str]:
    """Temas de una asignatura (las carpetas de secciones de Moodle)."""
    base = root / course
    if not base.is_dir():
        return []
    return sorted(p.name for p in base.iterdir()
                  if p.is_dir() and _visible(p) and p.name != NOTES_DIR)


def course_materials(root: Path, course: str) -> list[str]:
    """Archivos de una asignatura (rutas relativas a UJI), sin resúmenes ni versiones antiguas."""
    base = root / course
    out = []
    for path in sorted(base.rglob("*")):
        rel = path.relative_to(root)
        if (path.is_file() and all(_visible(Path(part)) for part in rel.parts)
                and path.suffix.lower() not in IGNORED_SUFFIXES):
            out.append(rel.as_posix())
    return out
