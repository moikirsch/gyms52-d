# -*- coding: utf-8 -*-
"""Une lo encontrado en Google Places con DENUE y arma data/base.csv, la base maestra de Gyms +52.

- Base: los lugares de Google (operando, con coordenadas y nombre verificable).
- DENUE se usa para cruzar: clave DENUE, teléfono, correo y sitio web cuando Google no los trae.
- Los registros de DENUE sin pareja en Google quedan en data/denue/sin_pareja.csv como candidatos (no se publican).
"""
import datetime as dt
import glob
import json
import os
from collections import defaultdict

import pandas as pd

from comun import clasificar, distancia_m, limpiar_nombre, similitud, slug, TIPOS_VALIDOS

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Qué significa haber aparecido en una sola búsqueda (solo se usa si el nombre no dice nada)
PISTAS = {
    "crossfit": "crossfit", "box de entrenamiento funcional": "funcional", "estudio de pilates": "pilates",
    "estudio de yoga": "yoga", "indoor cycling": "cycling", "gimnasio de box": "boxeo",
    "artes marciales": "artes marciales", "escuela de danza": "danza", "clases de natacion": "natacion",
    "clases de natación": "natacion", "muro de escalada": "escalada", "tienda de suplementos deportivos": "suplementos",
}
EXCLUIR = {"school", "primary_school", "secondary_school", "university", "hospital", "doctor", "physiotherapist",
           "restaurant", "hotel", "lodging", "spa", "beauty_salon", "real_estate_agency", "apartment_complex",
           "church", "park", "cafe", "bar", "car_repair", "medical_lab", "dentist"}


def componente(p, tipo, corto=False):
    for c in p.get("addressComponents", []):
        if tipo in c.get("types", []):
            return c.get("shortText" if corto else "longText", "")
    return ""


def es_fitness(p, disciplinas_por_nombre):
    tipos = set(p.get("types", []))
    if p.get("primaryType") in TIPOS_VALIDOS or tipos & TIPOS_VALIDOS:
        return True
    if p.get("primaryType") in EXCLUIR:
        return False
    return bool(disciplinas_por_nombre)


def descripcion(r):
    lugar = r["colonia"] + ", " + r["ciudad"] if r["colonia"] else r["ciudad"]
    articulo = "una" if r["tipo_lugar"] in ("Tienda", "Escuela de danza") else "un"
    tipo = r["tipo_lugar"].lower()
    estado = "" if r["estado"] in (r["ciudad"], "") else f", {r['estado']}"
    texto = f"{r['nombre']} es {articulo} {tipo} en {lugar}{estado}."
    disc = [d for d in r["disciplinas"].split("|") if d and d != "Pesas"]
    if disc:
        texto += " Disciplinas: " + ", ".join(d.lower() if d not in ("CrossFit", "HYROX", "MMA", "HIIT") else d for d in disc) + "."
    if r["cadena"]:
        texto += f" Forma parte de {r['cadena']}."
    return texto


