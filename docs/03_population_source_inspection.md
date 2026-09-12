# 03 — Inspección de fuente de población INEI (Fase 3, 2026-09-11)

## CORRECCIÓN (misma fecha, segunda ronda): la conclusión original era INCORRECTA

Todo lo que sigue en este documento hasta la sección "Corrección" fue la
investigación real de la primera ronda, que concluyó (erróneamente) que no
existía una fuente oficial descargable de población por centro poblado. Esa
conclusión fue **revisada y descartada** tras que el usuario señalara tres
fuentes adicionales no verificadas en la primera ronda. Se probaron
directamente, con evidencia real:

- **CENEPRED/SIGRID** (`https://sig.cenepred.gob.pe/sigrid/rest/services/S06_ICO/MapServer/2110002`)
  — servicio ArcGIS REST **vivo** (no estaba caído; el error de la primera
  ronda fue no haberlo probado). Metadata confirma `codccpp` (string, 10
  caracteres) y `pob_total`, fuente declarada explícitamente: *"Fuente: INEI
  - Censo de Población y Vivienda, 2017"*. Paginación real vía
  `resultOffset` (maxRecordCount=2000). Descargado para los 3 departamentos:
  **12 332 registros** (TUMBES 190, AMAZONAS 3174, CUSCO 8968), 0 IDs
  duplicados. Guardado en `data/raw/inei_cenepred/ccpp_raw.parquet` +
  manifest.
- **MINAM Geoservidor** (`.../Servicio_Oportunidades_Inversion/MapServer/16`)
  — también vivo, mismos 3 conteos por departamento EXACTOS (190/3174/8968),
  0 IDs duplicados. Campos `idccpp_17` (10 dígitos, mismo formato/valores
  que `codccpp` de CENEPRED), `pob17`, `area_17`. Guardado en
  `data/raw/inei_minam/ccpp_raw.parquet` + manifest.
- **Validación cruzada CENEPRED×MINAM** (por `codccpp`==`idccpp_17`): sobre
  **12 312 registros comparables, 100.00% con población IDÉNTICA** (0
  discrepancias) y 99.89% con nombre idéntico — evidencia contundente de que
  ambos redistribuyen exactamente el mismo producto censal INEI 2017.
- **REDATAM** (`.../Dictionary?BASE=CPV2017&ITEM=DICALL`): confirmado vivo
  (200 OK); su diccionario oficial de variables **sí** lista la entidad
  `Cenpob` con `CODCCPP` y `REDCODEN`, coincidiendo con el nombre de
  variable usado por CENEPRED — confirmación adicional de que `codccpp` es
  la convención oficial INEI, no un identificador ad-hoc de un portal
  externo. No se automatizó una consulta numérica CP-por-CP contra la
  interfaz interactiva de REDATAM (requiere navegar un flujo de sesión con
  menús en cascada, no un endpoint simple) — se consideró innecesario dado
  que CENEPRED y MINAM (dos canales independientes, dos ministerios
  distintos) ya concuerdan al 100% entre sí, evidencia más fuerte que una
  muestra manual de ~20 CP.
- **Estructura de claves real** (universo 19 370 SIGMED de los 3
  departamentos, antes de la muestra de 5000): `CPINEI` (10 dígitos,
  presente en 12 308/19 370 = 63.5%) coincide con `codccpp` de CENEPRED en
  **99.3%** de los casos con `CPINEI` no nulo (12 222/12 308), y con
  `idccpp_17` de MINAM en **99.4%** (12 236/12 308). `CPINEI2` (10 dígitos,
  presente en solo 47/19 370 = 0.2%) es una clave secundaria/alternativa,
  nunca independiente (todo registro con `CPINEI2` también tiene `CPINEI`);
  en 11 de 12 casos de la muestra de 5000, `CPINEI` y `CPINEI2` apuntan a
  CENTROS POBLADOS DISTINTOS con población distinta — no se resuelve
  arbitrariamente: se usa `CPINEI` como clave primaria y se expone
  `secondary_key_disagrees_with_primary=True` en esos 11/12 casos para
  auditoría (`build_population_match_report`, `src/metrics.py`).
- **Decisión (ítem 8 de la instrucción)**: **A. CENEPRED usable como
  redistribución oficial del Censo INEI 2017** — identificadores
  compatibles (99.3%), población consistente (100% de acuerdo con MINAM),
  cobertura alta (62.8% de la muestra de 5000, 63.1% del universo de
  19 370). Se usa CENEPRED como fuente primaria de `population`, MINAM como
  validación cruzada + fuente de `urban_rural` (`area_17`, cobertura
  también ~62.8%, muy superior al 26.7% del intento anterior con IGN).
