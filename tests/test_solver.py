"""Resolver ejercicio (Fase 5) con un cliente de Claude simulado (sin coste)."""

import json
from types import SimpleNamespace

import pytest

from uji_sync.ai import AIError
from uji_sync.library import course_materials
from uji_sync.solver import SOLUTIONS_DIR, STANDARD_METHOD, ExerciseSolver, history

USAGE = SimpleNamespace(input_tokens=2000, output_tokens=500,
                        cache_creation_input_tokens=0, cache_read_input_tokens=0)
T = lambda text: SimpleNamespace(type="text", text=text)  # noqa: E731

READ_OK = {
    "legible": True, "problema_lectura": "", "enunciado": "Deriva h(x) = sen(x²).",
    "datos": [{"nombre": "h(x)", "valor": "sen(x²)", "unidad": ""}], "se_pide": "h'(x)",
    "asignatura": "Cálculo I", "tema_probable": "Derivadas", "tipo_de_ejercicio": "Regla de la cadena",
    "consultas": ["regla de la cadena", "derivada de funciones compuestas"],
}
SOLVED_APUNTES = {
    "metodo_origen": "apuntes",
    "fuentes": [{"documento": "Tema 3.pdf", "ubicacion": "pág. 12", "para_que": "regla de la cadena"}],
    "ejercicio_parecido": "Boletín 3.pdf, ejercicio 4",
    "solucion": "### Datos\nh(x) = sen(x²)\n### Resultado\n**h'(x) = 2x·cos(x²)**",
    "resultado": "h'(x) = 2x·cos(x²)", "avisos": ["En tus apuntes, la pág. 13 pone cos(x) en vez de cos(x²)."],
}


class FakeClaude:
    def __init__(self, read=READ_OK, solved=SOLVED_APUNTES, search_first=True):
        self.read, self.solved, self.search_first = read, solved, search_first
        self.calls = []
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.calls.append(kw)
        if "tools" not in kw:  # paso 1: leer
            return SimpleNamespace(stop_reason="end_turn", model=kw["model"], usage=USAGE,
                                   content=[T(json.dumps(self.read))])
        if self.search_first and len([c for c in self.calls if "tools" in c]) == 1:
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], usage=USAGE, content=[
                SimpleNamespace(type="tool_use", id="t1", name="buscar_en_apuntes",
                                input={"consulta": "funciones compuestas"})])
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], usage=USAGE,
                               content=[T(json.dumps(self.solved))])


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    r = tmp_path / "UJI Study"
    (r / "Cálculo I/03 - Tema 3").mkdir(parents=True)
    (r / "Cálculo I/03 - Tema 3/Tema 3.pdf").write_bytes(b"%PDF")
    (r / "Física I/01 - Cinemática").mkdir(parents=True)
    return r


def searcher_with_log(log):
    def searcher(query, courses):
        log.append((query, tuple(courses)))
        return [
            {"path": "Cálculo I/03 - Tema 3/Tema 3.pdf", "loc": "pág. 12", "text": "Regla de la cadena…",
             "tipo": "Teoría"},
            {"path": "Cálculo I/03 - Tema 3/Boletín 3.pdf", "loc": "pág. 2", "text": "Ejercicio 4: deriva…",
             "tipo": "Problemas"},
            {"path": f"Cálculo I/{SOLUTIONS_DIR}/antigua.md", "loc": "", "text": "resolución de la IA",
             "tipo": ""},
        ]
    return searcher


def photo(tmp_path):
    from PIL import Image

    p = tmp_path / "ejercicio.jpg"
    Image.new("RGB", (800, 600), "white").save(p)
    return p


def test_solve_with_method_from_notes(root, tmp_path):
    log = []
    claude = FakeClaude()
    solver = ExerciseSolver(root, searcher_with_log(log), client=claude)
    sol = solver.solve(photo(tmp_path), "", None, None, "pasos")

    assert sol.ok and sol.course == "Cálculo I" and sol.metodo_origen == "apuntes"
    assert sol.markdown.startswith("> **Método de tus apuntes:** Tema 3.pdf, pág. 12")
    assert "Ejercicio parecido:** Boletín 3.pdf" in sol.markdown
    assert "## ⚠️ Avisos" in sol.markdown and "pág. 13" in sol.markdown  # error en apuntes señalado
    assert "## Enunciado\n\nDeriva h(x) = sen(x²)." in sol.markdown
    # Búsqueda: las consultas propuestas, limitada a la asignatura detectada
    assert log[0] == ("regla de la cadena", ("Cálculo I",))

    read_req, *solve_reqs = claude.calls
    assert read_req["messages"][0]["content"][0]["type"] == "image"  # la foto se envía al leer
    assert read_req["output_config"]["format"]["schema"]["properties"]["asignatura"]["enum"] == [
        "Cálculo I", "Física I", "No lo sé"]
    first = solve_reqs[0]
    assert first["output_config"]["effort"] == "high"
    assert first["output_config"]["format"]["schema"]["properties"]["metodo_origen"]["enum"] == ["apuntes", "estandar"]
    assert [t["name"] for t in first["tools"]] == ["buscar_en_apuntes", "leer_material"]
    prompt = first["messages"][0]["content"][-1]["text"]
    # Primero el ejercicio parecido; nunca resoluciones anteriores de la IA
    assert prompt.index("Boletín 3.pdf") < prompt.index("Tema 3.pdf (pág. 12)")
    assert SOLUTIONS_DIR not in prompt
    assert "Explicación paso a paso" in prompt and "### Por qué se utiliza" in prompt
    assert "No inventes un método distinto" in first["system"][0]["text"]
    assert sol.cost > 0 and any("Ha buscado" in s for s in sol.steps)

    # Historial: resolución y foto guardadas; nunca pasan a ser material de estudio
    saved = root / sol.saved
    assert saved.exists() and saved.parent.name == SOLUTIONS_DIR
    assert saved.with_suffix(".jpg").exists()
    assert history(root)[0]["course"] == "Cálculo I" and history(root)[0]["title"] == "Regla de la cadena"
    assert not any(SOLUTIONS_DIR in m for m in course_materials(root, "Cálculo I"))


def test_standard_method_is_said_honestly(root):
    solved = {**SOLVED_APUNTES, "metodo_origen": "estandar", "fuentes": [], "ejercicio_parecido": "",
              "avisos": []}
    solver = ExerciseSolver(root, lambda q, c: [], client=FakeClaude(solved=solved, search_first=False))
    sol = solver.solve(None, "Deriva h(x) = sen(x²)", "Cálculo I", "03 - Tema 3", "resultado")
    assert sol.markdown.startswith("> " + STANDARD_METHOD)
    assert "Método de tus apuntes" not in sol.markdown
    assert any("No he encontrado nada" in s for s in sol.steps)


def test_illegible_photo_stops_early(root, tmp_path):
    read = {**READ_OK, "legible": False, "problema_lectura": "La foto está desenfocada."}
    claude = FakeClaude(read=read)
    sol = ExerciseSolver(root, lambda q, c: [], client=claude).solve(photo(tmp_path), "", None, None, "corta")
    assert not sol.ok and "desenfocada" in sol.markdown and "No puedo leer bien" in sol.markdown
    assert len(claude.calls) == 1  # no se gasta en resolver


def test_modes_and_validation(root):
    solver = ExerciseSolver(root, None, client=FakeClaude())
    with pytest.raises(AIError):
        solver.solve(None, "x", None, None, "profesor")  # Fase 6
    with pytest.raises(AIError):
        solver.solve(None, "x", "No existe", None, "pasos")
