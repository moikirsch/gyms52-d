# -*- coding: utf-8 -*-
"""Utilidades compartidas del pipeline de Gyms +52."""
import math
import re
import unicodedata


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
    (r"yoga", "Yoga"),
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
    (r"hip ?hop", "Hip hop"),
    (r"salsa|bachata", "Salsa y bachata"),
    (r"danza|dance|baile", "Baile fitness"),
    (r"natacion|swim|alberca|acuatic|aquatic", "Natación"),
    (r"escalada|climbing|boulder|rocodromo", "Boulder"),
    (r"parkour", "Parkour"),
    (r"suplement|nutrition|gnc|proteina|protein", "Suplementos"),
    (r"tenis|tennis", "Tenis"),
    (r"squash", "Squash"),
    (r"padel", "Pádel"),
]

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
    elif any(d in disc for d in ("Yoga", "Hot yoga", "Yoga aéreo", "Pilates mat", "Pilates reformer", "Barre", "Indoor cycling", "Jumping")):
        tipo = "Estudio"
    elif any(d in disc for d in ("Ballet", "Hip hop", "Salsa y bachata", "Baile fitness", "Pole fitness", "Zumba", "Jazzercise")) and not tipos & {"gym", "fitness_center"}:
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
    return tipo, disc, cadena


def limpiar_nombre(s):
    """Quita emojis y símbolos sueltos del nombre que da Google."""
    s = "".join(c for c in (s or "") if unicodedata.category(c)[0] in "LNPZ" or c in "&+'-.")
    return re.sub(r"\s{2,}", " ", s).strip(" -|·•")
