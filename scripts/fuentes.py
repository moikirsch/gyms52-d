# -*- coding: utf-8 -*-
"""Importa fuentes públicas de gimnasios (cadenas, afiliaciones y pases) a un formato común.

Uso: python fuentes.py [--solo smartfit,crossfit,...] [--max-tp N] [--estricto]

Fuentes: smartfit, anytime, sportsworld, sportcity, crossfit, hyrox, totalpass, fitpass.
Escribe data/fuentes/<fuente>.jsonl (un lugar por línea, esquema normalizado) y data/fuentes/resumen.json.
Cada fuente corre aparte: si una falla, su archivo anterior se conserva, el error queda en el resumen
(y como anotación ::error:: en GitHub Actions) y se sigue con las demás. Con --estricto, sale con código 1.

TotalPass usa caché (data/fuentes/totalpass_cache.json, slug → fecha de última lectura): cada corrida lee
primero las URLs nuevas y luego las de más de 30 días, hasta --max-tp páginas (default 3000; 0 = sin límite).
El jsonl de TotalPass es acumulado: se actualiza con lo leído y se quitan los slugs que ya no están en el sitemap.
"""
import argparse
import datetime as dt
import html as htmlmod
import json
import math
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from comun import sin_acentos

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(RAIZ, "data", "fuentes")
UA = "gyms52.com directorio (bot@gyms52.com)"
FUENTES = ["smartfit", "anytime", "sportsworld", "sportcity", "crossfit", "hyrox", "totalpass", "fitpass"]
CAMPOS = ["fuente", "id_fuente", "nombre", "lat", "lng", "calle", "colonia", "ciudad", "estado", "cp", "telefono",
          "sitio_web", "url_fuente", "horario_osm", "cadena", "pases", "afiliaciones", "instalaciones",
          "mensualidad_desde", "precio_fuente_url", "foto", "estatus", "tipo"]
LISTAS = {"pases", "afiliaciones", "instalaciones"}
INSTALACIONES = ["Alberca", "Regaderas y vestidores", "Lockers", "Sauna o vapor", "Estacionamiento", "Área infantil",
                 "Cafetería", "Tienda", "Zona de peso libre", "Zona funcional", "Aire acondicionado"]
TP_DIAS_REFRESCO = 30
TP_MAX_DEFAULT = 3000


# ------------------------------------------------------------------ HTTP con ritmo
class Cliente:
    """requests.Session con User-Agent propio, pausa mínima entre peticiones y reintentos."""

    def __init__(self, pausa=1.0):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept-Language": "es-MX,es;q=0.9"})
        self.pausa = pausa
        self._ultimo = 0.0
        self._lock = threading.Lock()
        self.peticiones = 0

    def _esperar(self):
        with self._lock:
            falta = self._ultimo + self.pausa - time.monotonic()
            if falta > 0:
                time.sleep(falta)
            self._ultimo = time.monotonic()
            self.peticiones += 1

    def pedir(self, metodo, url, ok404=False, **kw):
        kw.setdefault("timeout", 60)
        ultimo = ""
        for intento in range(4):
            self._esperar()
            try:
                r = self.s.request(metodo, url, **kw)
                if r.status_code == 200:
                    return r
                if r.status_code == 404 and ok404:
                    return None
                ultimo = f"HTTP {r.status_code}"
                if r.status_code not in (429, 500, 502, 503, 504):
                    break
            except requests.RequestException as e:
                ultimo = e.__class__.__name__
            time.sleep(3 * (intento + 1))
        raise RuntimeError(f"{metodo} {url}: {ultimo}")

    def get(self, url, **kw):
        return self.pedir("GET", url, **kw)

    def post(self, url, **kw):
        return self.pedir("POST", url, **kw)


# ------------------------------------------------------------------ normalización
def registro(**kw):
    r = {c: ([] if c in LISTAS else "") for c in CAMPOS}
    for k, v in kw.items():
        if k not in r:
            raise KeyError(k)
        if v is None:
            continue
        r[k] = v if k in LISTAS or isinstance(v, (int, float)) else limpio(v)
    return r


def limpio(s):
    s = htmlmod.unescape(str(s or ""))
    return re.sub(r"\s+", " ", s).strip(" ,;")


def html_a_lineas(s):
    s = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</li>|</div>", "\n", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    return [limpio(x) for x in htmlmod.unescape(s).split("\n") if limpio(x)]


def num(x):
    try:
        v = float(str(x).strip())
        return v if math.isfinite(v) else None
    except (TypeError, ValueError):
        return None


def telefono(s):
    """Primer teléfono del texto, a 10 dígitos sin +52. '' si no queda en 10 dígitos."""
    if not s:
        return ""
    primero = re.split(r"[/,;]| y | o |ext", str(s))[0]
    d = re.sub(r"\D", "", primero)
    if len(d) == 12 and d.startswith("52"):
        d = d[2:]
    elif len(d) == 13 and d.startswith("521"):
        d = d[3:]
    elif len(d) == 12 and d[:3] in ("044", "045"):
        d = d[2:]
    return d if len(d) == 10 else ""


def cp(s):
    m = re.search(r"\b(\d{5})\b", s or "")
    return m.group(1) if m else ""


def web(s):
    s = (s or "").strip()
    if not s or "@" in s and "/" not in s or not re.search(r"[a-z0-9-]\.[a-z]{2,}", s.lower()):
        return ""
    if not re.match(r"https?://", s):
        s = "https://" + s.lstrip("/")
    return s


def titulo_ciudad(s):
    s = limpio(s)
    if s and (s.isupper() or s.islower()):
        menores = {"de", "del", "la", "las", "los", "y", "el"}
        s = " ".join(w if w.lower() in menores and i else w.capitalize() for i, w in enumerate(s.lower().split()))
    return s


