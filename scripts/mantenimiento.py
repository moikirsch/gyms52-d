# -*- coding: utf-8 -*-
"""Tareas puntuales de mantenimiento en gyms52.com, manejadas por solicitudes/mantenimiento.json.

  {"info": true}
      guarda en data/mantenimiento/info.json los plugins y ajustes del sitio.
  {"borrador_paginas": [123, 456]}
      pasa páginas a borrador: dejan de verse y se pueden volver a publicar.
  {"borrador_lugares": [wp_id, ...]}
      pasa fichas a borrador.
  {"plugins_activar": ["ninja-forms/ninja-forms"]}
      activa plugins instalados.
  {"formulario_reportar": "hola@gyms52.com"}
      instala Contact Form 7, crea o actualiza el formulario "Reportar un error" con ese destinatario
      y lo pone en la página reportar-un-error (id 39) en lugar del formulario viejo.
Cada corrida deja su bitácora en data/mantenimiento/<fecha>.json.
Necesita WP_USER y WP_APP_PASSWORD.
"""
import datetime as dt
import re
import json
import os
import time

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(RAIZ, "data", "mantenimiento")


def main():
    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    s.headers["User-Agent"] = "gyms52-pipeline/1.0"
    sol = json.load(open(os.path.join(RAIZ, "solicitudes", "mantenimiento.json")))
    os.makedirs(DIR, exist_ok=True)
    marca = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    log = {"solicitud": sol, "resultados": []}

    def anota(**k):
        log["resultados"].append(k)
        print(k)

    if sol.get("info"):
        info = {}
        r = s.get(f"{url}/wp-json/wp/v2/plugins", params={"context": "edit"}, timeout=60)
        info["plugins"] = [{"plugin": p["plugin"], "nombre": p["name"], "estado": p["status"], "version": p["version"]}
                           for p in r.json()] if r.status_code == 200 else f"HTTP {r.status_code} {r.text[:200]}"
        r = s.get(f"{url}/wp-json/wp/v2/settings", timeout=60)
        info["ajustes"] = r.json() if r.status_code == 200 else f"HTTP {r.status_code}"
        json.dump(info, open(os.path.join(DIR, "info.json"), "w"), ensure_ascii=False, indent=1)
        anota(accion="info", plugins=len(info["plugins"]) if isinstance(info["plugins"], list) else info["plugins"])

    for pl in sol.get("plugins_activar", []):
        r = s.post(f"{url}/wp-json/wp/v2/plugins/{pl}", json={"status": "active"}, timeout=90)
        anota(accion="activar", plugin=pl, http=r.status_code, detalle=r.text[:200] if r.status_code >= 300 else r.json().get("status"))

    for pid in sol.get("borrador_paginas", []):
        r = s.post(f"{url}/wp-json/wp/v2/pages/{pid}", json={"status": "draft"}, timeout=60)
        anota(accion="borrador", id=pid, http=r.status_code, estado=(r.json().get("status") if r.status_code == 200 else r.text[:150]))
        time.sleep(0.3)

    for wid in sol.get("borrador_lugares", []):
        r = s.post(f"{url}/wp-json/geodir/v2/lugares/{wid}", json={"status": "draft"}, timeout=60)
        anota(accion="borrador_lugar", id=wid, http=r.status_code, estado=(r.json().get("status") if r.status_code == 200 else r.text[:150]))
        time.sleep(0.3)

    destino = sol.get("formulario_reportar")
    if destino:
        formulario_reportar(s, url, destino, anota)

    json.dump(log, open(os.path.join(DIR, f"{marca}.json"), "w"), ensure_ascii=False, indent=1)


FORM_REPORTAR = """<label>Tu nombre
    [text* tu-nombre autocomplete:name]</label>

<label>Tu correo
    [email* tu-correo autocomplete:email]</label>

<label>Lugar y ciudad
    [text* lugar placeholder "Ej. Smart Fit Pabellón Iztapalapa, CDMX"]</label>

<label>Qué hay que corregir
    [textarea* mensaje placeholder "Ej. ya cerró, cambió de teléfono, el horario es otro o falta un lugar"]</label>

[submit "Enviar reporte"]"""


