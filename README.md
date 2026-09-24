# UJI Study Assistant

Aplicación personal para el día a día de la carrera en la **Universitat Jaume I**:

1. **Aula Virtual**: descarga y organiza los materiales de tus asignaturas.
2. **Biblioteca de apuntes**: tus fotos, PDF y ejercicios, etiquetados por
   asignatura, tema, tipo y profesor.
3. **Asistente de estudio** basado en tus materiales (en desarrollo por fases).

Funciona en el navegador del PC y, opcionalmente, en el móvil dentro de tu wifi.

## Estado de las fases

| Fase | Contenido | Estado |
|---|---|---|
| 1 | Investigación del Aula Virtual / Moodle ([informe](docs/FASE1-investigacion.md)) | ✅ |
| 2 | Sincronización del Aula Virtual | ✅ (pendiente de probar con tu cuenta) |
| 3 | Biblioteca de documentos con etiquetas | ✅ |
| 4 | Búsqueda dentro del contenido de los documentos | ⏳ siguiente |
| 5 | Resolver ejercicio con fotos | ⏳ |
| 6 | Modo «Como mis apuntes / profesor» | ⏳ |
| 7 | Tareas, entregas y calendario | ⏳ |

## Instalación en Windows

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>
   (marca *"Add python.exe to PATH"*).
2. Abre **PowerShell** en la carpeta del proyecto y ejecuta:

   ```powershell
   py -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```

3. Usa **Microsoft Edge** (viene con Windows) para el inicio de sesión en el
   Aula Virtual. Si no lo tuvieras: `.venv\Scripts\python -m playwright install chromium`.

## Uso

Haz doble clic en **`UJI Study Assistant.bat`**. Se abre una ventana negra (el
servidor: déjala abierta) y la aplicación en tu navegador, en
<http://127.0.0.1:8765>. Para salir, cierra la ventana negra.

| Sección | Qué hace |
|---|---|
| 🏠 **Inicio** | Última sincronización, materiales, bandeja y novedades de los últimos 14 días. |
| 📚 **Mis asignaturas** | Asignaturas con sus temas y materiales por tipo. Aquí indicas el **profesor** de cada una. |
| 📥 **Sincronizar Aula Virtual** | 1) Se abre Edge y **tú** inicias sesión. 2) Marcas las asignaturas. 3) Sincronizas. Puedes solo analizar primero. |
| 📖 **Biblioteca de apuntes** | Todo tu material con filtros (asignatura, tema, tipo, origen, texto). Subes fotos, capturas y PDF, y editas las etiquetas. |
| 📷 **Resolver ejercicio** | Próximamente (Fase 5). |
| 🔎 **Buscar en mis apuntes** | Busca por nombre y descripción. Con la IA activada, puedes **preguntar** a tus materiales. |
| 📅 **Tareas y entregas** | Próximamente (Fase 7). |
| ⚙️ **Configuración** | Carpeta (o Google Drive), IA, modo Claude Pro y acceso desde el móvil. |

### Seguridad del Aula Virtual

- **Tú** inicias sesión en una ventana de Edge normal (SSO y doble factor). La
  aplicación **no pide ni guarda tu contraseña** y no se salta ningún control.
- Solo accede a lo que tu cuenta puede ver, y lo que no se puede descargar se
  marca como «no disponible».
- La sesión queda en `%LOCALAPPDATA%\UJISync\browser-profile`. Para cerrarla,
  borra esa carpeta.

## Organización de la carpeta

Las carpetas siguen **los temas del Aula Virtual**, tal cual los organiza el
profesor. El **tipo** de material es una etiqueta (se filtra en la biblioteca), así
que nunca se mueve un archivo del profesor por clasificarlo mal.

```
UJI Study/
├── _Bandeja de apuntes/        ← archivos pendientes de organizar (p. ej. desde el móvil)
├── _Para Claude/               ← índice y novedades para la app de Claude (modo Pro)
├── Cálculo I/
│   ├── 00 - General/
│   ├── 03 - Tema 3_ Derivadas/ ← materiales del Aula Virtual
│   ├── Mis apuntes/
│   │   └── 03 - Tema 3_ Derivadas/   ← tus fotos y apuntes de ese tema
│   ├── _resumenes_IA/          ← (opcional) resúmenes con IA
│   └── _versiones_anteriores/  ← copias antiguas si el profesor sustituye un archivo
└── Física I/
```

**Tipos de material:** Teoría · Apuntes · Problemas · Ejercicios · Ejercicios
corregidos · Exámenes · Prácticas · Pizarra · Otros.

- A los archivos del Aula Virtual se les propone un tipo según su nombre
  (gratis y sin IA). Por ejemplo, «Boletín 3» pasa a Problemas y «Examen parcial»
  a Exámenes. Se puede corregir con «Editar».
