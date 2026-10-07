"""How long does one real deliberation take on THIS host? Measured, not assumed.

The live agent fell back to its numeric policy for about 21 hours. The cause was recorded in
its own journal as `modelo inalcanzable: TimeoutError('timed out')` -- twelve deliberations
exceeded the 600 s client timeout. So the mis-sized parameter is the TIMEOUT, not the
cadence: the cadence is already 30 minutes, which is longer than the timeout it never reached.

A timeout can only be sized from the latency it has to accommodate, and that latency is a
property of this box: aarch64, no GPU, a 30B mixture-of-experts model paged against 23 GB of
RAM. So this measures the real thing -- same endpoint, same model, same structured-output
schema, a prompt of representative size -- and reports the distribution rather than one
sample, because a timeout set to the mean fails half the time.

Run it ON the server, where the model is:
    PYTHONPATH=src:research .venv/bin/python -m research.llm_latency_probe [repeats]
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:30b-a3b"
REPORT = Path("data/validation/llm-latency-probe.json")
PROBE_TIMEOUT_S = 1800.0
"""Deliberately far above the production timeout: the point is to observe how long the model
actually takes, which a short timeout would hide behind the very error being diagnosed."""

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

# Representative of what the agent actually hands the model: market state, cost, the quant
# model's view and historical analogues. Padded to a realistic token count so the measured
# latency includes prompt processing, which on a CPU-only host dominates.
STATE_BLOCK = """
ESTADO DE MERCADO
  precio BTCUSDT: 83,556.92
  cambio 24h: -1.54%  ·  cambio 7d: -1.03%
  volatilidad 30d anualizada: 38.4%
  precio vs media 200d: +4.2%
  posicion actual: INVERTIDO (95% del capital)
  entrada: 84,862.83  ·  maximo desde entrada: 87,219.95
  stop protector vivo: 78,447.20 (6.1% bajo el precio)

COSTE DE ACTUAR
  ida y vuelta: 20 bps  ·  diferencial actual: 0.0012%
  una rotacion completa cuesta 0.20% del capital

MODELO CUANTITATIVO
  regimen detectado: 3 (alcista fuerte)  ·  P(long) = 0.560
  conviccion estructural: 0.5682  ·  retorno estructural esperado: 176.4 bps
  conviccion tactica: 0.5029  ·  retorno tactico esperado: -0.6 bps

ANALOGOS HISTORICOS (5 anios, situaciones mas parecidas)
  1. 2024-03-14  precio vs 200d +4.8%  vol 36.1%  ->  30d siguientes: +8.2%
  2. 2021-11-02  precio vs 200d +4.1%  vol 41.0%  ->  30d siguientes: -17.4%
  3. 2023-07-21  precio vs 200d +3.9%  vol 33.7%  ->  30d siguientes: +2.1%
  4. 2025-01-08  precio vs 200d +4.4%  vol 39.2%  ->  30d siguientes: -5.6%
  5. 2020-08-19  precio vs 200d +5.0%  vol 44.8%  ->  30d siguientes: +11.3%
  mediana de los analogos: +2.1%  ·  dispersion: alta

RESTRICCIONES
  solo spot, solo largo o efectivo, techo de caida 25%
  el stop vive en el exchange y puede forzar salida
