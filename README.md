# UJI Sync

Herramienta personal para descargar y organizar automáticamente los materiales
de tus asignaturas del **Aula Virtual de la UJI** (Moodle).

- **Tú** inicias sesión a mano en una ventana del navegador (SSO + doble factor).
- UJI Sync **no pide ni guarda tu contraseña**: trabaja con la sesión que tú abres
  y solo ve lo que Moodle ya te deja ver.
- Descarga PDF, PowerPoint, Word, Excel, imágenes y otros archivos, y guarda los
  enlaces como accesos directos `.url`.
- Organiza por asignatura y por sección/tema, y no duplica lo ya descargado.
- Puede guardar todo directamente en **Google Drive**.
- Opcional: **resume con IA (Claude)** cada material nuevo: idea principal,
  resumen, puntos clave, conceptos y preguntas de repaso.

```
UJI/
├── Matemáticas/
│   ├── 00 - General/
│   │   └── Web de la asignatura.url
│   ├── 01 - Tema 1_ Introducción/
│   │   ├── Tema 1.pdf
│   │   └── Prácticas/          ← Carpeta de Moodle, con sus subcarpetas
│   ├── _resumenes_IA/          ← resúmenes con IA, con la misma estructura de temas
│   │   ├── Novedades.md
│   │   └── 01 - Tema 1_ Introducción/
│   │       └── Tema 1.pdf - resumen.md
│   └── _versiones_anteriores/  ← copias antiguas si el profesor sustituye un archivo
└── Física/
```

La investigación previa (tecnología, API, autenticación, límites) está en
[`docs/FASE1-investigacion.md`](docs/FASE1-investigacion.md).

## Instalación en Windows

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>
   (marca *"Add python.exe to PATH"*). `tkinter` viene incluido.
2. Abre **PowerShell** en la carpeta del proyecto y ejecuta:

   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

3. UJI Sync usa **Microsoft Edge**, que ya viene con Windows. Si no lo tuvieras:
   `.venv\Scripts\python -m playwright install chromium`.

## Uso

Haz doble clic en **`UJI Sync.bat`** (o `.venv\Scripts\python -m uji_sync`).

1. Pulsa **"1. Abrir Aula Virtual e iniciar sesión"**. Se abre Edge: inicia sesión
   con tu cuenta UJI como siempre (incluido el doble factor).
2. La aplicación detecta que has entrado y muestra tus asignaturas.
3. Marca las que quieras y pulsa **"Sincronizar Aula Virtual"**.
4. Al terminar verás el resumen:

   ```
   Sincronización completada

   Matemáticas → 3 archivos nuevos, 12 sin cambios
   Física → 0 archivos nuevos, 8 sin cambios
   ```

Consejo: la primera vez marca **"Solo analizar (no descargar)"** para ver qué
se descargaría sin escribir nada en disco.

## Guardar en Google Drive

