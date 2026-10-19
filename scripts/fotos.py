# -*- coding: utf-8 -*-
"""Busca una foto del lugar en su propio sitio web y la deja lista para la ficha.

Uso: python fotos.py --max 1500
- Solo fichas publicadas, sin foto (`foto_el` vacío) y con sitio web propio.
- Candidatas: og:image, twitter:image y las imágenes grandes de la página principal.
- Filtro de calidad: horizontal (1.15 a 2.4), mínimo 600 x 350, sin "logo/icon" en el nombre,
  con detalle suficiente (entropía) y que no sea casi toda blanca. Ante la duda, no se usa.
- Guarda `foto_url` y marca `pendiente_sync=1`; publicar.py la manda a GeoDirectory, que la descarga.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import html as htmlmod
import io
import json
import math
import os
import re
from urllib.parse import urljoin, urlparse

import pandas as pd
import requests
from PIL import Image, ImageStat

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
REDES = ("instagram.com", "facebook.com", "tiktok.com", "wa.me", "whatsapp.com", "linktr.ee", "youtube.com")
MALAS = re.compile(r"logo|icon|favicon|sprite|placeholder|avatar|badge|flag|banner-app|whatsapp|payment|pago|visa|mastercard|"
                   r"promo|oferta|descuento|membres|precio|inscrip|cupon|black-?friday|buen-?fin|hot-?sale|maleta", re.I)
RE_META = re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\'][^>]*>', re.I)
RE_CONTENT = re.compile(r'content=["\']([^"\']+)["\']', re.I)
RE_IMG = re.compile(r'<img[^>]+>', re.I)
RE_SRC = re.compile(r'(?:data-src|data-lazy-src|src)=["\']([^"\']+\.(?:jpe?g|png|webp)(?:\?[^"\']*)?)["\']', re.I)


def candidatas(html, base):
    urls = []
    for m in RE_META.finditer(html):
        c = RE_CONTENT.search(m.group(0))
        if c:
            urls.append(urljoin(base, htmlmod.unescape(c.group(1).strip())))
    for m in RE_IMG.finditer(html):
        s = RE_SRC.search(m.group(0))
        if s:
            urls.append(urljoin(base, htmlmod.unescape(s.group(1).strip())))
    vistos, sal = set(), []
    for u in urls:
        if u.startswith("http") and u not in vistos and not MALAS.search(urlparse(u).path):
            vistos.add(u)
            sal.append(u)
    return sal[:8]


def entropia(img):
    h = img.convert("L").resize((256, 256)).histogram()
    t = sum(h)
    return -sum(c / t * math.log2(c / t) for c in h if c)


def evaluar(url):
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": UA})
        if r.status_code != 200 or len(r.content) < 25000:
            return None
        img = Image.open(io.BytesIO(r.content))
        img.load()
        w, h = img.size
        if w < 600 or h < 350 or not (1.15 <= w / h <= 2.4):
            return None
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        e = entropia(img)
        brillo = ImageStat.Stat(img.convert("L")).mean[0]
        if e < 6.2 or brillo > 232 or brillo < 18:
            return None
        return (e * min(w, 1600) * min(h, 1000), url)
    except Exception:
        return None


def buscar(sitio):
    try:
        r = requests.get(sitio, timeout=15, headers={"User-Agent": UA, "Accept-Language": "es-MX,es"}, allow_redirects=True)
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            return ""
        notas = [x for x in (evaluar(u) for u in candidatas(r.text[:800000], r.url)) if x]
        return max(notas)[1] if notas else ""
    except requests.RequestException:
        return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=1500)
    a = ap.parse_args()
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    for c in ("foto_url", "foto_el", "foto_subida", "pendiente_sync"):
        if c not in base.columns:
            base[c] = ""
    dominio = base.sitio_web.apply(lambda u: urlparse(u).netloc.lower().removeprefix("www.") if u else "")
    repetidos = {d for d, n in dominio.value_counts().items() if d and n >= 3}  # sitios de cadena: sus portadas son promociones
    propio = base.sitio_web.apply(lambda u: bool(u) and not any(d in u.lower() for d in REDES)) & ~dominio.isin(repetidos) & (base.cadena == "")
    objetivo = list(base[(base.wp_id != "") & (base.foto_el == "") & propio].head(a.max).index)
    hoy = dt.date.today().isoformat()
    con = 0
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for i, foto in zip(objetivo, ex.map(lambda k: buscar(base.at[k, "sitio_web"]), objetivo)):
            base.at[i, "foto_el"] = hoy
            if foto:
                base.at[i, "foto_url"] = foto
                base.at[i, "pendiente_sync"] = "1"
                con += 1
    base.to_csv(ruta, index=False)
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    json.dump({"revisadas": len(objetivo), "con_foto": con},
              open(os.path.join(RAIZ, "data", "corridas", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-fotos.json"), "w"))
    print(f"Fotos: {con} de {len(objetivo)} sitios con foto usable")


if __name__ == "__main__":
    main()
