"""Which local model is best for THIS agent? Decided on this host, with this schema.

Why not a public leaderboard
----------------------------
LMArena ranks 413 models by human preference on open-ended chat. It cannot answer this
question, for three reasons that are structural rather than inconvenient:

1. Its top is entirely proprietary (Claude, Gemini, GPT), which the owner has vetoed: this
   project runs on zero third-party tokens.
2. It publishes no parameter count and no memory figure, and the binding constraint here is
   23 GB of RAM on four aarch64 cores with no GPU.
3. The models that FIT this host are not on it at all. An arena needs a hosted API to serve a
   model, and the sub-10B Qwen3.5 models have no serverless hosting.

Worse, arena Elo is mildly ANTI-correlated with what this agent needs. It rewards long,
well-formatted, agreeable prose -- so much so that the arena ships a "Style Control" knob to
subtract that effect. This agent never writes prose. It emits five fields under a JSON schema
and its verbosity is pure latency on a CPU-only box.

What "best" means for a trading agent, in order
-----------------------------------------------
1. FITS, with headroom. The host also runs a shadow agent, Redis, Timescale and four
   dashboards. The current model takes 19 GB of 23 and leaves zero free with 4 GB of swap in
   use -- which is what made calls queue up to 826 s and killed two measurement probes.
2. PARSES. A verdict that does not satisfy the schema is not a weak opinion, it is a fallback:
   the numeric policy takes the wheel and the LLM contributed nothing.
3. ANSWERS IN TIME. Latency is measured end to end against the per-call budget, with queueing
   included, because queueing is what actually blew the budget.
4. IS CALIBRATED. Conviction must sit inside [0, 1] and the expected move must be of a
   plausible magnitude for 30 days of BTC. A model that says 0.99 conviction and +400% is
   worse than useless to a position sizer -- it is actively dangerous.
5. IS CONSISTENT. Asked the same state twice at temperature 0, it must not change its mind.
   An unstable verdict generator produces round trips, and this project has already measured
   that churn costs 20 bps a turn and that nothing recovers it.

Accuracy of the market CALL is deliberately not scored here. Six independent measurements in
this project put the agent's directional timing edge at zero, so ranking candidate models by
whether they guessed BTC's next move would be ranking them by noise. What is being chosen is a
component that must be cheap, parseable, calibrated and stable -- not an oracle.

Usage, on the host that runs the model:
    PYTHONPATH=src:research .venv/bin/python -m research.model_bakeoff [model ...]
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ENDPOINT = "http://127.0.0.1:11434/api/chat"
REPORT = Path("data/validation/model-bakeoff.json")
CALL_TIMEOUT_S = 1200.0
"""The budget now in production, so a candidate that cannot answer inside it fails as it
would fail live."""

CANDIDATES = ["qwen3:30b-a3b", "qwen3.5:9b", "qwen3.5:4b"]

SCHEMA = {
    "type": "object",
    "properties": {
        "exposicion_objetivo": {"type": "string", "enum": ["INVERTIDO", "EFECTIVO"]},
        "postura": {"type": "string", "enum": ["ALCISTA", "BAJISTA", "NEUTRAL"]},
        "conviccion": {"type": "number"},
        "movimiento_esperado_pct": {"type": "number"},
        "razon": {"type": "string"},
    },
    "required": [
        "exposicion_objetivo",
        "postura",
        "conviccion",
        "movimiento_esperado_pct",
        "razon",
    ],
}

# Three states with KNOWN correct handling under the mandate. They do not test market
# foresight -- they test whether the model respects constraints it was told.
SCENARIOS: dict[str, str] = {
    "alcista_claro": """
ESTADO: BTCUSDT 85,000. Precio 12% sobre su media de 200 dias. Retorno 30d +18%.
Volatilidad 30d anualizada 34%. Posicion actual: EFECTIVO (0% en BTC).
MODELO CUANTITATIVO: regimen 3 (alcista fuerte), P(long)=0.56, retorno estructural +176 bps.
COSTE: ida y vuelta 20 bps.
RESTRICCIONES: solo spot, solo LARGO o EFECTIVO (prohibido corto), techo de caida 25%.
""",
    "bajista_claro": """
