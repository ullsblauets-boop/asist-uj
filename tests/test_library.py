"""Biblioteca: etiquetas (asignatura, tema, tipo, profesor), edición y subidas."""

import pytest

from uji_sync.config import registry_path
from uji_sync.library import (
    add_upload, filter_items, guess_tipo, recent_items, sync_library, update_item,
)
from uji_sync.registry import Registry

from .test_ai import DATA, add_file


@pytest.mark.parametrize("name,tema,source,expected", [
    ("Examen parcial 2024.pdf", "", "aula", "Exámenes"),
    ("Solución boletín 3.pdf", "", "aula", "Ejercicios corregidos"),
    ("Boletín de problemas 2.pdf", "", "aula", "Problemas"),
    ("Ejercicios propuestos.pdf", "", "aula", "Ejercicios"),
    ("Práctica 1 - Laboratorio.pdf", "", "aula", "Prácticas"),
    ("Tema 3 - Derivadas.pdf", "", "aula", "Teoría"),
    ("presentacion.pptx", "", "aula", "Teoría"),
    ("Horario.pdf", "00 - General", "aula", "Otros"),
    ("IMG_2031.jpg", "", "propio", "Apuntes"),
    ("foto pizarra.jpg", "", "propio", "Pizarra"),
])
def test_guess_tipo(name, tema, source, expected):
    assert guess_tipo(name, tema, source) == expected


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "UJI Study"
    reg = Registry(registry_path(root))
    a = add_file(reg, root, "Cálculo I/03 - Tema 3_ Derivadas/Tema 3.pdf", b"t3", course="Cálculo I")
    add_file(reg, root, "Cálculo I/03 - Tema 3_ Derivadas/Boletín 3.pdf", b"b3", course="Cálculo I")
    add_file(reg, root, "Física I/02 - Cinemática/Examen 2023.pdf", b"ex", course="Física I")
    (root / "Cálculo I/01 - Tema 1").mkdir(parents=True)
    reg.save_summary(a.sha256, "claude-opus-5", DATA, 1, 1)
    reg.set_course_profesor("Cálculo I", "Dra. García")
    yield root, reg
    reg.close()


def test_sync_library_tags_everything(lib):
    root, reg = lib
    items = sync_library(root, reg)
    t3 = items["Cálculo I/03 - Tema 3_ Derivadas/Tema 3.pdf"]
    assert (t3["course"], t3["tema"], t3["tipo"], t3["profesor"], t3["source"]) == (
        "Cálculo I", "03 - Tema 3_ Derivadas", "Teoría", "Dra. García", "aula")
    assert t3["descripcion"] == "Límites y derivadas básicas."  # resumen existente
    assert items["Física I/02 - Cinemática/Examen 2023.pdf"]["tipo"] == "Exámenes"

    # Los cambios manuales se conservan en la siguiente sincronización
    update_item(root, reg, t3["path"], {"tipo": "Apuntes", "profesor": "Prof. X"})
    again = sync_library(root, reg)[t3["path"]]
    assert (again["tipo"], again["profesor"]) == ("Apuntes", "Prof. X")

    # Filtros
    assert [i["titulo"] for i in filter_items(again and sync_library(root, reg), course="Cálculo I", tipo="Problemas")] == ["Boletín 3"]
    assert [i["course"] for i in filter_items(sync_library(root, reg), q="examen")] == ["Física I"]
    assert len(recent_items(sync_library(root, reg))) == 3

    # Un archivo borrado desaparece de la biblioteca
    (root / "Física I/02 - Cinemática/Examen 2023.pdf").unlink()
    assert "Física I/02 - Cinemática/Examen 2023.pdf" not in sync_library(root, reg)


def test_upload_and_move_own_notes(lib):
    root, reg = lib
    sync_library(root, reg)
    it = add_upload(root, reg, "../../foto.jpg", b"img", "Cálculo I", "03 - Tema 3_ Derivadas",
                    "Pizarra", "", "Pizarra regla de la cadena")
    assert it["path"] == "Cálculo I/Mis apuntes/03 - Tema 3_ Derivadas/foto.jpg"
    assert (it["profesor"], it["titulo"], it["source"]) == ("Dra. García", "Pizarra regla de la cadena", "propio")
    # Mismo nombre: no se sobrescribe
    it2 = add_upload(root, reg, "foto.jpg", b"img2", "Cálculo I", "03 - Tema 3_ Derivadas", "Apuntes", "")
    assert it2["path"].endswith("foto (2).jpg")
    with pytest.raises(ValueError):
        add_upload(root, reg, "x.jpg", b"x", "No existe", "", "Apuntes", "")
    with pytest.raises(ValueError):
        add_upload(root, reg, "x.jpg", b"x", "Cálculo I", "../../fuera", "Apuntes", "")

    # Cambiar el tema de un apunte propio lo mueve de carpeta
    moved = update_item(root, reg, it["path"], {"tema": "01 - Tema 1"})
    assert moved["path"] == "Cálculo I/Mis apuntes/01 - Tema 1/foto.jpg"
    assert (root / moved["path"]).read_bytes() == b"img" and not (root / it["path"]).exists()
    assert moved["path"] in sync_library(root, reg)

    # Los del Aula Virtual no se mueven: solo cambian de etiqueta
    aula = update_item(root, reg, "Cálculo I/03 - Tema 3_ Derivadas/Tema 3.pdf", {"tema": "01 - Tema 1"})
    assert aula["path"] == "Cálculo I/03 - Tema 3_ Derivadas/Tema 3.pdf"
    with pytest.raises(ValueError):
        update_item(root, reg, moved["path"], {"tipo": "Inventado"})
