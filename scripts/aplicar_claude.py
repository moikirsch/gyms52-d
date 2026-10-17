# -*- coding: utf-8 -*-
"""Aplica a data/base.csv lo que la tarea programada de Claude encontró en la web (data/claude/*.csv).

Cada CSV trae: place_id, sitio_web, instagram, facebook, tiktok, whatsapp, telefono, correo, horario_texto, fuente_url, nota
- Solo llena campos vacíos (lo que ya venía de Google, OSM, DENUE o del sitio web se respeta).
- horario_texto viene en formato OpenStreetMap ("Mo-Fr 06:00-22:00; Sa 08:00-14:00").
- Marca claude_el en cada ficha revisada (aunque no haya encontrado nada) y pendiente_sync=1 donde hubo cambios.
"""
import datetime as dt
import glob
import os
import re

import pandas as pd

from comun import horario_osm

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPOS = ("sitio_web", "instagram", "facebook", "tiktok", "whatsapp", "telefono", "correo")


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
    for c in CAMPOS + ("horario", "claude_el", "pendiente_sync"):
        if c not in base.columns:
            base[c] = ""
    reg = os.path.join(RAIZ, "data", "claude", "aplicados.txt")
    hechos = set(open(reg).read().split()) if os.path.exists(reg) else set()
    idx = {p: i for i, p in enumerate(base.place_id)}
    revisadas = cambios = 0
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
            if hubo:
                base.at[i, "pendiente_sync"] = "1"
                cambios += 1
        nuevos.append(nombre)
    base.to_csv(ruta, index=False)
    with open(reg, "a") as f:
        for n in nuevos:
            f.write(n + "\n")
    print(f"Claude: {len(nuevos)} archivos, {revisadas} fichas revisadas, {cambios} con datos nuevos")


if __name__ == "__main__":
    main()
