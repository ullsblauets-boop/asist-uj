"use strict";
// UJI Study Assistant — interfaz web (PC y móvil). Sin dependencias externas.

const $ = (sel, el = document) => el.querySelector(sel);
const view = () => $("#view");
let status = null;          // /api/status
let jobTimer = null;

// ------------------------------------------------------------------ utilidades
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function api(path, { method = "GET", json, form } = {}) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (method !== "GET") opts.headers["X-UJI"] = "1";
  if (json !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(json); }
  if (form) opts.body = form;
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({ error: `Error ${r.status}` }));
  if (r.status === 401 && path !== "/api/login") showLogin();
  if (!r.ok && !data.error) data.error = `Error ${r.status}`;
  return data;
}

// Markdown mínimo: se escapa todo primero, así que nunca se inserta HTML de fuera.
function md(text) {
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
  let html = "", list = null;
  for (const raw of esc(text).split("\n")) {
    const line = raw.trimEnd();
    const ul = line.match(/^\s*[-*] (.*)/), ol = line.match(/^\s*\d+[.)] (.*)/);
    const kind = ul ? "ul" : ol ? "ol" : null;
    if (list && kind !== list) { html += `</${list}>`; list = null; }
    if (kind) { if (!list) { html += `<${kind}>`; list = kind; } html += `<li>${inline((ul || ol)[1])}</li>`; }
    else if (/^#{1,4} /.test(line)) html += `<h4>${inline(line.replace(/^#+ /, ""))}</h4>`;
    else if (line) html += `<p>${inline(line)}</p>`;
  }
  return html + (list ? `</${list}>` : "");
}

const opt = (value, label, selected) =>
  `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(label ?? value)}</option>`;
const fileUrl = (path, download) =>
  `/api/library/file?path=${encodeURIComponent(path)}${download ? "&download=1" : ""}`;
const fmtDate = (iso) => iso ? new Date(iso).toLocaleString("es-ES", { dateStyle: "short", timeStyle: "short" }) : "—";
function toast(msg) { alert(msg); }
function localOnly() {
  return `<div class="card"><h3>Solo en el PC</h3><p class="muted">Esta sección solo se puede usar desde el ordenador donde está instalada la aplicación.</p></div>`;
}
function aiNeeded() {
  return `<div class="notice">Esta función usa la IA de Claude (API de pago, aparte de Claude Pro).
    ${status.local ? 'Actívala en <a href="#configuracion">Configuración</a>.' : "Actívala desde el PC."}</div>`;
}

// ------------------------------------------------------------------ tareas en segundo plano
function renderJob(job) {
  const box = $("#job");
  if (!job) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  box.innerHTML = `<div class="card">
      <div class="row"><b class="grow">${job.running ? "⏳" : job.error ? "⚠️" : "✅"} ${esc(job.title)}</b>
        ${job.running ? "" : '<button class="btn small secondary" id="job-close">Cerrar</button>'}</div>
      ${job.log.length ? `<pre class="log">${esc(job.log.join("\n"))}</pre>` : ""}
      ${job.result ? `<pre class="result">${esc(job.result)}</pre>` : ""}
      ${job.error ? `<p class="warn">${esc(job.error)}</p>` : ""}
    </div>`;
  const log = $(".log", box); if (log) log.scrollTop = log.scrollHeight;
  const close = $("#job-close"); if (close) close.onclick = () => box.classList.add("hidden");
}

function watchJob(onDone) {
  clearInterval(jobTimer);
  const tick = async () => {
    const { job } = await api("/api/job");
    renderJob(job);
    if (!job || !job.running) { clearInterval(jobTimer); if (onDone) onDone(job); }
  };
  tick();
  jobTimer = setInterval(tick, 1000);
}

async function startJob(path, json, onDone) {
  const data = await api(path, { method: "POST", json: json ?? {} });
  if (data.error) { toast(data.error); return; }
  watchJob(onDone);
}

