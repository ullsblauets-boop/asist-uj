"""Interfaz sencilla con tkinter (incluido con Python en Windows).

Playwright no admite usarse desde varios hilos, así que todo el trabajo con el
navegador ocurre en un único hilo de trabajo (Worker). La interfaz solo recibe
mensajes por una cola y nunca se bloquea.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from .ai import DEFAULT_MODEL, MODELS, AIError, AIFatalError, AIProcessor, needs_api, pending
from .assistant import Assistant
from .claude_pro import PRO_DIR, write_pro_files
from .inbox import InboxOrganizer, inbox_dir, inbox_files
from .library import list_courses
from .mobile import MobileServer, new_pin
from .apikey import get_api_key, has_credentials, set_api_key, delete_api_key
from .config import BASE_URL, Settings, browser_profile_dir, find_google_drive, registry_path
from .moodle import Course, LoginCancelled, MoodleBrowser
from .registry import Registry
from .sync import CourseResult, Syncer, format_summary

AI_CONFIRM_OVER = 20  # pedir confirmación si hay más archivos que resumir


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
        root.geometry("720x760")
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

        ai = ttk.LabelFrame(self.root, text="IA (Claude)")
        ai.pack(fill="x", **pad)
        ai_row1, ai_row2 = ttk.Frame(ai), ttk.Frame(ai)  # dos filas: caben en ventanas estrechas
        ai_row1.pack(fill="x")
        ai_row2.pack(fill="x", pady=(4, 0))
        self.ai_var = tk.BooleanVar(value=self.settings.ai_enabled)
        ttk.Checkbutton(
            ai_row1, text="Resumir con IA los archivos nuevos", variable=self.ai_var,
            command=self.toggle_ai,
        ).pack(side="left")
        self.model_var = tk.StringVar(
            value=MODELS.get(self.settings.ai_model, MODELS[DEFAULT_MODEL]))
        ttk.Combobox(
            ai_row1, textvariable=self.model_var, values=list(MODELS.values()),
            state="readonly", width=30,
        ).pack(side="left", padx=6)
        ttk.Button(ai_row2, text="Clave de API…", command=self.configure_key).pack(side="left")
        self.pending_btn = ttk.Button(ai_row2, text="Resumir pendientes", command=self.start_pending)
        self.pending_btn.pack(side="left", padx=4)
        self.pro_var = tk.BooleanVar(value=self.settings.pro_index)
        ttk.Checkbutton(
            ai_row2, text="Preparar para Claude Pro (gratis)", variable=self.pro_var,
            command=self._save_settings,
        ).pack(side="left", padx=(8, 0))

        extra = ttk.LabelFrame(self.root, text="Asistente y apuntes")
        extra.pack(fill="x", **pad)
        ttk.Button(extra, text="💬 Asistente", command=self.open_assistant).pack(side="left")
        ttk.Button(extra, text="📂 Abrir bandeja de apuntes", command=self.open_inbox).pack(
            side="left", padx=4)
        self.inbox_btn = ttk.Button(extra, text="🗂 Organizar mis apuntes", command=self.start_inbox)
        self.inbox_btn.pack(side="left")
        ttk.Button(extra, text="📱 Móvil", command=self.toggle_mobile).pack(side="left", padx=4)
        self.mobile: MobileServer | None = None

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
        self.pending_btn.configure(state="disabled" if busy else "normal")
        self.inbox_btn.configure(state="disabled" if busy else "normal")
        self.sync_btn.configure(
            state="disabled" if busy or not self.course_vars else "normal"
        )

    # ------------------------------------------------------------------ IA
    def _model_id(self) -> str:
        label = self.model_var.get()
        return next((k for k, v in MODELS.items() if v == label), DEFAULT_MODEL)

    def _ensure_ai_ready(self) -> bool:
        if not self.settings.ai_consent:
            ok = messagebox.askyesno(
                "UJI Sync",
                "Para usar la IA (resúmenes, asistente y bandeja de apuntes), UJI Sync "
                "envía tus materiales a la API de Claude (Anthropic).\n\n"
                "· Se cobra por uso en tu cuenta de Anthropic (cada archivo se resume "
                "una sola vez).\n"
                "· Los resúmenes son para tu estudio personal: no los redistribuyas.\n\n"
                "¿Quieres activarlo?",
            )
            if not ok:
                return False
            self.settings.ai_consent = True
            self.settings.save()
        if not has_credentials():
            self.configure_key()
        return has_credentials()

    def toggle_ai(self) -> None:
        if self.ai_var.get() and not self._ensure_ai_ready():
            self.ai_var.set(False)
        self._save_settings()

    def configure_key(self) -> None:
        key = simpledialog.askstring(
            "Clave de API de Claude",
            "Pega tu clave de API de Anthropic (empieza por «sk-ant-»).\n"
            "Se consigue en https://console.anthropic.com/ → API Keys.\n\n"
            "Se guardará en el Administrador de credenciales de Windows.\n"
            "Déjalo vacío para borrar la clave guardada.",
            show="*", parent=self.root,
        )
        if key is None:
            return
        if not key.strip():
            if get_api_key() and messagebox.askyesno("UJI Sync", "¿Borrar la clave guardada?"):
                delete_api_key()
            return
        if set_api_key(key):
            messagebox.showinfo("UJI Sync", "Clave guardada de forma segura.")
        else:
            messagebox.showerror(
                "UJI Sync",
                "No se pudo guardar la clave en el almacén de credenciales.\n"
                "Como alternativa, define la variable de entorno ANTHROPIC_API_KEY.",
            )

    def start_pending(self) -> None:
        """Resume los archivos ya descargados que aún no tienen resumen."""
        if not self._ensure_ai_ready():
            return
        dest = Path(self.dest_var.get()).expanduser()
        ids = [cid for cid, (_, var) in self.course_vars.items() if var.get()] or None
        reg = Registry(registry_path(dest))
        try:
            recs = pending(reg, dest, ids)
            to_send = sum(needs_api(reg, r) for r in recs)
        finally:
            reg.close()
        if not recs:
            messagebox.showinfo("UJI Sync", "No hay materiales pendientes de resumir.")
            return
        if to_send and not messagebox.askyesno(
            "UJI Sync",
            f"Hay {len(recs)} archivos sin resumen; {to_send} se enviarán a Claude "
            "(tiene coste).\n\n¿Continuar?",
        ):
            return
        self._save_settings()
        self._set_busy(True)
        self.status_var.set("Resumiendo con IA…")
        self.worker.submit(self._task_ai, dest, [r.key for r in recs], "", self._model_id())

    # ------------------------------------------------- asistente y bandeja
    def _dest(self) -> Path:
        return Path(self.dest_var.get()).expanduser()

    def open_assistant(self) -> None:
        if not list_courses(self._dest()):
            messagebox.showinfo("UJI Sync", "Primero sincroniza el Aula Virtual para tener materiales.")
            return
        if self._ensure_ai_ready():
            AssistantWindow(self.root, self._dest(), self._model_id())

    def open_inbox(self) -> None:
        path = inbox_dir(self._dest())
        try:
            if sys.platform == "win32":
                os.startfile(path)  # abre la carpeta en el Explorador
            else:
                subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", str(path)])
        except OSError:
            messagebox.showinfo("UJI Sync", f"Deja tus apuntes en:\n{path}")

    def start_inbox(self) -> None:
        dest = self._dest()
        files = inbox_files(dest)
        if not files:
            messagebox.showinfo(
                "UJI Sync",
                f"La bandeja está vacía. Deja tus apuntes en:\n{inbox_dir(dest)}\n\n"
                "y vuelve a pulsar «Organizar mis apuntes».",
            )
            return
        if not list_courses(dest):
            messagebox.showinfo("UJI Sync", "Primero sincroniza el Aula Virtual para tener asignaturas.")
            return
        if not self._ensure_ai_ready():
            return
        if not messagebox.askyesno(
            "UJI Sync",
            f"Hay {len(files)} archivos en la bandeja. Se enviarán a Claude para decidir "
            "su asignatura y tema (tiene un coste pequeño).\n\n¿Organizarlos?",
        ):
            return
        self._set_busy(True)
        self.status_var.set("Organizando tus apuntes…")
        self.worker.submit(self._task_inbox, dest, self._model_id())

    def toggle_mobile(self) -> None:
        if self.mobile:
            if messagebox.askyesno("UJI Sync", f"La web para el móvil está activa en\n\n"
                                   f"{self.mobile.url}\nPIN: {self.mobile.pin}\n\n¿Desactivarla?"):
                self.mobile.stop()
                self.mobile = None
                self.status_var.set("Web para el móvil desactivada.")
            return
        if not list_courses(self._dest()):
            messagebox.showinfo("UJI Sync", "Primero sincroniza el Aula Virtual para tener materiales.")
            return
        if not self._ensure_ai_ready():
            return
        if not self.settings.mobile_pin:
            self.settings.mobile_pin = new_pin()
            self.settings.save()
        try:
            self.mobile = MobileServer(self._dest(), self.settings.mobile_pin, self._model_id()).start()
        except OSError as e:
            messagebox.showerror("UJI Sync", f"No se pudo activar la web para el móvil: {e}")
            return
        self.status_var.set(f"📱 Web para el móvil: {self.mobile.url} · PIN {self.mobile.pin}")
        messagebox.showinfo(
            "UJI Sync",
            "Web para el móvil activada.\n\n"
            f"1. Conecta el móvil a la misma wifi que este PC.\n"
            f"2. Abre en el navegador del móvil:\n    {self.mobile.url}\n"
            f"3. Escribe el PIN:  {self.mobile.pin}\n\n"
            "Consejo: añádela a la pantalla de inicio para abrirla como una app.\n\n"
            "Si Windows pregunta por el firewall, permite el acceso solo en redes "
            "privadas. No la actives en redes públicas.",
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
        self.worker.submit(self._task_sync, selected, dest, self.dry_var.get(), self.pro_var.get())

    def _save_settings(self) -> None:
        self.settings.dest_dir = self.dest_var.get()
        self.settings.include_past = self.past_var.get()
        self.settings.ai_enabled = self.ai_var.get()
        self.settings.ai_model = self._model_id()
        self.settings.pro_index = self.pro_var.get()
        self.settings.selected_course_ids = [
            cid for cid, (_, var) in self.course_vars.items() if var.get()
        ]
        self.settings.save()

    def on_close(self) -> None:
        if self.course_vars:
            self._save_settings()
        if self.mobile:
            self.mobile.stop()
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

    def _task_sync(self, courses: list[Course], dest: Path, dry_run: bool, pro: bool = False) -> None:
        w = self.worker
        syncer = Syncer(
            w.browser, dest, dry_run=dry_run,
            log=lambda t: w.events.put(("log", t)), should_stop=w.stop.is_set,
        )
        try:
            results = syncer.sync(courses)
        finally:
            syncer.close()
        if pro and not dry_run:
            write_pro_files(dest, results)  # sin IA: índice y novedades para la app de Claude
            w.events.put(("log", f"📋 Índice para Claude actualizado en {PRO_DIR}/"))
        w.events.put(("synced", (results, dest, dry_run)))

    def _task_inbox(self, dest: Path, model: str) -> None:
        w = self.worker
        reg = Registry(registry_path(dest))
        try:
            org = InboxOrganizer(dest, reg, model=model,
                                 log=lambda t: w.events.put(("log", t)), should_stop=w.stop.is_set)
            text = org.organize().text()
        finally:
            reg.close()
        w.events.put(("summary", text))

    def _task_ai(self, dest: Path, keys: list[str], prefix: str, model: str) -> None:
        w = self.worker
        reg = Registry(registry_path(dest))
        try:
            records = [r for k in keys if (r := reg.get(k))]
            proc = AIProcessor(dest, reg, model=model,
                               log=lambda t: w.events.put(("log", t)), should_stop=w.stop.is_set)
            ai_text = proc.process(records).text()
        finally:
            reg.close()
        text = "\n\n".join(t for t in (prefix, ai_text) if t) or "No había nada que resumir."
        w.events.put(("summary", text))

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

    def _on_synced(self, payload: tuple[list[CourseResult], Path, bool]) -> None:
        results, dest, dry_run = payload
        text = format_summary(results, dry_run)
        keys = [k for r in results for k in r.changed_keys]
        if dry_run or not self.ai_var.get() or not keys:
            return self._on_summary(text)
        reg = Registry(registry_path(dest))
        try:
            to_send = sum(needs_api(reg, rec) for k in keys if (rec := reg.get(k)))
        finally:
            reg.close()
        if to_send > AI_CONFIRM_OVER and not messagebox.askyesno(
            "UJI Sync",
            f"{text}\n\nHay {to_send} archivos nuevos para resumir con IA (tiene coste). "
            "¿Resumirlos ahora?\n(Si dices que no, podrás hacerlo luego con "
            "«Resumir pendientes».)",
        ):
            return self._on_summary(text)
        self.status_var.set("Resumiendo con IA…")
        self.worker.submit(self._task_ai, dest, keys, text, self._model_id())

    def _on_summary(self, text: str) -> None:
        self._set_busy(False)
        self.status_var.set(text.splitlines()[0])
        self.log("\n" + text + "\n")
        messagebox.showinfo("UJI Sync", text)


class AssistantWindow:
    """Ventana de chat con el asistente de estudio."""

    ALL = "Todas las asignaturas"

    def __init__(self, parent: tk.Tk, root_dir: Path, model: str):
        self.root_dir = root_dir
        self.model = model
        self.assistant: Assistant | None = None
        self.busy = False
        self.updates: queue.Queue = queue.Queue()  # el hilo de la IA nunca toca tkinter
        self.win = tk.Toplevel(parent)
        self.win.title("UJI Sync · Asistente")
        self.win.geometry("720x620")

        top = ttk.Frame(self.win)
        top.pack(fill="x", padx=10, pady=6)
        ttk.Label(top, text="Sobre:").pack(side="left")
        self.scope_var = tk.StringVar(value=self.ALL)
        scope = ttk.Combobox(top, textvariable=self.scope_var, state="readonly", width=30,
                             values=[self.ALL] + list_courses(root_dir))
        scope.pack(side="left", padx=6)
        scope.bind("<<ComboboxSelected>>", lambda e: self.new_conversation())
        ttk.Button(top, text="Nueva conversación", command=self.new_conversation).pack(side="left")
        self.cost_var = tk.StringVar()
        ttk.Label(top, textvariable=self.cost_var, foreground="#555").pack(side="right")

        self.chat = scrolledtext.ScrolledText(self.win, wrap="word", state="disabled")
        self.chat.pack(fill="both", expand=True, padx=10)
        self.chat.tag_configure("who", font=("TkDefaultFont", 10, "bold"))
        self.chat.tag_configure("info", foreground="#777")

        bottom = ttk.Frame(self.win)
        bottom.pack(fill="x", padx=10, pady=8)
        # El botón se coloca primero para que el cuadro de texto no lo tape.
        self.send_btn = ttk.Button(bottom, text="Enviar", command=self.send)
        self.send_btn.pack(side="right", padx=(6, 0))
        self.entry = tk.Text(bottom, height=3, wrap="word")
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Return>", self._on_enter)
        self.new_conversation()
        self.entry.focus_set()
        self.win.after(100, self._poll)

    def _poll(self) -> None:
        if not self.win.winfo_exists():
            return
        try:
            while True:
                fn, args = self.updates.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.win.after(100, self._poll)

    def _write(self, text: str, tag: str | None = None) -> None:
        self.chat.configure(state="normal")
        self.chat.insert("end", text, tag)
        self.chat.see("end")
        self.chat.configure(state="disabled")

    def _on_enter(self, event):
        if not event.state & 0x1:  # Mayús+Intro = salto de línea
            self.send()
            return "break"

    def new_conversation(self) -> None:
        if self.busy:
            return
        scope = self.scope_var.get()
        try:
            self.assistant = Assistant(self.root_dir, None if scope == self.ALL else scope,
                                       model=self.model)
        except AIError as e:
            self.assistant = None
            messagebox.showerror("UJI Sync", str(e), parent=self.win)
            return
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        self.chat.configure(state="disabled")
        self._write(f"Pregúntame lo que quieras sobre {scope.lower() if scope == self.ALL else scope}: "
                    "dudas, explicaciones, qué entra en un tema, preguntas de repaso…\n\n", "info")
        self.cost_var.set("")

    def send(self) -> None:
        question = self.entry.get("1.0", "end").strip()
        if not question or self.busy or self.assistant is None:
            return
        self.entry.delete("1.0", "end")
        self._write("Tú\n", "who")
        self._write(question + "\n\n")
        self._write("Pensando…\n", "info")
        self.busy = True
        self.send_btn.configure(state="disabled")
        threading.Thread(target=self._ask, args=(self.assistant, question), daemon=True).start()

    def _ask(self, assistant: Assistant, question: str) -> None:
        on_read = lambda ruta: self.updates.put((self._write, (f"📖 Leyendo {ruta}…\n", "info")))
        try:
            answer, error = assistant.ask(question, on_read=on_read), None
        except (AIError, AIFatalError) as e:
            answer, error = None, str(e)
        except Exception as e:  # nunca dejar la ventana bloqueada
            answer, error = None, f"{type(e).__name__}: {e}"
        self.updates.put((self._show_answer, (assistant, answer, error)))

    def _show_answer(self, assistant: Assistant, answer: str | None, error: str | None) -> None:
        self.busy = False
        self.send_btn.configure(state="normal")
        if assistant is not self.assistant:
            return  # la conversación se reinició mientras tanto
        if error:
            self._write(f"⚠ {error}\n\n", "info")
        else:
            self._write("Asistente\n", "who")
            self._write(answer + "\n\n")
        self.cost_var.set(f"Coste: {assistant.cost:.2f} US$".replace(".", ","))


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
