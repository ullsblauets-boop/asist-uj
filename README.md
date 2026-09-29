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
| 4 | Búsqueda dentro del contenido de los documentos | ✅ |
| 5 | Resolver ejercicio con fotos | ✅ |
| 6 | Modo «Como mis apuntes / profesor» | ✅ |
| 7 | Tareas, entregas, calendario y avisos | ✅ |

Todas las fases están construidas y probadas con un Aula Virtual y un Claude
simulados. La sincronización está comprobada con tu cuenta real. Las funciones de
IA, las tareas y los avisos están pendientes de probar con tus datos reales.

## Instalación en Windows

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>
   (marca *"Add python.exe to PATH"*).
2. Haz doble clic en **`Instalar.bat`** y espera a que diga «Listo» (unos
   minutos). Para actualizar a una versión nueva, igual: descomprímela y vuelve a
   hacer doble clic en `Instalar.bat`.

   (Equivale a ejecutar en PowerShell, dentro de la carpeta:
   `py -m venv .venv` y `.venv\Scripts\python -m pip install -r requirements.txt`.)

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
| 📷 **Resolver ejercicio** | Sube la foto de un ejercicio: se lee, se busca el método en tus apuntes y se resuelve explicado, incluso con el estilo de tus apuntes o de clase (requiere IA). |
| 🔎 **Buscar en mis apuntes** | Busca **dentro del contenido** de tus documentos (con página y fragmento). Con la IA activada, puedes **preguntar** a tus materiales. |
| 📅 **Tareas y entregas** | Entregas vencidas y próximas, calendario del mes, avisos de los profesores y exportación a Google Calendar u Outlook. |
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

## Resolver ejercicio

1. Sube una **foto** o un PDF del ejercicio (en el móvil, con la cámara) o
   escribe el enunciado.
2. Deja **Asignatura** y **Tema** en «Automático» o elígelos tú.
3. Elige el **modo**:
   - **Resultado**: solo la solución.
   - **Explicación corta**: datos, fórmula y resultado.
   - **Paso a paso**: datos → qué se pide → fórmula o procedimiento → por qué se
     usa → sustitución → operaciones → resultado con unidades.
   - **Como mis apuntes**: con tu terminología, notación y orden de pasos.
   - **Modo profesor**: como una solución modelo, con el estilo académico y el
     procedimiento de los materiales de clase.
4. Pulsa **RESOLVER**.

Qué hace:

- **Lee** el enunciado, los datos y lo que se pide. Si la foto no se entiende, lo
  dice y no gasta más.
- **Busca en tus materiales** ejercicios parecidos (Ejercicios, Problemas,
  Exámenes, Ejercicios corregidos) y la teoría del método. Si hace falta, abre el
  documento completo.
- **Indica siempre de dónde sale el método**:
  - «Método de tus apuntes: Tema 3.pdf, pág. 12», si lo ha encontrado;
  - si no, exactamente: *«No encuentro en tus materiales un procedimiento
    específico para este tipo de ejercicio. Te lo voy a resolver utilizando un
    método estándar.»*
- Copia las fórmulas de tus apuntes tal cual y **señala en «Avisos» los posibles
  errores** que vea en ellos, sin corregirlos en silencio.
- Cada resolución se guarda (con la foto) en `Asignatura/_resoluciones_IA/`. Esa
  carpeta **nunca se usa como fuente**, para no confundir una resolución de la IA
  con el método de tu profesor.

### Modos «Como mis apuntes» y «Modo profesor»

Para estos modos, la aplicación crea un **perfil de estilo** de cada asignatura.
Claude analiza una muestra de sus materiales: primero los del profesor
(ejercicios resueltos, problemas, exámenes y teoría) y después tus apuntes. De
ahí saca:

- terminología y notación, y las fórmulas tal como se escriben;
- el orden de los pasos y el nivel de explicación;
- convenciones (unidades, redondeos, signos) y procedimientos por tipo de ejercicio;
- y **si hay material suficiente**.

Se crea automáticamente la primera vez (de 0,05 a 0,15 US$ por asignatura) y
puedes verlo o actualizarlo en 📚 Mis asignaturas.

- Si hay suficiente material, la resolución lo indica: «Estilo: siguiendo los
  materiales de «Cálculo I»».
- Si no, lo dice: «No hay suficiente material de esta asignatura para reproducir
  el estilo de clase; uso un estilo estándar».
