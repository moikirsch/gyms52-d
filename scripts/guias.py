# -*- coding: utf-8 -*-
"""Arma páginas de guía por metrópoli y disciplina ("Pilates mat en Monterrey") con los datos de las fichas.

Uso: python guias.py [--min 6] [--tope 60] [--simular]
- Una página por metrópoli y disciplina con al menos --min lugares publicados (más "Gimnasios en <ciudad>").
- Ordena por qué tan completa está cada ficha (opiniones, foto, horario, redes, contacto) y muestra hasta --tope.
- Página madre "Guías" con el índice. Las páginas se actualizan en su lugar (data/guias.csv guarda sus ids).
"""
import argparse
import datetime as dt
import html
import os
import time

import pandas as pd
import requests

from comun import slug

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOMBRE_METRO = {"Valle de México (CDMX)": "Ciudad de México", "Zapopan": "Guadalajara", "Ecatepec de Morelos": "Ecatepec"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
PLURAL = {"Gimnasio": "gimnasios", "Estudio": "estudios", "Box": "boxes", "Gimnasio de combate": "gimnasios de combate",
          "Escuela de danza": "escuelas de danza", "Club deportivo": "clubes deportivos", "Deportivo público": "deportivos públicos",
          "Centro acuático": "centros acuáticos", "Muro de escalada": "muros de escalada", "Tienda": "tiendas"}


def puntaje(r):
    return (3 * bool(r.lo_mejor) + 2 * bool(r.get("foto_url", "")) + 2 * bool(r.horario) + bool(r.instagram or r.facebook)
            + bool(r.telefono or r.whatsapp) + bool(r.sitio_web) + bool(r.pases))


def enlaces(s, url):
    """id → liga pública de cada ficha, leyendo la API (100 por página)."""
    sal, pag = {}, 1
    while True:
        r = s.get(f"{url}/wp-json/geodir/v2/lugares", params={"per_page": 100, "page": pag, "_fields": "id,link"}, timeout=90)
        if r.status_code != 200:
            break
        datos = r.json()
        if not datos:
            break
        sal.update({str(d["id"]): d["link"] for d in datos})
        pag += 1
        if pag > int(r.headers.get("X-WP-TotalPages", pag)):
            break
    return sal


def item(r, liga):
    partes = [r.tipo_lugar]
    if r.colonia:
        partes.append(r.colonia)
    if r.ciudad and r.ciudad not in r.colonia:
        partes.append(r.ciudad)
    extra = []
    if r.pases:
        extra.append("Acepta " + r.pases.replace("|", " y "))
    if r.instalaciones:
        extra.append(r.instalaciones.replace("|", ", ").lower().capitalize())
    txt = f'<li><a href="{liga}"><strong>{html.escape(r.nombre)}</strong></a> · {html.escape(" · ".join(partes))}'
    if extra:
        txt += f'<br><small>{html.escape(". ".join(extra))}.</small>'
    if r.lo_mejor:
        txt += f'<br><em>{html.escape(r.lo_mejor)}</em>'
    return txt + "</li>"


def cuerpo_guia(titulo_corto, metro, filas, ligas, tope, hoy):
    n = len(filas)
    mes = f"{MESES[hoy.month - 1]} de {hoy.year}"
    tipos = filas.tipo_lugar.value_counts()
    tipo_txt = ", ".join(f"{c} {PLURAL.get(t, t.lower())}" for t, c in tipos.head(3).items())
    intro = (f"<p>Encontramos {n} lugares de {titulo_corto.lower()} en {metro}: {tipo_txt}. "
             f"Cada uno tiene su ficha con dirección, mapa, horario, redes y, cuando hay suficientes reseñas, lo que dice la gente.</p>"
             f"<p><small>Actualizada en {mes}. Si ves un dato mal, repórtalo desde la ficha.</small></p>")
    lista = [item(r, ligas[r.wp_id]) for _, r in filas.head(tope).iterrows() if r.wp_id in ligas]
    if n > tope:
        intro += f"<p>Aquí van los {tope} con información más completa.</p>"
    return "<!-- wp:html -->\n" + intro + '<ul class="g52-guia">' + "".join(lista) + "</ul>\n<!-- /wp:html -->"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=6)
    ap.add_argument("--tope", type=int, default=60)
    ap.add_argument("--simular", action="store_true")
    a = ap.parse_args()
    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ.get("WP_USER", ""), os.environ.get("WP_APP_PASSWORD", ""))
    base = pd.read_csv(os.path.join(RAIZ, "data", "base.csv"), dtype=str).fillna("")
    for c in ("lo_mejor", "foto_url", "pases", "instalaciones"):
        if c not in base.columns:
            base[c] = ""
    base = base[base.wp_id != ""].copy()
    base["puntaje"] = base.apply(puntaje, axis=1)
    hoy = dt.date.today()

    grupos = []  # (titulo_corto, metro_nombre, slug, filas)
    for metro, dfm in base.groupby("metropoli"):
        nombre = NOMBRE_METRO.get(metro, metro)
        gim = dfm[dfm.tipo_lugar == "Gimnasio"].sort_values("puntaje", ascending=False)
        if len(gim) >= a.min:
            grupos.append(("Gimnasios", nombre, slug(f"gimnasios {nombre}"), gim))
        x = dfm.assign(d=dfm.disciplinas.str.split("|")).explode("d")
        for d, dfd in x[(x.d != "") & (x.d != "Pesas") & (x.d != "Equipo de gimnasio")].groupby("d"):
            if len(dfd) >= a.min:
                grupos.append((d, nombre, slug(f"{d} {nombre}"), dfd.sort_values("puntaje", ascending=False)))
    print(f"Guías a publicar: {len(grupos)}")
    if a.simular:
        for g in grupos[:15]:
            print(" ", g[0], "en", g[1], len(g[3]))
        return

    ligas = enlaces(s, url)
    ruta = os.path.join(RAIZ, "data", "guias.csv")
    reg = pd.read_csv(ruta, dtype=str).fillna("") if os.path.exists(ruta) else pd.DataFrame(columns=["slug", "page_id", "titulo", "lugares"])
    ids = dict(zip(reg.slug, reg.page_id))

    def guardar_pagina(slug_p, titulo, contenido, padre=0, extracto=""):
        datos = {"title": titulo, "content": contenido, "status": "publish", "slug": slug_p, "excerpt": extracto}
        if padre:
            datos["parent"] = int(padre)
        pid = ids.get(slug_p)
        r = s.post(f"{url}/wp-json/wp/v2/pages" + (f"/{pid}" if pid else ""), json=datos, timeout=90)
        if r.status_code in (200, 201):
            ids[slug_p] = str(r.json()["id"])
            return ids[slug_p]
        print("  error", slug_p, r.status_code, r.text[:150])
        return ""

    madre = guardar_pagina("guias", "Guías", "<!-- wp:paragraph --><p>Preparando las guías…</p><!-- /wp:paragraph -->")
    filas_reg, indice = [], {}
    for titulo_corto, metro, slug_p, filas in grupos:
        titulo = f"{titulo_corto} en {metro}"
        pid = guardar_pagina(slug_p, titulo, cuerpo_guia(titulo_corto, metro, filas, ligas, a.tope, hoy), madre,
                             f"{len(filas)} lugares de {titulo_corto.lower()} en {metro}, con dirección, horario y opiniones.")
        if pid:
            filas_reg.append({"slug": slug_p, "page_id": pid, "titulo": titulo, "lugares": len(filas)})
            indice.setdefault(metro, []).append((titulo_corto, slug_p, len(filas)))
        time.sleep(0.3)
    # índice en la página madre
    partes = ["<!-- wp:html -->", "<p>Listas de lugares para entrenar por ciudad y disciplina, armadas con la información de cada ficha.</p>"]
    for metro in sorted(indice, key=lambda m: -sum(n for _, _, n in indice[m])):
        partes.append(f"<h2>{html.escape(metro)}</h2><ul class=\"g52-guias-indice\">")
        for t, sl, n in sorted(indice[metro], key=lambda z: -z[2]):
            partes.append(f'<li><a href="/guias/{sl}/">{html.escape(t)}</a> <small>({n})</small></li>')
        partes.append("</ul>")
    partes.append("<!-- /wp:html -->")
    guardar_pagina("guias", "Guías", "\n".join(partes))
    pd.DataFrame(filas_reg).to_csv(ruta, index=False)
    print(f"Guías publicadas: {len(filas_reg)}")


if __name__ == "__main__":
    main()
