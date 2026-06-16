# Auditoría — Whale Finder actual

## Objetivo

Auditar el `main.py` actual de Whale Finder para identificar qué partes se pueden reutilizar como base del futuro Smart Money Intelligence Engine v1.

## Estado actual

El archivo actual funciona como un worker monolítico. En un solo `main.py` concentra:

* configuración por variables de entorno;
* wallets activas hardcodeadas;
* normalización de trades;
* conexión a Polymarket Data API;
* fetch global de trades recientes;
* fetch histórico por wallet;
* deduplicación de trades;
* scoring básico por wallet;
* clasificación de wallet activa;
* revisión con OpenAI;
* discovery de candidatas;
* recomendaciones de reemplazo;
* escritura de outputs JSON;
* loop de worker.

## Funciones actuales de normalización

Funciones detectadas:

* `pick_wallet(activity)`
* `pick_market_id(activity)`
* `pick_timestamp(activity)`
* `normalize_title(title)`
* `is_short_term_noise_market(title)`
* `guess_category_from_title(title)`
* `normalize_activity(row)`

Campos reales usados desde Polymarket/Data API:

* wallet: `proxyWallet`, `wallet`, `user`, `address`, `trader`
* market id: `market`, `marketId`, `conditionId`, `condition_id`
* timestamp: `timestamp`, `time`, `createdAt`
* size: `usdcSize`, `size`, `amount`, `value`
* price: `price`
* side: `side`, `type`, `action`
* outcome: `outcome`, `answer`
* title: `title`, `marketTitle`, `slug`

## Outputs actuales reutilizables

El worker ya genera outputs útiles:

* `active_wallet_health.json`
* `all_scored_wallets_global.json`
* `all_scored_wallets_enriched.json`
* `global_candidates.json`
* `candidates.json`
* `replacement_recommendations.json`
* `run_summary.json`
* `state.json`

Estos outputs pueden alimentar parcialmente el Smart Money Engine, especialmente para wallet quality y clasificación inicial de wallets.

## Métricas actuales por wallet

El cálculo actual ya produce:

* `trade_count`
* `total_volume`
* `avg_size`
* `max_size`
* `unique_markets`
* `avg_price`
* `early_entries`
* `late_entries`
* `late_entry_ratio`
* `low_price_ratio`
* `sell_ratio`
* `extreme_price_volume_ratio`
* `opposing_market_count`
* `opposing_market_ratio`
* `concentration`
* `hard_flags`
* `score`
* `tier`
* `sample_trades`

Estas métricas sirven como base para `Wallet Quality Score v1`.

## Lo reutilizable para Smart Money Engine

Se puede reutilizar:

* normalización de trades;
* fetch global de trades;
* fetch por wallet;
* dedupe;
* cálculo de métricas por wallet;
* detección de opposing outcomes;
* detección de late entries;
* detección de precios extremos;
* hard flags;
* AI review opcional;
* outputs JSON.

## Limitaciones actuales

El `main.py` todavía no resuelve el objetivo completo de Estela de Capital porque:

* no genera lectura por mercado;
* no calcula `market_capital_trail`;
* no calcula `smart_bias`;
* no separa wallets calificadas vs ruidosas de forma formal;
* no persiste scores en Supabase;
* no tiene `Wallet Quality Score` con fórmula formal;
* no calcula `Market Capital Trail`;
* no tiene inferencia de mercados relacionados;
* no conecta con `markets.id` de DeepEngine;
* no produce `estela_capital_by_market.json`;
* no genera estados como `DIRECT_STRONG`, `DIRECT_WEAK`, `INFERRED_RELATED`, `CONTRADICTORY_FLOW`, `NO_RELIABLE_TRAIL`.

## Problema principal de arquitectura

El archivo es demasiado grande y mezcla responsabilidades:

* extracción de datos;
* normalización;
* scoring;
* clasificación;
* AI review;
* recomendaciones;
* storage;
* worker loop.

Para evolucionarlo, conviene separarlo en módulos y no seguir agregando lógica al mismo `main.py`.

## Separación recomendada

Crear nuevo módulo:

```txt
workers/smart_money/smart_money_engine/
  main.py
  config.py
  normalizers.py
  polymarket_client.py
  wallet_metrics.py
  wallet_classifier.py
  noise_filter.py
  market_trail.py
  consensus_engine.py
  related_markets.py
  storage.py
  outputs/
```

## Decisión de implementación

No modificar todavía el `whale_worker`.

El `whale_worker` debe seguir siendo recolector de alertas reales.

El nuevo `smart_money_engine` debe consumir datos existentes y producir interpretación:

* wallet quality;
* noise profile;
* capital trail por mercado;
* salida para Estela de Capital.

## Conclusión

El `main.py` actual sí sirve como base, pero no debe crecer más como archivo monolítico.

La siguiente etapa debe ser extraer sus piezas reutilizables hacia módulos separados y construir encima:

1. `Wallet Quality Score v1`
2. `Noise Filter v1`
3. `Market Capital Trail v1`
4. `estela_capital_by_market.json`

No implementar todavía Related Market Inference hasta tener estable la lectura directa.
