"""Acceso desde el móvil: una web pequeña servida por el PC en tu wifi.

El PC sigue haciendo la sincronización con el Aula Virtual (necesita el
navegador y tu inicio de sesión). Desde el móvil puedes usar el asistente,
subir apuntes a la bandeja y organizarlos, y ver las novedades.

Seguridad:
  - Hace falta un PIN; tras varios intentos fallidos se bloquea un rato.
  - Solo existen las funciones de abajo: no se puede navegar por tus archivos.
  - Es HTTP sin cifrar dentro de tu red: úsalo en tu wifi de casa, no en redes públicas.
"""

from __future__ import annotations

import json
import secrets
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from .ai import AIError, AIFatalError
from .assistant import Assistant
from .config import registry_path
from .fsutils import safe_name
from .inbox import InboxOrganizer, inbox_dir, inbox_files
from .library import list_courses
from .registry import Registry

DEFAULT_PORT = 8765
MAX_UPLOAD = 25 * 1024 * 1024
MAX_FAILED_PINS = 5
LOCKOUT_SECONDS = 60
PAGE = (Path(__file__).parent / "mobile_page.html")


def new_pin() -> str:
    return f"{secrets.randbelow(10**6):06d}"


def lan_ip() -> str:
    """IP del PC en la red local (no envía ningún paquete)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class MobileServer:
    def __init__(
        self,
        root: Path,
        pin: str,
        model: str,
        port: int = DEFAULT_PORT,
        host: str = "0.0.0.0",
        assistant_factory: Callable[[Path, str | None, str], Assistant] | None = None,
        organizer_factory: Callable[[Path, Registry, str], InboxOrganizer] | None = None,
    ):
        self.root = root
        self.pin = pin
        self.model = model
        self.assistant_factory = assistant_factory or (
            lambda root, course, model: Assistant(root, course, model=model))
        self.organizer_factory = organizer_factory or (
            lambda root, reg, model: InboxOrganizer(root, reg, model=model, log=lambda _: None))
        self.sessions: set[str] = set()
        self.conversations: dict[str, tuple[Assistant, threading.Lock]] = {}
        self.failed = 0
        self.locked_until = 0.0
        self.lock = threading.Lock()
        self.organize_lock = threading.Lock()
        self.httpd = ThreadingHTTPServer((host, port), self._handler())
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}"

    def start(self) -> "MobileServer":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    # ------------------------------------------------------------ acciones
    def check_pin(self, pin: str) -> str | None:
        """Devuelve un token de sesión si el PIN es correcto."""
        with self.lock:
            if time.monotonic() < self.locked_until:
                return None
            if secrets.compare_digest(pin, self.pin):
                self.failed = 0
                token = secrets.token_urlsafe(32)
                self.sessions.add(token)
                return token
            self.failed += 1
            if self.failed >= MAX_FAILED_PINS:
                self.locked_until = time.monotonic() + LOCKOUT_SECONDS
                self.failed = 0
            return None

    def chat(self, conversation: str | None, course: str | None, question: str) -> dict:
        with self.lock:
            entry = self.conversations.get(conversation or "")
            if entry is None:
                if course and course not in list_courses(self.root):
                    raise AIError("asignatura desconocida")
                conversation = secrets.token_urlsafe(12)
                entry = (self.assistant_factory(self.root, course or None, self.model),
                         threading.Lock())
                self.conversations[conversation] = entry
        assistant, conv_lock = entry
        reads: list[str] = []
        with conv_lock:
            answer = assistant.ask(question, on_read=reads.append)
        return {"conversation": conversation, "answer": answer, "reads": reads,
                "cost": round(assistant.cost, 4)}

    def save_upload(self, filename: str, data: bytes) -> str:
        box = inbox_dir(self.root)
        name = safe_name(Path(filename.replace("\\", "/")).name, fallback="apunte")
        stem, suffix = Path(name).stem, Path(name).suffix
        target, n = box / name, 1
        while target.exists():
            n += 1
            target = box / f"{stem} ({n}){suffix}"
        target.write_bytes(data)
        return target.name

    def organize(self) -> str:
        if not self.organize_lock.acquire(blocking=False):
            return "Ya se están organizando los apuntes; espera un momento."
        try:
            reg = Registry(registry_path(self.root))
            try:
                return self.organizer_factory(self.root, reg, self.model).organize().text()
            finally:
                reg.close()
        finally:
            self.organize_lock.release()

    def news(self) -> list[dict]:
        """La sección más reciente de Novedades.md de cada asignatura."""
        out = []
        for course in list_courses(self.root):
            path = self.root / course / "_resumenes_IA" / "Novedades.md"
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            sections = text.split("\n## ")[1:]
            if sections:
                when, _, body = sections[0].partition("\n")
                items = [line[2:] for line in body.splitlines() if line.startswith("- ")]
                out.append({"course": course, "when": when.strip(), "items": items})
        return out

    # ------------------------------------------------------------ HTTP
    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "UJISync"

            def log_message(self, *args):
                pass

            def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, code: int, data, headers: dict | None = None):
                self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8", headers)

            def _authed(self) -> bool:
                cookie = SimpleCookie(self.headers.get("Cookie") or "")
                token = cookie.get("ujisync")
                return token is not None and token.value in server.sessions

            def _body(self, limit: int) -> bytes | None:
                length = int(self.headers.get("Content-Length") or 0)
                if length > limit:
                    return None
                return self.rfile.read(length)

            def do_GET(self):
                if self.path == "/":
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8", {
                        "Content-Security-Policy":
                            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                            "script-src 'self' 'unsafe-inline'; img-src 'self' data:",
                    })
                if self.path == "/manifest.json":
                    return self._json(200, {
                        "name": "UJI Sync", "short_name": "UJI Sync", "start_url": "/",
                        "display": "standalone", "background_color": "#ffffff",
                        "theme_color": "#b8003a",
                    })
                if not self._authed():
                    return self._json(401, {"error": "Introduce el PIN"})
                if self.path == "/api/courses":
                    return self._json(200, {"courses": list_courses(server.root)})
                if self.path == "/api/inbox":
                    return self._json(200, {"files": [p.name for p in inbox_files(server.root)]})
                if self.path == "/api/news":
                    return self._json(200, {"news": server.news()})
                self._json(404, {"error": "No existe"})

            def do_POST(self):
                if self.path == "/api/login":
                    body = self._body(1024) or b"{}"
                    try:
                        pin = str(json.loads(body).get("pin", ""))
                    except ValueError:
                        pin = ""
                    token = server.check_pin(pin)
                    if token is None:
                        return self._json(401, {"error": "PIN incorrecto (o demasiados intentos: espera un minuto)"})
                    return self._json(200, {"ok": True}, {
                        "Set-Cookie": f"ujisync={token}; HttpOnly; SameSite=Strict; Path=/"})
                if not self._authed():
                    return self._json(401, {"error": "Introduce el PIN"})
                if self.path == "/api/upload":
                    data = self._body(MAX_UPLOAD)
                    if data is None:
                        return self._json(413, {"error": "Archivo demasiado grande (máx. 25 MB)"})
                    name = server.save_upload(unquote(self.headers.get("X-Filename", "apunte")), data)
                    return self._json(200, {"saved": name})
                if self.path == "/api/organize":
                    return self._json(200, {"result": server.organize()})
                if self.path == "/api/chat":
                    try:
                        req = json.loads(self._body(64 * 1024) or b"{}")
                        question = str(req.get("question", "")).strip()
                        if not question:
                            return self._json(400, {"error": "Escribe una pregunta"})
                        return self._json(200, server.chat(req.get("conversation"),
                                                           req.get("course"), question))
                    except (AIError, AIFatalError) as e:
                        return self._json(200, {"error": str(e)})
                    except ValueError:
                        return self._json(400, {"error": "Petición no válida"})
                self._json(404, {"error": "No existe"})

        return Handler