ESTADOS = ["Aguascalientes", "Baja California", "Baja California Sur", "Campeche", "Chiapas", "Chihuahua",
           "Ciudad de México", "Coahuila", "Colima", "Durango", "Estado de México", "Guanajuato", "Guerrero", "Hidalgo",
           "Jalisco", "Michoacán", "Morelos", "Nayarit", "Nuevo León", "Oaxaca", "Puebla", "Querétaro", "Quintana Roo",
           "San Luis Potosí", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz", "Yucatán", "Zacatecas"]
_ALIAS = {
    "ags": 0, "agu": 0, "bc": 1, "bcn": 1, "bcs": 2, "camp": 3, "cam": 3, "chis": 4, "chs": 4, "chp": 4, "chih": 5,
    "chh": 5, "cdmx": 6, "df": 6, "cmx": 6, "distritofederal": 6, "mexicocity": 6, "coah": 7, "coa": 7,
    "coahuiladezaragoza": 7, "col": 8, "dgo": 9, "dur": 9, "mex": 10, "edomex": 10, "edomexico": 10, "em": 10,
    "estadodemexico": 10, "mexico": 10, "gto": 11, "gua": 11, "gro": 12, "hgo": 13, "hid": 13, "jal": 14, "mich": 15,
    "mic": 15, "michoacandeocampo": 15, "mor": 16, "nay": 17, "nl": 18, "nle": 18, "oax": 19, "pue": 20, "qro": 21,
    "que": 21, "qroo": 22, "qr": 22, "roo": 22, "slp": 23, "sin": 24, "son": 25, "tab": 26, "tamps": 27, "tamp": 27,
    "tam": 27, "tlax": 28, "tla": 28, "ver": 29, "veracruzdeignaciodelallave": 29, "yuc": 30, "zac": 31,
}


def estado(s):
    k = re.sub(r"[^a-z]", "", sin_acentos(s or "").lower())
    if not k:
        return ""
    for i, e in enumerate(ESTADOS):
        if k == re.sub(r"[^a-z]", "", sin_acentos(e).lower()):
            return e
    if k in _ALIAS:
        return ESTADOS[_ALIAS[k]]
    return ""


# ------------------------------------------------------------------ horarios → formato OSM
DIAS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
DIA_ES = {"lu": "Mo", "ma": "Tu", "mi": "We", "ju": "Th", "vi": "Fr", "sa": "Sa", "do": "Su"}
DIA_EN = {"monday": "Mo", "tuesday": "Tu", "wednesday": "We", "thursday": "Th", "friday": "Fr", "saturday": "Sa",
          "sunday": "Su"}


def hhmm(h, m=0):
    h, m = int(h), int(m or 0)
    if h > 24 or m > 59:
        raise ValueError
    return f"{h:02d}:{m:02d}"


def rango(a, b):
    """'06:00','23:00' → '06:00-23:00'; cierre 00:00 → 24:00."""
    if b == "00:00":
        b = "24:00"
    if a == b:
        return ""
    return f"{a}-{b}"


def osm_desde_dias(por_dia, extra=""):
    """{'Mo': ['06:00-22:00'], ...} → 'Mo-Fr 06:00-22:00; Sa 08:00-14:00'. Días sin horas se omiten."""
    grupos = []
    for d in DIAS:
        h = ",".join(por_dia.get(d) or [])
        if grupos and grupos[-1][1] == h and DIAS.index(grupos[-1][0][-1]) == DIAS.index(d) - 1:
            grupos[-1][0].append(d)
        else:
            grupos.append(([d], h))
    partes = []
    for dias, h in grupos:
        if not h:
            continue
        txt = dias[0] if len(dias) == 1 else (f"{dias[0]},{dias[1]}" if len(dias) == 2 else f"{dias[0]}-{dias[-1]}")
        partes.append(f"{txt} {h}")
    if extra:
        partes.append(extra)
    if len(partes) == 1 and partes[0] == "Mo-Su 00:00-24:00":
        return "24/7"
    return "; ".join(partes)


def osm_desde_texto_es(texto):
    """Horario en español ('Lunes a Jueves: 6:00 a 23:00 hrs. Sábado: 8 a 18') → OSM. '' si no se entiende."""
    t = sin_acentos(texto or "").lower()
    t = re.sub(r"\s+", " ", t)
    dia = r"(?:(?:lun|mar|mie|jue|vie|sab|dom)[a-z]*|(?:dias\s+)?festivos?|feriados?)"
    hora = r"(\d{1,2})(?:[:.](\d{2}))?\s*(?:hrs?\.?|h\b)?\s*(am|pm|a\.m\.|p\.m\.)?"
    patron = re.compile(rf"({dia}(?:\s*(?:a|al|-|y|,)\s*{dia})*)\s*:?\s*(?:de\s*)?{hora}\s*(?:a|-|–)\s*{hora}")
    por_dia = {}
    for m in patron.finditer(t):
        dias_txt = m.group(1)
        nombres = re.findall(dia, dias_txt)
        cods = [DIA_ES.get(n[:2], "PH") for n in nombres]
        if re.search(rf"{dia}\s*(?:a|al|-)\s*{dia}", dias_txt) and len(cods) == 2 and "PH" not in cods:
            i, f = DIAS.index(cods[0]), DIAS.index(cods[1])
            cods = DIAS[i:f + 1] if f >= i else DIAS[i:] + DIAS[:f + 1]
        try:
            h1, m1, ap1, h2, m2, ap2 = m.group(2, 3, 4, 5, 6, 7)
            h1, h2 = int(h1), int(h2)
            if ap1 and ap1.startswith("p") and h1 < 12:
                h1 += 12
            if ap2 and ap2.startswith("p") and h2 < 12:
                h2 += 12
            r = rango(hhmm(h1, m1), hhmm(h2, m2))
        except ValueError:
            return ""
        if not r:
            continue
        for c in cods:
            por_dia.setdefault(c, []).append(r)
    ph = por_dia.pop("PH", None)
    if not por_dia:
        return ""
    return osm_desde_dias(por_dia, f"PH {','.join(ph)}" if ph else "")


def osm_desde_open_close(d):
    """{'monday': [{'open': '06:00', 'close': '21:00'}], ...} → OSM."""
    por_dia = {}
    for k, v in (d or {}).items():
        c = DIA_EN.get(str(k).lower())
        if not c or not isinstance(v, list):
            continue
        for x in v:
            try:
                a = hhmm(*str(x.get("open", "")).split(":")[:2])
                b = hhmm(*str(x.get("close", "")).split(":")[:2])
            except (ValueError, TypeError):
                continue
            r = rango(a, b)
            if r:
                por_dia.setdefault(c, []).append(r)
    return osm_desde_dias(por_dia) if por_dia else ""


# ------------------------------------------------------------------ instalaciones
REGLAS_INST = [
    (r"alberca|piscina|natacion|pool", "Alberca"),
    (r"regadera|vestidor|vestuario|ducha", "Regaderas y vestidores"),
    (r"locker|casillero", "Lockers"),
    (r"sauna|vapor|steam", "Sauna o vapor"),
    (r"estacionamiento|parking", "Estacionamiento"),
    (r"guarderia|area infantil|ludoteca|kids club|zona infantil|espacio kids", "Área infantil"),
    (r"cafeteria|cafe\b|snack bar|juice bar", "Cafetería"),
    (r"^tienda|^store$|^boutique", "Tienda"),
    (r"peso libre|free weight", "Zona de peso libre"),
    (r"funcional|functional", "Zona funcional"),
    (r"aire acondicionado|climatiza", "Aire acondicionado"),
]
NO_INST = re.compile(r"\bsin\b|uso parcial")


def instalaciones(nombres):
    out = []
    for n in nombres:
        k = sin_acentos(str(n)).lower().strip()
        if not k or NO_INST.search(k):
            continue
        for pat, val in REGLAS_INST:
            if re.search(pat, k) and val not in out:
                out.append(val)
    return [i for i in INSTALACIONES if i in out]


def con_cadena(nombre, cadena):
    n = limpio(nombre)
    base = sin_acentos(cadena).lower().replace(" ", "")
    if base in sin_acentos(n).lower().replace(" ", ""):
        return n
    return f"{cadena} {n}".strip()


# ------------------------------------------------------------------ 1. Smart Fit
SF_DIAS = {"lun": "Mo", "mar": "Tu", "mie": "We", "jue": "Th", "vie": "Fr", "sab": "Sa", "dom": "Su", "fer": "PH"}


def sf_horario(sched):
    por_dia, ph = {}, ""
    for dia, lst in (sched or {}).items():
        c = SF_DIAS.get(sin_acentos(dia).lower()[:3])
        if not c:
            continue
        for item in lst or []:
            t = ((item or {}).get("table") or {}).get("time", "")
            m = re.fullmatch(r"\s*(\d{1,2})h(\d{2})?\s*-\s*(\d{1,2})h(\d{2})?\s*", t)
            if not m:
                continue
            r = rango(hhmm(m.group(1), m.group(2)), hhmm(m.group(3), m.group(4)))
            if not r:
                continue
            if c == "PH":
                ph = f"PH {r}"
            else:
                por_dia.setdefault(c, []).append(r)
    return osm_desde_dias(por_dia, ph) if por_dia else ""


def f_smartfit(cli, st):
    base = "https://www.smartfit.com.mx/gimnasios.json?page={}"
    out, vistos, pagina, total = [], set(), 1, None
    while pagina:
        d = cli.get(base.format(pagina)).json()
        total = d.get("locations_count", total)
        locs = d.get("locations") or []
        for x in locs:
            if x.get("id") in vistos:
                continue
            vistos.add(x.get("id"))
            if x.get("is_digital"):
                st["omitidos_digitales"] = st.get("omitidos_digitales", 0) + 1
                continue
            if not x.get("opened"):
                st["proximamente"] = st.get("proximamente", 0) + 1
                continue
            a = x.get("address") or {}
            pos = a.get("position") or {}
            l1 = limpio(a.get("first_line"))
            calle, col = (l1.rsplit(" - ", 1) + [""])[:2] if " - " in l1 else (l1, "")
            l2 = limpio(a.get("second_line"))  # "Cuernavaca, MOR - 62374"
            m = re.match(r"(.*),\s*([^,]+?)\s*-\s*(\d{4,5})?\s*$", l2)
            ciudad, edo, codigo = (m.group(1), m.group(2), m.group(3) or "") if m else (l2, "", "")
            if len(codigo) == 4:
                codigo = "0" + codigo
            precios = [p.get("original_price_no_format") for p in (x.get("prices") or {}).values() if isinstance(p, dict)]
            precios = [int(round(p)) for p in precios if isinstance(p, (int, float)) and p >= 100]
            url = f"https://www.smartfit.com.mx/gimnasios/{x.get('permalink')}" if x.get("permalink") else ""
            feats = [f.get("name", "") for f in (x.get("features") or []) + (x.get("facilities") or []) if isinstance(f, dict)]
            out.append(registro(
                fuente="smartfit", id_fuente=str(x.get("id")), nombre=con_cadena(x.get("name"), "Smart Fit"),
                lat=num(pos.get("latitude")), lng=num(pos.get("longitude")), calle=calle, colonia=col,
                ciudad=ciudad, estado=estado(edo), cp=codigo, url_fuente=url, horario_osm=sf_horario(x.get("schedules")),
                cadena="Smart Fit", instalaciones=instalaciones(feats),
                mensualidad_desde=min(precios) if precios else "", precio_fuente_url=url if precios else "",
                foto=x.get("picture_url") or "", estatus="abierto",
                tipo=", ".join(a.get("name", "") for a in x.get("activities") or [] if isinstance(a, dict))))
        pagina = d.get("next_page") if locs else None
        if pagina and pagina > 200:
            raise RuntimeError("demasiadas páginas")
    st["total_fuente"] = total
    return out


# ------------------------------------------------------------------ 2. Anytime Fitness
def f_anytime(cli, st):
    url = "https://clubs-api.anytimefitness.workers.dev/api/v2/clubs/search?search=MX"
    d = cli.get(url).json()
    if not d.get("success", True):
        raise RuntimeError("respuesta sin success")
    clubs = d.get("data") or []
    st["total_fuente"] = (d.get("pagination") or {}).get("total", len(clubs))
    out, estatus_cnt = [], {}
    for x in clubs:
        if not str(x.get("afNumber", "")).startswith("MX-"):
            continue
        try:
            s = json.loads(x.get("status") or "{}").get("description", "")
        except (ValueError, AttributeError):
            s = str(x.get("status") or "")
        es = {"open": "abierto", "coming soon": "próximamente", "pre-sale": "preventa"}.get(s.lower(), s.lower())
        estatus_cnt[es] = estatus_cnt.get(es, 0) + 1
        if es != "abierto":
            continue
        a2 = limpio(x.get("address2"))
        calle, col = limpio(x.get("address")), ""
        if re.match(r"(?i)(col\.?|colonia|fracc\.?|fraccionamiento|barrio|residencial)\s", a2):
            col = re.sub(r"(?i)^(col\.?|colonia)\s+", "", a2)
        elif a2:
            calle = f"{calle}, {a2}"
        nom, dif = limpio(x.get("name")), limpio(x.get("differentiator"))
        if estado(nom) or sin_acentos(nom).lower() in sin_acentos(dif).lower():
            nom = ""
        nombre = " ".join(p for p in [nom, dif] if p) or limpio(x.get("name"))
        if not col:
            mc = re.search(r"(?i)\b(?:col\.|colonia)\s+([^,#]+?)\s*(?:,|$)", calle)
            if mc:
                col = mc.group(1)
        ciudad = limpio(x.get("city"))
        if estado(x.get("stateProvince")) == "Ciudad de México":
            ciudad = "Ciudad de México"
        elif estado(ciudad) == "Estado de México":
            ciudad = ""
        out.append(registro(
            fuente="anytime", id_fuente=x.get("afNumber"), nombre=con_cadena(nombre, "Anytime Fitness"),
            lat=num(x.get("latitude")), lng=num(x.get("longitud") or x.get("longitude")), calle=calle, colonia=col,
            ciudad=ciudad, estado=estado(x.get("stateProvince")), cp=cp(calle), telefono=telefono(x.get("phoneNumber")),
            url_fuente=url, cadena="Anytime Fitness", estatus="abierto"))
    st["por_estatus"] = estatus_cnt
    return out


# ------------------------------------------------------------------ 3. Sports World
def sw_coords(x):
    lat, lng = num(x.get("latitud")), num(x.get("longitud"))
    if lat is not None and lng is not None and lat and lng:
        return lat, -abs(lng)  # la API omite el signo negativo de la longitud
    m = re.search(r"ll=(-?\d+\.\d+),\s*(-?\d+\.\d+)", x.get("waze") or "")
    if m:
        return float(m.group(1)), -abs(float(m.group(2)))
    m = re.search(r"!2d(-?\d+\.\d+)!3d(-?\d+\.\d+)", x.get("mapa") or "")
    if m:
        return float(m.group(2)), -abs(float(m.group(1)))
    return None, None


def sw_direccion(html_dir, municipio, edo):
    lineas = [l.strip(" ,.") for l in html_a_lineas(html_dir)]
    calle = lineas[0] if lineas else ""
    col = ""
    resto = lineas[1:]
    mun_k = sin_acentos(municipio or "").lower()
    con_col = [l for l in resto if re.match(r"(?i)col\.?\s|colonia\s", l)]
    if con_col:
        col = re.sub(r"(?i)^(col\.?|colonia)\s*", "", con_col[0])
    else:
        for l in resto:
            k = sin_acentos(l).lower()
            if estado(l) or (mun_k and k == mun_k) or re.fullmatch(r"(c\.?p\.?\s*)?\d{5}", k) or \
                    re.search(r"plaza|centro comercial|mall|espacio|torre|paseo|codigo|ciudad de mexico|edo\.", k):
                continue
            col = l
            break
    col = re.sub(r",?\s*(c\.?p\.?\s*)?\d{5}$", "", col, flags=re.I).strip(" ,")
    return calle, col, cp(html_dir or "")


def f_sportsworld(cli, st):
    base = "https://www.sportsworld.com.mx"
    rutas = []
    try:
        h = cli.get(base + "/clubes").text
        rutas = sorted(set(re.findall(r'<option value="((?:zona|estado|cdmx)/[^"]+)"', h)))
    except RuntimeError as e:
        st["aviso"] = f"no se pudo leer la lista de zonas: {e}"
    if not rutas:
        rutas = ["zona/1", "zona/2", "zona/3", "zona/5"] + [f"estado/{e}" for e in [
            "Aguascalientes", "Coahuila", "Estado de México", "Guanajuato", "Jalisco", "Nuevo León", "Puebla",
            "Querétaro", "Sinaloa", "Sonora", "Veracruz", "Yucatán"]]
    st["zonas"] = len(rutas)
    clubs, fallas = {}, []
    for ruta in rutas:
        try:
            d = cli.get(f"{base}/api/getClubsByAlcaldia/{requests.utils.quote(ruta)}").json()
        except (RuntimeError, ValueError) as e:
            fallas.append(f"{ruta}: {e}")
            continue
        for x in d if isinstance(d, list) else []:
            clubs.setdefault(x.get("id"), x)
    if fallas:
        st["zonas_con_error"] = fallas
    if fallas and len(fallas) == len(rutas):
        raise RuntimeError("todas las zonas fallaron")
    out, preventa, inactivos = [], 0, 0
    for x in clubs.values():
        if str(x.get("status", 1)) != "1":
            inactivos += 1
            continue
        if str(x.get("preventa") or "0") not in ("0", "", "None"):
            preventa += 1
            continue
        lat, lng = sw_coords(x)
        edo = estado(x.get("estado")) or estado(x.get("ubicacion"))
        calle, col, codigo = sw_direccion(x.get("direccion"), x.get("municipio"), edo)
        mun = limpio(x.get("municipio") or x.get("locacion"))
        if re.search(r"(?i)plaza|centro comercial|mall", mun):
            mun = ""
        ciudad = "Ciudad de México" if edo == "Ciudad de México" else mun
        inst_raw = html_a_lineas((x.get("instalaciones_01") or "") + "<br>" + (x.get("instalaciones_02") or ""))
        inst_mapeo = [n.replace("Zona Intenz", "Zona funcional") for n in inst_raw]
        tag = x.get("tag") or ""
        out.append(registro(
            fuente="sportsworld", id_fuente=str(x.get("id_sw") or x.get("id")), nombre=con_cadena(x.get("club_title") or x.get("club"), "Sports World"),
            lat=lat, lng=lng, calle=calle, colonia=col, ciudad=ciudad, estado=edo, cp=codigo,
            telefono=telefono(x.get("telefono")), url_fuente=f"{base}/clubes/{tag}" if tag else f"{base}/clubes",
            horario_osm=osm_desde_texto_es(" ".join(html_a_lineas(x.get("horarios")))), cadena="Sports World",
            instalaciones=instalaciones(inst_mapeo), estatus="abierto", tipo=", ".join(inst_raw)))
    st["preventa"], st["inactivos"], st["total_fuente"] = preventa, inactivos, len(clubs)
    return out


# ------------------------------------------------------------------ 4. Sport City
def sc_direccion(texto):
    t = limpio(re.sub(r"^[^:]{0,60}:\s*", "", limpio(texto)))
    codigo = cp(t)
    partes = [p.strip(" .") for p in t.split(",") if p.strip(" .")]
    calle, col, ciudad, edo = t, "", "", ""
    if partes:
        edo = estado(partes[-1])
    idx = next((i for i, p in enumerate(partes) if re.fullmatch(r"(c\.?p\.?\s*)?\d{5}", p, re.I)), None)
    if idx is not None and idx >= 1:
        antes, despues = partes[:idx], partes[idx + 1:]
        mun = ""
        if len(antes) >= 3:
            calle, col, mun = ", ".join(antes[:-2]), antes[-2], antes[-1]
        elif len(antes) == 2:
            calle, col = antes
        else:
            calle = antes[0]
        if edo == "Ciudad de México":
            ciudad = "Ciudad de México"
        elif len(despues) >= 2:
            ciudad = despues[0]
        else:
            ciudad = mun
    else:
        m = re.search(r"(?i)\bcol\.?\s+(.+?)\s+c\.?p\.?", t)
        if m:
            col = m.group(1)
            calle = t[:m.start()].strip(" ,")
        if re.search(r"(?i)cdmx|ciudad de m[eé]xico", t):
            edo, ciudad = "Ciudad de México", "Ciudad de México"
    return calle, col, ciudad, edo, codigo


def f_sportcity(cli, st):
    url = "https://sportcity.com.mx/clubes"
    hdr = {"X-OCTOBER-REQUEST-HANDLER": "onFilterItem", "X-Requested-With": "XMLHttpRequest"}
    items, pagina, ultima = [], 1, 1
    while pagina <= ultima:
        d = cli.post(url, headers=hdr, data={"category": "all", "page": pagina}).json()
        if not d.get("success"):
            raise RuntimeError(f"página {pagina} sin success")
        data = d.get("data") or {}
        items += data.get("items") or []
        pag = data.get("pagination") or {}
        ultima = int(pag.get("last_page") or 1)
        st["total_fuente"] = pag.get("total")
        pagina += 1
        if pagina > 50:
            break
    out = []
    for x in items:
        f = x.get("dynamic_fields") or {}
        calle, col, ciudad, edo, codigo = sc_direccion(f.get("direccion"))
        if not edo:
            cats = [c.get("name", "") for c in x.get("categories") or []]
            edo = next((estado(c) for c in cats if estado(c)), "")
        tel = re.sub(r"^[^:]{0,60}:", "", limpio(f.get("telefono")))
        caps = [i.get("caption", "") for i in f.get("instalaciones") or [] if isinstance(i, dict)]
        img = (x.get("main_image") or x.get("featured_image") or {}).get("url", "")
        out.append(registro(
            fuente="sportcity", id_fuente=str(x.get("id")), nombre=con_cadena(x.get("name"), "Sport City"),
            lat=num(f.get("latitud")), lng=num(f.get("longitud")), calle=calle, colonia=col, ciudad=ciudad,
            estado=edo, cp=codigo, telefono=telefono(tel), url_fuente=x.get("url") or url,
            horario_osm=osm_desde_texto_es(re.sub(r"^[^:]{0,60}:", "", limpio(f.get("horario")))),
            cadena="Sport City", instalaciones=instalaciones(caps), foto=img, estatus="abierto",
            tipo=limpio(f.get("tipoclub"))))
    return out


# ------------------------------------------------------------------ 5. CrossFit
def f_crossfit(cli, st):
    api = "https://c3po.crossfit.com/api/affiliates/v2/affiliates"
    lista, pagina = [], 1
    while True:
        r = cli.get(f"{api}?country_code=MX&per_page=500&page={pagina}")
        d = r.json()
        lista += d if isinstance(d, list) else []
        if pagina >= int(r.headers.get("x-page-count") or 1) or not d:
            break
        pagina += 1
    st["total_fuente"] = len(lista)
    out, sin_detalle = [], 0
    for x in lista:
        if x.get("country_short_code", "MX") != "MX":
            continue
        try:
            det = cli.get(f"{api}/{x.get('id')}?detail=full", ok404=True)
            det = det.json() if det is not None else {}
        except (RuntimeError, ValueError):
            det, sin_detalle = {}, sin_detalle + 1
        lat = lng = None
        if det.get("is_lat_lng_pinned"):
            lat, lng = num(det.get("lat")), num(det.get("lng"))
        if lat is None or lng is None:
            ll = str(x.get("latlon") or det.get("coordinates") or "").split(",")
            if len(ll) == 2:
                lat, lng = num(ll[0]), num(ll[1])
        pub = (det.get("settings") or {})
        tel = telefono(det.get("contact_phone")) if (pub.get("contact_phone") or {}).get("is_public") else ""
        foto = x.get("photo") or ""
        if "affiliate-avatar" in foto or "default" in foto:
            foto = ""
        calle = ", ".join(p for p in [det.get("address_1") or x.get("address"), det.get("address_2")] if p)
        out.append(registro(
            fuente="crossfit", id_fuente=str(x.get("id")), nombre=x.get("name"), lat=lat, lng=lng, calle=calle,
            ciudad=titulo_ciudad(x.get("city")), estado=estado((det.get("state_slug") or "").replace("-", " ")) or estado(det.get("state_code")),
            cp=x.get("postal_code") or det.get("postal_code") or "", telefono=tel, sitio_web=web(x.get("website") or det.get("web")),
            url_fuente=f"https://www.crossfit.com/map/affiliate/{x.get('id')}", afiliaciones=["CrossFit"], foto=foto,
            estatus="abierto", tipo=det.get("org_type") or ""))
    if sin_detalle:
        st["sin_detalle"] = sin_detalle
    return out


# ------------------------------------------------------------------ 6. HYROX
MEXICO = [  # contorno aproximado (lng, lat); incluye el golfo de California
    (-117.12, 32.53), (-114.72, 32.72), (-111.07, 31.33), (-108.21, 31.33), (-108.21, 31.78), (-106.5, 31.78),
    (-104.9, 30.6), (-104.5, 29.6), (-103.3, 29.0), (-102.4, 29.8), (-101.4, 29.77), (-100.3, 28.3), (-99.5, 27.5),
    (-99.1, 26.4), (-97.15, 25.95), (-97.4, 25.0), (-97.7, 22.0), (-97.2, 20.6), (-96.1, 19.1), (-94.5, 18.15),
    (-92.0, 18.6), (-90.7, 19.4), (-90.4, 20.9), (-90.0, 21.3), (-88.0, 21.6), (-86.8, 21.5), (-86.8, 20.0),
    (-87.5, 18.4), (-88.2, 18.5), (-89.15, 17.9), (-90.98, 17.82), (-90.98, 17.25), (-91.4, 17.25), (-90.4, 16.1),
    (-91.7, 16.07), (-92.2, 14.53), (-93.5, 15.6), (-94.8, 16.2), (-96.5, 15.65), (-98.5, 16.3), (-100.0, 16.9),
    (-101.6, 17.65), (-103.5, 18.3), (-104.9, 19.3), (-105.7, 20.4), (-105.3, 21.6), (-106.0, 22.8), (-107.5, 24.5),
    (-109.0, 25.8), (-109.9, 22.9), (-112.1, 24.8), (-114.1, 27.7), (-115.9, 30.4)]


def en_mexico(lat, lng):
    dentro, n = False, len(MEXICO)
    for i in range(n):
        x1, y1 = MEXICO[i]
        x2, y2 = MEXICO[(i + 1) % n]
        if (y1 > lat) != (y2 > lat) and lng < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def cuadricula(sep_km=140, radio_km=100):
    celdas = []
    paso_lat = sep_km / 111.0
    lat = 14.5
    while lat <= 32.7 + 1e-9:
        paso_lng = sep_km / (111.32 * math.cos(math.radians(lat)))
        lng = -117.2
        while lng <= -86.7 + 1e-9:
            # conserva la celda si el centro o algún punto a ~0.8 radio cae dentro del contorno
            pts = [(lat, lng)] + [(lat + 0.8 * radio_km / 111 * math.sin(a), lng + 0.8 * radio_km / (111.32 * math.cos(math.radians(lat))) * math.cos(a))
                                  for a in [k * math.pi / 4 for k in range(8)]]
            if any(en_mexico(a, b) for a, b in pts):
                celdas.append((round(lat, 4), round(lng, 4)))
            lng += paso_lng
        lat += paso_lat
    return celdas


def f_hyrox(cli, st):
    api = "https://onefiit-api.platform.onefiit.com/hyrox365/v1/gyms/map"
    gyms, truncadas = {}, 0

    def consulta(lat, lng, radio_m, nivel=0):
        nonlocal truncadas
        d = cli.get(api, params={"latitude": lat, "longitude": lng, "radiusMeters": int(radio_m), "limit": 1000}).json()
        for g in d.get("gyms") or []:
            gyms.setdefault(g.get("hyroxEntityId"), g)
        if d.get("truncated"):
            truncadas += 1
            if nivel < 3:  # subdivide en 4 círculos más pequeños
                dlat = radio_m / 2 / 111000
                dlng = radio_m / 2 / (111320 * math.cos(math.radians(lat)))
                for a, b in [(dlat, dlng), (dlat, -dlng), (-dlat, dlng), (-dlat, -dlng)]:
                    consulta(lat + a, lng + b, radio_m * 0.71, nivel + 1)

    celdas = cuadricula()
    st["celdas"] = len(celdas)
    for lat, lng in celdas:
        consulta(lat, lng, 100000)
    st["truncadas"] = truncadas
    st["total_fuente"] = len(gyms)
    out, otros = [], 0
    for g in gyms.values():
        a = g.get("address") or {}
        if (a.get("country") or "").upper() != "MX":
            otros += 1
            continue
        geo = g.get("geoCoordinates") or {}
        cd = a.get("contactDetails") or {}
        img = (g.get("bannerImage") or g.get("cardImage") or {}) or {}
        out.append(registro(
            fuente="hyrox", id_fuente=g.get("hyroxEntityId"), nombre=g.get("gymName"), lat=num(geo.get("lat")),
            lng=num(geo.get("lon")), calle=a.get("street"), ciudad=titulo_ciudad(a.get("city")),
            estado=estado(a.get("state") or a.get("region") or ""), cp=a.get("postalCode") or "",
            telefono=telefono(cd.get("phone")), sitio_web=web(cd.get("website") or ""),
            url_fuente="https://hyrox365.com/", afiliaciones=["HYROX"],
            foto=img.get("url", "") if isinstance(img, dict) else "", estatus="abierto",
            tipo="HYROX Training Club" + (" (HTCX)" if g.get("htcx") else "")))
    st["fuera_de_mexico"] = otros
    return out


# ------------------------------------------------------------------ 7. TotalPass
def tp_slugs(cli):
    raiz = "https://totalpass.com/mx/sitemap.xml"
    pendientes, vistos, urls = [raiz], set(), set()
    while pendientes:
        u = pendientes.pop()
        if u in vistos or len(vistos) > 50:
            continue
        vistos.add(u)
        x = cli.get(u).text
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", x)
        if "<sitemapindex" in x:
            pendientes += [l for l in locs if "totalpass.com/mx" in l]
        else:
            urls |= {l for l in locs if "/mx/gimnasios/" in l}
    slugs = {}
    for u in urls:
        m = re.search(r"/mx/gimnasios/([^/?#]+)/?$", u)
        if m:
            slugs[m.group(1)] = u
    return slugs


def tp_flight(h):
    partes = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', h):
        try:
            partes.append(json.loads(m.group(1)))
        except ValueError:
            pass
    return "".join(partes)


def tp_json_linea(flight, marcador):
    for linea in flight.split("\n"):
        if marcador in linea:
            i = linea.find("[")
            try:
                return json.loads(linea[i:])
            except ValueError:
                continue
    return None


def tp_parse(h, slug, url):
    ld = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', h, re.S):
        try:
            j = json.loads(m.group(1))
        except ValueError:
            continue
        if isinstance(j, dict) and j.get("@type") in ("LocalBusiness", "SportsActivityLocation", "ExerciseGym"):
            ld = j
            break
    fl = tp_flight(h)
    gym = {}
    arr = tp_json_linea(fl, '"type":"gym","attributes"')
    if isinstance(arr, list) and len(arr) >= 4 and isinstance(arr[3], dict):
        gym = (arr[3].get("data") or {})
    at = gym.get("attributes") or {}
    mods = []
    m = re.search(r'"modalities":(\[\{"id":"\d+","type":"modality".*?\}\}\])\}', fl)
    if m:
        try:
            mods = [x["attributes"].get("translated_name") or x["attributes"].get("name") or x["attributes"].get("title")
                    for x in json.loads(m.group(1))]
        except (ValueError, KeyError, TypeError):
            mods = []
    if not mods:
        mods = re.findall(r'"type":"modality","attributes":\{"title":"[^"]*","name":"[^"]*","translated_name":"([^"]*)"', fl)
    mods = list(dict.fromkeys(x[:1].upper() + x[1:] for x in mods if x and "_" not in x))
    adr = at.get("address") or {}
    lad = ld.get("address") or {}
    geo = ld.get("geo") or {}
    loc = at.get("location") or {}
    lat = num(geo.get("latitude")) if geo else None
    lng = num(geo.get("longitude")) if geo else None
    if lat is None or lng is None:
        lat, lng = num(loc.get("lat")), num(loc.get("lng"))
    horario = osm_desde_open_close(ld.get("openingHours")) or osm_desde_open_close(at.get("business_hours"))
    calle = adr.get("street") or ""
    full = at.get("full_address") or lad.get("streetAddress") or ""
    if calle:
        # el número suele venir después de la calle en full_address: "Prol Guerrero, 3464, Interior A, Guerrero, ..."
        mm = re.match(re.escape(calle) + r"\s*,\s*([^,]*\d[^,]*)(?:,\s*(Interior[^,]*|Int\.?[^,]*))?", full)
        if mm:
            calle = calle + " " + mm.group(1) + (", " + mm.group(2) if mm.group(2) else "")
    else:
        calle = full
    es = "abierto"
    if at.get("closed") or at.get("active") is False:
        es = "cerrado"
    planes = [p.get("name") for p in at.get("accessible_on_plans") or [] if isinstance(p, dict)]
    return registro(
        fuente="totalpass", id_fuente=slug, nombre=at.get("name") or ld.get("name"), lat=lat, lng=lng, calle=calle,
        colonia=adr.get("neighborhood") or "", ciudad=titulo_ciudad(adr.get("city") or lad.get("addressLocality")),
        estado=estado(adr.get("state") or lad.get("addressRegion")), cp=(adr.get("zip_code") or lad.get("postalCode") or "").strip(),
        telefono=telefono(at.get("phone") or ld.get("telephone")), sitio_web=web(at.get("website")), url_fuente=url,
        horario_osm=horario, pases=["TotalPass"],
        instalaciones=instalaciones((at.get("structures") or []) + [x for x in mods if re.search(r"(?i)peso libre|nataci|sauna|vapor", x)]),
        foto=at.get("main_image_url") or ld.get("image") or "", estatus=es, tipo=", ".join(mods)), \
        {"tipo_tp": at.get("type"), "planes": planes, "estructuras": at.get("structures") or []}


def f_totalpass(cli, st, max_tp=TP_MAX_DEFAULT, hilos=4):
    ruta_cache = os.path.join(DIR, "totalpass_cache.json")
    ruta_jsonl = os.path.join(DIR, "totalpass.jsonl")
    cache = cargar_json(ruta_cache, {})
    previos = {}
    if os.path.exists(ruta_jsonl):
        with open(ruta_jsonl, encoding="utf-8") as f:
            for linea in f:
                try:
                    r = json.loads(linea)
                    previos[r["id_fuente"]] = r
                except (ValueError, KeyError):
                    pass
    slugs = tp_slugs(cli)
    if len(slugs) < 1000:
        raise RuntimeError(f"el sitemap trajo solo {len(slugs)} gimnasios; no se actualiza")
    st["urls_sitemap"] = len(slugs)
    hoy = dt.date.today()
    limite = (hoy - dt.timedelta(days=TP_DIAS_REFRESCO)).isoformat()
    nuevos = sorted(s for s in slugs if s not in cache)
    viejos = sorted((s for s in slugs if s in cache and cache[s] < limite), key=lambda s: cache[s])
    cola = nuevos + viejos
    if max_tp and max_tp > 0:
        cola = cola[:max_tp]
    st["pendientes_nuevos"], st["pendientes_viejos"], st["leidas_esta_corrida"] = len(nuevos), len(viejos), len(cola)
    tlocal = threading.local()
    lock = threading.Lock()
    leidos, errores, no_existe, otros_tipos, clientes = {}, [], 0, 0, []

    def trabajo(slug):
        nonlocal no_existe, otros_tipos
        if not hasattr(tlocal, "cli"):
            tlocal.cli = Cliente(pausa=1.0)  # cada hilo ~1 petición por segundo
            with lock:
                clientes.append(tlocal.cli)
        url = slugs[slug]
        try:
            r = tlocal.cli.get(url, ok404=True)
            if r is None:
                with lock:
                    no_existe += 1
                    cache[slug] = hoy.isoformat()
                return
            reg, extra = tp_parse(r.text, slug, url)
            with lock:
                if extra.get("tipo_tp") and extra["tipo_tp"] != "Gym::Presential" and not reg["lat"]:
                    otros_tipos += 1
                leidos[slug] = reg
                cache[slug] = hoy.isoformat()
        except Exception as e:  # noqa: BLE001 — una página mala no detiene la fuente
            with lock:
                errores.append(f"{slug}: {e}")

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=hilos) as ex:
        for i, _ in enumerate(ex.map(trabajo, cola), 1):
            if i % 250 == 0:
                print(f"  totalpass: {i}/{len(cola)} ({time.time() - t0:.0f}s)", flush=True)
    cli.peticiones += sum(c.peticiones for c in clientes)
    st["errores_pagina"] = len(errores)
    if errores:
        st["errores_ejemplo"] = errores[:5]
    st["404"] = no_existe
    if cola and len(errores) > 0.5 * len(cola):
        raise RuntimeError(f"{len(errores)} de {len(cola)} páginas fallaron: {errores[:3]}")
    todos = {k: v for k, v in previos.items() if k in slugs}
    st["retirados_del_sitemap"] = len(set(previos) - set(slugs))
    todos.update(leidos)
    for s in list(cache):
        if s not in slugs:
            del cache[s]
    guardar_json(ruta_cache, cache)
    st["cobertura_cache"] = f"{sum(1 for s in slugs if s in cache)}/{len(slugs)}"
    return list(todos.values()), {"descartar_validacion_en_previos": True}


