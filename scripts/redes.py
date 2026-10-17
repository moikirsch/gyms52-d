# -*- coding: utf-8 -*-
"""Lee el sitio web de cada ficha y saca Instagram, Facebook, TikTok, WhatsApp y correo.

Uso: python redes.py --metros 1 --max 3000
- Si el "sitio web" es en realidad un perfil de Instagram/Facebook/TikTok, lo mueve a su campo.
- Solo visita fichas con sitio y sin `redes_el`. Marca `pendiente_sync=1` donde algo cambió.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
from urllib.parse import urlparse

import pandas as pd
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
NO_PERFIL = {"sharer", "share", "intent", "dialog", "plugins", "tr", "p", "reel", "explore", "accounts", "watch",
             "hashtag", "events", "groups", "login", "privacy", "policies", "help", "legal", "about", "home.php"}
RE_IG = re.compile(r"https?://(?:www\.)?instagram\.com/([A-Za-z0-9_.]{2,30})/?", re.I)
RE_FB = re.compile(r"https?://(?:www\.|m\.|es-la\.)?facebook\.com/(?:pg/)?([A-Za-z0-9_.\-]{3,80})/?", re.I)
RE_TT = re.compile(r"https?://(?:www\.)?tiktok\.com/@([A-Za-z0-9_.]{2,30})", re.I)
RE_WA = re.compile(r"(?:wa\.me/|api\.whatsapp\.com/send/?\?phone=|whatsapp\.com/send\?phone=)\+?(\d{10,13})", re.I)
RE_MAIL = re.compile(r"mailto:([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[a-z]{2,})", re.I)


def perfil(regex, texto, base_url):
    for m in regex.finditer(texto):
        h = m.group(1).strip("/.")
        if h.lower() not in NO_PERFIL and not h.lower().startswith(("profile.php", "pages")):
            return base_url + h
    return ""


def extraer(texto):
    wa = RE_WA.search(texto)
    mail = RE_MAIL.search(texto)
    num = wa.group(1) if wa else ""
    if num.startswith("52") and len(num) == 12:
        num = num[2:]
    if num.startswith("521") and len(num) == 13:
        num = num[3:]
    return {
        "instagram": perfil(RE_IG, texto, "https://www.instagram.com/"),
        "facebook": perfil(RE_FB, texto, "https://www.facebook.com/"),
        "tiktok": perfil(RE_TT, texto, "https://www.tiktok.com/@"),
        "whatsapp": num,
        "correo": mail.group(1).lower() if mail and not mail.group(1).lower().endswith((".png", ".jpg")) else "",
    }


def visitar(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": UA, "Accept-Language": "es-MX,es"}, allow_redirects=True)
        if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
            return None
        return r.text[:600000]
    except requests.RequestException:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metros", default="")
    ap.add_argument("--max", type=int, default=3000)
    a = ap.parse_args()
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    for c in ("instagram", "facebook", "tiktok", "whatsapp", "redes_el", "pendiente_sync"):
        if c not in base.columns:
            base[c] = ""
    hoy = dt.date.today().isoformat()

    # 1) sitios que en realidad son redes sociales
    movidos = 0
    for i, r in base.iterrows():
        host = urlparse(r.sitio_web).netloc.lower()
        for red, dominio in (("instagram", "instagram.com"), ("facebook", "facebook.com"), ("tiktok", "tiktok.com")):
            if dominio in host:
                if not r[red]:
                    base.at[i, red] = r.sitio_web.split("?")[0]
                base.at[i, "sitio_web"] = ""
                base.at[i, "pendiente_sync"] = "1"
                movidos += 1

    # 2) leer sitios propios
    filtro = (base.sitio_web != "") & (base.redes_el == "")
    if a.metros:
        filtro &= base.metro_rango.isin([x.strip() for x in a.metros.split(",")])
    objetivo = list(base[filtro].head(a.max).index)
    leidos = cambios = 0
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for i, html in zip(objetivo, ex.map(lambda k: visitar(base.at[k, "sitio_web"]), objetivo)):
            base.at[i, "redes_el"] = hoy
            if not html:
                continue
            leidos += 1
            hubo = False
            for campo, valor in extraer(html).items():
                if valor and not base.at[i, campo]:
                    base.at[i, campo] = valor
                    hubo = True
            if hubo:
                base.at[i, "pendiente_sync"] = "1"
                cambios += 1
    base.to_csv(ruta, index=False)
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    json.dump({"perfiles_movidos": movidos, "sitios_visitados": len(objetivo), "sitios_leidos": leidos, "con_datos_nuevos": cambios},
              open(os.path.join(RAIZ, "data", "corridas", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-redes.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"Redes: {movidos} perfiles movidos desde 'sitio web', {leidos}/{len(objetivo)} sitios leídos, {cambios} con datos nuevos")


if __name__ == "__main__":
    main()