// ------------------------------------------------------------------ páginas
const pages = {
  async inicio() {
    const h = await api("/api/home");
    const courses = Object.entries(h.counts || {});
    view().innerHTML = `
      <h2>Hola 👋</h2>
      <p class="lead">Tu carrera en un sitio: materiales del Aula Virtual, tus apuntes y tu asistente de estudio.</p>
      <div class="grid">
        <div class="card"><div class="muted">Última sincronización</div><div class="stat">${h.last_sync ? fmtDate(h.last_sync) : "Nunca"}</div>
          ${status.local ? '<a class="btn small" href="#sincronizar">📥 Sincronizar</a>' : ""}</div>
        <div class="card"><div class="muted">Materiales</div><div class="stat">${courses.reduce((a, [, n]) => a + n, 0)}</div>
          <span class="muted">${courses.length} asignaturas</span></div>
        <div class="card"><div class="muted">En la bandeja de apuntes</div><div class="stat">${h.inbox}</div>
          <a class="btn small secondary" href="#biblioteca">📖 Ir a la biblioteca</a></div>
      </div>
      <div class="card"><h3>🆕 Novedades (últimos 14 días)</h3>
        ${h.recent.length ? `<ul class="list">${h.recent.map((it) => itemLine(it)).join("")}</ul>`
          : '<p class="muted">Todavía no hay novedades. Sincroniza el Aula Virtual o sube tus apuntes.</p>'}
      </div>`;
  },

  async asignaturas() {
    const { courses } = await api("/api/courses");
    view().innerHTML = `
      <h2>Mis asignaturas</h2>
      <p class="lead">Aparecen al sincronizar el Aula Virtual. Indica el profesor de cada una para etiquetar sus materiales.</p>
      ${courses.length ? "" : '<div class="card muted">Aún no hay asignaturas: ve a 📥 Sincronizar Aula Virtual.</div>'}
      <div class="grid">${courses.map((c) => `
        <div class="card">
          <h3>${esc(c.name)}</h3>
          <div class="muted">${c.total} materiales · ${c.temas.length} temas</div>
          <div class="row" style="margin:8px 0">${Object.entries(c.by_tipo).map(([t, n]) =>
            `<a class="badge" href="#biblioteca?course=${encodeURIComponent(c.name)}&tipo=${encodeURIComponent(t)}">${esc(t)} · ${n}</a>`).join("")}</div>
          <div class="row"><input class="grow profe" data-course="${esc(c.name)}" placeholder="Profesor/a" value="${esc(c.profesor)}">
            <button class="btn small save-profe" data-course="${esc(c.name)}">Guardar</button></div>
          <p><a href="#biblioteca?course=${encodeURIComponent(c.name)}">Ver materiales →</a></p>
        </div>`).join("")}</div>`;
    for (const b of view().querySelectorAll(".save-profe")) {
      b.onclick = async () => {
        const input = view().querySelector(`.profe[data-course="${CSS.escape(b.dataset.course)}"]`);
        const r = await api("/api/courses/profesor", { method: "POST", json: { course: b.dataset.course, profesor: input.value } });
        b.textContent = r.error ? "Error" : "✓ Guardado";
      };
    }
  },

  async sincronizar() {
    if (!status.local) { view().innerHTML = `<h2>Sincronizar Aula Virtual</h2>${localOnly()}`; return; }
    const { courses, selected } = await api("/api/sync/courses");
    const pend = status.ai.ready ? await api("/api/summaries/pending") : null;
    view().innerHTML = `
      <h2>Sincronizar Aula Virtual</h2>
      <p class="lead">Se abre Edge en este PC y <b>tú</b> inicias sesión con tu cuenta UJI. La aplicación no ve ni guarda tu contraseña
        y solo descarga lo que tu cuenta puede descargar.</p>
      <div class="card"><h3>1. Iniciar sesión</h3>
        <div class="row"><button class="btn" id="login-btn">🔐 Abrir Aula Virtual</button>
          <label class="check"><input type="checkbox" id="past"> Incluir cursos pasados</label></div>
      </div>
      <div class="card"><h3>2. Elegir asignaturas</h3>
        ${courses.length ? `<div class="row"><button class="btn small secondary" id="all">Marcar todas</button>
            <button class="btn small secondary" id="none">Desmarcar todas</button></div>
          ${courses.map((c) => `<label class="check"><input type="checkbox" class="course" value="${c.id}"
            ${selected.includes(c.id) ? "checked" : ""}> ${esc(c.name)}</label>`).join("")}`
          : '<p class="muted">Inicia sesión para ver tus asignaturas.</p>'}
      </div>
      <div class="card"><h3>3. Sincronizar</h3>
        <label class="check"><input type="checkbox" id="dry"> Solo analizar (no descargar nada)</label>
        <label class="check"><input type="checkbox" id="sum" ${status.ai.ready ? (status.ai.enabled ? "checked" : "") : "disabled"}>
          Resumir con IA los archivos nuevos ${status.ai.ready ? "" : '<span class="muted">(activa la IA en Configuración)</span>'}</label>
        <button class="btn" id="sync-btn" ${courses.length ? "" : "disabled"}>📥 Sincronizar Aula Virtual</button>
      </div>
      ${pend ? `<div class="card"><h3>Resúmenes pendientes</h3>
        <p class="muted">${pend.pending} materiales sin resumen · ${pend.to_send} se enviarían a Claude (coste).</p>
        <button class="btn secondary" id="pend-btn" ${pend.pending ? "" : "disabled"}>🤖 Resumir pendientes</button></div>` : ""}`;
    $("#login-btn").onclick = () => startJob("/api/sync/login", { include_past: $("#past").checked }, () => route());
    const all = $("#all"), none = $("#none");
    if (all) all.onclick = () => view().querySelectorAll(".course").forEach((c) => (c.checked = true));
    if (none) none.onclick = () => view().querySelectorAll(".course").forEach((c) => (c.checked = false));
    $("#sync-btn").onclick = () => startJob("/api/sync/run", {
      course_ids: [...view().querySelectorAll(".course:checked")].map((c) => +c.value),
      dry_run: $("#dry").checked, summarize: $("#sum").checked,
    }, refreshStatus);
    const pb = $("#pend-btn");
    if (pb) pb.onclick = () => confirm(`Se enviarán ${pend.to_send} archivos a Claude (tiene coste). ¿Seguir?`)
      && startJob("/api/summaries/run", {}, () => route());
  },

  async biblioteca(params) {
    const { courses } = await api("/api/courses");
    const byName = Object.fromEntries(courses.map((c) => [c.name, c]));
    const f = { course: params.get("course") || "", tema: params.get("tema") || "", tipo: params.get("tipo") || "",
                source: params.get("source") || "", q: params.get("q") || "" };
    const temasOf = (c) => (byName[c]?.temas || []);
    view().innerHTML = `
      <h2>Biblioteca de apuntes</h2>
      <p class="lead">Todo tu material, del Aula Virtual y tuyo, con asignatura, tema, tipo y profesor.</p>
      <details class="card" id="upload" ${params.get("subir") ? "open" : ""}><summary><b>⬆️ Subir apuntes, fotos o ejercicios</b></summary>
        <p class="muted">Fotos de apuntes, de la pizarra o de ejercicios, capturas, PDF, Word o PowerPoint.</p>
        <input type="file" id="files" multiple accept="image/*,.pdf,.docx,.pptx,.txt,.md">
        <div class="grid" style="margin-top:10px">
          <label class="field">Asignatura <select id="u-course">
            ${status.ai.ready ? opt("auto", "Automático (la IA decide)") : ""}
            ${courses.map((c) => opt(c.name)).join("")}</select></label>
          <label class="field">Tema <select id="u-tema"></select></label>
          <label class="field">Tipo <select id="u-tipo">${status.tipos.map((t) => opt(t, t, t === "Apuntes")).join("")}</select></label>
          <label class="field">Profesor <input id="u-profe"></label>
        </div>
        <button class="btn" id="u-send" style="margin-top:10px">Subir a la biblioteca</button>
        <span class="muted" id="u-status"></span>
      </details>
      <div class="card" id="inbox-card"></div>
      <div class="card">
        <div class="row">
          <select id="f-course">${opt("", "Todas las asignaturas")}${courses.map((c) => opt(c.name, c.name, c.name === f.course)).join("")}</select>
          <select id="f-tema">${opt("", "Todos los temas")}${temasOf(f.course).map((t) => opt(t, t, t === f.tema)).join("")}</select>
          <select id="f-tipo">${opt("", "Todos los tipos")}${status.tipos.map((t) => opt(t, t, t === f.tipo)).join("")}</select>
          <select id="f-source">${opt("", "Todo")}${Object.entries(status.sources).map(([k, v]) => opt(k, v, k === f.source)).join("")}</select>
          <input class="grow" id="f-q" placeholder="Buscar por nombre o descripción…" value="${esc(f.q)}">
        </div>
      </div>
      <div class="card"><div class="muted" id="count"></div><ul class="list" id="items"></ul></div>`;

    // subir
    const uc = $("#u-course"), ut = $("#u-tema"), up = $("#u-profe");
    const fillTemas = () => {
      const auto = uc.value === "auto";
      ut.innerHTML = auto ? opt("", "Automático") : opt("", "(sin tema concreto)") + temasOf(uc.value).map((t) => opt(t)).join("");
      ut.disabled = auto; $("#u-tipo").disabled = auto; up.disabled = auto;
      up.value = auto ? "" : (byName[uc.value]?.profesor || "");
    };
    if (f.course && byName[f.course]) uc.value = f.course;
    uc.onchange = fillTemas; fillTemas();
    $("#u-send").onclick = async () => {
      const files = $("#files").files;
      if (!files.length) { toast("Elige al menos un archivo."); return; }
      const form = new FormData();
      for (const file of files) form.append("files", file);
      form.append("course", uc.value); form.append("tema", ut.value);
      form.append("tipo", $("#u-tipo").value); form.append("profesor", up.value);
      $("#u-status").textContent = " Subiendo…";
      const r = await api("/api/library/upload", { method: "POST", form });
      if (r.error) { $("#u-status").textContent = " ⚠ " + r.error; return; }
      $("#files").value = "";
      if (r.job) { $("#u-status").textContent = " La IA está clasificando tus archivos…"; watchJob(() => route()); }
      else { $("#u-status").textContent = ` ✓ ${r.saved.length} archivo(s) añadidos.`; loadItems(); }
    };

    // bandeja
    const inbox = await api("/api/inbox");
    $("#inbox-card").innerHTML = `<h3>📥 Bandeja de apuntes</h3>
      <p class="muted">${inbox.files.length ? `${inbox.files.length} archivo(s) esperando: ${inbox.files.map(esc).join(", ")}`
        : "Vacía. También puedes dejar archivos en la carpeta «_Bandeja de apuntes» (por ejemplo, desde Google Drive en el móvil)."}</p>
      <div class="row">${inbox.files.length ? (status.ai.ready ? '<button class="btn small" id="org">🗂 Organizar con IA</button>'
        : '<span class="muted">Organizarlos automáticamente requiere la IA; si no, súbelos arriba eligiendo asignatura.</span>') : ""}
        ${status.local ? '<button class="btn small secondary" id="open-inbox">Abrir carpeta</button>' : ""}</div>`;
    const org = $("#org");
    if (org) org.onclick = () => startJob("/api/inbox/organize", {}, () => route());
    const oi = $("#open-inbox");
    if (oi) oi.onclick = () => api("/api/open", { method: "POST", json: { what: "inbox" } });

    // lista y filtros
    async function loadItems() {
      const qs = new URLSearchParams();
      for (const k of ["course", "tema", "tipo", "source", "q"]) {
        const v = $("#f-" + k).value; if (v) qs.set(k, v);
      }
      history.replaceState(null, "", "#biblioteca" + (qs.toString() ? "?" + qs : ""));
      const { items, total } = await api("/api/library?" + qs);
      $("#count").textContent = `${items.length} de ${total} materiales`;
      $("#items").innerHTML = items.map((it) => itemLine(it, true)).join("") || '<li class="muted">No hay materiales con estos filtros.</li>';
      for (const b of view().querySelectorAll(".edit")) b.onclick = () => editItem(items.find((i) => i.path === b.dataset.path), byName, loadItems);
    }
    for (const k of ["course", "tema", "tipo", "source"]) {
      $("#f-" + k).onchange = () => {
        if (k === "course") $("#f-tema").innerHTML = opt("", "Todos los temas") + temasOf($("#f-course").value).map((t) => opt(t)).join("");
        loadItems();
      };
    }
    let timer; $("#f-q").oninput = () => { clearTimeout(timer); timer = setTimeout(loadItems, 300); };
    loadItems();
  },

  async resolver() {
    view().innerHTML = `
      <h2>📷 Resolver ejercicio</h2>
      <p class="lead">Próximamente (Fase 5).</p>
      <div class="card soon">
        <p>Podrás subir la foto de un ejercicio y la aplicación:</p>
        <ol><li>leerá el enunciado,</li><li>identificará la asignatura y el tema,</li>
          <li>buscará en tus apuntes ejercicios parecidos y el método de tu profesor,</li>
          <li>y lo resolverá explicando datos, fórmula, por qué se usa, sustitución, operaciones, resultado y unidades.</li></ol>
        <p class="muted">Modos previstos: Resultado · Explicación corta · Paso a paso · Como mis apuntes · Modo profesor.
          Si tus materiales no muestran un método concreto, lo dirá y usará uno estándar.</p>
      </div>
      <p class="muted">Mientras tanto, ve subiendo a la <a href="#biblioteca?subir=1">biblioteca</a> tus ejercicios resueltos y apuntes:
        cuanto más material haya, mejor podrá seguir el método de tus clases.</p>`;
  },

  async buscar() {
    view().innerHTML = `
      <h2>🔎 Buscar en mis apuntes</h2>
      <p class="lead">Busca por nombre, o pregunta sobre tus materiales.</p>
      <div class="card"><h3>Buscar materiales</h3>
        <div class="row"><input class="grow" id="q" placeholder="Ej.: derivadas, cinemática, examen 2024…">
          <button class="btn" id="go">Buscar</button></div>
        <p class="muted">Por ahora busca en nombres, temas y descripciones. La búsqueda dentro del contenido de los documentos llega en la Fase 4.</p>
      </div>
      <div class="card"><h3>💬 Preguntar a mis apuntes</h3>
        ${status.ai.ready ? `
          <div class="row"><select id="scope">${opt("", "Todas las asignaturas")}${status.courses.map((c) => opt(c)).join("")}</select>
            <button class="btn small secondary" id="new">Nueva conversación</button><span class="muted grow" id="cost"></span></div>
          <div id="messages"></div>
          <div class="row"><textarea class="grow" id="question" rows="2" placeholder="¿Qué dio el profesor sobre derivadas?"></textarea>
            <button class="btn" id="send">Enviar</button></div>` : aiNeeded()}
      </div>`;
    const go = () => { location.hash = "#biblioteca?q=" + encodeURIComponent($("#q").value.trim()); };
    $("#go").onclick = go;
    $("#q").onkeydown = (e) => { if (e.key === "Enter") go(); };
    if (!status.ai.ready) return;
    let conversation = null;
    const add = (kind, html) => { const d = document.createElement("div"); d.className = "msg " + kind; d.innerHTML = html; $("#messages").appendChild(d); d.scrollIntoView({ block: "end" }); return d; };
    const reset = () => { conversation = null; $("#messages").innerHTML = ""; $("#cost").textContent = "";
      add("info", "Pregunta, por ejemplo: «¿Qué fórmulas aparecen en el tema 3?» o «¿Qué ejercicios tengo sobre derivadas?»"); };
    reset();
    $("#new").onclick = reset; $("#scope").onchange = reset;
    const send = async () => {
      const question = $("#question").value.trim(); if (!question) return;
      $("#question").value = ""; $("#send").disabled = true;
      add("me", esc(question));
      const thinking = add("info", "Pensando… (puede tardar si tiene que leer documentos)");
      const r = await api("/api/chat", { method: "POST", json: { conversation, course: $("#scope").value || null, question } });
      thinking.remove(); $("#send").disabled = false;
      if (r.error) { add("info", "⚠ " + esc(r.error)); return; }
      conversation = r.conversation;
      for (const p of r.reads) add("info", "📖 Ha leído " + esc(p));
      add("bot", md(r.answer));
      $("#cost").textContent = `Coste: ${r.cost.toFixed(2).replace(".", ",")} US$`;
    };
    $("#send").onclick = send;
    $("#question").onkeydown = (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } };
  },

  async tareas() {
    view().innerHTML = `
      <h2>📅 Tareas y entregas</h2>
      <p class="lead">Próximamente (Fase 7).</p>
      <div class="card soon"><p>Mostrará las tareas del Aula Virtual con su fecha de entrega, avisos de las próximas y un calendario.</p>
        <p class="muted">Antes de construirlo se comprobará qué funciones de Moodle están disponibles para tu cuenta.</p></div>`;
  },

  async configuracion() {
    if (!status.local) { view().innerHTML = `<h2>⚙️ Configuración</h2>${localOnly()}`; return; }
    const ai = status.ai;
    view().innerHTML = `
      <h2>⚙️ Configuración</h2>
      <div class="card"><h3>📁 Carpeta de la biblioteca</h3>
        <div class="row"><input class="grow" id="dest" value="${esc(status.dest)}">
          <button class="btn small" id="save-dest">Guardar</button>
          <button class="btn small secondary" id="drive">Usar Google Drive</button>
          <button class="btn small secondary" id="open">Abrir</button></div>
        <p class="muted">Con Google Drive para ordenadores, tus materiales estarán también en el móvil y en drive.google.com.</p>
      </div>
      <div class="card"><h3>🤖 IA (Claude)</h3>
        <p class="muted">Opcional. Resúmenes, asistente, organizar la bandeja y (más adelante) resolver ejercicios usan la API de Claude,
          que se paga por uso y va aparte de la suscripción Claude Pro.</p>
        <label class="check"><input type="checkbox" id="consent" ${ai.consent ? "checked" : ""}>
          Acepto que, al usar la IA, mis materiales se envíen a Anthropic para procesarlos.</label>
        <div class="row"><input class="grow" type="password" id="key" placeholder="${ai.has_key ? "Clave guardada ✓ (escribe otra para cambiarla)" : "Clave de API (sk-ant-…)"}">
          <button class="btn small" id="save-key">Guardar clave</button>
          ${ai.has_key ? '<button class="btn small secondary" id="del-key">Borrar</button>' : ""}</div>
        <p class="muted">La clave se guarda en el Administrador de credenciales de Windows, nunca en un archivo.</p>
        <div class="row"><label class="field">Modelo <select id="model">${Object.entries(ai.models).map(([k, v]) => opt(k, v, k === ai.model)).join("")}</select></label></div>
        <label class="check"><input type="checkbox" id="enabled" ${ai.enabled ? "checked" : ""}> Resumir automáticamente los archivos nuevos al sincronizar</label>
        <p>Estado: ${ai.ready ? '<b class="ok">IA activa</b>' : '<b class="warn">IA desactivada</b> (falta aceptar el aviso o la clave)'}</p>
      </div>
      <div class="card"><h3>✨ Claude Pro (gratis)</h3>
        <label class="check"><input type="checkbox" id="pro" ${status.pro_index ? "checked" : ""}>
          Preparar índice y novedades para usar tus materiales en la app de Claude (carpeta «_Para Claude»).</label>
      </div>
      <div class="card"><h3>📱 Acceso desde el móvil</h3>
        <label class="check"><input type="checkbox" id="mobile" ${status.mobile.enabled ? "checked" : ""}> Permitir el acceso desde el móvil en esta wifi</label>
        ${status.mobile.enabled ? `<p>Abre en el móvil <b>${esc(status.mobile.url)}</b> y escribe el PIN <b>${esc(status.mobile.pin)}</b>.</p>` : ""}
        <p class="muted">Solo en tu wifi de casa, no en redes públicas. Si Windows pregunta por el firewall, permite solo «Redes privadas».
          Desde el móvil no se pueden cambiar estos ajustes.</p>
      </div>
      <p class="muted">UJI Study Assistant ${esc(status.version)}</p>`;
    const save = async (json) => { const r = await api("/api/settings", { method: "POST", json }); if (r.error) toast(r.error); await refreshStatus(); };
    $("#save-dest").onclick = async () => { await save({ dest_dir: $("#dest").value }); toast("Carpeta guardada."); };
    $("#drive").onclick = async () => { const r = await api("/api/settings/drive", { method: "POST" }); if (r.error) toast(r.error); else { await refreshStatus(); route(); } };
    $("#open").onclick = () => api("/api/open", { method: "POST", json: { what: "dest" } });
    $("#consent").onchange = async (e) => { await save({ ai_consent: e.target.checked }); route(); };
    $("#save-key").onclick = async () => {
      const key = $("#key").value.trim(); if (!key) return;
      const r = await api("/api/apikey", { method: "POST", json: { key } });
      if (r.error) toast(r.error); else { await refreshStatus(); route(); }
    };
    const dk = $("#del-key");
    if (dk) dk.onclick = async () => { if (confirm("¿Borrar la clave guardada?")) { await api("/api/apikey", { method: "POST", json: { key: "" } }); await refreshStatus(); route(); } };
    $("#model").onchange = (e) => save({ ai_model: e.target.value });
    $("#enabled").onchange = (e) => save({ ai_enabled: e.target.checked });
    $("#pro").onchange = (e) => save({ pro_index: e.target.checked });
    $("#mobile").onchange = async (e) => {
      const r = await api("/api/mobile", { method: "POST", json: { enabled: e.target.checked } });
      if (r.error) toast(r.error);
      await refreshStatus(); route();
    };
  },
};