# ------------------------------------------------------------------ 8. Fitpass
# etiqueta de ciudad de Fitpass → (ciudad, estado). En CDMX el estado queda vacío: la zona incluye municipios del Edomex.
FP_CIUDADES = {
    "ACAPULCO": ("Acapulco", "Guerrero"), "CANCUN": ("Cancún", "Quintana Roo"), "CDMX": ("Ciudad de México", ""),
    "CUERNAVACA": ("Cuernavaca", "Morelos"), "GDL": ("Guadalajara", "Jalisco"), "LEON": ("León", "Guanajuato"),
    "LOS CABOS": ("Los Cabos", "Baja California Sur"), "MAZATLAN": ("Mazatlán", "Sinaloa"), "MERIDA": ("Mérida", "Yucatán"),
    "MONTERREY": ("Monterrey", "Nuevo León"), "PLAYA DEL CARMEN": ("Playa del Carmen", "Quintana Roo"),
    "PUEBLA": ("Puebla", "Puebla"), "PUERTO VALLARTA": ("Puerto Vallarta", "Jalisco"), "QUERETARO": ("Querétaro", "Querétaro"),
    "SAN LUIS POTOSI": ("San Luis Potosí", "San Luis Potosí"), "SAN MIGUEL DE ALLENDE": ("San Miguel de Allende", "Guanajuato"),
    "TIJUANA": ("Tijuana", "Baja California"), "TOLUCA": ("Toluca", "Estado de México"),
}

