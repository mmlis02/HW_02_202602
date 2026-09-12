# 00 — Inspección de fuentes (Fase 0)

Fecha de inspección: **2026-09-10**. Método: lectura de las páginas oficiales
(no se descargó ningún dataset). Todo lo marcado como *pendiente* se confirma en
Fase 1 al abrir el archivo real, con autorización previa.

> Ninguna URL de archivo aquí escrita es inventada: todas provienen de la página
> oficial del dataset leída en la fecha indicada. Aun así, deben re-verificarse
> con una petición `HEAD` antes de descargar (Fase 1).

---

## 1. OFERTA — RENIPRESS / SUSALUD

- **Página del dataset:**
  <https://www.datosabiertos.gob.pe/dataset/registro-nacional-de-entidades-prestadoras-de-servicios-de-salud-renipress>
- **Publicador:** Superintendencia Nacional de Salud (SUSALUD).
- **Licencia:** Open Data Commons Attribution License (ODC-BY).
- **Frecuencia:** mensual (un CSV por corte de fin de mes).
- **Formato:** CSV (uno por mes). Codificación y separador *pendientes* (RENIPRESS
  suele venir en Latin-1 con `;` — confirmar en Fase 1, no asumir).
- **CRS:** coordenadas en columnas de latitud/longitud, se asume EPSG:4326
  (geográficas WGS84) — *pendiente confirmar en el Diccionario de Datos y en el
  rango de valores*.
- **Cobertura:** nacional (todos los establecimientos inscritos en RENIPRESS).
- **Recursos disponibles en la página (leídos el 2026-09-10):**

  | Recurso | Formato | URL | Fecha |
  |---|---|---|---|
  | RENIPRESS - Abril 2026  | CSV | `https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_30-04-2026.csv` | 2026-04-30 |
  | RENIPRESS - Mayo 2026   | CSV | `https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_29-05-2026.csv` | 2026-05-29 |
  | RENIPRESS - Junio 2026  | CSV | `https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_30-06-2026.csv` | 2026-06-30 |
  | RENIPRESS - Julio 2026  | CSV | `https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_31-07-2026.csv` | 2026-07-31 |
  | **RENIPRESS - Agosto 2026** | CSV | `https://www.datosabiertos.gob.pe/sites/default/files/RENIPRESS_31-08-2026.csv` | **2026-08-31** |
  | Diccionario de Datos    | PDF | `https://www.datosabiertos.gob.pe/sites/default/files/Diccionario%20de%20datos%20RENIPRESS.pdf` | s/f |

- **Recurso que usaremos:** el corte **más reciente disponible**, hoy
  `RENIPRESS_31-08-2026.csv` (2026-08-31). Se **fija** ese corte para
  reproducibilidad; si en Fase 1 hay un corte de septiembre, se decide y se
  documenta el cambio.
- **Columnas:** *no listadas aquí a propósito.* El Diccionario de Datos es un PDF
  (Excel exportado, 12-nov-2025) que no se pudo convertir a texto en Fase 0. El
  catálogo de columnas y, sobre todo, (a) el nombre exacto de la columna de
  **categoría**, (b) el nombre y dominio de la columna de **condición/actividad**,
  y (c) los nombres de **lat/lon** y **UBIGEO** se extraen del PDF + del header
  real del CSV en Fase 1. **No se inventan.**
- **Problemas conocidos / a vigilar:**
  - El portal datosabiertos aplica un WAF que puede responder **HTTP 418** a
    clientes sin `User-Agent` de navegador → la descarga programática debe fijar
    un header `User-Agent` realista (se implementa en `src/acquisition.py`).
  - Variantes de texto en la categoría (`"II-1"`, `"II - 1"`, `"II1"`,
    `"SIN CATEGORIA"`, vacío) → de ahí la necesidad de normalización explícita.
  - Establecimientos sin coordenadas o con coordenadas fuera del Perú
    (validación `coord_within_peru_bbox`).
  - Posible corte de septiembre aún no publicado (hoy solo hasta agosto).

