"""Perfiles de velocidad y accesibilidad — car / bike / foot.

**Todo lo de aquí es un SUPUESTO DEL MODELO, no un dato observado.** OSM no
tiene un campo "tiempo de viaje"; solo tags (`highway`, `maxspeed`, `oneway`,
`surface`, `access`, `bicycle`, `foot`, `motor_vehicle`, `junction`). Este
módulo traduce esos tags a una velocidad y una dirección explícitas para cada
modo, documentadas caso por caso, parametrizadas en `config.md`
`routing.profiles`. Si dos analistas usaran velocidades distintas, obtendrían
tiempos distintos — eso es exactamente lo que hace explícito este archivo.

**Corrección de auditoría (2026-09-11)**: `track` se HABILITA para car (antes
excluido). La auditoría independiente de Fase 2 encontró que 1313/5000 demand
points snapeaban a un nodo sin ninguna arista transitable en auto, y que el
100% de una muestra de esos nodos solo tenía aristas `track`/`path` — excluir
`track` subestimaba el acceso vehicular rural de forma material (una muestra
controlada mostró ~30% de recuperación de conectividad). Se habilita con una
velocidad de fallback CONSERVADORA Y CONFIGURABLE (`config.md`
`routing.car_track_fallback_speed_kmh`, default 12 km/h) — un supuesto de
modelización explícito, **no** una velocidad promedio observada en Perú.
`path`, `footway`, `pedestrian`, `steps`, `cycleway` siguen excluidos de car.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# --- Vías nunca transitables (ninguna de las 3 categorías las usa) ----------
_NEVER_TRANSITABLE = {"proposed", "construction", "abandoned", "razed", "platform", "raceway"}

# ============================================================ CAR ==========
# Velocidad fallback (km/h) por tipo de vía cuando maxspeed falta o es inválido.
CAR_SPEED_KMH_BY_HIGHWAY = {
    "motorway": 100, "motorway_link": 60,
    "trunk": 90, "trunk_link": 50,
    "primary": 80, "primary_link": 45,
    "secondary": 60, "secondary_link": 40,
    "tertiary": 50, "tertiary_link": 35,
    "unclassified": 40,
    "residential": 30,
    "living_street": 15,
    "service": 20,
    # "track" NO va aquí: tiene su propio parámetro configurable (ver abajo),
    # separado de esta tabla porque es la pieza que la auditoría señaló como
    # más sensible/menos verificable — se quiere poder afinarla sola.
}
CAR_DEFAULT_SPEED_KMH = 30.0

#: Velocidad de fallback para `highway=track` en el perfil CAR — SUPUESTO DE
#: MODELIZACIÓN explícito (no una velocidad observada en campo en Perú),
#: elegido como conservador dado que una trocha rural típicamente no está
#: afirmada. Configurable vía `config.md` `routing.car_track_fallback_speed_kmh`;
#: la arquitectura queda preparada para un análisis de sensibilidad posterior
#: (ver `docs/01_routing_decision.md` §6) — este valor puede y debe revisarse.
CAR_TRACK_FALLBACK_SPEED_KMH_DEFAULT = 12.0

# Vías que un auto nunca puede usar (además de _NEVER_TRANSITABLE). "track" se
# retiró de este conjunto el 2026-09-11 (ver docstring del módulo) — sigue
# excluyendo explícitamente lo que nunca tiene sentido para un vehículo motor.
CAR_EXCLUDED_HIGHWAY = {
    "footway", "path", "pedestrian", "steps", "cycleway", "bridleway",
    "corridor",
}

# ============================================================ BIKE =========
BIKE_SPEED_KMH_BY_HIGHWAY = {
    "cycleway": 18,
    "primary": 16, "primary_link": 14,
    "secondary": 15, "secondary_link": 14,
    "tertiary": 15, "tertiary_link": 14,
    "unclassified": 14,
    "residential": 14,
    "living_street": 10,
    "service": 12,
    "track": 10,
    "path": 9,
    "footway": 8,
    "pedestrian": 6,
    "steps": 2,
}
BIKE_DEFAULT_SPEED_KMH = 12.0
# highway de alta velocidad donde se asume prohibida la bici salvo bicycle=yes explícito.
BIKE_HIGHSPEED_EXCLUDED = {"motorway", "motorway_link", "trunk", "trunk_link"}

# ============================================================ FOOT =========
FOOT_SPEED_KMH = 5.0            # OMS/ingeniería de tránsito: velocidad peatonal típica
FOOT_SPEED_KMH_STEPS = 2.0      # escaleras: mucho más lento, supuesto explícito
# highway de alta velocidad donde se asume prohibido caminar salvo foot=yes explícito.
FOOT_HIGHSPEED_EXCLUDED = {"motorway", "motorway_link", "trunk", "trunk_link"}

# ======================================================= VERSIONES DE LÓGICA
# Partes de las reglas de abajo que son CÓDIGO, no datos/tablas — no se pueden
# hashear automáticamente. Si se cambia la lógica de oneway o el parseo de
# maxspeed, hay que subir manualmente esta versión para que el hash de
# perfil (y por tanto el cache) se invalide. Documentado explícitamente en vez
# de fingir que el hash cubre "todo" por magia.
ONEWAY_LOGIC_VERSION = "v1-2026-09-11"
MAXSPEED_PARSE_LOGIC_VERSION = "v1-2026-09-11"


@dataclass
class EdgeWeight:
    speed_kmh: float
    time_s: float
    length_m: float
    forward: bool   # permite u->v
    backward: bool  # permite v->u


def _parse_maxspeed(raw) -> float | None:
    """Extrae un número de km/h de un valor `maxspeed` de OSM.

    Tolera: "60", "60 km/h", "60kmh", "50;40" (toma el primero), "walk"/"none"/
    "signals" (no numérico -> None, se usa el fallback por highway).
    """
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if not s or s in ("none", "signals", "walk", "variable"):
        return None
    first = s.split(";")[0].split(",")[0].strip()
    digits = "".join(ch for ch in first if ch.isdigit() or ch == ".")
    if not digits:
        return None
    try:
        val = float(digits)
    except ValueError:
        return None
    if "mph" in first:
        val *= 1.60934
    return val if 3.0 <= val <= 150.0 else None


def _is_no_access(tags: dict, keys: tuple[str, ...]) -> bool:
    for k in keys:
        v = tags.get(k)
        if v is not None and str(v).strip().lower() in ("no", "private"):
            return True
    return False


def _oneway_direction(tags: dict) -> tuple[bool, bool]:
    """Regla compartida car/bike (salvo contraflujo de bici): oneway/rotonda."""
    oneway_raw = str(tags.get("oneway") or "").strip().lower()
    is_roundabout = str(tags.get("junction") or "").strip().lower() == "roundabout"
    if oneway_raw in ("yes", "1", "true") or (is_roundabout and oneway_raw not in ("no", "0", "false")):
        return True, False
    elif oneway_raw in ("-1", "reverse"):
        return False, True
    return True, True


def car_edge_weight(tags: dict, length_m: float, *, track_fallback_speed_kmh: float = CAR_TRACK_FALLBACK_SPEED_KMH_DEFAULT) -> EdgeWeight | None:
    """None si el auto no puede usar esta vía en absoluto.

    `track_fallback_speed_kmh`: supuesto de modelización configurable (ver
    docstring del módulo) — se usa SOLO si `highway=track` y no hay `maxspeed`
    válido; si hay `maxspeed` válido en un track, se respeta igual que en
    cualquier otra vía (misma lógica general).
    """
    highway = tags.get("highway")
    if highway is None or highway in _NEVER_TRANSITABLE or highway in CAR_EXCLUDED_HIGHWAY:
        return None
    if _is_no_access(tags, ("access", "motor_vehicle")):
        return None

    maxspeed = _parse_maxspeed(tags.get("maxspeed"))
    if maxspeed is not None:
        speed = maxspeed
    elif highway == "track":
        speed = track_fallback_speed_kmh
    else:
        speed = CAR_SPEED_KMH_BY_HIGHWAY.get(highway, CAR_DEFAULT_SPEED_KMH)

    forward, backward = _oneway_direction(tags)
    time_s = length_m / (speed * 1000.0 / 3600.0)
    return EdgeWeight(speed_kmh=speed, time_s=time_s, length_m=length_m, forward=forward, backward=backward)


def bike_edge_weight(tags: dict, length_m: float, **_kw) -> EdgeWeight | None:
    highway = tags.get("highway")
    if highway is None or highway in _NEVER_TRANSITABLE:
        return None
    bicycle_tag = str(tags.get("bicycle") or "").strip().lower()
    if highway in BIKE_HIGHSPEED_EXCLUDED and bicycle_tag != "yes":
        return None
    if highway == "steps" and bicycle_tag != "yes":
        return None
    if bicycle_tag == "no":
        return None
    if _is_no_access(tags, ("access",)) and bicycle_tag not in ("yes", "permissive", "designated"):
        return None

    speed = BIKE_SPEED_KMH_BY_HIGHWAY.get(highway, BIKE_DEFAULT_SPEED_KMH)

    # Dirección: igual que autos, salvo que la bici tenga contraflujo explícito.
    oneway_bike = str(tags.get("oneway:bicycle") or "").strip().lower()
    cycleway = str(tags.get("cycleway") or "").strip().lower()
    bike_contraflow = oneway_bike == "no" or cycleway in ("opposite", "opposite_lane", "opposite_track")
    if bike_contraflow:
        forward, backward = True, True
    else:
        forward, backward = _oneway_direction(tags)

    time_s = length_m / (speed * 1000.0 / 3600.0)
    return EdgeWeight(speed_kmh=speed, time_s=time_s, length_m=length_m, forward=forward, backward=backward)


def foot_edge_weight(tags: dict, length_m: float, **_kw) -> EdgeWeight | None:
    highway = tags.get("highway")
    if highway is None or highway in _NEVER_TRANSITABLE:
        return None
    foot_tag = str(tags.get("foot") or "").strip().lower()
    if highway in FOOT_HIGHSPEED_EXCLUDED and foot_tag != "yes":
        return None
    if foot_tag == "no":
        return None
    if _is_no_access(tags, ("access",)) and foot_tag not in ("yes", "permissive", "designated"):
        return None

    speed = FOOT_SPEED_KMH_STEPS if highway == "steps" else FOOT_SPEED_KMH
    time_s = length_m / (speed * 1000.0 / 3600.0)
    # Regla explícita del enunciado: oneway vehicular NUNCA restringe a pie,
    # salvo una restricción peatonal explícita (rarísima en la práctica).
    oneway_foot = str(tags.get("oneway:foot") or "").strip().lower()
    if oneway_foot in ("yes", "1", "true"):
        forward, backward = True, False
    elif oneway_foot in ("-1", "reverse"):
        forward, backward = False, True
    else:
        forward, backward = True, True

    return EdgeWeight(speed_kmh=speed, time_s=time_s, length_m=length_m, forward=forward, backward=backward)


def make_edge_weight_fn(mode: str, cfg: dict | None = None):
    """Fábrica: cierra los parámetros efectivos de `cfg` sobre la función de
    peso de `mode`, para que `graph_build.py` solo necesite llamar
    `fn(tags, length_m)` sin preocuparse de config."""
    if mode == "car":
        track_speed = _car_track_fallback_speed(cfg)
        return lambda tags, length_m: car_edge_weight(tags, length_m, track_fallback_speed_kmh=track_speed)
    return PROFILE_FUNCS[mode]


def _car_track_fallback_speed(cfg: dict | None) -> float:
    if not cfg:
        return CAR_TRACK_FALLBACK_SPEED_KMH_DEFAULT
    try:
        return float(cfg["routing"]["car_track_fallback_speed_kmh"])
    except (KeyError, TypeError, ValueError):
        return CAR_TRACK_FALLBACK_SPEED_KMH_DEFAULT


PROFILE_FUNCS = {"car": car_edge_weight, "bike": bike_edge_weight, "foot": foot_edge_weight}


# ================================================== HASH DE PERFIL (cache) ==
def effective_profile_params(mode: str, cfg: dict | None = None) -> dict:
    """Todos los parámetros que determinan las aristas/pesos de `mode`.

    Se hashea esto (no el texto de `profiles.py`) para versionar el cache:
    cambiar una velocidad o una regla de exclusión cambia este dict y por
    tanto el hash, sin depender de que nadie se acuerde de borrar una carpeta
    a mano. Las partes que son lógica de código pura (oneway, parseo de
    maxspeed) se incluyen como una "versión" manual — ver
    `ONEWAY_LOGIC_VERSION`/`MAXSPEED_PARSE_LOGIC_VERSION` arriba.
    """
    common = {
        "never_transitable": sorted(_NEVER_TRANSITABLE),
        "oneway_logic_version": ONEWAY_LOGIC_VERSION,
        "maxspeed_parse_logic_version": MAXSPEED_PARSE_LOGIC_VERSION,
        "maxspeed_valid_range_kmh": [3.0, 150.0],
    }
    if mode == "car":
        return {
            **common,
            "mode": "car",
            "speed_kmh_by_highway": CAR_SPEED_KMH_BY_HIGHWAY,
            "default_speed_kmh": CAR_DEFAULT_SPEED_KMH,
            "excluded_highway": sorted(CAR_EXCLUDED_HIGHWAY),
            "track_fallback_speed_kmh": _car_track_fallback_speed(cfg),
            "access_keys": ["access", "motor_vehicle"],
        }
    if mode == "bike":
        return {
            **common,
            "mode": "bike",
            "speed_kmh_by_highway": BIKE_SPEED_KMH_BY_HIGHWAY,
            "default_speed_kmh": BIKE_DEFAULT_SPEED_KMH,
            "highspeed_excluded": sorted(BIKE_HIGHSPEED_EXCLUDED),
            "access_keys": ["access"],
        }
    if mode == "foot":
        return {
            **common,
            "mode": "foot",
            "speed_kmh": FOOT_SPEED_KMH,
            "speed_kmh_steps": FOOT_SPEED_KMH_STEPS,
            "highspeed_excluded": sorted(FOOT_HIGHSPEED_EXCLUDED),
            "access_keys": ["access"],
        }
    raise ValueError(f"modo desconocido: {mode}")


def profile_hash(mode: str, cfg: dict | None = None, length: int = 16) -> str:
    """Hash determinístico de los parámetros EFECTIVOS del perfil `mode`.

    Dos corridas con la misma `cfg` y el mismo código de `profiles.py` dan el
    mismo hash; cambiar una velocidad, una exclusión, o el track fallback,
    cambia el hash. Se usa como componente de la clave de cache de grafos y
    matrices — ver `src/routing/matrix.py` y `graph_build.py`.
    """
    params = effective_profile_params(mode, cfg)
    payload = json.dumps(params, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