def formulario_reportar(s, url, destino, anota):
    r = s.get(f"{url}/wp-json/wp/v2/plugins/contact-form-7/wp-contact-form-7", params={"context": "edit"}, timeout=60)
    if r.status_code == 404:
        r = s.post(f"{url}/wp-json/wp/v2/plugins", json={"slug": "contact-form-7", "status": "active"}, timeout=180)
        anota(accion="instalar_cf7", http=r.status_code, detalle=r.text[:200] if r.status_code >= 300 else r.json().get("status"))
    elif r.status_code == 200 and r.json().get("status") != "active":
        r = s.post(f"{url}/wp-json/wp/v2/plugins/contact-form-7/wp-contact-form-7", json={"status": "active"}, timeout=90)
        anota(accion="activar_cf7", http=r.status_code)
    else:
        anota(accion="cf7", http=r.status_code, estado=r.json().get("status") if r.status_code == 200 else r.text[:150])
    datos = {
        "title": "Reportar un error",
        "locale": "es_MX",
        "form": FORM_REPORTAR,
        "mail": {
            "active": True,
            "recipient": destino,
            "sender": "Gyms +52 <wordpress@gyms52.com>",
            "subject": "Reporte de error: [lugar]",
            "body": "Lugar y ciudad: [lugar]\nQué hay que corregir:\n[mensaje]\n\nDe: [tu-nombre] <[tu-correo]>\n\nEnviado desde gyms52.com/reportar-un-error/",
            "additional_headers": "Reply-To: [tu-correo]",
            "attachments": "", "use_html": False, "exclude_blank": False,
        },
    }
    api = f"{url}/wp-json/contact-form-7/v1/contact-forms"
    r = s.get(api, params={"per_page": 50}, timeout=60)
    todas = r.json() if r.status_code == 200 else []
    # el suyo, o el de ejemplo que crea el plugin al instalarse
    previo = [f for f in todas if f.get("title") == "Reportar un error"] or \
             [f for f in todas if f.get("title") in ("Contact form 1", "Formulario de contacto 1")]
    r = s.post(api + (f"/{previo[0]['id']}" if previo else ""), json=datos, timeout=60)
    anota(accion="guardar_formulario", http=r.status_code, respuesta=r.text[:300])
    if r.status_code not in (200, 201):
        return
    guardado = r.json()
    fid = guardado.get("id")
    mail = (guardado.get("properties") or {}).get("mail") or {}
    anota(accion="formulario", id=fid, destinatario=mail.get("recipient"), asunto=mail.get("subject"))
    if not fid:
        return
    r = s.get(f"{url}/wp-json/wp/v2/pages/39", params={"context": "edit"}, timeout=60)
    crudo = r.json()["content"]["raw"]
    open(os.path.join(DIR, f"reportar-un-error-{dt.date.today()}.html"), "w").write(crudo)
    codigo = f'[contact-form-7 id="{fid}" title="Reportar un error"]'
    bloque = f'<div class="g52-form">{codigo}</div>'
    nuevo = re.sub(r'\[contact-form-7[^\]]*\]', codigo, crudo)
    if codigo not in nuevo and "<p><noscript" in nuevo:
        i = nuevo.index("<p><noscript")
        j = nuevo.index("</p>", nuevo.index("</script>", i)) + len("</p>")
        nuevo = nuevo[:i] + bloque + nuevo[j:]
    if codigo not in nuevo:
        anota(accion="pagina_reportar", detalle="no encontré dónde poner el formulario")
        return
    r = s.post(f"{url}/wp-json/wp/v2/pages/39", json={"content": nuevo}, timeout=60)
    anota(accion="pagina_reportar", http=r.status_code, con_formulario=codigo in nuevo)


if __name__ == "__main__":
    main()