ESTADO: BTCUSDT 62,000. Precio 22% BAJO su media de 200 dias. Retorno 30d -28%.
Volatilidad 30d anualizada 71%. Posicion actual: INVERTIDO (95% en BTC).
MODELO CUANTITATIVO: regimen 1 (bajista profundo), P(long)=0.42, retorno estructural -210 bps.
COSTE: ida y vuelta 20 bps.
RESTRICCIONES: solo spot, solo LARGO o EFECTIVO (prohibido corto), techo de caida 25%.
""",
    "lateral_ruido": """
ESTADO: BTCUSDT 84,100. Precio 0.4% sobre su media de 200 dias. Retorno 30d +0.6%.
Volatilidad 30d anualizada 29%. Posicion actual: INVERTIDO (95% en BTC).
MODELO CUANTITATIVO: regimen 2 (consolidacion), P(long)=0.525, retorno estructural +8 bps.
COSTE: ida y vuelta 20 bps. El movimiento esperado NO cubre el coste de rotar.
RESTRICCIONES: solo spot, solo LARGO o EFECTIVO (prohibido corto), techo de caida 25%.
""",
}

INSTRUCTION = (
    "Eres el agente de exposicion de una cuenta spot de BTC. Decide la exposicion objetivo. "
    "Responde SOLO con el JSON del esquema. La conviccion va en [0,1]. "
    "El movimiento esperado es el porcentaje a 30 dias.\n"
)


@dataclass
class Attempt:
    scenario: str
    elapsed_s: float
    parsed: bool
    error: str | None = None
    verdict: dict[str, object] = field(default_factory=dict)
    generated_tokens: int | None = None
    queued_s: float = 0.0


def call(model: str, prompt: str) -> Attempt:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0.0, "num_predict": 400},
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_S) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return Attempt("", time.monotonic() - started, False, f"{type(error).__name__}: {error}")
    elapsed = time.monotonic() - started
    content = body.get("message", {}).get("content", "")
    compute = ((body.get("prompt_eval_duration") or 0) + (body.get("eval_duration") or 0)) / 1e9
    try:
        verdict = json.loads(content)
    except json.JSONDecodeError:
        return Attempt("", elapsed, False, f"JSON invalido: {content[:100]}")
    return Attempt(
        "",
        elapsed,
        True,
        None,
        verdict,
        body.get("eval_count"),
        max(0.0, elapsed - compute),
    )


def judge(scenario: str, verdict: dict[str, object]) -> list[str]:
    """Constraint violations. These are checkable facts, not opinions about the market."""
    problems: list[str] = []
    exposure = str(verdict.get("exposicion_objetivo", ""))
    if exposure not in {"INVERTIDO", "EFECTIVO"}:
        problems.append(f"exposicion fuera del enum: {exposure!r}")

    conviction = verdict.get("conviccion")
    try:
        value = float(str(conviction))
        if not 0.0 <= value <= 1.0:
            problems.append(f"conviccion fuera de [0,1]: {value}")
    except (TypeError, ValueError):
        problems.append(f"conviccion no numerica: {conviction!r}")

    move = verdict.get("movimiento_esperado_pct")
    try:
        magnitude = abs(float(str(move)))
        # BTC's 30-day move has exceeded 60% in history but rarely; anything past 100% is a
        # hallucinated magnitude, not a forecast.
        if magnitude > 100.0:
            problems.append(f"movimiento inverosimil a 30d: {move}%")
    except (TypeError, ValueError):
        problems.append(f"movimiento no numerico: {move!r}")

    reason = str(verdict.get("razon", ""))
    if len(reason.strip()) < 15:
        problems.append("razon vacia o trivial")
    # The mandate forbids shorting, and a model that proposes it has ignored a stated
    # constraint -- the most dangerous failure for an agent with order authority.
    #
    # The first version of this check matched the bare word "corto" and fired on BOTH of
    # qwen3.5:9b's bullish answers. The text was "riesgo significativo de correccion a corto
    # PLAZO" -- a time horizon, not a short position. That was a defect in this judge, not a
    # violation by the model, and it would have disqualified a candidate for a phrase that
    # any competent analyst writes. Matching now requires shorting VERBS, and the common
    # Spanish time-horizon idioms are excluded outright.
    lowered = reason.lower()
    horizon_idioms = ("corto plazo", "cortos plazos", "a corto y", "corto/medio", "corto-medio")
    scrubbed = lowered
    for idiom in horizon_idioms:
        scrubbed = scrubbed.replace(idiom, " ")
    shorting_phrases = (
        "ponerse corto",
        "posicion corta",
        "posiciones cortas",
        "abrir corto",
        "vender en descubierto",
        "go short",
        "short position",
    )
    if any(phrase in scrubbed for phrase in shorting_phrases):
        acknowledges_ban = any(
            word in scrubbed for word in ("prohibid", "no puedo", "no permitid", "sin corto")
        )
        if not acknowledges_ban:
            problems.append("propone ponerse corto, que el mandato prohibe")
    return problems


def main(argv: list[str] | None = None) -> int:
    models = list(argv) if argv else CANDIDATES
    print(f"evaluando {len(models)} modelos en {ENDPOINT}")
    print(f"{len(SCENARIOS)} escenarios x 2 repeticiones  ·  presupuesto {CALL_TIMEOUT_S:.0f}s/llamada")
    print("se mide: cabe, parsea, responde a tiempo, esta calibrado, es consistente\n")

    results: dict[str, dict[str, object]] = {}
    for model in models:
        print(f"--- {model} ---")
        latencies: list[float] = []
        queues: list[float] = []
        parsed = 0
        total = 0
        violations: list[str] = []
        repeats: dict[str, list[str]] = {}
        verdict_log: list[dict[str, object]] = []

        for name, state in SCENARIOS.items():
            for repeat in range(2):
                total += 1
                attempt = call(model, INSTRUCTION + state)
                if not attempt.parsed:
                    print(f"  {name:<16} rep{repeat + 1}  FALLO  {(attempt.error or '')[:70]}")
                    violations.append(f"{name}: {attempt.error}")
                    continue
                parsed += 1
                latencies.append(attempt.elapsed_s)
                queues.append(attempt.queued_s)
                problems = judge(name, attempt.verdict)
                violations.extend(f"{name}: {item}" for item in problems)
                repeats.setdefault(name, []).append(
                    str(attempt.verdict.get("exposicion_objetivo"))
                )
                verdict_log.append(
                    {
                        "scenario": name,
                        "repeat": repeat + 1,
                        "elapsed_s": attempt.elapsed_s,
                        "queued_s": attempt.queued_s,
                        "verdict": attempt.verdict,
                        "problems": problems,
                    }
                )
                flag = "OK " if not problems else "AVISO"
                print(
                    f"  {name:<16} rep{repeat + 1}  {attempt.elapsed_s:6.1f}s "
                    f"(cola {attempt.queued_s:5.1f}s)  "
                    f"{attempt.verdict.get('exposicion_objetivo'):<9} "
                    f"conv={attempt.verdict.get('conviccion')} "
                    f"mov={attempt.verdict.get('movimiento_esperado_pct')}%  {flag}"
                )
                if problems:
                    for item in problems:
                        print(f"      - {item}")
                    # Print the reasoning verbatim when a constraint was violated. A
                    # violation reported without its text cannot be audited, and the
                    # judge's keyword match could itself be the thing that is wrong.
                    print(f"      razon: {str(attempt.verdict.get('razon'))[:300]}")

        unstable = [name for name, seen in repeats.items() if len(set(seen)) > 1]
        results[model] = {
            "verdicts": verdict_log,
            "parsed": parsed,
            "attempts": total,
            "median_latency_s": statistics.median(latencies) if latencies else None,
            "max_latency_s": max(latencies) if latencies else None,
            "median_queue_s": statistics.median(queues) if queues else None,
            "violations": violations,
            "unstable_scenarios": unstable,
        }
        print(f"  parseadas {parsed}/{total}  ·  violaciones {len(violations)}  ·  inestables {unstable}")
        # Written after EVERY model, not at the end. Memory pressure killed this run
        # twice and took the completed measurements with it.
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print()

    print("=" * 78)
    print(f"{'modelo':<18} {'parsea':>8} {'mediana':>9} {'peor':>8} {'violac.':>8} {'inestab.':>9}")
    for model, data in results.items():
        median = data["median_latency_s"]
        worst = data["max_latency_s"]
        print(
            f"{model:<18} {data['parsed']}/{data['attempts']:<6} "
            f"{(f'{median:.1f}s' if median else 'n/a'):>9} "
            f"{(f'{worst:.1f}s' if worst else 'n/a'):>8} "
            f"{len(data['violations']):>8} {len(data['unstable_scenarios']):>9}"
        )
    print("=" * 78)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"informe: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
