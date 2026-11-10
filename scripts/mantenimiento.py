# -*- coding: utf-8 -*-
"""Tareas puntuales de mantenimiento en gyms52.com, manejadas por solicitudes/mantenimiento.json.

  {"info": true}
      guarda en data/mantenimiento/info.json los plugins y ajustes del sitio.
  {"borrador_paginas": [123, 456]}
      pasa páginas a borrador: dejan de verse y se pueden volver a publicar.
  {"plugins_activar": ["ninja-forms/ninja-forms"]}
      activa plugins instalados.
Cada corrida deja su bitácora en data/mantenimiento/<fecha>.json.
Necesita WP_USER y WP_APP_PASSWORD.
"""
import datetime as dt
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

    json.dump(log, open(os.path.join(DIR, f"{marca}.json"), "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
