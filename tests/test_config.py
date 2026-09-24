from pathlib import Path

from uji_sync.config import find_google_drive, registry_path


def test_find_google_drive(tmp_path):
    g = tmp_path / "G"
    (g / "Mi unidad").mkdir(parents=True)
    home = tmp_path / "home"
    home.mkdir()
    assert find_google_drive([home, g]) == g / "Mi unidad"
    assert find_google_drive([home]) is None


def test_registry_outside_destination(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    dest = tmp_path / "Drive" / "Mi unidad" / "UJI"
    db = registry_path(dest)
    assert db.parent == tmp_path / "appdata" / "UJISync" / "registros"
    assert dest not in db.parents
    assert registry_path(dest) == db
    assert registry_path(tmp_path / "otra" / "UJI") != db
    assert registry_path(Path(str(dest).upper())) == db  # Windows no distingue mayúsculas
