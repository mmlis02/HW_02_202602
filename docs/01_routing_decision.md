# 01 — Diagnóstico y decisión de motor de routing (Fase 0.5)

Fecha: 2026-09-10. Ninguna alternativa fue implementada todavía; este documento
es solo diagnóstico + recomendación, pendiente de validación del usuario.

## 1. Diagnóstico práctico del entorno (no solo "¿está el CLI instalado?")

Comandos ejecutados directamente en la máquina (no supuestos):

| Componente | Resultado real | Comando |
|---|---|---|
| Docker CLI | Instalado, v27.3.1 (binario suelto en `~/.local/bin/docker`, sin Docker Desktop) | `docker --version` |
| **Docker daemon** | **NO corriendo.** `Cannot connect to the Docker daemon at unix:///var/run/docker.sock` | `docker ps` |
| Docker Desktop | No instalado (`/Applications/Docker.app` no existe) | `ls /Applications` |
| Colima | Instalado v0.10.3, pero **`colima start` falla**: `dependency check failed for VM: lima not found, run 'brew install lima'` | `colima status` |
| `limactl` | No está en el PATH | `which limactl` |
| Homebrew | **No instalado** → no se puede `brew install lima/docker` de forma estándar | `which brew` |
| Hypervisor.framework | Disponible (`kern.hv_support = 1`) → técnicamente SÍ se podría virtualizar si hubiera un runtime instalado | `sysctl kern.hv_support` |
| CPU | Apple M2, 8 núcleos — no es un cuello de botella | `sysctl machdep.cpu.brand_string` |
| **RAM total** | 8 GiB | `sysctl hw.memsize` |
| **RAM libre AHORA** | **~0.06 GiB libre**; swap **9.58 / 10 GiB en uso** (encriptado) | `vm_stat`, `sysctl vm.swapusage` |
| **Disco libre AHORA** | **~5.6 GiB** en el volumen de datos, 97% ocupado | `df -h` |
| Java | OpenJDK Corretto 11.0.31 disponible (relevante solo si se evaluara r5py) | `java -version` |

**Conclusión del diagnóstico: NO basta con "Docker CLI está instalado" para decir
que OSRM es viable.** Hay dos bloqueantes independientes, cualquiera de los dos
ya lo impide:

1. **No hay ningún runtime de contenedores funcionando** (ni Docker Desktop, ni
   Colima operativo — falta `lima`, que a su vez requiere Homebrew, que no está
   instalado). Instalar `limactl` como binario suelto (sin `brew`, igual que se
   hizo con `colima`/`docker`) es técnicamente posible pero **no resuelve el
   punto 2**.
2. **La máquina está bajo presión de memoria severa en este momento** (swap al
   96% de su capacidad, <100 MB de RAM libre). Levantar una VM de Colima/Lima
   (mínimo ~2 GB de RAM asignados) sobre un sistema que ya está intercambiando a
   disco es un riesgo real de congelar la máquina, independientemente del disco.

## 2. Estimación de espacio si se resolviera el runtime

| Componente | Estimado |
|---|---|
| VM Linux de Colima/Lima (SO + overhead) | ~2–3 GB |
| Imagen `ghcr.io/project-osrm/osrm-backend` | ~0.6–1 GB |
| PBF de Perú recortado a 3 deptos + 25 km | ~30–80 MB (vs. 244 MB del Perú completo) |
| Datos procesados OSRM (extract+partition+customize) × 3 perfiles (car/bike/foot) | ~0.6–1.5 GB |
| **Total aproximado** | **~4–6 GB, mínimo** |

Frente a **~5.6 GB libres actuales** (que ya bajaron de ~5.0 GB al crear el
`.venv` en Fase 0), el margen es prácticamente nulo — sin contar que el propio
sistema operativo seguirá consumiendo espacio. **No es prudente intentarlo sin
liberar espacio primero**, y aun liberándolo, el problema de RAM (punto 1.2)
sigue sin resolverse solo con espacio en disco.

## 3. Alternativas evaluadas (ninguna implementada aún)

### (a) Liberar espacio + instalar runtime real
- Requiere: liberar ~15–20 GB (hay margen: `~/Library` 55 GB, `~/Movies` 27 GB,
  `~/Downloads` 23 GB — decisión del usuario, no mía) y conseguir Homebrew (con
  contraseña de administrador) o `limactl` como binario suelto.
- **No resuelve la presión de RAM actual** (swap al 96%): puede aliviarse
  cerrando otras apps, pero es una condición externa que puede repetirse.
- Es el único camino que deja **OSRM real** (motor recomendado por el enunciado),
  con su modelo de red vial completo (giros, sentidos, penalizaciones).

### (b) OSRM remoto
- El cliente (`src/routing.py`) ya está diseñado para apuntar a `config.routing.host`
  — no exige cambiar de arquitectura, solo levantar OSRM en otra máquina/nube y
  cambiar esa URL.