## 2. DEMANDA — SIGMED / MINEDU

- **Página de descargas:** <https://sigmed.minedu.gob.pe/descargas/>
- **Publicador:** Ministerio de Educación (MINEDU) — portal SIGMED / MED.
- **Datasets ofrecidos (leídos el 2026-09-10):**
  1. **Locales Escolares** — shapefile (`.shp`). Urbanos referenciales + rurales
     con GPS de MINEDU. Actualizado **05/02/2020**.
  2. **Padrón de Instituciones Educativas** — `.dbf`, se une a locales por
     `CODLOCAL`. Actualizado 05/02/2020.
  3. **Centros Poblados** — shapefile (`.shp`), **`GCS_WGS_1984`** (EPSG:4326).
     Archivo unificado de varias fuentes oficiales; centro poblado identificado
     por **código de 6 dígitos**. Actualizado **05/02/2020**. ← **este es el que
     usamos como demanda.**
  4. **Cartografía Base** — shapefile, escala 1:100 000, hidrografía e hipsografía.
- **Licencia / términos:** el portal indica *disclaimers* de precisión
  (coordenadas de precisión variable según fuente; ubicaciones urbanas
  referenciales; límites administrativos "solo con fines cartográficos"). No
  declara una licencia abierta explícita en la página → **anotar como
  restricción**: uso académico con atribución a MINEDU; confirmar términos al
  descargar.
- **CRS:** `GCS_WGS_1984` (EPSG:4326).
- **Cobertura:** nacional.
- **Fecha de los datos:** **2020-02-05** (dato antiguo — limitación a declarar en
  el informe: los centros poblados y su geometría son de 2020).
- **Descarga programática:** la página de descargas enlaza a archivos `.zip`; las
  **URLs exactas de cada `.zip` no se pudieron confirmar** en la lectura de Fase 0
  (la página usa enlaces/JS que el lector no resolvió a un fichero concreto).
  → **PENDIENTE Fase 1:** inspeccionar el HTML de la página o el panel de red del
  navegador para obtener la URL real del `.zip` de Centros Poblados **antes** de
  descargar. **No se escribe aquí una URL no verificada.**
- **Problemas conocidos:**
  - **SIGMED Centros Poblados no trae campo de población** → para ponderar por
    población hará falta unir con INEI (censo 2017) en Fase 3.
  - Datos de 2020; posibles centros poblados nuevos/renombrados desde entonces.
  - Clasificación urbano/rural: verificar si el shapefile trae un campo `ambito`
    utilizable; si no, aplicar el umbral de población de `config.md`.

## 3. RED VIAL — OpenStreetMap / Geofabrik

- **Página:** <https://download.geofabrik.de/south-america/peru.html>
- **Publicador:** Geofabrik GmbH, a partir de OpenStreetMap.
- **Licencia:** **ODbL 1.0** (Open Database License) — exige atribución
  "© OpenStreetMap contributors" y *share-alike* de derivados de la base.
- **Formato / recursos (leídos el 2026-09-10):**

  | Archivo | URL | Tamaño | Modificado |
  |---|---|---|---|
  | `peru-latest.osm.pbf` | `https://download.geofabrik.de/south-america/peru-latest.osm.pbf` | ~244 MB | 2026-09-10 (datos hasta `2026-09-10T20:21:06Z`) |
  | `peru-latest-free.shp.zip` | `https://download.geofabrik.de/south-america/peru-latest-free.shp.zip` | ~589 MB | ~2026-09-09 |
  | `peru-latest.osm.pbf.md5` | `https://download.geofabrik.de/south-america/peru-latest.osm.pbf.md5` | — | (checksum del `-latest`) |
  | `peru-260910.osm.pbf` (snapshot fechado) | `https://download.geofabrik.de/south-america/peru-260910.osm.pbf` | 255 898 422 B | 2026-09-10 23:35 |
  | `peru-260910.osm.pbf.md5` | `https://download.geofabrik.de/south-america/peru-260910.osm.pbf.md5` | — | 2026-09-10 23:35 |