def main():
    hoy = dt.date.today().isoformat()
    denue = pd.read_csv(os.path.join(RAIZ, "data", "denue", "gimnasios.csv"), dtype=str).fillna("")
    denue["lat"] = pd.to_numeric(denue["latitud"], errors="coerce")
    denue["lng"] = pd.to_numeric(denue["longitud"], errors="coerce")
    malla = defaultdict(list)
    for i, d in denue.dropna(subset=["lat", "lng"]).iterrows():
        malla[(round(d.lat, 2), round(d.lng, 2))].append(i)

    previo = {}
    ruta_base = os.path.join(RAIZ, "data", "base.csv")
    if os.path.exists(ruta_base):
        for _, r in pd.read_csv(ruta_base, dtype=str).fillna("").iterrows():
            previo[r["place_id"]] = r.to_dict()

    filas, usados_denue, descartados = [], set(), 0
    for archivo in sorted(glob.glob(os.path.join(RAIZ, "data", "places", "*.jsonl"))):
        for linea in open(archivo, encoding="utf-8"):
            p = json.loads(linea)
            nombre = limpiar_nombre(p.get("displayName", {}).get("text", ""))
            tipos = p.get("types", [])
            pista = " ".join(p.get("_busquedas", []))
            _, disc_nombre, _ = clasificar(nombre, ())
            disc_nombre = [d for d in disc_nombre if d not in ("Pesas", "Equipo de gimnasio")]
            if not nombre or not es_fitness(p, disc_nombre):
                descartados += 1
                continue
            busq = p.get("_busquedas", [])
            usar_pista = not disc_nombre and p.get("primaryType") not in ("gym", "fitness_center") and len(busq) == 1
            tipo, disciplinas, cadena = clasificar(nombre, tipos, PISTAS.get(busq[0], "") if usar_pista else "")
            lat, lng = p["location"]["latitude"], p["location"]["longitude"]
            # pareja en DENUE
            mejor, mejor_puntos = None, 0
            for dy in (-0.01, 0, 0.01):
                for dx in (-0.01, 0, 0.01):
                    for i in malla.get((round(lat + dy, 2), round(lng + dx, 2)), []):
                        d = denue.loc[i]
                        dist = distancia_m(lat, lng, d.lat, d.lng)
                        sim = similitud(nombre, d.nom_estab)
                        if (dist <= 120 and sim >= 0.34) or (dist <= 40 and sim >= 0.2):
                            puntos = sim - dist / 1000
                            if puntos > mejor_puntos:
                                mejor, mejor_puntos = i, puntos
            dn = denue.loc[mejor] if mejor is not None else None
            if mejor is not None:
                usados_denue.add(mejor)
            calle = (componente(p, "route") + " " + componente(p, "street_number")).strip()
            r = {
                "place_id": p["id"], "nombre": nombre, "slug": slug(nombre), "tipo_lugar": tipo,
                "disciplinas": "|".join(disciplinas), "cadena": cadena,
                "calle": calle or p.get("formattedAddress", "").split(",")[0],
                "colonia": componente(p, "sublocality_level_1") or componente(p, "neighborhood") or (dn.nomb_asent.title() if dn is not None else ""),
                "ciudad": componente(p, "locality") or componente(p, "administrative_area_level_2"),
                "estado": componente(p, "administrative_area_level_1"),
                "cp": componente(p, "postal_code") or (dn.cod_postal if dn is not None else ""),
                "lat": round(lat, 7), "lng": round(lng, 7), "google_maps_url": p.get("googleMapsUri", ""),
                "direccion_google": p.get("formattedAddress", ""),
                "telefono": dn.telefono if dn is not None else "", "correo": dn.correoelec.lower() if dn is not None else "",
                "sitio_web": dn.www.lower() if dn is not None else "", "denue_id": dn.id if dn is not None else "",
                "sector": dn.sector if dn is not None else "", "metro_rango": p.get("_metro_rango", ""),
                "metropoli": p.get("_metropoli", ""), "fuente": "google_places" + ("+denue" if dn is not None else ""),
                "ultima_verificacion": hoy,
            }
            if r["sector"] == "público" and r["tipo_lugar"] in ("Gimnasio", "Club deportivo"):
                r["tipo_lugar"] = "Deportivo público"
            if r["sitio_web"] and not r["sitio_web"].startswith("http"):
                r["sitio_web"] = "https://" + r["sitio_web"]
            r["descripcion"] = descripcion(r)
            ant = previo.get(r["place_id"], {})
            r["wp_id"] = ant.get("wp_id", "")
            r["publicado_el"] = ant.get("publicado_el", "")
            filas.append(r)

    if not filas:
        raise SystemExit("No hay lugares de Google todavía; corre places.py primero.")
    base = pd.DataFrame(filas).drop_duplicates("place_id")
    base.to_csv(ruta_base, index=False)
    metros_cubiertos = set(base["metro_rango"].astype(str))
    sin = denue.drop(index=list(usados_denue))
    sin = sin[sin.metro_rango.astype(str).isin(metros_cubiertos)]
    sin.drop(columns=["lat", "lng"]).to_csv(os.path.join(RAIZ, "data", "denue", "sin_pareja.csv"), index=False)
    print(f"Base: {len(base)} lugares | con DENUE: {(base.denue_id != '').sum()} | descartados: {descartados} | DENUE sin pareja: {len(sin)}")
    print(base.tipo_lugar.value_counts().to_string())


if __name__ == "__main__":
    main()
