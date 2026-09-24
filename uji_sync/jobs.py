"""Tareas largas en segundo plano (iniciar sesión, sincronizar, resumir, organizar).

Playwright exige usar el navegador siempre desde el mismo hilo, así que todas
las tareas se ejecutan de una en una en un único hilo de trabajo. La web
consulta el estado con current().
"""

from __future__ import annotations

import itertools
import queue
import threading
import traceback
from dataclasses import dataclass, field
from typing import Callable


class Busy(Exception):
    pass


@dataclass
class Job:
    id: int
    kind: str
    title: str
    running: bool = True
    log: list[str] = field(default_factory=list)
    result: str = ""
    error: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "kind": self.kind, "title": self.title, "running": self.running,
                "log": self.log[-400:], "result": self.result, "error": self.error}


class JobManager:
    def __init__(self):
        self._tasks: queue.Queue = queue.Queue()
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.job: Job | None = None
        self.stop = threading.Event()
        self.state: dict = {}      # datos que comparten las tareas (navegador, cursos de Moodle…)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def submit(self, kind: str, title: str, fn: Callable[[Job], str]) -> Job:
        """fn recibe el Job (para escribir en job.log) y devuelve el texto final."""
        with self._lock:
            if self.job and self.job.running:
                raise Busy(f"Ya hay una tarea en marcha: {self.job.title}")
            self.job = Job(next(self._ids), kind, title)
            job = self.job
        self._tasks.put((job, fn))
        return job

    def current(self) -> dict | None:
        return self.job.as_dict() if self.job else None

    def shutdown(self) -> None:
        self.stop.set()
        self._tasks.put((None, None))
        self.thread.join(timeout=10)

    def _run(self) -> None:
        while True:
            job, fn = self._tasks.get()
            if job is None:
                break
            try:
                job.result = fn(job) or ""
            except Exception as e:  # se muestra en la web
                job.error = f"{e}" if str(e) else type(e).__name__
                job.log.append("ERROR: " + job.error)
                traceback.print_exc()
            finally:
                job.running = False
        browser = self.state.get("browser")
        if browser:
            try:
                browser.close()
            except Exception:
                pass
