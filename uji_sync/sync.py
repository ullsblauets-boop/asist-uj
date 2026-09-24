"""Sincronización de cursos: descarga, organiza y evita duplicados."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Callable

from .config import registry_path
from .fsutils import folder_subpath, is_pluginfile, pluginfile_filename, pluginfile_key, safe_name
from .moodle import Course, MoodleBrowser, MoodleError, Section
from .registry import FileRecord, Registry, now

OLD_VERSIONS_DIR = "_versiones_anteriores"
LEGACY_DB_NAME = ".uji-sync.db"  # v0.1 guardaba el registro dentro de la carpeta UJI


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class CourseResult:
    course_id: int
    course_name: str
    new: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)   # no descargables / sin permiso
    errors: list[str] = field(default_factory=list)
    changed_keys: list[str] = field(default_factory=list)  # archivos nuevos o actualizados

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
        db_path = registry_path(dest_root)
        legacy = dest_root / LEGACY_DB_NAME
        if legacy.exists() and not db_path.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(db_path))
        self.registry = Registry(db_path)

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
        self._store(course, sec, key, "file", filename, url, dl.body,
                    target_dir / filename, rec, exists, res)

    def _sync_link(self, course, sec, sec_dir, item, target: str, res) -> None:
        """Guarda un enlace como acceso directo de Windows (.url)."""
        key = f"url:{course.id}:{item.cmid}"
        name = safe_name(item.name) + ".url"
        content = f"[InternetShortcut]\r\nURL={target}\r\n".encode("utf-8")
        rec = self.registry.get(key)
        exists = rec is not None and (self.root / rec.local_path).exists()
        if exists and rec.sha256 == hashlib.sha256(content).hexdigest():
            if not self.dry_run:
                self.registry.touch(key, target)
            res.unchanged += 1
            return
        if self.dry_run:
            (res.updated if exists else res.new).append(name)
            self.log(f"  {'↻' if exists else '+'} {sec_dir / name}")
            return
        self._store(course, sec, key, "link", name, target, content, sec_dir / name, rec, exists, res)

    def _store(self, course, sec, key, kind, name, url, data: bytes,
               wanted: PurePosixPath, rec, exists: bool, res) -> None:
        """Escribe el contenido descargado y lo apunta en el registro."""
        sha = hashlib.sha256(data).hexdigest()
        if exists and rec.sha256 == sha:
            self.registry.touch(key, url)
            res.unchanged += 1
            return
        if exists:
            local = rec.local_path
            if kind == "file":
                self._archive_old(local)
            res.updated.append(name)
            self.log(f"  ↻ {local}")
            self._write(local, data)
            if kind == "file":
                res.changed_keys.append(key)
        elif rec is None and self._is_unregistered_copy(str(wanted), sha):
            # Ya estaba en la carpeta (p. ej. en Google Drive, sincronizado desde
            # otro PC): se registra sin duplicarlo.
            local = str(wanted)
            res.unchanged += 1
        else:
            local = rec.local_path if rec else self._free_path(wanted, key)
            res.new.append(name)
            self.log(f"  + {local}")
            self._write(local, data)
            if kind == "file":
                res.changed_keys.append(key)
        ts = now()
        self.registry.upsert(FileRecord(
            key=key, kind=kind, course_id=course.id, course_name=course.fullname,
            section=sec.name, name=name, url=url, local_path=local, sha256=sha,
            size=len(data), first_seen=rec.first_seen if rec else ts, last_seen=ts,
            last_changed=ts,
        ))

    def _is_unregistered_copy(self, local: str, sha: str) -> bool:
        path = self.root / local
        return (self.registry.owner_of_path(local) is None and path.is_file()
                and file_sha256(path) == sha)

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

    def _archive_old(self, local: str) -> None:
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
