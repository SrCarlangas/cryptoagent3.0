"""Measure regime DETECTION quality on real Binance data. No money, no strategies.

Detection speed and false-alarm rate are measurable on their own, so they are measured
first and separately. If the detector cannot find a regime change at an acceptable lag,
no playbook built on top of it can work, and that is worth knowing before writing one.

Thresholds are swept on the TRAINING segment only and the chosen set is then reported on
the VALIDATION segment, per `REGIME-STUDY-PREREGISTRATION.md` section 5. The test segment
(2025-04-01 onward) is not touched here.

Selection objective, declared BEFORE running it so it cannot be reverse-engineered from
the winner: among candidates with oracle coverage >= 0.80, minimise

    median_lag_days + 20 * false_alarm_rate

The weight of 20 says one false alarm per transition is as costly as 20 days of lag. It is
a judgement, stated in the open, not a tuned quantity.

Usage:
    PYTHONPATH=src:research .venv/bin/python -m research.measure_regime_detection
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from multislot_sim import load_bars
from regime_taxonomy import (
    REGIMES,
    DailyBar,
    RegimeParams,
    detect_regimes,
    oracle_regimes,
    regime_shares,
    score_detection,
)

TRAIN_END = "2023-06-30"
VALIDATION_END = "2025-03-31"
COVERAGE_FLOOR = 0.70
FALSE_ALARM_CEILING = 0.35
TRANSITION_BUDGET_MULTIPLE = 3.0
REPORT = Path("data/validation/regime-detection.json")


def split(daily: list[DailyBar]) -> tuple[list[DailyBar], list[DailyBar], list[DailyBar]]:
    """Train / validation / test, by date. The test segment is returned but not scored."""
    train = [bar for bar in daily if bar.date <= TRAIN_END]
    validation = [bar for bar in daily if TRAIN_END < bar.date <= VALIDATION_END]
    test = [bar for bar in daily if bar.date > VALIDATION_END]
    return train, validation, test


def evaluate(daily: list[DailyBar], params: RegimeParams) -> dict[str, Any]:
    """Detection quality plus the regime mix, for one parameter set on one segment."""
    detector = detect_regimes(daily, params)
    oracle = oracle_regimes(daily, params)
    quality = score_detection(detector, oracle)
    return {
        "quality": asdict(quality),
        "summary": quality.summary(),
        "detector_shares": regime_shares(detector),
        "oracle_shares": regime_shares(oracle),
        "labelled_days": sum(1 for item in detector if item is not None),
    }


def objective(quality: dict[str, Any]) -> float | None:
    """Median detection lag among candidates that clear every hard constraint.

    REVISED AFTER THE FIRST RUN, and the reason is recorded because this study's own rule
    is that choices made after seeing a result get declared. The original objective was
    `median_lag + 20 * false_alarm_rate`, a weighted scalar. The sweep immediately found
    its degenerate optimum: a 7-day window flipping 366 times in 1269 days scored a
    *negative* lag of -26.5 days with a 96% false-alarm rate and won. A detector that
    changes label every three days "anticipates" every transition by coincidence, and a
    weighted sum happily pays 20 points of false alarms for 26 points of fake lead.

    The fix is not a reweighting -- it removes the ways the metric could be gamed:

    - A negative median lag is rejected outright. The oracle is acausal; a causal detector
      cannot legitimately lead it, so a lead is evidence of noise matching noise.
    - The false-alarm rate is a hard ceiling, not a priced term.
    - The transition count is capped against the ORACLE's own count. The oracle changes
      regime about 14 times in 1269 days; a detector allowed unlimited transitions is not
      measuring the same thing.

    Among survivors the objective is simply the lag, which is what was asked for.
    """
    coverage = quality["coverage"]
    lag = quality["median_lag_days"]
    rate = quality["false_alarm_rate"]
    oracle_count = quality["oracle_transitions"]
    found = quality["detector_transitions"]
    if coverage is None or lag is None or rate is None or not oracle_count:
        return None
    if coverage < COVERAGE_FLOOR or rate > FALSE_ALARM_CEILING or lag < 0:
        return None
    if found > TRANSITION_BUDGET_MULTIPLE * oracle_count:
        return None
    return float(lag)


def sweep(train: list[DailyBar]) -> list[dict[str, Any]]:
    """Grid scored on TRAINING only.

    The LOOKBACK WINDOW is swept here and that is the point. The first pass of this study
    swept only the thresholds and got a median lag of exactly 15.0 days in all twelve
    eligible cells -- an identical number across variants that should have differed, which
    in this project is evidence rather than reassurance. The cause was structural: lag is
    governed by the window length (roughly window/2, since that is when half the lookback
    consists of the new regime) and is almost independent of the thresholds. Sweeping
    thresholds alone was sweeping the wrong axis.
    """
    rows: list[dict[str, Any]] = []
    for window in (7, 10, 14, 21, 30, 45, 60):
        for efficiency in (0.25, 0.35, 0.45):
            for persistence in (1, 3, 5, 8):
                params = RegimeParams(
                    efficiency_window=window,
                    volatility_window=window,
                    efficiency_threshold=efficiency,
                    persistence_days=persistence,
                )
                result = evaluate(train, params)
                rows.append(
                    {
                        "params": asdict(params),
                        "label": f"win={window:>2} er={efficiency:.2f} k={persistence}",
                        "objective": objective(result["quality"]),
                        **result,
                    }
                )
    return rows


def main() -> int:
    bars, dataset_id = load_bars()
    from regime_taxonomy import to_daily

    daily = to_daily(bars)
    train, validation, test = split(daily)

    print(f"dataset {dataset_id}")
    print(
        f"dias completos {len(daily)}  "
        f"train {len(train)} ({train[0].date}..{train[-1].date})  "
        f"validacion {len(validation)}  prueba {len(test)} (SIN TOCAR)"
    )

    default = evaluate(train, RegimeParams())
    print(f"\n--- parametros por defecto, TRAIN ---\n{default['summary']}")
    print("  reparto detector: " + " ".join(
        f"{name[:4]} {default['detector_shares'][name]:.0%}" for name in REGIMES
    ))
    print("  reparto oraculo : " + " ".join(
        f"{name[:4]} {default['oracle_shares'][name]:.0%}" for name in REGIMES
    ))

    rows = sweep(train)
    eligible = [row for row in rows if row["objective"] is not None]
    eligible.sort(key=lambda row: row["objective"])

    oracle_transitions = rows[0]["quality"]["oracle_transitions"]
    print(
        f"\n--- barrido en TRAIN: {len(eligible)} de {len(rows)} pasan las restricciones duras\n"
        f"    (cobertura >= {COVERAGE_FLOOR:.0%}, falsas <= {FALSE_ALARM_CEILING:.0%}, "
        f"retardo >= 0, transiciones <= {TRANSITION_BUDGET_MULTIPLE:.0f}x las {oracle_transitions} del oraculo) ---"
    )
    print(f"{'config':<26} {'retardo':>8} {'falsas':>7} {'cobert':>7} {'trans':>6}")
    for row in eligible[:12]:
        quality = row["quality"]
        print(
            f"{row['label']:<26} {quality['median_lag_days']:>7.1f}d "
            f"{quality['false_alarm_rate']:>6.0%} "
            f"{quality['coverage']:>6.0%} {quality['detector_transitions']:>6}"
        )

    print("\n--- frontera del compromiso: el retardo mas bajo alcanzable a cada techo de falsas alarmas ---")
    print(f"{'techo falsas':>13} {'mejor retardo':>14} {'config':<26} {'trans':>6}")
    for ceiling in (0.10, 0.20, 0.30, 0.40, 0.50):
        viable = [
            row for row in rows
            if row["quality"]["median_lag_days"] is not None
            and row["quality"]["false_alarm_rate"] is not None
            and row["quality"]["coverage"] is not None
            and row["quality"]["median_lag_days"] >= 0
            and row["quality"]["false_alarm_rate"] <= ceiling
            and row["quality"]["coverage"] >= COVERAGE_FLOOR
            and row["quality"]["detector_transitions"]
            <= TRANSITION_BUDGET_MULTIPLE * row["quality"]["oracle_transitions"]
        ]
        if not viable:
            print(f"{ceiling:>12.0%} {'ninguna':>14}")
            continue
        best_at = min(viable, key=lambda row: row["quality"]["median_lag_days"])
        print(
            f"{ceiling:>12.0%} {best_at['quality']['median_lag_days']:>13.1f}d "
            f"{best_at['label']:<26} {best_at['quality']['detector_transitions']:>6}"
        )

    if not eligible:
        print("\nNINGUNA configuracion alcanza la cobertura minima. El detector no sirve.")
        return 1

    best = eligible[0]
    chosen = RegimeParams(**best["params"])
    print(f"\n--- elegido en TRAIN: {best['label']} ---")

    held = evaluate(validation, chosen)
    print(f"--- ese mismo, congelado, en VALIDACION ---\n{held['summary']}")
    print("  reparto detector: " + " ".join(
        f"{name[:4]} {held['detector_shares'][name]:.0%}" for name in REGIMES
    ))

    held_quality = held["quality"]
    breaches: list[str] = []
    if held_quality["coverage"] is None or held_quality["coverage"] < COVERAGE_FLOOR:
        breaches.append(f"cobertura {held_quality['coverage']:.0%} < {COVERAGE_FLOOR:.0%}")
    if held_quality["false_alarm_rate"] > FALSE_ALARM_CEILING:
        breaches.append(
            f"falsas alarmas {held_quality['false_alarm_rate']:.0%} > {FALSE_ALARM_CEILING:.0%}"
        )
    if held_quality["median_lag_days"] < 0:
        breaches.append("retardo negativo (empareja ruido con ruido)")
    budget = TRANSITION_BUDGET_MULTIPLE * held_quality["oracle_transitions"]
    if held_quality["detector_transitions"] > budget:
        breaches.append(
            f"{held_quality['detector_transitions']} transiciones > {budget:.0f} permitidas"
        )
    print(
        f"\nretardo train {best['objective']:.1f}d -> validacion "
        f"{held_quality['median_lag_days']:.1f}d"
    )
    print(
        "VEREDICTO en validacion: "
        + ("pasa todas las restricciones" if not breaches else "FALLA -> " + "; ".join(breaches))
    )
    print(
        "\nreparto BAJISTA (detector/oraculo) en train: "
        f"{default['detector_shares']['BAJISTA']:.0%} / {default['oracle_shares']['BAJISTA']:.0%}"
        "  <- si es ~0%, la taxonomia no aisla el bajista"
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "dataset_id": dataset_id,
                "coverage_floor": COVERAGE_FLOOR,
                "false_alarm_ceiling": FALSE_ALARM_CEILING,
                "transition_budget_multiple": TRANSITION_BUDGET_MULTIPLE,
                "segments": {
                    "train": [train[0].date, train[-1].date],
                    "validation": [validation[0].date, validation[-1].date],
                    "test_untouched": [test[0].date, test[-1].date],
                },
                "default_on_train": default,
                "sweep": rows,
                "chosen": {"label": best["label"], "params": best["params"]},
                "chosen_on_validation": held,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print(f"\ninforme: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
