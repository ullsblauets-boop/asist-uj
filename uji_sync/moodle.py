"""Acceso al Aula Virtual con la sesión que el usuario inicia a mano.

Todo pasa por un navegador real (Microsoft Edge por defecto) controlado con
Playwright. La herramienta nunca ve ni guarda la contraseña: espera a que el
usuario termine el login (SSO + doble factor) y después navega con esa sesión,
viendo solo lo que Moodle ya le permite ver.

Endpoints usados (estándar de Moodle, verificados en su código fuente):
  - lib/ajax/service.php + core_course_get_enrolled_courses_by_timeline_classification
  - course/view.php?id=N               (secciones y actividades)
  - mod/resource/view.php?id=N&redirect=1  -> redirige al archivo (pluginfile.php)
  - mod/folder/view.php?id=N           (archivos de una carpeta)
  - mod/url/view.php?id=N&redirect=1   -> redirige a la URL externa
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .fsutils import is_pluginfile, strip_query


class MoodleError(Exception):
    pass


class LoginCancelled(MoodleError):
    pass


@dataclass
class Course:
    id: int
    fullname: str
    shortname: str = ""


@dataclass
class Item:
    cmid: int | None     # id del módulo (None para archivos incrustados en textos)
    modtype: str         # resource | folder | url | inlinefile | forum | ...
    name: str
    url: str


@dataclass
class Section:
    number: int
    name: str
    items: list[Item] = field(default_factory=list)


@dataclass
class Download:
    status: int
    url: str
    content_type: str
    body: bytes


# Lee la página de un curso. Cubre el marcado de Moodle 4.x
# (li.section[data-sectionname], li.activity[data-id].modtype_X) y el de 3.x
# (li.section[aria-label], li.activity#module-N).
_PARSE_COURSE_JS = r"""
() => {
  const text = (el) => {
    if (!el) return '';
    const c = el.cloneNode(true);
    c.querySelectorAll('.accesshide, .sr-only, .visually-hidden').forEach(e => e.remove());
    return c.textContent.replace(/\s+/g, ' ').trim();
  };
  const sections = [];
  document.querySelectorAll('li.section').forEach((sec, i) => {
    const numAttr = sec.getAttribute('data-number') ?? sec.getAttribute('data-sectionid')
                    ?? (sec.id || '').replace('section-', '');
    const number = /^\d+$/.test(numAttr || '') ? parseInt(numAttr, 10) : i;
    const name = sec.getAttribute('data-sectionname') || text(sec.querySelector('.sectionname'))
                 || sec.getAttribute('aria-label') || '';
    const items = [];
    sec.querySelectorAll('li.activity').forEach((act) => {
      const mod = [...act.classList].find(c => c.startsWith('modtype_'));
      const modtype = mod ? mod.slice('modtype_'.length) : 'unknown';
      const idAttr = act.getAttribute('data-id') || (act.id || '').replace('module-', '');
      const cmid = /^\d+$/.test(idAttr || '') ? parseInt(idAttr, 10) : null;
      const link = act.querySelector('a.aalink') || act.querySelector('a[href*="/mod/"]');
      const nameEl = act.querySelector('[data-activityname]');
      const actName = (nameEl && nameEl.getAttribute('data-activityname'))
                      || text(act.querySelector('.instancename')) || text(link);
      if (modtype === 'label') {
        // Las etiquetas no son descargables, pero pueden contener archivos enlazados.
        act.querySelectorAll('a[href*="/pluginfile.php/"]').forEach(a => items.push(
          {cmid: null, modtype: 'inlinefile', name: text(a), url: a.href}));
        return;
      }
      if (cmid !== null) items.push({cmid, modtype, name: actName, url: link ? link.href : ''});
    });
    // Archivos enlazados en el resumen de la sección.
    sec.querySelectorAll('.summary a[href*="/pluginfile.php/"], .summarytext a[href*="/pluginfile.php/"]')
      .forEach(a => items.push({cmid: null, modtype: 'inlinefile', name: text(a), url: a.href}));
    sections.push({number, name, items});
  });
  // Formatos "una sección por página": enlaces a cada sección.
  const sectionLinks = [...document.querySelectorAll(
      'a[href*="/course/view.php?id="][href*="section="], a[href*="/course/section.php?id="]')]
    .map(a => a.href.split('#')[0]);
  return {sections, sectionLinks: [...new Set(sectionLinks)]};
}
"""

_IS_LOGGED_IN_JS = """
() => !!document.body && !document.body.classList.contains('notloggedin')
      && !!(window.M && M.cfg && M.cfg.sesskey)
