# -*- coding: utf-8 -*-
"""Publica en gyms52.com los lugares de data/base.csv que aún no tienen wp_id.

Uso: python publicar.py --metros 1 --max 300 [--estado publish|draft]
Necesita WP_USER y WP_APP_PASSWORD (contraseña de aplicación). WP_URL es opcional.
"""
import argparse
import datetime as dt
import json
import os
import time

import pandas as pd
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def categorias(s, url):
    mapa, pagina = {}, 1
    while True:
        r = s.get(f"{url}/wp-json/geodir/v2/lugares/categories", params={"per_page": 100, "page": pagina}, timeout=60)
        r.raise_for_status()
        lote = r.json()
        for c in lote:
            mapa[c["name"]] = c["id"]
        if len(lote) < 100:
            return mapa
        pagina += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metros", default="", help="rangos separados por coma; vacío = todos")
    ap.add_argument("--max", type=int, default=300)
    ap.add_argument("--estado", default="publish")
    a = ap.parse_args()
    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    s.headers["User-Agent"] = "gyms52-pipeline/1.0"
    cats = categorias(s, url)
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    pendientes = base[base.wp_id == ""]
    if a.metros:
        pendientes = pendientes[pendientes.metro_rango.isin([x.strip() for x in a.metros.split(",")])]
    hoy = dt.date.today().isoformat()
    hechos, errores = 0, []
    for i, r in pendientes.head(a.max).iterrows():
        ids = [cats[d] for d in r.disciplinas.split("|") if d in cats]
        cuerpo = {
            "title": r.nombre, "content": r.descripcion, "status": a.estado,
            "post_category": ids, "default_category": ids[0] if ids else None,
            "street": r.calle, "city": r.ciudad, "region": r.estado, "country": "Mexico", "zip": r.cp,
            "latitude": r.lat, "longitude": r.lng,
            "tipo_lugar": r.tipo_lugar, "cadena": r.cadena, "telefono": r.telefono, "correo": r.correo,
            "sitio_web": r.sitio_web, "place_id": r.place_id, "denue_id": r.denue_id, "fuente": r.fuente,
            "ultima_verificacion": r.ultima_verificacion,
        }
        cuerpo = {k: v for k, v in cuerpo.items() if v not in ("", None, [])}
        try:
            resp = s.post(f"{url}/wp-json/geodir/v2/lugares", json=cuerpo, timeout=90)
            if resp.status_code in (200, 201):
                base.at[i, "wp_id"] = str(resp.json()["id"])
                base.at[i, "publicado_el"] = hoy
                hechos += 1
            else:
                errores.append(f"{r.nombre}: {resp.status_code} {resp.text[:160]}")
                if resp.status_code in (401, 403):
                    break
        except requests.RequestException as e:
            errores.append(f"{r.nombre}: {e}")
        if hechos and hechos % 25 == 0:
            base.to_csv(ruta, index=False)
        time.sleep(0.4)
    base.to_csv(ruta, index=False)
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    nombre = dt.datetime.utcnow().strftime("%Y%m%d-%H%M") + "-publicar.json"
    json.dump({"publicados": hechos, "pendientes_antes": len(pendientes), "errores": errores[:30]},
              open(os.path.join(RAIZ, "data", "corridas", nombre), "w"), ensure_ascii=False, indent=1)
    print(f"Publicados: {hechos} | errores: {len(errores)}")
    for e in errores[:10]:
        print("  ", e)


if __name__ == "__main__":
    main()
