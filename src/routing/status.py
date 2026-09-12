"""Estados de routing explícitos (corrección de auditoría, 2026-09-11).

`reachable=True/False` por sí solo no distingue 4 situaciones reales y
metodológicamente distintas:

- el punto nunca se pudo ubicar en la red (`snap_failed`);
- se ubicó, pero dentro de su propio departamento no hay ruta hasta ninguna
  facility resolutiva (`no_route_same_department` — incluye tanto "nodo sin
  aristas transitables para el perfil" como "conectado pero sin resolutiva en
  su componente", ver `docs/01_routing_decision.md` §5 para el desglose fino);
- el par pertenece a departamentos distintos y la arquitectura de grafos
  separados por departamento nunca evaluó si existiría ruta
  (`cross_department_not_evaluated` — la auditoría demostró que esto NO
  cambia el nearest resolutive de ningún demand point, ver docs);
- se encontró una ruta real (`routed`).

Este módulo centraliza esa clasificación para que las salidas a nivel
"demanda" y a nivel "matriz completa" usen exactamente el mismo vocabulario.
"""

from __future__ import annotations

ROUTED = "routed"
SNAP_FAILED = "snap_failed"
NO_ROUTE_SAME_DEPT = "no_route_same_department"
CROSS_DEPT_NOT_EVALUATED = "cross_department_not_evaluated"

ALL_STATUSES = (ROUTED, SNAP_FAILED, NO_ROUTE_SAME_DEPT, CROSS_DEPT_NOT_EVALUATED)
# Estados válidos para una fila de la matriz completa (par origen-destino).
PAIR_STATUSES = ALL_STATUSES
# Estados válidos para el resumen por demand point (ya no depende de una
# facility en particular): cross-department no aplica a nivel "demanda" — un
# demand point está `routed` si alcanza AL MENOS una resolutiva de su propio
# departamento; nunca se evalúa contra otro departamento porque los grafos
# están separados (ver auditoría).
DEMAND_LEVEL_STATUSES = (ROUTED, SNAP_FAILED, NO_ROUTE_SAME_DEPT)


def classify_pair(*, snap_ok: bool, same_department: bool, reachable: bool) -> str:
    """Clasifica un par (demand, facility) para un modo dado.

    `snap_ok`: el demand point (o la facility) se pudo snapear (ambos deben
    poder, pero en este proyecto las 40 resolutivas snapean 100%, así que en
    la práctica esto refleja el snap del demand point).
    `same_department`: mismo departamento declarado que la facility.
    `reachable`: hubo un camino en el grafo (solo tiene sentido evaluarlo si
    `snap_ok and same_department`; si no, se ignora).
    """
    if not snap_ok:
        return SNAP_FAILED
    if not same_department:
        return CROSS_DEPT_NOT_EVALUATED
    return ROUTED if reachable else NO_ROUTE_SAME_DEPT


def classify_demand(*, snap_ok: bool, reachable_same_dept: bool) -> str:
    """Clasifica un demand point (por modo), independiente de una facility
    concreta: ¿llegó a razonar sobre la red? ¿alcanzó alguna resolutiva de su
    propio departamento?"""
    if not snap_ok:
        return SNAP_FAILED
    return ROUTED if reachable_same_dept else NO_ROUTE_SAME_DEPT
