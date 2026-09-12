# `config.md` — Configuración del proyecto

Accesibilidad por carretera a atención de emergencia con capacidad resolutiva en
**Tumbes, Cusco y Amazonas** (Perú).

Este archivo es la **única** fuente de parámetros modificables del proyecto.
El código Python **no** debe hardcodear estos valores: los lee desde el bloque
`yaml` de más abajo mediante `src/config.py` (`load_config()`).

> Regla de oro: cambiar de departamentos, umbrales o rutas **no** debe requerir
> tocar código Python. Solo se edita este archivo.

---

## 1. Departamentos de estudio

| Departamento | Región natural | Código UBIGEO (2 díg.) | Estado del código |
|---|---|---|---|
| Tumbes   | Costa     | `24` | **CONFIRMADO en Fase 1**: coincide con el prefijo de `UBIGEO` de los 164 registros RENIPRESS y los 340 SIGMED con `DEPARTAMENTO/DEP="TUMBES"`, y con `CODDEP` del shapefile de departamentos IGN. |
| Cusco    | Andes     | `08` | **CONFIRMADO en Fase 1**: mismo cruce, 1582 registros RENIPRESS / 14 813 SIGMED. |
| Amazonas | Amazonía  | `01` | **CONFIRMADO en Fase 1**: mismo cruce, 791 registros RENIPRESS / 4217 SIGMED. |

Fuente de los códigos: Instituto Nacional de Estadística e Informática (INEI),
sistema UBIGEO — los dos primeros dígitos identifican el departamento, ordenados
alfabéticamente (01 Amazonas … 08 Cusco … 24 Tumbes). **Verificación cruzada
completada en Fase 1** (2026-09-10): de 1890 UBIGEO distintos en RENIPRESS
nacional, 1889 existen en el shapefile de distritos del IGN (el único que no,
`160109`, es de Loreto — fuera de alcance); dentro de los 3 departamentos de
estudio, 0 discrepancias. **No se inventaron.**

Estos tres departamentos son obligatorios y no se sustituyen.

## 2. Pregunta principal

> «¿Cuánto tiempo tarda realmente, por carretera, la población de Tumbes, Cusco y
> Amazonas en llegar a un establecimiento de salud con capacidad resolutiva para
> una emergencia grave, y dónde están las mayores brechas?»

## 3. Establecimiento resolutivo — definición operativa

Un establecimiento es **resolutivo si y solo si**:

1. está **activo** (condición operativa vigente en RENIPRESS), **y**
2. su **categoría normalizada** pertenece a:
   `II-1`, `II-2`, `II-E`, `III-1`, `III-2`, `III-E`.

Las categorías del primer nivel (`I-1`, `I-2`, `I-3`, `I-4`) **permanecen en el
dataset** pero **no** cuentan como destino resolutivo en el cálculo principal.

La normalización de las categorías RENIPRESS (mapeo de las variantes de texto
crudas — p. ej. `"II - 1"`, `"II-1"`, `"II1"`, `"Sin Categoría"` — a las etiquetas
canónicas) se implementará de forma **explícita y documentada** en
`src/facilities.py` en Fase 1, a partir del catálogo real de valores observados
en el archivo. Aún no está definida porque no se ha descargado el dataset.

La **pertenencia a Tumbes/Cusco/Amazonas** de un establecimiento se determina por
el **departamento declarado** en RENIPRESS/SIGMED (columna de texto), con una
**verificación geoespacial independiente** contra los límites oficiales del IGN
(unión espacial punto-en-polígono a nivel de *distrito*, regla de validación 4 en
§6) que audita —sin corregir automáticamente— cualquier discrepancia. **Esto es
una decisión del proyecto, no un requisito del enunciado**: la auditoría de Fase 1
(2026-09-11) cruzó ambas fuentes y encontró 0 discrepancias departamentales reales
en los 3 departamentos, por lo que no se introdujo una transformación adicional
(reclasificar por polígono) sin necesidad demostrada. Si en una futura ejecución
la regla 4 revela discrepancias sistemáticas a nivel de distrito, se reevaluará.

## 4. Fuentes y fechas de corte

Un dataset con `-latest` o "el más reciente" no es reproducible: el resultado
cambiaría si el análisis se re-ejecuta otro día. Por eso cada fuente queda
**fijada a una fecha/recurso concreto** en `data_cutoff:` (§7). Reglas:

