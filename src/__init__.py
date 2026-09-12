"""Paquete fuente del proyecto de accesibilidad a emergencias resolutivas.

Módulos (se implementan por fases; ver README.md §Fases):

- ``config``        Fase 0 — carga de config.md. IMPLEMENTADO.
- ``acquisition``   Fase 1 — descarga reproducible de fuentes oficiales. IMPLEMENTADO.
- ``boundaries``    Fase 1 — límites IGN (deptos/provincias derivadas/distritos). IMPLEMENTADO.
- ``validation``    Fase 1 — las 6 reglas de validación obligatorias + auditoría. IMPLEMENTADO.
- ``facilities``    Fase 1 — normalización RENIPRESS y filtro de resolutivos. IMPLEMENTADO.
- ``demand``        Fase 1 — centros poblados y muestreo (<= 5000 puntos). IMPLEMENTADO.
- ``routing``       Fase 2 — motor de ruteo y matrices de tiempo de viaje. PENDIENTE.
- ``metrics``       Fase 3 — indicadores de acceso y brechas. PENDIENTE.
- ``analysis``      Fase 3 — agregación por depto/provincia/distrito, urbano/rural. PENDIENTE.
- ``visualization`` Fase 3/4 — mapas y figuras. PENDIENTE.
"""
