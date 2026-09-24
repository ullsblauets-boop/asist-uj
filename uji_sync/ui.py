"""Interfaz sencilla con tkinter (incluido con Python en Windows).

Playwright no admite usarse desde varios hilos, así que todo el trabajo con el
navegador ocurre en un único hilo de trabajo (Worker). La interfaz solo recibe
mensajes por una cola y nunca se bloquea.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from .config import BASE_URL, Settings, browser_profile_dir, find_google_drive
from .moodle import Course, LoginCancelled, MoodleBrowser
from .sync import Syncer, format_summary


class Worker(threading.Thread):
    def __init__(self, events: queue.Queue):
        super().__init__(daemon=True)
        self.tasks: queue.Queue = queue.Queue()
        self.events = events
        self.stop = threading.Event()
        self.browser: MoodleBrowser | None = None

    def submit(self, fn, *args) -> None:
        self.tasks.put((fn, args))

    def run(self) -> None:
        while True:
            fn, args = self.tasks.get()
            if fn is None:
                break
            try:
                fn(*args)
            except LoginCancelled:
                pass
            except Exception as e:  # mostrar cualquier fallo en la interfaz
                self.events.put(("error", f"{type(e).__name__}: {e}"))
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass

    def shutdown(self) -> None:
        self.stop.set()
        self.tasks.put((None, ()))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = Settings.load()
        self.events: queue.Queue = queue.Queue()
        self.worker = Worker(self.events)
        self.worker.start()
        self.course_vars: dict[int, tuple[Course, tk.BooleanVar]] = {}
        self.busy = False

        root.title("UJI Sync")
        root.geometry("720x620")
        root.minsize(520, 480)
        self._build()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self._poll_events)

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 4}
        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Carpeta de destino:").pack(side="left")
        self.dest_var = tk.StringVar(value=self.settings.dest_dir)
        ttk.Entry(top, textvariable=self.dest_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(top, text="Cambiar…", command=self.choose_dest).pack(side="left")
        ttk.Button(top, text="Usar Google Drive", command=self.use_google_drive).pack(
            side="left", padx=(4, 0))

        login = ttk.Frame(self.root)
        login.pack(fill="x", **pad)
        self.login_btn = ttk.Button(
            login, text="1. Abrir Aula Virtual e iniciar sesión", command=self.start_login
        )
        self.login_btn.pack(side="left")
        self.past_var = tk.BooleanVar(value=self.settings.include_past)
        ttk.Checkbutton(
            login, text="Incluir cursos pasados", variable=self.past_var, command=self.reload_courses
        ).pack(side="left", padx=10)

        self.status_var = tk.StringVar(
            value="Pulsa el botón 1. Se abrirá el navegador: inicia sesión tú mismo."
        )
        ttk.Label(self.root, textvariable=self.status_var, foreground="#555").pack(fill="x", **pad)

        box = ttk.LabelFrame(self.root, text="Asignaturas")
        box.pack(fill="both", expand=True, **pad)
        tools = ttk.Frame(box)
        tools.pack(fill="x")
        ttk.Button(tools, text="Marcar todas", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(tools, text="Desmarcar todas", command=lambda: self._set_all(False)).pack(side="left", padx=4)
        canvas = tk.Canvas(box, highlightthickness=0, height=160)
        scroll = ttk.Scrollbar(box, orient="vertical", command=canvas.yview)
        self.course_frame = ttk.Frame(canvas)
        self.course_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=self.course_frame, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        actions = ttk.Frame(self.root)
        actions.pack(fill="x", **pad)
        self.sync_btn = ttk.Button(
            actions, text="Sincronizar Aula Virtual", command=self.start_sync, state="disabled"
        )
        self.sync_btn.pack(side="left")
        self.dry_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            actions, text="Solo analizar (no descargar)", variable=self.dry_var
        ).pack(side="left", padx=10)

        self.log_box = scrolledtext.ScrolledText(self.root, height=12, state="disabled")
        self.log_box.pack(fill="both", expand=True, **pad)

    def _set_all(self, value: bool) -> None:
        for _, var in self.course_vars.values():
            var.set(value)

    def choose_dest(self) -> None:
        path = filedialog.askdirectory(initialdir=self.dest_var.get() or str(Path.home()))
        if path:
            self.dest_var.set(path)

    def use_google_drive(self) -> None:
        drive = find_google_drive()
        if drive is None:
            messagebox.showinfo(
                "UJI Sync",
                "No encuentro Google Drive en este PC.\n\n"
                "Instala «Google Drive para ordenadores» "
                "(https://www.google.com/drive/download/), inicia sesión con tu cuenta "
                "de Google y vuelve a pulsar este botón.\n\n"
                "También puedes elegir la carpeta a mano con «Cambiar…».",
            )
            return
        self.dest_var.set(str(drive / "UJI"))
        self.status_var.set(f"Los materiales se guardarán en Google Drive: {drive / 'UJI'}")

    def log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.login_btn.configure(state="disabled" if busy else "normal")
        self.sync_btn.configure(
            state="disabled" if busy or not self.course_vars else "normal"
        )

    # ------------------------------------------------------------ acciones
    def start_login(self) -> None:
        self._set_busy(True)
        self.status_var.set("Esperando a que inicies sesión en la ventana del navegador…")
        self.worker.submit(self._task_login, self.past_var.get())

    def reload_courses(self) -> None:
        if self.worker.browser and not self.busy:
            self._set_busy(True)
            self.worker.submit(self._task_courses, self.past_var.get())

    def start_sync(self) -> None:
        selected = [c for c, var in self.course_vars.values() if var.get()]
        if not selected:
            messagebox.showinfo("UJI Sync", "Selecciona al menos una asignatura.")
            return
        dest = Path(self.dest_var.get()).expanduser()
        self._save_settings()
        self._set_busy(True)
        self.status_var.set("Sincronizando…")
        self.worker.submit(self._task_sync, selected, dest, self.dry_var.get())

    def _save_settings(self) -> None:
        self.settings.dest_dir = self.dest_var.get()
        self.settings.include_past = self.past_var.get()
        self.settings.selected_course_ids = [
            cid for cid, (_, var) in self.course_vars.items() if var.get()
        ]
        self.settings.save()

    def on_close(self) -> None:
        if self.course_vars:
            self._save_settings()
        self.worker.shutdown()
        self.root.destroy()

    # ------------------------------------------- tareas (hilo del Worker)
    def _task_login(self, include_past: bool) -> None:
        w = self.worker
        if w.browser is None:
            w.browser = MoodleBrowser(BASE_URL, browser_profile_dir())
            w.browser.start()
        w.browser.open_site()
        w.browser.wait_for_login(should_stop=w.stop.is_set)
        w.events.put(("status", "Sesión iniciada. Cargando asignaturas…"))
        self._task_courses(include_past)

    def _task_courses(self, include_past: bool) -> None:
        courses = self.worker.browser.get_courses(include_past)
        self.worker.events.put(("courses", courses))

    def _task_sync(self, courses: list[Course], dest: Path, dry_run: bool) -> None:
        w = self.worker
        syncer = Syncer(
            w.browser, dest, dry_run=dry_run,
            log=lambda t: w.events.put(("log", t)), should_stop=w.stop.is_set,
        )
        try:
            results = syncer.sync(courses)
        finally:
            syncer.close()
        w.events.put(("summary", format_summary(results, dry_run)))

    # ------------------------------------------------ eventos (hilo de UI)
    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                getattr(self, f"_on_{kind}")(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)

    def _on_status(self, text: str) -> None:
        self.status_var.set(text)

    def _on_log(self, text: str) -> None:
        self.log(text)

    def _on_error(self, text: str) -> None:
        self._set_busy(False)
        self.status_var.set("Ha ocurrido un error.")
        self.log("ERROR: " + text)
        messagebox.showerror("UJI Sync", text)

    def _on_courses(self, courses: list[Course]) -> None:
        for child in self.course_frame.winfo_children():
            child.destroy()
        remembered = set(self.settings.selected_course_ids)
        self.course_vars = {}
        for c in courses:
            var = tk.BooleanVar(value=c.id in remembered)
            ttk.Checkbutton(self.course_frame, text=c.fullname, variable=var).pack(anchor="w")
            self.course_vars[c.id] = (c, var)
        self.status_var.set(f"{len(courses)} asignaturas encontradas. Marca las que quieras sincronizar.")
        self._set_busy(False)

    def _on_summary(self, text: str) -> None:
        self._set_busy(False)
        self.status_var.set(text.splitlines()[0])
        self.log("\n" + text + "\n")
        messagebox.showinfo("UJI Sync", text)


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
