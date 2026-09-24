"""Bandeja de apuntes y asistente, con un cliente de Claude simulado (sin coste)."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from uji_sync.ai import AIFatalError
from uji_sync.assistant import Assistant, build_index
from uji_sync.config import registry_path
from uji_sync.inbox import GENERAL, UNSORTED, InboxOrganizer, destinations, inbox_dir, inbox_files
from uji_sync.registry import Registry

from .test_ai import DATA, add_file

USAGE = SimpleNamespace(input_tokens=1000, output_tokens=100,
                        cache_creation_input_tokens=0, cache_read_input_tokens=0)


def text_block(text):
    return SimpleNamespace(type="text", text=text)


class ScriptedMessages:
    """Devuelve respuestas preparadas; `reply` decide según la petición."""

    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs, default=lambda o: o.__dict__)))
        return self.reply(kwargs)


def client_for(reply):
    msgs = ScriptedMessages(reply)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs)), msgs


@pytest.fixture()
def uji(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "UJI"
    for d in ["Matemáticas/00 - General", "Matemáticas/01 - Tema 1_ Límites",
              "Física/01 - Cinemática", "Matemáticas/_resumenes_IA"]:
        (root / d).mkdir(parents=True)
    return root


# ------------------------------------------------------------------ bandeja
def test_destinations_only_existing_folders(uji):
    d = destinations(uji)
    assert d[f"Matemáticas / {GENERAL}"] == ("Matemáticas", None)
    assert d["Matemáticas / 01 - Tema 1_ Límites"] == ("Matemáticas", "01 - Tema 1_ Límites")
    assert not any("_resumenes_IA" in k for k in d)


def test_inbox_organizes_notes(uji):
    from PIL import Image

    box = inbox_dir(uji)
    assert (box / "LÉEME.txt").exists()
    Image.new("RGB", (4000, 3000), "white").save(box / "IMG_2031.jpg")
    (box / "notas.txt").write_text("apuntes de cinemática: MRU y MRUA", encoding="utf-8")
    (box / "cosas.txt").write_text("lista de la compra", encoding="utf-8")
    (box / "datos.xlsx").write_bytes(b"xlsx")
    # Ya existe un apunte con el mismo nombre: no se debe sobrescribir
    existing = uji / "Física/Mis apuntes/01 - Cinemática/MRU y MRUA.txt"
    existing.parent.mkdir(parents=True)
    existing.write_text("anterior")

    def reply(kw):
        text = kw["messages"][0]["content"][-1]["text"]
        name = text.split("Nombre original del archivo: ")[1].split("\n")[0]
        dest = {
            "IMG_2031.jpg": ("Matemáticas / 01 - Tema 1_ Límites", "Límites laterales"),
            "notas.txt": ("Física / 01 - Cinemática", "MRU y MRUA"),
            "cosas.txt": (UNSORTED, "Lista"),
            "datos.xlsx": (f"Matemáticas / {GENERAL}", "Datos de prácticas"),
        }[name]
        data = {"destino": dest[0], "tipo": "Apuntes", "titulo": dest[1],
                "en_una_frase": f"Sobre {dest[1]}"}
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], usage=USAGE,
                               content=[text_block(json.dumps(data))])

    client, msgs = client_for(reply)
    reg = Registry(registry_path(uji))
    res = InboxOrganizer(uji, reg, client=client, log=lambda _: None).organize()

    assert sorted(res.moved) == [
        ("IMG_2031.jpg", "Matemáticas/Mis apuntes/01 - Tema 1_ Límites/Límites laterales.jpg"),
        ("datos.xlsx", "Matemáticas/Mis apuntes/Datos de prácticas.xlsx"),
        ("notas.txt", "Física/Mis apuntes/01 - Cinemática/MRU y MRUA (2).txt"),
    ]
    assert res.unsorted == ["cosas.txt"] and [p.name for p in inbox_files(uji)] == ["cosas.txt"]
    assert existing.read_text() == "anterior"
    # La foto se envía como imagen reducida; el Excel, solo por su nombre
    by_name = {c["messages"][0]["content"][-1]["text"].split(": ")[1].split("\n")[0]: c for c in msgs.calls}
    photo = by_name["IMG_2031.jpg"]["messages"][0]["content"][0]
    assert photo["type"] == "image" and photo["source"]["media_type"] == "image/jpeg"
    assert len(by_name["datos.xlsx"]["messages"][0]["content"]) == 1
    schema = by_name["notas.txt"]["output_config"]["format"]["schema"]
    assert UNSORTED in schema["properties"]["destino"]["enum"]
    assert reg.notes()["Matemáticas/Mis apuntes/01 - Tema 1_ Límites/Límites laterales.jpg"][
        "en_una_frase"] == "Sobre Límites laterales"
    assert "✓ IMG_2031.jpg →" in res.text() and "? cosas.txt" in res.text()
    lib = reg.library_items()["Matemáticas/Mis apuntes/01 - Tema 1_ Límites/Límites laterales.jpg"]
    assert (lib["tipo"], lib["tema"], lib["source"]) == ("Apuntes", "01 - Tema 1_ Límites", "propio")


def test_inbox_stops_on_fatal_error(uji):
    box = inbox_dir(uji)
    (box / "a.txt").write_text("a")

    def reply(kw):
        from uji_sync.ai import AIFatalError
        raise AIFatalError("clave no válida")

    client, _ = client_for(reply)
    reg = Registry(registry_path(uji))
    res = InboxOrganizer(uji, reg, client=client, log=lambda _: None).organize()
    assert res.fatal == "clave no válida" and res.moved == []
    assert [p.name for p in inbox_files(uji)] == ["a.txt"]  # el apunte sigue en la bandeja


# ------------------------------------------------------------------ asistente
def test_index_includes_summaries_and_notes(uji):
    reg = Registry(registry_path(uji))
    rec = add_file(reg, uji, "Matemáticas/01 - Tema 1_ Límites/Tema 1.pdf", b"%PDF")
    reg.save_summary(rec.sha256, "claude-opus-5", DATA, 1, 1)
    note = uji / "Matemáticas/Mis apuntes/01 - Tema 1_ Límites/Mis límites.txt"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    reg.save_note("Matemáticas/Mis apuntes/01 - Tema 1_ Límites/Mis límites.txt",
                  "n.txt", "Matemáticas", "01", "Mis límites", "Resumen propio de límites")
    (uji / "Matemáticas/_resumenes_IA/x.md").write_text("no debe salir")
    reg.close()
    index = build_index(uji, ["Matemáticas"])
    assert ("- Matemáticas/01 - Tema 1_ Límites/Tema 1.pdf (apuntes): Límites y derivadas "
            "básicas. Puntos clave: Definición de límite; Regla de la cadena") in index
    assert "Mis límites.txt (apunte propio): Resumen propio de límites" in index
    assert "_resumenes_IA" not in index
    assert "Puntos clave" not in build_index(uji, ["Matemáticas"], detailed=False)


def test_assistant_reads_documents_with_tool(uji):
    doc = uji / "Matemáticas/01 - Tema 1_ Límites/Tema 1.pdf"
    doc.write_bytes(b"%PDF-1.4 limites")
    secret = uji.parent / "secreto.txt"
    secret.write_text("no")

    def reply(kw):
        last = kw["messages"][-1]
        if last["role"] == "user" and isinstance(last["content"], str):
            return SimpleNamespace(stop_reason="tool_use", model=kw["model"], usage=USAGE, content=[
                text_block("Voy a mirar el tema."),
                SimpleNamespace(type="tool_use", id="t1", name="leer_material",
                                input={"ruta": "Matemáticas/01 - Tema 1_ Límites/Tema 1.pdf"}),
                SimpleNamespace(type="tool_use", id="t2", name="leer_material",
                                input={"ruta": "Matemáticas/../../secreto.txt"}),
            ])
        return SimpleNamespace(stop_reason="end_turn", model=kw["model"], usage=USAGE,
                               content=[text_block("Un límite es… (Tema 1.pdf)")])

    client, msgs = client_for(reply)
    a = Assistant(uji, "Matemáticas", client=client)
    reads = []
    answer = a.ask("¿Qué es un límite?", on_read=reads.append)
    assert answer == "Un límite es… (Tema 1.pdf)"
    assert reads == ["Matemáticas/01 - Tema 1_ Límites/Tema 1.pdf"]

    first = msgs.calls[0]
    assert first["tools"][0]["name"] == "leer_material" and first["tools"][0]["strict"] is True
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["cache_control"] == {"type": "ephemeral"}
    assert first["fallbacks"] == "default"
    assert "asignatura «Matemáticas»" in first["system"][0]["text"]

    results = msgs.calls[1]["messages"][-1]["content"]
    assert results[0]["tool_use_id"] == "t1" and results[0]["content"][1]["type"] == "document"
    assert results[1]["tool_use_id"] == "t2" and results[1]["is_error"] is True  # fuera de UJI
    assert a.cost > 0

    # La conversación continúa con el historial completo
    a.ask("¿Y una derivada?")
    sent = msgs.calls[-1]["messages"]
    assert sent[0]["content"] == "¿Qué es un límite?" and sent[4]["content"] == "¿Y una derivada?"
    a.reset()
    assert a.messages == []


def test_assistant_refusal_and_errors_keep_history_clean(uji):
    def refuse(kw):
        return SimpleNamespace(stop_reason="refusal", model=kw["model"], usage=USAGE, content=[])

    client, _ = client_for(refuse)
    a = Assistant(uji, None, client=client)
    assert "no puedo ayudarte" in a.ask("x")
    assert a.messages == []

    def fail(kw):
        raise AIFatalError("sin conexión")

    a._client, _ = client_for(fail)
    with pytest.raises(AIFatalError):
        a.ask("y")
    assert a.messages == []