- **Match sobre el universo de 19 370** (antes del muestreo): 12 222
  matched (63.1%), 7148 unmatched (36.9%), 0 ambiguous (CENEPRED no tiene
  IDs duplicados).
- **Control poblacional por departamento** (población matched observada vs.
  benchmark censal real MIMP/INEI 2017): captura solo 19.9% (CUSCO), 29.2%
  (AMAZONAS), 33.1% (TUMBES) del total departamental — **esperado y
  explicable matemáticamente**: (a) SIGMED no contiene todos los CP del
  censo (solo 19 370 vs. cientos de miles a nivel nacional, y dentro de los
  3 departamentos el match de `CPINEI` ya es solo 63%); (b) la muestra
  analizada es de 5000 de esos 19 370; (c) el `design_weight` expande la
  MUESTRA al universo de 19 370 (`stratum_n`), no al total del censo, así
  que ninguna expansión de esta muestra puede reproducir el 100% del censo
  departamental — es una comparación de dos universos distintos (universo
  de centros poblados SIGMED con IE, vs. censo poblacional completo), no
  una falla del método.
- **Urbano/rural**: `area_17` de MINAM verificado empíricamente (no por
  documentación oficial hallada, pero por perfil poblacional real): valor
  1 = urbano (media pob=3081, mediana=646 en los 3 departamentos), valor 2 =
  rural (media=50, mediana=17); valor 3 (solo 4 registros a nivel nacional,
  ninguno en los 3 departamentos con población≠0 relevante) se mapea a
  `unknown` — no se adivina su semántica sin documentación.

**Todo el material de la primera ronda (abajo) se conserva por
trazabilidad**, pero la fuente IGN `CCPP_0.zip` y la clasificación
urbano/rural basada en `CAT_POBLAD` quedan **supersedidas**, no eliminadas
(`build_urban_rural_classification`, en `src/analysis.py`, se conserva como
resguardo pero ya no se usa por defecto).

---

## Resultado (primera ronda, SUPERSEDIDO): BLOQUEO DOCUMENTADO, no resuelto por invención

Se buscó una fuente oficial de INEI con **población por centro poblado**,
identificable por un código compatible con `CPINEI`/`CPINEI2` de SIGMED
(formato observado: 10 dígitos, p.ej. `"0808070134"` = UBIGEO de 6 dígitos +
secuencia de 4). **No se encontró ni se pudo verificar un archivo
programáticamente descargable con esa granularidad y ese campo.** Se
documenta cada fuente revisada, con evidencia real, en vez de inventar un
archivo o una URL.

## Fuentes revisadas

1. **REDATAM Censos 2017** (`https://censos2017.inei.gob.pe/redatam/`) — es
   el sistema OFICIAL de consulta del Censo 2017. Verificado: es una interfaz
   de consulta interactiva (drill-down por ubicación), **no expone un export
   masivo CSV/Excel de población por centro poblado** vía una URL fija.
2. **Directorio Nacional de Centros Poblados — Censos 2017** (INEI, Lib1541,
   `https://www.inei.gob.pe/media/MenuRecursivo/publicaciones_digitales/Est/Lib1541/index.htm`) —
   es exactamente el producto que debería tener esta información (título
   confirmado), pero el contenido real está en PDFs de gran tamaño
   (`tomo1.pdf`, `tomo2.pdf`) — tablas de ~94 922 centros poblados en PDF, no
   viables de extraer de forma confiable ni reproducible en el tiempo de esta
   fase (y el enunciado exige no inventar el parseo).
3. **`microdatos.inei.gob.pe` / `proyectos.inei.gob.pe/microdatos/`** —
   portal oficial de microdatos (encuestas + censos), formatos SPSS/CSV/STATA.
   Requiere selección interactiva de módulo/año en un formulario (no hay URL
   directa verificable de un archivo agregado de población por CP), y la
   base completa del Censo 2017 es a nivel persona/vivienda (millones de
   registros) — agregarla a nivel CP excede el alcance de esta fase sin una
   URL de descarga concreta que poder verificar primero.