def f_fitpass(cli, st, hilos=4):
    base = "https://www.fitpass.com"
    h = cli.get(base + "/mx/mapa").text  # deja la cookie de sesión en cli.s
    ciudades = {}
    m = re.search(r'<select[^>]*name="city_id"[^>]*>(.*?)</select>', h, re.S)
    if m:
        for v, n in re.findall(r'<option[^>]*value="(\d+)"[^>]*>([^<]+)', m.group(1)):
            ciudades[v] = limpio(n)
    if not ciudades:
        ciudades = {str(i): "" for i in range(1, 54)}
        st["aviso"] = "no se encontró la lista de ciudades; se prueban ids 1..53"
    st["ciudades"] = len(ciudades)
    cookies = cli.s.cookies.copy()
    tlocal = threading.local()
    lock = threading.Lock()
    gyms, fallas, por_ciudad, clientes = {}, [], {}, []

    def trabajo(item):
        cid, cname = item
        if not hasattr(tlocal, "cli"):
            tlocal.cli = Cliente(pausa=1.0)
            tlocal.cli.s.cookies.update(cookies)
            with lock:
                clientes.append(tlocal.cli)
        url = f"{base}/map/search"
        params = {"utf8": "✓", "country": "mx", "name": "", "city_id": cid, "activity_id": "", "plan": ""}
        try:
            r = tlocal.cli.get(url, params=params, headers={"Turbo-Frame": "map_results", "Referer": base + "/mx/mapa"})
        except RuntimeError as e:
            with lock:
                fallas.append(f"{cid}: {e}")
            return
        txt = r.text
        bloques = re.split(r'(?=<div class="list-group-item)', txt)
        n = 0
        for b in bloques:
            if "data-gym-id" not in b:
                continue
            attrs = dict(re.findall(r'data-gym-([a-z-]+)="([^"]*)"', b))
            acts = re.search(r'<span class="text-uppercase">\s*(.*?)\s*</span>', b, re.S)
            attrs["actividades"] = limpio(acts.group(1)) if acts else ""
            attrs["ciudad"] = cname
            n += 1
            with lock:
                gyms.setdefault(attrs.get("id"), attrs)
        with lock:
            por_ciudad[cname or cid] = n

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        list(ex.map(trabajo, ciudades.items()))
    cli.peticiones += sum(c.peticiones for c in clientes)
    if fallas:
        st["ciudades_con_error"] = fallas
    if fallas and len(fallas) == len(ciudades):
        raise RuntimeError("todas las ciudades fallaron")
    st["por_ciudad"] = por_ciudad
    st["total_fuente"] = len(gyms)
    out, virtuales = [], 0
    for g in gyms.values():
        if g.get("virtual") == "true":
            virtuales += 1
            continue
        tipo = g.get("type") or ("pro" if g.get("pro") == "true" else "basic")
        if g.get("actividades"):
            tipo = f"{tipo} · {g['actividades'][:1].upper() + g['actividades'][1:].lower()}"
        out.append(registro(
            fuente="fitpass", id_fuente=g.get("id"), nombre=g.get("name"), lat=num(g.get("latitude")),
            lng=num(g.get("longitude")), calle=g.get("address"), ciudad=FP_CIUDADES.get(g.get("ciudad"), ("", ""))[0] or titulo_ciudad(g.get("ciudad")),
            estado=FP_CIUDADES.get(g.get("ciudad"), ("", ""))[1],
            url_fuente=base + "/mx/mapa", pases=["Fitpass"], estatus="abierto", tipo=tipo))
    st["virtuales"] = virtuales
    return out


