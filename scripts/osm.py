# -*- coding: utf-8 -*-
"""Descarga de OpenStreetMap (Overpass) los gimnasios, estudios, deportivos y tiendas de cada metrópoli.

Uso: python osm.py --metros 1,2,3     (vacío = las de lanzamiento de config/diario.json)
Gratis y sin llave. El área de cada metrópoli sale de las coordenadas de DENUE (con margen).
Escribe data/osm/NNN-slug.jsonl, un lugar por línea con sus etiquetas.
"""
import argparse
import datetime as dt
import json
import os
import time

import pandas as pd
import requests

from comun import slug

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVIDORES = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
              "https://overpass.private.coffee/api/interpreter"]
DEPORTES = "fitness|crossfit|yoga|pilates|boxing|kickboxing|martial_arts|karate|taekwondo|judo|jiu-jitsu|mma|" \
           "climbing|bouldering|swimming|gymnastics|dance|aerobics|cycling|weightlifting|muay_thai|capoeira|parkour"
CONSULTA = """[out:json][timeout:180];
(
  nwr["leisure"="fitness_centre"]({b});
  nwr["leisure"="sports_centre"]({b});
  nwr["leisure"="sports_hall"]["name"]({b});
  nwr["amenity"="dojo"]({b});
  nwr["leisure"="dance"]["name"]({b});
  nwr["amenity"="dancing_school"]({b});
  nwr["sport"~"{d}"]["name"]["leisure"!="pitch"]({b});
  nwr["shop"="sports"]["name"]({b});
  nwr["shop"="nutrition_supplements"]["name"]({b});
);
out center tags;"""


def caja(denue, rango):
    d = denue[denue.metro_rango.astype(str) == str(rango)]
    lat = pd.to_numeric(d.latitud, errors="coerce").dropna()
    lng = pd.to_numeric(d.longitud, errors="coerce").dropna()
    if len(lat) < 5:
        return None
    s, n = lat.quantile(0.01) - 0.03, lat.quantile(0.99) + 0.03
    o, e = lng.quantile(0.01) - 0.03, lng.quantile(0.99) + 0.03
    return f"{s:.4f},{o:.4f},{n:.4f},{e:.4f}"


def overpass(q):
    ultimo = ""
    for intento in range(6):
        url = SERVIDORES[intento % len(SERVIDORES)]
        try:
            r = requests.post(url, data={"data": q}, timeout=240, headers={"User-Agent": "gyms52.com directorio (bot@gyms52.com)"})
            if r.status_code == 200:
                return r.json().get("elements", [])
            ultimo = f"{url}: {r.status_code}"
        except requests.RequestException as e:
            ultimo = f"{url}: {e.__class__.__name__}"
        time.sleep(20 * (intento + 1))
    raise RuntimeError("Overpass no respondió: " + ultimo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metros", default="")
    a = ap.parse_args()
    if a.metros:
        rangos = [x.strip() for x in a.metros.split(",") if x.strip()]
    else:
        n = json.load(open(os.path.join(RAIZ, "config", "diario.json"))).get("metros_lanzamiento", 10)
        rangos = [str(i) for i in range(1, n + 1)]
    metros = pd.read_csv(os.path.join(RAIZ, "config", "metros.csv"), dtype=str).set_index("rango")
    denue = pd.read_csv(os.path.join(RAIZ, "data", "denue", "gimnasios.csv"), dtype=str).fillna("")
    os.makedirs(os.path.join(RAIZ, "data", "osm"), exist_ok=True)
    resumen = {}
    for rango in rangos:
        nombre = metros.loc[rango, "metropoli"]
        b = caja(denue, rango)
        if not b:
            resumen[rango] = "sin área"
            continue
        try:
            elementos = overpass(CONSULTA.replace("{b}", b).replace("{d}", DEPORTES))
        except RuntimeError as e:
            resumen[rango] = str(e)
            print(e)
            continue
        ruta = os.path.join(RAIZ, "data", "osm", f"{int(rango):03d}-{slug(nombre)}.jsonl")
        n = 0
        with open(ruta, "w", encoding="utf-8") as f:
            for el in elementos:
                t = el.get("tags", {})
                c = el.get("center") or el
                if not t.get("name") or "lat" not in c:
                    continue
                f.write(json.dumps({"osm_id": f"{el['type']}/{el['id']}", "lat": c["lat"], "lng": c["lon"], "tags": t,
                                    "metro_rango": rango, "metropoli": nombre}, ensure_ascii=False) + "\n")
                n += 1
        resumen[rango] = n
        print(f"{rango} {nombre}: {n} lugares con nombre")
        time.sleep(5)
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    json.dump(resumen, open(os.path.join(RAIZ, "data", "corridas", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-osm.json"), "w"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