function itemLine(it, editable) {
  return `<li>
    <div class="row"><span class="item-title grow"><a href="${fileUrl(it.path)}" target="_blank" rel="noopener">${esc(it.titulo)}</a></span>
      <span class="badge accent">${esc(it.tipo)}</span>
      <span class="badge">${it.source === "propio" ? "Mis apuntes" : "Aula Virtual"}</span>
      ${editable ? `<button class="btn small secondary edit" data-path="${esc(it.path)}">Editar</button>` : ""}</div>
    <div class="muted">${esc(it.course)}${it.tema ? " · " + esc(it.tema) : ""}${it.profesor ? " · " + esc(it.profesor) : ""}</div>
    ${it.descripcion ? `<div>${esc(it.descripcion)}</div>` : ""}
  </li>`;
}

function editItem(it, byName, onSaved) {
  const own = it.source === "propio";
  const temas = (c) => byName[c]?.temas || [];
  const dlg = document.createElement("div");
  dlg.className = "card";
  dlg.innerHTML = `<h3>Editar «${esc(it.titulo)}»</h3>
    <div class="grid">
      <label class="field">Título <input id="e-titulo" value="${esc(it.titulo)}"></label>
      <label class="field">Asignatura <select id="e-course" ${own ? "" : "disabled"}>${Object.keys(byName).map((c) => opt(c, c, c === it.course)).join("")}</select></label>
      <label class="field">Tema <select id="e-tema" ${own ? "" : "disabled"}></select></label>
      <label class="field">Tipo <select id="e-tipo">${status.tipos.map((t) => opt(t, t, t === it.tipo)).join("")}</select></label>
      <label class="field">Profesor <input id="e-profe" value="${esc(it.profesor)}"></label>
    </div>
    ${own ? '<p class="muted">Si cambias la asignatura o el tema, el archivo se moverá a su carpeta.</p>'
      : '<p class="muted">Los archivos del Aula Virtual se quedan en su carpeta; solo cambian sus etiquetas.</p>'}
    <div class="row"><button class="btn" id="e-save">Guardar</button><button class="btn secondary" id="e-cancel">Cancelar</button></div>`;
  const li = view().querySelector(`.edit[data-path="${CSS.escape(it.path)}"]`).closest("li");
  li.after(dlg);
  const fill = () => { const c = $("#e-course", dlg).value;
    $("#e-tema", dlg).innerHTML = (own ? opt("", "(sin tema concreto)") : "") + (own ? temas(c) : [it.tema]).map((t) => opt(t, t || "—", t === it.tema)).join(""); };
  $("#e-course", dlg).onchange = fill; fill();
  $("#e-cancel", dlg).onclick = () => dlg.remove();
  $("#e-save", dlg).onclick = async () => {
    const json = { path: it.path, titulo: $("#e-titulo", dlg).value, tipo: $("#e-tipo", dlg).value, profesor: $("#e-profe", dlg).value };
    if (own) { json.course = $("#e-course", dlg).value; json.tema = $("#e-tema", dlg).value; }
    const r = await api("/api/library/update", { method: "POST", json });
    if (r.error) { toast(r.error); return; }
    dlg.remove(); onSaved();
  };
}

