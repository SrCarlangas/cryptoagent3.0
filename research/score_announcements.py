"""Score Binance announcement titles with the LOCAL model, to close the narrative hypothesis.

`research/cross_section_ic.py` refuted the cheap numeric proxy: announcement COUNT carries no
cross-sectional information (90d t = -0.86, 180d t = -0.58, delisting t = +0.59, none reaching
one standard error on a corpus with 99% coverage). But a count cannot tell a new listing from a
delisting warning -- both are "one mention". That is precisely the gap a model can close, and
it is the last open hypothesis in this project.

Runs on the SERVER's `qwen3:30b-a3b` via Ollama on loopback. **Zero third-party tokens**, which
is the owner's standing constraint.

Design choices that matter:

- **Batched.** 30 titles per call instead of one, which turns ~3,300 calls into ~110. The task
  is extraction, not deliberation, so batching costs nothing in quality and saves hours of GPU.
- **Ollama structured output via `format`**, the same mechanism `OllamaClient` uses in
  production. A first attempt asked for compact pipe-delimited lines and the model answered with
  reasoning prose ("Okay, let's tackle this problem...") despite `think: false`. A schema does
  not request a shape, it constrains the decoder to it. A batch that still comes back unusable is
  RECORDED AS FAILED rather than silently skipped. This project has three measured incidents of a silent default
  producing a real-looking number; the count of failed batches is reported with the result.
- **Resumable.** Results append to disk after every batch, so a timeout loses one batch, not the
  run. The backtest taught that lesson at a cost of hours.
- **The model never sees prices or dates.** It reads a title and says what the title means for
  the asset. Anything else would leak outcome information into the feature.

What it extracts per title:
    asset   the ticker the announcement is ABOUT (or "" when it names none)
    impact  -2 strongly bad for that asset .. +2 strongly good, 0 neutral/irrelevant
    kind    listing | delisting | warning | maintenance | promo | other

Usage, on the server:
    PYTHONPATH=. .venv/bin/python research/score_announcements.py --limit 20     # muestra
    PYTHONPATH=. .venv/bin/python research/score_announcements.py               # completo
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

ENDPOINT = "http://127.0.0.1:11434/api/chat"
MODEL = "qwen3:30b-a3b"
SOURCE = Path("data/history/binance-announcements.json")
DEST = Path("data/validation/announcement-scores.json")
DEST_TEMPLATE = "data/validation/announcement-scores{suffix}.json"
BATCH = 25

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "asset": {"type": "string"},
                    "impact": {"type": "integer"},
                    "kind": {"type": "string"},
                },
                "required": ["i", "asset", "impact", "kind"],
            },
        }
    },
    "required": ["items"],
}

SYSTEM = """Eres un analista que clasifica titulares de anuncios de un exchange de criptomonedas.

Para cada titular numerado devuelves un objeto con:
  "i"      el numero del titular
  "asset"  el ticker del activo del que trata el anuncio, en mayusculas, sin el par
           (por ejemplo ADA, no ADAUSDT). Cadena vacia si no trata de un activo concreto
           o si trata de muchos a la vez.
  impacto  entero de -2 a 2: efecto ESPERADO del anuncio sobre ese activo.
           -2 muy malo (deslistado, retirada de pares, aviso de riesgo)
           -1 malo (suspension temporal, cambio restrictivo)
            0 neutro o irrelevante (mantenimiento rutinario, promocion generica)
           +1 bueno (nuevo par, mas margen, mas colateral)
           +2 muy bueno (listado nuevo en spot, inclusion destacada)
  kind     una de: listing, delisting, warning, maintenance, promo, other

