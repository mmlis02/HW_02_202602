"""maps — construcción de mapas folium (Fase 4, corregido 2026-09-12).
Devuelve objetos `folium.Map`; el renderizado en la app usa
`streamlit_folium.st_folium`.

Los distritos SIN datos suficientes (`district_status != "computable"`) se
pintan en gris neutro, NUNCA como si tuvieran tiempo 0/bajo — un color
"malo" ahí confundiría "sin información" con "buen acceso" o "mal acceso".

Corrección 2026-09-11 (bug de viewport #1): el mapa NUNCA usa un centro/zoom
fijo. El viewport SIEMPRE se calcula con `fit_bounds()` a partir de las
geometrías distritales que corresponden al filtro geográfico activo (nunca
a partir de puntos de facilities) — ver `compute_bounds` (función pura,
testeada) y su uso en `build_choropleth_map`.

Corrección 2026-09-12 (bug de viewport #2 — `st_folium`): `fit_bounds()`
solo tiene efecto si el componente `st_folium` se REMONTA; con una `key`
fija (o sin key), streamlit-folium intenta preservar el pan/zoom anterior
entre reruns aunque el objeto `folium.Map` cambie. La `key` dependiente del
filtro vive en `app.py` (no aquí), pero se documenta porque es la otra mitad
de este mismo bug.

Corrección 2026-09-12 (bug de "todos los distritos grises"): la causa REAL
no era un late-binding de lambdas en un loop (no existía tal loop — solo hay
un `style_function` para un único `GeoJson`). La causa real era que
`merged_display["district_status"]` se SOBRESCRIBÍA con la etiqueta legible
("Computable") para el tooltip, y ESA MISMA columna (ya sobrescrita) era la
que `style_function` leía para decidir el color — comparar
`"Computable" != "computable"` (con mayúscula) es SIEMPRE `True`, así que
absolutamente todos los distritos, computables o no, caían en la rama
"insufficient data" (gris). Corregido: se mantiene `district_status` con su
valor RAW para el estilo, y se añade una columna NUEVA
(`district_status_label`) solo para el tooltip — nunca se sobrescribe la
columna de la que depende la lógica.

Corrección 2026-09-12 (CARTO): CARTO Dark Matter ahora exige API key y
mostraba el watermark "API KEY REQUIRED". Se reemplaza por
`tiles="OpenStreetMap"` (built-in de folium, sin key, sin credenciales) —
sacrificando la estética oscura a favor de reproducibilidad.
"""

from __future__ import annotations

import branca.colormap as cm
import folium
import geopandas as gpd
import pandas as pd
from folium.plugins import MarkerCluster

INSUFFICIENT_DATA_COLOR = "#bdbdbd"  # gris neutro, pensado para basemap CLARO (OSM estándar)
STATUS_LABELS = {
    "computable": "Computable",
    "low_routing_coverage": "Baja cobertura de ruteo",
    "zero_routing_coverage": "Sin ninguna ruta calculada",
    "low_population_sample_coverage": "Muestra insuficiente (población)",
    "zero_population_sample_coverage": "Sin muestra con población",
    "calibration_impossible": "Calibración imposible (sin muestra)",
}
COMPUTABLE = "computable"

#: Escala secuencial tiempo bajo -> claro, tiempo alto -> rojo oscuro
#: (YlOrRd), NUNCA diverging.
SEQUENTIAL_COLORS = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#800026"]

LAYER_COLORS = {
    "Resolutivo": "#1b7837",
    "Candidato upgrade (I-3/I-4)": "#d95f02",
    "Otro": "#7570b3",
}


def compute_bounds(gdf: gpd.GeoDataFrame | None) -> list[list[float]] | None:
    """Bounds `[[min_lat, min_lon], [max_lat, max_lon]]` (formato
    `folium.Map.fit_bounds`) a partir de la geometría de `gdf` — NUNCA de
    puntos de facilities. Devuelve `None` si `gdf` es vacío o sus geometrías
    no producen un bounds válido (p.ej. todas nulas), para que el llamador
    pueda mostrar un mensaje de "sin datos" en vez de fallar."""
    if gdf is None or len(gdf) == 0:
        return None
    minx, miny, maxx, maxy = gdf.total_bounds
    if any(v != v for v in (minx, miny, maxx, maxy)):  # NaN check, sin depender de numpy aquí
        return None
    return [[miny, minx], [maxy, maxx]]


def _is_missing(val) -> bool:
    return val is None or (isinstance(val, float) and val != val)


def build_colormap(computable: pd.DataFrame) -> cm.LinearColormap | None:
    """Colormap secuencial calculado SOLO sobre distritos
    `district_status == "computable"` con `weighted_mean_access_min` no
    nulo — los distritos insufficient-data nunca entran en el min/max de
    la escala."""
    valid = computable["weighted_mean_access_min"].dropna()
    if not len(valid):
        return None
    vmin, vmax = float(valid.min()), float(valid.max())
    if vmin == vmax:
        vmax = vmin + 1e-9  # evita división por cero en branca si todos los valores son iguales
    return cm.LinearColormap(colors=SEQUENTIAL_COLORS, vmin=vmin, vmax=vmax)


