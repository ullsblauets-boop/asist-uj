"""Perfil de estilo de una asignatura (Fase 6)."""

import json
from types import SimpleNamespace

from uji_sync.config import registry_path
from uji_sync.library import sync_library, update_item
from uji_sync.registry import Registry
from uji_sync.search import SearchIndex
from uji_sync.style import build_profile, gather_samples

from .test_search import NoEmbedder

PROFILE = {"suficiente": True, "motivo": "", "terminologia": ["esfuerzo axil"], "notacion": ["N", "σ = N/A"],
           "formulas_habituales": ["σ = N/A"], "orden_de_pasos": ["Datos", "Equilibrio", "Tensión"],
           "nivel_de_explicacion": "detallado", "convenciones": ["tracción positiva"],
           "procedimientos": [{"tipo_de_ejercicio": "barra a tracción", "pasos": ["N", "σ"], "fuente": "Sol.txt"}]}


class FakeClaude:
    def __init__(self):
        self.calls = []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"],
                               usage=SimpleNamespace(input_tokens=15000, output_tokens=800),
                               content=[SimpleNamespace(type="text", text=json.dumps(PROFILE))])


def test_samples_and_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "UJI Study"
    t = root / "Estructuras/02 - Axil"
    t.mkdir(parents=True)
    (t / "Tema 2 teoria.txt").write_text("El esfuerzo axil N produce una tensión σ = N/A.", encoding="utf-8")
    (t / "Solucion boletin 2.txt").write_text("Sol: tracción positiva, N = 20 kN, σ = 20/4 = 5 MPa.", encoding="utf-8")
    own = root / "Estructuras/Mis apuntes/02 - Axil"
    own.mkdir(parents=True)
    (own / "mis notas.txt").write_text("Recordar: tracción +, compresión −.", encoding="utf-8")
    (root / "Otra/01 - X").mkdir(parents=True)
    (root / "Otra/01 - X/otra.txt").write_text("Nada que ver.", encoding="utf-8")
    reg = Registry(registry_path(root))
    sync_library(root, reg)
    idx = SearchIndex(root, embedder=NoEmbedder())
    idx.update()
    idx.close()

    sample, sources = gather_samples(root, "Estructuras", reg)
    # Primero el material del profesor (ejercicios corregidos antes que teoría); luego los apuntes propios
    assert sources == ["Estructuras/02 - Axil/Solucion boletin 2.txt", "Estructuras/02 - Axil/Tema 2 teoria.txt",
                       "Estructuras/Mis apuntes/02 - Axil/mis notas.txt"]
    assert "[tipo: Ejercicios corregidos; profesor/Aula Virtual]" in sample and "otra.txt" not in sample

    claude = FakeClaude()
    profile = build_profile(root, "Estructuras", reg, claude)
    assert profile["suficiente"] and profile["fuentes"] == sources
    assert reg.get_style("Estructuras")["notacion"] == ["N", "σ = N/A"]
    req = claude.calls[0]
    assert req["output_config"]["format"]["schema"]["required"][0] == "suficiente"
    assert "Describe solo lo que se ve en las muestras" in req["system"]

    # Sin materiales indexados: no se gasta y se dice por qué
    empty = build_profile(root, "Vacía", reg, claude)
    assert empty["suficiente"] is False and "No hay materiales indexados" in empty["motivo"]
    assert len(claude.calls) == 1
    reg.close()
