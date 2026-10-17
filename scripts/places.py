# -*- coding: utf-8 -*-
"""Busca lugares de fitness en Google Places (Text Search, API nueva) por metrópoli.

Uso: python places.py --metros 1,2 --max 600
Necesita la variable de entorno GOOGLE_PLACES_KEY.
Guarda los resultados crudos en data/places/<rango>-<metropoli>.jsonl (sin duplicados por place_id)
y deja un resumen en data/corridas/.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time

import pandas as pd
import requests

from comun import slug

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://places.googleapis.com/v1/places:searchText"
# Solo campos de nivel Pro: sin teléfono, sitio web ni rating, para cuidar el costo.
CAMPOS = ",".join("places." + c for c in [
    "id", "displayName", "formattedAddress", "addressComponents", "location", "types", "primaryType",
    "googleMapsUri", "businessStatus"]) + ",nextPageToken"
BUSQUEDAS = [
    "gimnasio", "crossfit", "box de entrenamiento funcional", "estudio de pilates", "estudio de yoga",
    "indoor cycling", "gimnasio de box", "artes marciales", "escuela de danza", "clases de natación",
    "muro de escalada", "tienda de suplementos deportivos", "tienda de artículos deportivos",
]


class CuotaAgotada(Exception):
    pass


def municipios(fila):
    out = []
    for item in str(fila["lista_municipios"]).split(";"):
        item = item.strip()
        if "(" in item:
            mun, edo = item.rsplit("(", 1)
            out.append((mun.strip(), edo.rstrip(")").strip()))
    return out


def buscar(clave, texto, contador, maximo, max_paginas=3):
    resultados, token = [], None
    for _ in range(max_paginas):
        if contador["n"] >= maximo:
            break
        cuerpo = {"textQuery": texto, "languageCode": "es", "regionCode": "MX", "pageSize": 20}
        if token:
            cuerpo["pageToken"] = token
        r = requests.post(URL, json=cuerpo, timeout=60, headers={
            "X-Goog-Api-Key": clave, "X-Goog-FieldMask": CAMPOS, "Content-Type": "application/json"})
        contador["n"] += 1
        if r.status_code != 200:
            contador["errores"].append(f"{r.status_code} {texto}: {r.text[:200]}")
            if r.status_code == 429:
                contador["n"] -= 1
                raise CuotaAgotada(r.text[:200])
            if r.status_code in (400, 401, 403):
                raise SystemExit("Google Places rechazó la llave o la petición: " + r.text[:300])
            break
        j = r.json()
        resultados += j.get("places", [])
        token = j.get("nextPageToken")
        if not token:
            break
        time.sleep(1.5)
    return resultados


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metros", default="1", help="rangos separados por coma, ej. 1,2,3")
    ap.add_argument("--max", type=int, default=600, help="tope de peticiones a Google en esta corrida")
    ap.add_argument("--auto", type=int, default=0, help="toma en orden las primeras N metrópolis que tengan búsquedas pendientes")
    a = ap.parse_args()
    clave = os.environ.get("GOOGLE_PLACES_KEY")
    if not clave:
        raise SystemExit("Falta GOOGLE_PLACES_KEY")
    metros = pd.read_csv(os.path.join(RAIZ, "config", "metros.csv"))
    rangos = [int(x) for x in a.metros.split(",") if x.strip()]
    if a.auto:
        rangos = []
        for _, f in metros[metros.rango <= a.auto].sort_values("rango").iterrows():
            est = os.path.join(RAIZ, "data", "places", f"{int(f['rango']):03d}-{slug(f['metropoli'])}.hecho.json")
            hechas = set(json.load(open(est))) if os.path.exists(est) else set()
            if len(hechas) < len(municipios(f)) * len(BUSQUEDAS):
                rangos.append(int(f["rango"]))
        print("Metrópolis con búsquedas pendientes:", rangos or "ninguna")
    contador = {"n": 0, "errores": []}
    resumen = {"inicio": dt.datetime.now(dt.timezone.utc).isoformat() + "Z", "metros": {}}
    os.makedirs(os.path.join(RAIZ, "data", "places"), exist_ok=True)
    for rango in rangos:
        fila = metros[metros.rango == rango].iloc[0]
        ruta = os.path.join(RAIZ, "data", "places", f"{rango:03d}-{slug(fila['metropoli'])}.jsonl")
        vistos = {}
        if os.path.exists(ruta):
            for linea in open(ruta, encoding="utf-8"):
                p = json.loads(linea)
                vistos[p["id"]] = p
        antes = len(vistos)
        ruta_estado = ruta.replace(".jsonl", ".hecho.json")
        hechas = set(json.load(open(ruta_estado))) if os.path.exists(ruta_estado) else set()
        agotada = False
        for mun, edo in municipios(fila):
            for q in BUSQUEDAS:
                if contador["n"] >= a.max or agotada:
                    break
                consulta = f"{q} en {mun}, {edo}"
                if consulta in hechas:
                    continue
                try:
                    encontrados = buscar(clave, consulta, contador, a.max)
                except CuotaAgotada as e:
                    contador["errores"].append("Cuota diaria de Google agotada: " + str(e)[:120])
                    agotada = True
                    break
                hechas.add(consulta)
                for p in encontrados:
                    if p.get("businessStatus") == "CLOSED_PERMANENTLY":
                        continue
                    p.setdefault("_busquedas", [])
                    previo = vistos.get(p["id"], p)
                    previo.setdefault("_busquedas", [])
                    if q not in previo["_busquedas"]:
                        previo["_busquedas"].append(q)
                    previo["_metro_rango"], previo["_metropoli"] = rango, fila["metropoli"]
                    vistos[p["id"]] = previo
        json.dump(sorted(hechas), open(ruta_estado, "w"), ensure_ascii=False)
        with open(ruta, "w", encoding="utf-8") as f:
            for p in vistos.values():
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        resumen["metros"][fila["metropoli"]] = {"antes": antes, "despues": len(vistos)}
        print(f"{fila['metropoli']}: {antes} -> {len(vistos)} lugares")
        if agotada:
            print("Cuota diaria de Google agotada; se retoma en la siguiente corrida.")
            break
    resumen.update(peticiones=contador["n"], errores=contador["errores"][:20], fin=dt.datetime.now(dt.timezone.utc).isoformat() + "Z")
    os.makedirs(os.path.join(RAIZ, "data", "corridas"), exist_ok=True)
    nombre = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-places.json"
    json.dump(resumen, open(os.path.join(RAIZ, "data", "corridas", nombre), "w"), ensure_ascii=False, indent=1)
    print(f"Peticiones usadas: {contador['n']} de {a.max}")


if __name__ == "__main__":
    main()
