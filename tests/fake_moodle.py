"""Servidor Moodle simulado para pruebas locales.

Imita el marcado estándar de Moodle 4.x (plantillas core_courseformat) y los
endpoints que usa UJI Sync. NO es el Aula Virtual real: sirve para comprobar
la lógica (login manual, lista de cursos, descargas, duplicados).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

SESSKEY = "abc123"


class FakeMoodle:
    def __init__(self):
        # Contenido modificable desde los tests.
        self.resource_rev = 1
        self.resource_body = b"%PDF-1.4 tema 1 v1"
        self.forbidden_cmid = 14  # recurso que el alumno no puede descargar
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self.server.shutdown()

    # ------------------------------------------------------------------
    def course_html(self) -> str:
        b = self.base_url
        res_link = f"{b}/mod/resource/view.php?id=10"

        def act(cmid, mod, name, extra=""):
            return f"""
            <li class="activity activity-wrapper {mod} modtype_{mod}" id="module-{cmid}" data-for="cmitem" data-id="{cmid}">
              <div class="activity-item" data-activityname="{name}" data-region="activity-card">
                <a class="aalink stretched-link" href="{b}/mod/{mod}/view.php?id={cmid}">
                  <span class="instancename">{name} <span class="accesshide"> Archivo</span></span></a>
                {extra}
              </div>
            </li>"""

        label = f"""
            <li class="activity activity-wrapper label modtype_label" id="module-20" data-for="cmitem" data-id="20">
              <div class="activity-item"><div class="no-overflow">
                Ver <a href="{b}/pluginfile.php/70/mod_label/intro/Horario.pdf">Horario</a>
              </div></div>
            </li>"""
        return f"""<!DOCTYPE html><html><head><script>var M = {{cfg: {{sesskey: "{SESSKEY}"}}}};</script></head>
        <body class="path-course-view"><div id="region-main"><ul class="topics">
          <li id="section-0" class="section course-section main" data-sectionid="0" data-for="section"
              data-id="100" data-number="0" data-sectionname="General">
            <h3 class="sectionname">General</h3>
            <ul class="section" data-for="cmlist">{act(15, 'forum', 'Avisos')}{act(12, 'url', 'Web de la asignatura')}</ul>
          </li>
          <li id="section-1" class="section course-section main" data-sectionid="1" data-for="section"
              data-id="101" data-number="1" data-sectionname="Tema 1: Introducción">
            <h3 class="sectionname">Tema 1: Introducción</h3>
            <ul class="section" data-for="cmlist">{act(10, 'resource', 'Apuntes tema 1')}{act(11, 'folder', 'Prácticas')}{label}{act(14, 'resource', 'Solo profesorado')}</ul>
          </li>
        </ul></div><!-- {res_link} --></body></html>"""

    def folder_html(self) -> str:
        b = self.base_url
        files = ["P1.pdf", "Datos/datos.xlsx", "Datos/figura 1.png"]
        links = "".join(
            f'<a href="{b}/pluginfile.php/61/mod_folder/content/3/{quote(f)}?forcedownload=1">{f}</a>'
            for f in files
        )
        return f"<html><body><div id='region-main'>{links}</div></body></html>"

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _logged(self):
                return "MoodleSession=ok" in (self.headers.get("Cookie") or "")

            def _send(self, code, body=b"", ctype="text/html; charset=utf-8", headers=None):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _redirect(self, location, cookie=None):
                h = {"Location": location}
                if cookie:
                    h["Set-Cookie"] = cookie
                self._send(303, headers=h)

            def do_POST(self):
                u = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                if u.path == "/login/index.php":
                    return self._redirect("/my/", "MoodleSession=ok; Path=/")
                if u.path == "/lib/ajax/service.php":
                    q = parse_qs(u.query)
                    if not self._logged() or q.get("sesskey") != [SESSKEY]:
                        return self._send(200, json.dumps(
                            {"error": "Clave de sesión no válida"}).encode(), "application/json")
                    req = json.loads(raw)[0]
                    assert req["methodname"] == "core_course_get_enrolled_courses_by_timeline_classification"
                    courses = [{"id": 1, "fullname": "Matemáticas", "shortname": "MT1001"},
                               {"id": 2, "fullname": "Física", "shortname": "FS1002"}]
                    data = [{"error": False, "data": {"courses": courses, "nextoffset": 2}}]
                    return self._send(200, json.dumps(data).encode(), "application/json")
                self._send(404)

            def do_GET(self):
                u = urlsplit(self.path)
                q = parse_qs(u.query)
                p = u.path
                if p == "/login/index.php":
                    return self._send(200, b"""<html><body class="notloggedin">
                        <script>var M={cfg:{sesskey:'guest'}};</script>
                        <form method="post" action="/login/index.php"><button id="loginbtn">Entrar</button></form>
                        </body></html>""")
                if not self._logged():
                    return self._redirect("/login/index.php")
                if p == "/my/":
                    return self._send(200, f"""<html><body class="page-my-index">
                        <script>var M={{cfg:{{sesskey:'{SESSKEY}'}}}};</script>Mi área</body></html>""".encode())
                if p == "/course/view.php":
                    if q.get("id") == ["1"]:
                        return self._send(200, fake.course_html().encode())
                    return self._send(200, b"<html><body><script>var M={cfg:{sesskey:'x'}};</script></body></html>")
                if p == "/mod/resource/view.php":
                    cmid = int(q["id"][0])
                    if cmid == 10:
                        return self._redirect(
                            f"{fake.base_url}/pluginfile.php/50/mod_resource/content/{fake.resource_rev}/"
                            "Tema%201.pdf")
                    if cmid == fake.forbidden_cmid:
                        return self._redirect(f"{fake.base_url}/pluginfile.php/51/mod_resource/content/1/privado.pdf")
                if p == "/mod/folder/view.php":
                    return self._send(200, fake.folder_html().encode())
                if p == "/mod/url/view.php":
                    return self._redirect("https://example.org/asignatura")
                if p.startswith("/pluginfile.php/"):
                    if "privado.pdf" in p:
                        return self._send(403, b"forbidden")
                    if "mod_resource" in p:
                        return self._send(200, fake.resource_body, "application/pdf")
                    return self._send(200, ("contenido " + p).encode(), "application/octet-stream")
                self._send(404)

        return H
