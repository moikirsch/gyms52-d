# -*- coding: utf-8 -*-
"""Publica en gyms52.com los lugares de data/base.csv que aún no tienen wp_id.

Uso: python publicar.py --metros 1 --max 300 [--estado publish|draft]
Necesita WP_USER y WP_APP_PASSWORD (contraseña de aplicación). WP_URL es opcional.
"""
import argparse
import datetime as dt
import json
import re
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
    ap.add_argument("--actualizar", action="store_true", help="reenvía a WordPress las fichas con pendiente_sync=1")
    ap.add_argument("--todas", action="store_true", help="con --actualizar, reenvía todas las publicadas")
    ap.add_argument("--retirar", action="store_true", help="pasa a borrador las fichas de data/retirar.csv")
    a = ap.parse_args()
    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    s.headers["User-Agent"] = "gyms52-pipeline/1.0"
    if a.retirar:
        ruta_ret = os.path.join(RAIZ, "data", "retirar.csv")
        if not os.path.exists(ruta_ret):
            print("Nada que retirar"); return
        ret = pd.read_csv(ruta_ret, dtype=str).fillna("")
        hechos = 0
        for i, r in ret[ret.retirado_el == ""].iterrows():
            resp = s.post(f"{url}/wp-json/geodir/v2/lugares/{r.wp_id}", json={"status": "draft"}, timeout=60)
            if resp.status_code in (200, 201, 404):
                ret.at[i, "retirado_el"] = dt.date.today().isoformat()
                hechos += 1
            time.sleep(0.3)
        ret.to_csv(ruta_ret, index=False)
        print(f"Retiradas: {hechos}")
        return
    cats = categorias(s, url)
    ruta = os.path.join(RAIZ, "data", "base.csv")
    base = pd.read_csv(ruta, dtype=str).fillna("")
    for c in ("pendiente_sync", "foto_url", "foto_subida"):
        if c not in base.columns:
            base[c] = ""
    if a.actualizar:
        pendientes = base[(base.wp_id != "") & ((base.pendiente_sync == "1") | a.todas)]
    else:
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
            "instagram": r.get("instagram", ""), "facebook": r.get("facebook", ""), "tiktok": r.get("tiktok", ""),
            "whatsapp": r.get("whatsapp", ""), "business_hours": r.get("horario", ""),
            "instalaciones": [x for x in r.get("instalaciones", "").split("|") if x], "servicios": [x for x in r.get("servicios", "").split("|") if x],
            "pases": [x for x in r.get("pases", "").split("|") if x], "abierto_24h": 1 if r.get("abierto_24h") == "1" else "",
            "mensualidad_desde": r.get("mensualidad_desde", ""), "inscripcion": r.get("inscripcion", ""),
            "pase_dia": r.get("pase_dia", ""), "fecha_precio": r.get("fecha_precio", ""),
            "pases_fuente": r.get("opiniones_fuentes", "")[:250], "pases_verificado_el": r.get("opiniones_el", ""),
        }
        if cuerpo["correo"] and not re.fullmatch(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9]([A-Za-z0-9\-]*[A-Za-z0-9])?\.)+[A-Za-z]{2,}", cuerpo["correo"].strip()):
            cuerpo["correo"] = ""  # WordPress rechaza correos mal escritos
        foto_nueva = r.get("foto_url", "") and r.get("foto_subida", "") != "1"
        if foto_nueva:
            cuerpo["post_images"] = f"{r.foto_url}|0|{r.nombre}|"
        cuerpo = {k: v for k, v in cuerpo.items() if v not in ("", None, [])}
        destino = f"{url}/wp-json/geodir/v2/lugares" + (f"/{r.wp_id}" if a.actualizar else "")
        if a.actualizar:
            cuerpo.pop("status", None)
        try:
            resp = s.post(destino, json=cuerpo, timeout=90)
            if resp.status_code in (200, 201):
                base.at[i, "wp_id"] = str(resp.json()["id"])
                if not a.actualizar:
                    base.at[i, "publicado_el"] = hoy
                base.at[i, "pendiente_sync"] = ""
                if foto_nueva:
                    base.at[i, "foto_subida"] = "1"
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
    nombre = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M") + "-publicar.json"
    json.dump({"publicados": hechos, "pendientes_antes": len(pendientes), "errores": errores[:30]},
              open(os.path.join(RAIZ, "data", "corridas", nombre), "w"), ensure_ascii=False, indent=1)
    print(f"Publicados: {hechos} | errores: {len(errores)}")
    for e in errores[:10]:
        print("  ", e)


if __name__ == "__main__":
    main()
