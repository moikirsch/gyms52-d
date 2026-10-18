# Gyms +52 · datos

Base maestra y procesos del directorio [gyms52.com](https://gyms52.com). Todo corre en GitHub Actions; nada depende de una computadora prendida.

## Cómo funciona

1. **DENUE** (`scripts/denue.py`): descarga del INEGI los centros de acondicionamiento físico (SCIAN 713943 privados y 713944 públicos) y los marca por metrópoli. Se actualiza solo el 15 de enero y el 15 de julio.
2. **Google Places** (`scripts/places.py`): busca 13 tipos de lugar en cada municipio de las metrópolis pedidas. Usa solo campos de nivel Pro para cuidar el costo y respeta un tope de peticiones por corrida.
3. **Unir** (`scripts/unir.py`): cruza Google con DENUE (distancia y nombre), clasifica tipo de lugar y disciplinas, y escribe `data/base.csv`. Lo de DENUE sin pareja queda en `data/denue/sin_pareja.csv` como candidato, sin publicarse.
4. **Publicar** (`scripts/publicar.py`): sube a WordPress los lugares sin `wp_id` y guarda el id de vuelta en la base. Con `--actualizar` reenvía solo las fichas marcadas `pendiente_sync=1` (con `--todas`, todas).
5. **Enriquecer**: `scripts/detalles.py` trae de Google sitio web, teléfono, horario y calificación; `scripts/redes.py` lee cada sitio web y saca Instagram, Facebook, TikTok, WhatsApp y correo. Lo que cambia queda marcado para subirse.

6. **Fuentes gratis**: `scripts/osm.py` baja de OpenStreetMap gimnasios, estudios, dojos, academias de baile y tiendas (sin llave ni cuota). `unir.py` usa OSM para completar contacto, redes y horario, y agrega como fichas nuevas lo que Google no tiene. También agrega lo de DENUE sin pareja en las metrópolis de lanzamiento, salvo nombres genéricos ("GIMNASIO", "ZUMBA SIN NOMBRE"). Si después Google encuentra un lugar que venía de OSM o DENUE, se queda con la misma ficha en WordPress.
7. **Claude**: una tarea programada busca en la web redes, contacto, horario y lo que dicen las reseñas (resumen propio "Lo mejor" / "A considerar", instalaciones, servicios, pases y precios con fuente y fecha) y deja un CSV en `data/claude/`. `aplicar_claude.py` lo integra (solo llena campos vacíos) y se sube a WordPress.

## Cómo pedir una corrida

Edita y sube uno de estos archivos; el cambio dispara el proceso:

- `solicitudes/places.json` → `{"metros": "1,2", "max": 600}`
- `solicitudes/publicar.json` → `{"metros": "1", "max": 300, "estado": "publish"}`
- `solicitudes/osm.json` → `{"metros": ""}` (vacío = las de lanzamiento; también corre solo cada lunes)
- `solicitudes/enriquecer.json` → `{"metros": "1", "max": 2000, "todas": false}`

También se pueden lanzar a mano desde la pestaña Actions.

## Corrida diaria

`diario.yml` corre todos los días a las 7:17 am (centro de México): busca en las metrópolis de lanzamiento que tengan búsquedas pendientes, une, publica lo nuevo y lo enriquece. Se ajusta en `config/diario.json` (`metros_lanzamiento`, `max_google`). Si Google agota su cuota del día, la búsqueda se detiene y retoma al día siguiente donde se quedó.

## Secretos del repositorio

`GOOGLE_PLACES_KEY`, `WP_USER`, `WP_APP_PASSWORD`. Nunca van en archivos.

## Resultados

Cada corrida deja su resumen en `data/corridas/`.
