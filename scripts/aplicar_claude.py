# -*- coding: utf-8 -*-
"""Aplica a data/base.csv lo que la tarea programada de Claude encontró en la web (data/claude/*.csv).

Cada CSV trae: place_id, sitio_web, instagram, facebook, tiktok, whatsapp, telefono, correo, horario_texto, fuente_url, nota
y, desde oct 2026, lo que dicen las reseñas: lo_mejor, a_considerar, instalaciones, servicios, abierto_24h, pases,
mensualidad_desde, inscripcion, pase_dia, fecha_precio, precio_fuente_url, opiniones_fuentes
- Solo llena campos vacíos (lo que ya venía de Google, OSM, DENUE o del sitio web se respeta).
- horario_texto viene en formato OpenStreetMap ("Mo-Fr 06:00-22:00; Sa 08:00-14:00").
- Marca claude_el en cada ficha revisada (aunque no haya encontrado nada) y pendiente_sync=1 donde hubo cambios.
"""
import datetime as dt
import glob
import os
import re

import pandas as pd

from comun import horario_osm, sin_acentos
from unir import con_opiniones, descripcion

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPOS = ("sitio_web", "instagram", "facebook", "tiktok", "whatsapp", "telefono", "correo")
OPCIONES = {
    "instalaciones": ["Alberca", "Regaderas y vestidores", "Lockers", "Sauna o vapor", "Estacionamiento", "Área infantil",
                      "Cafetería", "Tienda", "Zona de peso libre", "Zona funcional", "Aire acondicionado"],
    "servicios": ["Entrenador personal", "Nutriólogo", "Evaluación corporal", "Fisioterapia", "App propia", "Clases en línea"],
    "pases": ["TotalPass", "Wellhub", "ClassPass", "Fitpass"],
}
PRECIOS = ("mensualidad_desde", "inscripcion", "pase_dia")
NUEVAS = ("lo_mejor", "a_considerar", "instalaciones", "servicios", "abierto_24h", "pases") + PRECIOS + (
    "fecha_precio", "precio_fuente_url", "opiniones_fuentes", "opiniones_el")


def lista(campo, v):
    """Solo deja opciones válidas del sitio, separadas por |."""
    validas = {sin_acentos(o).lower(): o for o in OPCIONES[campo]}
    sal = []
    for x in re.split(r"[|,;]", v or ""):
        o = validas.get(sin_acentos(x.strip()).lower())
        if o and o not in sal:
            sal.append(o)
    return "|".join(sal)


def frase(v):
    v = re.sub(r"\s+", " ", (v or "").replace("—", ",").replace("–", ",")).strip()
    return "" if v.lower() in ("", "nan", "none", "-") else v[:400]


def limpio(campo, v):
    v = (v or "").strip()
    if not v or v.lower() in ("nan", "none", "-", "n/a", "no encontrado"):
        return ""
    if campo in ("whatsapp", "telefono"):
        v = re.sub(r"\D", "", v)[-10:]
        return v if len(v) == 10 else ""
    if campo == "correo":
        return v.lower() if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", v.lower()) else ""
    if not v.startswith("http"):
        v = "https://" + v.lstrip("/")
    return v.split("?")[0].rstrip("/")


