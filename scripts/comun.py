# -*- coding: utf-8 -*-
"""Utilidades compartidas del pipeline de Gyms +52."""
import csv
import html
import math
import json
import os
import re
import unicodedata

RAIZ_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_WP_IDS = os.path.join(RAIZ_REPO, "data", "wp_ids.csv")


# ---------------------------------------------------------------- bitácora de ids de WordPress
# Cada ficha creada en WordPress se anota aquí (place_id, wp_id) al momento. Solo la escriben
# los procesos de la fila "datos", así que no choca con los push de la tarea de Claude, que
# reescribe base.csv completo. Si base.csv pierde un wp_id, se recupera de aquí y la ficha
# no se vuelve a publicar (eso causó ~850 duplicados el 19 oct 2026).
def registrar_wp_id(place_id, wp_id, nombre=""):
    nuevo = not os.path.exists(RUTA_WP_IDS)
    with open(RUTA_WP_IDS, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["place_id", "wp_id", "nombre"])
        w.writerow([place_id, wp_id, nombre])
        f.flush()


def leer_wp_ids():
    if not os.path.exists(RUTA_WP_IDS):
        return {}
    with open(RUTA_WP_IDS, encoding="utf-8") as f:
        return {r["place_id"]: r["wp_id"] for r in csv.DictReader(f) if r.get("place_id") and r.get("wp_id")}


def restaurar_wp_ids(base):
    """Llena los wp_id vacíos de base con la bitácora. Devuelve cuántos recuperó."""
    ids = leer_wp_ids()
    if not ids or "wp_id" not in base.columns:
        return 0
    usados = set(base.wp_id) - {""}
    n = 0
    for i in base.index[base.wp_id == ""]:
        w = ids.get(base.at[i, "place_id"], "")
        if w and w not in usados:
            base.at[i, "wp_id"] = w
            usados.add(w)
            n += 1
    return n


def clave_titulo(s):
    s = sin_acentos(html.unescape(s or "")).lower().replace("–", "-").replace("—", "-")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def sin_acentos(s):
    return "".join(c for c in unicodedata.normalize("NFD", s or "") if unicodedata.category(c) != "Mn")