"""

_AJAX_JS = """
async ([base, sesskey, method, args]) => {
  const r = await fetch(`${base}/lib/ajax/service.php?sesskey=${encodeURIComponent(sesskey)}`
                        + `&info=${encodeURIComponent(method)}`, {
    method: 'POST', credentials: 'same-origin',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify([{index: 0, methodname: method, args}]),
  });
  return await r.json();
}
"""


class MoodleBrowser:
    """Navegador con sesión manual. Debe usarse siempre desde un mismo hilo."""

    def __init__(
        self,
        base_url: str,
        profile_dir: Path,
        channel: str | None = "msedge",
        headless: bool = False,
        delay: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.profile_dir = profile_dir
        self.channel = channel
        self.headless = headless
        self.delay = delay  # pausa entre peticiones para no cargar el servidor
        self._pw = None
        self.context = None
        self._page = None

    # ---------- ciclo de vida ----------
    def start(self) -> None:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        kwargs = dict(user_data_dir=str(self.profile_dir), headless=self.headless)
        exe = os.environ.get("UJI_SYNC_BROWSER_PATH")
        if exe:
            kwargs["executable_path"] = exe
        elif self.channel:
            kwargs["channel"] = self.channel
        try:
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        except PlaywrightError:
            if "channel" not in kwargs:
                raise
            # Sin Edge: usar el Chromium de Playwright (python -m playwright install chromium).
            kwargs.pop("channel")
            self.context = self._pw.chromium.launch_persistent_context(**kwargs)
        self._page = self.context.pages[0] if self.context.pages else self.context.new_page()

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
        finally:
            if self._pw:
                self._pw.stop()
            self.context = self._pw = self._page = None

    @property
    def page(self):
        # Si el usuario cerró la pestaña, usar otra (o abrir una nueva).
        if self._page is None or self._page.is_closed():
            pages = [p for p in self.context.pages if not p.is_closed()]
            self._page = pages[-1] if pages else self.context.new_page()
        return self._page

    # ---------- login manual ----------
    def open_site(self) -> None:
        # /my/ exige sesión: si no la hay, Moodle redirige al login de la UJI.
        self.page.goto(f"{self.base_url}/my/", wait_until="domcontentloaded")

    def is_logged_in(self) -> bool:
        page = self.page
        if not page.url.startswith(self.base_url):
            return False
        try:
            return bool(page.evaluate(_IS_LOGGED_IN_JS))
        except PlaywrightError:
            return False  # la página está navegando

    def wait_for_login(
        self, timeout: float = 900, should_stop: Callable[[], bool] = lambda: False
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if should_stop():
                raise LoginCancelled("Inicio de sesión cancelado.")
            if self.is_logged_in():
                return
            self.page.wait_for_timeout(1000)
        raise MoodleError("Tiempo de espera agotado: no se detectó el inicio de sesión.")

    # ---------- cursos ----------
    def _ensure_on_site(self) -> None:
        if not self.is_logged_in():
            self.page.goto(f"{self.base_url}/my/", wait_until="domcontentloaded")
            if not self.is_logged_in():
                raise MoodleError("La sesión ha caducado. Vuelve a iniciar sesión.")

    def ajax(self, method: str, args: dict):
        self._ensure_on_site()
        sesskey = self.page.evaluate("() => M.cfg.sesskey")
        res = self.page.evaluate(_AJAX_JS, [self.base_url, sesskey, method, args])
        if isinstance(res, dict):  # error global (p. ej. sesskey no válida)
            raise MoodleError(res.get("message") or res.get("error") or str(res))
        item = res[0]
        if item.get("error"):
            exc = item.get("exception") or {}
            raise MoodleError(exc.get("message") or str(exc))
        return item["data"]

    def get_courses(self, include_past: bool = False) -> list[Course]:
        classification = "all" if include_past else "inprogress"
        data = self.ajax(
            "core_course_get_enrolled_courses_by_timeline_classification",
            {"offset": 0, "limit": 0, "classification": classification},
        )
        courses = [
            Course(int(c["id"]), c.get("fullname") or c.get("shortname") or str(c["id"]),
                   c.get("shortname") or "")
            for c in data.get("courses", [])
        ]
        return sorted(courses, key=lambda c: c.fullname.lower())

    # ---------- contenido ----------
    def _goto(self, url: str) -> None:
        time.sleep(self.delay)
        resp = self.page.goto(url, wait_until="domcontentloaded")
        if resp is not None and resp.status >= 400:
            raise MoodleError(f"HTTP {resp.status} al abrir {url}")

    def get_course_sections(self, course_id: int) -> list[Section]:
        self._goto(f"{self.base_url}/course/view.php?id={course_id}")
        data = self.page.evaluate(_PARSE_COURSE_JS)
        sections = [self._section(s) for s in data["sections"]]
        if not any(s.items for s in sections) and data["sectionLinks"]:
            # Curso con una sección por página: visitar cada sección.
            by_number: dict[int, Section] = {s.number: s for s in sections}
            for link in data["sectionLinks"]:
                self._goto(link)
                for s in self.page.evaluate(_PARSE_COURSE_JS)["sections"]:
                    sec = self._section(s)
                    if not sec.items:
                        continue
                    known = by_number.setdefault(sec.number, sec)
                    if known is not sec:
                        seen = {(i.cmid, i.url) for i in known.items}
                        known.items += [i for i in sec.items if (i.cmid, i.url) not in seen]
                        known.name = known.name or sec.name
            sections = sorted(by_number.values(), key=lambda s: s.number)
        return sections

    @staticmethod
    def _section(raw: dict) -> Section:
        return Section(
            number=int(raw["number"]),
            name=raw["name"],
            items=[Item(i["cmid"], i["modtype"], i["name"], i["url"]) for i in raw["items"]],
        )

    def resolve_redirect(self, url: str) -> str | None:
        """Devuelve el destino de una redirección de Moodle sin descargar el contenido."""
        time.sleep(self.delay)
        resp = self.context.request.get(url, max_redirects=0)
        try:
            location = resp.headers.get("location")
            return urljoin(url, location) if location and 300 <= resp.status < 400 else None
        finally:
            resp.dispose()

    def resolve_resource(self, cmid: int) -> str | None:
        """URL pluginfile.php del archivo de un recurso, o None si no es descargable."""
        target = self.resolve_redirect(f"{self.base_url}/mod/resource/view.php?id={cmid}&redirect=1")
        if target and is_pluginfile(target):
            return strip_query(target)
        # Sin redirección (p. ej. recurso incrustado): buscar el archivo en la página.
        self._goto(f"{self.base_url}/mod/resource/view.php?id={cmid}")
        found = self.page.evaluate(
            """() => {
                 const el = document.querySelector(
                   '#region-main a[href*="/pluginfile.php/"], #region-main object[data*="/pluginfile.php/"],'
                   + ' #region-main iframe[src*="/pluginfile.php/"], #region-main embed[src*="/pluginfile.php/"],'
                   + ' #region-main img[src*="/pluginfile.php/"]');
                 return el ? (el.href || el.data || el.src) : null;
               }"""
        )
        return strip_query(found) if found else None

    def resolve_url(self, cmid: int) -> str | None:
        return self.resolve_redirect(f"{self.base_url}/mod/url/view.php?id={cmid}&redirect=1")

    def list_folder_files(self, cmid: int) -> list[str]:
        self._goto(f"{self.base_url}/mod/folder/view.php?id={cmid}")
        urls = self.page.evaluate(
            """() => [...document.querySelectorAll('a[href*="/pluginfile.php/"]')]
                       .map(a => a.href).filter(h => h.includes('/mod_folder/content/'))"""
        )
        return list(dict.fromkeys(strip_query(u) for u in urls))

    def download(self, url: str) -> Download:
        time.sleep(self.delay)
        resp = self.context.request.get(url, timeout=300_000)
        try:
            return Download(
                status=resp.status,
                url=resp.url,
                content_type=resp.headers.get("content-type", ""),
                body=resp.body() if resp.ok else b"",
            )
        finally:
            resp.dispose()