# ------------------------------------------------------------------ validación, escritura y resumen
def valido(r):
    if not r.get("nombre"):
        return False
    lat, lng = r.get("lat"), r.get("lng")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return False
    return 14 <= lat <= 33 and -118 <= lng <= -86


def cargar_json(ruta, defecto):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return defecto


def guardar_json(ruta, obj):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ruta)


def escribir_jsonl(ruta, regs):
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in regs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, ruta)


def llenado(regs):
    if not regs:
        return {}
    out = {}
    for c in CAMPOS:
        n = sum(1 for r in regs if r.get(c) not in ("", [], None))
        out[c] = round(100 * n / len(regs))
    return out


def correr(nombre, cli, args):
    st = {}
    t0 = time.time()
    if nombre == "totalpass":
        regs, _ = f_totalpass(cli, st, max_tp=args.max_tp)
    else:
        regs = globals()[f"f_{nombre}"](cli, st)
    buenos, malos, vistos = [], 0, set()
    for r in regs:
        r["lat"] = round(r["lat"], 7) if isinstance(r.get("lat"), float) else r.get("lat")
        r["lng"] = round(r["lng"], 7) if isinstance(r.get("lng"), float) else r.get("lng")
        if not valido(r) or r["id_fuente"] in vistos:
            malos += 1
            continue
        vistos.add(r["id_fuente"])
        buenos.append(r)
    if not buenos:
        raise RuntimeError("0 registros válidos; se conserva el archivo anterior")
    buenos.sort(key=lambda r: (r["estado"], r["ciudad"], r["nombre"]))
    escribir_jsonl(os.path.join(DIR, f"{nombre}.jsonl"), buenos)
    st.update({"ok": True, "exportados": len(buenos), "descartados": malos, "segundos": round(time.time() - t0, 1),
               "peticiones": cli.peticiones, "llenado_pct": llenado(buenos)})
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--solo", default="", help="fuentes separadas por coma (default: todas)")
    ap.add_argument("--max-tp", type=int, default=TP_MAX_DEFAULT,
                    help=f"máximo de páginas de TotalPass a leer en esta corrida (default {TP_MAX_DEFAULT}; 0 = sin límite)")
    ap.add_argument("--estricto", action="store_true", help="sale con código 1 si alguna fuente falla")
    args = ap.parse_args()
    pedidas = [s.strip().lower() for s in args.solo.split(",") if s.strip()] or FUENTES
    desconocidas = [s for s in pedidas if s not in FUENTES]
    if desconocidas:
        ap.error(f"fuentes desconocidas: {', '.join(desconocidas)} (válidas: {', '.join(FUENTES)})")
    os.makedirs(DIR, exist_ok=True)
    ruta_res = os.path.join(DIR, "resumen.json")
    resumen = cargar_json(ruta_res, {})
    resumen.setdefault("fuentes", {})
    ahora = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    fallidas = []
    for nombre in pedidas:
        print(f"== {nombre}", flush=True)
        t0 = time.time()
        cli = Cliente(pausa=1.0)
        try:
            st = correr(nombre, cli, args)
            print(f"   {st['exportados']} exportados, {st['descartados']} descartados, {st['segundos']}s", flush=True)
        except Exception as e:  # noqa: BLE001 — falla visible, se sigue con las demás
            st = {"ok": False, "error": f"{e.__class__.__name__}: {e}", "segundos": round(time.time() - t0, 1),
                  "peticiones": cli.peticiones}
            prev = resumen["fuentes"].get(nombre) or {}
            if prev.get("ok"):
                st["ultimo_ok"] = prev.get("fecha")
                st["exportados_ultimo_ok"] = prev.get("exportados")
            elif prev.get("ultimo_ok"):
                st["ultimo_ok"], st["exportados_ultimo_ok"] = prev.get("ultimo_ok"), prev.get("exportados_ultimo_ok")
            fallidas.append(nombre)
            print(f"::error title=fuentes {nombre}::{st['error']}", flush=True)
        st["fecha"] = ahora
        resumen["fuentes"][nombre] = st
        resumen["actualizado"] = ahora
        guardar_json(ruta_res, resumen)
    resumen["ultima_corrida"] = {"fecha": ahora, "fuentes": pedidas, "fallidas": fallidas}
    guardar_json(ruta_res, resumen)
    print(f"resumen: {ruta_res}" + (f" · fallaron: {', '.join(fallidas)}" if fallidas else ""))
    if fallidas and args.estricto:
        sys.exit(1)


if __name__ == "__main__":
    main()
