"""Modo «Solo Pro»: prepara tus materiales para la app de Claude, sin usar la API.

Tras cada sincronización se escriben, en UJI/_Para Claude/:
  - Índice de materiales.md: asignaturas, temas y archivos (con resumen si ya existe).
  - Novedades.md: qué ha llegado o cambiado en cada sincronización.
  - Cómo usar con Claude.md: cómo conectar Google Drive en la app de Claude,
    instrucciones para un Proyecto y peticiones útiles.
No se envía nada a ninguna IA: no tiene coste.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath

from .config import registry_path
from .library import NOTES_DIR, course_materials, list_courses
from .registry import Registry

PRO_DIR = "_Para Claude"
INDEX_FILE = "Índice de materiales.md"
NEWS_FILE = "Novedades.md"
HOWTO_FILE = "Cómo usar con Claude.md"
NEWS_HEADER = "# Novedades del Aula Virtual\n"

PROJECT_INSTRUCTIONS = """\
Eres mi asistente de estudio de la Universitat Jaume I. Mis materiales están en
Google Drive, en la carpeta «UJI»: una carpeta por asignatura, con los temas
del Aula Virtual como subcarpetas y mis propios apuntes en «Mis apuntes».

- Antes de responder, consulta «UJI/_Para Claude/Índice de materiales.md» para
  saber qué materiales hay y dónde están, y abre los que necesites.
- Para saber qué hay nuevo, mira «UJI/_Para Claude/Novedades.md».
- Responde en español, de forma clara y didáctica, y di de qué archivo sale
  cada cosa. Si algo no está en mis materiales, avísame antes de explicarlo con
  conocimiento general."""

HOWTO = f"""\
# Cómo usar tus materiales con Claude (plan Pro, sin coste extra)

UJI Sync mantiene esta carpeta al día cada vez que sincronizas. Aquí tienes
un índice de todos tus materiales para que Claude los encuentre fácilmente.

## Configurar (una sola vez)

1. En claude.ai o en la app del móvil ve a **Ajustes → Conectores** y conecta
   **Google Drive** con la misma cuenta donde está tu carpeta UJI.
2. Crea un **Proyecto** llamado «UJI» y pega esto en sus instrucciones:

```text
{PROJECT_INSTRUCTIONS}
```

3. Abre las conversaciones de estudio dentro de ese proyecto.

## Peticiones útiles

- «¿Qué hay nuevo en el Aula Virtual desde la semana pasada?»
- «Resúmeme el Tema 3 de Cálculo I y hazme un esquema.»
- «Hazme 10 preguntas tipo test del tema de Cinemática, con soluciones al final.»
- «Explícame la regla de la cadena con los ejemplos de mis apuntes.»
- «Tengo estos apuntes en la bandeja: ¿a qué asignatura y tema va cada uno?»

## Si Claude no puede abrir un archivo

Adjúntalo directamente en el chat (el clip 📎), también desde el móvil.
Si no encuentra el índice, adjunta «{INDEX_FILE}» de esta carpeta.
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_index(root: Path) -> str:
    reg = Registry(registry_path(root))
    try:
        records = {r.local_path: r for r in reg.files()}
        notes = reg.notes()
        lines = [
            "# Índice de materiales · UJI",
            "",
            f"_Actualizado por UJI Sync el {datetime.now().strftime('%d/%m/%Y %H:%M')}._",
            "",
            "Rutas relativas a la carpeta «UJI» de Google Drive. Una carpeta por "
            f"asignatura; los temas son las secciones del Aula Virtual; «{NOTES_DIR}» son "
            "apuntes propios del estudiante.",
        ]
        for course in list_courses(root):
            lines += ["", f"## {course}", ""]
            current_folder = None
            for rel in course_materials(root, course):
                folder = str(PurePosixPath(rel).parent)
                if folder != current_folder:
                    lines += ["", f"### {folder.split('/', 1)[1] if '/' in folder else 'General'}", ""]
                    current_folder = folder
                lines.append(_entry(reg, root, rel, records, notes))
        return "\n".join(lines) + "\n"
    finally:
        reg.close()


def _entry(reg, root: Path, rel: str, records, notes) -> str:
    size_kb = max(1, (root / rel).stat().st_size // 1024)
    line = f"- `{rel}` ({size_kb} KB"
    rec = records.get(rel)
    if rec:
        line += f", actualizado {rec.last_changed[:10]}"
    line += ")"
    summary = reg.get_summary(rec.sha256) if rec else None
    if summary:  # resumen de IA ya existente: se reutiliza sin coste
        line += f": {summary['en_una_frase']}"
    elif rel in notes:
        line += f": apunte propio. {notes[rel]['en_una_frase']}"
    return line


def add_news(root: Path, changed_paths: dict[str, list[str]]) -> None:
    """Añade arriba de Novedades.md los archivos nuevos o cambiados (por asignatura)."""
    if not any(changed_paths.values()):
        return
    path = root / PRO_DIR / NEWS_FILE
    old = path.read_text(encoding="utf-8") if path.exists() else NEWS_HEADER
    body = old[len(NEWS_HEADER):] if old.startswith(NEWS_HEADER) else old
    section = [f"\n## {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"]
    for course, paths in changed_paths.items():
        if paths:
            section.append(f"**{course}**")
            section += [f"- `{p}`" for p in paths]
            section.append("")
    _write(path, NEWS_HEADER + "\n".join(section) + body)


def write_pro_files(root: Path, results=()) -> None:
    """Actualiza la carpeta _Para Claude tras una sincronización."""
    reg = Registry(registry_path(root))
    try:
        changed = {
            r.course_name: [rec.local_path for k in r.changed_keys if (rec := reg.get(k))]
            for r in results
        }
    finally:
        reg.close()
    add_news(root, changed)
    _write(root / PRO_DIR / INDEX_FILE, build_index(root))
    _write(root / PRO_DIR / HOWTO_FILE, HOWTO)