- Quita presión de disco/RAM local, pero introduce una dependencia externa (una
  máquina que hay que provisionar, mantener accesible, y que un tercero que
  reproduzca el proyecto también necesitaría, o tendría que montar su propio
  OSRM con las instrucciones que dejemos). No resuelve el problema **hoy**, solo
  lo traslada.

### (c) OSMnx / pyrosm + NetworkX (grafo local, sin contenedor)
- Construye el grafo vial directamente del PBF recortado (`pyrosm` lee `.osm.pbf`
  nativamente; `osmnx`/`networkx` para el grafo y caminos mínimos), sin Docker,
  sin VM, sin daemon.
- **Idea clave para el tamaño del problema real:** los **destinos** (establecimientos
  resolutivos) son pocas decenas, mientras que los **orígenes** (demand points)
  son hasta 5 000. Un Dijkstra de una sola fuente por cada **establecimiento
  resolutivo** (invirtiendo el sentido del grafo) entrega, en una sola pasada por
  perfil, el tiempo desde ESE establecimiento a **todos** los nodos de la red —
  de ahí se lee directamente la fila de la matriz completa origin × facility para
  ese establecimiento. Con un puñado de establecimientos resolutivos (decenas, no
  miles) × 3 perfiles, son unas pocas decenas de ejecuciones de Dijkstra sobre un
  grafo ya recortado a 3 departamentos — nada comparable a rutear 5 000 × N pares
  uno por uno.
- Requiere modelar velocidades por tipo de vía (`highway`, `maxspeed`, `surface`)
  para cada perfil: **más trabajo de diseño que usar los perfiles ya afinados de
  OSRM**, y sin lógica de giros/sentidos — limitación real a documentar.
- Caching: trivial (el grafo se serializa una vez a `data/cache/`; la matriz
  calculada se guarda en parquet).
- Reproducible: 100% determinista, sin servicio externo, versiones fijables por
  `environment.yml`.
- Sin límites de API (todo corre en el proceso local).
- Dependencias nuevas (`osmnx`, `pyrosm` o `pyosmium`) son paquetes Python
  puros/binarios livianos vía conda-forge — no un contenedor.

### (d) OpenRouteService (ORS) como fallback
- **API pública**: cuotas y límites de tasa (decenas de peticiones/minuto y un
  máximo de ubicaciones por petición de matriz) muy por debajo de lo que exige
  una matriz de 5 000 × N × 3 perfiles de forma reproducible — forzaría un
  fraccionamiento masivo y dependencia de disponibilidad/latencia de un tercero.
  Además necesita una API key (gestión de credenciales, límite diario).
- **ORS autoalojado**: corre sobre JVM y típicamente necesita **más RAM** que
  OSRM para un extracto comparable (heap de varios GB) — mismo problema de
  runtime/contenedor que OSRM, pero peor en memoria. No resuelve nada que OSRM
  no resuelva ya, y añade una JVM.
- Conclusión: **solo como último recurso**, no como plan principal para este
  entorno.

## 4. Recomendación para ESTE entorno

Ver la sección **B** de la respuesta al usuario (resumen ejecutivo). Este
documento queda como respaldo técnico del diagnóstico.

## 5. Decisión final validada (2026-09-11)

El usuario confirmó explícitamente la opción (c): **NetworkX local sobre un
grafo construido de un extracto de OSM (pyrosm)**, sin OSRM local, sin API
remota. `config.md routing.engine = "networkx_local"`.

### Ajuste real encontrado durante la implementación: extracción por departamento

El plan original recortaba con la unión de los 3 departamentos + buffer de
25 km en un solo paso. Al ejecutarlo (2026-09-11), `pyrosm.get_network()` sobre
esa unión (~201 600 km², ~16% de Perú) **agotó la RAM** de esta máquina y forzó
al sistema a crecer archivos de swap (`/System/Volumes/VM/swapfile11`,
`swapfile12`) hasta dejar ~1.2 GB libres en el disco de 228 GB — se abortó el
proceso antes de que seguir empeorando fuera irreversible.

Se cambió a extraer **un departamento a la vez** (`src/routing/osm_extract.py`),
liberando memoria (`gc.collect()`) entre uno y otro y cacheando cada uno por
separado antes de combinarlos. Resultado real:

| Departamento | Nodos | Edges | Tiempo | RAM pico aprox. |
|---|---:|---:|---:|---:|
| Tumbes | 121 743 | 126 625 | ~65 s | ~500 MB |
| Amazonas | 793 513 | 806 236 | ~4.5 min | ~610 MB |
| Cusco | (ver informe final) | (ver informe final) | (ver informe final) | (ver informe final) |

Esto **no** es un cambio de motor ni de resultado — es cómo se llega de forma
segura a la misma red combinada en esta máquina concreta. Documentado también
en `config.md` (`routing.extract_per_department: true`).

