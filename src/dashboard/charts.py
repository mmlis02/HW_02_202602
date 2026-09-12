"""charts — figuras Plotly (Fase 4). Devuelve objetos `go.Figure`; el
renderizado en la app usa `st.plotly_chart`.

Misma escala semántica de tiempo en todos los gráficos (verde=mejor,
rojo=peor) y color NEUTRO separado para "sin tiempo estimable" (nunca se
confunde con ">120 min", sección 29 del enunciado).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

BAND_COLORS = {
    "≤30 min": "#1a9850",
    "30–60 min": "#91cf60",
    "60–120 min": "#fee08b",
    ">120 min": "#d73027",
    "Sin tiempo estimable": "#bdbdbd",
}


def coverage_bands_figure(band_pcts: dict, *, title: str = "Cobertura poblacional por banda de tiempo") -> go.Figure:
    """`band_pcts`: {"≤30 min": x, "30–60 min": y, ...} — debe sumar ~100%
    (Reading B, sobre el frame completo, población calibrada)."""
    labels = list(BAND_COLORS.keys())
    values = [band_pcts.get(k, 0.0) for k in labels]
    fig = go.Figure(go.Bar(
        x=values, y=[""] * len(labels), orientation="h",
        marker_color=[BAND_COLORS[k] for k in labels],
        text=[f"{v:.1f}%" for v in values], textposition="inside",
        customdata=labels, hovertemplate="%{customdata}: %{x:.1f}%<extra></extra>",
    ))
    fig.update_layout(barmode="stack", title=title, xaxis_title="% de población (frame calibrado)", yaxis_visible=False, height=180, margin=dict(t=50, b=30))
    return fig


def weighted_ecdf_figure(df: pd.DataFrame, *, group_col: str, time_col: str = "t_min", weight_col: str = "calibrated_weight", title: str | None = None) -> go.Figure:
    """ECDF POBLACIONAL (población acumulada, no CP acumulados) — cada CP
    pesa por `calibrated_weight`, nunca 1 CP = 1 observación equiponderada."""
    fig = go.Figure()
    for group, g in df.groupby(group_col):
        t = pd.to_numeric(g[time_col], errors="coerce")
        w = pd.to_numeric(g[weight_col], errors="coerce")
        mask = t.notna() & w.notna()
        if not mask.any():
            continue
        order = t[mask].sort_values().index
        tt = t.loc[order].values
        ww = w.loc[order].values
        cum = np.cumsum(ww) / ww.sum() * 100.0
        fig.add_trace(go.Scatter(x=tt, y=cum, mode="lines", name=str(group)))
    for x in (30, 60, 120):
        fig.add_vline(x=x, line_dash="dash", line_color="gray", opacity=0.5)
    fig.update_layout(
        title=title or "Distribución poblacional ponderada del tiempo de acceso (ECDF)",
        xaxis_title="Tiempo de acceso en auto (min)", yaxis_title="% de población acumulada (con tiempo estimable)",
        height=420,
    )
    return fig


def urban_rural_comparison_figure(urban_rural_summary: pd.DataFrame) -> go.Figure:
    df = urban_rural_summary.set_index("urban_rural")
    fig = go.Figure()
    for metric, label in [("weighted_mean_access_min", "Media ponderada"), ("weighted_median_access_min", "Mediana ponderada")]:
        if metric in df.columns:
            fig.add_trace(go.Bar(x=df.index.astype(str), y=df[metric], name=label))
    fig.update_layout(title="Acceso en auto: urbano vs rural (media/mediana ponderada)", yaxis_title="Minutos", barmode="group", height=380)
    return fig


def urban_rural_coverage_bands_figure(urban_rural_summary: pd.DataFrame) -> go.Figure:
    df = urban_rural_summary.copy()
    bands = [("pct_le_30", "≤30 min"), ("pct_30_60", "30–60 min"), ("pct_60_120", "60–120 min"), ("pct_gt_120", ">120 min")]
    fig = go.Figure()
    for col, label in bands:
        if col in df.columns:
            fig.add_trace(go.Bar(x=df["urban_rural"].astype(str), y=df[col], name=label, marker_color=BAND_COLORS.get(label)))
    fig.update_layout(barmode="stack", title="Bandas de cobertura por ámbito (entre población con tiempo estimable)", yaxis_title="%", height=380)
    return fig
