"""Registro local (SQLite) de lo descargado, para evitar duplicados.

La base de datos vive dentro de la carpeta de destino (UJI/.uji-sync.db) y guarda
rutas relativas, así que la carpeta UJI se puede mover sin perder el historial.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    key          TEXT PRIMARY KEY,   -- identificador estable del recurso en Moodle
    kind         TEXT NOT NULL,      -- file | link
    course_id    INTEGER NOT NULL,
    course_name  TEXT NOT NULL,
    section      TEXT NOT NULL,
    name         TEXT NOT NULL,
    url          TEXT NOT NULL,      -- URL exacta (incluye la revisión de Moodle)
    local_path   TEXT NOT NULL,      -- relativa a la carpeta UJI
    sha256       TEXT NOT NULL,
    size         INTEGER NOT NULL,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL,
    last_changed TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS files_local_path ON files(local_path);
CREATE TABLE IF NOT EXISTS runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    started  TEXT NOT NULL,
    finished TEXT,
    dry_run  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS run_courses (
    run_id      INTEGER NOT NULL REFERENCES runs(id),
    course_id   INTEGER NOT NULL,
    course_name TEXT NOT NULL,
    new         INTEGER NOT NULL,
    updated     INTEGER NOT NULL,
    unchanged   INTEGER NOT NULL,
    skipped     INTEGER NOT NULL,
    errors      INTEGER NOT NULL
);
-- Resúmenes de IA indexados por contenido: el mismo archivo nunca se paga dos veces.
CREATE TABLE IF NOT EXISTS summaries (
    sha256        TEXT PRIMARY KEY,
    model         TEXT NOT NULL,
    created       TEXT NOT NULL,
    data          TEXT NOT NULL,     -- JSON con título, resumen, puntos clave...
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL
);
-- Apuntes propios que la bandeja ha organizado.
CREATE TABLE IF NOT EXISTS notes (
    local_path    TEXT PRIMARY KEY,  -- relativa a la carpeta UJI
    original_name TEXT NOT NULL,
    course_name   TEXT NOT NULL,
    section       TEXT NOT NULL,
    titulo        TEXT NOT NULL,
    en_una_frase  TEXT NOT NULL,
    created       TEXT NOT NULL
);
-- Biblioteca: etiquetas de cada archivo (del Aula Virtual o propio).
CREATE TABLE IF NOT EXISTS library (
    path        TEXT PRIMARY KEY,    -- relativa a la carpeta de destino
    course      TEXT NOT NULL,
    tema        TEXT NOT NULL,
    tipo        TEXT NOT NULL,
    profesor    TEXT NOT NULL,
    source      TEXT NOT NULL,       -- aula | propio
    titulo      TEXT NOT NULL,
    descripcion TEXT NOT NULL,
    added       TEXT NOT NULL
);
-- Perfil de estilo de cada asignatura (Fase 6).
CREATE TABLE IF NOT EXISTS style_profiles (
    course  TEXT PRIMARY KEY,
    data    TEXT NOT NULL,
    cost    REAL NOT NULL,
    created TEXT NOT NULL
);
-- Tareas y entregas del calendario del Aula Virtual (Fase 7).
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY,
    course     TEXT NOT NULL,
    name       TEXT NOT NULL,
    timesort   INTEGER NOT NULL,
    url        TEXT NOT NULL,
    action     TEXT NOT NULL,
    overdue    INTEGER NOT NULL,
    modulename TEXT NOT NULL,
    updated    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events_done (id INTEGER PRIMARY KEY);
-- Avisos de los foros de cada asignatura (Fase 7).
CREATE TABLE IF NOT EXISTS announcements (
    url        TEXT PRIMARY KEY,
    course     TEXT NOT NULL,
    title      TEXT NOT NULL,
    date       TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS course_meta (
    course   TEXT PRIMARY KEY,
    profesor TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class FileRecord:
    key: str
    kind: str
    course_id: int
    course_name: str
    section: str
    name: str
    url: str
    local_path: str
    sha256: str
    size: int
    first_seen: str
    last_seen: str
    last_changed: str


class Registry:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def get(self, key: str) -> FileRecord | None:
        row = self.conn.execute("SELECT * FROM files WHERE key = ?", (key,)).fetchone()
        return FileRecord(**dict(row)) if row else None

    def owner_of_path(self, local_path: str) -> str | None:
        row = self.conn.execute(
            "SELECT key FROM files WHERE local_path = ?", (local_path,)
        ).fetchone()
        return row["key"] if row else None

    def upsert(self, rec: FileRecord) -> None:
        self.conn.execute(
            """INSERT INTO files VALUES (:key, :kind, :course_id, :course_name, :section,
                   :name, :url, :local_path, :sha256, :size, :first_seen, :last_seen, :last_changed)
               ON CONFLICT(key) DO UPDATE SET
                   kind=excluded.kind, course_id=excluded.course_id,
                   course_name=excluded.course_name, section=excluded.section,
                   name=excluded.name, url=excluded.url, local_path=excluded.local_path,
                   sha256=excluded.sha256, size=excluded.size, last_seen=excluded.last_seen,
                   last_changed=excluded.last_changed""",
            rec.__dict__,
        )
        self.conn.commit()

    def touch(self, key: str, url: str) -> None:
        self.conn.execute(
            "UPDATE files SET last_seen = ?, url = ? WHERE key = ?", (now(), url, key)
        )
        self.conn.commit()

    def files(self, course_ids: list[int] | None = None) -> list[FileRecord]:
        sql, args = "SELECT * FROM files WHERE kind = 'file'", []
        if course_ids is not None:
            sql += f" AND course_id IN ({','.join('?' * len(course_ids))})"
            args = list(course_ids)
        rows = self.conn.execute(sql + " ORDER BY local_path", args).fetchall()
        return [FileRecord(**dict(r)) for r in rows]

    def get_summary(self, sha256: str) -> dict | None:
        row = self.conn.execute(
            "SELECT data, model, created FROM summaries WHERE sha256 = ?", (sha256,)
        ).fetchone()
        if not row:
            return None
        return {**json.loads(row["data"]), "_model": row["model"], "_created": row["created"]}

    def save_summary(self, sha256: str, model: str, data: dict,
                     input_tokens: int, output_tokens: int) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO summaries VALUES (?, ?, ?, ?, ?, ?)",
            (sha256, model, now(), json.dumps(data, ensure_ascii=False),
             input_tokens, output_tokens),
        )
        self.conn.commit()

    def save_note(self, local_path: str, original_name: str, course_name: str,
                  section: str, titulo: str, en_una_frase: str) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO notes VALUES (?, ?, ?, ?, ?, ?, ?)",
            (local_path, original_name, course_name, section, titulo, en_una_frase, now()),
        )
        self.conn.commit()

    def notes(self) -> dict[str, dict]:
        rows = self.conn.execute("SELECT * FROM notes").fetchall()
        return {r["local_path"]: dict(r) for r in rows}

    # ---------------------------------------------------------- biblioteca
    def library_items(self) -> dict[str, dict]:
        rows = self.conn.execute("SELECT * FROM library").fetchall()
        return {r["path"]: dict(r) for r in rows}

    def save_library_item(self, item: dict) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO library VALUES (:path, :course, :tema, :tipo, :profesor,
                   :source, :titulo, :descripcion, :added)""",
            item,
        )
        self.conn.commit()

    def delete_library_item(self, path: str) -> None:
        self.conn.execute("DELETE FROM library WHERE path = ?", (path,))
        self.conn.commit()

    def course_profesores(self) -> dict[str, str]:
        rows = self.conn.execute("SELECT course, profesor FROM course_meta").fetchall()
        return {r["course"]: r["profesor"] for r in rows}

    def set_course_profesor(self, course: str, profesor: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO course_meta VALUES (?, ?)", (course, profesor))
        self.conn.commit()

    # ---------------------------------------------------------- estilo (Fase 6)
    def get_style(self, course: str) -> dict | None:
        row = self.conn.execute("SELECT data FROM style_profiles WHERE course = ?", (course,)).fetchone()
        return json.loads(row["data"]) if row else None

    def save_style(self, course: str, data: dict, cost: float) -> None:
        self.conn.execute("INSERT OR REPLACE INTO style_profiles VALUES (?, ?, ?, ?)",
                          (course, json.dumps(data, ensure_ascii=False), cost, now()))
        self.conn.commit()

    # ---------------------------------------------------------- tareas y avisos (Fase 7)
    def save_events(self, events: list[dict]) -> None:
        """Sustituye las tareas conocidas por las recibidas del Aula Virtual."""
        self.conn.execute("DELETE FROM events")
        self.conn.executemany(
            "INSERT OR REPLACE INTO events VALUES (:id, :course, :name, :timesort, :url, :action,"
            " :overdue, :modulename, :updated)", [{**e, "updated": now()} for e in events])
        self.conn.commit()

    def events(self) -> list[dict]:
        done = {r["id"] for r in self.conn.execute("SELECT id FROM events_done")}
        rows = self.conn.execute("SELECT * FROM events ORDER BY timesort").fetchall()
        return [{**dict(r), "overdue": bool(r["overdue"]), "done": r["id"] in done} for r in rows]

    def set_event_done(self, event_id: int, done: bool) -> None:
        if done:
            self.conn.execute("INSERT OR IGNORE INTO events_done VALUES (?)", (event_id,))
        else:
            self.conn.execute("DELETE FROM events_done WHERE id = ?", (event_id,))
        self.conn.commit()

    def add_announcements(self, course: str, items: list[dict]) -> list[dict]:
        """Guarda los avisos y devuelve los que no se habían visto antes."""
        new = []
        for it in items:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO announcements VALUES (?, ?, ?, ?, ?)",
                (it["url"], course, it["title"], it.get("date", ""), now()))
            if cur.rowcount:
                new.append(it)
        self.conn.commit()
        return new

    def announcements(self, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM announcements ORDER BY first_seen DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def last_run(self) -> str | None:
        row = self.conn.execute(
            "SELECT finished FROM runs WHERE dry_run = 0 AND finished IS NOT NULL "
            "ORDER BY id DESC LIMIT 1").fetchone()
        return row["finished"] if row else None

    def start_run(self, dry_run: bool) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (started, dry_run) VALUES (?, ?)", (now(), int(dry_run))
        )
        self.conn.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, results) -> None:
        for r in results:
            self.conn.execute(
                "INSERT INTO run_courses VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, r.course_id, r.course_name, len(r.new), len(r.updated),
                 r.unchanged, len(r.skipped), len(r.errors)),
            )
        self.conn.execute("UPDATE runs SET finished = ? WHERE id = ?", (now(), run_id))
        self.conn.commit()
