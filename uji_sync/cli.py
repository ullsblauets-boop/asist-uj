"""Punto de entrada: interfaz gráfica (por defecto) o diagnóstico por consola."""

from __future__ import annotations

import argparse

from .config import BASE_URL, browser_profile_dir, find_google_drive


def diagnose(include_past: bool, course_id: int | None) -> int:
    """Comprueba login, lista de cursos y lectura de un curso. No descarga nada."""
    from .moodle import MoodleBrowser, MoodleError

    drive = find_google_drive()
    print(f"Google Drive: {drive if drive else 'no detectado'}")
    browser = MoodleBrowser(BASE_URL, browser_profile_dir())
    browser.start()
    try:
        print("Se ha abierto el navegador. Inicia sesión en el Aula Virtual…")
        browser.open_site()
        browser.wait_for_login()
        print("✓ Sesión detectada")

        try:
            courses = browser.get_courses(include_past)
        except MoodleError as e:
            print(f"✗ No se pudo obtener la lista de cursos: {e}")
            return 1
        print(f"✓ {len(courses)} cursos:")
        for c in courses:
            print(f"   [{c.id}] {c.fullname}")
        if not courses:
            return 0

        cid = course_id or courses[0].id
        sections = browser.get_course_sections(cid)
        items = [i for s in sections for i in s.items]
        print(f"\n✓ Curso {cid}: {len(sections)} secciones, {len(items)} elementos")
        for s in sections:
            print(f"   {s.number:02d} {s.name}")
            for i in s.items:
                print(f"      - [{i.modtype}] {i.name}")

        first = next((i for i in items if i.modtype == "resource"), None)
        if first:
            url = browser.resolve_resource(first.cmid)
            print(f"\n{'✓' if url else '✗'} Archivo de '{first.name}': {url or 'no encontrado'}")
        return 0
    finally:
        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uji_sync", description="UJI Sync")
    parser.add_argument("--diagnostico", action="store_true",
                        help="comprobar el acceso sin descargar nada")
    parser.add_argument("--curso", type=int, help="id del curso a analizar en el diagnóstico")
    parser.add_argument("--pasados", action="store_true", help="incluir cursos pasados")
    args = parser.parse_args(argv)
    if args.diagnostico:
        return diagnose(args.pasados, args.curso)
    from .ui import run

    run()
    return 0