- **CRS:** EPSG:4326 (OSM siempre en lon/lat WGS84).
- **Cobertura:** todo el Perú. Para el proyecto se **recortará** a los 3
  departamentos + `routing.clip_buffer_km` (25 km) con `pyosmium` en Fase 2, para
  bajar de ~244 MB a algo manejable en disco.
- **Recurso que usaremos:** un **snapshot fechado** (`peru-YYMMDD.osm.pbf`), no
  `-latest`, para que el análisis sea reproducible; se fija la fecha al descargar
  en Fase 2 y se guarda su `.md5`.
- **Problemas conocidos:**
  - **DISCO:** el PBF (~244 MB) + datos OSRM de 3 perfiles + imagen Docker
    superan con holgura el espacio libre actual (~4 GB). **Bloqueante de Fase 2**
    (ver §5 y el informe de Fase 0).
  - Cobertura de caminos rurales en Amazonas/altoandino es irregular en OSM →
    limitación a discutir; los tiempos en zonas sin vías mapeadas saldrán como
    "sin ruta", no imputados.
  - ODbL obliga a citar OSM en el informe y el dashboard.

## 4. LÍMITES ADMINISTRATIVOS — IGN (vía Datos Abiertos)

- **Página del dataset:** <https://www.datosabiertos.gob.pe/dataset/limites-departamentales>
- **Publicador:** Instituto Geográfico Nacional (IGN).
- **Licencia:** Open Data Commons Attribution License (ODC-BY).
- **Escala:** 1:100 000. Descritos como **"límites referenciales"** (no son
  límites de demarcación territorial oficial; suficiente para agregación
  estadística, se declara en el informe).
- **Recursos (leídos el 2026-09-10):**

  | Recurso | Formato | URL | Fecha |
  |---|---|---|---|
  | Límites Departamentales | SHP (.zip) | `https://www.datosabiertos.gob.pe/sites/default/files/DEPARTAMENTOS_LIMITES.zip` | 2023-08-01 |
  | Límites Distritales | SHP (.zip) | `https://www.datosabiertos.gob.pe/sites/default/files/DISTRITOS_LIMITES.zip` | 2023-08-01 |

- **CRS:** no indicado en la página → *pendiente* leer el `.prj` al descargar
  (habitualmente EPSG:4326 en estas capas del IGN).
- **Cobertura:** nacional; departamentos y distritos. **Provincias:** no hay un
  `.zip` de provincias en esta página → se derivan por disolución de distritos
  por los 4 primeros dígitos del UBIGEO, o se busca la capa de provincias del IGN
  en Fase 1. *Pendiente.*
- **Problemas conocidos:**
  - Mismo WAF de datosabiertos (posible HTTP 418 sin `User-Agent` de navegador).
  - "Límites referenciales" ≠ demarcación oficial → matiz para la presentación.
  - Falta capa de provincias como recurso directo.

## 5. Códigos de departamento (UBIGEO)

Verificado contra la Norma Técnica UBIGEO del INEI (búsqueda del 2026-09-10):
los 2 primeros dígitos identifican el departamento, **ordenados alfabéticamente**.

| Departamento | Código |
|---|---|
| Amazonas | `01` |
| Cusco | `08` |
| Tumbes | `24` |

`01` (Amazonas) y `24` (Tumbes) confirmados también en la página UBIGEO de
Wikipedia (que cita al INEI). `08` (Cusco) se sigue del orden alfabético del INEI
(01 Amazonas, 02 Áncash, 03 Apurímac, 04 Arequipa, 05 Ayacucho, 06 Cajamarca,
07 Callao, **08 Cusco**). **Re-confirmación definitiva en Fase 1** contra la
columna de UBIGEO/departamento del propio RENIPRESS y del shapefile IGN.

## 6. Población (para Fase 3, aún no inspeccionada a fondo)

SIGMED no trae población. Se necesitará población por centro poblado / distrito
del **INEI (Censo 2017)**. Fuente concreta y método de unión: **pendiente**, se
inspecciona al inicio de la Fase 3. No se decide nada todavía.

