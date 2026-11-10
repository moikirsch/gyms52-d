# -*- coding: utf-8 -*-
"""Lee el sitio propio de cada ficha y saca reservas en línea, horario y precios publicados.

Uso: python sitios.py --max 1500 [--rehacer] [--simular N]
- Solo visita fichas con sitio web propio (no redes sociales) y sin `sitio_el`.
- Reservas: detecta la plataforma (Mindbody, Glofox, Fitco, Wodify, etc.) y guarda la liga para reservar.
- Horario: solo si el sitio lo publica en datos estructurados (schema.org); nunca lo adivina del texto.
- Precios: mensualidad e inscripción solo si aparecen como "$X al mes" o "inscripción $X" en el sitio;
  se guardan con la fecha y la página de donde salieron. Solo llena campos vacíos.
- Además de la portada, lee hasta 2 páginas internas de precios, planes, horarios o clases.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html as htmlmod
import json
import os
import re
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests

from comun import DIAS_GD, horario_osm, horario_texto_gd, sin_acentos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
REDES = ("instagram.com", "facebook.com", "tiktok.com", "wa.me", "whatsapp.com", "linktr.ee", "youtube.com", "google.com",
         "goo.gl", "maps.app")

# dominio que aparece en una liga o un iframe → nombre de la plataforma
PLATAFORMAS = [
    ("mindbodyonline.com", "Mindbody"), ("mindbody.io", "Mindbody"), ("clients.mindbodyonline", "Mindbody"),
    ("glofox.com", "Glofox"), ("fitco.io", "Fitco"), ("fitco.com", "Fitco"), ("wodify.com", "Wodify"),
    ("trainingym.com", "Trainingym"), ("zenplanner.com", "Zen Planner"), ("pushpress.com", "PushPress"),
    ("boxmagic.cl", "BoxMagic"), ("boxmagic.app", "BoxMagic"), ("virtuagym.com", "Virtuagym"),
    ("eversports.", "Eversports"), ("momence.com", "Momence"), ("arketa.co", "Arketa"), ("bsport.io", "bsport"),
    ("teamup.com", "TeamUp"), ("goteamup.com", "TeamUp"), ("clubready.com", "ClubReady"), ("marianatek.com", "Mariana Tek"),
    ("agendapro.com", "AgendaPro"), ("simplybook.me", "SimplyBook"), ("acuityscheduling.com", "Acuity"),
    ("calendly.com", "Calendly"), ("fitune.mx", "Fitune"), ("hapana.com", "Hapana"), ("perfectgym.com", "PerfectGym"),
    ("resawod.com", "Resawod"), ("wellnessliving.com", "WellnessLiving"), ("vagaro.com", "Vagaro"),
    ("sportskit.", "SportsKit"), ("gymmasteronline.com", "GymMaster"), ("fitfuel", ""),
]
PLATAFORMAS = [(d, n) for d, n in PLATAFORMAS if n]
RE_LIGA = re.compile(r"""(?:href|src|data-src|action)\s*=\s*["']([^"'<>\s]+)["']""", re.I)
RE_JSONLD = re.compile(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
INTERNAS = re.compile(r"precio|tarifa|membres|planes|plan-|paquete|horario|clases|schedule|pricing|prices|reserva|booking", re.I)
RE_MES = re.compile(r"\$\s?(\d{1,2}[,.]\d{3}|\d{3,5})(?:\.\d{2})?\s*(?:mxn|m\.n\.|pesos)?\s*(?:/|al|x|por|cada)\s*mes\b", re.I)
RE_MES2 = re.compile(r"mensualidad(?:es)?\s*(?:desde|de)?\s*:?\s*\$\s?(\d{1,2}[,.]\d{3}|\d{3,5})", re.I)
RE_INSC = re.compile(r"inscripci[oó]n\s*(?:desde|de)?\s*:?\s*\$\s?(\d{1,2}[,.]\d{3}|\d{3,5})", re.I)
PROMO = re.compile(r"primer mes|1er mes|promo|descuento|\d+\s?%|\boff\b|antes\s*\$|por tiempo limitado|estudiante|anual|semestr|trimestr", re.I)
DIA_SCHEMA = {"monday": "Mo", "tuesday": "Tu", "wednesday": "We", "thursday": "Th", "friday": "Fr", "saturday": "Sa", "sunday": "Su"}


def propio(url):
    host = urlparse(url).netloc.lower()
    return host and not any(r in host for r in REDES)


def visitar(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": UA, "Accept-Language": "es-MX,es"}, allow_redirects=True)
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            return None, url
        return r.text[:800000], r.url
    except requests.RequestException:
        return None, url


def texto_plano(h):
    h = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", h, flags=re.S | re.I)
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", h)))


def reservas(paginas):
    """Primera liga a una plataforma de reservas conocida → (plataforma, liga)."""
    for h, base_url in paginas:
        for liga in RE_LIGA.findall(h):
            low = liga.lower()
            for dominio, nombre in PLATAFORMAS:
                if dominio in low:
                    absoluta = urljoin(base_url, liga)
                    if absoluta.startswith("http") and not absoluta.lower().endswith((".js", ".css", ".png", ".jpg", ".svg")):
                        return nombre, absoluta.split("#")[0]
                    return nombre, ""  # solo un script o widget: sabemos la plataforma, no la liga
    return "", ""


def _objetos(dato):
    if isinstance(dato, list):
        for x in dato:
            yield from _objetos(x)
    elif isinstance(dato, dict):
        yield dato
        for k in ("@graph", "mainEntity", "location"):
            if k in dato:
                yield from _objetos(dato[k])


def horario_schema(paginas):
    """Horario desde schema.org (openingHours u openingHoursSpecification) en formato GeoDirectory."""
    for h, _ in paginas:
        for bloque in RE_JSONLD.findall(h):
            try:
                dato = json.loads(bloque.strip())
            except ValueError:
                continue
            for o in _objetos(dato):
                oh = o.get("openingHours")
                if oh:
                    txt = "; ".join(oh) if isinstance(oh, list) else str(oh)
                    gd = horario_osm(txt.replace(" -", "-").replace("- ", "-"))
                    if gd:
                        return gd
                spec = o.get("openingHoursSpecification")
                if spec:
                    por_dia = {d: [] for d in DIAS_GD}
                    for s in spec if isinstance(spec, list) else [spec]:
                        if not isinstance(s, dict):
                            continue
                        dias = s.get("dayOfWeek", [])
                        dias = dias if isinstance(dias, list) else [dias]
                        a, b = str(s.get("opens", ""))[:5], str(s.get("closes", ""))[:5]
                        if not re.fullmatch(r"\d{2}:\d{2}", a) or not re.fullmatch(r"\d{2}:\d{2}", b):
                            continue
                        if b in ("00:00", "24:00"):
                            b = "23:59"
                        for d in dias:
                            clave = DIA_SCHEMA.get(str(d).rsplit("/", 1)[-1].lower())
                            if clave:
                                por_dia[clave].append(f"{a}-{b}")
                    if any(por_dia.values()):
                        return horario_texto_gd(por_dia)
    return ""


def _num(x):
    try:
        return int(re.sub(r"[,.]", "", x))
    except ValueError:
        return 0


def precios(paginas):
    """(mensualidad mínima, inscripción, liga de la página). Solo montos con contexto claro y en rango creíble."""
    mejor_mes, insc, fuente = 0, 0, ""
    for h, url in paginas:
        t = texto_plano(h)
        if re.search(r"\bUSD\b|dólares|dolares", t, re.I):
            continue
        mes = [_num(m.group(1)) for rx in (RE_MES, RE_MES2) for m in rx.finditer(t) if not PROMO.search(t[max(0, m.start() - 90):m.end() + 40])]
        mes = [m for m in mes if 250 <= m <= 8000]
        if mes and (not mejor_mes or min(mes) < mejor_mes):
            mejor_mes, fuente = min(mes), url
        ins = [_num(m) for m in RE_INSC.findall(t)]
        ins = [m for m in ins if 100 <= m <= 6000]
        if ins and not insc:
            insc = min(ins)
            fuente = fuente or url
    return mejor_mes, insc, fuente


def leer(url):
    portada, final = visitar(url)
    if not portada:
        return None
    paginas = [(portada, final)]
    host = urlparse(final).netloc.lower()
    vistas = {final.rstrip("/")}
    for liga in RE_LIGA.findall(portada):
        absoluta = urljoin(final, liga).split("#")[0]
        if urlparse(absoluta).netloc.lower() != host or absoluta.rstrip("/") in vistas:
            continue
        if INTERNAS.search(urlparse(absoluta).path) and not absoluta.lower().endswith((".pdf", ".jpg", ".png", ".css", ".js")):
            vistas.add(absoluta.rstrip("/"))
            h, u = visitar(absoluta)
            if h:
                paginas.append((h, u))
            if len(paginas) >= 3:
                break
    plataforma, liga = reservas(paginas)
    mes, insc, fuente = precios(paginas)
    return {"reserva_plataforma": plataforma, "reserva_url": liga, "horario": horario_schema(paginas),
            "mensualidad_desde": str(mes) if mes else "", "inscripcion": str(insc) if insc else "", "precio_fuente_url": fuente}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=1500)
    ap.add_argument("--rehacer", action="store_true")
    ap.add_argument("--simular", type=int, default=0, help="lee N sitios e imprime lo que encontró, sin guardar")
    a = ap.parse_args()
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    for c in ("sitio_el", "reserva_url", "reserva_plataforma", "horario", "mensualidad_desde", "inscripcion", "fecha_precio",
              "precio_fuente_url", "pendiente_sync"):
        if c not in base.columns:
            base[c] = ""
    if a.rehacer:
        base["sitio_el"] = ""
    filtro = (base.wp_id != "") & (base.sitio_web != "") & (base.sitio_el == "") & base.sitio_web.map(propio)
    objetivo = list(base[filtro].index)[: (a.simular or a.max)]
    hoy = dt.date.today()
    cuenta = {"leidos": 0, "reserva": 0, "horario": 0, "precio": 0, "con_cambios": 0}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for i, res in zip(objetivo, ex.map(lambda k: leer(base.at[k, "sitio_web"]), objetivo)):
            if a.simular:
                if res and any(res.values()):
                    print(base.at[i, "nombre"][:40], "|", {k: v for k, v in res.items() if v})
                continue
            base.at[i, "sitio_el"] = hoy.isoformat()
            if not res:
                continue
            cuenta["leidos"] += 1
            cambio = False
            if res["reserva_plataforma"] and not base.at[i, "reserva_plataforma"]:
                base.at[i, "reserva_plataforma"] = res["reserva_plataforma"]
                base.at[i, "reserva_url"] = res["reserva_url"]
                cuenta["reserva"] += 1
                cambio = True
            if res["horario"] and not base.at[i, "horario"]:
                base.at[i, "horario"] = res["horario"]
                cuenta["horario"] += 1
                cambio = True
            if res["mensualidad_desde"] and not base.at[i, "mensualidad_desde"] and not base.at[i, "cadena"]:
                base.at[i, "mensualidad_desde"] = res["mensualidad_desde"]
                if res["inscripcion"] and not base.at[i, "inscripcion"]:
                    base.at[i, "inscripcion"] = res["inscripcion"]
                base.at[i, "fecha_precio"] = hoy.strftime("%Y-%m")
                base.at[i, "precio_fuente_url"] = res["precio_fuente_url"]
                cuenta["precio"] += 1
                cambio = True
            if cambio:
                cuenta["con_cambios"] += 1
                base.at[i, "pendiente_sync"] = "1"
    if a.simular:
        return
    if cuenta["con_cambios"]:
        from unir import con_opiniones, descripcion
        cambiadas = base.index[(base.sitio_el == hoy.isoformat()) & (base.pendiente_sync == "1")]
        for i in cambiadas:
            base.at[i, "descripcion"] = con_opiniones(descripcion(base.loc[i].to_dict()), base.loc[i].to_dict())
    base.to_csv(ruta, index=False)
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    cuenta["visitados"] = len(objetivo)
    json.dump(cuenta, open(os.path.join(RAIZ, "data", "corridas", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-sitios.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"Sitios: {cuenta['leidos']}/{len(objetivo)} leídos | reservas {cuenta['reserva']} | horario {cuenta['horario']} | "
          f"precios {cuenta['precio']} | fichas con cambios {cuenta['con_cambios']}")


if __name__ == "__main__":
    main()
