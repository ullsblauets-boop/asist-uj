"""Prueba de extremo a extremo contra un Moodle simulado, con un navegador real."""

import os

import pytest

from uji_sync.moodle import MoodleBrowser
from uji_sync.sync import Syncer, format_summary

from .fake_moodle import FakeMoodle

pytest.importorskip("playwright")


@pytest.fixture()
def env(tmp_path):
    fake = FakeMoodle().start()
    browser = MoodleBrowser(fake.base_url, tmp_path / "profile", channel=None,
                            headless=True, delay=0)
    try:
        browser.start()
    except Exception as e:  # sin navegador disponible
        fake.stop()
        pytest.skip(f"No hay navegador para Playwright: {e}")
    # "Login manual": aquí lo simula el test pulsando el botón del formulario.
    browser.open_site()
    assert not browser.is_logged_in()
    browser.page.click("#loginbtn")
    browser.wait_for_login(timeout=10)
    yield fake, browser, tmp_path / "UJI"
    browser.close()
    fake.stop()


def run(browser, dest, dry_run=False):
    syncer = Syncer(browser, dest, dry_run=dry_run, log=lambda _: None)
    try:
        return syncer.sync([c for c in browser.get_courses() if c.id == 1])[0]
    finally:
        syncer.close()


def files_in(root):
    return sorted(
        os.path.relpath(os.path.join(d, f), root).replace(os.sep, "/")
        for d, _, fs in os.walk(root) for f in fs if not f.startswith(".uji-sync")
    )


def test_full_flow(env):
    fake, browser, dest = env
    assert [c.fullname for c in browser.get_courses()] == ["Física", "Matemáticas"]

    # Solo analizar: no se escribe nada
    r = run(browser, dest, dry_run=True)
    assert len(r.new) == 7 and files_in(dest) == []

    # Primera sincronización
    r = run(browser, dest)
    assert files_in(dest) == [
        "Matemáticas/00 - General/Web de la asignatura.url",
        "Matemáticas/01 - Tema 1_ Introducción/Horario.pdf",
        "Matemáticas/01 - Tema 1_ Introducción/Prácticas/Datos/datos.xlsx",
        "Matemáticas/01 - Tema 1_ Introducción/Prácticas/Datos/figura 1.png",
        "Matemáticas/01 - Tema 1_ Introducción/Prácticas/P1.pdf",
        "Matemáticas/01 - Tema 1_ Introducción/Tema 1.pdf",
    ]
    assert len(r.new) == 6 and r.unchanged == 0
    assert r.skipped == ["privado.pdf"]  # sin permiso: no se fuerza
    assert "Matemáticas → 6 archivos nuevos, 0 sin cambios, 1 no disponibles" in format_summary([r])

    # Segunda: nada nuevo, sin duplicados
    r = run(browser, dest)
    assert (len(r.new), len(r.updated), r.unchanged) == (0, 0, 6)

    # El profesor sustituye el PDF (nueva revisión): se actualiza y se guarda la versión anterior
    fake.resource_rev, fake.resource_body = 2, b"%PDF-1.4 tema 1 v2"
    r = run(browser, dest)
    assert r.updated == ["Tema 1.pdf"] and r.unchanged == 5
    tema = dest / "Matemáticas/01 - Tema 1_ Introducción/Tema 1.pdf"
    assert tema.read_bytes() == b"%PDF-1.4 tema 1 v2"
    old = [f for f in files_in(dest) if "_versiones_anteriores" in f]
    assert len(old) == 1

    # Nueva revisión con el mismo contenido: sin cambios
    fake.resource_rev = 3
    r = run(browser, dest)
    assert (len(r.new), len(r.updated), r.unchanged) == (0, 0, 6)

    # Si el usuario borra un archivo, se vuelve a descargar
    tema.unlink()
    r = run(browser, dest)
    assert r.new == ["Tema 1.pdf"] and tema.exists()
