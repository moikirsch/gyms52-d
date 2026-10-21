# Gyms +52: traspaso de sesión

> El repo es público desde el 21 oct 2026 (minutos gratis de GitHub Actions). Nunca subas llaves, contraseñas ni datos personales: todo eso va en los secretos de GitHub.

Actualizado: 19 oct 2026, 10:00 am (hora CDMX). Desde hoy el proyecto se lleva desde la sesión session_01G1sJGBbq7a9nYj5Fhce5Dz. Úsalo para retomar el proyecto en una sesión nueva sin repetir trabajo ni romper lo que ya corre.

## 1. Qué es y cómo está hoy

- **Sitio:** https://gyms52.com ("Gyms +52"), directorio nacional de gimnasios, estudios, boxes, deportivos, tiendas y eventos de fitness en México. Es hermano de padel52.com y usa el mismo stack.
- **Números al 19 oct, 9 am:** 25,629 lugares en la base, 25,548 publicados y 81 pendientes de publicar, en las 30 metrópolis de lanzamiento.
- **Cobertura de datos (fichas publicadas):**

| Dato | Fichas |
|---|---|
| Teléfono | 11,137 |
| Pases (TotalPass, Fitpass, etc.) | 8,391 |
| Horario | 8,051 |
| Foto propia | 7,429 |
| Sitio web | 7,028 |
| Instalaciones | 5,529 |
| Precio oficial | 479 |
| Facebook | 412 |
| Instagram | 380 |
| Afiliación CrossFit o HYROX | 298 |
| Con reseñas revisadas por Claude | 240 |
| Con resumen "Lo mejor" | 6 |

- **Páginas especiales:**
  - https://gyms52.com/eventos: 23 eventos, de oct 2026 a abr 2027.
  - https://gyms52.com/guias: 437 guías por ciudad y disciplina.

## 2. Accesos (las credenciales nunca van al chat)

- **WordPress (Pressable):** wp-admin de gyms52.com. El Chrome de Moi (Claude in Chrome) tiene la sesión de wp-admin iniciada. Para escribir por REST desde ese navegador:
  1. Saca el nonce con `fetch('/wp-admin/admin-ajax.php?action=rest-nonce')`.
  2. Manda el header `X-WP-Nonce`.
  - Cuidado: Claude in Chrome bloquea respuestas con pares `clave=valor` o URLs con query ("BLOCKED: Cookie/query string data"). Reemplaza `=` antes de devolver texto.
  - Abre siempre una pestaña propia: Moi usa ese Chrome al mismo tiempo.
- **Repo de datos:** GitHub privado `moikirsch/gyms52-d`.
  - El clon de trabajo estaba en `/home/claude/gyms52-d`. En una sesión nueva, clónalo de nuevo; si no hay acceso, usa `add_repo` con owner `moikirsch`, repo `gyms52-d`, access `push`.
  - Cada commit lleva al final las líneas de atribución de la sesión: `Co-Authored-By` y `Claude-Session`.
