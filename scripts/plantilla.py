# -*- coding: utf-8 -*-
"""Lee o sube plantillas del tema en gyms52.com (editor de sitio de WordPress).

Lo maneja solicitudes/plantilla.json:
  {"accion": "leer", "plantillas": ["directory//gd-single"]}
    baja cada plantilla a data/plantillas/<slug>.html (con copia fechada en data/plantillas/respaldos/).
  {"accion": "subir", "plantillas": ["directory//gd-single"]}
    respalda la versión del sitio y sube data/plantillas/<slug>.html.
  {"accion": "listar"}
    escribe data/plantillas/lista.txt con las plantillas y partes de plantilla del tema.
  "estilos": true  (con leer o subir)
    baja o sube el CSS adicional de Global Styles (id 14) en data/plantillas/estilos.css.
  "partes": ["directory//header"]  (con leer o subir)
    igual que "plantillas", pero para partes de plantilla.
  "paginas": [{"id": 6, "title": "Agregar un lugar"}]  (con subir)
    cambia el título de páginas.
Necesita WP_USER y WP_APP_PASSWORD.
"""
import datetime as dt
import json
import os

import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(RAIZ, "data", "plantillas")


def main():
    url = os.environ.get("WP_URL", "https://gyms52.com").rstrip("/")
    s = requests.Session()
    s.auth = (os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"])
    s.headers["User-Agent"] = "gyms52-pipeline/1.0"
    sol = json.load(open(os.path.join(RAIZ, "solicitudes", "plantilla.json")))
    accion = sol.get("accion", "leer")
    marca = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M")
    os.makedirs(os.path.join(DIR, "respaldos"), exist_ok=True)
    if accion == "listar" or sol.get("listar"):
        lineas = []
        for tipo in ("templates", "template-parts"):
            r = s.get(f"{url}/wp-json/wp/v2/{tipo}", params={"context": "edit", "per_page": 100}, timeout=60)
            r.raise_for_status()
            for t in r.json():
                lineas.append(f"{tipo}\t{t['id']}\t{t.get('source', '')}\t{t.get('title', {}).get('raw', '')}")
        open(os.path.join(DIR, "lista.txt"), "w").write("\n".join(lineas) + "\n")
        print(f"{len(lineas)} plantillas y partes")
        if accion == "listar":
            return
    if sol.get("estilos"):
        gs = os.environ.get("WP_GLOBAL_STYLES_ID", "14")
        r = s.get(f"{url}/wp-json/wp/v2/global-styles/{gs}", params={"context": "edit"}, timeout=60)
        r.raise_for_status()
        estilos = r.json().get("styles") or {}
        actual = estilos.get("css", "")
        open(os.path.join(DIR, "respaldos", f"estilos_{marca}.css"), "w").write(actual)
        ruta = os.path.join(DIR, "estilos.css")
        if accion == "leer":
            open(ruta, "w").write(actual)
            print(f"estilos: leídos ({len(actual)} caracteres)")
        else:
            nueva = open(ruta).read()
            if nueva == actual:
                print("estilos: sin cambios")
            else:
                estilos["css"] = nueva
                r = s.post(f"{url}/wp-json/wp/v2/global-styles/{gs}", json={"styles": estilos}, timeout=60)
                print(f"estilos: subidos HTTP {r.status_code} {r.text[:200] if r.status_code >= 300 else ''}")
                r.raise_for_status()
    if accion == "subir":
        for pg in sol.get("paginas", []):
            r = s.post(f"{url}/wp-json/wp/v2/pages/{pg['id']}", json={"title": pg["title"]}, timeout=60)
            print(f"página {pg['id']}: título HTTP {r.status_code}")
            r.raise_for_status()
    pares = [("templates", p) for p in sol.get("plantillas", [])] + [("template-parts", p) for p in sol.get("partes", [])]
    for tipo, pid in pares:
        slug = pid.split("//")[-1]
        r = s.get(f"{url}/wp-json/wp/v2/{tipo}/{pid}", params={"context": "edit"}, timeout=60)
        if r.status_code == 404:
            print(f"{pid}: no existe")
            continue
        r.raise_for_status()
        actual = r.json()["content"]["raw"]
        open(os.path.join(DIR, "respaldos", f"{slug}_{marca}.html"), "w").write(actual)
        if accion == "leer":
            open(os.path.join(DIR, f"{slug}.html"), "w").write(actual)
            print(f"{pid}: leída ({len(actual)} caracteres)")
            continue
        nueva = open(os.path.join(DIR, f"{slug}.html")).read()
        if nueva == actual:
            print(f"{pid}: sin cambios")
            continue
        r = s.post(f"{url}/wp-json/wp/v2/{tipo}/{pid}", json={"content": nueva}, timeout=60)
        print(f"{pid}: subida HTTP {r.status_code} {r.text[:200] if r.status_code >= 300 else ''}")
        r.raise_for_status()


if __name__ == "__main__":
    main()