| Fuente | Fecha de corte fijada | Regla |
|---|---|---|
| RENIPRESS | **2026-08-31** (`RENIPRESS_31-08-2026.csv`, descargado y verificado en Fase 1: 36 004 registros nacionales, 2537 en los 3 deptos) | Corte mensual más reciente publicado a la fecha de esta inspección (2026-09-10). Si al ejecutar Fase 1 ya existe un corte de septiembre, se decide explícitamente si se actualiza (documentando el cambio) o se mantiene agosto. No se decidió solo: se mantuvo agosto. |
| SIGMED Centros Poblados | **2020-02-05** (shapefile) — el `.zip` en sí tiene `Last-Modified: 2021-12-10` porque MINEDU lo re-empaquetó ese día para añadir el diccionario de datos (`DICCIONARIO_CP_P.doc`, con esa misma fecha interna); el shapefile `CP_P.shp` conserva su fecha de datos 2020-02-05 (confirmado por el propio diccionario: "Actualizado al 05/02/2020"). | Es la única fecha de datos que existe; MINEDU no publica cortes periódicos. Limitación a declarar en el informe (geometría potencialmente desactualizada desde 2020). |
| Límites administrativos IGN | **2025-06-24** (`Last-Modified` real del servidor para ambos `.zip`, verificado por `HEAD` en Fase 1 — corrige la fecha "2023-08-01" que se había leído de la página en Fase 0, que resultó ser la fecha de publicación del *dataset*, no del archivo actual) | Fecha real del archivo descargado, no la del listado de la página. |
| OSM / Geofabrik | **TBD — se fija el día de la descarga en Fase 2** | Política: usar siempre un snapshot **fechado** (`peru-YYMMDD.osm.pbf`), nunca `-latest`. No se escribe hoy una fecha porque el archivo no se ha descargado todavía (Fase 2 fuera de alcance). Al descargar, la fecha exacta y el `.md5` se registran aquí y en `data/raw/`. |

## 5. Estrategia de CRS

Se analizó si `EPSG:32718` (UTM 18S) es adecuado para los tres departamentos.
Longitudes de zona UTM: 17S `[-84,-78]`, 18S `[-78,-72]`, 19S `[-72,-66]`.

- **Tumbes** (~-80.4°) cae en zona **17S**.
- **Amazonas** (~-77 a -78.9°) cae mayormente en zona **17S/18S**, cerca del límite.
- **Cusco** (~-70.4 a -74.0°) se reparte entre zona **18S y 19S**, cerca del límite.

Es decir: **ningún** departamento está centrado en la zona 18S — un único UTM
nacional siempre implica una aproximación. El error de escala de UTM a ~3° del
meridiano central es <1%, aceptable para operaciones tolerantes (un buffer de
25 km), pero **sesgaría de forma desigual** cualquier cálculo de **área o
densidad de población** entre Costa/Andes/Amazonía si se usara un único UTM,
precisamente porque el proyecto compara esas tres regiones entre sí.

**Decisión (no requiere rediseñar la arquitectura, solo añade dos parámetros):**

| Uso | CRS | Motivo |
|---|---|---|
| Almacenamiento, I/O, uniones espaciales (punto-en-polígono, distrito, departamento) | `EPSG:4326` | Los predicados topológicos (contains, intersects) son correctos en cualquier CRS consistente; no necesitan proyección métrica. |
| Buffer de recorte OSM (25 km) | `EPSG:32718` (UTM 18S) | Error <1% irrelevante para un buffer de esta escala. |
| Área / densidad de población por depto-provincia-distrito | `ESRI:102033` (South America Albers Equal Area Conic) — **verificado que `pyproj` lo resuelve** | Cónica de área equivalente para todo el continente: no tiene el sesgo de zona de UTM, comparación justa entre los 3 departamentos. |
| Snapping a la red vial (si el motor de ruteo es un grafo local tipo OSMnx/NetworkX) | proyectar el grafo (`osmnx.project_graph`) al UTM local antes de construir el índice de vecino más cercano | Buscar el nodo más cercano en grados (4326) sin proyectar da resultados incorrectos porque 1° de longitud ≠ 1° de latitud en distancia real. |
| Tiempo de viaje (la métrica principal) | no depende de estos CRS | Sale del motor de ruteo (OSRM o grafo), que calcula en su propio espacio geodésico/métrico interno. |
| Mapas (Fase 3/4) | pendiente, no crítico ahora | Se decide al implementar `visualization.py`. |

## 6. Reglas de validación obligatorias (Fase 1)

Para cada regla: parámetro en `validation:` (§7), umbral/tolerancia, acción y
justificación. Ninguna regla asume un valor real de RENIPRESS que no se haya
verificado: donde el valor depende de los datos, se deja `"TBD"` y se indica cómo
se determinará en Fase 1.

> **Nota de transparencia (añadida tras la auditoría de Fase 1, 2026-09-11):** los
> umbrales numéricos de alarma (`max_missing_pct_alarm: 15.0`,
> `max_out_of_bbox_pct_alarm: 5.0`, `max_mojibake_pct_alarm: 1.0`) y la tolerancia
> de coordenada-cero (`zero_tolerance_deg`) son **decisiones de diseño del
> proyecto**, no valores exigidos por el enunciado (que solo pide implementar cada
> chequeo, sin fijar un %). Se documentan aquí como tales para que quede claro en
> la presentación qué es requisito y qué es criterio propio.

