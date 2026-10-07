"""Diagnóstico del stop vivo del agente LLM a partir del log de actividad.

Lee ``data/live/llm-agent-activity.jsonl`` (JSON Lines, una decisión por línea)
y reporta:

1. Atribución de regla del stop (stop duro / break-even / trailing).
2. Distribución de la distancia del stop al precio (global y por regla).
3. Operaciones reales (idas y vueltas) con PnL bruto y neto.
4. Latencia de detección de salidas y de reentrada.
5. Tiempo entre operaciones consecutivas.

Todo lo calculado es aritmética directa sobre el log; cuando un dato falta en
el log se dice explícitamente y no se inventa.

Ejecutar con::

    PYTHONPATH=src:research .venv/bin/python -m research.live_stop_diagnosis
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

# ---------------------------------------------------------------------------
# Parámetros de las reglas del stop (fracciones, no porcentajes).
# ---------------------------------------------------------------------------
HARD_STOP_FRAC = Decimal("0.03")  # stop duro: entry * (1 - 0.03)
BREAK_EVEN_FRAC = Decimal("0.0025")  # bloqueo break-even: entry * (1 + 0.0025)
TRAILING_FRAC = Decimal("0.025")  # trailing: high * (1 - 0.025)
REL_TOL = Decimal("1e-6")  # tolerancia relativa de atribución

# Costes de transacción asumidos para el PnL neto.
FEE_BPS_PER_SIDE = Decimal("10")  # 10 bps por lado
BPS = Decimal("10000")

LOG_PATH = os.path.join("data", "live", "llm-agent-activity.jsonl")


# ---------------------------------------------------------------------------
# Utilidades de parseo.
# ---------------------------------------------------------------------------
def _dec(value: object) -> Decimal | None:
    """Convierte una cadena del log a Decimal, o None si no es convertible."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _dt(value: object) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _percentile(sorted_vals: list[Decimal], pct: float) -> Decimal | None:
    """Percentil por interpolación lineal; ``sorted_vals`` debe venir ordenado."""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (Decimal(str(pct)) / Decimal("100")) * Decimal(len(sorted_vals) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = rank - Decimal(lo)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def _fmt(value: Decimal | None, places: str = "0.0001") -> str:
    if value is None:
        return "n/a"
    return str(value.quantize(Decimal(places)))


# ---------------------------------------------------------------------------
# Modelo de datos.
# ---------------------------------------------------------------------------
@dataclass
class Decision:
    at: datetime | None
    price: Decimal | None
    entry_price: Decimal | None
    high_since_entry: Decimal | None
    active_stop_price: Decimal | None
    action: str | None
    position_before: str | None
    position_after: str | None
    order_status: str | None
    order_side: str | None
    order_avg_price: Decimal | None
    order_base_qty: Decimal | None
    fees_usdt: Decimal | None
    raw_at: str

    @classmethod
    def from_json(cls, obj: dict) -> Decision:
        return cls(
            at=_dt(obj.get("at")),
            price=_dec(obj.get("price")),
            entry_price=_dec(obj.get("entry_price")),
            high_since_entry=_dec(obj.get("high_since_entry")),
            active_stop_price=_dec(obj.get("active_stop_price")),
            action=obj.get("action"),
            position_before=obj.get("position_before"),
            position_after=obj.get("position_after"),
            order_status=obj.get("order_status"),
            order_side=obj.get("order_side"),
            order_avg_price=_dec(obj.get("order_avg_price")),
            order_base_qty=_dec(obj.get("order_base_qty")),
            fees_usdt=_dec(obj.get("fees_usdt")),
            raw_at=str(obj.get("at") or ""),
        )


@dataclass
class Fill:
    """Un relleno real (order_status == FILLED)."""

    at: datetime | None
    side: str
    avg_price: Decimal
    base_qty: Decimal
    fees_usdt: Decimal | None
    position_before: str | None
    position_after: str | None
    price: Decimal | None


@dataclass
class RoundTrip:
    buy: Fill
    sell: Fill
    gross_usdt: Decimal
    gross_pct: Decimal
    net_usdt: Decimal
    net_pct: Decimal
    hold_hours: Decimal | None


# ---------------------------------------------------------------------------
# Carga.
# ---------------------------------------------------------------------------
def load_decisions(path: str) -> list[Decision]:
    out: list[Decision] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.append(Decision.from_json(obj))
    return out


# ---------------------------------------------------------------------------
# 1. Atribución de regla.
# ---------------------------------------------------------------------------
RULE_LABELS = ("hard_stop", "break_even", "trailing", "unattributed")


def attribute_rule(d: Decision) -> str | None:
    """Devuelve la regla que explica active_stop_price, o None si falta dato."""
    if d.entry_price is None or d.active_stop_price is None or d.entry_price == 0:
        return None
    stop = d.active_stop_price
    candidates: list[tuple[str, Decimal]] = [
        ("hard_stop", d.entry_price * (Decimal("1") - HARD_STOP_FRAC)),
        ("break_even", d.entry_price * (Decimal("1") + BREAK_EVEN_FRAC)),
    ]
    if d.high_since_entry is not None:
        candidates.append(
            ("trailing", d.high_since_entry * (Decimal("1") - TRAILING_FRAC))
        )
    best_label = "unattributed"
    for label, cand in candidates:
        if cand == 0:
            continue
        rel = abs(stop - cand) / abs(cand)
        if rel <= REL_TOL:
            best_label = label
            break
    return best_label


def analyze_rules(decisions: list[Decision]) -> dict:
    counts = {k: 0 for k in RULE_LABELS}
    attributed: list[tuple[str, Decimal]] = []  # (regla, distancia relativa)
    considered = 0
    for d in decisions:
        rule = attribute_rule(d)
        if rule is None:
            continue
        considered += 1
        counts[rule] += 1
        if d.price is not None and d.price != 0 and d.active_stop_price is not None:
            dist = (d.price - d.active_stop_price) / d.price
            attributed.append((rule, dist))
    return {"counts": counts, "considered": considered, "distances": attributed}


# ---------------------------------------------------------------------------
# 2. Distancia del stop.
# ---------------------------------------------------------------------------
def analyze_distance(decisions: list[Decision], attributed: list[tuple[str, Decimal]]) -> dict:
    dists: list[Decimal] = []
    for d in decisions:
        if (
            d.active_stop_price is not None
            and d.price is not None
            and d.price != 0
        ):
            dists.append((d.price - d.active_stop_price) / d.price)
    dists_sorted = sorted(dists)
    n = len(dists)
    under_half = sum(1 for x in dists if x < Decimal("0.005"))
    under_one = sum(1 for x in dists if x < Decimal("0.01"))
    pct_points = {p: _percentile(dists_sorted, p) for p in (1, 5, 25, 50, 75)}

    # Por regla
    by_rule: dict[str, dict] = {}
    for label in ("hard_stop", "break_even", "trailing", "unattributed"):
        vals = sorted(x for (r, x) in attributed if r == label)
        if not vals:
            by_rule[label] = {"n": 0}
            continue
        by_rule[label] = {
            "n": len(vals),
            "p50": _percentile(vals, 50),
            "p5": _percentile(vals, 5),
            "p95": _percentile(vals, 95),
            "min": vals[0],
            "max": vals[-1],
        }
    return {
        "n": n,
        "percentiles": pct_points,
        "under_half_pct": under_half,
        "under_one_pct": under_one,
        "by_rule": by_rule,
    }


# ---------------------------------------------------------------------------
# 3. Operaciones reales + PnL.
# ---------------------------------------------------------------------------
def extract_fills(decisions: list[Decision]) -> list[Fill]:
    fills: list[Fill] = []
    for d in decisions:
        if (
            d.order_status == "FILLED"
            and d.order_side in ("BUY", "SELL")
            and d.order_avg_price is not None
            and d.order_base_qty is not None
        ):
            fills.append(
                Fill(
                    at=d.at,
                    side=d.order_side,
                    avg_price=d.order_avg_price,
                    base_qty=d.order_base_qty,
                    fees_usdt=d.fees_usdt,
                    position_before=d.position_before,
                    position_after=d.position_after,
                    price=d.price,
                )
            )
    return fills


def build_round_trips(fills: list[Fill]) -> list[RoundTrip]:
    """Empareja un BUY con el siguiente SELL (ida y vuelta FIFO simple)."""
    trips: list[RoundTrip] = []
    open_buy: Fill | None = None
    for f in fills:
        if f.side == "BUY":
            open_buy = f
        elif f.side == "SELL" and open_buy is not None:
            buy = open_buy
            qty = min(buy.base_qty, f.base_qty)
            if qty <= 0:
                open_buy = None
                continue
            gross = (f.avg_price - buy.avg_price) * qty
            cost_basis = buy.avg_price * qty
            gross_pct = (gross / cost_basis) * Decimal("100") if cost_basis else Decimal("0")
            # Fees: 10 bps por lado sobre el nocional de cada pata.
            notional_buy = buy.avg_price * qty
            notional_sell = f.avg_price * qty
            fee = (notional_buy + notional_sell) * (FEE_BPS_PER_SIDE / BPS)
            net = gross - fee
            net_pct = (net / cost_basis) * Decimal("100") if cost_basis else Decimal("0")
            hold = None
            if buy.at and f.at:
                hold = Decimal((f.at - buy.at).total_seconds()) / Decimal("3600")
            trips.append(
                RoundTrip(
                    buy=buy,
                    sell=f,
                    gross_usdt=gross,
                    gross_pct=gross_pct,
                    net_usdt=net,
                    net_pct=net_pct,
                    hold_hours=hold,
                )
            )
            open_buy = None
    return trips


# ---------------------------------------------------------------------------
# 4 & 5. Latencia de detección y tiempo entre operaciones.
# ---------------------------------------------------------------------------
def analyze_latency(decisions: list[Decision]) -> dict:
    """Latencia de detección de salida y tiempo salida->reentrada.

    - Detección: entre la última decisión que mostraba LONG (position_before o
      position_after == LONG justo antes del cambio) y la primera que muestra
      position_after != LONG.
    - Reentrada: entre una salida (position_after != LONG viniendo de LONG) y la
      siguiente entrada (position_after == LONG viniendo de != LONG).
    """
    detection_gaps: list[Decimal] = []
    reentry_gaps: list[Decimal] = []
    last_long_time: datetime | None = None
    last_exit_time: datetime | None = None

    for d in decisions:
        after = d.position_after
        before = d.position_before
        if after == "LONG":
            last_long_time = d.at
        # Transición de LONG a no-LONG = salida detectada
        if before == "LONG" and after is not None and after != "LONG":
            if last_long_time and d.at:
                gap = Decimal((d.at - last_long_time).total_seconds()) / Decimal("3600")
                if gap >= 0:
                    detection_gaps.append(gap)
            last_exit_time = d.at
        # Transición a LONG viniendo de no-LONG = reentrada
        if before is not None and before != "LONG" and after == "LONG" and last_exit_time and d.at:
            gap = Decimal((d.at - last_exit_time).total_seconds()) / Decimal("3600")
            if gap >= 0:
                reentry_gaps.append(gap)
            last_exit_time = None

    return {"detection_gaps": detection_gaps, "reentry_gaps": reentry_gaps}


def analyze_spacing(fills: list[Fill]) -> dict:
    times = [f.at for f in fills if f.at is not None]
    gaps: list[Decimal] = []
    for i in range(1, len(times)):
        delta = Decimal((times[i] - times[i - 1]).total_seconds()) / Decimal("3600")
        gaps.append(delta)
    gaps_sorted = sorted(gaps)
    return {
        "n": len(gaps),
        "median": _percentile(gaps_sorted, 50),
        "max": gaps_sorted[-1] if gaps_sorted else None,
    }


# ---------------------------------------------------------------------------
# Informe.
# ---------------------------------------------------------------------------
def _stats(vals: list[Decimal]) -> dict:
    if not vals:
        return {"n": 0}
    s = sorted(vals)
    return {
        "n": len(s),
        "median": _percentile(s, 50),
        "min": s[0],
        "max": s[-1],
    }


def report(path: str = LOG_PATH) -> None:
    if not os.path.exists(path):
        print(f"ERROR: no existe el log en {path}")
        return

    decisions = load_decisions(path)
    n = len(decisions)
    valid_times = [d.at for d in decisions if d.at is not None]
    t0 = min(valid_times) if valid_times else None
    t1 = max(valid_times) if valid_times else None

    print("=" * 72)
    print("DIAGNÓSTICO DEL STOP VIVO — llm-agent-activity.jsonl")
    print("=" * 72)
    print(f"Decisiones leídas : {n}")
    print(f"Rango temporal    : {t0} -> {t1}")
    if t0 and t1:
        span_h = (t1 - t0).total_seconds() / 3600
        print(f"Cobertura         : {span_h:.1f} h ({span_h / 24:.1f} días)")
    print("Rotación          : fichero único, sin .1/.gz detectados en data/live/")
    print()

    # --- 1. Atribución de regla ---
    rules = analyze_rules(decisions)
    considered = rules["considered"]
    print("-" * 72)
    print("1. ATRIBUCIÓN DE REGLA DEL STOP")
    print("-" * 72)
    print(f"Decisiones con entry_price y active_stop_price: {considered}")
    print(f"{'Regla':<16}{'N':>10}{'% del total':>16}")
    for label in RULE_LABELS:
        c = rules["counts"][label]
        pct = (Decimal(c) / Decimal(considered) * 100) if considered else Decimal("0")
        print(f"{label:<16}{c:>10}{_fmt(pct, '0.01') + ' %':>16}")
    print()

    # --- 2. Distancia del stop ---
    dist = analyze_distance(decisions, rules["distances"])
    print("-" * 72)
    print("2. DISTANCIA DEL STOP  (price - stop) / price")
    print("-" * 72)
    print(f"Decisiones con stop y price: {dist['n']}")
    print("Percentiles (fracción del precio):")
    for p in (1, 5, 25, 50, 75):
        v = dist["percentiles"][p]
        pctv = (v * 100) if v is not None else None
        print(f"  p{p:<3}: {_fmt(v, '0.000001')}  ({_fmt(pctv, '0.0001')} %)")
    print(f"Stop a < 0.5% del precio : {dist['under_half_pct']} decisiones")
    print(f"Stop a < 1.0% del precio : {dist['under_one_pct']} decisiones")
    print()
    print("Distancia por regla atribuida (fracción del precio):")
    print(f"{'Regla':<16}{'N':>8}{'p5':>12}{'p50':>12}{'p95':>12}{'min':>12}{'max':>12}")
    for label in ("hard_stop", "break_even", "trailing", "unattributed"):
        r = dist["by_rule"][label]
        if r.get("n", 0) == 0:
            print(f"{label:<16}{0:>8}{'—':>12}{'—':>12}{'—':>12}{'—':>12}{'—':>12}")
            continue
        print(
            f"{label:<16}{r['n']:>8}"
            f"{_fmt(r['p5'], '0.000001'):>12}"
            f"{_fmt(r['p50'], '0.000001'):>12}"
            f"{_fmt(r['p95'], '0.000001'):>12}"
            f"{_fmt(r['min'], '0.000001'):>12}"
            f"{_fmt(r['max'], '0.000001'):>12}"
        )
    print()

    # --- 3. Operaciones reales ---
    fills = extract_fills(decisions)
    trips = build_round_trips(fills)
    print("-" * 72)
    print("3. OPERACIONES REALES (order_status == FILLED)")
    print("-" * 72)
    print(f"Rellenos (fills) totales: {len(fills)}")
    print(f"{'Fecha':<26}{'lado':>6}{'avg_price':>16}{'base_qty':>14}{'pos':>14}")
    for f in fills:
        pos = f"{f.position_before}->{f.position_after}"
        print(
            f"{f.at!s:<26}{f.side:>6}{_fmt(f.avg_price, '0.01'):>16}"
            f"{_fmt(f.base_qty, '0.00000001'):>14}{pos:>14}"
        )
    print()
    print(f"Idas y vueltas (BUY->SELL) emparejadas: {len(trips)}")
    print(
        f"{'#':>3}{'entrada':<22}{'salida':<22}{'horas':>8}"
        f"{'bruto$':>12}{'bruto%':>9}{'neto$':>12}{'neto%':>9}"
    )
    cum_gross = Decimal("0")
    cum_net = Decimal("0")
    wins_gross = 0
    losses_gross = 0
    wins_net = 0
    losses_net = 0
    for i, t in enumerate(trips, 1):
        cum_gross += t.gross_usdt
        cum_net += t.net_usdt
        if t.gross_usdt > 0:
            wins_gross += 1
        elif t.gross_usdt < 0:
            losses_gross += 1
        if t.net_usdt > 0:
            wins_net += 1
        elif t.net_usdt < 0:
            losses_net += 1
        print(
            f"{i:>3}{t.buy.at!s:<22}{t.sell.at!s:<22}"
            f"{_fmt(t.hold_hours, '0.01'):>8}"
            f"{_fmt(t.gross_usdt, '0.01'):>12}{_fmt(t.gross_pct, '0.01'):>9}"
            f"{_fmt(t.net_usdt, '0.01'):>12}{_fmt(t.net_pct, '0.01'):>9}"
        )
    print()
    print(f"PnL BRUTO acumulado : {_fmt(cum_gross, '0.01')} USDT")
    print(f"PnL NETO  acumulado : {_fmt(cum_net, '0.01')} USDT  (10 bps/lado)")
    print(f"Idas y vueltas ganadoras (bruto): {wins_gross}  perdedoras: {losses_gross}")
    print(f"Idas y vueltas ganadoras (neto) : {wins_net}  perdedoras: {losses_net}")
    print()

    # --- 4. Latencia de detección ---
    lat = analyze_latency(decisions)
    det = _stats(lat["detection_gaps"])
    ree = _stats(lat["reentry_gaps"])
    print("-" * 72)
    print("4. LATENCIA DE DETECCIÓN (horas)")
    print("-" * 72)
    print(
        f"Salidas detectadas (LONG->no-LONG): n={det['n']}"
        + (
            f"  mediana={_fmt(det['median'], '0.0001')}  "
            f"min={_fmt(det['min'], '0.0001')}  max={_fmt(det['max'], '0.0001')}"
            if det["n"]
            else ""
        )
    )
    print(
        f"Salida -> reentrada: n={ree['n']}"
        + (
            f"  mediana={_fmt(ree['median'], '0.0001')}  "
            f"min={_fmt(ree['min'], '0.0001')}  max={_fmt(ree['max'], '0.0001')}"
            if ree["n"]
            else ""
        )
    )
    print()

    # --- 5. Tiempo entre operaciones ---
    spc = analyze_spacing(fills)
    print("-" * 72)
    print("5. TIEMPO ENTRE OPERACIONES (horas, entre fills consecutivos)")
    print("-" * 72)
    print(
        f"Intervalos: n={spc['n']}  "
        f"mediana={_fmt(spc['median'], '0.01')}  max={_fmt(spc['max'], '0.01')}"
    )
    print("=" * 72)


if __name__ == "__main__":
    report()
