# -*- coding: utf-8 -*-
"""Une lo encontrado en Google Places con DENUE y arma data/base.csv, la base maestra de Gyms +52.

- Base: los lugares de Google (operando, con coordenadas y nombre verificable).
- DENUE se usa para cruzar: clave DENUE, teléfono, correo y sitio web cuando Google no los trae.
- OpenStreetMap (data/osm): completa contacto, redes y horario de lo que ya está, y agrega lo que Google no tiene.
- DENUE sin pareja en las metrópolis de lanzamiento entra como ficha propia si su nombre no es genérico.
- Cuando un lugar cambia de fuente (p. ej. Google encuentra uno que venía de DENUE), conserva su ficha en WordPress.
"""
import datetime as dt
import glob
import json
import os
import re
from collections import defaultdict

import pandas as pd

from comun import restaurar_wp_ids, DISC_SECUNDARIAS, es_cancha, sin_acentos, titulo, clasificar, distancia_m, horario_osm, limpiar_nombre, nombre_denue, similitud, slug, TIPOS_VALIDOS

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Qué significa haber aparecido en una sola búsqueda (solo se usa si el nombre no dice nada)
PISTAS = {
    "crossfit": "crossfit", "box de entrenamiento funcional": "funcional", "estudio de pilates": "pilates",
    "estudio de yoga": "yoga", "indoor cycling": "cycling", "gimnasio de box": "boxeo",
    "artes marciales": "artes marciales", "escuela de danza": "danza", "clases de natacion": "natacion",
    "clases de natación": "natacion", "muro de escalada": "escalada", "tienda de suplementos deportivos": "suplementos",
}
ENRIQUECIDOS = ("horario", "google_rating", "google_resenas", "instagram", "facebook", "tiktok", "whatsapp",
               "detalles_el", "redes_el", "claude_el", "pendiente_sync",
               "lo_mejor", "a_considerar", "instalaciones", "servicios", "abierto_24h", "pases", "mensualidad_desde",
               "inscripcion", "pase_dia", "fecha_precio", "precio_fuente_url", "opiniones_fuentes", "opiniones_el", "foto_url", "foto_el", "foto_subida", "afiliaciones")
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


