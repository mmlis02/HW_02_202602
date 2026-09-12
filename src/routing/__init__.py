"""Fase 2 — Routing y cómputo de tiempos de viaje.

Motor: NetworkX sobre un grafo construido a partir de un extracto de OSM
(pyrosm), NO OSRM local (ver docs/01_routing_decision.md: bloqueo real de
RAM/disco para un runtime de contenedores en esta máquina). Diseño modular para
poder sustituir el motor más adelante sin tocar el resto del proyecto:
``osm_extract`` y ``graph_build`` son lo único acoplado a "cómo se obtiene el
grafo"; ``matrix``, ``snapping``, ``compare`` trabajan contra la interfaz
genérica de un ``networkx.DiGraph`` con peso ``time_s``/``length``.
"""