---

## Resumen de lo que queda PENDIENTE de verificar (antes o al inicio de Fase 1)

1. Header y encoding reales del CSV RENIPRESS; nombre exacto de las columnas de
   categoría, condición/actividad, lat, lon, UBIGEO (del Diccionario PDF + CSV).
2. URL real del `.zip` de **Centros Poblados** de SIGMED (no verificada en F0).
3. Términos de uso exactos de SIGMED (no declara licencia abierta explícita).
4. CRS real (`.prj`) de las capas del IGN; capa de **provincias**.
5. `HEAD` de cada URL de descarga (tamaño, `Last-Modified`, código 200) antes de
   bajar nada.
6. Fuente INEI de población (Fase 3).

---

# Fase 1 — verificación real (2026-09-10)

Todo lo de abajo viene de abrir los archivos efectivamente descargados
(`data/raw/`, manifests con sha256 en `*.manifest.json`), no de las páginas.
Resuelve los pendientes de la sección anterior.

## RENIPRESS — `RENIPRESS_31-08-2026.csv`

- **19 763 567 bytes**, confirmado por `HEAD` antes de descargar y por el tamaño
  real del archivo. `Last-Modified: 2026-08-31`.
- **Encoding: UTF-8 con BOM** (`EF BB BF`, verificado con `file(1)` y lectura de
  bytes). **Separador: `;`**. Terminador de línea CRLF. **No** es Latin-1/CP1252
  como se había anticipado en Fase 0 — se verificó antes de fijar el parser, no
  se asumió.
- **31 columnas**, header real:
  `INSTITUCION;COD_IPRESS;NOMBRE;CLASIFICACION;TIPO_ESTABLECIMIENTO;DEPARTAMENTO;
  PROVINCIA;DISTRITO;UBIGEO;DIRECCION;CO_DISA;COD_RED;COD_MICRORRED;DISA;RED;
  MICRORED;COD_UE;UNIDAD_EJECUTORA;CATEGORIA;TELEFONO;HORARIO;INICIO_ACTIVIDAD;
  ESTADO;NORTE;ESTE;IMAGEN_1;FE_ACT_IMAGEN_1;IMAGEN_2;FE_ACT_IMAGEN_2;IMAGEN_3;
  FE_ACT_IMAGEN_3`.
- **36 004 registros nacionales**; **2537 en Tumbes+Cusco+Amazonas** (Cusco 1582,
  Amazonas 791, Tumbes 164).
- `COD_IPRESS` = clave única. **0 duplicados** en los 36 004 registros nacionales.
- `NORTE` = **latitud**, `ESTE` = **longitud** (grados decimales pese al nombre;
  no son coordenadas UTM). 13 174/36 004 nulas a nivel nacional; 600/2537
  (23.65%) en los 3 departamentos — **por encima del umbral de alarma
  `max_missing_pct_alarm=15.0`** configurado (ver reporte de calidad).
- `CATEGORIA`: dominio real observado = `{I-1, I-2, I-3, I-4, II-1, II-2, II-E,
  III-1, III-2, III-E, "0"}`. Las 10 primeras ya vienen en formato canónico
  (no hicieron falta variantes de texto como `"II - 1"` — se implementó la
  tolerancia igual, de forma defensiva); `"0"` = sin categoría asignada
  (8552/36004 nacional). Ningún valor fuera de este catálogo apareció.
- `ESTADO`: dominio real = `ACTIVO(26901)`, `CIERRE TEMPORAL DE OFICIO(4378)`,
  `BAJA DEFINITIVA(3470)`, `BAJA PROVISIONAL(907)`, `BAJA DEFINITIVA DE
  OFICIO(201)`, `BAJA PROVISIONAL DE OFICIO(119)`, `CIERRE TEMPORAL DE
  PARTE(28)`. Solo `ACTIVO` se mapeó a "activo".
