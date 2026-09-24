# UJI Sync — Fase 1: Investigación

Fecha: 2026-09-24

## Qué se ha podido comprobar y qué no

El entorno donde se hizo esta investigación **no tiene acceso de red a
`aulavirtual.uji.es` ni a `cent.uji.es`** (el proxy los bloquea). Por eso:

- **Comprobado** (fuentes públicas y código fuente oficial de Moodle): los puntos marcados ✅.
- **Pendiente de verificar en tu equipo**, con tu sesión iniciada: los puntos marcados ⚠️.
  El prototipo de la Fase 2 empezará con un paso de diagnóstico que los confirme
  antes de descargar nada.

## 1. Tecnología del Aula Virtual

- ✅ El Aula Virtual de la UJI está basada en **Moodle** (software libre), en
  `https://aulavirtual.uji.es`.
- ✅ Tiene al menos dos métodos de acceso publicados: el inicio de sesión UJI y
  un plugin de login **eIDAS** (`/auth/eidas/login.php`).
- ⚠️ Versión exacta de Moodle y tema visual: no verificables desde aquí. Afectan
  a los selectores HTML, no a las URLs estándar de Moodle.

## 2. ¿Hay una API oficial de Moodle para el alumnado?

- ✅ Moodle tiene una API de *web services* (`/webservice/rest/server.php`) que usa
  la **app oficial Moodle Mobile** mediante un *token*.
- ✅ La UJI **admite oficialmente la app Moodle Mobile** (FAQ del Aula Virtual y
  guía del CENT), así que el servicio móvil está activado.
- ⚠️ El alumnado **no tiene una API pública documentada para herramientas propias**.
  El token está pensado para la app oficial.

Formas de conseguir un token, y por qué **no** las usaremos en la v1:

| Vía | Problema |
|---|---|
| `/login/token.php` con usuario y contraseña | Pide tu contraseña, que es justo lo que no queremos. Además, con SSO y doble factor normalmente no funciona. |
| `/admin/tool/mobile/launch.php` (flujo SSO de la app) | Devuelve el token a la URL `moodlemobile://…` de la app oficial. Usarlo desde otra herramienta sería suplantar a la app. |
| Página *Preferencias → Claves de seguridad* (`/user/managetoken.php`) | ⚠️ Puede que el alumnado no la vea o que no deje crear tokens. Queda como posible mejora si confirmas que la tienes. |

## 3. Autenticación de la UJI

- ✅ **SSO** (autenticación única) con el usuario corporativo UJI.
- ✅ **Doble factor**: código TOTP de 6 dígitos (Google Authenticator) o llave WebAuthn.
- Conclusión: **cualquier automatización del login sería frágil e inapropiada**.
  El login tiene que hacerlo una persona en un navegador real.

## 4. Método más seguro: navegador controlado con login manual

**Propuesta:** Python + **Playwright**, abriendo un Chromium **visible**.

1. La herramienta abre `https://aulavirtual.uji.es`.
2. **Tú** inicias sesión a mano (SSO y doble factor). La herramienta no ve ni guarda tu contraseña.
3. Cuando detecta que ya estás dentro, trabaja **con esa misma sesión**, igual que si
   hicieras clic tú, y solo ve lo que Moodle ya te deja ver.
4. La sesión vive en un perfil de navegador local (`~/.uji-sync/browser-profile`,
   fuera del repositorio). Puedes borrarlo cuando quieras y no contiene tu contraseña.

Endpoints que usaremos. Todos son estándar en Moodle y están comprobados en el código fuente oficial:

| Qué | Cómo | Estado |
|---|---|---|
| Lista de cursos | `lib/ajax/service.php` con `core_course_get_enrolled_courses_by_timeline_classification` (`ajax => true`, es la que usa el propio panel "Mis cursos") | ✅ existe · ⚠️ probar en UJI |
| Contenido del curso por secciones | HTML de `/course/view.php?id=N` | ✅ existe · ⚠️ selectores según tema |
| Índice de recursos del curso | `/course/resources.php?id=N` | ✅ existe |
| Descarga de archivos | URLs `/pluginfile.php/...` que aparecen en la página, descargadas con las cookies de la sesión | ✅ |
| Carpetas | `/mod/folder/view.php?id=N` (y `download_folder.php` si el profesor lo permite) | ✅ existe |
| Enlaces | `/mod/url/view.php?id=N`: se guarda la URL en un `.url`/índice, no se descarga el destino | ✅ |

