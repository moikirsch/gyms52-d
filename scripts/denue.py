# -*- coding: utf-8 -*-
"""Descarga DENUE (sector 71) y deja los centros de acondicionamiento físico en data/denue/gimnasios.csv.

SCIAN 713943 = privados, 713944 = públicos. Cada registro queda marcado con la metrópoli a la que pertenece
según config/metros.csv.
"""
import io
import os
import sys
import zipfile

import pandas as pd
import requests

from comun import sin_acentos

URL = "https://www.inegi.org.mx/contenidos/masiva/denue/denue_00_71_csv.zip"
RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, "data", "denue", "gimnasios.csv")
CODIGOS = {"713943": "privado", "713944": "público"}
COLS = ["id", "nom_estab", "raz_social", "codigo_act", "per_ocu", "tipo_vial", "nom_vial", "numero_ext",
        "letra_ext", "numero_int", "tipo_asent", "nomb_asent", "nom_CenCom", "cod_postal", "cve_ent", "entidad",
        "cve_mun", "municipio", "localidad", "telefono", "correoelec", "www", "latitud", "longitud", "fecha_alta"]


def clave(estado, municipio):
    e = sin_acentos(estado).lower().replace("estado de mexico", "mexico").strip()
    for sufijo in (" de ignacio de la llave", " de ocampo", " de zaragoza"):
        e = e.replace(sufijo, "")
    return e + "|" + sin_acentos(municipio).lower().strip()


def mapa_metros():
    m = pd.read_csv(os.path.join(RAIZ, "config", "metros.csv"))
    mapa = {}
    for _, fila in m.iterrows():
        for item in str(fila["lista_municipios"]).split(";"):
            item = item.strip()
            if "(" not in item:
                continue
            mun, edo = item.rsplit("(", 1)
            mapa[clave(edo.rstrip(")"), mun)] = (int(fila["rango"]), fila["metropoli"])
    return mapa


def main(ruta_zip=None):
    if ruta_zip:
        datos = open(ruta_zip, "rb").read()
    else:
        r = requests.get(URL, timeout=600)
        r.raise_for_status()
        datos = r.content
    z = zipfile.ZipFile(io.BytesIO(datos))
    nombre = next(n for n in z.namelist() if n.startswith("conjunto_de_datos/") and n.endswith(".csv"))
    df = pd.read_csv(z.open(nombre), encoding="latin-1", dtype=str, low_memory=False)
    df = df[df["codigo_act"].isin(CODIGOS)][COLS].copy()
    for c in df.columns:
        df[c] = df[c].fillna("").str.strip()
    df["sector"] = df["codigo_act"].map(CODIGOS)
    mapa = mapa_metros()
    marcas = [mapa.get(clave("mexico" if e == "México" else e, m), (None, "")) for e, m in zip(df["entidad"], df["municipio"])]
    df["metro_rango"] = [x[0] if x[0] is not None else "" for x in marcas]
    df["metropoli"] = [x[1] for x in marcas]
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    df.sort_values(["cve_ent", "cve_mun", "nom_estab"]).to_csv(SALIDA, index=False)
    print(f"DENUE: {len(df)} registros ({(df.metropoli != '').sum()} dentro de metrópolis) -> {SALIDA}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
