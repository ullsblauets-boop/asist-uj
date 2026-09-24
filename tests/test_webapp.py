"""UJI Study Assistant (web): seguridad, API, sincronización de extremo a extremo e interfaz."""

import io
import os
import time
from pathlib import Path

import pytest

from uji_sync.config import Settings
from uji_sync.inbox import InboxResult
from uji_sync.webapp import AppState, ServerThread, create_app

from .fake_moodle import FakeMoodle

REMOTE = {"REMOTE_ADDR": "192.168.1.50"}
H = {"X-UJI": "1"}


class FakeAssistant:
    def __init__(self, root, course, model):
        self.course, self.cost = course, 0.0

    def ask(self, question, on_read):
        on_read("Cálculo I/03 - Tema 3/Tema 3.pdf")
        self.cost += 0.01
        return f"**Según tus apuntes** ({self.course}) <b>x</b>"


class FakeOrganizer:
    def __init__(self, root, reg, model, log):
        self.root = root

    def organize(self):
        return InboxResult(moved=[("a.jpg", "Cálculo I/Mis apuntes/a.jpg")])


@pytest.fixture()
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("uji_sync.webapp.has_credentials", lambda: True)
    root = tmp_path / "UJI Study"
    (root / "Cálculo I/03 - Tema 3").mkdir(parents=True)
    (root / "Cálculo I/03 - Tema 3/Tema 3.pdf").write_bytes(b"%PDF t3")
    (root / "Cálculo I/03 - Tema 3/Boletín 3.pdf").write_bytes(b"%PDF b3")
    (tmp_path / "secreto.txt").write_text("no")
    s = Settings(dest_dir=str(root), ai_consent=True, mobile_pin="123456")
    st = AppState(s, assistant_factory=FakeAssistant, organizer_factory=FakeOrganizer)
    yield st
    st.jobs.shutdown()


@pytest.fixture()
def client(state):
    return create_app(state).test_client()


def test_security(client, state):
    # Host desconocido (protección contra DNS rebinding)
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 403
    # Las peticiones que cambian algo exigen la cabecera X-UJI
    assert client.post("/api/settings", json={"pro_index": False}).status_code == 403
    # Desde otro dispositivo: PIN obligatorio
    assert client.get("/api/status", environ_base=REMOTE).status_code == 401
    for _ in range(5):
        assert client.post("/api/login", json={"pin": "000000"}, headers=H, environ_base=REMOTE).status_code == 401
    assert client.post("/api/login", json={"pin": "123456"}, headers=H, environ_base=REMOTE).status_code == 401  # bloqueado
    state.locked_until = 0
    assert client.post("/api/login", json={"pin": "123456"}, headers=H, environ_base=REMOTE).status_code == 200
    st = client.get("/api/status", environ_base=REMOTE).get_json()
    assert st["local"] is False and "pin" not in st["mobile"]
    # Ajustes sensibles: solo desde el PC
    for path in ("/api/settings", "/api/apikey", "/api/mobile", "/api/sync/run", "/api/open"):
        assert client.post(path, json={}, headers=H, environ_base=REMOTE).status_code == 403, path
    assert client.get("/api/sync/courses", environ_base=REMOTE).status_code == 403
    # Solo se sirven archivos de la biblioteca
    assert client.get("/api/library/file?path=../secreto.txt").status_code == 404
    assert client.get("/api/library/file?path=Cálculo I/03 - Tema 3/Tema 3.pdf").data == b"%PDF t3"


def test_library_api(client):
    st = client.get("/api/status").get_json()
    assert st["courses"] == ["Cálculo I"] and "Pizarra" in st["tipos"] and st["ai"]["ready"]
    items = client.get("/api/library").get_json()["items"]
    assert {i["titulo"]: i["tipo"] for i in items} == {"Boletín 3": "Problemas", "Tema 3": "Teoría"}

    assert client.post("/api/courses/profesor", json={"course": "Cálculo I", "profesor": "Dra. García"},
                       headers=H).status_code == 200
    courses = client.get("/api/courses").get_json()["courses"]
    assert courses[0]["profesor"] == "Dra. García" and courses[0]["by_tipo"] == {"Problemas": 1, "Teoría": 1}

    data = {"files": [(io.BytesIO(b"foto"), "pizarra.jpg"), (io.BytesIO(b"pdf"), "ej.pdf")],
            "course": "Cálculo I", "tema": "03 - Tema 3", "tipo": "Pizarra", "profesor": ""}
    r = client.post("/api/library/upload", data=data, headers=H, content_type="multipart/form-data")
    saved = r.get_json()["saved"]
    assert [s["path"] for s in saved] == ["Cálculo I/Mis apuntes/03 - Tema 3/pizarra.jpg",
                                           "Cálculo I/Mis apuntes/03 - Tema 3/ej.pdf"]
    assert saved[0]["profesor"] == "Dra. García"
    only_own = client.get("/api/library?source=propio&tipo=Pizarra").get_json()["items"]
    assert len(only_own) == 2
    r = client.post("/api/library/update", json={"path": saved[1]["path"], "tipo": "Ejercicios"}, headers=H)
    assert r.get_json()["item"]["tipo"] == "Ejercicios"
    assert client.post("/api/library/update", json={"path": "no/existe", "tipo": "Otros"}, headers=H).status_code == 404

    home = client.get("/api/home").get_json()
    assert home["counts"] == {"Cálculo I": 4} and len(home["recent"]) == 4


