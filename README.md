# Accesibilidad por carretera a atención de emergencia resolutiva — Tumbes, Cusco, Amazonas

Proyecto académico (Python) reproducible. Estima **cuánto tarda, por carretera,
la población de tres departamentos del Perú en llegar a un establecimiento de
salud con capacidad resolutiva para una emergencia grave, y dónde están las
mayores brechas**.

## Pregunta principal

> ¿Cuánto tiempo tarda realmente, por carretera, la población de **Tumbes, Cusco
> y Amazonas** en llegar a un establecimiento de salud con **capacidad
> resolutiva** para una emergencia grave, y **dónde están las mayores brechas**?

## Departamentos (fijos, definidos en `config.md`)

| Departamento | Región natural | UBIGEO |
|---|---|---|
| Tumbes | Costa | 24 |
| Cusco | Andes | 08 |
| Amazonas | Amazonía | 01 |

El código Python lee los departamentos desde `config.md`. Cambiarlos **no**
requiere tocar código.

## Establecimiento "resolutivo"

Activo **Y** con categoría normalizada en
`{II-1, II-2, II-E, III-1, III-2, III-E}`.
Las categorías `I-1..I-4` se conservan en el dataset pero **no** son destino en
el cálculo principal. La normalización de categorías RENIPRESS se implementa de
forma explícita y documentada en `src/facilities.py` (Fase 1).

## Fuentes de datos

Inspeccionadas el 2026-09-10 — detalle, URLs, licencias y problemas conocidos en
[`docs/00_sources_inspection.md`](docs/00_sources_inspection.md).

| Rol | Fuente | Licencia |
|---|---|---|
| Oferta (establecimientos) | RENIPRESS / SUSALUD (datosabiertos.gob.pe) | ODC-BY |
| Demanda (centros poblados) | SIGMED / MINEDU | uso académico c/ atribución (revisar) |
| Red vial | OpenStreetMap / Geofabrik (extracto Perú) | ODbL 1.0 |
| Límites admin. | IGN (datosabiertos.gob.pe) | ODC-BY |
| Población (Fase 3) | INEI, Censo 2017 | por confirmar |

Ningún dataset grande se descarga sin autorización explícita.

## Estructura

```
HW_02_202602/
├── app.py                  # Dashboard Streamlit (Fase 4)
├── config.md               # ÚNICA fuente de parámetros modificables
├── environment.yml         # Entorno conda AUTORITATIVO
├── requirements.txt         # Referencia pip
├── README.md
├── data/
│   ├── raw/                # Descargas originales (git-ignored)
│   ├── processed/          # Datos limpios/derivados (git-ignored)
│   ├── outputs/            # Resultados y reportes de calidad (git-ignored)
│   └── cache/              # Cache de routing (git-ignored)
├── src/
│   ├── config.py           # Lee config.md                       [IMPLEMENTADO]
│   ├── acquisition.py      # Descarga reproducible de fuentes    [IMPLEMENTADO — Fase 1]
│   ├── boundaries.py       # Límites IGN (deptos/provincias/distritos) [IMPLEMENTADO — Fase 1, añadido]
│   ├── validation.py       # 6 reglas de validación + auditoría  [IMPLEMENTADO — Fase 1]
│   ├── facilities.py       # Normalización RENIPRESS + resolutivo [IMPLEMENTADO — Fase 1]
│   ├── demand.py           # Centros poblados + muestreo         [IMPLEMENTADO — Fase 1]
│   ├── routing.py          # Cliente de routing + matrices       (Fase 2)
│   ├── metrics.py          # Indicadores de acceso               (Fase 3)
│   ├── analysis.py         # Agregación y brechas                (Fase 3)
│   └── visualization.py    # Mapas y figuras                     (Fase 3/4)
├── scripts/                # Puntos de entrada por fase
│   ├── download_data.py    # [IMPLEMENTADO] adquisición idempotente
│   ├── validate_data.py    # [IMPLEMENTADO] procesamiento + validación Fase 1
├── tests/                  # pytest
├── figures/  tables/       # Salidas para el informe (git-ignored)
├── report/                 # report.tex + references.bib  (Fase 5)
└── docs/                   # Notas de trabajo (inspección de fuentes, decisiones)
```

Cambios respecto a la estructura sugerida en el enunciado, con motivo:

- **`environment.yml`** añadido: el stack geoespacial (GDAL/GEOS/PROJ) necesita
  binarios de conda-forge; esta máquina no tiene Homebrew ni compilador de C, así
  que `requirements.txt` (pip) no basta para reproducir el entorno. Se conserva
  `requirements.txt` como referencia.
- **`docs/`** añadido: notas de trabajo internas (inspección de fuentes,
  decisiones), separadas del entregable final en `report/`.
- **`src/boundaries.py`** añadido: ni `facilities.py` ni `demand.py` eran el
  lugar natural para cargar/derivar los límites IGN (departamentos, provincias
  derivadas por disolución, distritos) que ambos necesitan para la regla de
  "punto fuera de su distrito declarado" y para la agregación de Fase 3.
- `src/__init__.py` en vez de `src/**init**.py` (el enunciado tenía un typo de
  Markdown).

## Entorno

```bash
conda env create -p ./.venv -f environment.yml   # crear
conda activate ./.venv                             # activar
pytest -q                                          # correr tests
```

Python **3.12** (env conda en `./.venv`). Fase 0 instala solo el núcleo
(Fases 1); las dependencias de routing, mapas y dashboard se instalan en su fase.

## Fases

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Configuración e inspección de fuentes | **hecha** |
| 0.5 | Bloqueantes de diseño (routing, CRS, validación, cutoff) | **hecha** |
| 1 | Adquisición y validación de datos | **hecha** — ver informe de Fase 1 |
| 2 | Routing (grafo local OSMnx/NetworkX; OSRM local descartado — ver `docs/01_routing_decision.md`) | pendiente, bloqueada por RAM/disco para OSRM local |
| 3 | Métricas y análisis de brechas | pendiente |
| 4 | Dashboard Streamlit | pendiente |
| 5 | Informe LaTeX | pendiente |

No se inicia una fase sin validar la anterior.

## Reproducibilidad

- Toda la parametrización en `config.md` (un bloque `yaml`).
- Semilla de muestreo: `42`.
- Cortes de datos fijados por fecha (RENIPRESS y snapshot OSM).
- Política `no_silent_drops`: cada registro excluido queda auditado en
  `data/outputs/`.
