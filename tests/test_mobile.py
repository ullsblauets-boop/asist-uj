"""Web para el móvil: seguridad, API y la página en un navegador con tamaño de móvil."""

import json
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError

import pytest

from uji_sync import mobile
from uji_sync.inbox import InboxResult
from uji_sync.mobile import MobileServer

PIN = "123456"


class FakeAssistant:
    def __init__(self, root, course, model):
        self.course, self.cost, self.questions = course, 0.0, []

    def ask(self, question, on_read):
        self.questions.append(question)
        on_read("Matemáticas/01 - Tema 1/Tema 1.pdf")
        self.cost += 0.02
        return f"**Respuesta** {len(self.questions)} sobre {self.course}\n- punto <script>x</script>"


class FakeOrganizer:
    def __init__(self, root, reg, model):
        self.root = root

    def organize(self):
        moved = [(p.name, f"Matemáticas/Mis apuntes/{p.name}") for p in (self.root / "_Bandeja de apuntes").iterdir()
                 if p.name != "LÉEME.txt"]
        return InboxResult(moved=moved)


@pytest.fixture()
def server(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    root = tmp_path / "UJI"
    (root / "Matemáticas/01 - Tema 1").mkdir(parents=True)
    (root / "Matemáticas/_resumenes_IA").mkdir()
    (root / "Matemáticas/_resumenes_IA/Novedades.md").write_text(
        "# Novedades · Matemáticas\n\n## 24/09/2026 18:30\n"
        "- **[Tema 1.pdf](<01 - Tema 1/Tema 1.pdf - resumen.md>)** (Tema 1): Límites.\n\n"
        "## 20/09/2026 10:00\n- viejo\n", encoding="utf-8")
    (root / "secreto.txt").write_text("no")
    srv = MobileServer(root, PIN, "claude-opus-5", port=0, host="127.0.0.1",
                       assistant_factory=FakeAssistant, organizer_factory=FakeOrganizer).start()
    yield srv, root
    srv.stop()


def client(srv):
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
    base = f"http://127.0.0.1:{srv.port}"

    def call(path, data=None, headers=None, raw=False):
        body = data if raw or data is None else json.dumps(data).encode()
        req = urllib.request.Request(base + path, data=body, headers=headers or {},
                                     method="POST" if data is not None else "GET")
        try:
            with opener.open(req) as r:
                return r.status, (r.read() if path == "/" else json.loads(r.read()))
        except HTTPError as e:
            return e.code, json.loads(e.read())
    return call


def test_pin_required_and_lockout(server, monkeypatch):
    srv, _ = server
    call = client(srv)
    assert call("/api/courses")[0] == 401
    assert call("/api/upload", b"x", raw=True)[0] == 401
    for _ in range(mobile.MAX_FAILED_PINS):
        assert call("/api/login", {"pin": "000000"})[0] == 401
    # Bloqueado: ni siquiera el PIN correcto funciona durante un rato
    assert call("/api/login", {"pin": PIN})[0] == 401
    srv.locked_until = 0
    assert call("/api/login", {"pin": PIN})[0] == 200
    assert call("/api/courses") == (200, {"courses": ["Matemáticas"]})


def test_api_flow(server):
    srv, root = server
    call = client(srv)
    call("/api/login", {"pin": PIN})

    # Subidas: el nombre se sanea y nunca sale de la bandeja
    assert call("/api/upload", b"foto", {"X-Filename": "..%2F..%2Fsecreto.txt"}, raw=True)[1] == {"saved": "secreto.txt"}
    assert (root / "secreto.txt").read_text() == "no"
    assert call("/api/upload", b"2", {"X-Filename": "secreto.txt"}, raw=True)[1] == {"saved": "secreto (2).txt"}
    assert call("/api/inbox")[1] == {"files": ["secreto (2).txt", "secreto.txt"]}

    status, data = call("/api/organize", {})
    assert status == 200 and "✓ secreto.txt → Matemáticas/Mis apuntes/secreto.txt" in data["result"]

    # Chat: la conversación se mantiene entre preguntas
    s, r1 = call("/api/chat", {"question": "¿Qué es un límite?", "course": "Matemáticas"})
    assert r1["reads"] == ["Matemáticas/01 - Tema 1/Tema 1.pdf"] and "sobre Matemáticas" in r1["answer"]
    s, r2 = call("/api/chat", {"question": "¿Y otra?", "conversation": r1["conversation"]})
    assert r2["answer"].startswith("**Respuesta** 2") and r2["cost"] == 0.04
    assert call("/api/chat", {"question": "x", "course": "../.."})[1] == {"error": "asignatura desconocida"}
    assert call("/api/chat", {"question": " "})[0] == 400

    news = call("/api/news")[1]["news"]
    assert news == [{"course": "Matemáticas", "when": "24/09/2026 18:30",
                     "items": ["**[Tema 1.pdf](<01 - Tema 1/Tema 1.pdf - resumen.md>)** (Tema 1): Límites."]}]
    assert call("/api/../secreto.txt")[0] in (401, 404)


def test_page_in_mobile_browser(server):
    """La página funciona en un navegador con tamaño de móvil y no inyecta HTML de la IA."""
    pw = pytest.importorskip("playwright.sync_api")
    import os
    srv, root = server
    with pw.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=os.environ.get("UJI_SYNC_BROWSER_PATH"))
        except Exception as e:
            pytest.skip(f"No hay navegador: {e}")
        page = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        page.goto(f"http://127.0.0.1:{srv.port}/")
        page.fill("#pin", "999999")
        page.click("#login-btn")
        page.wait_for_selector("#login-error:has-text('PIN incorrecto')")
        page.fill("#pin", PIN)
        page.click("#login-btn")
        page.wait_for_selector("#tab-chat:not(.hidden)")
        assert page.locator("#course option").all_inner_texts() == ["Todas las asignaturas", "Matemáticas"]
        page.fill("#question", "¿Qué es un límite?")
        page.click("#send")
        bot = page.wait_for_selector(".msg.bot")
        assert bot.inner_html().startswith("<p><b>Respuesta</b>")
        assert "&lt;script&gt;" in bot.inner_html()  # el HTML de la respuesta se muestra como texto
        page.click("nav button[data-tab=notes]")
        page.set_input_files("#files", files=[{"name": "foto.jpg", "mimeType": "image/jpeg", "buffer": b"x"}])
        page.wait_for_selector("#upload-status:has-text('1 archivo')")
        assert (root / "_Bandeja de apuntes" / "foto.jpg").exists()
        page.click("nav button[data-tab=news]")
        page.wait_for_selector("#news .card")
        assert "Tema 1.pdf (Tema 1): Límites." in page.inner_text("#news")
        assert page.evaluate("document.documentElement.scrollWidth <= 390")  # sin scroll horizontal
        page.screenshot(path=str(Path(os.environ.get("UJI_SYNC_SHOT_DIR", root)) / "movil.png"))
        browser.close()