def con_opiniones(texto, r):
    """Agrega a la descripción lo que dice la gente en sus reseñas (resumen propio, no citas)."""
    partes = []
    if r.get("lo_mejor"):
        partes.append(f"<p><strong>Lo mejor, según sus reseñas:</strong> {r['lo_mejor']}</p>")
    if r.get("a_considerar"):
        partes.append(f"<p><strong>A considerar:</strong> {r['a_considerar']}</p>")
    return texto + ("\n" + "\n".join(partes) if partes else "")


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
            disc_nombre = [d for d in disc_nombre if d not in ("Pesas", "Equipo de gimnasio") and d not in DISC_SECUNDARIAS]
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
                "colonia": componente(p, "sublocality_level_1") or componente(p, "neighborhood") or (titulo(dn.nomb_asent) if dn is not None else ""),
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
            if r["sitio_web"] and not r["sitio_web"].startswith("http"):
                r["sitio_web"] = "https://" + r["sitio_web"]
            filas.append(r)

    if not filas:
        raise SystemExit("No hay lugares de Google todavía; corre places.py primero.")
    lanzamiento = [str(k) for k in range(1, json.load(open(os.path.join(RAIZ, "config", "diario.json"))).get("metros_lanzamiento", 10) + 1)]
    malla_f = defaultdict(list)
    for k, r in enumerate(filas):
        malla_f[(round(r["lat"], 2), round(r["lng"], 2))].append(k)

    def pareja(lat, lng, nombre, max_lejos=120):
        mejor, mejor_p = None, 0
        for dy in (-0.01, 0, 0.01):
            for dx in (-0.01, 0, 0.01):
                for k in malla_f.get((round(lat + dy, 2), round(lng + dx, 2)), []):
                    f = filas[k]
                    dist = distancia_m(lat, lng, f["lat"], f["lng"])
                    sim = similitud(nombre, f["nombre"])
                    if (dist <= max_lejos and sim >= 0.34) or (dist <= 40 and sim >= 0.2):
                        if sim - dist / 1000 > mejor_p:
                            mejor, mejor_p = k, sim - dist / 1000
        return mejor

    def agregar(r):
        filas.append(r)
        malla_f[(round(r["lat"], 2), round(r["lng"], 2))].append(len(filas) - 1)

    def vecino_denue(lat, lng):
        """Registro DENUE más cercano (para municipio, colonia y CP cuando la fuente no los trae)."""
        mejor, md = None, 3000
        for dy in (-0.02, -0.01, 0, 0.01, 0.02):
            for dx in (-0.02, -0.01, 0, 0.01, 0.02):
                for i in malla.get((round(lat + dy, 2), round(lng + dx, 2)), []):
                    d = distancia_m(lat, lng, denue.at[i, "lat"], denue.at[i, "lng"])
                    if d < md:
                        mejor, md = i, d
        return denue.loc[mejor] if mejor is not None else None

    estados_metro = pd.read_csv(os.path.join(RAIZ, "config", "metros.csv"), dtype=str).set_index("rango")["estado"].to_dict()

    # ---------- OpenStreetMap ----------
    n_osm_nuevos = n_osm_completan = 0
    for archivo in sorted(glob.glob(os.path.join(RAIZ, "data", "osm", "*.jsonl"))):
        for linea in open(archivo, encoding="utf-8"):
            o = json.loads(linea)
            t = o["tags"]
            if str(o["metro_rango"]) not in lanzamiento:
                continue
            nombre = limpiar_nombre(t.get("name", ""))
            deporte = t.get("sport", "").replace(";", " ").replace("_", " ")
            tipos, pista = [], ""
            if t.get("leisure") == "fitness_centre":
                tipos.append("gym")
            if t.get("shop") == "sports":
                tipos.append("sporting_goods_store")
            if t.get("shop") == "nutrition_supplements":
                pista = "suplementos"
            if t.get("leisure") == "dance" or t.get("amenity") == "dancing_school":
                pista = "danza"
            if t.get("amenity") == "dojo":
                pista = "artes marciales"
            _, disc_nombre, _ = clasificar(nombre, ())
            disc_nombre = [d for d in disc_nombre if d not in ("Pesas", "Equipo de gimnasio") and d not in DISC_SECUNDARIAS]
            _, disc_dep, _ = clasificar(deporte, ())
            disc_dep = [d for d in disc_dep if d not in ("Pesas", "Equipo de gimnasio") and d not in DISC_SECUNDARIAS]
            if not (tipos or pista or disc_nombre or disc_dep or "fitness" in deporte):
                continue  # p. ej. un sports_centre de pura cancha de futbol
            if not nombre or (es_cancha(nombre) and not t.get("shop")):
                continue
            extra = {
                "sitio_web": (t.get("website") or t.get("contact:website") or "").strip(),
                "telefono": "".join(ch for ch in (t.get("phone") or t.get("contact:phone") or "").split(";")[0] if ch.isdigit())[-10:],
                "correo": (t.get("email") or t.get("contact:email") or "").lower().strip(),
                "instagram": t.get("contact:instagram", "").strip(),
                "facebook": t.get("contact:facebook", "").strip(),
                "horario": horario_osm(t.get("opening_hours", "")),
            }
            for red, url in (("instagram", "https://www.instagram.com/"), ("facebook", "https://www.facebook.com/")):
                if extra[red] and not extra[red].startswith("http"):
                    extra[red] = url + extra[red].lstrip("@/")
            if extra["sitio_web"] and not extra["sitio_web"].startswith("http"):
                extra["sitio_web"] = "https://" + extra["sitio_web"]
            k = pareja(o["lat"], o["lng"], nombre, 80)
            if k is not None:
                filas[k]["osm_id"] = o["osm_id"]
                filas[k].setdefault("_extra", {}).update({c: v for c, v in extra.items() if v})
                n_osm_completan += 1
                continue
            tipo, disciplinas, cadena = clasificar(nombre + " " + deporte, tipos, pista)
            vd = vecino_denue(o["lat"], o["lng"])
            calle = (t.get("addr:street", "") + " " + t.get("addr:housenumber", "")).strip()
            r = {
                "place_id": "osm:" + o["osm_id"], "nombre": nombre, "slug": slug(nombre), "tipo_lugar": tipo,
                "disciplinas": "|".join(disciplinas), "cadena": cadena, "calle": calle,
                "colonia": t.get("addr:suburb") or t.get("addr:neighbourhood") or (titulo(vd.nomb_asent) if vd is not None else ""),
                "ciudad": titulo(t.get("addr:city", "").split(",")[0]) or (vd.municipio if vd is not None else ""),
                "estado": vd.entidad if vd is not None else estados_metro.get(str(o["metro_rango"]), ""),
                "cp": t.get("addr:postcode") or (vd.cod_postal if vd is not None else ""),
                "lat": round(o["lat"], 7), "lng": round(o["lng"], 7), "google_maps_url": "", "direccion_google": "",
                "telefono": "", "correo": "", "sitio_web": "", "denue_id": "", "sector": "",
                "metro_rango": str(o["metro_rango"]), "metropoli": o["metropoli"], "fuente": "osm",
                "ultima_verificacion": hoy, "osm_id": o["osm_id"], "_extra": {c: v for c, v in extra.items() if v},
            }
            agregar(r)
            n_osm_nuevos += 1

    # ---------- Fuentes oficiales (cadenas, pases, afiliaciones) ----------
    PRIORIDAD = ["smartfit", "anytime", "sportsworld", "sportcity", "crossfit", "hyrox", "totalpass", "fitpass"]
    DISC_FUENTE = {"crossfit": "CrossFit", "hyrox": "HYROX"}
    n_fuente_nuevos, n_fuente_completan = defaultdict(int), defaultdict(int)
    for fuente in PRIORIDAD:
        ruta_f = os.path.join(RAIZ, "data", "fuentes", f"{fuente}.jsonl")
        if not os.path.exists(ruta_f):
            continue
        for linea in open(ruta_f, encoding="utf-8"):
            try:
                o = json.loads(linea)
                lat, lng = float(o["lat"]), float(o["lng"])
            except (ValueError, KeyError, TypeError):
                continue
            nombre = limpiar_nombre(o.get("nombre", ""))
            if not nombre or es_cancha(nombre):
                continue
            if fuente == "fitpass" and re.search(r"belleza|est[eé]tica|u[ñn]as|spa\b|masaje|barber|anniversary|evento|nutri[oó]log", sin_acentos(nombre + " " + o.get("tipo", "")), re.I):
                continue  # Fitpass mezcla servicios que no son lugares para entrenar
            fid = f"{fuente}:{o.get('id_fuente', '')}"
            extra = {c: (o.get(c) or "") for c in ("telefono", "sitio_web")}
            extra["horario"] = horario_osm(o.get("horario_osm", ""))
            if (o.get("foto") or "").startswith("http"):
                extra["foto_url"] = o["foto"]
            union = {"pases": o.get("pases") or [], "afiliaciones": o.get("afiliaciones") or [],
                     "instalaciones": o.get("instalaciones") or []}
            forzar = {}
            if o.get("cadena"):
                forzar["cadena"] = o["cadena"]
                if str(o.get("mensualidad_desde", "")).isdigit():
                    forzar.update({"mensualidad_desde": str(o["mensualidad_desde"]), "precio_fuente_url": o.get("precio_fuente_url") or o.get("url_fuente", ""),
                                   "fecha_precio": hoy[:7]})
            # cadenas: misma marca a menos de 150 m aunque el nombre cambie; demás: nombre parecido
            k = None
            if o.get("cadena"):
                mejor = 151
                for dy in (-0.01, 0, 0.01):
                    for dx in (-0.01, 0, 0.01):
                        for kk in malla_f.get((round(lat + dy, 2), round(lng + dx, 2)), []):
                            f = filas[kk]
                            d = distancia_m(lat, lng, f["lat"], f["lng"])
                            if d < mejor and (f.get("cadena") == o["cadena"] or sin_acentos(o["cadena"]).lower() in sin_acentos(f["nombre"]).lower()):
                                k, mejor = kk, d
            if k is None:
                k = pareja(lat, lng, nombre, 150)
            if k is not None:
                f = filas[k]
                f.setdefault("_extra", {}).update({c: v for c, v in extra.items() if v})
                for c, v in union.items():
                    f.setdefault("_union", {}).setdefault(c, set()).update(v)
                f.setdefault("_forzar", {}).update(forzar)
                f["fuente_ids"] = "|".join(sorted(set(filter(None, f.get("fuente_ids", "").split("|") + [fid]))))
                if fuente in DISC_FUENTE and DISC_FUENTE[fuente] not in f["disciplinas"].split("|"):
                    f["disciplinas"] = "|".join(filter(None, f["disciplinas"].split("|") + [DISC_FUENTE[fuente]]))
                n_fuente_completan[fuente] += 1
                continue
            if fuente == "anytime" and o.get("estatus", "abierto") not in ("abierto", "open", "Open", ""):
                continue
            tipo, disciplinas, cadena = clasificar(nombre + " " + o.get("tipo", ""), [], "")
            if fuente in DISC_FUENTE and DISC_FUENTE[fuente] not in disciplinas:
                disciplinas = list(disciplinas) + [DISC_FUENTE[fuente]]
            vd = vecino_denue(lat, lng)
            r = {
                "place_id": fid, "nombre": nombre, "slug": slug(nombre), "tipo_lugar": tipo, "disciplinas": "|".join(disciplinas),
                "cadena": o.get("cadena") or cadena, "calle": titulo(o.get("calle", "")) if o.get("calle", "").isupper() else o.get("calle", ""),
                "colonia": o.get("colonia") or (titulo(vd.nomb_asent) if vd is not None else ""),
                "ciudad": o.get("ciudad") or (vd.municipio if vd is not None else ""),
                "estado": o.get("estado") or (vd.entidad if vd is not None else ""),
                "cp": o.get("cp") or (vd.cod_postal if vd is not None else ""),
                "lat": round(lat, 7), "lng": round(lng, 7), "google_maps_url": "", "direccion_google": "",
                "telefono": "", "correo": "", "sitio_web": "", "denue_id": "", "sector": "",
                "metro_rango": "", "metropoli": "", "fuente": fuente, "ultima_verificacion": hoy, "osm_id": "", "fuente_ids": fid,
                "_extra": {c: v for c, v in extra.items() if v}, "_union": {c: set(v) for c, v in union.items()}, "_forzar": forzar,
            }
            if vd is not None:
                r["metro_rango"], r["metropoli"] = str(vd.metro_rango), vd.metropoli
            if not r["metro_rango"]:
                continue  # fuera de las metrópolis que cubrimos por ahora
            agregar(r)
            n_fuente_nuevos[fuente] += 1

    # ---------- DENUE sin pareja ----------
    n_denue = n_denue_genericos = 0
    for i, d in denue.iterrows():
        if i in usados_denue or str(d.metro_rango) not in lanzamiento or pd.isna(d.lat):
            continue
        k = pareja(d.lat, d.lng, d.nom_estab)
        if k is not None:
            f = filas[k]
            if not f["denue_id"]:
                f["denue_id"], f["sector"] = d.id, d.sector
                f.setdefault("_extra", {}).update({c: v for c, v in (("telefono", d.telefono), ("correo", d.correoelec.lower()),
                                                                       ("sitio_web", d.www.lower())) if v})
                f["fuente"] += "+denue"
            usados_denue.add(i)
            continue
        nombre = nombre_denue(d.nom_estab)
        if nombre and es_cancha(nombre):
            nombre = ""
        if not nombre:
            n_denue_genericos += 1
            continue
        tipo, disciplinas, cadena = clasificar(nombre, ())
        numero = d.numero_ext if d.numero_ext not in ("0", "") else (d.letra_ext if d.letra_ext not in ("SN", "S/N") else "")
        calle = titulo(" ".join(x for x in (d.tipo_vial if d.tipo_vial not in ("NINGUNO", "CALLE") else "", d.nom_vial, numero) if x))
        r = {
            "place_id": "denue:" + d.id, "nombre": nombre, "slug": slug(nombre), "tipo_lugar": tipo,
            "disciplinas": "|".join(disciplinas), "cadena": cadena, "calle": calle, "colonia": titulo(d.nomb_asent),
            "ciudad": d.municipio, "estado": d.entidad, "cp": d.cod_postal, "lat": round(d.lat, 7), "lng": round(d.lng, 7),
            "google_maps_url": "", "direccion_google": "", "telefono": d.telefono, "correo": d.correoelec.lower(),
            "sitio_web": d.www.lower(), "denue_id": d.id, "sector": d.sector, "metro_rango": str(d.metro_rango),
            "metropoli": d.metropoli, "fuente": "denue", "ultima_verificacion": (d.fecha_alta + "-01") if len(d.fecha_alta) == 7 else hoy,
        }
        if r["sitio_web"] and not r["sitio_web"].startswith("http"):
            r["sitio_web"] = "https://" + r["sitio_web"]
        usados_denue.add(i)
        agregar(r)
        n_denue += 1

    # ---------- Normalizar, conservar ficha publicada y lo enriquecido ----------
    por_denue = {v["denue_id"]: v for v in previo.values() if v.get("denue_id")}
    por_osm = {v["osm_id"]: v for v in previo.values() if v.get("osm_id")}
    por_fid = {}
    for v in previo.values():
        for fi in (v.get("fuente_ids") or "").split("|"):
            if fi:
                por_fid.setdefault(fi, v)
    wp_usados = set()
    for r in filas:
        if r["estado"] in ("México", "State of Mexico", "Méx.", "Edo. Méx."):
            r["estado"] = "Estado de México"
        if r["estado"] == "Ciudad de México":
            r["ciudad"] = "Ciudad de México"
        if r["sector"] == "público" and r["tipo_lugar"] in ("Gimnasio", "Club deportivo"):
            r["tipo_lugar"] = "Deportivo público"
        r.setdefault("osm_id", "")
        r.setdefault("fuente_ids", "")
        r["descripcion"] = descripcion(r)
        ant = previo.get(r["place_id"]) or por_denue.get(r["denue_id"] or "-") or por_osm.get(r["osm_id"] or "-") or {}
        if not ant:
            for fi in r["fuente_ids"].split("|"):
                if fi and fi in por_fid:
                    ant = por_fid[fi]
                    break
        if ant.get("wp_id") in wp_usados:
            ant = {}
        r["wp_id"] = ant.get("wp_id", "")
        r["publicado_el"] = ant.get("publicado_el", "")
        if r["wp_id"]:
            wp_usados.add(r["wp_id"])
        for c in ("sitio_web", "telefono", "correo"):
            if not r[c] and ant.get(c):
                r[c] = ant[c]
        for c in ENRIQUECIDOS:
            r[c] = ant.get(c, "")
        r["descripcion"] = con_opiniones(r["descripcion"], r)
        cambio = bool(ant) and (ant.get("place_id") != r["place_id"] or ant.get("descripcion") != r["descripcion"]
                                or ant.get("nombre") != r["nombre"])
        for c, v in r.pop("_extra", {}).items():
            if v and not r.get(c):
                r[c] = v
                cambio = True
        for c, v in r.pop("_union", {}).items():
            actual = set(filter(None, (r.get(c) or "").split("|")))
            nuevo = actual | set(v)
            if nuevo != actual:
                r[c] = "|".join(sorted(nuevo))
                cambio = True
        for c, v in r.pop("_forzar", {}).items():
            if v and r.get(c) != v:
                r[c] = v
                cambio = True
        r["descripcion"] = con_opiniones(descripcion(r), r)
        if ant and ant.get("descripcion") != r["descripcion"]:
            cambio = True
        if cambio and r["wp_id"]:
            r["pendiente_sync"] = "1"

    base = pd.DataFrame(filas).drop_duplicates("place_id")
    ruta_c = os.path.join(RAIZ, "data", "cerrados.csv")
    if os.path.exists(ruta_c):
        cerr = pd.read_csv(ruta_c, dtype=str).fillna("")
        base = base[~base.place_id.isin(set(cerr.place_id)) & ~(base.wp_id.isin(set(cerr.wp_id)) & (base.wp_id != ""))]
    rec = restaurar_wp_ids(base)
    if rec:
        print(f"wp_id recuperados de la bitácora: {rec}")
    base.to_csv(ruta_base, index=False)
    # fichas publicadas que ya no están en la base (p. ej. canchas): se pasan a borrador
    ruta_ret = os.path.join(RAIZ, "data", "retirar.csv")
    ret = pd.read_csv(ruta_ret, dtype=str).fillna("") if os.path.exists(ruta_ret) else pd.DataFrame(columns=["wp_id", "nombre", "motivo", "retirado_el"])
    vivos = set(base.wp_id) - {""}
    ya = set(ret.wp_id)
    nuevos_ret = [{"wp_id": v["wp_id"], "nombre": v.get("nombre", ""), "motivo": "fuera de la base", "retirado_el": ""}
                  for v in previo.values() if v.get("wp_id") and v["wp_id"] not in vivos and v["wp_id"] not in ya]
    if nuevos_ret:
        pd.concat([ret, pd.DataFrame(nuevos_ret)]).to_csv(ruta_ret, index=False)
    print(f"Por retirar de WordPress: {len(nuevos_ret)}")
    sin = denue.drop(index=list(usados_denue))
    sin = sin[sin.metro_rango.astype(str).isin(lanzamiento)]
    sin.drop(columns=["lat", "lng"]).to_csv(os.path.join(RAIZ, "data", "denue", "sin_pareja.csv"), index=False)
    print(f"Base: {len(base)} lugares | Google: {(base.fuente.str.startswith('google')).sum()} | OSM nuevos: {n_osm_nuevos} "
          f"| OSM completan: {n_osm_completan} | fuentes nuevas: {dict(n_fuente_nuevos)} | fuentes completan: {dict(n_fuente_completan)} | DENUE nuevos: {n_denue} | DENUE genéricos fuera: {n_denue_genericos} "
          f"| descartados Google: {descartados}")
    print(base.tipo_lugar.value_counts().to_string())


if __name__ == "__main__":
    main()
