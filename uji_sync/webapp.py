"""UJI Study Assistant: aplicación web local (PC y móvil).

Se abre en el navegador del PC (http://127.0.0.1:8765). Opcionalmente se
puede activar el acceso desde el móvil en la wifi de casa, protegido con PIN.

Seguridad:
  - Desde el propio PC no hace falta PIN; desde otro dispositivo, sí.
  - Los ajustes sensibles (clave de API, carpeta, sincronizar, móvil) solo se
    pueden cambiar desde el PC.
  - Las peticiones que cambian algo exigen la cabecera X-UJI (una web ajena no
    puede enviarla sin permiso del navegador) y un Host conocido.
  - Solo se sirven archivos que están en la biblioteca.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path, PurePosixPath

from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.serving import make_server

from . import __version__
from .ai import (
    DEFAULT_MODEL, MODELS, AIError, AIFatalError, AIProcessor, make_client, needs_api, pending,
)
from .apikey import delete_api_key, has_credentials, set_api_key
from .assistant import Assistant
from .claude_pro import PRO_DIR, write_pro_files
from .config import BASE_URL, Settings, browser_profile_dir, find_google_drive, registry_path
from .inbox import InboxOrganizer, inbox_dir, inbox_files
from .jobs import Busy, JobManager
from .library import (
    SOURCES, TIPOS, add_upload, filter_items, list_courses, list_sections, recent_items,
    sync_library, update_item,
)
from .registry import Registry
from .search import LocalEmbedder, SearchIndex, claude_ocr
from .solver import AVAILABLE_MODES, MODES, SOLUTIONS_DIR, ExerciseSolver, history
from .sync import Syncer, format_summary

PORT = 8765
MOBILE_PORT = 8766
MAX_UPLOAD = 25 * 1024 * 1024
MAX_FAILED_PINS = 5
LOCKOUT_SECONDS = 60
AI_CONFIRM_OVER = 20
LOCAL_ADDRS = {"127.0.0.1", "::1"}
STATIC = Path(__file__).parent / "web"


def lan_ip() -> str:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def new_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"


class AppState:
    def __init__(self, settings: Settings, browser_factory=None, assistant_factory=None,
                 organizer_factory=None, processor_factory=None, embedder=None, ocr_factory=None,
                 solver_factory=None):
        self.settings = settings
        self.solver_factory = solver_factory or (
            lambda root, model: ExerciseSolver(root, self.search_for_assistant, model=model))
        self.embedder = embedder if embedder is not None else LocalEmbedder()
        self.ocr_factory = ocr_factory or (lambda model: claude_ocr(make_client(), model))
        self.jobs = JobManager()
        self.sessions: set[str] = set()
        self.failed = 0
        self.locked_until = 0.0
        self.lock = threading.Lock()
        self.conversations: dict[str, tuple[Assistant, threading.Lock]] = {}
        self.mobile_server = None
        self.browser_factory = browser_factory or (
            lambda: MoodleBrowserLazy())
        self.assistant_factory = assistant_factory or (
            lambda root, course, model: Assistant(root, course, model=model,
                                                  searcher=self.search_for_assistant))
        self.organizer_factory = organizer_factory or (
            lambda root, reg, model, log: InboxOrganizer(root, reg, model=model, log=log))
        self.processor_factory = processor_factory or (
            lambda root, reg, model, log: AIProcessor(root, reg, model=model, log=log))

    @property
    def root(self) -> Path:
        return Path(self.settings.dest_dir).expanduser()

    def ai_ready(self) -> bool:
        return self.settings.ai_consent and has_credentials()

    def registry(self) -> Registry:
        return Registry(registry_path(self.root))

    # ---------------------------------------------------------- búsqueda (Fase 4)
    def search_index(self) -> SearchIndex:
        return SearchIndex(self.root, embedder=self.embedder)

    def index_update(self, log, ocr: bool = False, auto: bool = False):
        """Actualiza el índice. Con ocr=True (y la IA activada) lee fotos y escaneados.
        En modo automático (tras sincronizar u organizar) no lee más de AI_CONFIRM_OVER."""
        idx = self.search_index()
        try:
            ocr_fn = None
            if ocr and self.ai_ready():
                if auto and len(idx.ocr_candidates()) > AI_CONFIRM_OVER:
                    log("Hay muchas fotos sin leer: usa «Leer fotos con IA» en Buscar.")
                else:
                    ocr_fn = self.ocr_factory(self.settings.ai_model)
            return idx.update(log=log, ocr=ocr_fn, should_stop=self.jobs.stop.is_set)
        finally:
            idx.close()

    def search_for_assistant(self, query: str, courses: list[str]) -> list[dict]:
        idx = self.search_index()
        try:
            hits = idx.search(query, limit=12)
        finally:
            idx.close()
        reg = self.registry()
        try:
            tags = reg.library_items()
        finally:
            reg.close()
        out = []
        for h in hits:
            if h["path"].split("/", 1)[0] in courses:
                tag = tags.get(h["path"], {})
                out.append({**h, "tipo": tag.get("tipo", ""), "source": tag.get("source", "")})
        return out[:8]

    def check_pin(self, pin: str) -> str | None:
        with self.lock:
            if time.monotonic() < self.locked_until or not self.settings.mobile_pin:
                return None
            if secrets.compare_digest(pin, self.settings.mobile_pin):
                self.failed = 0
                token = secrets.token_urlsafe(32)
                self.sessions.add(token)
                return token
            self.failed += 1
            if self.failed >= MAX_FAILED_PINS:
                self.locked_until = time.monotonic() + LOCKOUT_SECONDS
                self.failed = 0
            return None


def MoodleBrowserLazy():
    from .moodle import MoodleBrowser

    return MoodleBrowser(BASE_URL, browser_profile_dir())


def create_app(state: AppState) -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD + 1024 * 1024

    def is_local() -> bool:
        return request.remote_addr in LOCAL_ADDRS

    def err(msg: str, code: int = 400):
        resp = jsonify({"error": msg})
        resp.status_code = code
        return resp

    def local_only():
        if not is_local():
            abort(err("Esta opción solo está disponible en el PC.", 403))

    def require_ai():
        if not state.ai_ready():
            abort(err("Activa la IA en Configuración (clave de API y aviso de privacidad).", 409))

    @app.before_request
    def security():
        host = (request.host or "").rsplit(":", 1)[0].strip("[]")
        if host not in ("127.0.0.1", "localhost", "::1", lan_ip()):
            abort(403)  # protege contra «DNS rebinding»
        if not request.path.startswith("/api/"):
            return None
        if request.method != "GET" and request.headers.get("X-UJI") != "1":
            abort(err("Petición no permitida", 403))
        if request.path == "/api/login" or is_local():
            return None
        token = request.cookies.get("ujistudy")
        if not token or token not in state.sessions:
            abort(err("Introduce el PIN", 401))
        return None

    @app.after_request
    def headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        if resp.mimetype == "text/html":
            resp.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'")
        return resp

    # ------------------------------------------------------------ páginas
    @app.get("/")
    def index():
        return send_from_directory(STATIC, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(STATIC, name)

    @app.get("/manifest.json")
    def manifest():
        return jsonify({"name": "UJI Study Assistant", "short_name": "UJI Study", "start_url": "/",
                        "display": "standalone", "background_color": "#ffffff",
                        "theme_color": "#b8003a"})

    @app.post("/api/login")
    def login():
        pin = str((request.get_json(silent=True) or {}).get("pin", ""))
        token = state.check_pin(pin)
        if token is None:
            return err("PIN incorrecto (o demasiados intentos: espera un minuto)", 401)
        resp = jsonify({"ok": True})
        resp.set_cookie("ujistudy", token, httponly=True, samesite="Strict")
        return resp

    # ------------------------------------------------------------ estado
    @app.get("/api/status")
    def status():
        s = state.settings
        data = {
            "version": __version__, "local": is_local(), "dest": s.dest_dir,
            "courses": list_courses(state.root), "tipos": TIPOS, "sources": SOURCES,
            "ai": {"ready": state.ai_ready(), "consent": s.ai_consent, "has_key": has_credentials(),
                   "enabled": s.ai_enabled, "model": s.ai_model, "models": MODELS},
            "pro_index": s.pro_index, "ocr_enabled": s.ocr_enabled, "job": state.jobs.current(),
            "logged_in": bool(state.jobs.state.get("moodle_courses")),
            "mobile": {"enabled": state.mobile_server is not None},
            "inbox": len(inbox_files(state.root)),
        }
        if is_local() and state.mobile_server is not None:
            data["mobile"].update(url=f"http://{lan_ip()}:{MOBILE_PORT}", pin=s.mobile_pin)
        return jsonify(data)

    @app.get("/api/home")
    def home():
        reg = state.registry()
        try:
            items = sync_library(state.root, reg)
            last = reg.last_run()
        finally:
            reg.close()
        counts: dict[str, int] = {}
        for it in items.values():
            counts[it["course"]] = counts.get(it["course"], 0) + 1
        return jsonify({"last_sync": last, "recent": recent_items(items)[:30],
                        "counts": counts, "inbox": len(inbox_files(state.root))})

    @app.get("/api/job")
    def job():
        return jsonify({"job": state.jobs.current()})

    # ------------------------------------------------------------ asignaturas
    @app.get("/api/courses")
    def courses():
        reg = state.registry()
        try:
            items = sync_library(state.root, reg)
            profes = reg.course_profesores()
        finally:
            reg.close()
        out = []
        for c in list_courses(state.root):
            by_tipo: dict[str, int] = {}
            for it in items.values():
                if it["course"] == c:
                    by_tipo[it["tipo"]] = by_tipo.get(it["tipo"], 0) + 1
            out.append({"name": c, "temas": list_sections(state.root, c),
                        "profesor": profes.get(c, ""), "by_tipo": by_tipo,
                        "total": sum(by_tipo.values())})
        return jsonify({"courses": out})

    @app.post("/api/courses/profesor")
    def set_profesor():
        data = request.get_json(force=True)
        course, profesor = data.get("course"), str(data.get("profesor", "")).strip()
        if course not in list_courses(state.root):
            return err("Asignatura desconocida")
        reg = state.registry()
        try:
            reg.set_course_profesor(course, profesor)
            items = sync_library(state.root, reg)
            for it in items.values():  # rellenar el profesor donde aún no hay
                if it["course"] == course and not it["profesor"]:
                    reg.save_library_item({**it, "profesor": profesor})
        finally:
            reg.close()
        return jsonify({"ok": True})

    # ------------------------------------------------------------ biblioteca
    @app.get("/api/library")
    def library():
        a = request.args
        reg = state.registry()
        try:
            items = sync_library(state.root, reg)
        finally:
            reg.close()
        found = filter_items(items, a.get("course"), a.get("tema"), a.get("tipo"),
                             a.get("profesor"), a.get("source"), a.get("q"))
        return jsonify({"items": found, "total": len(items)})

    @app.post("/api/library/update")
    def library_update():
        data = request.get_json(force=True)
        reg = state.registry()
        try:
            sync_library(state.root, reg)
            if data.get("path") not in reg.library_items():
                return err("Archivo no encontrado", 404)
            item = update_item(state.root, reg, data["path"], data)
        except ValueError as e:
            return err(str(e))
        finally:
            reg.close()
        return jsonify({"item": item})

    @app.post("/api/library/upload")
    def library_upload():
        files = request.files.getlist("files")
        if not files:
            return err("No has elegido ningún archivo")
        f = request.form
        course = f.get("course", "")
        if course == "auto":
            # Automático: a la bandeja, y la IA decide asignatura, tema y tipo.
            require_ai()
            box = inbox_dir(state.root)
            from .fsutils import safe_name
            from .library import free_path
            for up in files:
                name = safe_name(Path(up.filename or "apunte").name, fallback="apunte")
                rel = free_path(box, PurePosixPath(name))
                up.save(box / rel)
            return _start_organize()
        reg = state.registry()
        try:
            saved = [add_upload(state.root, reg, up.filename or "apunte", up.read(), course,
                                f.get("tema", ""), f.get("tipo", "Apuntes"),
                                f.get("profesor", ""), f.get("titulo", "") if len(files) == 1 else "")
                     for up in files]
        except ValueError as e:
            return err(str(e))
        finally:
            reg.close()
        return jsonify({"saved": saved, "indexing": _start_index(ocr=state.settings.ocr_enabled)})

    def _start_index(ocr: bool) -> bool:
        """Indexa en segundo plano si no hay otra tarea en marcha."""
        def run(job):
            return state.index_update(job.log.append, ocr=ocr, auto=True).text()
        try:
            state.jobs.submit("index", "Actualizar índice de búsqueda", run)
            return True
        except Busy:
            return False

    # ------------------------------------------------------------ búsqueda
    @app.get("/api/search")
    def search():
        a = request.args
        q = a.get("q", "").strip()
        if not q:
            return jsonify({"results": []})
        reg = state.registry()
        try:
            items = sync_library(state.root, reg)
        finally:
            reg.close()
        filtered = any(a.get(k) for k in ("course", "tema", "tipo", "source"))
        paths = ({i["path"] for i in filter_items(items, a.get("course"), a.get("tema"), a.get("tipo"),
                                                   None, a.get("source"))} if filtered else None)
        idx = state.search_index()
        try:
            hits = idx.search(q, paths=paths, limit=30)
        finally:
            idx.close()
        for h in hits:
            it = items.get(h["path"], {})
            h.update(titulo=it.get("titulo", PurePosixPath(h["path"]).stem), tipo=it.get("tipo", ""),
                     course=it.get("course", ""), tema=it.get("tema", ""), source=it.get("source", ""))
            h.pop("text", None)
        return jsonify({"results": hits})

    @app.get("/api/search/status")
    def search_status():
        idx = state.search_index()
        try:
            st = idx.status()
            st["ocr_candidates"] = len(idx.ocr_candidates())
        finally:
            idx.close()
        return jsonify(st)

    @app.post("/api/search/index")
    def search_reindex():
        ocr = bool((request.get_json(silent=True) or {}).get("ocr"))
        if ocr:
            local_only()  # leer fotos con IA tiene coste: solo desde el PC
            require_ai()

        def run(job):
            return state.index_update(job.log.append, ocr=ocr).text()
        try:
            title = "Leer fotos con IA e indexar" if ocr else "Actualizar índice de búsqueda"
            return jsonify({"job": state.jobs.submit("index", title, run).as_dict()})
        except Busy as e:
            return err(str(e), 409)

    @app.get("/api/library/file")
    def library_file():
        rel = request.args.get("path", "")
        reg = state.registry()
        try:
            known = rel in sync_library(state.root, reg)
        finally:
            reg.close()
        path = (state.root / rel).resolve()
        if not known or not path.is_file() or state.root.resolve() not in path.parents:
            abort(404)
        return send_file(path, as_attachment=request.args.get("download") == "1")

    # ------------------------------------------------------------ bandeja
    @app.get("/api/inbox")
    def inbox():
        return jsonify({"files": [p.name for p in inbox_files(state.root)],
                        "folder": str(inbox_dir(state.root))})

    def _start_organize():
        model = state.settings.ai_model

        def run(job):
            reg = state.registry()
            try:
                org = state.organizer_factory(state.root, reg, model, job.log.append)
                text = org.organize().text()
                sync_library(state.root, reg)
            finally:
                reg.close()
            state.index_update(job.log.append, ocr=state.settings.ocr_enabled, auto=True)
            return text
        try:
            return jsonify({"job": state.jobs.submit("organize", "Organizar apuntes", run).as_dict()})
        except Busy as e:
            return err(str(e), 409)

    @app.post("/api/inbox/organize")
    def organize():
        require_ai()
        return _start_organize()

    # ------------------------------------------------------------ asistente
    @app.post("/api/chat")
    def chat():
        require_ai()
        data = request.get_json(force=True)
        question = str(data.get("question", "")).strip()
        if not question:
            return err("Escribe una pregunta")
        course = data.get("course") or None
        with state.lock:
            entry = state.conversations.get(data.get("conversation") or "")
            conversation = data.get("conversation")
            if entry is None:
                if course and course not in list_courses(state.root):
                    return err("Asignatura desconocida")
                try:
                    assistant = state.assistant_factory(state.root, course, state.settings.ai_model)
                except AIError as e:
                    return err(str(e))
                conversation = secrets.token_urlsafe(12)
                entry = (assistant, threading.Lock())
                state.conversations[conversation] = entry
        assistant, conv_lock = entry
        reads: list[str] = []
        try:
            with conv_lock:
                answer = assistant.ask(question, on_read=reads.append)
        except (AIError, AIFatalError) as e:
            return jsonify({"error": str(e), "conversation": conversation})
        return jsonify({"conversation": conversation, "answer": answer, "reads": reads,
                        "cost": round(assistant.cost, 4)})

    # ------------------------------------------------------------ resolver ejercicio
    @app.post("/api/solve")
    def solve():
        require_ai()
        f = request.form
        mode = f.get("mode", "pasos")
        if mode not in AVAILABLE_MODES:
            return err("Ese modo llegará en la Fase 6.")
        course = None if f.get("course", "auto") == "auto" else f.get("course")
        tema = None if f.get("tema", "auto") in ("auto", "") else f.get("tema")
        if course and course not in list_courses(state.root):
            return err("Asignatura desconocida")
        if tema and (not course or tema not in list_sections(state.root, course)):
            return err("Tema desconocido")
        text = f.get("text", "").strip()[:8000]
        upload = request.files.get("file")
        if not text and not upload:
            return err("Sube una foto o escribe el enunciado.")
        tmp = None
        try:
            if upload:
                from .config import app_dir
                from .fsutils import safe_name
                tmp_dir = app_dir() / "tmp"
                tmp_dir.mkdir(parents=True, exist_ok=True)
                tmp = tmp_dir / f"{secrets.token_hex(8)}-{safe_name(Path(upload.filename or 'foto.jpg').name)}"
                upload.save(tmp)
            solver = state.solver_factory(state.root, state.settings.ai_model)
            sol = solver.solve(tmp, text, course, tema, mode)
        except (AIError, AIFatalError) as e:
            return jsonify({"error": str(e)})
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
        return jsonify(sol.as_dict())

    @app.get("/api/solve/history")
    def solve_history():
        # Lista de pares para conservar el orden (Resultado → Modo profesor)
        return jsonify({"items": history(state.root), "modes": [[k, v] for k, v in MODES.items()],
                        "available": list(AVAILABLE_MODES)})

    @app.get("/api/solve/file")
    def solve_file():
        rel = PurePosixPath(request.args.get("path", ""))
        path = (state.root / rel).resolve()
        if (SOLUTIONS_DIR not in rel.parts or ".." in rel.parts or not path.is_file()
                or state.root.resolve() not in path.parents):
            abort(404)
        return send_file(path, mimetype="text/plain; charset=utf-8")

    # ------------------------------------------------------------ sincronizar (solo PC)
    @app.post("/api/sync/login")
    def sync_login():
        local_only()
        include_past = bool((request.get_json(silent=True) or {}).get("include_past"))

        def run(job):
            js = state.jobs.state
            if js.get("browser") is None:
                js["browser"] = state.browser_factory()
                js["browser"].start()
            browser = js["browser"]
            job.log.append("Se ha abierto el navegador: inicia sesión en el Aula Virtual.")
            browser.open_site()
            browser.wait_for_login(should_stop=state.jobs.stop.is_set)
            job.log.append("✓ Sesión iniciada. Buscando tus asignaturas…")
            js["moodle_courses"] = browser.get_courses(include_past)
            return f"{len(js['moodle_courses'])} asignaturas encontradas."
        try:
            return jsonify({"job": state.jobs.submit("login", "Iniciar sesión", run).as_dict()})
        except Busy as e:
            return err(str(e), 409)

    @app.get("/api/sync/courses")
    def sync_courses():
        local_only()
        courses = state.jobs.state.get("moodle_courses") or []
        return jsonify({"courses": [{"id": c.id, "name": c.fullname} for c in courses],
                        "selected": state.settings.selected_course_ids})

    @app.post("/api/sync/run")
    def sync_run():
        local_only()
        data = request.get_json(force=True)
        ids = {int(i) for i in data.get("course_ids", [])}
        courses = [c for c in state.jobs.state.get("moodle_courses") or [] if c.id in ids]
        if not courses:
            return err("Marca al menos una asignatura (e inicia sesión antes).")
        dry_run = bool(data.get("dry_run"))
        summarize = bool(data.get("summarize")) and state.ai_ready()
        s = state.settings
        s.selected_course_ids = sorted(ids)
        s.save()
        root, model, pro = state.root, s.ai_model, s.pro_index

        def run(job):
            browser = state.jobs.state["browser"]
            syncer = Syncer(browser, root, dry_run=dry_run, log=job.log.append,
                            should_stop=state.jobs.stop.is_set)
            try:
                results = syncer.sync(courses)
            finally:
                syncer.close()
            text = format_summary(results, dry_run)
            if dry_run:
                return text
            reg = state.registry()
            try:
                sync_library(root, reg)
                keys = [k for r in results for k in r.changed_keys]
                if summarize and keys:
                    recs = [r for k in keys if (r := reg.get(k))]
                    to_send = sum(needs_api(reg, r) for r in recs)
                    if to_send > AI_CONFIRM_OVER:
                        text += (f"\n\nHay {to_send} archivos nuevos para resumir: no se han "
                                 "resumido automáticamente. Usa «Resumir pendientes».")
                    else:
                        proc = state.processor_factory(root, reg, model, job.log.append)
                        text += "\n\n" + proc.process(recs).text()
                        sync_library(root, reg)
            finally:
                reg.close()
            if pro:
                write_pro_files(root, results)
                job.log.append(f"📋 Índice para Claude actualizado en {PRO_DIR}/")
            job.log.append("🔎 Actualizando el índice de búsqueda…")
            stats = state.index_update(job.log.append, ocr=state.settings.ocr_enabled, auto=True)
            return text + "\n\n" + stats.text()
        try:
            return jsonify({"job": state.jobs.submit("sync", "Sincronizar", run).as_dict()})
        except Busy as e:
            return err(str(e), 409)

    @app.get("/api/summaries/pending")
    def summaries_pending():
        local_only()
        reg = state.registry()
        try:
            recs = pending(reg, state.root)
            return jsonify({"pending": len(recs), "to_send": sum(needs_api(reg, r) for r in recs)})
        finally:
            reg.close()

    @app.post("/api/summaries/run")
    def summaries_run():
        local_only()
        require_ai()
        root, model = state.root, state.settings.ai_model

        def run(job):
            reg = state.registry()
            try:
                proc = state.processor_factory(root, reg, model, job.log.append)
                text = proc.process(pending(reg, root)).text() or "No había nada que resumir."
                sync_library(root, reg)
                return text
            finally:
                reg.close()
        try:
            return jsonify({"job": state.jobs.submit("summaries", "Resumir pendientes", run).as_dict()})
        except Busy as e:
            return err(str(e), 409)

    # ------------------------------------------------------------ configuración (solo PC)
    @app.post("/api/settings")
    def settings():
        local_only()
        data = request.get_json(force=True)
        s = state.settings
        if "dest_dir" in data and str(data["dest_dir"]).strip():
            s.dest_dir = str(data["dest_dir"]).strip()
        for key in ("ai_enabled", "pro_index", "ai_consent", "ocr_enabled"):
            if key in data:
                setattr(s, key, bool(data[key]))
        if data.get("ai_model") in MODELS:
            s.ai_model = data["ai_model"]
        s.save()
        return jsonify({"ok": True})

    @app.post("/api/settings/drive")
    def settings_drive():
        local_only()
        drive = find_google_drive()
        if drive is None:
            return err("No encuentro Google Drive para ordenadores en este PC. Instálalo desde "
                       "https://www.google.com/drive/download/ o escribe la carpeta a mano.", 404)
        state.settings.dest_dir = str(drive / "UJI Study")
        state.settings.save()
        return jsonify({"dest": state.settings.dest_dir})

    @app.post("/api/apikey")
    def apikey():
        local_only()
        key = str((request.get_json(force=True) or {}).get("key", "")).strip()
        if not key:
            delete_api_key()
            return jsonify({"ok": True, "deleted": True})
        if not set_api_key(key):
            return err("No se pudo guardar en el Administrador de credenciales. Como alternativa, "
                       "define la variable de entorno ANTHROPIC_API_KEY.", 500)
        return jsonify({"ok": True})

    @app.post("/api/open")
    def open_folder():
        local_only()
        what = (request.get_json(force=True) or {}).get("what")
        path = inbox_dir(state.root) if what == "inbox" else state.root
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])
        except OSError:
            pass
        return jsonify({"path": str(path)})

    @app.post("/api/mobile")
    def mobile():
        local_only()
        enabled = bool((request.get_json(force=True) or {}).get("enabled"))
        if enabled and state.mobile_server is None:
            if not state.settings.mobile_pin:
                state.settings.mobile_pin = new_pin()
                state.settings.save()
            try:
                state.mobile_server = ServerThread(app, "0.0.0.0", MOBILE_PORT).start()
            except OSError as e:
                return err(f"No se pudo activar el acceso desde el móvil: {e}", 500)
        elif not enabled and state.mobile_server is not None:
            state.mobile_server.stop()
            state.mobile_server = None
            state.sessions.clear()
        return jsonify({"ok": True})

    return app


class ServerThread:
    def __init__(self, app: Flask, host: str, port: int):
        self.server = make_server(host, port, app, threaded=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.server.server_port

    def start(self) -> "ServerThread":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()


def run(open_browser: bool = True) -> None:
    import logging
    import webbrowser

    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # consola limpia
    settings = Settings.load()
    if not settings.dest_dir:
        settings.dest_dir = str(Path.home() / "UJI Study")
    state = AppState(settings)
    app = create_app(state)
    server = ServerThread(app, "127.0.0.1", PORT).start()
    url = f"http://127.0.0.1:{PORT}"
    print(f"UJI Study Assistant funcionando en {url}  (cierra esta ventana para salir)")
    if open_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        if state.mobile_server:
            state.mobile_server.stop()
        state.jobs.shutdown()