4. **IGN "Dataset Centros Poblados"** (datosabiertos.gob.pe,
   `https://www.datosabiertos.gob.pe/sites/default/files/CCPP_0.zip`) —
   **descargado y verificado realmente** (6 019 493 bytes, sha256 en
   `data/raw/inei/CCPP_0.zip.manifest.json`, `Last-Modified: 2025-05-26`).
   136 587 puntos, columnas `OBJECTID, NOM_POBLAD, FUENTE, CÓDIGO, CAT_POBLAD,
   DIST, PROV, DEP, CÓD_INT, CATEGORIA, X, Y, N_BUSQDA`. El campo `CÓDIGO` es
   de 10 dígitos y **con el mismo formato que `CPINEI`** (confirma que ambos
   catálogos comparten esquema de codificación) — pero **no tiene ningún
   campo de población** (confirmado por inspección real de las columnas, no
   solo de la descripción de la página). `FUENTE` indica si el punto viene de
   INEI o IGN, no es una variable de población.
5. **`dportalgis.vivienda.gob.pe/.../ccpp_inei/MapServer/0`** (capa ArcGIS
   REST citada como "Centros Poblados INEI Censo 2017 Población-Vivienda",
   hallada en búsqueda) — **el dominio no resuelve** (`curl`: "Could not
   resolve host"), verificado dos veces. No se pudo usar ni confirmar.
6. **`data.opendatasoft.com/.../centros-poblados-inei-censo-2017-poblacion-vivienda`** —
   mirror de **terceros** (portal comercial, namespace `bogota-laburbano`), no
   es una fuente oficial de INEI. Se descarta explícitamente por instrucción
   del usuario de usar una fuente OFICIAL.

## Fuentes adicionales revisadas (segunda ronda, misma sesión)

7. **GEOCATMIN/INGEMMET** ArcGIS REST, capa "Centros Poblados - INEI"
   (`https://geocatmin.ingemmet.gob.pe/arcgis/rest/services/SERV_OTRAS_FUENTES/MapServer/20`)
   — **verificado con GET real** (`?f=json`, 200 OK). Sí tiene un campo de
   población (`TOT_POB99`, alias "Poblacion"), pero: (a) el sufijo `99`
   confirma que es **población de 1999** (o del censo anterior a 2017,
   probablemente Censo 1993/proyección), no del Censo 2017 exigido; (b) la
   propia descripción del servicio dice explícitamente *"la fuente no
   oficial de la información es del INEI... dicha información es
   referencial y solo para uso de ubicación referencial en campo"* — se
   auto-declara no oficial y no apta para análisis; (c) su código
   (`CODCCPP02`, 4 caracteres) no tiene el formato de 10 dígitos de
   `CPINEI`. Descartada por las tres razones.
8. **SIGRID/CENEPRED** ArcGIS REST (`sigrid.cenepred.gob.pe/.../tcp_informacion_complementaria/MapServer/2010000`)
   — intento real de GET a `?f=json`: la primera ruta devolvió una página
   HTML de configuración/error (no JSON), y una segunda ruta al mismo
   MapServer padre falló la conexión (`http_code=000`). Servidor no
   confiable/no accesible de forma verificable. Descartada.
9. **`dportalgis.vivienda.gob.pe`** — reintento de DNS en esta segunda
   ronda: `nslookup` devuelve **NXDOMAIN** explícito (no es un fallo de red
   transitorio, el dominio no existe). Confirma definitivamente el hallazgo
   original.
10. **`inei.gob.pe/media/MenuRecursivo/Cap03020.xls`** ("Población estimada
    y proyectada...") — descargado y verificado con GET real (200 OK, 19 968
    bytes). Metadatos internos del archivo Excel (`Create Time: 2012-07-17`,
    `Last-Modified` HTTP: 2013-09-04) confirman que es **anterior al Censo
    2017** — es de una serie de proyecciones más antigua. Descartada por
    fecha (no corresponde a la fuente censal exigida).
11. **MIMP (`mimp.gob.pe`), `2_Inf_de_Poblacion-CensoNacional-2017.xlsx`**
    — descargado y verificado con GET real (200 OK, 262 095 bytes, hoja
    `DISTRITAL`, 3734 filas). Es un archivo de un **ministerio del Estado
    peruano** (no INEI directamente) que republica agregados del **Censo
    Nacional 2017: XII de Población y VII de Vivienda** citando
    explícitamente `FUENTE: CENSO 2017` en cada bloque de columnas.
    Contiene `UBIGEO` (6 dígitos), `DEPARTAMENTO`, `PROVINCIA`, `DISTRITO` y
    población por tramo etario (0-5, 6-11, 12-17, 18-29, 30-44, 45-59, 60+),
    cuya suma da la población total censada 2017 **a nivel DISTRITO**. Es
    real, oficial (cita la fuente censal primaria de forma verificable) y
    descargable — pero es **agregado distrital, no por centro poblado**: NO
    resuelve el requisito de población por CP, y usarlo como tal violaría
    el principio de no confundir granularidades. Se adopta **solo** como
    insumo de un chequeo secundario de representatividad (comparar la
    distribución de la muestra por departamento/distrito contra la
    población real 2017), nunca para construir `analysis_weight_i` por CP.
    Guardado en `data/raw/inei/2_Inf_de_Poblacion-CensoNacional-2017.xlsx`
    con manifest.

## Decisión

**No existe, tras 11 fuentes reales verificadas, un archivo de población
por CENTRO POBLADO descargable y oficial.** `demand.parquet` (SIGMED) se
mantiene como está — `CPINEI`/`CPINEI2` ya estaban preservados desde Fase 1
precisamente para este cruce, y siguen ahí, listos, para cuando se
identifique un archivo real a ese nivel.

Sí se identificó y se descargó (fuente #11) un archivo oficial de
**población DISTRITAL** (Censo 2017, republicado por MIMP). Se usa
**exclusivamente** como benchmark externo de representatividad
departamental/distrital (comparar cuántos CP de la muestra caen en cada
departamento/distrito contra la población real de ese departamento/distrito)
— nunca como `population_i` de un centro poblado individual.

Toda la arquitectura de Fase 3 (`src/metrics.py`) se construyó y probó de
forma **genérica**: recibe cualquier tabla de población indexada por un
código compatible con `CPINEI`, calcula el cruce, y clasifica
`matched`/`unmatched`/`ambiguous`. Como no hay tabla real, la corrida real de
esta fase produce **`population_match_status="unmatched"` para los 5000
demand points** — un resultado honesto, no una simulación. En cuanto se
consiga (o el usuario indique) un archivo real de población por centro
poblado con código compatible, el mismo código produce el cruce real sin
cambios.

## Clasificación urbano/rural (Metric 6) — fuente real, cobertura parcial

El shapefile IGN `CCPP_0.zip` (fuente #4, sin población) sí trae un campo
`CAT_POBLAD` con la **categoría de centro poblado** (`CASERÍO`,
`UNID. AGROPECUARIA`, `ANEXO`, `PUEBLO`, `CIUDAD`, `VILLA`,
`URBANIZACION`, `PP.JJ.AA.HH.`, `BARRIO O CUARTEL`, `CAMPO MINERO`, etc.) —
esta es exactamente la tipología que INEI usa en su propia documentación
censal para derivar el área urbana/rural (urbano: Ciudad, Pueblo, Villa,
Urbanización, Asentamiento Humano/Pueblo Joven, Balneario, Conjunto
Habitacional, Cooperativa de Vivienda, Barrio/Cuartel; rural: Caserío,
Anexo, Unidad Agropecuaria, Comunidad, Cooperativa Agraria, Campo Minero,
Otros). Se adopta esta regla (documentada en `config.md`, sección
`urban_rural_classification`) como la "regla oficial reproducible basada en
definiciones de INEI" que pide el enunciado cuando no hay un campo
urbano/rural directo.

**Verificado (cruce real por `CPINEI`)**: de los 3162 demand points con
`CPINEI` no nulo, solo **1335 (42.2%)** tienen `CÓDIGO` coincidente en el
shapefile IGN — el resto (incluidos los 1838 sin `CPINEI` en absoluto) queda
como `urban_rural_status="unknown"`, nunca inventado. `CPINEI2` casi no
solapa (3/12) y `CÓD_INT` no solapa nada (0/3162) — se usa exclusivamente
`CPINEI` vs `CÓDIGO` para este cruce, documentado explícitamente como
**cobertura parcial (42% de los que tienen CPINEI, 26.7% del total de 5000)**.

## Qué se necesitaría para desbloquear esto

- Un archivo tabular (CSV/Excel/SPSS) descargable por URL verificable, con al
  menos: código de centro poblado (10 dígitos, compatible con `CPINEI`) y
  población total.
- Alternativa de menor granularidad (si no existe a nivel CP): población
  **distrital** oficial (UBIGEO de 6 dígitos) — permitiría al menos una
  agregación a nivel distrito/provincia/departamento (no a nivel CP
  individual), declarando explícitamente esa limitación de granularidad. No
  se implementó esta alternativa sin que el usuario decida si la acepta,
  porque cambia el significado de "población del centro poblado" que pide el
  enunciado (sería población del distrito repartida, no observada por CP).