| # | Regla | Parámetro | Umbral/tolerancia | Acción | Justificación |
|---|---|---|---|---|---|
| 1 | Coordenadas ausentes / nulas / `≈(0,0)` | `validation.facilities.coord_missing` | alarma agregada `max_missing_pct_alarm: 15.0` (no es un dropout automático por registro); **`zero_tolerance_deg: 1e-6`** — un punto con `\|lon\|≤tol` Y `\|lat\|≤tol` se trata como "cero/ausente", no solo `lon==0 and lat==0` exacto | `keep_flag_exclude_from_routing`: se conserva el registro, se excluye del cálculo espacial | No se puede inventar una coordenada. Excluir del cómputo sin borrar el registro cumple `no_silent_drops`; el umbral agregado detiene el pipeline si el problema es sistémico. **Corrección de auditoría**: 2 establecimientos con coordenadas `≈-7.8e-07` (ruido de punto flotante de un "cero" mal escrito) caían antes en la regla 2 (fuera de bbox) en vez de aquí — con la tolerancia quedan correctamente clasificados como regla 1. `1e-6` grados ≈ 11 cm en el ecuador: no afecta ninguna coordenada real de Perú (todo el país está a más de 68° de longitud y 0° de latitud del origen). |
| 2 | Coordenadas fuera del bbox de Perú | `validation.facilities.coord_out_of_bbox` | `tolerance_deg: 0.0` (el bbox ya es holgado); alarma agregada `max_out_of_bbox_pct_alarm: 5.0` | `keep_flag_exclude_from_routing` | Un punto fuera del país no es utilizable para rutear en Perú; se documenta en vez de borrarlo silenciosamente. |
| 3 | Lat/lon intercambiadas | `validation.facilities.swapped_latlon` | detección: si `(lon,lat)` falla el bbox pero el par invertido `(lat,lon)` sí cae dentro → sospecha; se confirma con el polígono de distrito declarado si ya está disponible | inequívoco → `correct_with_audit` (se hace el swap, se registra valor original y corregido); ambiguo → `keep_warning` (no se corrige solo, se excluye del cálculo) | Perú es un caso favorable: los rangos numéricos de lat (`0`..`-18.4`) y lon (`-68.6`..`-81.4`) de `peru_bbox` **no se solapan**, por lo que el swap es detectable con una prueba de bbox sin ver los datos reales. Auto-corregir sin registrar sería inventar un valor; por eso se exige auditoría del cambio. |
| 4 | Punto fuera de su distrito declarado | `validation.facilities.point_outside_declared_district` | `containment_buffer_m: 1000` (tolerancia por la escala 1:100 000 de los polígonos IGN) | `keep_warning`; la pertenencia departamental para el análisis se decide por unión espacial (§3), la columna declarada queda como verificación cruzada (`qc_cross_check`) | No se puede saber, solo con esto, si el error está en la coordenada o en el UBIGEO declarado — no se auto-corrige. Requiere los límites IGN (Fase 1). |
| 5 | Códigos de establecimiento duplicados | `validation.facilities.duplicate_facility_code` | **`key_field: "COD_IPRESS"`** (verificado: 0 duplicados en 36 004 registros nacionales); `tie_break_field: null` (no aplica: no se encontraron duplicados) | duplicado exacto (fila 100% idéntica) → `drop_duplicate_keep_first`; mismo código con datos distintos → `keep_warning` (no se decide solo cuál fila es la correcta) | Confirmado por inspección real (`pandas.Series.duplicated()` sobre el CSV descargado) — 0 duplicados nacionales en `COD_IPRESS`, 0 en `CODCP` (SIGMED). Se implementa igual el mecanismo por si aparecieran en un corte futuro. |
| 6 | Problemas de encoding | `validation.facilities.encoding_check` + `acquisition.renipress.encoding` | **`encoding: "utf-8-sig"`, `sep: ";"`** (verificado: el archivo trae BOM UTF-8 y separador `;`, NO Latin-1/CP1252 como se había anticipado en Fase 0); alarma `max_mojibake_pct_alarm: 1.0` | `verificado_ok`: 0 patrones de mojibake detectados en `NOMBRE`/`DIRECCION`/`DISTRITO`/`PROVINCIA` (36 004 registros); no fue necesario probar encodings alternativos | `file(1)` + inspección de bytes (BOM `EF BB BF`) confirmaron UTF-8 con BOM antes de fijar el parser — la hipótesis de Fase 0 (Latin-1) era una anticipación razonable pero **no se usó sin verificar**. |

Regla general (`validation.policy: no_silent_drops`): toda exclusión o corrección
—no solo los descartes— queda en el audit CSV de `data/outputs/`, con el motivo y,
cuando aplique, el valor original y el corregido.

## 7. Parámetros (bloque legible por máquina)

Todo lo que el código consume está en este único bloque `yaml`.