- `UBIGEO`: prefijo de 2 dígitos coincide con `DEPARTAMENTO` en el 100% de los
  registros de los 3 departamentos (Tumbes=24, Cusco=08, Amazonas=01);
  1889/1890 UBIGEO nacionales existen en el shapefile de distritos del IGN (el
  único ausente, `160109`, es de Loreto, fuera de alcance).
- **41 establecimientos activos + categoría resolutiva** en los 3 departamentos;
  **40 con coordenadas usables** (1, código `00016758` "HERMANA JOSEFINA
  SERRANO", Cusco, `II-E`, activo, sin lat/lon — se conserva en el dataset,
  excluido del cálculo espacial).

## SIGMED — Centros Poblados

- **URL real**: `https://sigmed.minedu.gob.pe/descargas/archivos/CP_MED.zip`.
  **No estaba en el HTML de la página** (se genera con JS): se encontró leyendo
  `js/mapaeducativo.js`, función `descargashpccpp()` →
  `document.location = "archivos/CP_MED.zip"`. Verificada con `HEAD` (200,
  `application/x-zip-compressed`, 12 179 858 bytes, `Last-Modified:
  2021-12-10`) antes de descargar.
- El `.zip` contiene el shapefile `CP_P.*` + `DICCIONARIO_CP_P.doc`. El
  diccionario (convertido a texto con `textutil`) dice **"Actualizado al
  05/02/2020"** — esa es la fecha de los datos; el `Last-Modified` de 2021 es de
  cuando MINEDU re-empaquetó el zip añadiendo el diccionario.
- `CP_P.prj` = `GCS_WGS_1984` → **EPSG:4326**, confirmado. `CP_P.cpg` = `UTF-8`.
- **19 columnas** reales (`UBIGEO, DEP, PROV, DIST, CODCP, NOMCP, MNOMCP,
  CAPITAL, CON_IE, NIVEL, CPINEI, CPINEI2, FUENTE_INE, FUENTE_G, Z, XGD, YGD,
  Y_X_COORD, geometry`) — coinciden con el diccionario oficial. `XGD`=longitud,
  `YGD`=latitud (grados decimales). **Confirmado: no hay columna de
  población** (ni en el diccionario ni en el shapefile).
- **153 400 centros poblados nacionales**; **19 370 en los 3 departamentos**
  (Cusco 14 813, Amazonas 4217, Tumbes 340) — **supera el límite de 5000**, por
  lo que se aplicó muestreo (ver más abajo).
- `CODCP` = clave única MINEDU (6 dígitos). **0 duplicados**, nacional y en los
  3 deptos. 0 coordenadas nulas/fuera de bbox en el ámbito de estudio.

## Límites administrativos — IGN