- El Modo profesor **no afirma imitar al profesor**: reproduce el estilo de los
  materiales disponibles.

Coste orientativo: entre 0,05 y 0,30 US$ por ejercicio con Opus, que se muestra
en cada resolución. La IA puede equivocarse, sobre todo en cálculos largos:
revisa las operaciones. Es para estudiar y practicar, no para usar en
evaluaciones.

## Tareas, entregas y avisos

Al sincronizar se leen del Aula Virtual:

- **Tareas con fecha**: las mismas de la «Línea de tiempo» de tu Área personal,
  leídas con la función oficial del calendario de Moodle. En 📅 Tareas verás:
  - las **vencidas o pendientes**, las **próximas** agrupadas por día y un
    **calendario del mes**, cada una con un botón para abrirla en el Aula Virtual;
  - una casilla **«Hecha»** para organizarte (es una marca local: no entrega nada).
- **Avisos de los profesores**: se leen del foro de avisos de cada asignatura y
  se marcan como **nuevos** los que no habías visto.
- **Exportar al calendario**: «Descargar calendario (.ics)» genera un archivo con
  todas las entregas (con aviso un día antes) para importarlo en Google Calendar
  (Configuración → Importar y exportar) u Outlook.
- En 🏠 Inicio aparecen las próximas entregas y los avisos recientes. Con la sesión
  ya iniciada, «Actualizar tareas» las refresca sin sincronizar los archivos.

Limitaciones:

- Solo aparecen las tareas que Moodle pone en tu calendario. Una fecha escrita
  solo dentro de un PDF no se detecta.
- Los avisos se leen de la página del foro. Si con tu cuenta no aparecen, el
  diagnóstico lo mostrará y se ajustará.

## Búsqueda en tus documentos

En 🔎 **Buscar** escribes lo que buscas y aparecen los documentos con el
**fragmento** donde sale y la **página** o diapositiva. Al pulsar, el PDF se abre
en esa página. Hay filtros por asignatura y tipo.

- **Por palabras**: ignora tildes y mayúsculas («hormigon» encuentra «hormigón»).
- **Por significado**: «velocidad instantánea» encuentra «derivada» aunque no
  compartan palabras. Usa un modelo multilingüe que se ejecuta **en tu PC**,
  gratis y sin enviar nada fuera. La primera vez se descarga (unos 220 MB), así
  que la primera indexación tarda algo más.
- **Qué se indexa**: el texto de PDF, Word, PowerPoint (con notas del orador) y
  archivos de texto, tanto del Aula Virtual como tuyos. Se actualiza solo al
  sincronizar, al subir apuntes y al organizar la bandeja. Solo se procesa lo
  nuevo o cambiado. También puedes pulsar «Actualizar índice».
- **Fotos y PDF escaneados** no tienen texto:
  - Sin IA, se encuentran por su título y etiquetas.
  - Con la IA activada, «👁 Leer fotos con IA» hace que Claude los transcriba
    una sola vez (letra a mano y fórmulas incluidas, céntimos por foto) y su
    texto pasa al buscador.
  - En Configuración puedes hacer que las fotos nuevas se lean automáticamente.
- El **asistente** usa este buscador: antes de responder busca en tus documentos
  y cita el documento y la página.

Si la búsqueda por significado no está disponible (por ejemplo, sin internet la
primera vez), la búsqueda por palabras sigue funcionando y la pantalla te dice
por qué.

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
| Resolver ejercicio (y perfil de estilo de la asignatura) | Sí |
| Tareas, calendario y avisos | No |

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

Si algo no funciona con tu cuenta, ejecuta el diagnóstico. No descarga nada:
comprueba el inicio de sesión, las asignaturas, cómo se lee un curso, el foro de
avisos y las tareas con fecha.

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
  search.py      búsqueda: extracción de texto, índice por palabras (FTS5), significado, OCR
  solver.py      resolver ejercicio: leer la foto, buscar el método, resolver, historial
  style.py       perfil de estilo de cada asignatura (modos «Como mis apuntes» y «Modo profesor»)
  tasks.py       tareas: agrupación y exportación a calendario (.ics)
  config.py, apikey.py, fsutils.py, cli.py
tests/           pruebas con un Moodle simulado y un Claude simulado (sin coste)
```

Pruebas: `pip install -r requirements-dev.txt` y luego `python -m pytest`.
