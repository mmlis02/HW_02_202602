# 04 — Notas de Fase 3 (hallazgos puntuales)

## Advertencia de interpretación: ranking de brechas críticas y distritos con cobertura de POBLACIÓN (no de ruteo) nula

`rank_critical_gaps` marca 7 distritos con `low_routing_coverage_warning`
por tener 0%/NaN de población con tiempo estimable. Auditado caso por caso:
en **El Cenepa, Río Santiago, Vista Alegre, Megantoni, Machupicchu** el 0%
refleja una falla REAL de ruteo (0 CP con `routing_status_car="routed"`).
Pero en **Wanchaq** (distrito urbano central de Cusco) y **Luya Viejo**, el
ruteo en sí funciona bien (7/9 CP `routed` en Wanchaq) — el 0%/NaN viene de
que **ninguno de sus CP tiene población matched** (join CPINEI×CENEPRED sin
éxito para esos CP puntuales), no de un problema de accesibilidad vial. La
métrica actual no distingue estas dos causas (cobertura de ruteo vs.
cobertura de join poblacional) porque ambas colapsan en
`analysis_weight=NaN`. **No se corrigió en esta fase** (evitar scope creep)
— se documenta como limitación conocida: al leer el ranking de brechas,
verificar `routing_status_car` a nivel CP antes de concluir que un distrito
con la advertencia tiene mala accesibilidad vial real.


## Investigación `foot_time / car_time > 100×` (pendiente de Fase 2)

27 casos reales (`data/outputs/foot_over_car_extreme_ratio.csv`), ratio
100.5×–353.3×. Evidencia real revisada:

- En los **27/27** casos, `nearest_facility_car != nearest_facility_foot`
  (0% coinciden) — el modo a pie nunca llega a la misma facility que el
  auto en estos casos.
- `distance_m_foot / distance_m_car` (mismos 27 casos) va de **7.5× a
  26.3×**, con `distance_m_foot` siempre >150 km. No es un problema de
  velocidad asumida (5 km/h peatonal) sino de **qué facility resulta
  "nearest" en cada grafo**: la facility geométricamente más cercana (la que
  usa el auto) no es alcanzable — o es alcanzable solo con un rodeo enorme —
  en el grafo peatonal, así que el nearest-por-modo peatonal termina siendo
  una facility distinta y mucho más lejana.

**Clasificación**: artefacto de **topología/componente dependiente del
perfil** (no error de datos de OSM confirmado, no error de código). El
grafo peatonal excluye vías que el auto sí usa (p. ej. tramos tipo
`motorway`/`trunk` sin equivalente peatonal paralelo, o un puente vehicular
sin contraparte peatonal cercana), lo que puede fragmentar la conectividad
peatonal de forma distinta a la vehicular en zonas de topografía difícil
(selva/sierra de Cusco, donde se concentran estos 27 casos). Se documenta
como **limitación conocida y usable**: el tiempo peatonal reportado en esos
27 casos es aritméticamente correcto para el grafo peatonal tal como está
construido, pero compara facilities distintas y no debe leerse como "cuánto
tardaría alguien en llegar a pie a la misma posta que en auto". **No se
modifica el ruteo** — no se encontró un error real, solo una limitación
metodológica esperable de perfiles con reglas de accesibilidad distintas.

## Casos extremos de tiempo en auto (top 20)

Revisados uno por uno (`data/outputs/extreme_access_cases.csv`): se
concentran en distritos amazónicos/de selva alta de Cusco (Camanti,
Kosñipata, Echarate — Quispicanchi/Paucartambo/La Convención), con
distancias de red de 175–345 km y tiempos de 214–326 min (velocidad
promedio implícita ~55-75 km/h, coherente con una mezcla de vía asfaltada y
rural). No se observan artefactos evidentes (bucles, tiempos absurdos para
la distancia, snap fallido, etc.) — se mantienen sin modificar.