- `DEPARTAMENTOS_LIMITES.zip` (4 039 979 bytes) y `DISTRITOS_LIMITES.zip`
  (18 752 137 bytes). **`Last-Modified` real (HEAD): 2025-06-24`** para ambos —
  distinto de la fecha "2023-08-01" leída de la página en Fase 0 (esa era la
  fecha de publicación del *dataset*, no del archivo vigente).
- `DEPARTAMENTOS.shp`: 25 registros, columnas `OBJECTID, CODDEP, DEPARTAMEN,
  CAPITAL, FUENTE`; `FUENTE="INEI"`. CRS confirmado `EPSG:4326` (`.prj`
  `GCS_WGS_1984`). Geometrías válidas, sin vacías.
- `DISTRITOS.shp`: **1891 registros**, columnas `OBJECTID_1, UBIGEO, CODDEP,
  DEPARTAMEN, CODPROV, PROVINCIA, CODDIST, DISTRITO, CAPITAL, FUENTE`. Mismo
  CRS. Geometrías válidas, sin vacías.
- **No existe un `.zip` de provincias** en el portal (`PROVINCIAS_LIMITES.zip`
  devuelve 404, verificado). Se **derivaron** disolviendo `DISTRITOS` por
  `(CODDEP, CODPROV)` — campos reales del shapefile, no inventados. Resultado:
  **23 provincias** en los 3 departamentos (Tumbes 3, Cusco 13, Amazonas 7 —
  coincide con el número real de provincias de cada departamento).
- En los 3 departamentos de estudio: **213 distritos** IGN (Tumbes 13, Cusco
  116, Amazonas 84).

## Muestreo de demanda — desviación documentada

`config.md` (`demand.sampling`) declara un diseño πps ponderado por
`estimated_population` (Horvitz-Thompson). **SIGMED no trae población** y la
fuente INEI se integra recién en Fase 3 — no se puede ejecutar ese diseño hoy
sin inventar pesos. Se implementó en su lugar un **muestreo estratificado por
distrito, con cuota ∝ conteo de centros poblados del distrito** (capacity-
constrained water-filling, `src/demand.py::capacity_constrained_proportional_
allocation`), semilla **42** (`numpy.random.default_rng`), sin reemplazo.

- Antes del muestreo: 19 370 centros poblados en el ámbito (todos con
  coordenadas usables — 0 excluidos por las reglas 1/2).
- Después: **5000** (Cusco 3823, Amazonas 1089, Tumbes 88 — proporcional al
  conteo real de CP por departamento, no por población).
- **Implicancia para las estimaciones**: los resultados de accesibilidad de
  Fase 2/3 basados en esta muestra representan la distribución *territorial* de
  centros poblados, no la distribución *poblacional* — un distrito con muchos
  centros poblados pequeños pesará más que uno con pocos centros poblados
  grandes. Es **PROVISIONAL**: en Fase 3, con población real unida, se
  reemplaza por el diseño ponderado declarado en `config.md` y los resultados
  de Fase 1/2 se re-evalúan bajo el nuevo diseño.

## Reporte de calidad — resultado real

Ver `data/outputs/data_quality_report.csv` (resumen por regla) y
`data/outputs/data_quality_audit_detail.csv` (870 registros individuales
afectados por al menos una regla). Hallazgo que requiere atención antes de
Fase 2: **la regla 1 (coordenadas ausentes) dispara la alarma configurada en
facilities** (23.65% > 15.0%) — 600 de los 2537 establecimientos en los 3
departamentos no tienen lat/lon en RENIPRESS. Solo 1 de los 41 resolutivos se
ve afectado, así que el cálculo principal no se degrada mucho, pero el dato
queda señalado, no oculto.

## Correcciones de auditoría aplicadas (2026-09-11, Parte A)

1. `qc_district_mismatch` ahora se conserva en `facilities.parquet`/`demand.parquet` (antes se calculaba y se perdía).
2. `CPINEI`/`CPINEI2` se conservan en `demand.parquet` cuando existen en el raw (necesarios para la unión de población en Fase 3).
3. `demand.parquet` ahora persiste `stratum_n`, `stratum_sample_n`, `inclusion_prob`, `design_weight` — pesos del **diseño muestral de centros poblados**, NO poblacionales; no se usan todavía para estimaciones de población/cobertura/Gini.
4. `data_quality_audit_detail.parquet` (nuevo, junto al `.csv`) preserva el dtype string de `record_key` — el `.csv` por sí solo pierde los ceros a la izquierda al releerse con pandas por defecto.
5. `coord_missing` ahora usa `zero_tolerance_deg=1e-6` (antes `==0` exacto): 2 facilities con coordenadas `≈-7.8e-07` pasaron de clasificarse (incorrectamente) en la regla 2 a la regla 1.
6. `config.md` §3 corregido: el ámbito departamental se filtra por texto declarado + verificación geoespacial independiente (no por unión espacial como se documentaba antes) — refleja lo que el código realmente hace; se aclara que es decisión del proyecto, no requisito del enunciado.
7. Tests de integración añadidos en `tests/test_integration_phase1.py` (`process_facilities`, `process_demand`, cadena de `boundaries`).

Recuentos actualizados tras estas correcciones: regla 1 (facilities) 600→**602**; regla 2 (facilities) 2→**0**. El resto de conteos no cambia.
