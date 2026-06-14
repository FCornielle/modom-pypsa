"""Factores de nodo (pérdidas) re-estimados desde la solución AC.

Es la variable de realimentación del lazo iterativo DC↔AC, igual que GAMS↔PowerFactory:
PowerFactory (la AC) mide las pérdidas reales del punto de operación y de ahí salen los
factores que GAMS (el despacho) consume. Aquí:

- `system_loss_fraction(net)` — pérdidas / demanda del flujo AC resuelto.
- `update_loss_factors(prev, net, ctx, base_load_h, damping)` — re-estima el factor de
  retiro por barra MODOM (W) de modo que el uplift del despacho DC iguale las pérdidas
  AC, **preservando la forma espacial** de los factores previos (semilla = factores
  nodales del MODOM). Si no hay forma previa, usa la distancia eléctrica (|Δθ| al slack)
  del propio flujo AC como proxy de pérdidas marginales; en último caso, uplift uniforme.

El Jacobiano del flujo (`net._ppc["internal"]["J"]`) queda disponible para una futura
estimación ITL (incremental transmission loss) más fina; este v1 prioriza robustez y
convergencia del lazo.
"""
from __future__ import annotations

import math

import pandas as pd


def system_loss_fraction(net) -> float:
    """Pérdidas activas / demanda servida del flujo AC (fracción, p.ej. 0.03)."""
    load = float(net.res_load.p_mw[net.load.in_service].sum()) if len(net.load) else 0.0
    if load <= 1e-6:
        return 0.0
    losses = float(net.res_line.pl_mw.sum() + net.res_trafo.pl_mw.sum())
    return max(losses, 0.0) / load


def _angle_distance_weights(net, ctx) -> dict[str, float]:
    """Proxy de pérdidas marginales: |ángulo - ángulo del slack| por barra MODOM (W)."""
    fb = ctx["for_by_bus"]
    if not len(net.ext_grid):
        return {}
    slack_bus = int(net.ext_grid.bus.iloc[0])
    va0 = float(net.res_bus.at[slack_bus, "va_degree"]) if slack_bus in net.res_bus.index else 0.0
    w: dict[str, float] = {}
    for b, fn in fb.items():
        if b in net.res_bus.index and net.bus.at[b, "in_service"]:
            va = net.res_bus.at[b, "va_degree"]
            if va == va:
                w[fn] = abs(float(va) - va0)
    return w


def update_loss_factors(prev, net, ctx, base_load_h, damping: float = 0.5) -> pd.Series:
    """Re-estima factores de retiro por W desde la AC.

    `prev`: Series W->factor del paso anterior (semilla = factores MODOM). `base_load_h`:
    Series W->MW de demanda base (sin factor) de la hora. Devuelve Series W->factor.
    """
    prev = pd.Series(prev, dtype=float) if prev is not None else pd.Series(dtype=float)
    base = pd.Series(base_load_h, dtype=float)
    l_ac = system_loss_fraction(net) * float(base.sum())  # MW de pérdidas objetivo

    # 1) forma espacial: exceso previo (factor-1); si no hay, distancia angular AC
    shape = (prev.reindex(base.index) - 1.0).clip(lower=0.0)
    if not (shape.fillna(0.0) > 1e-9).any():
        aw = _angle_distance_weights(net, ctx)
        shape = pd.Series({w: aw.get(w, 0.0) for w in base.index}, dtype=float)
    shape = shape.fillna(0.0)

    # 2) escalar la forma para que Σ shape_i · load_i = pérdidas AC
    denom = float((shape * base.reindex(shape.index).fillna(0.0)).sum())
    if denom > 1e-6 and l_ac > 1e-6:
        excess = shape * (l_ac / denom)
    else:  # sin forma utilizable -> uplift uniforme
        frac = system_loss_fraction(net)
        excess = pd.Series(frac, index=base.index, dtype=float)
    target = 1.0 + excess

    # 3) amortiguar hacia el objetivo para estabilidad del lazo
    if prev.empty:
        new = target
    else:
        p = prev.reindex(target.index).fillna(1.0)
        new = p + damping * (target - p)
    return new.clip(lower=1.0)


def factor_delta(prev, new) -> float:
    """Máximo cambio absoluto entre dos vectores de factores (criterio de convergencia)."""
    if prev is None:
        return math.inf
    p = pd.Series(prev, dtype=float)
    n = pd.Series(new, dtype=float)
    common = p.index.intersection(n.index)
    if not len(common):
        return math.inf
    return float((n[common] - p[common]).abs().max())