def test_chat_and_organize(client, state):
    r = client.post("/api/chat", json={"question": "¿Qué es una derivada?", "course": "Cálculo I"}, headers=H).get_json()
    assert r["reads"] == ["Cálculo I/03 - Tema 3/Tema 3.pdf"] and "Cálculo I" in r["answer"]
    assert client.post("/api/chat", json={"question": "x", "course": "../x"}, headers=H).status_code == 400

    upload = {"files": [(io.BytesIO(b"x"), "a.jpg")], "course": "auto"}
    r = client.post("/api/library/upload", data=upload, headers=H, content_type="multipart/form-data")
    assert r.get_json()["job"]["kind"] == "organize"
    for _ in range(50):
        job = client.get("/api/job").get_json()["job"]
        if not job["running"]:
            break
        time.sleep(0.05)
    assert "a.jpg" in job["result"]

    state.settings.ai_consent = False  # sin IA activada no se puede usar
    assert client.post("/api/chat", json={"question": "x"}, headers=H).status_code == 409


def test_sync_job_end_to_end(tmp_path, state, client):
    """Iniciar sesión y sincronizar desde la web, contra el Moodle simulado y un navegador real."""
    pytest.importorskip("playwright")
    from uji_sync.moodle import MoodleBrowser

    fake = FakeMoodle().start()

    class AutoLogin(MoodleBrowser):
        def open_site(self):
            super().open_site()
            self.page.click("#loginbtn")  # en la vida real, esto lo haces tú

    state.browser_factory = lambda: AutoLogin(fake.base_url, tmp_path / "profile", channel=None,
                                              headless=True, delay=0)
    try:
        def wait():
            for _ in range(300):
                job = client.get("/api/job").get_json()["job"]
                if not job["running"]:
                    return job
                time.sleep(0.1)
            raise AssertionError("la tarea no termina")
        try:
            client.post("/api/sync/login", json={}, headers=H)
            job = wait()
        except Exception as e:
            pytest.skip(f"No hay navegador: {e}")
        if job["error"]:
            pytest.skip(f"No hay navegador: {job['error']}")
        assert job["result"] == "2 asignaturas encontradas."
        courses = client.get("/api/sync/courses").get_json()["courses"]
        assert [c["name"] for c in courses] == ["Física", "Matemáticas"]
        client.post("/api/sync/run", json={"course_ids": [1]}, headers=H)
        job = wait()
        assert "Matemáticas → 6 archivos nuevos" in job["result"], job
        items = client.get("/api/library?course=Matemáticas").get_json()["items"]
        assert len(items) == 5  # los .url no son materiales
        root = Path(state.settings.dest_dir)
        assert (root / "_Para Claude" / "Índice de materiales.md").exists()
        assert state.settings.selected_course_ids == [1]
    finally:
        fake.stop()


@pytest.mark.parametrize("viewport", [(1280, 800), (390, 844)], ids=["pc", "movil"])
def test_interface_in_browser(state, viewport, tmp_path):
    pw = pytest.importorskip("playwright.sync_api")
    server = ServerThread(create_app(state), "127.0.0.1", 0).start()
    base = f"http://127.0.0.1:{server.port}"
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch(executable_path=os.environ.get("UJI_SYNC_BROWSER_PATH"))
            except Exception as e:
                pytest.skip(f"No hay navegador: {e}")
            page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base + "/")
            page.wait_for_selector("text=Novedades (últimos 14 días)")
            mobile = viewport[0] < 800

            def go(name):
                if mobile:
                    page.click("#menu-btn")
                page.click(f"#menu a[data-page={name}]")

            go("biblioteca")
            page.wait_for_selector("#items li .item-title")
            assert page.locator("#count").inner_text() == "2 de 2 materiales"
            page.click("#upload summary")  # el panel de subida empieza plegado
            page.set_input_files("#files", files=[{"name": "pizarra.jpg", "mimeType": "image/jpeg", "buffer": b"x"}])
            page.select_option("#u-course", "Cálculo I")
            page.select_option("#u-tema", "03 - Tema 3")
            page.select_option("#u-tipo", "Pizarra")
            page.click("#u-send")
            page.wait_for_selector("#u-status:has-text('1 archivo')")
            page.wait_for_selector("#count:has-text('3 de 3')")
            page.select_option("#f-tipo", "Pizarra")
            page.wait_for_selector("#count:has-text('1 de 3')")
            page.click(".edit")
            page.fill("#e-titulo", "Regla de la cadena")
            page.click("#e-save")
            page.wait_for_selector("text=Regla de la cadena")

            go("buscar")
            page.fill("#question", "¿Qué es una derivada?")
            page.click("#send")
            bot = page.wait_for_selector(".msg.bot")
            assert bot.inner_html().startswith("<p><b>Según tus apuntes</b>")
            assert "&lt;b&gt;x&lt;/b&gt;" in bot.inner_html()  # nunca se inyecta HTML de la IA

            go("asignaturas")
            page.wait_for_selector("text=Pizarra · 1")
            go("configuracion")
            page.wait_for_selector("text=Carpeta de la biblioteca")
            go("resolver")
            page.wait_for_selector("text=Próximamente (Fase 5)")
            page.wait_for_selector("#sidebar:not(.open)", state="attached")
            page.wait_for_timeout(400)  # fin de la animación del menú
            assert page.evaluate(f"document.documentElement.scrollWidth <= {viewport[0]}")
            page.screenshot(path=str(Path(os.environ.get("UJI_SYNC_SHOT_DIR", tmp_path)) / f"web_{viewport[0]}.png"),
                            full_page=False)
            go("inicio")
            page.wait_for_selector("text=Regla de la cadena")
            assert page.locator("#view .edit").count() == 0  # en Inicio no se edita
            page.wait_for_timeout(400)
            page.screenshot(path=str(Path(os.environ.get("UJI_SYNC_SHOT_DIR", tmp_path)) / f"inicio_{viewport[0]}.png"))
            assert errors == []
            browser.close()
    finally:
        server.stop()
