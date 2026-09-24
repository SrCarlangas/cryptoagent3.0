# Integración de ejecución en cuenta demo de Binance

**Fecha:** 2026-09-16  
**Origen:** portada y adaptada desde `cryptoagent2.0` (`/home/ubuntu/workplace/cryptoagent2.0`, servidor remoto), revisado por SSH de solo lectura. No se copiaron credenciales ni el `.env` remoto.

## Qué se trajo y cómo se adaptó

El proyecto anterior conecta a la cuenta demo vía `https://demo-api.binance.com/api` con `BINANCE_DEMO=true`, usando `python-binance` (`BinanceAdapter`). Aquí se reimplementó el mismo comportamiento respetando la arquitectura hexagonal y sin dependencias pesadas:

- **Puerto de ejecución** (`src/btc_decision_agent/application/execution.py`): interfaz `ExecutionPort` con `ticker_price`, `account_balance` y `place_market_quote_order`. El dominio nunca ejecuta por su cuenta; solo un adapter explícitamente habilitado actúa sobre una `Decision` ya registrada (record-before-export).
- **Adapter demo** (`src/btc_decision_agent/adapters/binance_execution.py`): cliente REST firmado (HMAC-SHA256) con stdlib + `certifi`, sin `python-binance`. Apunta a `demo-api.binance.com` (o `testnet.binance.vision`), nunca a producción.

## Diferencias deliberadas frente a cryptoagent2.0

- Sin `python-binance` ni `tenacity`: cliente REST propio, liviano y coherente con el backfill.
- Órdenes market por `quoteOrderQty` redondeado a 2 decimales (mismo fix del proyecto viejo para el error -1111 de precisión).
- `Decimal` en vez de `float` para montos y precios.

## Salvaguardas de seguridad

- **Real money bloqueado:** `ExecutionVenue.REAL` lanza `RealCapitalBlockedError` en construcción, en `base_url()`, en cada request y en la factory. Solo se permite `DEMO`/`TESTNET`.
- **Deshabilitado por defecto:** `enabled=False`; cualquier request lanza error hasta opt-in explícito.
- **Credenciales solo por entorno:** `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET`; nunca en código ni en el repo. Faltantes ⇒ fail-closed.
- **URL validada:** un override de `BINANCE_DEMO_REST_URL` debe ser https y apuntar a un endpoint no-real; en caso contrario, error.
- **Sin retiros:** el adapter solo consulta ticker/cuenta y coloca órdenes market; nunca llama withdrawals.

Cobertura: `tests/test_execution_adapter.py` prueba el bloqueo de venue real, el estado deshabilitado, URLs no-reales, credenciales faltantes, firma HMAC y rechazo de montos no positivos. Ningún test toca la red.

## Cómo operar en la demo (cuando decidas hacerlo)

1. Crea claves de API en `demo.binance.com` (cuenta demo, sin fondos reales).
2. Copia `.env.example` a `.env` (gitignored) y rellena `BINANCE_DEMO_API_KEY` / `BINANCE_DEMO_API_SECRET`.
3. Habilita el adapter en código con `build_demo_adapter(enabled=True)` o `BinanceDemoExecutionAdapter(enabled=True)`.
4. El adapter traduce una `Decision ENTER_LONG`/`EXIT_LONG` en una orden market demo por el notional aprobado por el `RiskGovernor`.

Nada de esto habilita capital real: para eso haría falta una fase separada, una estrategia que supere el gate y tu autorización explícita.

## Estado

Adapter implementado, validado (67 tests, ruff, mypy verdes) y **sin conectar todavía**: no se colocó ninguna orden demo ni se cargaron credenciales. El siguiente paso operativo requiere tus claves de demo y tu visto bueno para una corrida en vivo.
