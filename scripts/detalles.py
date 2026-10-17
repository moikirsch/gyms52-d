# -*- coding: utf-8 -*-
"""Completa cada ficha con Google Place Details: sitio web, teléfono, horario y calificación.

Uso: python detalles.py --metros 1 --max 2000
Solo consulta fichas sin `detalles_el`. Marca `pendiente_sync=1` donde algo cambió, para que
publicar.py --actualizar lo suba a WordPress.
"""
import argparse
import datetime as dt
import json
import os
import time

import pandas as pd
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPOS = "websiteUri,nationalPhoneNumber,regularOpeningHours,rating,userRatingCount"
DIAS = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]


def horario_gd(roh):
    """Convierte regularOpeningHours de Google al formato de horario de GeoDirectory."""
    periodos = (roh or {}).get("periods") or []
    if not periodos:
        return ""
    if len(periodos) == 1 and "close" not in periodos[0]:
        rangos = [f"{d} 00:00-23:59" for d in DIAS[1:] + DIAS[:1]]
    else:
        por_dia = {d: [] for d in DIAS}
        for p in periodos:
            o, c = p.get("open", {}), p.get("close", {})
            if "day" not in o:
                continue
            ini = f"{o.get('hour', 0):02d}:{o.get('minute', 0):02d}"
            fin = f"{c.get('hour', 23):02d}:{c.get('minute', 59):02d}" if c else "23:59"
            if fin == "00:00":
                fin = "23:59"
            por_dia[DIAS[o["day"]]].append(f"{ini}-{fin}")
        rangos = [f"{d} {','.join(v)}" for d, v in ((d, por_dia[d]) for d in DIAS[1:] + DIAS[:1]) if v]
    return json.dumps(rangos, ensure_ascii=False, separators=(",", ":")) + ',["UTC":"-6","Timezone":"America/Mexico_City"]'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metros", default="")
    ap.add_argument("--max", type=int, default=2000)
    a = ap.parse_args()
    clave = os.environ["GOOGLE_PLACES_KEY"]
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    for c in ("horario", "google_rating", "google_resenas", "detalles_el", "pendiente_sync"):
        if c not in base.columns:
            base[c] = ""
    filtro = base.detalles_el == ""
    if a.metros:
        filtro &= base.metro_rango.isin([x.strip() for x in a.metros.split(",")])
    hoy = dt.date.today().isoformat()
    hechas, cambios, errores = 0, 0, []
    for i in base[filtro].head(a.max).index:
        r = requests.get(f"https://places.googleapis.com/v1/places/{base.at[i, 'place_id']}", timeout=60,
                         headers={"X-Goog-Api-Key": clave, "X-Goog-FieldMask": CAMPOS, "Accept-Language": "es"})
        if r.status_code == 429:
            errores.append("Cuota diaria agotada")
            break
        if r.status_code != 200:
            errores.append(f"{base.at[i, 'nombre']}: {r.status_code} {r.text[:120]}")
            if r.status_code in (401, 403):
                break
            continue
        j = r.json()
        hechas += 1
        antes = base.loc[i].copy()
        if j.get("websiteUri") and not base.at[i, "sitio_web"]:
            base.at[i, "sitio_web"] = j["websiteUri"]
        if j.get("nationalPhoneNumber") and not base.at[i, "telefono"]:
            base.at[i, "telefono"] = "".join(ch for ch in j["nationalPhoneNumber"] if ch.isdigit())
        h = horario_gd(j.get("regularOpeningHours"))
        if h:
            base.at[i, "horario"] = h
        if "rating" in j:
            base.at[i, "google_rating"] = str(j["rating"])
            base.at[i, "google_resenas"] = str(j.get("userRatingCount", ""))
        base.at[i, "detalles_el"] = hoy
        if not antes[["sitio_web", "telefono", "horario"]].equals(base.loc[i, ["sitio_web", "telefono", "horario"]]):
            base.at[i, "pendiente_sync"] = "1"
            cambios += 1
        if hechas % 100 == 0:
            base.to_csv(ruta, index=False)
        time.sleep(0.05)
    base.to_csv(ruta, index=False)
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    json.dump({"consultadas": hechas, "con_cambios": cambios, "errores": errores[:20]},
              open(os.path.join(RAIZ, "data", "corridas", dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-detalles.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"Detalles: {hechas} consultadas, {cambios} con datos nuevos, {len(errores)} errores")


if __name__ == "__main__":
    main()