def resolve_fill_color(status: str | None, value: float | None, colormap: cm.LinearColormap | None) -> str:
    """Única fuente de verdad para el color de relleno de UN distrito —
    usada tanto por `style_function` como por los tests/diagnóstico
    (`describe_render_stats`), para que no puedan divergir. Gris SOLO si
    `status != "computable"` o el valor falta; nunca por defecto."""
    if status != COMPUTABLE or _is_missing(value) or colormap is None:
        return INSUFFICIENT_DATA_COLOR
    return colormap(value)


def describe_render_stats(merged: pd.DataFrame) -> dict:
    """Diagnóstico REAL (no solo HTML) de lo que se va a renderizar —
    pensado para imprimirse/testear antes de construir el mapa: N total, N
    computable, N insuficiente, min/max de tiempo, y CUÁNTOS colores
    distintos resultarían. Si hay múltiples valores computables distintos
    pero `n_unique_render_colors == 1`, hay un bug (p.ej. el de
    sobrescritura de `district_status` corregido en esta versión)."""
    n_total = len(merged)
    is_computable = merged["district_status"] == COMPUTABLE
    n_computable = int(is_computable.sum())
    n_insufficient = n_total - n_computable
    colormap = build_colormap(merged[is_computable])
    valid = merged.loc[is_computable, "weighted_mean_access_min"].dropna()
    colors = {resolve_fill_color(COMPUTABLE, v, colormap) for v in valid}
    return {
        "n_total": n_total,
        "n_computable": n_computable,
        "n_insufficient": n_insufficient,
        "vmin": float(valid.min()) if len(valid) else None,
        "vmax": float(valid.max()) if len(valid) else None,
        "n_unique_render_colors": len(colors),
    }


def build_choropleth_map(
    district_geom: gpd.GeoDataFrame, district_metrics: pd.DataFrame, *, bounds_padding: tuple[int, int] = (20, 20),
) -> folium.Map | None:
    """Mapa principal: choropleth de `weighted_mean_access_min` por
    distrito. `district_metrics` debe venir YA FILTRADO por el sidebar
    (departamento/provincia/distrito) -- el merge es INNER, así que solo se
    dibujan (y solo entran en el cálculo del viewport) los distritos del
    filtro activo. Devuelve `None` si no queda ningún distrito (selección
    vacía) para que el llamador muestre un mensaje en vez de un mapa vacío.

    Basemap: OpenStreetMap estándar (sin API key, sin watermark) — ver
    docstring del módulo (CARTO Dark Matter retirado)."""
    merged = district_geom.merge(district_metrics, on="UBIGEO", how="inner")
    if merged.empty:
        return None

    bounds = compute_bounds(merged)
    if bounds is None:
        return None

    colormap = build_colormap(merged[merged["district_status"] == COMPUTABLE])

    fmap = folium.Map(tiles="OpenStreetMap", control_scale=False)
    fmap.fit_bounds(bounds, padding=bounds_padding)

    def _style(feature):
        props = feature["properties"]
        fill = resolve_fill_color(props.get("district_status"), props.get("weighted_mean_access_min"), colormap)
        is_insufficient = fill == INSUFFICIENT_DATA_COLOR
        return {
            "fillColor": fill,
            "color": "#8a8a8a" if is_insufficient else "#555555",
            "weight": 0.5,
            "fillOpacity": 0.55 if is_insufficient else 0.8,
        }

    tooltip_fields = ["DIST", "PROV", "DEP", "weighted_mean_access_min", "known_population", "pct_le_30", "pct_le_60_cum", "pct_le_120_cum", "pct_no_time_estimate", "district_status_label"]
    tooltip_aliases = ["Distrito", "Provincia", "Departamento", "Tiempo medio (min)", "Población (calibrada)", "% ≤30 min", "% ≤60 min (acum)", "% ≤120 min (acum)", "% sin tiempo estimable", "Calidad del dato"]

    # OJO (bug corregido): `district_status` se conserva INTACTO (es el que
    # lee `_style`/`resolve_fill_color`). La etiqueta legible para el
    # tooltip va en una columna NUEVA, nunca sobrescribiendo la original.
    merged_display = merged.copy()
    merged_display["district_status_label"] = merged_display["district_status"].map(STATUS_LABELS).fillna(merged_display["district_status"])
    for col in ["weighted_mean_access_min", "known_population", "pct_le_30", "pct_le_60_cum", "pct_le_120_cum", "pct_no_time_estimate"]:
        merged_display[col] = merged_display[col].round(1)

    folium.GeoJson(
        merged_display,
        style_function=_style,
        tooltip=folium.GeoJsonTooltip(fields=tooltip_fields, aliases=tooltip_aliases, sticky=True),
        name="Tiempo de acceso por distrito",
        control=False,
    ).add_to(fmap)

    if colormap is not None:
        _add_vertical_legend(fmap, vmin=colormap.vmin, vmax=colormap.vmax)
    _add_insufficient_data_note(fmap)

    return fmap


