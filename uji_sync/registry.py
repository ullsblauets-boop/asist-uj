"""Registro local (SQLite) de lo descargado, para evitar duplicados.

La base de datos vive dentro de la carpeta de destino (UJI/.uji-sync.db) y guarda
rutas relativas, así que la carpeta UJI se puede mover sin perder el historial.
"""

from __future__ import annotations

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