"""

PROMPT = (
    "Eres el agente de exposicion. Decide la exposicion objetivo para BTCUSDT a partir del "
    "estado que sigue. Responde SOLO con el JSON del esquema.\n" + STATE_BLOCK
)


def one_call(
    timeout_s: float, *, think: bool = False, num_predict: int = 320
) -> tuple[float, dict[str, object] | None, str | None]:
    """Seconds elapsed, the parsed verdict, and an error description if it failed.

    `think` and `num_predict` mirror the two calls production actually makes: a cheap pass
    (think=False, 900) and, only when the verdict wants to move the book, a reasoning pass
    (think=True, 2500). The second is the one that timed out, so it is the one that sizes
    the timeout.
    """
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT}],
        "stream": False,
        "think": think,
        "format": SCHEMA,
        "options": {"temperature": 0.0, "num_predict": num_predict},
    }
    request = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = json.loads(response.read())
        elapsed = time.monotonic() - started
        content = body.get("message", {}).get("content", "")
        try:
            verdict = json.loads(content)
        except json.JSONDecodeError:
            return elapsed, None, f"respuesta no es JSON: {content[:120]}"
        # Ollama reports its own timings in nanoseconds; they separate prompt processing
        # from generation, which is what decides whether a longer timeout or a shorter
        # prompt is the right lever.
        verdict["_eval_count"] = body.get("eval_count")
        verdict["_prompt_eval_count"] = body.get("prompt_eval_count")
        verdict["_prompt_eval_s"] = (body.get("prompt_eval_duration") or 0) / 1e9
        verdict["_eval_s"] = (body.get("eval_duration") or 0) / 1e9
        return elapsed, verdict, None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return time.monotonic() - started, None, f"{type(error).__name__}: {error}"


def main(argv: list[str] | None = None) -> int:
    repeats = int((argv or ["3"])[0])
    print(f"sondeando {MODEL} en {ENDPOINT}  ·  {repeats} rondas  ·  tope {PROBE_TIMEOUT_S:.0f}s")
    print(f"prompt de {len(PROMPT):,} caracteres")
    print("cada ronda mide las DOS llamadas que hace produccion\n")

    cheap: list[float] = []
    dear: list[float] = []
    failures: list[str] = []
    details: list[dict[str, object]] = []

    for attempt in range(1, repeats + 1):
        for label, think, tokens, bucket in (
            ("barata (think=False, 900)", False, 900, cheap),
            ("razonada (think=True, 2500)", True, 2500, dear),
        ):
            elapsed, verdict, error = one_call(
                PROBE_TIMEOUT_S, think=think, num_predict=tokens
            )
            if error is not None:
                print(f"  {attempt}. {label:<30} FALLO tras {elapsed:7.1f}s  {error[:70]}")
                failures.append(f"{label}: {error}")
                continue
            assert verdict is not None
            bucket.append(elapsed)
            prompt_s = float(verdict.get("_prompt_eval_s") or 0.0)
            gen_s = float(verdict.get("_eval_s") or 0.0)
            queued = elapsed - prompt_s - gen_s
            print(
                f"  {attempt}. {label:<30} {elapsed:7.1f}s  "
                f"(cola {queued:6.1f}s + prompt {prompt_s:5.1f}s + gen {gen_s:6.1f}s, "
                f"{verdict.get('_eval_count')} tokens)"
            )
            details.append(
                {
                    "path": label,
                    "elapsed_s": elapsed,
                    "queued_s": queued,
                    "prompt_eval_s": prompt_s,
                    "eval_s": gen_s,
                    "generated_tokens": verdict.get("_eval_count"),
                }
            )

    samples = cheap + dear
    if not samples:
        print("\nNINGUNA llamada completo. El modelo no responde en absoluto; la cadencia")
        print("no es el problema y subir el timeout no lo arreglaria.")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(
            json.dumps({"model": MODEL, "samples": [], "failures": failures}, indent=2),
            encoding="utf-8",
        )
        return 1

    # A deliberation that wants to trade pays BOTH calls in sequence, so the thing the
    # cadence must clear is the sum, not either one.
    worst_call = max(samples)
    worst_round = (max(cheap) if cheap else 0.0) + (max(dear) if dear else 0.0)
    print("\n--- latencia medida ---")
    for name, bucket in (("barata", cheap), ("razonada", dear)):
        if bucket:
            print(
                f"  {name:<9} n={len(bucket)}  min {min(bucket):7.1f}s  "
                f"mediana {statistics.median(bucket):7.1f}s  max {max(bucket):7.1f}s"
            )
    print(f"  fallos {len(failures)}")
    print(f"  peor LLAMADA individual: {worst_call:.1f}s")
    print(f"  peor RONDA completa (barata + razonada): {worst_round:.1f}s")
    print()
    print("--- dimensionado ---")
    print("  produccion ANTES: timeout 600s por llamada  ·  cadencia 1800s")
    print(f"  la peor llamada observada es {worst_call / 600:.2f}x el timeout anterior")
    # Twice the worst observed call, because queueing against the live agent is the
    # dominant term and it is not bounded by anything measured here.
    recommended_timeout = max(900.0, worst_call * 2.0)
    recommended_cadence = max(recommended_timeout * 2.0 * 1.25, worst_round * 3.0)
    print(f"  timeout recomendado: {recommended_timeout:.0f}s  (2x la peor llamada)")
    print(
        f"  cadencia recomendada: {recommended_cadence:.0f}s "
        f"= {recommended_cadence / 60:.0f} min  (debe cubrir 2 llamadas con margen)"
    )

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        json.dumps(
            {
                "model": MODEL,
                "prompt_chars": len(PROMPT),
                "cheap_s": cheap,
                "reasoning_s": dear,
                "failed": len(failures),
                "worst_call_s": worst_call,
                "worst_round_s": worst_round,
                "recommended_timeout_s": recommended_timeout,
                "recommended_cadence_s": recommended_cadence,
                "samples": details,
                "failures": failures,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\ninforme: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