```yaml
# ------------------------------------------------------------------
# config.md — bloque de parámetros. Editar SOLO aquí.
# Lo lee src/config.py::load_config()
# ------------------------------------------------------------------

project:
  name: "Accesibilidad a emergencias resolutivas — Tumbes, Cusco, Amazonas"
  question: >
    ¿Cuánto tiempo tarda realmente, por carretera, la población de Tumbes, Cusco
    y Amazonas en llegar a un establecimiento de salud con capacidad resolutiva
    para una emergencia grave, y dónde están las mayores brechas?
  presentation_minutes: 12

# --- Departamentos de estudio -------------------------------------
# El código itera sobre esta lista. Añadir/quitar aquí NO exige tocar Python.
departments:
  - name: "Tumbes"
    region: "Costa"
    ubigeo_dep: "24"      # INEI UBIGEO; re-confirmar en Fase 1 contra los datasets
  - name: "Cusco"
    region: "Andes"
    ubigeo_dep: "08"
  - name: "Amazonas"
    region: "Amazonía"
    ubigeo_dep: "01"

# --- Clasificación de establecimientos (RENIPRESS) ---------------
facilities:
  resolutive_categories:            # cuentan como destino en el cálculo principal
    - "II-1"
    - "II-2"
    - "II-E"
    - "III-1"
    - "III-2"
    - "III-E"
  nonresolutive_categories:         # se conservan en el dataset, NO son destino
    - "I-1"
    - "I-2"
    - "I-3"
    - "I-4"
  active_only: true                 # exigir establecimiento activo
  # Dominio REAL observado en ESTADO (36 004 registros, RENIPRESS 2026-08-31):
  # ACTIVO(26901) CIERRE TEMPORAL DE OFICIO(4378) BAJA DEFINITIVA(3470)
  # BAJA PROVISIONAL(907) BAJA DEFINITIVA DE OFICIO(201)
  # BAJA PROVISIONAL DE OFICIO(119) CIERRE TEMPORAL DE PARTE(28)
  # Solo "ACTIVO" = operando hoy. Los "CIERRE TEMPORAL*" están cerrados AHORA
  # (no definitivamente) -> tampoco pueden atender una emergencia -> NO activos.
  active_status_values: ["ACTIVO"]  # verificado en Fase 1, ver docs/00_sources_inspection.md
  # CORREGIDO tras auditoría (2026-09-11): el filtro OPERATIVO de departamento usa el
  # texto declarado (DEPARTAMENTO/DEP), con una verificación geoespacial INDEPENDIENTE
  # (regla de validación 4, punto-en-polígono contra IGN) que audita —sin corregir
  # automáticamente— cualquier discrepancia a nivel de distrito. Esto es una decisión
  # del proyecto (no lo exige el enunciado): la auditoría de Fase 1 verificó 0
  # discrepancias departamentales reales entre texto y polígono en los 3 departamentos,
  # así que no se introduce una transformación adicional sin necesidad demostrada.
  department_membership_source: "declared_text_with_geospatial_crosscheck"

# --- Geografía ----------------------------------------------------
crs:
  geographic: "EPSG:4326"           # I/O, almacenamiento, uniones espaciales (§5)
  metric_clip: "EPSG:32718"         # UTM 18S — SOLO para el buffer de recorte OSM (25 km)
  metric_area: "ESRI:102033"        # South America Albers Equal Area Conic — área y
                                     # densidad de población entre departamentos (§5)
  # Ver §5 para la justificación completa (ningún departamento está centrado en 18S;
  # un único UTM sesgaría comparaciones de área entre Costa/Andes/Amazonía).

# Bounding box de Perú continental (lon/lat, EPSG:4326).
# Orden: [min_lon, min_lat, max_lon, max_lat]. Valor de trabajo, ajustable.
# Nota: los rangos de lat y lon de este bbox NO se solapan numéricamente — eso es lo
# que hace detectable el swap de lat/lon en validation.facilities.swapped_latlon.
peru_bbox: [-81.4, -18.4, -68.6, -0.0]

# --- Demanda (centros poblados) --------------------------------
demand:
  source: "SIGMED / MINEDU — Centros Poblados"
  max_points: 5000                  # límite duro de puntos de demanda a rutear
  sampling:
    strategy: "stratified_pps"      # πps sistemático de Madow por estrato — diseño FINAL (Fase 3)
    stratify_by: "ubigeo_distrito"  # un estrato por distrito
    size_measure: "estimated_population"
    estimator: "horvitz_thompson"
    seed: 42
    # Cuota por distrito ∝ población distrital INEI (water-filling con tope).
    district_quota: "pop_proportional"
    # --- DESVIACIÓN DOCUMENTADA para Fase 1 (ver docs/00_sources_inspection.md) ---
    # SIGMED no trae población y la fuente INEI se une recién en Fase 3 (population:
    # abajo). Por eso el muestreo EJECUTADO en Fase 1 usa como tamaño de estrato el
    # CONTEO de centros poblados por distrito (dato real, no inventado) en vez de
    # población, con el mismo water-filling capacity-constrained y seed=42. Es
    # PROVISIONAL: se reemplaza en Fase 3 por el diseño de arriba en cuanto haya
    # población real, y los resultados de accesibilidad basados en la muestra de
    # Fase 1/2 se re-evalúan en ese momento.
    phase1_interim_size_measure: "cp_count_per_district"
    # --- Pesos de diseño persistidos (auditoría 2026-09-11) ---
    # `demand.parquet` guarda, por cada CP muestreado: stratum_n, stratum_sample_n,
    # inclusion_prob, design_weight. Son pesos del DISEÑO MUESTRAL DE CENTROS
    # POBLADOS (probabilidad de que ESE asentamiento entre a la muestra de 5000),
    # calculados hoy sin ningún dato de INEI. NO son pesos poblacionales y NO deben
    # usarse todavía para población ponderada, cobertura, medias poblacionales ni
    # Gini — eso requiere unir población real (Fase 3) y, muy probablemente,
    # recalcular estos pesos combinándolos con population_i/π_i (Horvitz-Thompson).
    persist_design_weights: true
  population:
    # SIGMED no trae campo de población -> se estima en Fase 3.
    source: "INEI (población por centro poblado / distrito, censo 2017)"
    method: "PENDIENTE Fase 3"

# --- Adquisición: cómo leer cada fuente cruda ----------------------
# (separado de "validation": aquí va cómo SE LEE el archivo; en validation, cómo se
# DETECTAN y RESUELVEN los problemas — ver §6.)
acquisition:
  renipress:
    url: "https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_31-08-2026.csv"
    resource: "RENIPRESS_31-08-2026.csv"   # corte fijado, ver §4 / data_cutoff
    format: "csv"
    encoding: "utf-8-sig"          # verificado en Fase 1: BOM EF BB BF + UTF-8, NO Latin-1/CP1252
    sep: ";"                       # verificado en Fase 1 (header real)
    fallback_encodings: ["utf-8-sig", "latin-1", "cp1252"]  # orden probado; utf-8-sig funcionó al primer intento
    user_agent_required: true      # el WAF de datosabiertos puede responder 418 sin UA de navegador
  sigmed_centros_poblados:
    # URL real obtenida inspeccionando js/mapaeducativo.js de la página de
    # descargas (función descargashpccpp(): document.location="archivos/CP_MED.zip"),
    # NO adivinada. Verificada con HEAD (200, application/x-zip-compressed).
    url: "https://sigmed.minedu.gob.pe/descargas/archivos/CP_MED.zip"
    resource: "CP_MED.zip"
    format: "shp"                  # shapefile "CP_P" dentro del zip
    crs_declared: "EPSG:4326"      # confirmado por CP_P.prj: GCS_WGS_1984
    encoding: "utf-8"              # confirmado por CP_P.cpg
  ign_limites:
    departamentos_url: "https://www.datosabiertos.gob.pe/sites/default/files/DEPARTAMENTOS_LIMITES.zip"
    departamentos_resource: "DEPARTAMENTOS_LIMITES.zip"
    distritos_url: "https://www.datosabiertos.gob.pe/sites/default/files/DISTRITOS_LIMITES.zip"
    distritos_resource: "DISTRITOS_LIMITES.zip"
    format: "shp"
    crs_declared: "EPSG:4326"      # confirmado por los .prj: GCS_WGS_1984
    provincias: "derivadas en Fase 1 disolviendo DISTRITOS por (CODDEP,CODPROV) -- no existe .zip de provincias en el portal"
  osm_geofabrik:
    format: "osm.pbf"
    snapshot_policy: "dated_not_latest"   # usar peru-YYMMDD.osm.pbf, nunca "-latest"; guardar su .md5
  ign_ccpp_sin_poblacion:
    # Fase 3: investigado como candidato a fuente de población por centro
    # poblado. Descargado e inspeccionado -- NO tiene campo de población
    # (columnas: OBJECTID, NOM_POBLAD, FUENTE, CÓDIGO, CAT_POBLAD, DIST, PROV,
    # DEP, CÓD_INT, CATEGORIA, X, Y, N_BUSQDA). Se conserva descargado y
    # documentado (docs/03_population_source_inspection.md) para trazabilidad
    # de la búsqueda, NO se usa como fuente de población.
    url: "https://www.datosabiertos.gob.pe/sites/default/files/CCPP_0.zip"
    resource: "CCPP_0.zip"
    format: "shp"
    publisher: "IGN"   # no INEI -- el campo FUENTE por registro indica agencia de origen del punto, no el publicador del dataset
    used_for_population: false
  mimp_poblacion_distrital_censo2017:
    # Fase 3: unica fuente real, oficial y descargable identificada tras 11
    # candidatas verificadas (ver docs/03_population_source_inspection.md).
    # Es DISTRITAL (UBIGEO 6 digitos), no por centro poblado -- se usa SOLO
    # como benchmark externo de representatividad departamental/distrital de
    # la muestra, NUNCA como population_i de un CP individual.
    url: "https://www.mimp.gob.pe/omep/pdf/resumen2/2_Inf_de_Poblacion-CensoNacional-2017.xlsx"
    resource: "2_Inf_de_Poblacion-CensoNacional-2017.xlsx"
    format: "xlsx"
    publisher: "MIMP (republica agregados oficiales del Censo 2017 INEI, FUENTE citada por bloque de columnas)"
    granularity: "distrito (UBIGEO 6 digitos)"
    sheet: "DISTRITAL"
    population_columns: ["Primera infancia (0 - 5 años)", "Niñez (6 - 11 años)", "Adolescencia (12 - 17 años)", "Jóvenes (18 - 29 años)", "Adultos/as jóvenes (30 - 44 años)", "Adultos/as (45 - 59 años)", "Adultos/as mayores (60 y más años)"]  # suma = poblacion total censada 2017 del distrito
    used_for_cp_population: false
    used_for: "sample_representativeness_benchmark_only"
  inei_cenepred_ccpp:
    # Fase 3 (corrección tras revisión con el usuario 2026-09-11): fuente
    # PRIMARIA de población por centro poblado. Servicio ArcGIS REST vivo,
    # verificado con GET real (no estaba caído -- la conclusión previa de
    # "no existe" fue un error). Republica el Censo 2017 INEI, capa
    # "Centros Poblados" (fuente declarada en la metadata del servicio:
    # "INEI - Censo de Población y Vivienda, 2017").
    service_query_url: "https://sig.cenepred.gob.pe/sigrid/rest/services/S06_ICO/MapServer/2110002/query"
    id_field: "codccpp"          # 10 digitos, formato identico a CPINEI (99.3% de solapamiento verificado)
    population_field: "pob_total"
    dep_field: "nomb_dep"
    departments: ["TUMBES", "AMAZONAS", "CUSCO"]
    page_size: 2000
    n_records_by_department_verified: {TUMBES: 190, AMAZONAS: 3174, CUSCO: 8968}
    raw_dir: "data/raw/inei_cenepred"
  inei_minam_ccpp:
    # Fase 3: fuente de VALIDACION cruzada + urbano/rural. Mismo universo
    # exacto que CENEPRED (mismos N por departamento, 0 duplicados,
    # poblacion identica en el 100% de 12312 registros comparables,
    # nombres identicos en 99.89%) -- evidencia fuerte de que ambas
    # redistribuyen el mismo producto INEI Censo 2017.
    service_query_url: "https://geoservidorperu.minam.gob.pe/arcgis/rest/services/Servicio_Oportunidades_Inversion/MapServer/16/query"
    id_field: "idccpp_17"        # 10 digitos, formato identico a CPINEI y a codccpp de CENEPRED
    population_field: "pob17"
    urban_rural_field: "area_17"  # 1=Urbano, 2=Rural (verificado por perfil poblacional: media urbana=12953, mediana=2214; media rural=182, mediana=119); valor 3 minoritario, sin documentacion oficial encontrada -> mapeado a unknown
    dep_field: "departamen"
    departments: ["TUMBES", "AMAZONAS", "CUSCO"]
    page_size: 1000
    raw_dir: "data/raw/inei_minam"

# --- Clasificacion urbano/rural (Fase 3, Metrica 6) ------------------
# No existe campo urbano/rural directo en ninguna fuente oficial verificada
# (ver docs/03_population_source_inspection.md). Se usa una regla
# reproducible basada en la categoria de centro poblado (CAT_POBLAD) del
# shapefile IGN CCPP_0.zip, que replica la tipologia que INEI usa en su
# propia documentacion censal para distinguir area urbana/rural. Cruce por
# CPINEI (unica clave con solapamiento real verificado: 1335/3162 = 42.2%);
# CPINEI2 y COD_INT NO se usan (solapamiento nulo o insignificante). Todo lo
# no cruzado queda como "unknown" -- nunca se infiere visualmente ni se
# imputa.
urban_rural_classification:
  source: "data/raw/inei/extracted_ccpp/CCPP_IGN100K.shp (CAT_POBLAD)"
  join_key: "CPINEI"           # contra el campo CÓDIGO del shapefile IGN
  coverage_note: "42.2% de los CP con CPINEI no nulo (1335/3162); 26.7% del universo de 5000"
  urban_categories: ["CIUDAD", "PUEBLO", "VILLA", "URBANIZACION", "PP.JJ.AA.HH.", "PUEBLO JOVEN", "PUEBLO JOVEN, AAHH", "BARRIO O CUARTEL", "ASOCIACION DE VIVIENDA", "CONJTO.HABITACIONAL", "COOPERATIVA DE VIVIENDA"]
  rural_categories: ["CASERÍO", "UNID. AGROPECUARIA", "ANEXO", "COMUNIDAD", "COOP. AGRARIA", "CAMPO MINERO", "ASIA", "OTROS"]
  unknown_when: "sin CPINEI, o CPINEI sin match en CÓDIGO, o CAT_POBLAD no listado arriba"

# --- Fechas de corte (reproducibilidad) — ver §4 -------------------
data_cutoff:
  renipress:
    date: "2026-08-31"
    resource: "RENIPRESS_31-08-2026.csv"
  sigmed_centros_poblados:
    date: "2020-02-05"
  limites_administrativos_ign:
    date: "2025-06-24"   # Last-Modified real del servidor (HEAD, Fase 1); corrige el "2023-08-01" de Fase 0
  osm_geofabrik:
    date: "2026-09-10"   # Last-Modified real del PBF descargado en Fase 2 (HEAD verificado)
    resource: "peru-260910.osm.pbf"   # snapshot fechado real; peru-latest.osm.pbf es un 302 a este archivo
    sha256_ref: "ver data/raw/osm/peru-260910.osm.pbf.manifest.json"
  ign_ccpp_sin_poblacion:
    date: "2025-05-26"   # Last-Modified real del servidor (HEAD/GET verificado, Fase 3)
  mimp_poblacion_distrital_censo2017:
    date: "2017-10-22"   # fecha de referencia real del dato (dia del Censo 2017); archivo republicado 2022-11-17 (Last-Modified servidor)

# --- Routing (Fase 2, decisión validada con el usuario 2026-09-11) --------
# Motor: NetworkX sobre un grafo construido de un extracto de OSM (pyrosm).
# NO OSRM local (bloqueo real de RAM/disco en esta máquina, ver
# docs/01_routing_decision.md). NO API remota. Diseño modular: routing.engine
# identifica el motor; solo src/routing/osm_extract.py y graph_build.py están
# acoplados a "cómo se obtiene el grafo" — matrix.py/snapping.py/compare.py
# trabajan contra cualquier networkx.DiGraph con peso time_s/length.
routing:
  engine: "networkx_local"
  clip_buffer_km: 25
  # ADAPTACIÓN DOCUMENTADA (2026-09-11): se extrae POR DEPARTAMENTO, no con un
  # único recorte de la unión de los 3 + buffer. Un primer intento con la unión
  # (~201 600 km², ~16% de Perú) agotó la RAM de esta máquina (8 GB, ya bajo
  # presión) y forzó al sistema a crecer archivos de swap hasta dejar ~1.2 GB
  # libres en disco — se abortó antes de agotarlo. No es un cambio de motor ni
  # de resultado, es cómo se llega a la misma red combinada sin arriesgar la
  # máquina. Ver src/routing/osm_extract.py.
  extract_per_department: true
  osm_pbf:
    source: "Geofabrik — Peru"
    url: "https://download.geofabrik.de/south-america/peru-latest.osm.pbf"   # redirige (302) a un snapshot fechado
    resolved_resource: "peru-260910.osm.pbf"   # nombre real guardado, ver data_cutoff.osm_geofabrik
  # Umbral de snap no aceptable — DECISIÓN METODOLÓGICA DEL PROYECTO (no un
  # dato observado): a esta distancia del nodo vial más cercano, un punto
  # probablemente esté mal geocodificado o en una zona sin cobertura vial
  # mapeada en OSM; forzar el snap ahí daría un tiempo de viaje ficticio.
  snap_max_distance_m: 2000
  cache_dir: "data/cache"
  profiles: ["car", "bike", "foot"]   # reglas explícitas en src/routing/profiles.py
  # --- Corrección de auditoría (2026-09-11): track habilitado en car --------
  # La auditoría independiente de Fase 2 encontró que 1313/5000 demand points
  # snapeaban a un nodo SIN ninguna arista transitable en auto porque su único
  # acceso vial mapeado en OSM era un `track` (trocha); excluirlo del perfil
  # car subestimaba el acceso vehicular rural de forma material (~30% de una
  # muestra controlada recuperaba conectividad al habilitarlo). Se habilita
  # `highway=track` en car con esta velocidad de fallback:
  #   - SUPUESTO DE MODELIZACIÓN, NO una velocidad promedio observada en Perú;
  #   - conservadora (trocha típicamente sin afirmar);
  #   - si el track trae `maxspeed` válido en OSM, se usa ese (misma lógica
  #     general de maxspeed que cualquier otra vía) — este valor es solo el
  #     fallback cuando no hay maxspeed;
  #   - deja la arquitectura preparada para un análisis de sensibilidad
  #     posterior (probar 8/15/20 km/h) sin tocar código, solo este número.
  # path/footway/pedestrian/steps/cycleway NO se habilitan para car.
  car_track_fallback_speed_kmh: 12
  # --- Versionado de perfil (cache) ------------------------------------
  # Los grafos y las matrices se cachean con un hash de los parámetros
  # EFECTIVOS del perfil (tablas de velocidad, exclusiones, este fallback de
  # track, etc. — ver `src/routing/profiles.py::profile_hash`), no solo del
  # cutoff de OSM/buffer/snap. Cambiar una velocidad o una regla de
  # accesibilidad invalida el cache automáticamente la próxima corrida, sin
  # necesidad de borrar carpetas a mano (así se detectó y corrigió el riesgo
  # que la propia auditoría de Fase 2 encontró).
  # --- Conservado por si se retoma OSRM en el futuro (NO usado ahora) -------
  osrm_reserved:
    image: "ghcr.io/project-osrm/osrm-backend:v6.0.0"
    host: "http://127.0.0.1"
    ports: { car: 5001, bike: 5002, foot: 5003 }

# --- Umbrales de acceso (minutos) ----------------------------
access_thresholds_min: [30, 60, 120]

# --- Criterio urbano / rural --------------------------------
urban_rural:
  primary: "inei_ambito"            # usar el campo 'ambito' del centro poblado (INEI)
  fallback_population_threshold: 2000   # si falta 'ambito': urbano si pob >= 2000
  # (Convención INEI aproximada; documentar y revisar en Fase 3.)

# --- Reglas de validación obligatorias — ver §6 para la justificación ----------
validation:
  policy: "no_silent_drops"    # toda exclusión O corrección se registra en el audit CSV con motivo

  facilities:
    min_records_total: 1
    require_unique_key: true
    min_resolutive_in_scope: 1
    category_normalization_coverage_pct: 98.0

    coord_missing:                              # regla 1
      treat_zero_as_missing: true
      zero_tolerance_deg: 1e-6            # CORREGIDO (auditoría 2026-09-11): antes ==0 exacto.
                                            # decisión del proyecto, no del enunciado (ver §6 nota).
      action: "keep_flag_exclude_from_routing"
      max_missing_pct_alarm: 15.0

    coord_out_of_bbox:                          # regla 2
      bbox_ref: "peru_bbox"
      tolerance_deg: 0.0
      action: "keep_flag_exclude_from_routing"
      max_out_of_bbox_pct_alarm: 5.0

    swapped_latlon:                             # regla 3
      enabled: true
      detection: "swap_test_against_bbox"
      confirm_with_district_polygon: true
      action_if_unambiguous: "correct_with_audit"
      action_if_ambiguous: "keep_warning"

    point_outside_declared_district:            # regla 4
      enabled: true
      containment_buffer_m: 1000
      action: "keep_warning"
      # CORREGIDO (auditoría 2026-09-11): el scope departamental usa el texto
      # declarado + este chequeo como verificación cruzada independiente (ver §3).
      department_membership_source: "declared_text_with_geospatial_crosscheck"
      department_column_used_as: "qc_cross_check"

    duplicate_facility_code:                    # regla 5
      key_field: "COD_IPRESS"            # verificado: clave RENIPRESS, 0 duplicados nacionales (Fase 1)
      tie_break_field: null              # no aplica: no se encontraron duplicados en la inspección real
      exact_duplicate_action: "drop_duplicate_keep_first"
      conflicting_duplicate_action: "keep_warning"

    encoding_check:                             # regla 6
      mojibake_check: true
      max_mojibake_pct_alarm: 1.0
      action: "correct_with_audit"

  demand:
    min_records_per_department: 1
    require_unique_key: true
    coord_missing:
      treat_zero_as_missing: true
      zero_tolerance_deg: 1e-6            # ver nota en facilities.coord_missing arriba
      action: "keep_flag_exclude_from_routing"
      max_missing_pct_alarm: 15.0
    coord_out_of_bbox:
      bbox_ref: "peru_bbox"
      tolerance_deg: 0.0
      action: "keep_flag_exclude_from_routing"
      max_out_of_bbox_pct_alarm: 5.0
    swapped_latlon:                             # misma lógica que en facilities (regla 3)
      enabled: true
      detection: "swap_test_against_bbox"
      confirm_with_district_polygon: true
      action_if_unambiguous: "correct_with_audit"
      action_if_ambiguous: "keep_warning"
    point_outside_declared_district:            # misma lógica que en facilities (regla 4)
      enabled: true
      containment_buffer_m: 1000
      action: "keep_warning"
      department_membership_source: "declared_text_with_geospatial_crosscheck"
      department_column_used_as: "qc_cross_check"
    duplicate_facility_code:
      key_field: "CODCP"                # verificado: clave MINEDU de 6 dígitos, 0 duplicados nacionales (Fase 1)
      tie_break_field: null             # no aplica: no se encontraron duplicados en la inspección real
      exact_duplicate_action: "drop_duplicate_keep_first"
      conflicting_duplicate_action: "keep_warning"
    encoding_check:
      mojibake_check: true
      max_mojibake_pct_alarm: 1.0
      action: "correct_with_audit"

# --- Rutas del proyecto ------------------------------------
paths:
  data_raw: "data/raw"
  data_processed: "data/processed"
  data_outputs: "data/outputs"
  data_cache: "data/cache"
  figures: "figures"
  tables: "tables"
  report: "report"
  docs: "docs"
```

## 8. Notas de reproducibilidad

- Entorno: env conda en `./.venv` (Python 3.12), definido en `environment.yml`.
  `requirements.txt` se mantiene como referencia pip.
- Semilla global de sampling: `42` (arriba).
- Ningún dato grande (RENIPRESS, SIGMED, PBF de OSM) se descarga sin autorización
  explícita. Las URLs verificadas están en `docs/00_sources_inspection.md`.
- Toda exclusión o corrección de registros queda auditada en `data/outputs/`
  (política `no_silent_drops`, §6).
- Fechas de corte fijadas por fuente en `data_cutoff` (§4/§7) — evita depender de
  "el dato más reciente" en cada re-ejecución.
- Decisión de motor de routing (`routing.engine`): diagnóstico completo en
  `docs/01_routing_decision.md`; el valor en este archivo no cambia hasta que se
  valide con el usuario.
