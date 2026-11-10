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

from comun import foto_valida, slug

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOMBRE_METRO = {"Valle de México (CDMX)": "Ciudad de México", "Zapopan": "Guadalajara", "Ecatepec de Morelos": "Ecatepec"}
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
PLURAL = {"Gimnasio": "gimnasios", "Estudio": "estudios", "Box": "boxes", "Gimnasio de combate": "gimnasios de combate",
          "Escuela de danza": "escuelas de danza", "Club deportivo": "clubes deportivos", "Deportivo público": "deportivos públicos",
          "Centro acuático": "centros acuáticos", "Muro de escalada": "muros de escalada", "Tienda": "tiendas"}


def puntaje(r):
    return (3 * bool(r.lo_mejor) + 2 * foto_valida(r.get("foto_url", "")) + 2 * bool(r.horario) + bool(r.instagram or r.facebook)
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
        planes = [x for x in str(r.get("totalpass_planes", "")).split("|") if x and "free" not in x.lower()]
        if planes and "TotalPass" in r.pases:
            extra.append(f"TotalPass desde {planes[0]}")
    if r.instalaciones:
        extra.append(r.instalaciones.replace("|", ", ").lower().capitalize())
    txt = f'<li><a href="{liga}"><strong>{html.escape(r.nombre)}</strong></a> · {html.escape(" · ".join(partes))}'
    if extra:
        txt += f'<br><small>{html.escape(". ".join(extra))}.</small>'
    if r.lo_mejor:
        txt += f'<br><em>{html.escape(r.lo_mejor)}</em>'
    return txt + "</li>"


def cuerpo_guia(titulo_corto, metro, filas, ligas, tope, hoy, frase=""):
    n = len(filas)
    mes = f"{MESES[hoy.month - 1]} de {hoy.year}"
    tipos = filas.tipo_lugar.value_counts()
    tipo_txt = ", ".join(f"{c} {PLURAL.get(t, t.lower())}" for t, c in tipos.head(3).items())
    frase = frase or f"lugares de {titulo_corto.lower()}"
    intro = (f"<p>Encontramos {n} {frase} en {metro}: {tipo_txt}. "
             f"Cada uno tiene su ficha con dirección, mapa, horario, redes y, cuando hay suficientes reseñas, lo que dice la gente.</p>"
             f"<p><small>Actualizada en {mes}. Si ves un dato mal, repórtalo desde la ficha.</small></p>")
    lista = [item(r, ligas[r.wp_id]) for _, r in filas.head(tope).iterrows() if r.wp_id in ligas]
    if n > tope:
        intro += f"<p>Aquí van los {tope} con información más completa.</p>"
    return "<!-- wp:html -->\n" + intro + '<ul class="g52-guia">' + "".join(lista) + "</ul>\n<!-- /wp:html -->"


def pagina_densidad(hoy):
    """Metrópolis con más gimnasios por habitante, con el DENUE del INEGI (misma fuente para todas)."""
    d = pd.read_csv(os.path.join(RAIZ, "data", "denue", "gimnasios.csv"), dtype=str).fillna("")
    m = pd.read_csv(os.path.join(RAIZ, "config", "metros.csv"), dtype=str).fillna("")
    m["poblacion"] = pd.to_numeric(m.poblacion, errors="coerce")
    conteo = d.groupby("metro_rango").size()
    m["gyms"] = m.rango.map(conteo).fillna(0)
    m = m[(m.poblacion >= 300000) & (m.gyms > 0)].copy()
    m["por100k"] = m.gyms / m.poblacion * 100000
    m["nombre"] = m.metropoli.map(lambda x: NOMBRE_METRO.get(x, x))
    m = m.sort_values("por100k", ascending=False)
    total = d.shape[0]
    pais = m.gyms.sum() / m.poblacion.sum() * 100000
    mes = f"{MESES[hoy.month - 1]} de {hoy.year}"
    p = ["<!-- wp:html -->",
         f"<p>En las metrópolis de México de más de 300 mil habitantes hay en promedio <strong>{pais:.0f} lugares para entrenar por cada "
         f"100 mil personas</strong>. {html.escape(m.iloc[0]['nombre'])} encabeza la lista con {m.iloc[0]['por100k']:.0f}; "
         f"{html.escape(m.iloc[-1]['nombre'])} cierra con {m.iloc[-1]['por100k']:.0f}.</p>",
         "<table class=\"g52-precios\"><thead><tr><th>#</th><th>Metrópoli</th><th>Por cada 100 mil habitantes</th>"
         "<th>Lugares registrados</th><th>Habitantes</th></tr></thead><tbody>"]
    for k, (_, r) in enumerate(m.iterrows(), 1):
        p.append(f"<tr><td>{k}</td><td>{html.escape(r['nombre'])}</td><td>{r.por100k:.1f}</td><td>{int(r.gyms):,}</td><td>{int(r.poblacion):,}</td></tr>")
    p.append("</tbody></table>")
    p.append(f"<h2>Cómo lo calculamos</h2><p>Contamos los centros de acondicionamiento físico públicos y privados que registra el "
             f"Directorio Estadístico Nacional de Unidades Económicas (DENUE) del INEGI en cada zona metropolitana ({total:,} en total) "
             f"y los dividimos entre su población. Usamos solo el DENUE para que todas las ciudades se midan igual; en Gyms +52 hay "
             f"más lugares porque sumamos estudios, boxes y clubes de otras fuentes. Actualizado en {mes}.</p>")
    p.append("<!-- /wp:html -->")
    return "\n".join(p), len(m)


def pagina_cadenas(base, hoy, minimo=8):
    """Comparativo de las cadenas con más sucursales publicadas: sucursales, ciudades, pases, 24 h y precio."""
    c = base[base.cadena != ""]
    filas = []
    for cadena, g in c.groupby("cadena"):
        if len(g) < minimo:
            continue
        precio = pd.to_numeric(g.mensualidad_desde, errors="coerce").dropna()
        pases = []
        for pase in ("TotalPass", "Wellhub", "Fitpass", "ClassPass"):
            n = g.pases.str.contains(pase, na=False).sum()
            if n:
                pases.append(f"{pase} ({n})")
        precio = precio[(precio >= 150) & (precio <= 10000)]
        filas.append((cadena, len(g), g.metropoli.nunique(),
                      _pesos(precio.median()) if len(precio) >= 3 else "sin datos suficientes", ", ".join(pases) or "ninguno registrado"))
    filas.sort(key=lambda z: -z[1])
    mes = f"{MESES[hoy.month - 1]} de {hoy.year}"
    p = ["<!-- wp:html -->",
         f"<p>Las cadenas de gimnasios con más sucursales en México, según las fichas de Gyms +52. Actualizado en {mes}.</p>",
         "<table class=\"g52-precios\"><thead><tr><th>Cadena</th><th>Sucursales</th><th>Ciudades</th>"
         "<th>Mensualidad típica</th><th>Sucursales con pase</th></tr></thead><tbody>"]
    for f in filas:
        p.append("<tr>" + "".join(f"<td>{html.escape(str(x))}</td>" for x in f) + "</tr>")
    p.append("</tbody></table><p><small>Sucursales y pases según los sitios oficiales de cada cadena y de cada pase. "
             "La mensualidad típica es la mediana de lo que publica la cadena por sucursal, sin promociones; puede variar en cada una.</small></p>")
    p.append("<!-- /wp:html -->")
    return "\n".join(p), len(filas)


def _pesos(x):
    return f"${int(round(x)):,}"


def indice_precios(base, hoy, min_ciudad=5, min_total=150):
    """Página con la mensualidad típica (mediana) por ciudad y por tipo de lugar.

    Usa solo precios con fecha de los últimos 12 meses. Las cadenas cuentan una vez por cadena y ciudad,
    para que una cadena con cientos de sucursales al mismo precio no tape a los independientes.
    Regresa (html, resumen, publicable): solo se publica con al menos min_total precios independientes."""
    df = base.assign(m=pd.to_numeric(base.mensualidad_desde, errors="coerce")).dropna(subset=["m"])
    df = df[(df.m >= 150) & (df.m <= 10000)]
    corte = f"{hoy.year - 1}-{hoy.month:02d}"
    df = df[df.fecha_precio.fillna("") >= corte]
    df["ciudad_guia"] = df.metropoli.map(lambda m: NOMBRE_METRO.get(m, m))
    indep = df[df.cadena == ""]
    cadenas = df[df.cadena != ""].groupby(["cadena", "ciudad_guia"]).m.median().reset_index()
    muestra = pd.concat([indep[["ciudad_guia", "tipo_lugar", "m"]], cadenas.assign(tipo_lugar="Gimnasio")[["ciudad_guia", "tipo_lugar", "m"]]])
    resumen = f"Índice de precios: {len(indep)} precios independientes, {len(cadenas)} cadena-ciudad"
    if len(indep) < min_total:
        return "", resumen + f" (se publica al llegar a {min_total} independientes)", False
    mes = f"{MESES[hoy.month - 1]} de {hoy.year}"
    med = muestra.m.median()
    filas_c = []
    for c, g in muestra.groupby("ciudad_guia"):
        if len(g) >= min_ciudad:
            filas_c.append((c, len(g), g.m.median(), g.m.quantile(0.25), g.m.quantile(0.75)))
    filas_c.sort(key=lambda z: -z[1])
    filas_t = []
    for t, g in muestra.groupby("tipo_lugar"):
        if len(g) >= min_ciudad:
            filas_t.append((t, len(g), g.m.median()))
    filas_t.sort(key=lambda z: -z[2])
    p = ["<!-- wp:html -->",
         f"<p>En México, la mensualidad típica para entrenar es de <strong>{_pesos(med)}</strong>, según {len(muestra)} precios "
         f"publicados por gimnasios, estudios y boxes en Gyms +52. Actualizado en {mes}.</p>",
         "<h2>Por ciudad</h2><table class=\"g52-precios\"><thead><tr><th>Ciudad</th><th>Mensualidad típica</th>"
         "<th>La mitad de los lugares cobra entre</th><th>Precios</th></tr></thead><tbody>"]
    for c, n, m, q1, q3 in filas_c:
        p.append(f"<tr><td>{html.escape(c)}</td><td>{_pesos(m)}</td><td>{_pesos(q1)} y {_pesos(q3)}</td><td>{n}</td></tr>")
    p.append("</tbody></table><h2>Por tipo de lugar</h2><table class=\"g52-precios\"><thead><tr><th>Tipo</th>"
             "<th>Mensualidad típica</th><th>Precios</th></tr></thead><tbody>")
    for t, n, m in filas_t:
        p.append(f"<tr><td>{html.escape(t)}</td><td>{_pesos(m)}</td><td>{n}</td></tr>")
    p.append("</tbody></table>")
    p.append("<h2>Cómo lo calculamos</h2><p>Tomamos la mensualidad más baja que cada lugar publica en su sitio, redes o en "
             "reseñas recientes, siempre con fecha y fuente, y solo de los últimos 12 meses. No contamos promociones de "
             "primer mes ni planes anuales. Cada cadena cuenta una vez por ciudad, para que una cadena con muchas sucursales "
             "al mismo precio no cargue el promedio. \"Mensualidad típica\" es la mediana: la mitad cobra menos y la mitad más.</p>")
    p.append("<!-- /wp:html -->")
    return "\n".join(p), resumen + f", publicado con {len(muestra)} precios", True


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
    for c in ("lo_mejor", "foto_url", "pases", "instalaciones", "abierto_24h", "reserva_plataforma", "mensualidad_desde", "cadena", "totalpass_planes"):
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
        # guías por necesidad: lo que la gente busca además de la disciplina
        necesidades = [
            ("Gimnasios abiertos 24 horas", "lugares abiertos las 24 horas", f"gimnasios 24 horas {nombre}", dfm[dfm.abierto_24h == "1"]),
            ("Gimnasios con alberca", "lugares para entrenar con alberca", f"gimnasios con alberca {nombre}",
             dfm[dfm.instalaciones.str.contains("Alberca", na=False)]),
            ("Clases con reserva en línea", "lugares donde puedes reservar tu clase en línea", f"reserva en linea {nombre}",
             dfm[dfm.reserva_plataforma != ""]),
        ]
        for pase in ("TotalPass", "Wellhub", "Fitpass", "ClassPass"):
            necesidades.append((f"Dónde usar {pase}", f"lugares que aceptan {pase}", f"{pase} {nombre}",
                                dfm[dfm.pases.str.contains(pase, na=False)]))
        for titulo_corto, frase, sl, dfn in necesidades:
            if len(dfn) >= a.min:
                grupos.append((titulo_corto, nombre, slug(sl), dfn.sort_values("puntaje", ascending=False), frase))
    grupos = [g if len(g) == 5 else (*g, "") for g in grupos]
    print(f"Guías a publicar: {len(grupos)}")
    if a.simular:
        nec = [g for g in grupos if g[4]]
        print(f"  de esas, por necesidad: {len(nec)}")
        for g in nec[:25]:
            print(" ", g[0], "en", g[1], len(g[3]))
        print(indice_precios(base, hoy)[1])
        print(pagina_densidad(hoy)[0][:900])
        print(pagina_cadenas(base, hoy)[0][:1500])
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
        if not pid:  # páginas que no están en guias.csv (madre, cadenas, densidad, precios): búscala antes de crear otra
            q = {"slug": slug_p, "status": "publish", "_fields": "id"}
            if padre:
                q["parent"] = int(padre)
            r0 = s.get(f"{url}/wp-json/wp/v2/pages", params=q, timeout=60)
            if r0.status_code == 200 and r0.json():
                pid = str(r0.json()[0]["id"])
        r = s.post(f"{url}/wp-json/wp/v2/pages" + (f"/{pid}" if pid else ""), json=datos, timeout=90)
        if r.status_code in (200, 201):
            ids[slug_p] = str(r.json()["id"])
            return ids[slug_p]
        print("  error", slug_p, r.status_code, r.text[:150])
        return ""

    # la página madre no se guarda en guias.csv: se busca por su slug para no crear "guias-2", "guias-3"...
    r = s.get(f"{url}/wp-json/wp/v2/pages", params={"slug": "guias", "status": "publish", "_fields": "id"}, timeout=60)
    if r.status_code == 200 and r.json():
        ids["guias"] = str(r.json()[0]["id"])
    madre = guardar_pagina("guias", "Guías", "<!-- wp:paragraph --><p>Preparando las guías…</p><!-- /wp:paragraph -->")
    filas_reg, indice = [], {}
    for titulo_corto, metro, slug_p, filas, frase in grupos:
        titulo = f"{titulo_corto} en {metro}"
        pid = guardar_pagina(slug_p, titulo, cuerpo_guia(titulo_corto, metro, filas, ligas, a.tope, hoy, frase), madre,
                             f"{len(filas)} {frase or 'lugares de ' + titulo_corto.lower()} en {metro}, con dirección, horario y opiniones.")
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
    precios_html, precios_resumen, publicable = indice_precios(base, hoy)
    print(precios_resumen)
    if publicable and guardar_pagina("precios-gimnasios", "Cuánto cuesta un gimnasio en México", precios_html, madre,
                                     "Mensualidad típica de gimnasios y estudios por ciudad, con datos publicados por los propios lugares."):
        partes.insert(2, '<p><strong><a href="/guias/precios-gimnasios/">Cuánto cuesta un gimnasio en México</a></strong>: '
                         'mensualidades por ciudad y tipo de lugar.</p>')
    dens_html, n_dens = pagina_densidad(hoy)
    if n_dens and guardar_pagina("gimnasios-por-habitante", "Las ciudades de México con más gimnasios por habitante", dens_html, madre,
                                 "Lugares para entrenar por cada 100 mil habitantes en las metrópolis de México, con datos del INEGI."):
        partes.insert(2, '<p><strong><a href="/guias/gimnasios-por-habitante/">Las ciudades con más gimnasios por habitante</a></strong>.</p>')
    cad_html, n_cad = pagina_cadenas(base, hoy)
    if n_cad and guardar_pagina("cadenas-de-gimnasios", "Cadenas de gimnasios en México: sucursales, pases y precios", cad_html, madre,
                                "Smart Fit, Anytime Fitness, Sports World, Sport City y más: cuántas sucursales tienen, en qué ciudades y qué pases aceptan."):
        partes.insert(2, '<p><strong><a href="/guias/cadenas-de-gimnasios/">Cadenas de gimnasios en México</a></strong>: sucursales, pases y precios.</p>')
    print(f"Páginas de datos: densidad {n_dens} metrópolis, cadenas {n_cad}")
    partes.append("<!-- /wp:html -->")
    guardar_pagina("guias", "Guías", "\n".join(partes))
    pd.DataFrame(filas_reg).to_csv(ruta, index=False)
    print(f"Guías publicadas: {len(filas_reg)}")


if __name__ == "__main__":
    main()