Descartado: `core_course_get_contents` por AJAX. **No** tiene `ajax => true`
(solo se puede usar con el token de la app), así que por sesión web no está disponible.

## 5. Límites y cosas que no son posibles o no se harán

- **No** se automatiza el login, el doble factor ni ningún CAPTCHA.
- **No** se guardan credenciales.
- Solo se descarga lo que Moodle te sirve con tu sesión. Si un recurso está
  oculto, restringido o no tiene permiso de descarga, se registra como
  "no disponible" y no se intenta sortear.
- Los vídeos incrustados (Kaltura, YouTube, etc.) y el contenido dentro de
  actividades como H5P, SCORM o Cuestionarios **no** se descargan en la v1.
- Ritmo prudente: peticiones secuenciales con una pausa pequeña, para no cargar el servidor.
- ⚠️ Revisa la normativa de uso del Aula Virtual. Descargar los materiales a los que
  tienes acceso para uso personal es lo mismo que hace la app oficial ("descargar
  contenido para verlo sin conexión"), pero **no redistribuyas** esos materiales.

## 6. Duplicados y registro (diseño para la Fase 2)

- Registro local en **SQLite** (`UJI/.uji-sync.db`) con: curso, sección, id del
  módulo, URL, ruta local, tamaño, `Last-Modified`/`ETag`, **SHA-256** y fecha.
- Un archivo se considera **sin cambios** si coinciden la URL y el hash o las
  cabeceras. Si cambia, se guarda la versión nueva y la antigua se conserva con sufijo.
- SQLite se usa también en la Fase 4 (novedades, buscador, IA) sin cambiar de tecnología.

## 7. Comparativa de enfoques

| Enfoque | Seguridad | Sencillez | Robustez | Veredicto |
|---|---|---|---|---|
| Playwright con login manual y sesión web | ✅ sin contraseña | ✅ | Media: depende del HTML, se mitiga con URLs estándar | **Elegido** |
| Token de la API móvil | ⚠️ suplanta a la app o pide la contraseña | Media | Alta | Descartado para la v1 |
| Copiar cookies del navegador a mano | ⚠️ manejo manual de la cookie de sesión | Baja | Baja | Descartado |
| Extensión de navegador | ✅ | Baja: empaquetado, permisos | Media | Posible más adelante |

## 8. Estructura propuesta del proyecto (Fase 2)

```
uji_sync/
  browser.py     # abrir Chromium, esperar login manual
  moodle.py      # cursos (AJAX), secciones y recursos (HTML)
  downloader.py  # descargas con la sesión, nombres seguros
  registry.py    # SQLite: registro y duplicados
  ui.py          # interfaz sencilla (checkboxes + "Sincronizar Aula Virtual")
  cli.py
```

Salida: `UJI/<Asignatura>/<Sección>/<archivo>`.

## Fuentes

- FAQ Aula Virtual (Moodle Mobile): https://aulavirtual.uji.es/mod/glossary/showentry.php?eid=1427561822
- CENT, Aula Virtual en el móvil: https://cent.uji.es/pub/aula-virtual-mobil/
- UJI, autenticación: https://www.uji.es/cau/manuals/manuals/autenticacio/
- UJI, doble factor: https://universitatjaumei.atlassian.net/wiki/spaces/MANUJI/pages/5246781915/Autenticaci+amb+doble+factor
- Login eIDAS: https://aulavirtual.uji.es/auth/eidas/login.php
- Código fuente de Moodle (`lib/db/services.php`, `admin/tool/mobile/launch.php`, `course/resources.php`): https://github.com/moodle/moodle/tree/MOODLE_405_STABLE
