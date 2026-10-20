# -*- coding: utf-8 -*-
"""Publica la página "Eventos" (carreras, HYROX, CrossFit, triatlones, torneos) desde data/eventos/eventos.csv.

Columnas: id,nombre,tipo,fecha_inicio,fecha_fin,ciudad,estado,sede,distancias,precio_desde,liga,fuente,actualizado_el[,organizador]
- Solo muestra eventos de hoy en adelante, agrupados por mes. Agrega datos estructurados (schema.org SportsEvent).
- La tarea programada de Claude mantiene el CSV; este script solo lo publica.
"""
import datetime as dt
import html
import json
import os

import pandas as pd
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGEN = "https://gyms52.com/wp-content/uploads/2026/10/gyms52-portada.jpg"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_txt(i, f):
    a = dt.date.fromisoformat(i)
    if not f or f == i:
        return f"{a.day} de {MESES[a.month - 1]}"
    b = dt.date.fromisoformat(f)
    if a.month == b.month:
        return f"{a.day} al {b.day} de {MESES[a.month - 1]}"
    return f"{a.day} de {MESES[a.month - 1]} al {b.day} de {MESES[b.month - 1]}"


def main():
    ruta = os.path.join(RAIZ, "data", "eventos", "eventos.csv")
    ev = pd.read_csv(ruta, dtype=str).fillna("")
    hoy = dt.date.today().isoformat()
    ev = ev[(ev.fecha_inicio.str.match(r"^\d{4}-\d{2}-\d{2}$")) & ((ev.fecha_fin.where(ev.fecha_fin != "", ev.fecha_inicio)) >= hoy)]
    ev = ev.sort_values(["fecha_inicio", "nombre"])
    partes = ["<!-- wp:html -->",
              f"<p>Carreras, HYROX, competencias de CrossFit, triatlones y torneos en México. {len(ev)} eventos próximos, "
              "con fecha, sede y liga de registro. Confirma siempre con el organizador antes de inscribirte.</p>"]
    schema = []
    mes_actual = ""
    for _, e in ev.iterrows():
        d = dt.date.fromisoformat(e.fecha_inicio)
        mes = f"{MESES[d.month - 1].capitalize()} {d.year}"
        if mes != mes_actual:
            if mes_actual:
                partes.append("</ul>")
            partes.append(f"<h2>{mes}</h2><ul class=\"g52-guia g52-eventos\">")
            mes_actual = mes
        lugar = ", ".join(x for x in (e.sede, e.ciudad, e.estado) if x)
        detalle = " · ".join(x for x in (e.tipo, e.distancias, f"desde ${int(e.precio_desde):,}" if e.precio_desde.isdigit() else "") if x)
        nombre = html.escape(e.nombre)
        enlace = f'<a href="{html.escape(e.liga)}" target="_blank" rel="noopener nofollow"><strong>{nombre}</strong></a>' if e.liga.startswith("http") else f"<strong>{nombre}</strong>"
        partes.append(f"<li>{enlace}<br>{fecha_txt(e.fecha_inicio, e.fecha_fin)} · {html.escape(lugar)}"
                      + (f"<br><small>{html.escape(detalle)}</small>" if detalle else "") + "</li>")
        item = {"@type": "SportsEvent", "name": e.nombre, "startDate": e.fecha_inicio, "endDate": e.fecha_fin or e.fecha_inicio,
                "eventStatus": "https://schema.org/EventScheduled", "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
                "location": {"@type": "Place", "name": e.sede or e.ciudad,
                             "address": {"@type": "PostalAddress", "addressLocality": e.ciudad, "addressRegion": e.estado, "addressCountry": "MX"}}}
        desc = f"{e.tipo} en {e.ciudad}" + (f", {e.sede}" if e.sede else "") + f", {fecha_txt(e.fecha_inicio, e.fecha_fin)}."
        if e.distancias:
            desc += f" {e.distancias}."
        item["description"] = desc
        item["image"] = [IMAGEN]
        if e.liga.startswith("http"):
            item["url"] = e.liga
            oferta = {"@type": "Offer", "url": e.liga, "priceCurrency": "MXN"}
            if e.precio_desde.isdigit():
                oferta["price"] = e.precio_desde
            item["offers"] = oferta
        org = e.get("organizador", "")
        if org:
            item["organizer"] = {"@type": "Organization", "name": org, **({"url": e.liga} if e.liga.startswith("http") else {})}
        schema.append(item)
    if mes_actual:
        partes.append("</ul>")
    partes.append(f"<p><small>Actualizada el {dt.date.today().day} de {MESES[dt.date.today().month - 1]} de {dt.date.today().year}. "
                  "¿Organizas un evento? Escríbenos desde Reportar un error.</small></p>")
    partes.append('<script type="application/ld+json">' + json.dumps({"@context": "https://schema.org", "@graph": schema}, ensure_ascii=False) + "</script>")
    partes.append("<!-- /wp:html -->")

    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    reg = os.path.join(RAIZ, "data", "eventos", "pagina.json")
    pid = json.load(open(reg)).get("page_id") if os.path.exists(reg) else None
    datos = {"title": "Eventos", "slug": "eventos", "status": "publish", "content": "\n".join(partes),
             "excerpt": "Carreras, HYROX, CrossFit, triatlones y torneos en México, con fecha, sede y registro."}
    r = s.post(f"{url}/wp-json/wp/v2/pages" + (f"/{pid}" if pid else ""), json=datos, timeout=90)
    r.raise_for_status()
    json.dump({"page_id": r.json()["id"]}, open(reg, "w"))
    print(f"Eventos publicados: {len(ev)}")


if __name__ == "__main__":
    main()
