"""src.dashboard — lógica del dashboard de Fase 4, separada de Streamlit.

Ningún módulo de este paquete debe recalcular routing, cambiar pesos
estadísticos, ni modificar la muestra — todo se lee de `data/processed/` y
`data/outputs/` (outputs ya precomputados en Fases 1-3, o
`data/outputs/dashboard_*` precomputados por
`scripts/precompute_dashboard_outputs.py`).

`kpis.py`, `filters.py` y `scenario.py` son Python/pandas puro — sin
`import streamlit` — para poder testearse sin lanzar la app (ver
`tests/test_dashboard_*.py`). `data.py`, `maps.py`, `charts.py` y
`quality.py` sí pueden usar Streamlit (cache, construcción de figuras para
`st.plotly_chart`/`st_folium`), pero no contienen lógica de cálculo
reutilizable — esa vive en los módulos puros.
"""
