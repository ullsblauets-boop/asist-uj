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


# ================================================================ biblioteca
# Cada archivo de la carpeta lleva etiquetas: asignatura, tema, tipo y profesor.
# Las carpetas siguen los temas del Aula Virtual; el tipo es una etiqueta.

import re
import shutil
from datetime import datetime, timedelta
from pathlib import PurePosixPath

TIPOS = ["Teoría", "Apuntes", "Problemas", "Ejercicios", "Ejercicios corregidos",
         "Exámenes", "Prácticas", "Pizarra", "Otros"]
SOURCES = {"aula": "Aula Virtual", "propio": "Mis apuntes"}

# Propuesta de tipo por el nombre (sin IA, gratis). El orden importa.
_TIPO_RULES = [
    ("Exámenes", r"examen|parcial|convocatoria|final\b|prueba"),
    ("Ejercicios corregidos", r"soluci[oó]n|resuelto|resuelta|corregid"),
    ("Problemas", r"problema|bolet[ií]n|hoja\b|hoja \d"),
    ("Ejercicios", r"ejercicio|actividad|tarea"),
    ("Prácticas", r"pr[aá]ctica|laboratorio|\blab\b"),
    ("Pizarra", r"pizarra|whiteboard"),
    ("Teoría", r"tema|teor[ií]a|apuntes|transparencias|diapositivas|slides|lecci[oó]n|unidad"),
]


def guess_tipo(name: str, tema: str = "", source: str = "aula") -> str:
    text = f"{name} {tema}".lower()
    for tipo, pattern in _TIPO_RULES:
        if re.search(pattern, text):
            return tipo
    if source == "propio":
        return "Apuntes"
    if PurePosixPath(name).suffix.lower() in (".pptx", ".ppt"):
        return "Teoría"
    return "Otros"


def _location(rel: str) -> tuple[str, str, str]:
    """Asignatura, tema y origen deducidos de la ruta."""
    parts = PurePosixPath(rel).parts
    course = parts[0]
    if len(parts) > 1 and parts[1] == NOTES_DIR:
        return course, (parts[2] if len(parts) > 3 else ""), "propio"
    return course, (parts[1] if len(parts) > 2 else ""), "aula"


def sync_library(root: Path, registry) -> dict[str, dict]:
    """Pone la biblioteca al día con lo que hay en disco y devuelve sus elementos."""
    items = registry.library_items()
    profesores = registry.course_profesores()
    notes = registry.notes()
    summaries = {r.local_path: r.sha256 for r in registry.files()}
    present = set()
    for course in list_courses(root):
        for rel in course_materials(root, course):
            present.add(rel)
            if rel in items:
                continue
            course_name, tema, source = _location(rel)
            note = notes.get(rel)
            summary = registry.get_summary(summaries[rel]) if rel in summaries else None
            item = {
                "path": rel, "course": course_name, "tema": tema,
                "tipo": guess_tipo(PurePosixPath(rel).name, tema, source),
                "profesor": profesores.get(course_name, ""), "source": source,
                "titulo": note["titulo"] if note else PurePosixPath(rel).stem,
                "descripcion": (note["en_una_frase"] if note
                                else summary["en_una_frase"] if summary else ""),
                "added": datetime.now().isoformat(timespec="seconds"),
            }
            registry.save_library_item(item)
            items[rel] = item
    for rel in [r for r in items if r not in present]:  # archivos borrados o movidos
        registry.delete_library_item(rel)
        del items[rel]
    return items


def filter_items(items: dict[str, dict], course=None, tema=None, tipo=None,
                 profesor=None, source=None, q=None) -> list[dict]:
    out = []
    q = (q or "").lower().strip()
    for it in items.values():
        if course and it["course"] != course or tema and it["tema"] != tema:
            continue
        if tipo and it["tipo"] != tipo or source and it["source"] != source:
            continue
        if profesor and it["profesor"] != profesor:
            continue
        if q and q not in f"{it['titulo']} {it['path']} {it['descripcion']}".lower():
            continue
        out.append(it)
    return sorted(out, key=lambda i: (i["course"], i["tema"], i["titulo"].lower()))


def recent_items(items: dict[str, dict], days: int = 14) -> list[dict]:
    since = (datetime.now() - timedelta(days=days)).isoformat()
    return sorted((i for i in items.values() if i["added"] >= since),
                  key=lambda i: i["added"], reverse=True)


def notes_folder(course: str, tema: str) -> PurePosixPath:
    return PurePosixPath(course, NOTES_DIR, *([tema] if tema else []))


def free_path(root: Path, rel: PurePosixPath) -> PurePosixPath:
    """Ruta libre: nunca se sobrescribe un archivo existente."""
    candidate, n = rel, 1
    while (root / candidate).exists():
        n += 1
        candidate = rel.with_name(f"{rel.stem} ({n}){rel.suffix}")
    return candidate


def update_item(root: Path, registry, path: str, changes: dict) -> dict:
    """Cambia las etiquetas de un archivo. Los apuntes propios se mueven de carpeta
    si cambian de asignatura o tema; los del Aula Virtual solo cambian de etiqueta."""
    items = registry.library_items()
    item = dict(items[path])
    for key in ("course", "tema", "tipo", "profesor", "titulo", "descripcion"):
        if key in changes and changes[key] is not None:
            item[key] = str(changes[key]).strip()
    if item["tipo"] not in TIPOS:
        raise ValueError("tipo desconocido")
    if item["course"] not in list_courses(root):
        raise ValueError("asignatura desconocida")
    if item["source"] == "propio":
        if item["tema"] and item["tema"] not in list_sections(root, item["course"]):
            raise ValueError("tema desconocido")
        folder = notes_folder(item["course"], item["tema"])
        if PurePosixPath(path).parent != folder:
            new_rel = free_path(root, folder / PurePosixPath(path).name)
            (root / new_rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(root / path), str(root / new_rel))
            registry.delete_library_item(path)
            item["path"] = str(new_rel)
    registry.save_library_item(item)
    return item


def add_upload(root: Path, registry, filename: str, data: bytes, course: str, tema: str,
               tipo: str, profesor: str, titulo: str = "") -> dict:
    """Guarda un archivo subido en <Asignatura>/Mis apuntes/<Tema>/ con sus etiquetas."""
    from .fsutils import safe_name

    if course not in list_courses(root):
        raise ValueError("asignatura desconocida")
    if tema and tema not in list_sections(root, course):
        raise ValueError("tema desconocido")
    if tipo not in TIPOS:
        raise ValueError("tipo desconocido")
    name = safe_name(PurePosixPath(filename.replace("\\", "/")).name, fallback="apunte")
    rel = free_path(root, notes_folder(course, tema) / name)
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)
    item = {
        "path": str(rel), "course": course, "tema": tema, "tipo": tipo,
        "profesor": profesor or registry.course_profesores().get(course, ""),
        "source": "propio", "titulo": titulo.strip() or rel.stem, "descripcion": "",
        "added": datetime.now().isoformat(timespec="seconds"),
    }
    registry.save_library_item(item)
    return item