- Tus apuntes se guardan en `Mis apuntes/<Tema>/`. Si les cambias la asignatura
  o el tema, el archivo se mueve a su carpeta.
- Los archivos del Aula Virtual no se mueven nunca: solo cambian sus etiquetas.
- Las etiquetas se guardan en el registro local
  (`%LOCALAPPDATA%\UJISync\registros\`) y se conservan entre sincronizaciones.

## Google Drive

Instala **Google Drive para ordenadores** y, en ⚙️ Configuración, pulsa
**"Usar Google Drive"**: la biblioteca pasa a `G:\Mi unidad\UJI Study` y estará
también en el móvil y en drive.google.com. Si usas la aplicación en otro PC con el
mismo Drive, los archivos idénticos se reconocen y no se duplican.

## IA (opcional)

Las funciones de IA usan la **API de Claude**, que **se paga por uso y va aparte
de la suscripción Claude Pro**. Sin activar la IA, todo lo demás funciona gratis.

| Función | Necesita API |
|---|---|
| Sincronizar, organizar, biblioteca, etiquetas, filtros | No |
| Índice para la app de Claude (modo Pro) | No |
| Resúmenes automáticos de los materiales | Sí |
| Preguntar a tus materiales | Sí |
| Subir con asignatura «Automático» / organizar la bandeja | Sí |
| Resolver ejercicio (Fase 5) | Sí |

Para activarla, en ⚙️ Configuración:

1. Acepta el aviso de privacidad: tus materiales se envían a Anthropic cuando
   usas la IA.
2. Pega tu clave de API, que se crea en <https://console.anthropic.com/>. Se
   guarda en el **Administrador de credenciales de Windows**, nunca en un archivo.
3. Elige el modelo: Claude Opus 5 (mejor calidad) o Claude Sonnet 5 (más barato).

Cada material se resume una sola vez, porque se reconoce por su contenido. Si una
sincronización trae más de 20 archivos, no se resumen automáticamente: lo decides
tú con «Resumir pendientes». En cada respuesta se muestra el coste aproximado.

### Con Claude Pro, sin pagar la API

Con **"Preparar para Claude Pro"** (activado por defecto), cada sincronización
actualiza `_Para Claude/` con un índice de materiales, las novedades y una guía.
En la app de Claude, conecta Google Drive (Ajustes → Conectores), crea un
Proyecto «UJI» con las instrucciones de la guía y pregunta ahí. Si Claude no
puede abrir algún archivo desde Drive, adjúntalo en el chat.

## Desde el móvil

En ⚙️ Configuración, activa **"Permitir el acceso desde el móvil"**. Verás una
dirección (p. ej. `http://192.168.1.35:8766`) y un **PIN**. Ábrela en el móvil,
conectado a la misma wifi, y añádela a la pantalla de inicio.

- En el móvil tienes la misma aplicación: biblioteca (con la cámara para subir
  fotos), búsqueda, asistente y novedades.
- Sincronizar y cambiar ajustes solo se puede hacer desde el PC.
- Seguridad:
  - Hace falta el PIN, y tras 5 intentos fallidos se bloquea un minuto.
  - Solo se sirven archivos de la biblioteca.
  - La conexión es HTTP sin cifrar: úsala **solo en tu wifi de casa**.
  - Si Windows pregunta por el firewall, permite únicamente «Redes privadas».

## Diagnóstico

Si la sincronización no funciona con tu cuenta, ejecuta el diagnóstico (no
descarga nada) y revisa lo que muestra:

```powershell
.venv\Scripts\python -m uji_sync --diagnostico
```

## Estructura del código

```
uji_sync/
  webapp.py      servidor web (Flask) y API; seguridad (PIN, solo-PC, cabeceras)
  web/           interfaz: index.html, app.js, style.css (sin dependencias externas)
  jobs.py        tareas en segundo plano (el navegador siempre en el mismo hilo)
  moodle.py      navegador + login manual + lectura de cursos y recursos
  sync.py        descarga, organización, duplicados y resumen
  library.py     carpetas, biblioteca (etiquetas, filtros, subidas, edición)
  registry.py    registro SQLite (archivos, resúmenes, biblioteca, profesores)
  ai.py          llamadas a Claude y resúmenes
  assistant.py   preguntas sobre tus materiales
  inbox.py       bandeja: clasificar con IA
  claude_pro.py  índice para la app de Claude (sin API)
  config.py, apikey.py, fsutils.py, cli.py
tests/           pruebas con un Moodle simulado y un Claude simulado (sin coste)
```

Pruebas: `pip install -r requirements-dev.txt` y luego `python -m pytest`.