1. Instala **Google Drive para ordenadores**
   (<https://www.google.com/drive/download/>) e inicia sesión con tu cuenta de Google.
   Drive aparecerá en el Explorador de Windows, normalmente como `G:\Mi unidad`.
2. En UJI Sync pulsa **"Usar Google Drive"**: la carpeta de destino pasa a ser
   `G:\Mi unidad\UJI`.
3. Sincroniza como siempre. Google Drive sube los archivos solo, con la misma
   organización por asignatura y tema, y los verás en <https://drive.google.com>
   y en el móvil.

Detalles:

- UJI Sync no necesita permisos sobre tu cuenta de Google: solo escribe en una
  carpeta de tu PC, y la app oficial de Google se encarga de subirla.
- El **registro** de descargas se guarda en tu PC
  (`%LOCALAPPDATA%\UJISync\registros\`), no en Drive, para evitar que Drive
  bloquee o duplique la base de datos mientras se usa.
- Si usas UJI Sync en **otro PC** con el mismo Drive, los archivos que ya estén
  en Drive y sean idénticos se reconocen y no se duplican.
- Si Drive no se detecta (por ejemplo, porque lo tienes en otra letra o en otro
  idioma), elige la carpeta a mano con **"Cambiar…"**.

Alternativa descartada: subir con la API de Google Drive. Obligaría a crear un
proyecto en Google Cloud y a guardar en el PC un token con acceso a tu Drive, y
sería mucho más código para el mismo resultado.

## Resúmenes con IA (Claude)

Cuando se descarga un material nuevo, Claude lo lee y deja un resumen en
`<Asignatura>/_resumenes_IA/`, con la misma estructura de temas (y, si usas Google
Drive, también en Drive). Cada resumen incluye:

- **En una frase**: la idea principal.
- **Resumen**, **puntos clave** y **conceptos** con su definición.
- **Preguntas de repaso**, para autoevaluarte.
- Un enlace al archivo original.

Además, `_resumenes_IA/Novedades.md` va acumulando (lo más reciente arriba) qué
ha llegado en cada sincronización y de qué trata.

Formatos: **PDF** (Claude ve también tablas, fórmulas e imágenes), **Word
(.docx)**, **PowerPoint (.pptx)**, incluidas las notas del orador, y texto. Los
Excel, imágenes sueltas y formatos antiguos (.doc, .ppt) no se resumen.

### Activarlo

1. Crea una clave de API en <https://console.anthropic.com/> (API Keys) y añade
   saldo. **Es de pago por uso** y va aparte de cualquier suscripción a Claude.
2. En UJI Sync marca **"Resumir con IA los archivos nuevos"**. La primera vez te
   pedirá la clave: se guarda en el **Administrador de credenciales de Windows**,
   nunca en un archivo. Para cambiarla o borrarla, usa **"Clave de API…"**.
3. Sincroniza. Al final verás los resúmenes creados y el coste aproximado.

Para resumir materiales que ya tenías descargados, pulsa **"Resumir pendientes"**
(usa las asignaturas marcadas, o todas si no hay ninguna marcada).

### Coste y control

- Modelo por defecto: **Claude Opus 5**, el de mejor calidad. Un PDF típico de
  unas 30 páginas cuesta aproximadamente entre 0,10 y 0,40 US$. En el desplegable
  puedes elegir **Claude Sonnet 5**, que cuesta menos de la mitad.
- **Cada contenido se resume una sola vez.** El resumen se guarda por la huella
  del archivo: resincronizar, mover o volver a descargar el mismo archivo no
  cuesta nada. Si borras un `.md`, se regenera gratis.
- Si en una sincronización hay **más de 20 archivos** que resumir, UJI Sync te
  pide confirmación antes de enviarlos.
- Los PDF de más de 22 MB y los documentos larguísimos se omiten (se avisa en el
  registro) en vez de recortarse.

### Privacidad

Para resumir un archivo, su contenido se envía a la API de Anthropic. La primera
vez que actives la función te lo recordará. Los resúmenes son para tu estudio
personal: no redistribuyas los materiales ni los resúmenes. Son generados por IA
y pueden contener errores; consulta siempre el original.

## Diagnóstico

Si algo no funciona, ejecuta el diagnóstico. No descarga nada: dice si detecta
Google Drive, comprueba el login, lista tus cursos y muestra cómo se lee un curso.

```powershell
.venv\Scripts\python -m uji_sync --diagnostico            # primer curso
.venv\Scripts\python -m uji_sync --diagnostico --curso 1234
```

## Privacidad y seguridad

- La contraseña solo se escribe en la página oficial de la UJI; UJI Sync no la lee.
- La sesión queda en un perfil de navegador propio en
  `%LOCALAPPDATA%\UJISync\browser-profile`, así que puede que no tengas que
  volver a entrar cada vez. **Para cerrar la sesión, borra esa carpeta.**
- Las preferencias (carpeta de destino, asignaturas marcadas) están en
  `%LOCALAPPDATA%\UJISync\config.json`, y el registro de descargas en
  `%LOCALAPPDATA%\UJISync\registros\`.
- Las peticiones se hacen de una en una y con una pausa, para no cargar el servidor.
- La clave de la API de Claude (si usas los resúmenes) se guarda en el
  Administrador de credenciales de Windows.
- Usa los materiales solo para ti: no los redistribuyas.

## Qué hace y qué no hace

| Elemento de Moodle | Qué hace UJI Sync |
|---|---|
| Archivo (recurso) | Lo descarga |
| Carpeta | Descarga sus archivos conservando subcarpetas |
| URL | Crea un acceso directo `.url` |
| Archivos enlazados en etiquetas o en la descripción de un tema | Los descarga |
| Recursos sin permiso de descarga | Los cuenta como "no disponibles"; nunca intenta saltarse el permiso |
| Foros, tareas, cuestionarios, H5P, SCORM, vídeos incrustados | No los descarga (previsto para fases futuras) |

**Efecto secundario a saber:** para obtener el archivo de un recurso, UJI Sync abre
su enlace igual que si hicieras clic tú, así que Moodle lo registra como **visto**
(finalización de actividad, registros). Es lo mismo que hace la app oficial.

**Duplicados:** Moodle cambia la URL de un archivo (número de revisión) cuando el
profesorado lo sustituye. Si la URL no ha cambiado y el archivo sigue en tu disco,
no se vuelve a descargar. Si cambia, se descarga y se compara el contenido
(SHA-256): si es distinto, se actualiza y la versión antigua va a
`_versiones_anteriores/`. Si borras un archivo, se vuelve a descargar. Si ya hay
en la carpeta un archivo idéntico que no está en el registro, se reutiliza.

## Estructura del código

```
uji_sync/
  config.py    rutas, preferencias y detección de Google Drive (nunca credenciales)
  moodle.py    navegador + login manual + lectura de cursos/secciones/recursos
  sync.py      descarga, organización, duplicados y resumen
  registry.py  registro SQLite (archivos, ejecuciones y resúmenes)
  ai.py        resúmenes con Claude (extracción, petición, .md, novedades)
  apikey.py    clave de API en el almacén seguro del sistema
  fsutils.py   nombres válidos en Windows, URLs pluginfile.php
  ui.py        interfaz tkinter
  cli.py       entrada: interfaz o --diagnostico
tests/         pruebas con un Moodle simulado (no es el Aula Virtual real)
```

Pruebas: `pip install -r requirements-dev.txt` y luego `python -m pytest`.

## Preparado para el futuro (resto de la Fase 4)

Cada función futura encaja en una pieza existente, sin reescribir nada:

| Función | Dónde encaja |
|---|---|
| Tareas y fechas de entrega, calendario | Nuevo método en `MoodleBrowser` con una función AJAX de Moodle (*se verificará antes de usarla*) + tabla nueva en `registry.py` |
| Anuncios nuevos | Leer el foro "Avisos" (`modtype_forum`, ya detectado en `get_course_sections`) |
| Novedades desde la última sincronización | Tablas `runs` y `files` (`first_seen`, `last_changed`) ya guardan el historial |
| Buscador en todos los materiales | Índice SQLite FTS5 con el texto y los resúmenes (tabla `summaries`, que ya guarda conceptos y puntos clave) |
| Preguntar a la IA sobre tus materiales | Reutilizar `ai.py` y los resúmenes guardados como contexto |
