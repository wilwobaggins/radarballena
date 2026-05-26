# Whale Finder

Worker de Smart Money encargado de auditar wallets actuales y descubrir nuevas wallets candidatas.

## Responsabilidad

- Evaluar wallets activas.
- Buscar wallets nuevas en Polymarket.
- Calcular health score.
- Detectar wallets degradadas.
- Generar recomendaciones de reemplazo.

## No hace

- No crea alertas reales.
- No cambia wallets automáticamente.
- No actualiza producción sin aprobación manual.

## Outputs esperados

- `active_wallet_health.json`
- `global_candidates.json`
- `replacement_recommendations.json`

## Ejecución

```bash
python main.py