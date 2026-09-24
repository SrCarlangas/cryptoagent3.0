# ADR-0001: stack y persistencia offline

- Estado: aceptado
- Fecha: 2026-09-15
- Decisión relacionada: D-011

## Contexto

El mandato autoriza únicamente implementación y validación offline. Se requieren contratos estrictos, aritmética decimal, concurrencia de ingestión futura, replay byte-determinista y persistencia auditable sin infraestructura externa.

## Decisión

- Runtime compatible con Python `>=3.12,<3.15`; validación inicial en CPython 3.14.3.
- `asyncio` sólo en adapters de ingestión; el dominio permanece síncrono y puro.
- Pydantic v2 para contratos frozen, enums cerrados y validación estricta.
- pytest, Hypothesis, Ruff y mypy strict con versiones exactas en `pyproject.toml`.
- Arquitectura hexagonal: dominio ← aplicación ← adapters. Las policies no importan transporte, persistencia ni simulación.
- Ledger local append-only en JSONL canónico UTF-8; cada línea contiene hash y payload. Escritura `flush` + `fsync`; duplicados son idempotentes y colisiones bloquean.
- Fixtures JSON versionados y replay con reloj inyectado. Ningún adapter se conecta automáticamente.

## Alternativas rechazadas

- Float: pierde exactitud contractual.
- Base de datos o broker obligatorio: añade estado operativo innecesario para fixtures/replay.
- Dependencia directa de Binance desde el dominio: viola portabilidad.
- Runtime global fijado a 3.12: innecesario; se conserva compatibilidad y se valida el runtime disponible.

## Consecuencias

JSONL prioriza auditabilidad y portabilidad sobre consultas complejas. La interfaz `DecisionLedger` permite sustituirlo sin cambiar el dominio. No hay credenciales, endpoints privados ni ejecución de órdenes.