def _add_vertical_legend(fmap: folium.Map, *, vmin: float, vmax: float) -> None:
    """Leyenda vertical propia (no el widget horizontal por defecto de
    branca, que quedaba cortado) -- a la derecha, dentro del mapa, sin tapar
    el LayerControl (que folium coloca arriba a la derecha por defecto)."""
    mid = (vmin + vmax) / 2
    gradient = ", ".join(SEQUENTIAL_COLORS[::-1])  # oscuro (alto) arriba -> claro (bajo) abajo
    html = f"""
    <div style="position: fixed; top: 90px; right: 12px; z-index: 9999;
                background: rgba(255,255,255,0.92); color: #222; padding: 8px 10px;
                border-radius: 6px; font-size: 11px; font-family: sans-serif; text-align: center;
                border: 1px solid #999; box-shadow: 0 1px 4px rgba(0,0,0,0.3);">
      <div style="font-weight: bold; margin-bottom: 4px;">Minutos</div>
      <div style="display:flex; align-items: stretch;">
        <div style="width:16px; height:130px; border-radius:2px;
                    background: linear-gradient(to bottom, {gradient}); border:1px solid #888;"></div>
        <div style="display:flex; flex-direction:column; justify-content:space-between;
                    margin-left:6px; height:130px;">
          <span>{vmax:.0f}</span><span>{mid:.0f}</span><span>{vmin:.0f}</span>
        </div>
      </div>
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(html))


def _add_insufficient_data_note(fmap: folium.Map) -> None:
    html = f"""
    <div style="position: fixed; bottom: 20px; left: 20px; z-index: 9999; background: rgba(255,255,255,0.92);
                color: #222; padding: 8px 12px; border-radius: 6px; font-size: 12px; font-family: sans-serif;
                border: 1px solid #999; box-shadow: 0 1px 4px rgba(0,0,0,0.3); max-width: 300px; white-space: normal;">
      <span style="display:inline-block;width:12px;height:12px;background:{INSUFFICIENT_DATA_COLOR};
                   border:1px solid #999;margin-right:6px;"></span>
      Sin información suficiente (no es "0 min" ni "mal acceso")
    </div>
    """
    fmap.get_root().html.add_child(folium.Element(html))


def group_facilities_by_category(facilities: pd.DataFrame, *, category_col: str = "layer_category") -> dict[str, pd.DataFrame]:
    """Agrupa facilities por capa (Resolutivo/Candidato/Otro) -- lógica pura
    de preparación de clusters, sin folium, para poder testearse sola. Los
    filtros (categoría/institución/resolutivo) deben aplicarse ANTES de
    llamar a esta función; agrupa lo que se le pase, nada más."""
    return {cat: facilities[facilities[category_col] == cat] for cat in LAYER_COLORS if (facilities[category_col] == cat).any()}


def add_facility_layer(
    fmap: folium.Map, facilities: pd.DataFrame, *, highlight_ids: set[str] | None = None, default_show: bool = False,
) -> folium.Map:
    """Añade una capa de clusters por categoría (Resolutivo / Candidato
    upgrade / Otro), cada una un `MarkerCluster` independiente controlable
    desde `LayerControl` -- nunca mezclados en un único cluster. `facilities`
    debe venir YA FILTRADO (categoría/institución/resolutivo) por el
    llamador; esta función no filtra nada, solo agrupa y dibuja lo recibido.
    `default_show=False` dibuja los clusters pero ocultos hasta que el
    usuario los active (uso en la pestaña "Mapa"); `True` los deja visibles
    desde el inicio (uso en la pestaña "Establecimientos")."""
    highlight_ids = highlight_ids or set()
    groups = group_facilities_by_category(facilities)
    for category, sub in groups.items():
        color = LAYER_COLORS[category]
        cluster = MarkerCluster(name=category, show=default_show)
        for _, r in sub.iterrows():
            if pd.isna(r.get("lon")) or pd.isna(r.get("lat")):
                continue
            is_highlighted = str(r["COD_IPRESS"]) in highlight_ids
            tooltip = (
                f"<b>{r['NOMBRE']}</b><br>Categoría: {r['CATEGORIA_NORM']}<br>"
                f"Institución: {r.get('INSTITUCION', r.get('DEPARTAMENTO', ''))}<br>Estado: {r['ESTADO']}<br>"
                f"Resolutivo: {'Sí' if r['is_resolutive'] else 'No'}<br>"
                f"{r['DISTRITO']}, {r['PROVINCIA']}, {r['DEPARTAMENTO']}"
                + ("<br><b>⚠ excluido de routing por calidad espacial</b>" if r.get("qc_excluded_from_routing") else "")
            )
            folium.CircleMarker(
                location=(r["lat"], r["lon"]),
                radius=8 if is_highlighted else 5,
                color="#ffcc00" if is_highlighted else color,
                fill=True, fill_color=color, fill_opacity=0.9 if is_highlighted else 0.75,
                weight=3 if is_highlighted else 1,
                tooltip=tooltip,
            ).add_to(cluster)
        cluster.add_to(fmap)
    folium.LayerControl(collapsed=True).add_to(fmap)
    return fmap