- **Secretos de GitHub Actions:** `GOOGLE_PLACES_KEY`, `WP_USER`, `WP_APP_PASSWORD`. Ya están configurados. No pedirlos ni moverlos.
- **Google Cloud (Places API New):**
  - Las cuotas diarias son bajas. Moi pidió subir "SearchTextRequest per day". Falta pedir también "GetPlaceRequest per day" (liga: https://console.cloud.google.com/apis/api/places.googleapis.com/quotas).
- **Site Kit de Google:** Moi lo conectó el 18 oct. Pendiente de su lado: dar de alta `sitemap_index.xml` en Search Console.
- **gh CLI:** no está autenticado. No hay forma de ver el historial de GitHub Actions desde la sesión: solo se ve lo que cada corrida guarda en el repo. Si un proceso no deja commit, pídele a Moi que revise github.com/moikirsch/gyms52-d/actions o los correos de falla de GitHub.

## 3. Arquitectura (todo en la nube)

**Stack:**
- WordPress con GeoDirectory gratis y el tema Directory (BlockStrap) en Pressable.
- Plugins:
  - GeoDirectory, UsersWP, BlockStrap Page Builder Blocks.
  - Yoast SEO, Google Site Kit.
  - Say What (traducciones puntuales: "options", "Showing…", "Home", "Closed", etc.).
  - Akismet y Jetpack Protect.
- Mapas con OpenStreetMap.
- La CPT de lugares se publica en `geodir/v2/lugares`.

**Flujo:** el repo `gyms52-d` es la base maestra (`data/base.csv`). Los scripts de `scripts/` corren en GitHub Actions y publican por la REST de GeoDirectory con una contraseña de aplicación.

| Script | Qué hace |
|---|---|
| `denue.py` | DENUE del INEGI (SCIAN 713943 y 713944), dos veces al año |
| `places.py` | Google Text Search por municipio; respeta la cuota y se reanuda solo |
| `osm.py` | OpenStreetMap (Overpass) por metrópoli |
| `fuentes.py` | Fuentes oficiales: Smart Fit, Anytime, Sports World, Sport City, CrossFit, HYROX, TotalPass y Fitpass. Escribe `data/fuentes/*.jsonl` y `resumen.json`. **Wellhub queda fuera** porque sus términos prohíben extraer datos; ClassPass, Planet Fitness y Zumba bloquean scripts |
| `unir.py` | Junta Google + OSM + fuentes + DENUE en `data/base.csv`, quita duplicados, clasifica, arma la descripción y conserva el `wp_id` aunque cambie la fuente. Canchas y campos (fútbol, frontón, pádel) quedan fuera. Lo publicado que sale de la base va a `data/retirar.csv` y pasa a borrador |
| `publicar.py` | Publica las fichas nuevas. `--actualizar` sube las que tienen `pendiente_sync=1` (`--todas` las sube todas). `--retirar` pasa a borrador las de `retirar.csv`. Instalaciones, pases y afiliaciones van como lista JSON (WordPress parte el texto por espacios). La foto va como `post_images: "url|0|titulo|"` y GeoDirectory la descarga |
| `detalles.py` | Google Place Details: sitio, teléfono, horario y calificación. La cuota da para ~110 al día |
| `redes.py` | Lee el sitio web de cada lugar y saca Instagram, Facebook, TikTok, WhatsApp y correo. Las cuentas tienen que parecerse al nombre o al dominio del lugar |
| `fotos.py` | Foto del sitio web propio, con filtro de calidad. Las cadenas quedan fuera porque sus portadas son promociones |
| `aplicar_claude.py` | Integra `data/claude/*.csv` (lo que encuentra la tarea de Claude). Solo llena campos vacíos; las opiniones se reemplazan. Una nota "cerrado: …" manda la ficha a borrador y la registra en `data/cerrados.csv` para que no vuelva |
| `guias.py` | Páginas `/guias/<disciplina>-<ciudad>/` y el índice `/guias/`. Los ids quedan en `data/guias.csv` |
| `eventos.py` | Página `/eventos/` desde `data/eventos/eventos.csv`, con datos estructurados SportsEvent |
| `plantilla.py` | La creó otra sesión: lee y sube plantillas del tema desde Actions, con respaldos en `data/plantillas` |

**Workflows** (`.github/workflows/`):

| Workflow | Disparador | Fila |
|---|---|---|
| `diario.yml` | 7:17 am diario: places → unir → publicar → detalles → redes → fotos → actualizar → retirar | `datos` |
| `osm.yml` | Lunes 4:41 am o `solicitudes/osm.json` | `datos` |
| `fuentes.yml` | Miércoles 4:41 am o `solicitudes/fuentes.json` (`{"max_totalpass": 3000}`; 0 = todas) | `datos` |
| `enriquecer.yml` | `solicitudes/enriquecer.json` | `datos` |
| `claude.yml` | Push de `data/claude/*.csv` o `solicitudes/claude.json`. Aplica, sube y guarda con reintentos | `claude` |
| `guias.yml` | Domingos 5:33 am o `solicitudes/guias.json` | `guias` |
| `eventos.yml` | Push de `data/eventos/eventos.csv` o `solicitudes/eventos.json` | `eventos` |
| `places.yml`, `publicar.yml`, `denue.yml`, `plantilla.yml` | Manuales o programados | — |

- **Ojo con las filas de GitHub:** cada fila solo guarda **un** proceso en espera. Si entra otro, reemplaza al que esperaba, y el reemplazado se cancela sin avisar. Por eso Claude, eventos y guías tienen fila propia. No dispares 2 procesos de la fila `datos` seguidos: espera a que termine uno.
- **Cómo pedir una corrida:** edita y sube el JSON correspondiente de `solicitudes/` (ver el README del repo).

**Reportes y bitácoras (en el repo):**
- `data/corridas/ultima-*.log`: el último log de cada paso (places, unir, publicar, detalles, redes, fotos, osm, fuentes, claude, guias, eventos).
- `data/corridas/AAAAMMDD-HHMM-*.json`: el resumen de cada corrida.
- `data/fuentes/resumen.json`: el estado de cada fuente oficial.
- `data/retirar.csv`: lo que pasó a borrador. `data/cerrados.csv`: lo cerrado.
- `data/claude/aplicados.txt`: los CSV de Claude ya integrados.
- `README.md`: documentación del flujo completo.

## 4. Tareas programadas de Claude (en la nube)

| Tarea | Id | Horario |
|---|---|---|
| Gyms52 - Enriquecer fichas con búsqueda web | `trig_01SFyRzvrvhaVJfUNdyKewbJ` | Cada hora al minuto 23 (CDMX) |
| Gyms52 - Eventos deportivos | `trig_014RyozWcHeYEvgwGg8LYv9K` | Lunes 6:41 am |

- **Enriquecer:**
  - Revisa 30 fichas por vuelta: contacto, redes, horario y reseñas (resumen propio "Lo mejor" y "A considerar"), instalaciones, servicios, pases y precios con fuente y fecha. También detecta cierres.
  - Escribe `data/claude/<fecha-hora UTC>.csv` y hace push; eso dispara `claude.yml`.
  - Prioridad: lugares con más reseñas de Google, luego cadenas y pases, luego el resto.
  - Ambas tareas tienen aprobación automática y no mandan avisos.
- **Eventos:** actualiza `data/eventos/eventos.csv` (6 meses hacia adelante; borra lo pasado). El push publica la página.
- **Otras tareas de la cuenta (no tocar):** las de QueComer, Padel52 y Meta Ads de NU Espacios.

## 5. Diseño y marca

- **Marca:**
  - Colores: Azul Eléctrico `#2B8CFF`, Negro `#090B10`, Grafito `#141821`, Malla `#262C38`, Piedra `#545C6B`, Niebla `#9BA3B2`, Cristal `#EEF2F8`. Nunca texto azul sobre blanco.
  - Tipografía: Archivo (títulos; logo en Expanded Black Italic) y Poppins (texto).
- **Documentos y artifacts:**
  - Manual de marca: https://claude.ai/artifact/1A4WZs1W5qZ3k9rpQpuGYt
  - Taxonomía y plan: https://claude.ai/code/artifact/cc304996-0755-4711-9050-6a5dec4584a3
- **Medios en WordPress:**
  - Portada: id 31.
  - Imagen genérica de ficha: id 1610 (`gyms52-sin-foto`).
  - Pin del mapa: id 9331 (`gyms52-pin-30.png`, azul sólido con borde, 30×39 px). Es el marcador por defecto de GeoDirectory y el ícono de las 83 categorías.
  - Las categorías tienen además un ícono de Font Awesome 6 en azul.
- **CSS global:** en Global Styles id 14 (`styles.css`). El bloque de móvil va entre `/* ===== G52 MOVIL INICIO ===== */` y `... FIN`. Abajo hay reglas de guías, categorías en escritorio, ocultar la imagen genérica (`#post_images` con `sin-foto`) y `.geodir-post-rating-value-0`.
- **Plantillas modificadas:**
  - `gd-single`: el cuadro de datos usa los campos propios: tipo de lugar, teléfono, correo, sitio web, Instagram, Facebook, TikTok, WhatsApp, pases, instalaciones, servicios y precios. "Ver en el mapa" y "Compartir" van en español.
  - `gd-archive-item-simple`: tarjetas con tipo y ciudad.
  - `front-page`: categorías (`max_count` 12) y "Lugares destacados".
  - `footer`: aviso de cookies `#g52-cookies`, copia del de padel52, con cookie `g52_cookies` y la liga "Configurar cookies".
  - **Otra sesión de Claude** (session_014Fd…) también modificó `gd-single` (imagen a la izquierda en escritorio, sin renglones vacíos) usando `plantilla.yml`. Lee la plantilla en vivo antes de cambiarla.
- **SEO:**
  - Yoast genera `/sitemap_index.xml`.
  - El título de la portada es "Gyms +52: gimnasios, estudios y boxes en México". Se cambia desde el editor de bloques con `wp.data.dispatch('yoast-seo/editor').updateData({title, description})` y luego `savePost`.
  - La REST no expone los meta de Yoast.
- **Revisión móvil:** Pressable muestra un "Confirm you are human" al Chromium headless. Para ver la versión móvil, inyecta un iframe de 390 px dentro de una pestaña de gyms52.com en el Chrome de Moi.

## 6. Campos propios de GeoDirectory

`tipo_lugar`, `cadena`, `telefono`, `whatsapp`, `correo`, `sitio_web`, `instagram`, `facebook`, `tiktok`, `reserva_url`, `reserva_plataforma`, `business_hours`, `mensualidad_desde`, `mensualidad_hasta`, `inscripcion`, `pase_dia`, `clase_suelta`, `prueba_gratis`, `fecha_precio`, `pases`, `totalpass_nivel`, `wellhub_plan`, `classpass_creditos`, `fitpass_plan`, `pases_fuente`*, `pases_verificado_el`*, `afiliaciones`, `afiliaciones_declaradas`, `afiliaciones_fuente`*, `abierto_24h`, `instalaciones`, `servicios`, `publico`, `marcas_equipo`, `place_id`*, `denue_id`*, `fuente`*, `ultima_verificacion`*. Los que llevan * son solo para administración.

**Valores permitidos (enum):**
- instalaciones: Alberca, Regaderas y vestidores, Lockers, Sauna o vapor, Estacionamiento, Área infantil, Cafetería, Tienda, Zona de peso libre, Zona funcional, Aire acondicionado.
- servicios: Entrenador personal, Nutriólogo, Evaluación corporal, Fisioterapia, App propia, Clases en línea.
- pases: TotalPass, Wellhub, ClassPass, Fitpass.
- afiliaciones: CrossFit, HYROX, Les Mills, Zumba, Jazzercise, Yoga Alliance, Pilates certificado, IBJJF, Federación mexicana.
- publico: Solo mujeres, Adultos mayores, Niños, Accesible en silla de ruedas.

**Mañas de la REST:**
- Un número no se puede dejar vacío por REST (queda en 0). Para vaciarlo, manda el formulario clásico `post.php` (FormData de `form#post`).
- Agregar un tipo de publicación (para Eventos) requiere el complemento de pago: por eso Eventos es una página.

## 7. Pendientes y problemas abiertos

1. **La corrida de fuentes del 19 oct:**
   - Publicó las 15 tandas, pero no se ve su commit final "Fuentes: publicación". Probablemente se acabó su tiempo durante `--actualizar`.
   - Lo que no alcanzó a subir sigue con `pendiente_sync=1` y debería subirse en la siguiente corrida diaria. Verifica que eso pase.
   - La corrida diaria del 19 oct (7:17) tampoco dejó commit. Revisa si quedó cancelada en la fila `datos`; si sí, vuelve a lanzarla (`solicitudes/enriquecer.json` o esperar al 20 oct). Antes de lanzar, confirma que la de fuentes ya no corre.
2. **El resumen "Lo mejor" sale muy poco** (6 de 240 fichas revisadas). Revisa los CSV de `data/claude/` para entender por qué: si la búsqueda web no encuentra reseñas, o si la regla de "menos de 3 opiniones" es demasiado estricta. Ajusta el prompt de la tarea `trig_01SFyRzvrvhaVJfUNdyKewbJ` con `update_trigger`.
3. **`claude.yml`:** lo simplifiqué el 19 oct (pasos separados y guardado con `pull --rebase -X theirs` y reintentos). Desde entonces ya aplicó todo: hay 15 CSV y 15 aplicados. Vigila que siga así.
4. **Instagram y Facebook siguen bajos.** TotalPass trae el Instagram como "sitio web"; `redes.py` los mueve en la corrida diaria. Confirma que suban después de la próxima corrida diaria.
5. **Cuotas de Google:** Moi pidió subir "SearchTextRequest per day". Falta pedir "GetPlaceRequest per day" a ~2,000.
6. **Sports World:** la fuente dice que casi todos sus clubes de CDMX abren de 6:00 a 19:00 entre semana. Es sospechoso; conviene verificarlo.
7. **Textos que siguen en inglés:** el título de archivo "Todos: Lugares". El resto ya se tradujo con Say What.
8. **Pendientes de Moi:** el correo catch-all de @gyms52.com; aprobar mandar a la papelera la página en inglés "terms-and-conditions" (id 8) y el logo duplicado (media id 16); dar de alta el sitemap en Search Console.
9. **Ideas que quedaron:** precios de más cadenas, el plan TotalPass mínimo (TP1 a TP7), Les Mills como etiqueta, coaches e instructores, abrir más metrópolis (`config/diario.json`: `metros_lanzamiento`, hoy 30).

## 7b. Cambios del 19 oct, 9:30 a 10:00 am

1. **Duplicados en WordPress (grave, ya contenido):**
   - WordPress tenía 26,405 lugares publicados contra 25,548 en la base: 857 fichas huérfanas, todas copias de las 81 pendientes (hasta 15 copias de cada una, p. ej. "Altus Fit").
   - Causa: `publicar.py` creaba la ficha, pero el `wp_id` se perdía al guardar `base.csv`. Las tandas de `fuentes.yml` seguían aunque el push fallara, y `claude.yml` hace `rebase -X theirs` y sube su `base.csv` completo, que pisa los ids nuevos.
   - Arreglo: `data/wp_ids.csv` es una bitácora (place_id, wp_id) que `publicar.py` escribe al crear cada ficha. `publicar.py` y `unir.py` recuperan de ahí los ids perdidos. Antes de crear, `publicar.py` busca una huérfana con el mismo título (`/wp/v2/search`) y la adopta. `fuentes.yml` se detiene si una tanda no se puede guardar.
   - Las 81 pendientes se van a ligar a su copia más antigua en la siguiente publicación. Las otras 776 copias (lista en `data/duplicados-2026-10-19.csv`) se mandaron a la papelera el 19 oct con el sí de Moi. Quedaron 25,629 publicados, igual que la base.
   - Ojo: la REST de GeoDirectory devuelve `id: null` en listas y en `GET /lugares/<id>`. Para ids usa `/wp-json/wp/v2/search?subtype=gd_place` o `/wp-json/geodir/v2/markers/?post_type=gd_place`.
2. **Portada:** el mapa tipo `directory` cargaba los 25,548 pines (2 MB) y congelaba el navegador. Lo quité de `front-page`. "Cerca de ti" (no filtraba por ubicación) pasó a "Recién agregados", en carrusel. El respaldo de la plantilla anterior es el patrón borrador id 28203.
3. **Menú:** `menu-wrapper` ahora tiene Lugares, Guías, Eventos y Blog. El respaldo es un patrón borrador.
4. **Clasificación:** reglas nuevas en `comun.py`. Especializados (Infantil, Adultos mayores, Prenatal y posparto, Rehabilitación, Adaptado, Entrenamiento personal) es una etiqueta secundaria: no cuenta como prueba de que el lugar es de fitness. También hay reglas nuevas para Bootcamp, EMS, Step, Remo indoor, Running club, Ninja, Vinyasa, Ashtanga, Hatha, Tai chi, Movilidad, Jazz, Danza contemporánea, Telas, Aquaeróbics, Clavados y Escalada con cuerda. Unas 330 fichas cambian en la siguiente `unir`.
5. **Limpieza:** la página en inglés "terms-and-conditions" (id 8) está en la papelera. El logo duplicado (media 16) sigue ahí: borrar medios es permanente, así que Moi lo borra a mano.
6. **"Lo mejor":** Moi pidió bajar el mínimo a 2 opiniones. Cambiar el prompt de la tarea `trig_01SFyRzvrvhaVJfUNdyKewbJ` fue bloqueado por permisos; Moi lo cambia o da permiso.
7. **"Lo mejor" (diagnóstico):** no se pierde nada. Las tareas solo encontraron reseñas suficientes en 10 de ~270 fichas revisadas con la columna nueva, y las 10 están en la base. El cuello de botella es la búsqueda web (no lee reseñas de Google). La decisión está pendiente con Moi.

8. **Corridas diarias del 19 oct:** la #2 (manual, 11:08) publicó 568 fichas nuevas y actualizó miles, pero falló al guardar (choque de rebase, versión vieja del workflow). La #3 (programada, arrancó 13:40 por retraso de GitHub) ya con el arreglo: adoptó las 81 pendientes sin duplicar, actualizó 5,000 y guardó bien. Quedan 842 con `pendiente_sync` para la siguiente.
9. **559 fichas publicadas sin fila en la base:** son lugares de Google que publicó la #2; sus datos de búsqueda se perdieron. Moi decidió dejarlas: cuando `places.py` las vuelva a encontrar, `publicar.py` las adopta por título. No mandarlas a la papelera.
10. **Tareas programadas:** el 19 oct se agregó a todas (Gyms52, QueComer y Padel52) la regla de no esperar aprobaciones: abrir con WebFetch solo ligas que salieron en una búsqueda y saltarse lo que pida permiso.

## 8. Cómo revisar el estado rápido

```bash
git clone https://github.com/moikirsch/gyms52-d && cd gyms52-d
git log -15 --format='%ar | %an | %s'
tail -3 data/corridas/ultima-*.log
python3 -c "import pandas as pd; b=pd.read_csv('data/base.csv',dtype=str).fillna(''); p=b[b.wp_id!='']; print(len(b), len(p)); [print(c,(p[c]!='').sum()) for c in ['telefono','instagram','facebook','horario','foto_url','pases','lo_mejor']]"
```

Para revisar el sitio sin sesión: `curl -s -A "Mozilla/5.0" https://gyms52.com/wp-json/geodir/v2/lugares/<id>`.

## 9. Reglas de trabajo con Moi

- Escribir en español de México, directo y corto, sin rayas largas ni las palabras vetadas de sus preferencias.
- Hacer preguntas con AskUserQuestion antes de trabajo complejo.
- Nunca inventar datos de producto, precio ni disponibilidad.
- Las credenciales nunca van al chat.
- Mandar a la papelera o borrar algo solo con su sí explícito.
- Fotos de lugares: primero de sus redes, luego de su sitio web y Google al final. Su abogado dijo que no hay riesgo, porque es publicidad a favor del lugar.
- Cada commit lleva las líneas de atribución de la sesión.
