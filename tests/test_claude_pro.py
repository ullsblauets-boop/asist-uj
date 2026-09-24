"""Modo «Solo Pro»: índice y novedades para la app de Claude, sin llamar a la API."""

from uji_sync.claude_pro import HOWTO_FILE, INDEX_FILE, NEWS_FILE, PRO_DIR, write_pro_files
from uji_sync.config import registry_path
from uji_sync.library import list_courses
from uji_sync.registry import Registry
from uji_sync.sync import CourseResult

from .test_ai import DATA, add_file


def test_pro_files(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "UJI"
    reg = Registry(registry_path(root))
    a = add_file(reg, root, "Cálculo I/03 - Tema 3/Tema 3.pdf", b"x" * 3000, course="Cálculo I")
    b = add_file(reg, root, "Cálculo I/00 - General/Guía.pdf", b"g", course="Cálculo I")
    reg.save_summary(a.sha256, "claude-opus-5", DATA, 1, 1)  # resumen ya existente: se reutiliza
    note = root / "Cálculo I/Mis apuntes/03 - Tema 3/Derivadas.jpg"
    note.parent.mkdir(parents=True)
    note.write_bytes(b"j")
    reg.save_note("Cálculo I/Mis apuntes/03 - Tema 3/Derivadas.jpg", "IMG.jpg", "Cálculo I",
                  "03 - Tema 3", "Derivadas", "Ejemplos de derivadas")
    reg.close()

    write_pro_files(root, [CourseResult(1, "Cálculo I", changed_keys=[a.key])])
    pro = root / PRO_DIR
    index = (pro / INDEX_FILE).read_text(encoding="utf-8")
    assert "## Cálculo I" in index and "### 03 - Tema 3" in index
    assert "- `Cálculo I/03 - Tema 3/Tema 3.pdf` (2 KB, actualizado t): Límites y derivadas básicas." in index
    assert "- `Cálculo I/00 - General/Guía.pdf` (1 KB, actualizado t)" in index
    assert "Derivadas.jpg` (1 KB): apunte propio. Ejemplos de derivadas" in index
    howto = (pro / HOWTO_FILE).read_text(encoding="utf-8")
    assert "Conectores" in howto and INDEX_FILE in howto
    news = (pro / NEWS_FILE).read_text(encoding="utf-8")
    assert "**Cálculo I**\n- `Cálculo I/03 - Tema 3/Tema 3.pdf`" in news

    # Sin cambios no se añade nada; con cambios, lo nuevo va arriba
    write_pro_files(root, [CourseResult(1, "Cálculo I")])
    assert (pro / NEWS_FILE).read_text(encoding="utf-8") == news
    write_pro_files(root, [CourseResult(1, "Cálculo I", changed_keys=[b.key])])
    news2 = (pro / NEWS_FILE).read_text(encoding="utf-8")
    assert news2.index("Guía.pdf") < news2.index("Tema 3.pdf")
    # La carpeta _Para Claude no se confunde con una asignatura
    assert list_courses(root) == ["Cálculo I"]