Devuelve un objeto con la clave "items": una lista con un objeto por titular, en orden.
No expliques nada."""


class ScoringFailed(Exception):
    """A batch came back unusable. Recorded, never silently dropped."""


def ask(titles: list[tuple[int, str]], timeout_s: float) -> list[dict[str, Any]]:
    """Send one batch and parse it strictly."""
    listing = "\n".join(f"{index}. {title}" for index, title in titles)
    body = {
        "model": MODEL,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "options": {"temperature": 0, "num_predict": 48 * len(titles)},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": listing},
        ],
    }
    request = urllib.request.Request(
        ENDPOINT, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        payload = json.load(response)
    content = ((payload.get("message") or {}).get("content") or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-z]*\n?|```$", "", content).strip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ScoringFailed(f"JSON invalido: {error}; inicio={content[:160]!r}") from error
    rows = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list) or not rows:
        raise ScoringFailed(f"sin items utilizables; inicio={content[:160]!r}")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Score announcement titles with the local model.")
    parser.add_argument("--limit", type=int, default=0, help="Solo los primeros N titulares.")
    parser.add_argument(
        "--catalog",
        default="",
        help=(
            "Puntuar solo un catalogo (listing|delisting|maintenance). El corpus completo "
            "cuesta ~8h en esta maquina sin GPU, y la forma TRANSVERSAL de la hipotesis ya "
            "esta cerrada por densidad: el 93% de las celdas activo-periodo no tiene ningun "
            "anuncio, asi que ningun modelo puede ordenar 254 activos con informacion sobre 13. "
            "Lo que si sostienen los datos es un estudio de EVENTO, y el catalogo de deslistados "
            "es su subconjunto de mayor informacion."
        ),
    )
    parser.add_argument("--timeout", type=float, default=600.0)
    args = parser.parse_args()

    global DEST
    if args.catalog:
        DEST = Path(DEST_TEMPLATE.format(suffix=f"-{args.catalog}"))
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = []
    for kind, arts in raw.items():
        if args.catalog and kind != args.catalog:
            continue
        for art in arts:
            items.append({"t": art["t"], "title": art["title"], "catalog": kind})
    items.sort(key=lambda item: item["t"])
    if args.limit:
        items = items[: args.limit]
    print(f"titulares a puntuar: {len(items)}", flush=True)

    done: dict[str, Any] = {}
    if DEST.is_file():
        done = json.loads(DEST.read_text(encoding="utf-8"))
        print(f"reanudando: {len(done.get('scores', {}))} ya puntuados", flush=True)
    scores: dict[str, Any] = done.get("scores", {})
    failures: list[str] = done.get("failures", [])

    started = time.time()
    for start in range(0, len(items), BATCH):
        chunk = items[start : start + BATCH]
        if all(str(start + offset) in scores for offset in range(len(chunk))):
            continue
        numbered = [(start + offset, item["title"]) for offset, item in enumerate(chunk)]
        try:
            parsed = ask(numbered, args.timeout)
        except (ScoringFailed, OSError, TimeoutError) as error:
            failures.append(f"lote {start}: {error}")
            print(f"  lote {start}: FALLO {error}", flush=True)
            continue
        kept = 0
        for entry in parsed:
            try:
                index = int(entry["i"])
                impact = max(-2, min(2, int(entry.get("impact", 0))))
            except (KeyError, TypeError, ValueError):
                continue
            if not (start <= index < start + len(chunk)):
                continue
            item = items[index]
            scores[str(index)] = {
                "t": item["t"],
                "catalog": item["catalog"],
                "asset": str(entry.get("asset", "")).upper().strip()[:12],
                "impact": impact,
                "kind": str(entry.get("kind", "other")).lower().strip()[:16],
            }
            kept += 1
        if kept < len(chunk):
            failures.append(f"lote {start}: solo {kept}/{len(chunk)} titulares devueltos")
        elapsed = time.time() - started
        rate = (start + BATCH) / elapsed if elapsed > 0 else 0
        remaining = (len(items) - start - BATCH) / rate / 60 if rate > 0 else 0
        print(
            f"  {start + len(chunk)}/{len(items)}  lote ok {kept}/{len(chunk)}  "
            f"{rate * 60:.0f} titulares/min  quedan ~{remaining:.0f} min",
            flush=True,
        )
        DEST.parent.mkdir(parents=True, exist_ok=True)
        DEST.write_text(
            json.dumps({"model": MODEL, "scores": scores, "failures": failures}, indent=1),
            encoding="utf-8",
        )

    DEST.write_text(
        json.dumps({"model": MODEL, "scores": scores, "failures": failures}, indent=1),
        encoding="utf-8",
    )
    print(f"\npuntuados {len(scores)} de {len(items)}  ·  lotes con fallo: {len(failures)}")
    if failures:
        print("  (los fallos se reportan, no se ocultan; los primeros 3:)")
        for line in failures[:3]:
            print(f"    {line}")
    print(f"salida: {DEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