// ------------------------------------------------------------------ navegación
const TITLES = { inicio: "Inicio", asignaturas: "Mis asignaturas", sincronizar: "Sincronizar", biblioteca: "Biblioteca",
  resolver: "Resolver ejercicio", buscar: "Buscar", tareas: "Tareas y entregas", configuracion: "Configuración" };

async function refreshStatus() { status = await api("/api/status"); return status; }

async function route() {
  const [name, query] = (location.hash.slice(1) || "inicio").split("?");
  const page = pages[name] ? name : "inicio";
  for (const a of document.querySelectorAll("#menu a")) a.classList.toggle("active", a.dataset.page === page);
  $("#title").textContent = TITLES[page];
  closeMenu();
  if (!status || status.error) await refreshStatus();
  if (status.error) return;
  view().innerHTML = '<p class="muted">Cargando…</p>';
  await pages[page](new URLSearchParams(query || ""));
}

function closeMenu() { $("#sidebar").classList.remove("open"); $("#scrim").classList.add("hidden"); }
$("#menu-btn").onclick = () => { $("#sidebar").classList.add("open"); $("#scrim").classList.remove("hidden"); };
$("#scrim").onclick = closeMenu;

function showLogin() {
  view().innerHTML = `<div id="login"><h2>🎓 UJI Study</h2>
    <p>Escribe el PIN que aparece en <b>Configuración → Acceso desde el móvil</b>, en tu PC.</p>
    <input id="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="••••••">
    <button class="btn" id="pin-btn" style="width:100%;justify-content:center">Entrar</button>
    <p class="muted" id="pin-error"></p></div>`;
  const go = async () => {
    const r = await api("/api/login", { method: "POST", json: { pin: $("#pin").value.trim() } });
    if (r.error) { $("#pin-error").textContent = r.error; return; }
    status = null; route();
  };
  $("#pin-btn").onclick = go;
  $("#pin").onkeydown = (e) => { if (e.key === "Enter") go(); };
}

window.addEventListener("hashchange", route);
route().then(async () => {
  const { job } = await api("/api/job");
  if (job && job.running) watchJob(() => route());
});
