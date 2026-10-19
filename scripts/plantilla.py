# -*- coding: utf-8 -*-
"""Lee o sube plantillas del tema en gyms52.com (editor de sitio de WordPress).

Lo maneja solicitudes/plantilla.json:
  {"accion": "leer", "plantillas": ["directory//gd-single"]}
    baja cada plantilla a data/plantillas/<slug>.html (con copia fechada en data/plantillas/respaldos/).
  {"accion": "subir", "plantillas": ["directory//gd-single"]}
    respalda la versión del sitio y sube data/plantillas/<slug>.html.
Necesita WP_USER y WP_APP_PASSWORD.
"""
import datetime as dt
import json
import os

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(RAIZ, "data", "plantillas")


def main():
    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    s.headers["User-Agent"] = "gyms52-pipeline/1.0"
    sol = json.load(open(os.path.join(RAIZ, "solicitudes", "plantilla.json")))
    accion = sol.get("accion", "leer")
    marca = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    os.makedirs(os.path.join(DIR, "respaldos"), exist_ok=True)
    for pid in sol.get("plantillas", []):
        slug = pid.split("//")[-1]
        r = s.get(f"{url}/wp-json/wp/v2/templates/{pid}", params={"context": "edit"}, timeout=60)
        r.raise_for_status()
        actual = r.json()["content"]["raw"]
        open(os.path.join(DIR, "respaldos", f"{slug}_{marca}.html"), "w").write(actual)
        if accion == "leer":
            open(os.path.join(DIR, f"{slug}.html"), "w").write(actual)
            print(f"{pid}: leída ({len(actual)} caracteres)")
            continue
        nueva = open(os.path.join(DIR, f"{slug}.html")).read()
        if nueva == actual:
            print(f"{pid}: sin cambios")
            continue
        r = s.post(f"{url}/wp-json/wp/v2/templates/{pid}", json={"content": nueva}, timeout=60)
        print(f"{pid}: subida HTTP {r.status_code} {r.text[:200] if r.status_code >= 300 else ''}")
        r.raise_for_status()


if __name__ == "__main__":
    main()
