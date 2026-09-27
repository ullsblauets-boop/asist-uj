"""Búsqueda dentro de los documentos: palabras, significado (modelo simulado) y OCR."""

import zlib

import numpy as np
import pytest

from uji_sync.search import IndexStats, SearchIndex, chunk, extract_segments

# «Significado» simulado: cada concepto es una dirección del espacio.
CONCEPTS = {
    "derivad": 0, "velocidad instant": 0, "tasa de cambio": 0,
    "hormig": 1, "tracci": 1, "acero": 1,
    "paella": 2,
}


class FakeEmbedder:
    error = None

    def available(self):
        return True

    def embed(self, texts):
        out = []
        for t in texts:
            v = np.zeros(64, dtype="float32")
            for key, dim in CONCEPTS.items():
                if key in t.lower():
                    v[dim] += 1
            if not v.any():  # sin concepto: una dirección propia (no se parece a nada)
                v[3 + zlib.crc32(t.lower().encode()) % 61] = 1
            out.append(v / np.linalg.norm(v))
        return np.array(out)


class NoEmbedder:
    error = "falta el paquete fastembed"

    def available(self):
        return False


def make_pdf(path, pages):
    """PDF mínimo con una línea de texto por página (sin librerías extra)."""
    objs, kids = [], []
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 40 700 Td ({text}) Tj ET".encode("latin-1")
        content_id, page_id = 4 + 2 * i, 5 + 2 * i
        kids.append(page_id)
        objs.append((content_id, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"))
        objs.append((page_id, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                              b"/Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % content_id))
    objs = [(1, b"<< /Type /Catalog /Pages 2 0 R >>"),
            (2, b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids))),
            (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")] + objs
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for num, body in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % offsets[n] for n in sorted(offsets))
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    path.write_bytes(bytes(out))


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    r = tmp_path / "UJI Study"
    t3 = r / "Calculo I/03 - Tema 3"
    t3.mkdir(parents=True)
    make_pdf(t3 / "Tema 3.pdf", ["Introduccion al tema de funciones reales.",
                                 "La derivada de f mide la tasa de cambio. Regla de la cadena."])
    (r / "Construccion/02 - Materiales").mkdir(parents=True)
    (r / "Construccion/02 - Materiales/Hormigon.txt").write_text(
        "El hormigón armado resiste la tracción gracias al acero corrugado.", encoding="utf-8")
    notes = r / "Calculo I/Mis apuntes/03 - Tema 3"
    notes.mkdir(parents=True)
    (notes / "pizarra.jpg").write_bytes(b"\xff\xd8 foto")
    make_pdf(r / "Construccion/02 - Materiales/Escaneado.pdf", [""])
    return r


def test_extract_and_chunk(root):
    segs = extract_segments(root / "Calculo I/03 - Tema 3/Tema 3.pdf")
    assert [loc for loc, _ in segs] == ["pág. 1", "pág. 2"] and "derivada" in segs[1][1]
    long = [("pág. 1", "Frase número uno. " * 200)]
    pieces = chunk(long)
    assert len(pieces) > 3 and all(len(t) <= 900 for _, t in pieces) and pieces[0][0] == "pág. 1"


def test_keyword_semantic_and_ocr(root):
    idx = SearchIndex(root, embedder=FakeEmbedder())
    st = idx.status()
    assert (st["documents"], st["pending"]) == (4, 4)

    stats = idx.update()
    assert stats.indexed == 2 and sorted(stats.no_text) == [
        "Calculo I/Mis apuntes/03 - Tema 3/pizarra.jpg", "Construccion/02 - Materiales/Escaneado.pdf"]
    assert idx.status()["pending"] == 0 and len(idx.ocr_candidates()) == 2

    # Palabras: sin tildes ni mayúsculas, con la página y el fragmento resaltado
    res = idx.search("REGLA de la CADENA")
    assert res[0]["path"] == "Calculo I/03 - Tema 3/Tema 3.pdf" and res[0]["loc"] == "pág. 2"
    assert "\u0002cadena\u0003" in res[0]["snippet"].lower() and "palabras" in res[0]["match"]
    assert idx.search("hormigon")[0]["path"].endswith("Hormigon.txt")  # sin tilde encuentra «hormigón»

    # Significado: «velocidad instantánea» encuentra la derivada aunque no comparta palabras
    res = idx.search("velocidad instantánea")
    assert res[0]["path"].endswith("Tema 3.pdf") and res[0]["match"] == ["significado"]
    assert idx.search("velocidad instantánea", paths={"Construccion/02 - Materiales/Hormigon.txt"}) == []
    assert idx.search("receta de paella") == []  # nada relacionado

    # OCR con IA: una sola vez por archivo; el texto pasa al índice
    calls = []

    def ocr(path):
        calls.append(path.name)
        return (f"Apuntes a mano: la derivada del seno es el coseno ({path.name})", 0.01)

    stats = idx.update(ocr=ocr)
    assert sorted(calls) == ["Escaneado.pdf", "pizarra.jpg"] and stats.ocr_done == 2
    assert idx.ocr_candidates() == []
    assert any(r["path"].endswith("pizarra.jpg") for r in idx.search("coseno"))
    idx.update(ocr=ocr)
    assert len(calls) == 2  # no se vuelve a pagar

    # Cambios: un archivo modificado se reindexa; uno borrado sale del índice
    (root / "Construccion/02 - Materiales/Hormigon.txt").write_text("Vigas de madera laminada.", encoding="utf-8")
    (root / "Calculo I/03 - Tema 3/Tema 3.pdf").unlink()
    stats = idx.update()
    assert (stats.indexed, stats.removed) == (1, 1)
    assert idx.search("hormigon") == [] and idx.search("madera")[0]["path"].endswith("Hormigon.txt")
    assert idx.search("cadena") == []
    idx.close()


def test_without_semantic_model(root):
    idx = SearchIndex(root, embedder=NoEmbedder())
    stats = idx.update()
    assert stats.semantic_error == "falta el paquete fastembed"
    assert "no disponible" in stats.text()
    assert idx.search("derivada")[0]["match"] == ["palabras"]  # la búsqueda por palabras sigue funcionando
    assert idx.status()["semantic"]["available"] is False
    idx.close()


def test_stats_text():
    s = IndexStats(indexed=3, ocr_done=1, cost=0.02)
    assert "3 documentos indexados" in s.text() and "0,02 US$" in s.text()
