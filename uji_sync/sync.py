"""Sincronización de cursos: descarga, organiza y evita duplicados."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Callable

from .fsutils import folder_subpath, is_pluginfile, pluginfile_filename, pluginfile_key, safe_name
from .moodle import Course, MoodleBrowser, MoodleError, Section
from .registry import FileRecord, Registry, now

OLD_VERSIONS_DIR = "_versiones_anteriores"
DB_NAME = ".uji-sync.db"


@dataclass
class CourseResult:
    course_id: int
    course_name: str
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)   # no descargables / sin permiso
    errors: list[str] = field(default_factory=list)

    def line(self, dry_run: bool = False) -> str:
        n, u = len(self.new), len(self.updated)
        verb = "por descargar" if dry_run else ("archivo nuevo" if n == 1 else "archivos nuevos")
        parts = [f"{n} {verb}"]
        if u:
            parts.append(f"{u} {'actualizado' if u == 1 else 'actualizados'}")
        parts.append(f"{self.unchanged} sin cambios")
        if self.skipped:
            parts.append(f"{len(self.skipped)} no disponibles")
        if self.errors:
            parts.append(f"{len(self.errors)} errores")
        return f"{self.course_name} → " + ", ".join(parts)


def format_summary(results: list[CourseResult], dry_run: bool = False) -> str:
    title = "Análisis completado (no se ha descargado nada)" if dry_run else "Sincronización completada"
    return "\n".join([title, ""] + [r.line(dry_run) for r in results])


class Syncer:
    def __init__(
        self,
        browser: MoodleBrowser,
        dest_root: Path,
        dry_run: bool = False,
        log: Callable[[str], None] = print,
        should_stop: Callable[[], bool] = lambda: False,
    ):
        self.browser = browser
        self.root = dest_root
        self.dry_run = dry_run
        self.log = log
        self.should_stop = should_stop
        self.registry = Registry(dest_root / DB_NAME)

    def close(self) -> None:
        self.registry.close()

    def sync(self, courses: list[Course]) -> list[CourseResult]:
        run_id = self.registry.start_run(self.dry_run)
        results = []
        try:
            for course in courses:
                if self.should_stop():
                    break
                results.append(self.sync_course(course))
        finally:
            self.registry.finish_run(run_id, results)
        return results

    # ------------------------------------------------------------------
    def sync_course(self, course: Course) -> CourseResult:
        res = CourseResult(course.id, course.fullname)
        self.log(f"▶ {course.fullname}")
        try:
            sections = self.browser.get_course_sections(course.id)
        except MoodleError as e:
            res.errors.append(str(e))
            self.log(f"  ✗ No se pudo leer el curso: {e}")
            return res
        course_dir = PurePosixPath(safe_name(course.fullname))
        for sec in sections:
            sec_dir = course_dir / self._section_dirname(sec)
            for item in sec.items:
                if self.should_stop():
                    return res
                try:
                    self._sync_item(course, sec, sec_dir, item, res)
                except MoodleError as e:
                    res.errors.append(f"{item.name}: {e}")
                    self.log(f"  ✗ {item.name}: {e}")
        return res

    @staticmethod
    def _section_dirname(sec: Section) -> str:
        name = sec.name or ("General" if sec.number == 0 else f"Sección {sec.number}")
        return safe_name(f"{sec.number:02d} - {name}")

    def _sync_item(self, course, sec, sec_dir, item, res) -> None:
        if item.modtype == "resource" and item.cmid is not None:
            url = self.browser.resolve_resource(item.cmid)
            if not url:
                res.skipped.append(item.name)
                self.log(f"  – {item.name}: no descargable")
                return
            self._sync_file(course, sec, sec_dir, url, res)
        elif item.modtype == "folder" and item.cmid is not None:
            folder_dir = sec_dir / safe_name(item.name)
            for url in self.browser.list_folder_files(item.cmid):
                sub = [safe_name(p) for p in folder_subpath(url)]
                self._sync_file(course, sec, folder_dir.joinpath(*sub), url, res)
        elif item.modtype == "inlinefile" and is_pluginfile(item.url):
            self._sync_file(course, sec, sec_dir, item.url, res)
        elif item.modtype == "url" and item.cmid is not None:
            target = self.browser.resolve_url(item.cmid) or item.url
            self._sync_link(course, sec, sec_dir, item, target, res)
        # Otras actividades (foros, tareas, cuestionarios...) no tienen archivos
        # descargables directamente; quedan para fases futuras.

    # ------------------------------------------------------------------
    def _sync_file(self, course, sec, target_dir: PurePosixPath, url: str, res) -> None:
        key = pluginfile_key(url)
        filename = safe_name(pluginfile_filename(url))
        rec = self.registry.get(key)
        exists = rec is not None and (self.root / rec.local_path).exists()

        # Moodle cambia la revisión en la URL cuando se sustituye el archivo:
        # misma URL + archivo presente = sin cambios, sin volver a descargar.
        if exists and rec.url == url:
            if not self.dry_run:
                self.registry.touch(key, url)
            res.unchanged += 1
            return
        if self.dry_run:
            (res.updated if exists else res.new).append(filename)
            self.log(f"  {'↻' if exists else '+'} {target_dir / filename}")
            return

        dl = self.browser.download(url)
        if dl.status != 200 or not is_pluginfile(dl.url):
            # 403/404 o redirección al login: no hay permiso para descargarlo.
            res.skipped.append(filename)
            self.log(f"  – {filename}: no disponible (HTTP {dl.status})")
            return
        sha = hashlib.sha256(dl.body).hexdigest()

        if exists and rec.sha256 == sha:
            self.registry.touch(key, url)
            res.unchanged += 1
            return

        if exists:
            local = rec.local_path
            self._archive_old(course, local)
            res.updated.append(filename)
            self.log(f"  ↻ {local}")
        else:
            local = rec.local_path if rec else self._free_path(target_dir / filename, key)
            res.new.append(filename)
            self.log(f"  + {local}")
        self._write(local, dl.body)
        ts = now()
        self.registry.upsert(FileRecord(
            key=key, kind="file", course_id=course.id, course_name=course.fullname,
            section=sec.name, name=filename, url=url, local_path=local, sha256=sha,
            size=len(dl.body), first_seen=rec.first_seen if rec else ts, last_seen=ts,
            last_changed=ts,
        ))

    def _sync_link(self, course, sec, sec_dir, item, target: str, res) -> None:
        """Guarda un enlace como acceso directo de Windows (.url)."""
        key = f"url:{course.id}:{item.cmid}"
        content = f"[InternetShortcut]\r\nURL={target}\r\n".encode("utf-8")
        sha = hashlib.sha256(content).hexdigest()
        rec = self.registry.get(key)
        exists = rec is not None and (self.root / rec.local_path).exists()
        if exists and rec.sha256 == sha:
            if not self.dry_run:
                self.registry.touch(key, target)
            res.unchanged += 1
            return
        name = safe_name(item.name) + ".url"
        if self.dry_run:
            (res.updated if exists else res.new).append(name)
            self.log(f"  {'↻' if exists else '+'} {sec_dir / name}")
            return
        local = rec.local_path if rec else self._free_path(sec_dir / name, key)
        (res.updated if exists else res.new).append(name)
        self.log(f"  {'↻' if exists else '+'} {local}")
        self._write(local, content)
        ts = now()
        self.registry.upsert(FileRecord(
            key=key, kind="link", course_id=course.id, course_name=course.fullname,
            section=sec.name, name=name, url=target, local_path=local, sha256=sha,
            size=len(content), first_seen=rec.first_seen if rec else ts, last_seen=ts,
            last_changed=ts,
        ))

    # ------------------------------------------------------------------
    def _free_path(self, wanted: PurePosixPath, key: str) -> str:
        """Ruta libre: no pisa archivos de otros recursos ni archivos del usuario."""
        stem, suffix = wanted.stem, wanted.suffix
        candidate, n = wanted, 1
        while True:
            rel = str(candidate)
            owner = self.registry.owner_of_path(rel)
            if owner in (None, key) and not (owner is None and (self.root / rel).exists()):
                return rel
            n += 1
            candidate = wanted.with_name(f"{stem} ({n}){suffix}")

    def _archive_old(self, course: Course, local: str) -> None:
        src = self.root / local
        p = PurePosixPath(local)
        dst_rel = (PurePosixPath(p.parts[0]) / OLD_VERSIONS_DIR
                   / f"{p.stem} ({date.today().isoformat()}){p.suffix}")
        dst = self.root / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        n = 2
        while dst.exists():
            dst = dst.with_name(f"{p.stem} ({date.today().isoformat()}, {n}){p.suffix}")
            n += 1
        os.replace(src, dst)

    def _write(self, local: str, data: bytes) -> None:
        path = self.root / local
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)
