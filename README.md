# UJI Sync

Herramienta personal para descargar y organizar automáticamente los materiales
de tus asignaturas del **Aula Virtual de la UJI** (Moodle).

- **Tú** inicias sesión a mano en una ventana del navegador (SSO + doble factor).
- UJI Sync **no pide ni guarda tu contraseña**: trabaja con la sesión que tú abres
  y solo ve lo que Moodle ya te deja ver.
- Descarga PDF, PowerPoint, Word, Excel, imágenes y otros archivos, y guarda los
  enlaces como accesos directos `.url`.
- Organiza por asignatura y por sección/tema, y no duplica lo ya descargado.

```
UJI/
├── Matemáticas/
│   ├── 00 - General/
│   │   └── Web de la asignatura.url
│   ├── 01 - Tema 1_ Introducción/
│   │   ├── Tema 1.pdf
│   │   └── Prácticas/          ← Carpeta de Moodle, con sus subcarpetas
│   └── _versiones_anteriores/  ← copias antiguas si el profesor sustituye un archivo
├── Física/
└── .uji-sync.db                ← registro de lo descargado
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

### Diagnóstico

Si algo no funciona, ejecuta el diagnóstico. No descarga nada: comprueba el login,
lista tus cursos y muestra cómo se lee un curso.

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
  `%LOCALAPPDATA%\UJISync\config.json`.
- Las peticiones se hacen de una en una y con una pausa, para no cargar el servidor.
- Usa los materiales solo para ti: no los redistribuyas.

## Qué hace y qué no hace (v0.1)

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
`_versiones_anteriores/`. Si borras un archivo, se vuelve a descargar.

## Estructura del código

```
uji_sync/
  config.py    rutas y preferencias (nunca credenciales)
  moodle.py    navegador + login manual + lectura de cursos/secciones/recursos
  sync.py      descarga, organización, duplicados y resumen
  registry.py  registro SQLite (archivos y ejecuciones)
  fsutils.py   nombres válidos en Windows, URLs pluginfile.php
  ui.py        interfaz tkinter
  cli.py       entrada: interfaz o --diagnostico
tests/         pruebas con un Moodle simulado (no es el Aula Virtual real)
```

Pruebas: `pip install -r requirements-dev.txt` y luego `python -m pytest`.

## Preparado para el futuro (Fase 4, no implementado)

Cada función futura encaja en una pieza existente, sin reescribir nada:

| Función | Dónde encaja |
|---|---|
| Tareas y fechas de entrega, calendario | Nuevo método en `MoodleBrowser` con una función AJAX de Moodle (*se verificará antes de usarla*) + tabla nueva en `registry.py` |
| Anuncios nuevos | Leer el foro "Avisos" (`modtype_forum`, ya detectado en `get_course_sections`) |
| Novedades desde la última sincronización | Tablas `runs` y `files` (`first_seen`, `last_changed`) ya guardan el historial |
| Buscador en todos los materiales | Extraer texto de los archivos a un índice SQLite FTS5 junto al registro |
| Resúmenes / análisis de PDFs con IA | Módulo aparte que lea los archivos registrados; no toca la sincronización |