Cusco (el más grande): 2 497 788 nodos, 2 533 846 edges — la extracción tomó
~8-9 min y llegó a picos de RSS de hasta ~1.3 GB, sin repetir el problema (el
enfoque por departamento se sostuvo también en el caso más grande).

## 6. Corrección de auditoría (2026-09-11) — `track` habilitado en car

La auditoría independiente de Fase 2 encontró que **1289-1313 demand points
snapeaban a un nodo sin ninguna arista transitable en el perfil car**
(dependiendo de si se cuenta por nodo único o por punto de demanda — varios
puntos pueden compartir el nodo más cercano), y que el 100% de una muestra de
esos nodos solo tenía aristas `track`/`path` incidentes — exactamente los
tipos que car excluía. Una prueba controlada (grafo diagnóstico
`car_with_track`, solo Cusco, muestra de 30 puntos aislados) mostró que ~30%
recuperaba conectividad con track habilitado, con tiempos de 5.6-105 min —
viajes reales, lentos, no artefactos.

**Decisión**: se habilita `highway=track` en el perfil car con una velocidad
de fallback **configurable y conservadora** (`config.md`
`routing.car_track_fallback_speed_kmh`, valor inicial 12 km/h) — un supuesto
de modelización explícito, no una velocidad observada en campo en Perú. Si el
`track` trae `maxspeed` válido en OSM, se usa ese valor (misma lógica general
que cualquier otra vía). `path`, `footway`, `pedestrian`, `steps`, `cycleway`
siguen excluidos de car — solo se tocó `track`.

**Resultado real tras habilitarlo** (corrida completa, 5000 demand points,
seed 42 sin cambios):

| | ANTES (sin track) | DESPUÉS (con track, 12 km/h) |
|---|---:|---:|
| car routed (de 4674 snap-ok) | 3271 (70.0%) | 3721 (79.6%) |
| car routed (de 5000 totales) | 65.4% | 74.4% |
| previamente aislados que recuperan arista | — | 494/1313 |
| previamente aislados que recuperan ruta a una resolutiva | — | 408/1313 |
| siguen aislados incluso con track | — | 819/1313 |

Confirma el hallazgo de la auditoría: el impacto es material (+450 demand
points con acceso vehicular a una resolutiva), no marginal, y concentrado en
Amazonas/Cusco (zonas rurales/andinas). El valor de 12 km/h **no se declara
definitivo** — la arquitectura (parámetro en `config.md` + `profile_hash`
para invalidar cache) queda lista para un análisis de sensibilidad posterior
(p.ej. 8/15/20 km/h) sin tocar código.

## 7. Versionado de perfil (`profile_hash`) — corrección de auditoría

La auditoría encontró que ni el grafo cacheado (`graph_{mode}.pkl`, sin
versión en el nombre) ni la clave de cache de las matrices dependían del
perfil de velocidades/accesibilidad — tuvimos que borrar `data/cache/graphs/`
a mano esta sesión al habilitar `track`, porque el sistema no lo habría
detectado solo. Corregido: `src/routing/profiles.py::profile_hash(mode, cfg)`
hashea (SHA-256, primeros 16 hex) los parámetros EFECTIVOS del perfil (tablas
de velocidad, exclusiones, fallback de track, rango válido de maxspeed) más
dos "versiones de lógica" manuales (`ONEWAY_LOGIC_VERSION`,
`MAXSPEED_PARSE_LOGIC_VERSION`) para la parte que es código, no datos. El
grafo se cachea como `graph_{mode}_{profile_hash}.pkl` y la matriz bajo
`.../{mode}/{cache_version}__{profile_hash}/`. Un cambio de perfil hace que el
archivo/carpeta esperados simplemente no existan → se reconstruye solo, sin
intervención manual. `bike`/`foot` no cambiaron de perfil esta vez, pero sí
cambió el ESQUEMA de la matriz (columna `routing_status`, universo completo
de 5000 demand points en vez de solo los snapeados) para los 3 modos por
requisito de la corrección — eso obligó a re-ejecutar Dijkstra también para
bike/foot (grafo reutilizado del cache, sin re-extraer OSM; solo el cómputo,
barato, ~110-140 s por modo, se repitió).

## 8. Limitación cross-departamento — estado documentado, no "corregido"

La auditoría demostró (cota geodésica, 100% de los 3271 demand points
reachable-en-car de la corrida anterior) que ningún nearest resolutive actual
puede cambiar por evaluar los pares cross-departamento — ver
`docs/00_...` no aplica aquí, ver el informe de auditoría del 2026-09-11. Por
eso esos pares **no se recalculan sobre un grafo nacional**: se etiquetan
explícitamente `routing_status="cross_department_not_evaluated"` (80 937
pares en la matriz de auto, 40.47% de las 200 000 celdas totales) en vez de
mezclarse con "sin ruta" — ver `src/routing/status.py` y
`docs/02_routing_outputs_schema.md`.