def main():
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    for c in CAMPOS + NUEVAS + ("horario", "claude_el", "pendiente_sync"):
        if c not in base.columns:
            base[c] = ""
    reg = os.path.join(RAIZ, "data", "claude", "aplicados.txt")
    hechos = set(open(reg).read().split()) if os.path.exists(reg) else set()
    idx = {p: i for i, p in enumerate(base.place_id)}
    revisadas = cambios = 0
    cerrados = []
    nuevos = []
    for archivo in sorted(glob.glob(os.path.join(RAIZ, "data", "claude", "*.csv"))):
        nombre = os.path.basename(archivo)
        if nombre in hechos:
            continue
        hoja = pd.read_csv(archivo, dtype=str).fillna("")
        fecha = (re.match(r"(\d{4}-\d{2}-\d{2})", nombre) or [None, dt.date.today().isoformat()])[1]
        for _, r in hoja.iterrows():
            i = idx.get(r.get("place_id", ""))
            if i is None:
                continue
            revisadas += 1
            base.at[i, "claude_el"] = fecha
            nota = (r.get("nota", "") or "").strip()
            if nota.lower().startswith("cerrado") and base.at[i, "wp_id"]:
                cerrados.append({"wp_id": base.at[i, "wp_id"], "nombre": base.at[i, "nombre"], "place_id": base.at[i, "place_id"],
                                 "motivo": nota[:300], "retirado_el": ""})
            hubo = False
            for c in CAMPOS:
                v = limpio(c, r.get(c, ""))
                if v and not base.at[i, c]:
                    base.at[i, c] = v
                    hubo = True
            h = horario_osm(r.get("horario_texto", ""))
            if h and not base.at[i, "horario"]:
                base.at[i, "horario"] = h
                hubo = True
            # opiniones: se reemplazan con la lectura más reciente (son un resumen, no un dato fijo)
            if any(c in hoja.columns for c in ("lo_mejor", "a_considerar")):
                base.at[i, "opiniones_el"] = fecha
                for c in ("lo_mejor", "a_considerar"):
                    v = frase(r.get(c, ""))
                    if v and v != base.at[i, c]:
                        base.at[i, c] = v
                        hubo = True
                for c in OPCIONES:
                    v = lista(c, r.get(c, ""))
                    if v and v != base.at[i, c]:
                        base.at[i, c] = v
                        hubo = True
                a24 = (r.get("abierto_24h", "") or "").strip().lower()
                if a24 in ("1", "si", "sí", "true") and base.at[i, "abierto_24h"] != "1":
                    base.at[i, "abierto_24h"] = "1"
                    hubo = True
                precios = {c: re.sub(r"\D", "", r.get(c, "") or "") for c in PRECIOS}
                fecha_p = (r.get("fecha_precio", "") or "").strip()[:7]
                fuente_p = (r.get("precio_fuente_url", "") or "").strip()
                if any(50 <= int(v) <= 20000 for v in precios.values() if v) and re.fullmatch(r"20\d\d-\d\d", fecha_p) and fuente_p.startswith("http"):
                    for c, v in precios.items():
                        if v and 50 <= int(v) <= 20000:
                            base.at[i, c] = v
                    base.at[i, "fecha_precio"], base.at[i, "precio_fuente_url"] = fecha_p, fuente_p
                    hubo = True
                f_op = (r.get("opiniones_fuentes", "") or "").strip()
                if f_op:
                    base.at[i, "opiniones_fuentes"] = f_op[:500]
            if hubo:
                fila = base.loc[i].to_dict()
                base.at[i, "descripcion"] = con_opiniones(descripcion(fila), fila)
                base.at[i, "pendiente_sync"] = "1"
                cambios += 1
        nuevos.append(nombre)
    # lugares que Claude encontró cerrados: fuera de la base y a borrador en WordPress
    if cerrados:
        ruta_ret = os.path.join(RAIZ, "data", "retirar.csv")
        ret = pd.read_csv(ruta_ret, dtype=str).fillna("") if os.path.exists(ruta_ret) else pd.DataFrame(columns=["wp_id", "nombre", "motivo", "retirado_el"])
        nuevos_ret = [c for c in cerrados if c["wp_id"] not in set(ret.wp_id)]
        if nuevos_ret:
            pd.concat([ret, pd.DataFrame(nuevos_ret)]).to_csv(ruta_ret, index=False)
        reg_c = os.path.join(RAIZ, "data", "cerrados.csv")
        prev = pd.read_csv(reg_c, dtype=str).fillna("") if os.path.exists(reg_c) else pd.DataFrame()
        pd.concat([prev, pd.DataFrame(cerrados)]).drop_duplicates("place_id").to_csv(reg_c, index=False)
        base = base[~base.place_id.isin({c["place_id"] for c in cerrados})]
    base.to_csv(ruta, index=False)
    with open(reg, "a") as f:
        for n in nuevos:
            f.write(n + "\n")
    print(f"Claude: {len(nuevos)} archivos, {revisadas} fichas revisadas, {cambios} con datos nuevos, {len(cerrados)} cerrados a borrador")


if __name__ == "__main__":
    main()