def slug(s):
    s = sin_acentos(s).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def norm_nombre(s):
    s = sin_acentos(s or "").lower()
    s = re.sub(r"\b(gym|gimnasio|fitness|club|center|centro|studio|estudio|the|el|la|de|del|sa|cv|s a|c v)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def similitud(a, b):
    """Jaccard de tokens normalizados."""
    ta, tb = set(norm_nombre(a).split()), set(norm_nombre(b).split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def distancia_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ---------------------------------------------------------------- clasificación
# (patrón en nombre normalizado, disciplina = nombre de la categoría en WordPress)
REGLAS_DISCIPLINA = [
    (r"crossfit|cross fit|\bwod\b", "CrossFit"),
    (r"hyrox", "HYROX"),
    (r"funcional|functional|bootcamp|f45|orangetheory|orange theory", "Funcional"),
    (r"bootcamp|boot camp", "Bootcamp"),
    (r"electroestimul|electro estimul|bodytec|xbody|\bems (training|fitness|studio|gym)", "EMS"),
    (r"step aerobic|aerobics step|clases de step|\bstep (class|fitness)", "Step"),
    (r"remo indoor|indoor rowing|rowing (studio|club|fitness)", "Remo indoor"),
    (r"run club|running club|club de corredores", "Running club"),
    (r"ninja (gym|park|parque|warrior|academy)|ninja warrior", "Ninja"),
    (r"\bhiit\b", "HIIT"),
    (r"powerlifting|power lifting", "Powerlifting"),
    (r"halterofilia|weightlifting", "Halterofilia"),
    (r"calistenia|calisthenics|street workout", "Calistenia"),
    (r"strongman", "Strongman"),
    (r"spinning|cycling|cycle|indoor ride|\bride\b|siclo", "Indoor cycling"),
    (r"jumping", "Jumping"),
    (r"reformer", "Pilates reformer"),
    (r"pilates", "Pilates mat"),
    (r"hot yoga|bikram", "Hot yoga"),
    (r"yoga aereo|aerial yoga", "Yoga aéreo"),
    (r"vinyasa", "Vinyasa"),
    (r"ashtanga", "Ashtanga"),
    (r"hatha", "Hatha yoga"),
    (r"yoga", "Yoga"),
    (r"tai ?chi|taichi", "Tai chi"),
    (r"stretching|estiramiento|clases de movilidad|mobility (studio|class)", "Movilidad y stretching"),
    (r"\bbarre\b", "Barre"),
    (r"muay thai|muaythai", "Muay thai"),
    (r"kickboxing|kick boxing", "Kickboxing"),
    (r"\bmma\b|artes marciales mixtas", "MMA"),
    (r"jiu ?jitsu|jiujitsu|\bbjj\b|gracie", "Jiu-jitsu brasileño"),
    (r"\bjudo\b", "Judo"),
    (r"karate", "Karate"),
    (r"taekwondo|tae kwon do|\btkd\b", "Taekwondo"),
    (r"krav maga", "Krav maga"),
    (r"boxeo|boxing|box club|escuela de box|\bbox\b(?! (funcional|training|crossfit))", "Box"),
    (r"lucha", "Lucha"),
    (r"artes marciales|martial|dojo", "Combate"),
    (r"esgrima", "Esgrima"),
    (r"zumba", "Zumba"),
    (r"jazzercise", "Jazzercise"),
    (r"\bpole\b|pole dance|pole fitness", "Pole fitness"),
    (r"ballet", "Ballet"),
    (r"jazz dance|danza jazz|(danza|dance|ballet|academia|escuela|studio).*\bjazz\b|\bjazz\b.*(danza|dance|ballet|academia|escuela)", "Jazz"),
    (r"danza contemporanea|contemporary dance", "Danza contemporánea"),
    (r"telas aereas|danza aerea|aerial (dance|silk|hoop)|acrobacia aerea", "Telas y danza aérea"),
    (r"hip ?hop", "Hip hop"),
    (r"salsa|bachata", "Salsa y bachata"),
    (r"danza|dance|baile", "Baile fitness"),
    (r"aquaerobic|aquafit|hidroaerobic|acuaerobic", "Aquaeróbics"),
    (r"clavados", "Clavados"),
    (r"natacion|swim|alberca|acuatic|aquatic", "Natación"),
    (r"escalada|climbing|boulder|rocodromo", "Boulder"),
    (r"escalada (en|con) cuerda|top ?rope|via ferrata", "Escalada con cuerda"),
    (r"parkour", "Parkour"),
    (r"suplement|nutrition|gnc|proteina|protein", "Suplementos"),
    (r"tenis|tennis", "Tenis"),
    (r"squash", "Squash"),
    (r"padel", "Pádel"),
]

# Disciplinas de público o servicio: se agregan como etiqueta extra, pero no cuentan
# como prueba de que el lugar es de fitness (p. ej. una clínica de fisioterapia).
REGLAS_SECUNDARIAS = [
    (r"\bkids?\b|infantil|para ninos|\bninos\b|baby gym|junior", "Infantil"),
    (r"adulto mayor|adultos mayores|tercera edad|\bsenior", "Adultos mayores"),
    (r"prenatal|embarazad|posparto|postparto|post parto", "Prenatal y posparto"),
    (r"rehabilit|fisioterap|\bfisio\b|kinesio", "Rehabilitación"),
    (r"adaptad|discapacidad|paralimp", "Adaptado"),
    (r"entrenador personal|entrenamiento personal|personal train", "Entrenamiento personal"),
]
DISC_SECUNDARIAS = {d for _, d in REGLAS_SECUNDARIAS}

CADENAS = {
    "smart fit": "Smart Fit", "sports world": "Sports World", "anytime fitness": "Anytime Fitness",
    "energy fitness": "Energy Fitness", "snap fitness": "Snap Fitness", "planet fitness": "Planet Fitness",
    "orangetheory": "Orangetheory", "orange theory": "Orangetheory", "f45": "F45", "siclo": "Siclo",
    "sport city": "Sport City", "bodytech": "Bodytech", "fitness time": "Fitness Time", "gold s gym": "Gold's Gym",
    "golds gym": "Gold's Gym", "bonga": "Bonga Gym", "hard candy": "Hard Candy Fitness", "ultra gym": "Ultra Gym",
}

TIPOS_TIENDA = {"sporting_goods_store", "store", "clothing_store", "shopping_mall", "health_food_store"}
TIPOS_VALIDOS = {"gym", "fitness_center", "yoga_studio", "sports_club", "sports_complex", "sports_activity_location",
                 "swimming_pool", "sporting_goods_store", "athletic_field", "dance_hall", "martial_arts_school",
                 "sports_school", "pilates_studio"}


def clasificar(nombre, tipos=(), pista=""):
    """Devuelve (tipo_lugar, [disciplinas], cadena)."""
    n = sin_acentos(nombre or "").lower()
    texto = n + " " + sin_acentos(pista or "").lower()
    disc = []
    for patron, d in REGLAS_DISCIPLINA:
        if re.search(patron, texto) and d not in disc:
            disc.append(d)
    cadena = next((v for k, v in CADENAS.items() if k in n), "")
    tipos = set(tipos or ())
    if tipos & TIPOS_TIENDA and not tipos & {"gym", "fitness_center"}:
        tipo = "Tienda"
        if not any(d in disc for d in ("Suplementos",)):
            disc.append("Ropa deportiva" if "clothing_store" in tipos else "Equipo de gimnasio")
    elif any(d in disc for d in ("CrossFit", "HYROX")) or re.search(r"\bbox\b.*(funcional|crossfit|training)|training box", n):
        tipo = "Box"
    elif any(d in disc for d in ("Muay thai", "Kickboxing", "MMA", "Jiu-jitsu brasileño", "Judo", "Karate", "Taekwondo", "Krav maga", "Box", "Lucha", "Esgrima", "Combate")):
        tipo = "Gimnasio de combate"
    elif any(d in disc for d in ("Yoga", "Hot yoga", "Yoga aéreo", "Vinyasa", "Ashtanga", "Hatha yoga", "Tai chi", "Pilates mat",
                                 "Pilates reformer", "Barre", "Indoor cycling", "Jumping", "EMS")):
        tipo = "Estudio"
    elif any(d in disc for d in ("Ballet", "Hip hop", "Salsa y bachata", "Baile fitness", "Pole fitness", "Zumba", "Jazzercise", "Jazz",
                                 "Danza contemporánea", "Telas y danza aérea")) and not tipos & {"gym", "fitness_center"}:
        tipo = "Escuela de danza"
    elif "Natación" in disc and ("swimming_pool" in tipos or "natacion" in n or "acuatic" in n):
        tipo = "Centro acuático"
    elif "Boulder" in disc:
        tipo = "Muro de escalada"
    elif re.search(r"\bdeportivo\b|unidad deportiva|polideportivo", n):
        tipo = "Deportivo público" if re.search(r"municipal|unidad deportiva|deportivo [a-z]+$", n) else "Club deportivo"
    elif tipos & {"sports_club", "sports_complex"} or re.search(r"\bclub\b", n) and not cadena:
        tipo = "Club deportivo"
    else:
        tipo = "Gimnasio"
    if tipo in ("Gimnasio", "Club deportivo") and not disc:
        disc.append("Pesas")
    if not disc:
        disc.append("Pesas" if tipo != "Tienda" else "Equipo de gimnasio")
    if tipo != "Tienda":
        for patron, d in REGLAS_SECUNDARIAS:
            if re.search(patron, n) and d not in disc:
                disc.append(d)
    return tipo, disc, cadena


def limpiar_nombre(s):
    """Quita emojis y símbolos sueltos del nombre que da Google."""
    s = "".join(c for c in (s or "") if unicodedata.category(c)[0] in "LNPZ" or c in "&+'-.")
    return re.sub(r"\s{2,}", " ", s).strip(" -|·•")


# ---------- Fuentes abiertas: OpenStreetMap y DENUE ----------
DIAS_GD = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


def horario_texto_gd(por_dia):
    """{'Mo': ['06:00-22:00'], ...} → formato de horario de GeoDirectory."""
    rangos = [f"{d} {','.join(por_dia[d])}" for d in DIAS_GD if por_dia.get(d)]
    if not rangos:
        return ""
    return json.dumps(rangos, ensure_ascii=False, separators=(",", ":")) + ',["UTC":"-6","Timezone":"America/Mexico_City"]'


def horario_osm(texto):
    """Convierte opening_hours de OSM (casos comunes) al formato de GeoDirectory. Si no lo entiende, regresa ''."""
    texto = (texto or "").strip()
    if not texto:
        return ""
    if texto == "24/7":
        return horario_texto_gd({d: ["00:00-23:59"] for d in DIAS_GD})
    por_dia = {d: [] for d in DIAS_GD}
    for regla in [r.strip() for r in texto.split(";") if r.strip()]:
        m = re.fullmatch(r"((?:Mo|Tu|We|Th|Fr|Sa|Su)(?:\s*[-,]\s*(?:Mo|Tu|We|Th|Fr|Sa|Su))*)?\s*(.+)", regla)
        if not m:
            return ""
        dias_txt, horas_txt = m.group(1), m.group(2).strip()
        dias = []
        for parte in (dias_txt or "Mo-Su").replace(" ", "").split(","):
            if "-" in parte:
                i, f = DIAS_GD.index(parte[:2]), DIAS_GD.index(parte[3:5])
                dias += [DIAS_GD[k % 7] for k in range(i, f + 1 if f >= i else f + 8)]
            else:
                dias.append(parte)
        if horas_txt in ("off", "closed"):
            for d in dias:
                por_dia[d] = []
            continue
        horas = []
        for h in horas_txt.split(","):
            hm = re.fullmatch(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", h.strip())
            if not hm:
                return ""
            a, b = f"{int(hm.group(1)):02d}:{hm.group(2)}", f"{int(hm.group(3)):02d}:{hm.group(4)}"
            if b in ("24:00", "00:00"):
                b = "23:59"
            horas.append(f"{a}-{b}")
        for d in dias:
            por_dia[d] = horas
    return horario_texto_gd(por_dia)


GENERICAS_NOMBRE = set("""gimnasio gimnacio gimnasios gym gyms clases clase de del la el los las y e en zumba fitness
spinning crossfit cardio box boxeo yoga pilates danza baile bailes academia escuela centro centros acondicionamiento
fisico fisica sector privado publico sin nombre deportivo deportiva unidad sport sports club estudio studio funcional
entrenamiento aerobics aerobicos aerobic fit training trainer power body center artes marciales karate taekwondo judo
natacion alberca pesas kick kickboxing tae kwon do muay thai mma ballet jazz salon sala""".split())
MAYUS = {"mma", "hiit", "hyrox", "cdmx", "ufc", "trx", "bjj", "cf", "ii", "iii", "iv", "imss", "issste", "unam", "ipn"}
MINUS = {"de", "del", "la", "el", "los", "las", "y", "e", "en", "a", "con", "por", "para"}


def nombre_denue(s):
    """Nombre de DENUE en tipo título. Regresa '' si es genérico ("GIMNASIO", "ZUMBA SIN NOMBRE")."""
    s = limpiar_nombre(s)
    if not s or "sin nombre" in s.lower():
        return ""
    palabras = re.findall(r"[a-z0-9ñ]+", sin_acentos(s.lower()))
    if not [w for w in palabras if w not in GENERICAS_NOMBRE and len(w) >= 3]:
        return ""
    return titulo(s)


def titulo(s):
    """Tipo título en español: "CALLE LERDO DE TEJADA" → "Calle Lerdo de Tejada"."""
    salida = []
    for k, w in enumerate((s or "").split()):
        base = sin_acentos(w.lower()).strip(".,")
        if base in MAYUS:
            salida.append(w.upper())
        elif base in MINUS and k > 0:
            salida.append(w.lower())
        else:
            salida.append(w[:1].upper() + w[1:].lower())
    return " ".join(salida)


# Canchas y campos de deportes de equipo: no son lugares de entrenamiento (DENUE y OSM los traen mezclados)
RE_CANCHA = re.compile(r"\b(cancha|canchas|campo de fut|campo de beis|futbol rapido|f[uú]tbol r[aá]pido|fut ?7|futbol 7|"
                       r"fut[bv]ol(?! americano)|futball|soccer(?! ?city)|front[oó]n|beisbol|b[eé]isbol|basquet|b[aá]squetbol|"
                       r"padel|p[aá]del|tenis club|club de tenis|campo de golf|golf)\b", re.I)
RE_ENTRENA = re.compile(r"gimnasio|gym|fitness|box\b|crossfit|pesas|funcional|entrenamiento|alberca|nataci|yoga|pilates|dojo|karate|tae", re.I)


def es_cancha(nombre):
    n = sin_acentos(nombre or "")
    return bool(RE_CANCHA.search(n)) and not RE_ENTRENA.search(n)
